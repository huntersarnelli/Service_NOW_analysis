"""
Media-sentiment mean-reversion backtest library
===============================================

Matches live dashboard rules (app.py / data/market.py):
  Entry : Z-score < Z_ENTRY  (default -1.5)
  Optional technical filter: Close > TREND_SMA
  Stop  : trail = Close - ATR_MULT * ATR  (only raised)
  Exit  : trail hit OR Z > Z_EXIT (default 0)

Media layer is INFORMATIONAL research — not wired into the live app.
Daily media scores default to a reproducible *simulator* (Alpha Vantage
NEWS_SENTIMENT-style scale in [-1, +1]). Swap in real history later via
`load_or_simulate_media(...)` or by assigning columns on the price frame.

Notebook usage
--------------
    from studies.media_backtest_lib import (
        UNIVERSE, download_ohlcv, prepare_frame, run_backtest,
        VARIANT_SPECS, run_multi_variant_study, summarize_trades,
    )
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

# ─────────────────────────────────────────────────────────────
# Defaults (aligned with app / production notebooks)
# ─────────────────────────────────────────────────────────────
Z_ENTRY = -1.5
Z_EXIT = 0.0
ATR_MULT = 2.0
SMA_WINDOW = 20
ATR_WINDOW = 14
TREND_SMA = 50
START_CAPITAL = 1_000.0

MOMENTUM_BUCKET = ["NVDA", "META", "NET"]
QUALITY_BUCKET = ["NOW", "MSFT", "GOOGL", "PANW", "CRWD", "DDOG", "CRM"]
UNIVERSE = MOMENTUM_BUCKET + QUALITY_BUCKET

DEFAULT_START = "2020-01-01"


# ─────────────────────────────────────────────────────────────
# Market data + indicators
# ─────────────────────────────────────────────────────────────
def download_ohlcv(
    ticker: str,
    start: str = DEFAULT_START,
    end: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """Download OHLCV via yfinance; returns None if insufficient data."""
    try:
        df = yf.download(
            ticker,
            start=start,
            end=end,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty:
            return None
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        out = df[cols].dropna().copy()
        out.index = pd.to_datetime(out.index).tz_localize(None)
        if len(out) < 80:
            return None
        return out
    except Exception:
        return None


def add_indicators(
    df: pd.DataFrame,
    sma_window: int = SMA_WINDOW,
    atr_window: int = ATR_WINDOW,
    trend_sma: int = TREND_SMA,
) -> pd.DataFrame:
    """Z-score, ATR, trend SMA — same construction as the live app."""
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
    out["daily_ret"] = out["Close"].pct_change()

    # Forward returns for event / filter research (not used for PnL)
    for h in (5, 10, 21):
        out[f"fwd_{h}d"] = out["Close"].shift(-h) / out["Close"] - 1.0

    # Realized vol proxy for regime splits
    out["rv_21"] = out["daily_ret"].rolling(21).std() * np.sqrt(252)
    return out


# ─────────────────────────────────────────────────────────────
# Media score simulation (AV-style [-1, +1])
# ─────────────────────────────────────────────────────────────
def _seed_for(ticker: str, salt: str = "media") -> int:
    h = hashlib.md5(f"{ticker}:{salt}".encode()).hexdigest()
    return int(h[:8], 16)


def simulate_daily_media(
    index: pd.DatetimeIndex,
    ticker: str,
    price: Optional[pd.Series] = None,
    corr_to_returns: float = 0.15,
) -> pd.DataFrame:
    """
    Build a reproducible daily media panel on the trading calendar.

    Columns
    -------
    media_raw       : latent daily score in [-1, 1]
    media_label     : Bullish / Somewhat Bullish / Neutral / ...
    media_7d        : rolling 7-session mean
    media_30d       : rolling 30-session mean
    media_badge_7d  : Good / Neutral / Bad  (same thresholds as dashboard)

    Notes for later real-data swap
    ------------------------------
    Replace `media_raw` with the average Alpha Vantage ticker_sentiment_score
    of articles published that day (or NaN → ffill with a research policy).
    Then recompute media_7d / media_30d identically.
    """
    n = len(index)
    rng = np.random.default_rng(_seed_for(ticker))

    # Mean-reverting AR(1) around a mild ticker-specific bias
    center = float(rng.uniform(-0.05, 0.12))
    x = center
    raw = np.empty(n)
    for i in range(n):
        x = 0.88 * x + 0.12 * center + float(rng.normal(0, 0.09))
        raw[i] = x

    # Optional weak coupling to lagged returns (so filters can matter)
    if price is not None and len(price) == n:
        rets = price.pct_change().fillna(0.0).to_numpy()
        # standardize
        r = (rets - rets.mean()) / (rets.std() + 1e-9)
        raw = (1 - corr_to_returns) * raw + corr_to_returns * np.clip(r, -2, 2) * 0.35

    raw = np.clip(raw, -1.0, 1.0)
    s = pd.Series(raw, index=index, name="media_raw")
    out = pd.DataFrame(
        {
            "media_raw": s,
            "media_7d": s.rolling(7, min_periods=3).mean(),
            "media_30d": s.rolling(30, min_periods=10).mean(),
        },
        index=index,
    )
    out["media_label"] = out["media_raw"].map(score_to_label)
    out["media_badge_7d"] = out["media_7d"].map(media_badge)
    out["media_badge_30d"] = out["media_30d"].map(media_badge)
    return out


def score_to_label(score: float) -> str:
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return "Neutral"
    if score <= -0.35:
        return "Bearish"
    if score < -0.15:
        return "Somewhat Bearish"
    if score <= 0.15:
        return "Neutral"
    if score < 0.35:
        return "Somewhat Bullish"
    return "Bullish"


def media_badge(score: float) -> str:
    """Dashboard-aligned Good / Neutral / Bad."""
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return "Neutral"
    if score > 0.15:
        return "Good"
    if score < -0.15:
        return "Bad"
    return "Neutral"


def load_or_simulate_media(
    df: pd.DataFrame,
    ticker: str,
    real_media: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Attach media columns to a price frame.

    Parameters
    ----------
    real_media : optional DataFrame indexed by date with at least `media_raw`.
                 If provided, used instead of the simulator (research path for
                 Alpha Vantage history dumps or your own scraper).
    """
    out = df.copy()
    if real_media is not None and not real_media.empty:
        m = real_media.copy()
        m.index = pd.to_datetime(m.index).tz_localize(None)
        if "media_raw" not in m.columns:
            raise ValueError("real_media must include column 'media_raw'")
        raw = m["media_raw"].reindex(out.index)
        # Research default: limited ffill so weekends/gaps don't zero the filter
        raw = raw.ffill(limit=3)
        out["media_raw"] = raw
        out["media_7d"] = out["media_raw"].rolling(7, min_periods=3).mean()
        out["media_30d"] = out["media_raw"].rolling(30, min_periods=10).mean()
        out["media_label"] = out["media_raw"].map(score_to_label)
        out["media_badge_7d"] = out["media_7d"].map(media_badge)
        out["media_badge_30d"] = out["media_30d"].map(media_badge)
    else:
        sim = simulate_daily_media(out.index, ticker, price=out["Close"])
        for c in sim.columns:
            out[c] = sim[c]
    return out


# ─────────────────────────────────────────────────────────────
# Earnings proximity (yfinance; soft-fail to empty)
# ─────────────────────────────────────────────────────────────
def fetch_earnings_dates(ticker: str, start: str = DEFAULT_START) -> pd.DatetimeIndex:
    """Announcement dates if available; else empty index."""
    try:
        t = yf.Ticker(ticker)
        ed = None
        if hasattr(t, "get_earnings_dates"):
            ed = t.get_earnings_dates(limit=40)
        if ed is None or getattr(ed, "empty", True):
            return pd.DatetimeIndex([])
        dates = pd.to_datetime(ed.index)
        if getattr(dates, "tz", None) is not None:
            dates = dates.tz_convert("UTC").tz_localize(None)
        dates = pd.DatetimeIndex(dates).normalize()
        start_ts = pd.Timestamp(start)
        return dates[dates >= start_ts].unique().sort_values()
    except Exception:
        return pd.DatetimeIndex([])


def add_earnings_flags(
    df: pd.DataFrame,
    earnings_dates: pd.DatetimeIndex,
    pre_days: int = 5,
    post_days: int = 1,
) -> pd.DataFrame:
    """
    near_earnings = True if session is within [earn - pre_days, earn + post_days].
    Useful for avoid-earnings media variants.
    """
    out = df.copy()
    out["near_earnings"] = False
    if earnings_dates is None or len(earnings_dates) == 0:
        return out
    idx = out.index
    mask = pd.Series(False, index=idx)
    for ed in earnings_dates:
        lo = ed - pd.Timedelta(days=pre_days)
        hi = ed + pd.Timedelta(days=post_days)
        mask |= (idx >= lo) & (idx <= hi)
    out["near_earnings"] = mask
    return out


def prepare_frame(
    ticker: str,
    start: str = DEFAULT_START,
    end: Optional[str] = None,
    real_media: Optional[pd.DataFrame] = None,
    include_earnings: bool = True,
) -> Optional[pd.DataFrame]:
    """Full research frame: OHLCV + indicators + media + earnings flags."""
    raw = download_ohlcv(ticker, start=start, end=end)
    if raw is None:
        return None
    df = add_indicators(raw)
    df = load_or_simulate_media(df, ticker, real_media=real_media)
    if include_earnings:
        ed = fetch_earnings_dates(ticker, start=start)
        df = add_earnings_flags(df, ed)
    else:
        df["near_earnings"] = False
    df.attrs["ticker"] = ticker
    return df


# ─────────────────────────────────────────────────────────────
# Entry filter builders (media / trend / earnings)
# ─────────────────────────────────────────────────────────────
EntryFilter = Callable[[pd.DataFrame, int], tuple[bool, str]]


def filter_always_ok(df: pd.DataFrame, i: int) -> tuple[bool, str]:
    return True, "ok"


def filter_trend_50(df: pd.DataFrame, i: int) -> tuple[bool, str]:
    row = df.iloc[i]
    if pd.isna(row.get("trend_sma")):
        return False, "trend_sma_nan"
    if row["Close"] > row["trend_sma"]:
        return True, "trend_ok"
    return False, "trend_fail"


def make_media_min_filter(col: str, threshold: float, name: str) -> EntryFilter:
    def _f(df: pd.DataFrame, i: int) -> tuple[bool, str]:
        v = df.iloc[i].get(col)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return False, f"{name}_nan"
        if float(v) >= threshold:
            return True, f"{name}>={threshold:.2f}"
        return False, f"{name}_below"

    return _f


def make_media_badge_filter(col: str = "media_badge_7d", allow: tuple[str, ...] = ("Good", "Neutral")) -> EntryFilter:
    allowed = set(allow)

    def _f(df: pd.DataFrame, i: int) -> tuple[bool, str]:
        b = df.iloc[i].get(col, "Neutral")
        if b in allowed:
            return True, f"badge_{b}"
        return False, f"badge_block_{b}"

    return _f


def make_avoid_earnings_filter(base: Optional[EntryFilter] = None) -> EntryFilter:
    base = base or filter_always_ok

    def _f(df: pd.DataFrame, i: int) -> tuple[bool, str]:
        ok, reason = base(df, i)
        if not ok:
            return ok, reason
        if bool(df.iloc[i].get("near_earnings", False)):
            return False, "near_earnings"
        return True, reason + "+earn_clear"

    return _f


def make_composite_filter(
    media_col: str = "media_7d",
    media_weight: float = 0.35,
    z_scale: float = 1.5,
    composite_min: float = 0.0,
) -> EntryFilter:
    """
    Composite score after Z trigger fires (Z already required by engine):
      score = (-z / z_scale) + media_weight * media
    More negative Z and higher media → higher score.
    """

    def _f(df: pd.DataFrame, i: int) -> tuple[bool, str]:
        row = df.iloc[i]
        z = row.get("zscore")
        m = row.get(media_col)
        if z is None or pd.isna(z) or m is None or pd.isna(m):
            return False, "composite_nan"
        score = (-float(z) / z_scale) + media_weight * float(m)
        if score >= composite_min:
            return True, f"composite={score:.2f}"
        return False, f"composite_low={score:.2f}"

    return _f


def combine_filters(*filters: EntryFilter) -> EntryFilter:
    def _f(df: pd.DataFrame, i: int) -> tuple[bool, str]:
        reasons = []
        for fn in filters:
            ok, reason = fn(df, i)
            reasons.append(reason)
            if not ok:
                return False, "+".join(reasons)
        return True, "+".join(reasons)

    return _f


# ─────────────────────────────────────────────────────────────
# Core backtest engine
# ─────────────────────────────────────────────────────────────
@dataclass
class BacktestResult:
    ticker: str
    variant: str
    equity: pd.Series
    trades: pd.DataFrame
    metrics: dict[str, Any]
    daily: pd.DataFrame = field(repr=False)


def run_backtest(
    df: pd.DataFrame,
    ticker: str = "?",
    variant: str = "baseline",
    z_entry: float = Z_ENTRY,
    z_exit: float = Z_EXIT,
    atr_mult: float = ATR_MULT,
    start_capital: float = START_CAPITAL,
    entry_filter: Optional[EntryFilter] = None,
    warmup: int = 60,
) -> BacktestResult:
    """
    All-in / all-out mean reversion with trailing ATR stop.

    Position is applied with a 1-bar lag on returns (enter/exit at close,
    PnL from next bar) — same convention as your testing notebooks.
    """
    entry_filter = entry_filter or filter_always_ok
    data = df.copy()
    n = len(data)
    position = np.zeros(n, dtype=float)

    in_trade = False
    stop_price = 0.0
    entry_price = 0.0
    entry_date = None
    entry_i = 0
    entry_z = np.nan
    entry_media_7d = np.nan
    entry_media_30d = np.nan
    entry_reason = ""
    trades: list[dict] = []

    for i in range(warmup, n):
        row = data.iloc[i]
        z = row["zscore"]
        close = float(row["Close"])
        atr = row["atr"]
        date = data.index[i]

        if any(pd.isna(x) for x in (z, atr, close)) or atr <= 0:
            position[i] = 1.0 if in_trade else 0.0
            continue

        if not in_trade:
            if z < z_entry:
                ok, reason = entry_filter(data, i)
                if ok:
                    in_trade = True
                    entry_price = close
                    stop_price = close - atr_mult * atr
                    entry_date = date
                    entry_i = i
                    entry_z = float(z)
                    entry_media_7d = float(row["media_7d"]) if pd.notna(row.get("media_7d")) else np.nan
                    entry_media_30d = float(row["media_30d"]) if pd.notna(row.get("media_30d")) else np.nan
                    entry_reason = reason
                    position[i] = 1.0
                else:
                    position[i] = 0.0
            else:
                position[i] = 0.0
        else:
            new_stop = close - atr_mult * atr
            if new_stop > stop_price:
                stop_price = new_stop

            exit_reason = None
            if close < stop_price:
                exit_reason = "trail_stop"
            elif z > z_exit:
                exit_reason = "mean_revert_z"

            if exit_reason:
                ret = close / entry_price - 1.0
                # Forward returns from entry bar (research)
                fwd = {}
                for h in (5, 10, 21):
                    col = f"fwd_{h}d"
                    fwd[col] = (
                        float(data.iloc[entry_i][col])
                        if col in data.columns and pd.notna(data.iloc[entry_i][col])
                        else np.nan
                    )
                trades.append(
                    {
                        "ticker": ticker,
                        "variant": variant,
                        "entry_date": entry_date,
                        "exit_date": date,
                        "entry_price": entry_price,
                        "exit_price": close,
                        "return_pct": ret * 100.0,
                        "days_held": (date - entry_date).days if entry_date is not None else 0,
                        "entry_z": entry_z,
                        "exit_z": float(z),
                        "entry_media_7d": entry_media_7d,
                        "entry_media_30d": entry_media_30d,
                        "entry_filter_reason": entry_reason,
                        "exit_reason": exit_reason,
                        "fwd_5d": fwd.get("fwd_5d", np.nan) * 100 if pd.notna(fwd.get("fwd_5d", np.nan)) else np.nan,
                        "fwd_10d": fwd.get("fwd_10d", np.nan) * 100 if pd.notna(fwd.get("fwd_10d", np.nan)) else np.nan,
                        "fwd_21d": fwd.get("fwd_21d", np.nan) * 100 if pd.notna(fwd.get("fwd_21d", np.nan)) else np.nan,
                        "entry_rv_21": float(row["rv_21"]) if pd.notna(row.get("rv_21")) else np.nan,
                    }
                )
                # fix entry_rv at entry
                trades[-1]["entry_rv_21"] = (
                    float(data.iloc[entry_i]["rv_21"])
                    if pd.notna(data.iloc[entry_i].get("rv_21"))
                    else np.nan
                )
                in_trade = False
                position[i] = 0.0
            else:
                position[i] = 1.0

    data["position"] = position
    data["strat_ret"] = data["position"].shift(1) * data["daily_ret"]
    data["equity"] = start_capital * (1 + data["strat_ret"].fillna(0)).cumprod()
    data["bh_equity"] = start_capital * (1 + data["daily_ret"].fillna(0)).cumprod()

    trades_df = pd.DataFrame(trades)
    metrics = compute_metrics(data["equity"], data["bh_equity"], trades_df, start_capital)

    return BacktestResult(
        ticker=ticker,
        variant=variant,
        equity=data["equity"],
        trades=trades_df,
        metrics=metrics,
        daily=data,
    )


def compute_metrics(
    equity: pd.Series,
    bh_equity: pd.Series,
    trades_df: pd.DataFrame,
    start_capital: float = START_CAPITAL,
) -> dict[str, Any]:
    final = float(equity.iloc[-1]) if len(equity) else start_capital
    bh_final = float(bh_equity.iloc[-1]) if len(bh_equity) else start_capital
    days = max((equity.index[-1] - equity.index[0]).days, 1) if len(equity) > 1 else 1
    years = days / 365.25
    cagr = (final / start_capital) ** (1 / years) - 1 if years > 0 and final > 0 else 0.0
    max_dd = float((equity / equity.cummax() - 1).min()) if len(equity) else 0.0

    # Sharpe-like on strategy daily returns
    rets = equity.pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if len(rets) > 5 and rets.std() > 0 else np.nan

    n_tr = len(trades_df)
    if n_tr > 0:
        win_rate = float((trades_df["return_pct"] > 0).mean())
        avg_trade = float(trades_df["return_pct"].mean())
        winners = trades_df.loc[trades_df["return_pct"] > 0, "return_pct"]
        losers = trades_df.loc[trades_df["return_pct"] <= 0, "return_pct"]
        avg_win = float(winners.mean()) if len(winners) else np.nan
        avg_loss = float(losers.mean()) if len(losers) else np.nan
        avg_hold = float(trades_df["days_held"].mean())
        fwd5 = float(trades_df["fwd_5d"].mean()) if "fwd_5d" in trades_df else np.nan
        fwd10 = float(trades_df["fwd_10d"].mean()) if "fwd_10d" in trades_df else np.nan
        fwd21 = float(trades_df["fwd_21d"].mean()) if "fwd_21d" in trades_df else np.nan
    else:
        win_rate = avg_trade = avg_win = avg_loss = avg_hold = np.nan
        fwd5 = fwd10 = fwd21 = np.nan

    return {
        "final_equity": final,
        "total_return_pct": (final / start_capital - 1) * 100,
        "cagr": cagr,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "bh_final": bh_final,
        "beats_bh": final > bh_final,
        "num_trades": n_tr,
        "win_rate": win_rate,
        "avg_trade_pct": avg_trade,
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "avg_days_held": avg_hold,
        "fwd_5d_mean": fwd5,
        "fwd_10d_mean": fwd10,
        "fwd_21d_mean": fwd21,
    }


# ─────────────────────────────────────────────────────────────
# Variant catalog
# ─────────────────────────────────────────────────────────────
def default_variant_specs() -> dict[str, EntryFilter]:
    """Named media/technical filters to compare side-by-side."""
    return {
        "baseline": filter_always_ok,
        "trend50": filter_trend_50,
        "media7d_neutral+": make_media_min_filter("media_7d", -0.15, "media7d"),
        "media7d_gt0": make_media_min_filter("media_7d", 0.0, "media7d"),
        "media7d_gt015": make_media_min_filter("media_7d", 0.15, "media7d"),
        "media30d_neutral+": make_media_min_filter("media_30d", -0.15, "media30d"),
        "media30d_gt0": make_media_min_filter("media_30d", 0.0, "media30d"),
        "badge7d_not_bad": make_media_badge_filter("media_badge_7d", ("Good", "Neutral")),
        "badge7d_good_only": make_media_badge_filter("media_badge_7d", ("Good",)),
        "avoid_earnings": make_avoid_earnings_filter(filter_always_ok),
        "media7d_gt0_no_earn": make_avoid_earnings_filter(
            make_media_min_filter("media_7d", 0.0, "media7d")
        ),
        "composite_z_media": make_composite_filter("media_7d", 0.35, 1.5, 0.0),
        "trend50_media7d_gt0": combine_filters(
            filter_trend_50, make_media_min_filter("media_7d", 0.0, "media7d")
        ),
    }


VARIANT_SPECS = default_variant_specs()  # mutable alias for notebooks


def run_all_variants_one_ticker(
    df: pd.DataFrame,
    ticker: str,
    variants: Optional[dict[str, EntryFilter]] = None,
    **bt_kwargs,
) -> list[BacktestResult]:
    variants = variants or default_variant_specs()
    results = []
    for name, filt in variants.items():
        results.append(
            run_backtest(df, ticker=ticker, variant=name, entry_filter=filt, **bt_kwargs)
        )
    return results


def results_to_frame(results: list[BacktestResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        row = {"ticker": r.ticker, "variant": r.variant, **r.metrics}
        rows.append(row)
    return pd.DataFrame(rows)


def run_multi_variant_study(
    tickers: list[str] = UNIVERSE,
    start: str = DEFAULT_START,
    end: Optional[str] = None,
    variants: Optional[dict[str, EntryFilter]] = None,
    verbose: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    """
    Full multi-stock × multi-variant study.

    Returns
    -------
    summary : one row per ticker × variant
    all_trades : concatenated trade logs
    frames : ticker -> prepared DataFrame (for further EDA)
    """
    variants = variants or default_variant_specs()
    summary_rows: list[BacktestResult] = []
    trade_parts: list[pd.DataFrame] = []
    frames: dict[str, pd.DataFrame] = {}

    for i, t in enumerate(tickers, 1):
        if verbose:
            print(f"[{i}/{len(tickers)}] {t} …")
        df = prepare_frame(t, start=start, end=end)
        if df is None:
            if verbose:
                print(f"  skip {t} (no data)")
            continue
        frames[t] = df
        for res in run_all_variants_one_ticker(df, t, variants=variants):
            summary_rows.append(res)
            if len(res.trades):
                trade_parts.append(res.trades)

    summary = results_to_frame(summary_rows)
    all_trades = pd.concat(trade_parts, ignore_index=True) if trade_parts else pd.DataFrame()
    return summary, all_trades, frames


def portfolio_equal_weight_equity(
    results: list[BacktestResult],
    start_capital: float = START_CAPITAL,
) -> pd.Series:
    """Average normalized equity across tickers for one variant."""
    series_list = []
    for r in results:
        eq = r.equity / start_capital
        series_list.append(eq)
    if not series_list:
        return pd.Series(dtype=float)
    panel = pd.concat(series_list, axis=1).ffill().fillna(1.0)
    port = panel.mean(axis=1) * start_capital
    port.name = results[0].variant if results else "portfolio"
    return port


def split_period_metrics(
    trades: pd.DataFrame,
    equity: pd.Series,
    start_capital: float = START_CAPITAL,
    split_date: str = "2025-01-01",
) -> pd.DataFrame:
    """Compare trade stats before/after a regime split date."""
    if trades is None or trades.empty:
        return pd.DataFrame()
    split = pd.Timestamp(split_date)
    rows = []
    for label, mask in [
        ("pre_" + split_date[:4], pd.to_datetime(trades["entry_date"]) < split),
        ("post_" + split_date[:4], pd.to_datetime(trades["entry_date"]) >= split),
    ]:
        sub = trades.loc[mask]
        if sub.empty:
            rows.append({"period": label, "num_trades": 0})
            continue
        rows.append(
            {
                "period": label,
                "num_trades": len(sub),
                "win_rate": (sub["return_pct"] > 0).mean(),
                "avg_trade_pct": sub["return_pct"].mean(),
                "fwd_5d_mean": sub["fwd_5d"].mean() if "fwd_5d" in sub else np.nan,
                "fwd_10d_mean": sub["fwd_10d"].mean() if "fwd_10d" in sub else np.nan,
                "fwd_21d_mean": sub["fwd_21d"].mean() if "fwd_21d" in sub else np.nan,
            }
        )
    return pd.DataFrame(rows)


def rank_variants(summary: pd.DataFrame, by: str = "final_equity") -> pd.DataFrame:
    """Average metrics across tickers per variant, ranked."""
    if summary.empty:
        return summary
    g = (
        summary.groupby("variant", as_index=False)
        .agg(
            mean_final=("final_equity", "mean"),
            median_final=("final_equity", "median"),
            mean_cagr=("cagr", "mean"),
            mean_max_dd=("max_dd", "mean"),
            mean_sharpe=("sharpe", "mean"),
            mean_win_rate=("win_rate", "mean"),
            total_trades=("num_trades", "sum"),
            mean_fwd_10d=("fwd_10d_mean", "mean"),
            tickers=("ticker", "count"),
            beats_bh_count=("beats_bh", "sum"),
        )
        .sort_values(by if by in ("mean_final",) else "mean_final", ascending=False)
    )
    # map by alias
    if by == "final_equity":
        g = g.sort_values("mean_final", ascending=False)
    elif by == "cagr":
        g = g.sort_values("mean_cagr", ascending=False)
    elif by == "sharpe":
        g = g.sort_values("mean_sharpe", ascending=False)
    g.insert(0, "rank", range(1, len(g) + 1))
    return g


def media_forward_correlation(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Correlation of media scores with forward returns (pooled)."""
    parts = []
    for t, df in frames.items():
        cols = ["media_raw", "media_7d", "media_30d", "fwd_5d", "fwd_10d", "fwd_21d"]
        sub = df[cols].dropna().copy()
        sub["ticker"] = t
        parts.append(sub)
    if not parts:
        return pd.DataFrame()
    panel = pd.concat(parts, ignore_index=True)
    rows = []
    for mcol in ("media_raw", "media_7d", "media_30d"):
        for fcol in ("fwd_5d", "fwd_10d", "fwd_21d"):
            rows.append(
                {
                    "media": mcol,
                    "forward": fcol,
                    "corr": panel[mcol].corr(panel[fcol]),
                    "n": len(panel),
                }
            )
    return pd.DataFrame(rows)


def vol_regime_trade_stats(trades: pd.DataFrame, rv_cut: Optional[float] = None) -> pd.DataFrame:
    """Split trades into high/low vol at entry using median RV if cut not given."""
    if trades is None or trades.empty or "entry_rv_21" not in trades.columns:
        return pd.DataFrame()
    t = trades.dropna(subset=["entry_rv_21"]).copy()
    if t.empty:
        return pd.DataFrame()
    cut = rv_cut if rv_cut is not None else float(t["entry_rv_21"].median())
    t["vol_regime"] = np.where(t["entry_rv_21"] >= cut, "high_vol", "low_vol")
    return (
        t.groupby(["variant", "vol_regime"], as_index=False)
        .agg(
            n=("return_pct", "count"),
            win_rate=("return_pct", lambda s: (s > 0).mean()),
            avg_ret=("return_pct", "mean"),
            fwd_10d=("fwd_10d", "mean"),
        )
        .sort_values(["variant", "vol_regime"])
    )


def threshold_sweep(
    df: pd.DataFrame,
    ticker: str,
    media_col: str = "media_7d",
    thresholds: Optional[list[float]] = None,
) -> pd.DataFrame:
    """Grid of media thresholds for one ticker (EDA helper)."""
    thresholds = thresholds or [-0.30, -0.15, 0.0, 0.10, 0.15, 0.25]
    rows = []
    base = run_backtest(df, ticker=ticker, variant="baseline", entry_filter=filter_always_ok)
    rows.append({"threshold": None, "variant": "baseline", **base.metrics})
    for th in thresholds:
        res = run_backtest(
            df,
            ticker=ticker,
            variant=f"{media_col}>={th}",
            entry_filter=make_media_min_filter(media_col, th, media_col),
        )
        rows.append({"threshold": th, "variant": res.variant, **res.metrics})
    return pd.DataFrame(rows)


def summarize_trades(trades: pd.DataFrame, n: int = 12) -> None:
    if trades is None or trades.empty:
        print("No trades.")
        return
    print(f"Trades: {len(trades)} | Win% {(trades['return_pct']>0).mean()*100:.1f}% | "
          f"Avg {trades['return_pct'].mean():.2f}%")
    cols = [
        c
        for c in [
            "ticker",
            "variant",
            "entry_date",
            "exit_date",
            "return_pct",
            "days_held",
            "entry_media_7d",
            "entry_filter_reason",
            "exit_reason",
        ]
        if c in trades.columns
    ]
    print(trades[cols].tail(n).to_string(index=False))


# ─────────────────────────────────────────────────────────────
# Plotting helpers — same visual language as testing/test2.ipynb
# ─────────────────────────────────────────────────────────────
def print_performance_block(
    result: BacktestResult,
    z_entry: float = Z_ENTRY,
    atr_mult: float = ATR_MULT,
    start_capital: float = START_CAPITAL,
    header: Optional[str] = None,
) -> None:
    """
    Console report matching testing/test2.ipynb exactly:

        ============================================================
        WINNING STRATEGY: Z < -1.5 + 2.0×ATR Trailing Stop
        ============================================================
        Starting Capital : $1,000
        ...
    """
    m = result.metrics
    final_value = m["final_equity"]
    if header is None:
        header = f"WINNING STRATEGY: Z < {z_entry} + {atr_mult}×ATR Trailing Stop"

    print("=" * 60)
    print(header)
    print("=" * 60)
    print(f"Starting Capital : ${start_capital:,.0f}")
    print(f"Final Value      : ${final_value:,.0f}")
    print(f"Total Return     : {(final_value / start_capital - 1) * 100:.1f}%")
    print(f"CAGR             : {m['cagr'] * 100:.1f}%")
    print(f"Max Drawdown     : {m['max_dd'] * 100:.1f}%")
    print(f"Number of Trades : {m['num_trades']}")
    print("=" * 60)

    trades_df = result.trades
    if trades_df is not None and len(trades_df) > 0:
        print("\nTrade Summary:")
        print(f"  Win rate       : {(trades_df['return_pct'] > 0).mean() * 100:.1f}%")
        print(f"  Avg trade      : {trades_df['return_pct'].mean():.2f}%")
        print(
            f"  Avg winner     : "
            f"{trades_df.loc[trades_df['return_pct'] > 0, 'return_pct'].mean():.2f}%"
        )
        print(
            f"  Avg loser      : "
            f"{trades_df.loc[trades_df['return_pct'] <= 0, 'return_pct'].mean():.2f}%"
        )
        print(f"  Avg days held  : {trades_df['days_held'].mean():.1f}")
        print("\nLast 8 trades:")
        # Prefer the same simple columns as test2; append media cols if present
        cols = [
            c
            for c in [
                "entry_date",
                "exit_date",
                "entry_price",
                "exit_price",
                "return_pct",
                "days_held",
                "entry_media_7d",
                "exit_reason",
            ]
            if c in trades_df.columns
        ]
        print(trades_df[cols].tail(8).to_string(index=False))


def plot_equity_vs_buyhold(
    result: BacktestResult,
    title: Optional[str] = None,
    z_entry: float = Z_ENTRY,
    atr_mult: float = ATR_MULT,
    start_capital: float = START_CAPITAL,
    figsize: tuple[int, int] = (14, 7),
):
    """
    Equity chart matching testing/test2.ipynb:

        plt.figure(figsize=(14, 7))
        plt.plot(equity, label=f'Strategy (${final:,.0f})', color='green', lw=2)
        plt.plot(..., label='Buy & Hold', color='black', alpha=0.6)
        plt.title(..., fontsize=14)
        plt.ylabel('Portfolio Value ($)')
        plt.legend(); plt.grid(True, alpha=0.3); plt.show()
    """
    import matplotlib.pyplot as plt

    eq = result.equity
    daily = result.daily
    final_value = float(eq.iloc[-1])

    # Same B&H construction as the testing notebook
    if "daily_ret" in daily.columns:
        bh_vals = start_capital * (1 + daily["daily_ret"].fillna(0)).cumprod()
        bh_index = daily.index
    elif "bh_equity" in daily.columns:
        bh_vals = daily["bh_equity"]
        bh_index = daily.index
    else:
        bh_vals = eq * np.nan
        bh_index = eq.index

    if title is None:
        title = f"{result.ticker} Best Strategy — Z<{z_entry} + {atr_mult}×ATR Trail"

    plt.figure(figsize=figsize)
    plt.plot(
        eq.index,
        eq.values,
        label=f"Strategy (${final_value:,.0f})",
        color="green",
        lw=2,
    )
    plt.plot(
        bh_index,
        bh_vals,
        label="Buy & Hold",
        color="black",
        alpha=0.6,
    )
    plt.title(title, fontsize=14)
    plt.ylabel("Portfolio Value ($)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    return plt.gcf()


def plot_variant_equities(
    curves: dict[str, pd.Series],
    title: str = "Strategy comparison",
    buyhold: Optional[pd.Series] = None,
    figsize: tuple[int, int] = (15, 8),
    highlight: Optional[str] = "baseline",
):
    """
    Multi-strategy overlay like the test2 comparison cell:
    top variants on one chart, optional B&H in black dashed/gray.
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=figsize)
    for name, series in curves.items():
        if series is None or len(series) == 0:
            continue
        final = float(series.iloc[-1])
        lw = 2.5 if highlight and name == highlight else 2.0
        color = "green" if highlight and name == highlight else None
        ax.plot(
            series.index,
            series.values,
            label=f"{name} (${final:,.0f})",
            lw=lw,
            color=color,
        )
    if buyhold is not None and len(buyhold):
        ax.plot(
            buyhold.index,
            buyhold.values,
            label=f"Buy & Hold (${float(buyhold.iloc[-1]):,.0f})",
            color="black",
            alpha=0.55,
            lw=1.5,
        )
    ax.set_title(title, fontsize=14)
    ax.set_ylabel("Portfolio Value ($)")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_threshold_sweep(
    sweep_7: pd.DataFrame,
    sweep_30: pd.DataFrame,
    title: str = "Media threshold vs final equity",
    figsize: tuple[int, int] = (14, 7),
):
    """Threshold grid in the same clean matplotlib style."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=figsize)
    s7 = sweep_7.dropna(subset=["threshold"])
    s30 = sweep_30.dropna(subset=["threshold"])
    if len(s7):
        ax.plot(
            s7["threshold"],
            s7["final_equity"],
            "o-",
            color="green",
            lw=2,
            label="media_7d threshold",
        )
    if len(s30):
        ax.plot(
            s30["threshold"],
            s30["final_equity"],
            "s-",
            color="steelblue",
            lw=2,
            label="media_30d threshold",
        )
    base = sweep_7.loc[sweep_7["threshold"].isna(), "final_equity"]
    if len(base):
        ax.axhline(
            float(base.iloc[0]),
            ls="--",
            color="black",
            alpha=0.6,
            label=f"baseline (${float(base.iloc[0]):,.0f})",
        )
    ax.set_xlabel("Minimum media score to allow entry")
    ax.set_ylabel("Portfolio Value ($)")
    ax.set_title(title, fontsize=14)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig
