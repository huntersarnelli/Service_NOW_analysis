"""
Market data, indicators, and live strategy levels.

Shared by both strategies (see data/strategies.py) and reusable in notebooks:

    from data.market import get_data, compute_indicators, get_levels, scan_bucket

NOTE: get_levels / scan_bucket implement the live BUY / NEAR / WATCH logic.
Do not couple media sentiment or earnings into these functions unless you
intentionally change the strategy.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

# ─────────────────────────────────────────────────────────────
# Universe & defaults used by the dashboard
# ─────────────────────────────────────────────────────────────
HISTORY_DAYS = 180

MOMENTUM_BUCKET = ["NVDA", "META", "NET"]
QUALITY_BUCKET = ["NOW", "MSFT", "GOOGL", "PANW", "CRWD", "DDOG", "CRM"]
ALL_TICKERS = MOMENTUM_BUCKET + QUALITY_BUCKET

# Aggressive Dip universe (was hard-coded in aggressive_dip_dashboard.py)
DIP_BUCKET = ["META", "NVDA", "NET", "DDOG"]

# Every symbol either strategy can ask for.
UNIVERSE = list(dict.fromkeys(ALL_TICKERS + DIP_BUCKET))

_OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def required_history_days(
    sma_window: int,
    atr_window: int,
    trend_sma: int,
    extra_bars: int = 40,
) -> int:
    """
    Calendar days needed to guarantee `max(window) + extra_bars` *trading* bars.

    The old code fetched a flat 180 calendar days (~124 trading bars) while the
    sidebar allowed a 200-bar trend SMA, so every ticker silently returned None
    and the dashboard went blank. Always size the request to the widest window.
    """
    need_bars = max(int(sma_window), int(atr_window), int(trend_sma)) + int(extra_bars)
    calendar = int(need_bars * 1.6) + 30  # trading days -> calendar days, + slack
    return max(HISTORY_DAYS, calendar)


def _clean(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    cols = [c for c in _OHLCV if c in df.columns]
    if "Close" not in cols:
        return None
    out = df[cols].dropna(subset=["Close"]).copy()
    if out.empty:
        return None
    out.index = pd.to_datetime(out.index)
    if getattr(out.index, "tz", None) is not None:
        out.index = out.index.tz_localize(None)
    return out


def get_data(ticker: str, days: int = HISTORY_DAYS) -> Optional[pd.DataFrame]:
    """Download OHLCV history for a single ticker via yfinance."""
    end = datetime.now().date() + timedelta(days=1)
    start = end - timedelta(days=int(days))
    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        )
        return _clean(df)
    except Exception:
        return None


def get_data_batch(
    tickers: list[str],
    days: int = HISTORY_DAYS,
) -> dict[str, pd.DataFrame]:
    """
    Download every ticker in ONE yfinance request.

    The old scan issued a separate download per symbol (10 sequential round
    trips). Batching is ~10x fewer requests, which also matters a great deal
    when running from a datacenter IP where Yahoo throttles hard.
    """
    tickers = [t for t in dict.fromkeys(tickers) if t]
    if not tickers:
        return {}

    end = datetime.now().date() + timedelta(days=1)
    start = end - timedelta(days=int(days))
    try:
        raw = yf.download(
            tickers,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
    except Exception:
        return {}

    if raw is None or raw.empty:
        return {}

    out: dict[str, pd.DataFrame] = {}
    multi = isinstance(raw.columns, pd.MultiIndex)
    for t in tickers:
        try:
            frame = raw[t] if multi else raw
        except KeyError:
            continue
        cleaned = _clean(frame)
        if cleaned is not None:
            out[t] = cleaned
    return out


def compute_indicators(
    df: pd.DataFrame,
    sma_window: int,
    atr_window: int,
    trend_sma: int,
) -> pd.DataFrame:
    """Add SMA, std, Z-score, trend SMA, and ATR columns."""
    out = df.copy()
    out["sma"] = out["Close"].rolling(sma_window).mean()
    out["std"] = out["Close"].rolling(sma_window).std()
    out["zscore"] = (out["Close"] - out["sma"]) / out["std"]
    out["trend_sma"] = out["Close"].rolling(trend_sma).mean()

    tr = pd.concat(
        [
            out["High"] - out["Low"],
            (out["High"] - out["Close"].shift(1)).abs(),
            (out["Low"] - out["Close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(atr_window).mean()
    return out


def levels_from_frame(
    ticker: str,
    df: pd.DataFrame,
    use_filter: bool,
    z_entry: float,
    atr_mult: float,
    sma_window: int,
    atr_window: int,
    trend_sma: int,
) -> Optional[dict]:
    """
    Compute live levels and signal from an already-downloaded OHLCV frame.

    Exact strategy logic:
      buy_trigger = SMA + z_entry * std
      initial_stop (if buy at trigger) = buy_trigger - atr_mult * ATR
      mean_exit   = SMA  (Z > 0)
      signal      = (Z < z_entry) and (trend_ok if use_filter else True)
      trail       = Close - atr_mult * ATR  (raised only when in a trade)

    When use_filter is False (the default), trend_ok is always True and
    the N-SMA is still computed for display / comparison only.
    """
    trend_sma_len = max(int(trend_sma), 1)
    min_bars = max(60, sma_window + 5, atr_window + 5, trend_sma_len + 5)
    if df is None or len(df) < min_bars:
        return None

    df = compute_indicators(df, sma_window, atr_window, trend_sma_len)
    last = df.iloc[-1]

    close = float(last["Close"])
    sma = float(last["sma"])
    std = float(last["std"])
    atr = float(last["atr"])
    z = float(last["zscore"])
    trend_sma_val = (
        float(last["trend_sma"]) if pd.notna(last["trend_sma"]) else float("nan")
    )

    if any(np.isnan(x) for x in (sma, std, atr, z)) or std == 0:
        return None

    buy_trigger = sma + (z_entry * std)
    initial_stop = buy_trigger - (atr_mult * atr)
    mean_exit = sma
    trail_now = close - (atr_mult * atr)

    trend_ok = True
    if use_filter and not np.isnan(trend_sma_val):
        trend_ok = close > trend_sma_val

    signal = (z < z_entry) and trend_ok
    dist_pct = (close - buy_trigger) / close * 100.0
    dist_dollar = close - buy_trigger
    risk = buy_trigger - initial_stop
    reward = mean_exit - buy_trigger
    rr = (reward / risk) if risk > 0 else float("nan")

    if signal:
        status = "BUY"
    elif dist_pct < 5:
        status = "NEAR"
    elif dist_pct < 12:
        status = "WATCH"
    else:
        status = "FAR"

    return {
        "ticker": ticker,
        "close": close,
        "z": z,
        "sma20": sma,
        "std": std,
        "atr": atr,
        "trend_sma": trend_sma_val,
        "trend_sma_len": trend_sma_len,
        "buy_trigger": buy_trigger,
        "initial_stop": initial_stop,
        "mean_exit": mean_exit,
        "trail_now": trail_now,
        "trend_ok": trend_ok,
        "use_filter": use_filter,
        "signal": signal,
        "status": status,
        "dist_pct": dist_pct,
        "dist_dollar": dist_dollar,
        "risk": risk,
        "reward": reward,
        "rr": rr,
        "last_bar_date": df.index[-1],
        "history": df,
    }


def get_levels(
    ticker: str,
    use_filter: bool,
    z_entry: float,
    atr_mult: float,
    sma_window: int,
    atr_window: int,
    trend_sma: int,
) -> Optional[dict]:
    """Download + compute live levels for one ticker (single-symbol path)."""
    days = required_history_days(sma_window, atr_window, trend_sma)
    df = get_data(ticker, days=days)
    if df is None:
        return None
    return levels_from_frame(
        ticker, df, use_filter, z_entry, atr_mult, sma_window, atr_window, trend_sma
    )


def scan_bucket(
    tickers: list[str],
    use_filter: bool,
    z_entry: float,
    atr_mult: float,
    sma_window: int,
    atr_window: int,
    trend_sma: int,
    bucket_name: str,
    frames: Optional[dict[str, pd.DataFrame]] = None,
) -> list[dict]:
    """
    Scan a list of tickers and attach a bucket label to each result.

    Pass `frames` (from get_data_batch) to avoid one download per ticker.
    """
    rows = []
    for t in tickers:
        if frames is not None:
            df = frames.get(t)
            info = (
                levels_from_frame(
                    t, df, use_filter, z_entry, atr_mult,
                    sma_window, atr_window, trend_sma,
                )
                if df is not None
                else None
            )
        else:
            info = get_levels(
                t, use_filter, z_entry, atr_mult, sma_window, atr_window, trend_sma
            )
        if info:
            info = dict(info)
            info["bucket"] = bucket_name
            rows.append(info)
    return rows


def get_earnings_dates(ticker: str, limit: int = 16) -> list:
    """Past + upcoming earnings dates (used by the Aggressive Dip sizing rule)."""
    try:
        ed = yf.Ticker(ticker).get_earnings_dates(limit=limit)
        if ed is None or len(ed) == 0:
            return []
        dates = []
        for idx in ed.index:
            ts = pd.Timestamp(idx)
            if ts.tz is not None:
                ts = ts.tz_localize(None)
            dates.append(ts.normalize())
        return sorted(set(dates))
    except Exception:
        return []


def get_earnings_batch(tickers: list[str], limit: int = 16) -> dict[str, list]:
    return {t: get_earnings_dates(t, limit=limit) for t in tickers}
