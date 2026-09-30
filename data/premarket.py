"""
Pre-market / after-hours moves for the morning brief. INFORMATION ONLY.

One yfinance request with prepost=True returns 5-minute bars from 4:00am to 8:00pm ET
(futures trade nearly 24h). For each ticker we compare the latest extended-hours
price with the right reference close:

  pre-market (before 9:30)  -> vs the previous session's close
  market open               -> vs the previous session's close
  after hours (after 16:00) -> vs today's close

A pre-market gap is where to LOOK, not a tested signal: decisions still go through
the buy-zone rules or your logged Buy / Pass.
"""

from __future__ import annotations

from datetime import time as dtime

import pandas as pd
import yfinance as yf

FUTURES = {"ES=F": "S&P 500 futures", "NQ=F": "Nasdaq-100 futures"}
OPEN, CLOSE = dtime(9, 30), dtime(16, 0)
BIG_MOVE_PCT = 2.0  # your stocks moving at least this much outside market hours are listed


def session_label(ts: pd.Timestamp) -> str:
    t = ts.time()
    if t < OPEN:
        return "pre-market"
    if t < CLOSE:
        return "market open"
    return "after hours"


def move_since_close(bars: pd.Series) -> dict:
    """Latest price vs the right reference close (see module docstring)."""
    bars = bars.dropna()
    if bars.empty:
        return {"price": float("nan"), "move_pct": float("nan"), "session": "", "as_of": None}
    latest_time, latest = bars.index[-1], float(bars.iloc[-1])
    regular = bars[[OPEN <= ts.time() < CLOSE for ts in bars.index]]
    label = session_label(latest_time)
    if label == "after hours":
        reference = regular[regular.index.date <= latest_time.date()]
    else:
        reference = regular[regular.index.date < latest_time.date()]
    if reference.empty:
        return {"price": latest, "move_pct": float("nan"), "session": label, "as_of": latest_time}
    ref = float(reference.iloc[-1])
    return {"price": latest, "move_pct": (latest / ref - 1) * 100, "session": label,
            "as_of": latest_time, "reference_close": ref}


def fetch_moves(tickers: list[str]) -> pd.DataFrame:
    """One row per ticker: latest extended-hours price, % move vs reference close, session, as-of time."""
    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        return pd.DataFrame()
    try:
        raw = yf.download(tickers, period="5d", interval="5m", prepost=True, group_by="ticker",
                          progress=False, auto_adjust=True, threads=True)
    except Exception:  # noqa: BLE001
        return pd.DataFrame()
    rows = []
    for ticker in tickers:
        try:
            closes = raw[ticker]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
        except KeyError:
            continue
        info = move_since_close(closes)
        rows.append({"ticker": ticker, **info})
    return pd.DataFrame(rows)
