"""
Scoreboard — did the calls work? Every call is scored against QQQ (the "just buy
the Nasdaq-100" alternative) at 20 and 60 trading days after the decision.

Three groups:
  Your buys          your-call stocks you chose to buy     (want: beats QQQ)
  Your passes        your-call stocks you chose to skip    (want: LAGS QQQ — good pass)
  Buy-zone signals   every 🟢 Buy zone stock, logged automatically by the app

Honest limits: until ~30 calls are scored, averages are mostly noise. The simple
t-statistic here treats calls as independent; calls made in the same week are
not, so read it as optimistic.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

BUY_ZONE_DOC = "buy_zone_log"
HORIZONS = (20, 60)
BENCHMARK = "QQQ"
MIN_CALLS_FOR_VERDICT = 30


# ─────────────────────────────────────────────────────────────
# Buy-zone signal log (written automatically by the app)
# ─────────────────────────────────────────────────────────────
def load_buy_zone_log(store) -> list[dict]:
    """Buy-zone signals — kept in the SHARED store (the screen is the same for everyone)."""
    return (store.get(BUY_ZONE_DOC) or {}).get("signals", [])


def log_buy_zone(qualifying_rows: list[dict], store) -> int:
    """Record today's buy-zone stocks once per (ticker, bar date). Returns how many were new."""
    signals = load_buy_zone_log(store)
    known = {(s["ticker"], s["date"]) for s in signals}
    added = 0
    for r in qualifying_rows:
        bar = pd.Timestamp(r["last_bar"]).date().isoformat()
        if (r["ticker"], bar) in known:
            continue
        signals.append({"ticker": r["ticker"], "date": bar, "price": float(r["close"])})
        known.add((r["ticker"], bar))
        added += 1
    if added:
        store.put(BUY_ZONE_DOC, {"schema": 1, "updated_at": datetime.now().isoformat(timespec="seconds"),
                                 "signals": signals})
    return added


# ─────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────
def score_call(ticker: str, start_date: str, frames: dict[str, pd.DataFrame], horizon: int,
               benchmark: str = BENCHMARK) -> dict:
    """Return vs benchmark from the close on/before start_date to `horizon` bars later.

    status: 'scored' (horizon reached), 'pending' (return so far), or 'no data'.
    """
    stock, bench = frames.get(ticker), frames.get(benchmark)
    if stock is None or stock.empty or bench is None or bench.empty:
        return {"status": "no data"}
    start = pd.Timestamp(start_date)
    close = stock["Close"]
    position = int(close.index.searchsorted(start, side="right")) - 1
    if position < 0:
        return {"status": "no data"}
    elapsed = len(close) - 1 - position
    end = position + min(horizon, elapsed)
    start_day, end_day = close.index[position], close.index[end]
    bench_close = bench["Close"]
    b_start = bench_close.asof(start_day)
    b_end = bench_close.asof(end_day)
    stock_return = (close.iloc[end] / close.iloc[position] - 1) * 100
    bench_return = (b_end / b_start - 1) * 100 if pd.notna(b_start) and pd.notna(b_end) else np.nan
    return {"status": "scored" if elapsed >= horizon else "pending", "days": min(horizon, elapsed),
            "return": float(stock_return), "benchmark": float(bench_return),
            "edge": float(stock_return - bench_return) if pd.notna(bench_return) else np.nan}


def score_table(calls: list[dict], frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """calls: dicts with group, ticker, date (+ optional note). One row per call, 20d and 60d."""
    rows = []
    for call in calls:
        row = {"Group": call["group"], "Stock": call["ticker"], "Date": call["date"],
               "Note": call.get("note", "")}
        for h in HORIZONS:
            s = score_call(call["ticker"], call["date"], frames, h)
            row[f"{h}d status"] = s["status"] if s["status"] != "pending" else f"pending ({s['days']}d)"
            row[f"{h}d vs QQQ"] = s.get("edge", np.nan)
        rows.append(row)
    return pd.DataFrame(rows)


def verdict(edges: np.ndarray, group: str) -> str:
    n = len(edges)
    if n < MIN_CALLS_FOR_VERDICT:
        return f"Too early — {n} of ~{MIN_CALLS_FOR_VERDICT} calls scored"
    mean, sd = edges.mean(), edges.std(ddof=1)
    t = mean / (sd / np.sqrt(n)) if sd > 0 else np.nan
    good = mean < 0 if group == "Your passes" else mean > 0
    if good and abs(t) >= 2:
        return "Working" + (" — your passes lag QQQ" if group == "Your passes" else " — beats QQQ")
    if good:
        return "Leaning the right way, not convincing yet"
    return "Not working so far"


def summarise(table: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for group in ["Your buys", "Your passes", "Buy-zone signals"]:
        sub = table[table["Group"] == group] if not table.empty else table
        row = {"Group": group, "Calls": len(sub)}
        for h in HORIZONS:
            scored = sub[sub[f"{h}d status"] == "scored"][f"{h}d vs QQQ"].dropna().to_numpy() \
                if not sub.empty else np.array([])
            row[f"Scored {h}d"] = len(scored)
            row[f"Avg vs QQQ {h}d"] = float(scored.mean()) if len(scored) else np.nan
            row[f"Beat QQQ {h}d"] = float((scored > 0).mean() * 100) if len(scored) else np.nan
        scored_20 = sub[sub["20d status"] == "scored"]["20d vs QQQ"].dropna().to_numpy() \
            if not sub.empty else np.array([])
        row["Verdict (20d)"] = verdict(scored_20, group)
        rows.append(row)
    return pd.DataFrame(rows)


def build_calls(decisions: list, buy_zone_signals: list[dict]) -> list[dict]:
    calls = [{"group": "Your buys" if d.action == "buy" else "Your passes", "ticker": d.ticker,
              "date": d.decided_on, "note": d.thesis} for d in decisions]
    calls += [{"group": "Buy-zone signals", "ticker": s["ticker"], "date": s["date"], "note": ""}
              for s in buy_zone_signals]
    return calls
