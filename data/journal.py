"""
Decision journal — every your-call decision, BUY or PASS, with the date, price,
your reason and confidence. Logging the passes matters as much as the buys:
without them you only remember the winners.

Stored in portfolio_data/journal.json (gitignored). Build 2 adds the scoreboard
that fills in each decision's return vs QQQ at 20 and 60 trading days.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
JOURNAL_DOC = "journal"
ACTIONS = ("buy", "pass")


@dataclass
class Decision:
    ticker: str
    action: str  # "buy" or "pass"
    price: float  # last close when you decided
    status: str  # e.g. "your_call"
    why_flagged: str  # the app's reason, e.g. "company news, just reported"
    thesis: str  # your one-line reason
    confidence: int  # 1-5
    media_score_7d: Optional[float] = None
    decided_on: str = field(default_factory=lambda: date.today().isoformat())
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


def validate_decision(raw: dict) -> tuple[Optional[Decision], Optional[str]]:
    ticker = str(raw.get("ticker") or "").strip().upper()
    if not ticker:
        return None, "Ticker is required."
    action = str(raw.get("action") or "").lower()
    if action not in ACTIONS:
        return None, "Choose Buy or Pass."
    try:
        price = float(raw.get("price"))
    except (TypeError, ValueError):
        return None, "No price available for this stock."
    if not price > 0:
        return None, "No price available for this stock."
    try:
        confidence = int(raw.get("confidence"))
    except (TypeError, ValueError):
        return None, "Confidence must be 1-5."
    if not 1 <= confidence <= 5:
        return None, "Confidence must be 1-5."
    thesis = str(raw.get("thesis") or "").strip()
    if not thesis:
        return None, "Write one line on why — future you will want to know."
    media = raw.get("media_score_7d")
    return Decision(
        ticker=ticker, action=action, price=price,
        status=str(raw.get("status") or ""), why_flagged=str(raw.get("why_flagged") or ""),
        thesis=thesis, confidence=confidence,
        media_score_7d=float(media) if media is not None and pd.notna(media) else None,
        decided_on=str(raw.get("decided_on") or date.today().isoformat()),
        id=str(raw.get("id") or uuid.uuid4().hex[:12]),
    ), None


def load_journal(store) -> list[Decision]:
    payload = store.get(JOURNAL_DOC) or {}
    out = []
    for record in payload.get("decisions", []):
        decision, error = validate_decision(record) if isinstance(record, dict) else (None, "bad")
        if decision and not error:
            out.append(decision)
    return out


def append_decision(decision: Decision, store) -> None:
    decisions = load_journal(store) + [decision]
    store.put(JOURNAL_DOC, {"schema": 1, "updated_at": datetime.now().isoformat(timespec="seconds"),
                            "decisions": [asdict(d) for d in decisions]})


def journal_frame(decisions: list[Decision]) -> pd.DataFrame:
    if not decisions:
        return pd.DataFrame(columns=["Date", "Stock", "Decision", "Price", "Confidence", "Why flagged", "Your reason"])
    return pd.DataFrame([{
        "Date": d.decided_on, "Stock": d.ticker, "Decision": d.action.upper(),
        "Price": d.price, "Confidence": d.confidence, "Why flagged": d.why_flagged,
        "Your reason": d.thesis,
    } for d in reversed(decisions)])
