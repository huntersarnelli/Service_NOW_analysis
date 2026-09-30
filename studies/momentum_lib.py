"""
Momentum study library (docs/05_MOMENTUM_STUDY.md). Rules are fixed in §3 of that
doc; this file implements them and nothing else.

Monthly panels are built from the insider-trading repo's cached daily prices:
  adj     month-end adjusted close (returns)
  traded  month-end as-traded close (the $5 floor)
  dv20    20-day average dollar volume at month-end (liquidity ranking)
  last    date of the last trade in the month (to skip stocks that stopped trading)
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

PRICE_CACHE = Path(os.environ.get("MOMENTUM_PRICE_CACHE",
                                  r"C:\Users\hunte\insider-trading\data\raw\prices"))
FUNDS = {"SPY", "QQQ"}
MIN_PRICE = 5.0
UNIVERSE_SIZE = 200
TOP_N = 20
COST_PER_SIDE = 0.001  # 0.10%
N_RANDOM = 200
STALE_DAYS = 7  # last trade must be within 7 calendar days of month-end


def reverting_spikes(adj: np.ndarray) -> int:
    """One-day moves >= 4x up or <= -75% that return within 50% of the prior price inside 5 days."""
    ratio = adj[1:] / adj[:-1]
    count = 0
    for day in np.flatnonzero((ratio >= 4.0) | (ratio <= 0.25)):
        after = adj[day + 2: day + 7]
        if len(after) and np.any(np.abs(after / adj[day] - 1) < 0.5):
            count += 1
    return count


def monthly_rows(history: pd.DataFrame) -> pd.DataFrame:
    """Collapse one ticker's daily history to one row per calendar month."""
    h = history.sort_values("date").drop_duplicates("date").set_index("date")
    h["dv20"] = (h["close"] * h["volume"]).rolling(20).mean()
    h["month"] = h.index.to_period("M")
    last = h.groupby("month").tail(1)
    return pd.DataFrame({"adj": last["adj_close"].to_numpy(), "traded": last["close_as_traded"].to_numpy(),
                         "dv20": last["dv20"].to_numpy(), "last": last.index.to_numpy()},
                        index=last["month"].to_numpy())


def load_panels(cache_dir: Path = PRICE_CACHE) -> tuple[dict[str, pd.DataFrame], dict]:
    """Monthly panels (months x tickers) plus a log of what was loaded / excluded."""
    columns = {"adj": {}, "traded": {}, "dv20": {}, "last": {}}
    log = {"files": 0, "bad_print_tickers": [], "funds_kept_as_benchmarks": []}
    for path in sorted(Path(cache_dir).glob("px_*.parquet")):
        ticker = path.stem[3:]
        history = pd.read_parquet(path)
        log["files"] += 1
        if history.empty or len(history) < 30:
            continue
        if ticker not in FUNDS and reverting_spikes(history.sort_values("date")["adj_close"].to_numpy()) > 0:
            log["bad_print_tickers"].append(ticker)
            continue
        rows = monthly_rows(history)
        for key in columns:
            columns[key][ticker] = rows[key]
        if ticker in FUNDS:
            log["funds_kept_as_benchmarks"].append(ticker)
    panels = {key: pd.DataFrame(series).sort_index() for key, series in columns.items()}
    return panels, log


def eligible_universe(panels: dict, month: pd.Period, allowed: set | None = None,
                      size: int = UNIVERSE_SIZE) -> list[str]:
    """§3 eligibility at month-end t, then the `size` most-traded names (all of them if size=None)."""
    adj, traded, dv20, last = (panels[k] for k in ("adj", "traded", "dv20", "last"))
    t12 = month - 12
    if t12 not in adj.index:
        return []
    row_ok = (
        adj.loc[month].notna() & adj.loc[t12].notna() & adj.loc[month - 1].notna()
        & (traded.loc[month] >= MIN_PRICE) & dv20.loc[month].notna()
    )
    month_end = month.to_timestamp(how="end").normalize()
    fresh = pd.to_datetime(last.loc[month]) >= month_end - pd.Timedelta(days=STALE_DAYS)
    ok = row_ok & fresh
    ok = ok[ok].index.difference(list(FUNDS))
    if allowed is not None:
        ok = ok.intersection(list(allowed))
    ranked = dv20.loc[month, ok].sort_values(ascending=False)
    return list(ranked.index if size is None else ranked.index[:size])


def momentum_scores(panels: dict, month: pd.Period, names: list[str]) -> pd.Series:
    """12-1 momentum: return from month-end t-12 to month-end t-1."""
    adj = panels["adj"]
    return adj.loc[month - 1, names] / adj.loc[month - 12, names] - 1


def next_month_returns(panels: dict, month: pd.Period, names: list[str]) -> tuple[pd.Series, int]:
    """Return from month-end t to the last price in month t+1. Missing -> 0% (count returned)."""
    adj = panels["adj"]
    nxt = month + 1
    if nxt not in adj.index:
        return pd.Series(np.nan, index=names), len(names)
    returns = adj.loc[nxt, names] / adj.loc[month, names] - 1
    missing = int(returns.isna().sum())
    return returns.fillna(0.0), missing


def turnover(previous: list[str], current: list[str]) -> float:
    """Share of the portfolio replaced (1.0 for the first month)."""
    if not previous:
        return 1.0
    return len(set(current) - set(previous)) / len(current)


def max_drawdown(monthly_returns: pd.Series) -> float:
    wealth = (1 + monthly_returns.fillna(0)).cumprod()
    return float((wealth / wealth.cummax() - 1).min() * 100)


def t_stat(values: np.ndarray) -> float:
    values = values[~np.isnan(values)]
    if len(values) < 3 or values.std(ddof=1) == 0:
        return float("nan")
    return float(values.mean() / (values.std(ddof=1) / np.sqrt(len(values))))
