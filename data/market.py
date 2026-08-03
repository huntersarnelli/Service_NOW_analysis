"""
Market data, indicators, and live strategy levels.

Extracted from the Streamlit app so the same logic can be reused in notebooks:

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


def get_data(ticker: str, days: int = HISTORY_DAYS) -> Optional[pd.DataFrame]:
    """Download OHLCV history for a single ticker via yfinance."""
    end = datetime.now().date() + timedelta(days=1)
    start = end - timedelta(days=days)
    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty:
            return None
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        return df[cols].dropna().copy()
    except Exception:
        return None


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


def get_levels(
    ticker: str,
    use_filter: bool,
    z_entry: float,
    atr_mult: float,
    sma_window: int,
    atr_window: int,
    trend_sma: int,
) -> Optional[dict]:
    """
    Compute live levels and signal for one ticker.

    Exact strategy logic:
      buy_trigger = SMA + z_entry * std
      initial_stop (if buy at trigger) = buy_trigger - atr_mult * ATR
      mean_exit   = SMA  (Z > 0)
      signal      = (Z < z_entry) and (trend_ok if use_filter else True)
      trail       = Close - atr_mult * ATR  (raised only when in a trade)

    When use_filter is False (the default), trend_ok is always True and
    the N-SMA is still computed for display / comparison only.
    """
    # Always compute a positive-length trend SMA for charts/tables, even when
    # the filter is off. Filter application is controlled only by use_filter.
    trend_sma_len = max(int(trend_sma), 1)
    min_bars = max(60, sma_window + 5, atr_window + 5, trend_sma_len + 5)
    df = get_data(ticker)
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

    # Default strategy: no trend gate. Filter only when use_filter is True.
    trend_ok = True
    if use_filter and not np.isnan(trend_sma_val):
        trend_ok = close > trend_sma_val

    signal = (z < z_entry) and trend_ok
    dist_pct = (close - buy_trigger) / close * 100.0
    dist_dollar = close - buy_trigger
    risk = buy_trigger - initial_stop
    reward = mean_exit - buy_trigger
    rr = (reward / risk) if risk > 0 else float("nan")

    # Proximity tiers for UI
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
        "history": df,
    }


def scan_bucket(
    tickers: list[str],
    use_filter: bool,
    z_entry: float,
    atr_mult: float,
    sma_window: int,
    atr_window: int,
    trend_sma: int,
    bucket_name: str,
) -> list[dict]:
    """Scan a list of tickers and attach a bucket label to each result."""
    rows = []
    for t in tickers:
        info = get_levels(
            t, use_filter, z_entry, atr_mult, sma_window, atr_window, trend_sma
        )
        if info:
            info["bucket"] = bucket_name
            rows.append(info)
    return rows
