"""
Paper-trade log for the insider fast trade (H10). Every signal that passes the
H10 rules is logged — you don't pick — and its outcome is filled in from prices:

    entry      open of the entry day (or close, for filings made during market hours)
    same day   entry-day close (open entries only)        backtest: +0.48pp vs SPY
    next day   close one trading day after entry          backtest: +0.69pp vs SPY

Compare the live numbers with the backtest after ~30 trades before using real money.
Stored in portfolio_data/paper_trades.json (gitignored).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

PAPER_PATH = Path(__file__).resolve().parent.parent / "portfolio_data" / "paper_trades.json"
BACKTEST_SAME_DAY_EDGE = 0.48  # pp vs SPY, H10 open entries (insider-trading repo)
BACKTEST_NEXT_DAY_EDGE = 0.69  # pp vs SPY, H10 all entries


@dataclass
class PaperTrade:
    accession: str
    ticker: str
    insider: str
    role: str
    value_usd: float
    accepted: str  # ISO, Eastern
    entry_date: str
    entry_type: str  # "open" or "close"
    tested_sector: bool
    logged_on: str = field(default_factory=lambda: date.today().isoformat())
    status: str = "pending"  # pending -> filled
    entry_price: Optional[float] = None
    same_day_return: Optional[float] = None  # %, open entries only
    same_day_spy: Optional[float] = None
    next_day_return: Optional[float] = None  # %
    next_day_spy: Optional[float] = None
    next_day_qqq: Optional[float] = None


def load_trades(path: Path = PAPER_PATH) -> list[PaperTrade]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    fields = PaperTrade.__dataclass_fields__
    return [PaperTrade(**{k: v for k, v in rec.items() if k in fields})
            for rec in payload.get("trades", []) if isinstance(rec, dict)]


def save_trades(trades: list[PaperTrade], path: Path = PAPER_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": 1, "updated_at": datetime.now().isoformat(timespec="seconds"),
               "trades": [asdict(t) for t in trades]}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def add_signals(scan_results: pd.DataFrame, path: Path = PAPER_PATH) -> int:
    """Log every passing signal not already logged (by accession). Returns how many were added."""
    if scan_results is None or scan_results.empty:
        return 0
    trades = load_trades(path)
    known = {t.accession for t in trades}
    added = 0
    for row in scan_results[scan_results["passes"]].itertuples(index=False):
        if row.accession in known:
            continue
        trades.append(PaperTrade(
            accession=row.accession, ticker=row.ticker, insider=row.insider, role=row.role,
            value_usd=float(row.value_usd), accepted=row.accepted, entry_date=row.entry_date,
            entry_type=row.entry_type, tested_sector=bool(row.tested_sector)))
        known.add(row.accession)
        added += 1
    save_trades(trades, path)
    return added


def _bar(frame: Optional[pd.DataFrame], day: pd.Timestamp) -> Optional[int]:
    if frame is None or frame.empty or day not in frame.index:
        return None
    return int(frame.index.get_loc(day))


def fill_outcomes(trades: list[PaperTrade], frames: dict[str, pd.DataFrame]) -> int:
    """Fill prices/returns for trades whose entry (and next) day now exist. Returns how many changed."""
    spy, qqq = frames.get("SPY"), frames.get("QQQ")
    changed = 0
    for t in trades:
        if t.status == "filled":
            continue
        frame = frames.get(t.ticker)
        day = pd.Timestamp(t.entry_date)
        i, s = _bar(frame, day), _bar(spy, day)
        if i is None or s is None:
            continue
        price_col = "Open" if t.entry_type == "open" else "Close"
        t.entry_price = float(frame[price_col].iloc[i])
        if t.entry_type == "open":
            t.same_day_return = (float(frame["Close"].iloc[i]) / t.entry_price - 1) * 100
            t.same_day_spy = (float(spy["Close"].iloc[s]) / float(spy["Open"].iloc[s]) - 1) * 100
        if i + 1 < len(frame) and s + 1 < len(spy):
            t.next_day_return = (float(frame["Close"].iloc[i + 1]) / t.entry_price - 1) * 100
            t.next_day_spy = (float(spy["Close"].iloc[s + 1]) / float(spy[price_col].iloc[s]) - 1) * 100
            q = _bar(qqq, day)
            if q is not None and q + 1 < len(qqq):
                t.next_day_qqq = (float(qqq["Close"].iloc[q + 1]) / float(qqq[price_col].iloc[q]) - 1) * 100
            t.status = "filled"
        changed += 1
    return changed


def trades_frame(trades: list[PaperTrade]) -> pd.DataFrame:
    rows = []
    for t in reversed(trades):
        rows.append({
            "Entry day": t.entry_date, "Stock": t.ticker, "Insider": t.insider, "Role": t.role,
            "Bought $": t.value_usd, "Entry": t.entry_type, "Tested sector": "yes" if t.tested_sector else "no",
            "Status": t.status,
            "Same-day vs SPY": (t.same_day_return - t.same_day_spy) if t.same_day_return is not None
            and t.same_day_spy is not None else np.nan,
            "Next-day vs SPY": (t.next_day_return - t.next_day_spy) if t.next_day_return is not None
            and t.next_day_spy is not None else np.nan,
        })
    return pd.DataFrame(rows)


def summary(trades: list[PaperTrade]) -> dict:
    filled = [t for t in trades if t.status == "filled" and t.next_day_spy is not None]
    edges = np.array([t.next_day_return - t.next_day_spy for t in filled])
    same = np.array([t.same_day_return - t.same_day_spy for t in trades
                     if t.same_day_return is not None and t.same_day_spy is not None])
    return {
        "n_logged": len(trades), "n_filled": len(filled),
        "next_day_edge": float(edges.mean()) if len(edges) else float("nan"),
        "next_day_hit": float((edges > 0).mean()) if len(edges) else float("nan"),
        "same_day_edge": float(same.mean()) if len(same) else float("nan"),
        "n_same_day": int(len(same)),
    }
