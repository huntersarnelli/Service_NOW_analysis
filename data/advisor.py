"""
The LLM advisory layer — advisory only, never a gate.

Why this is advisory
--------------------
OVERREACTION_STUDY.md §8 sets the honest expectations before a line of this was
written:

  FOR   The axis that produced a real, stable effect is exactly the axis a
        model operates on -- is this decline about the company or about the
        market? Earnings proximity is the crudest possible proxy for that
        question and it still delivered +0.80pp at 20 days, t = 2.35.

  AGAINST  The one other crude proxy that should have worked -- volume --
        produced nothing and flipped sign across halves. And the ceiling is
        visible: the whole effect is +0.80pp per trade at 20 days, decaying to
        zero by 60. A model layer would be splitting an effect of that size.

So the model never decides anything here. The statistical screen decides; the
model annotates what it is looking at. Promote it to a gate only after it has
been backtested with point-in-time data, which this repository cannot currently
do -- see the lookahead warning below.

The lookahead problem, stated plainly
-------------------------------------
A model scoring 2023 news knows what happened in 2024. Any backtest of this
layer without point-in-time data and a knowledge-cutoff-aware model will look
brilliant and be worthless. That is the single largest risk in this feature,
larger than cost or latency. Nothing in this module should be read as evidence
that the layer works, because no such evidence exists yet.

Order of operations
-------------------
Statistics narrow the field first -- 124 names down to the handful that print a
qualifying dip -- and the model judges only those. Model-first would be
expensive, slow, non-deterministic, and would invert the one thing already
known to work.

Cost control
------------
Only candidates you explicitly ask about are sent. Results are cached per
(ticker, bar date, prompt version) so re-running the app on the same bar costs
nothing. Typical call is a few hundred input tokens and a few hundred output.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional

MODEL = "claude-opus-5"
PROMPT_VERSION = "v1"

SYSTEM = """You are a research assistant for a systematic dip-buying strategy. \
You do NOT make buy or sell decisions — a statistical screen has already \
decided which names are candidates. Your only job is to characterise WHY a \
stock declined, so the user is not blindsided by something they did not know.

The distinction that matters, from Chan (2003) and Savor (2012): declines \
driven by genuinely new, material, company-specific information tend to DRIFT \
further (bad to buy); declines driven by market-wide moves, sector sympathy, \
stale news, or no identifiable news tend to REVERSE (better to buy).

Rules:
- Be concise and concrete. No hedging boilerplate, no disclaimers.
- If you do not know of any specific news, say so plainly. "No identifiable \
company-specific news" is a useful and common answer, not a failure.
- Never state or imply a price target, a recommendation, or a confidence in \
future returns.
- Distinguish what you actually know from what you are inferring from the \
numbers you were given.
- Your knowledge has a cutoff. If the bar date is at or after it, say the \
recent news is outside what you know rather than guessing."""

SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {
            "type": "string",
            "enum": ["company_specific", "market_driven", "sector_driven",
                     "mixed", "unknown"],
            "description": "What most likely drove this decline.",
        },
        "drift_risk": {
            "type": "string",
            "enum": ["low", "moderate", "high", "unknown"],
            "description": (
                "Risk that the decline keeps going because it reflects new "
                "material information. High for fresh company-specific bad "
                "news; low for market-wide drags."
            ),
        },
        "summary": {
            "type": "string",
            "description": "Two sentences maximum on what is going on.",
        },
        "known_issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Specific structural or legal overhangs you actually know of "
                "(litigation, regulation, guidance cuts, secular decline). "
                "Empty array if none known."
            ),
        },
        "what_would_change_it": {
            "type": "string",
            "description": (
                "One sentence: what information would move this from one "
                "classification to another."
            ),
        },
        "knowledge_caveat": {
            "type": "string",
            "description": (
                "State plainly whether the bar date is beyond your knowledge "
                "cutoff and what that means for this answer."
            ),
        },
    },
    "required": ["classification", "drift_risk", "summary", "known_issues",
                 "what_would_change_it", "knowledge_caveat"],
    "additionalProperties": False,
}


@dataclass
class Advice:
    ticker: str
    classification: str
    drift_risk: str
    summary: str
    known_issues: list
    what_would_change_it: str
    knowledge_caveat: str
    model: str = MODEL
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def available() -> tuple[bool, str]:
    """(is_usable, reason) — checked before any UI offers the feature."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False, "The `anthropic` package is not installed (pip install anthropic)."
    if not _resolve_key():
        return False, (
            "No credentials found. Set ANTHROPIC_API_KEY, add it to "
            "`.streamlit/secrets.toml`, or run `ant auth login`."
        )
    return True, ""


def _resolve_key() -> Optional[str]:
    """
    Env var first, then Streamlit secrets. A bare Anthropic() client also picks
    up an `ant auth login` profile, so a missing key here is not automatically
    fatal -- but the UI needs something to show, so an explicit key wins.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets.get("ANTHROPIC_API_KEY")  # type: ignore[no-any-return]
    except Exception:
        return None


def _fmt_context(row: dict, breadth: float, spec_name: str) -> str:
    dte = row.get("days_to_earnings")
    return f"""Ticker: {row['ticker']}  ({row.get('sector', 'Unknown sector')})
Bar date: {row['last_bar'].date() if hasattr(row.get('last_bar'), 'date') else row.get('last_bar')}
Close: ${row['close']:,.2f}

Statistical picture computed from price data:
- Z-score (20d): {row['z']:.2f}  (below -1.2 is the dip trigger)
- Market-neutralised Z: {row['idio_z']:.2f}  (a HIGHER value means more of the
  decline is explained by the market falling rather than by this company)
- Rolling beta vs SPY: {row['beta']:.2f}
- Trailing 20d volatility, annualised: {row['rvol20']:.1f}%
- Trading bars since last earnings report: {row['days_since_earnings']:.0f}
- Calendar days to next earnings: {dte if dte is not None else 'unknown'}
- Breadth: {breadth:.0%} of the 124-name universe is simultaneously below the
  dip threshold today (a high number means a market-wide selloff, a low number
  means this name is falling largely alone)

The screen in use is "{spec_name}" and this name passed it.

Characterise why this stock declined."""


def get_advice(row: dict, breadth: float, spec_name: str,
               max_tokens: int = 1200) -> Advice:
    """
    One advisory call for one candidate. Raises nothing — failures come back on
    the `error` field so a dead API key can never take the dashboard down.
    """
    ok, reason = available()
    if not ok:
        return Advice(row["ticker"], "unknown", "unknown", "", [], "", "",
                      error=reason)

    try:
        import anthropic

        key = _resolve_key()
        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()

        response = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "medium",
                "format": {
                    "type": "json_schema",
                    "schema": SCHEMA,
                },
            },
            messages=[{"role": "user", "content": _fmt_context(row, breadth, spec_name)}],
        )

        if response.stop_reason == "refusal":
            cat = getattr(getattr(response, "stop_details", None), "category", None)
            return Advice(row["ticker"], "unknown", "unknown", "", [], "", "",
                          error=f"Model declined to answer (category: {cat}).")

        text = "".join(b.text for b in response.content if b.type == "text")
        data = json.loads(text)
        return Advice(
            ticker=row["ticker"],
            classification=data["classification"],
            drift_risk=data["drift_risk"],
            summary=data["summary"],
            known_issues=data.get("known_issues", []),
            what_would_change_it=data.get("what_would_change_it", ""),
            knowledge_caveat=data.get("knowledge_caveat", ""),
        )
    except Exception as e:  # noqa: BLE001 - advisory layer must never break the app
        return Advice(row["ticker"], "unknown", "unknown", "", [], "", "",
                      error=f"{type(e).__name__}: {e}")


DRIFT_COLOR = {
    "low": "#1F6F54",
    "moderate": "#8A6014",
    "high": "#8C2F39",
    "unknown": "#64757B",
}

CLASSIFICATION_LABEL = {
    "company_specific": "Company-specific — the drift case",
    "sector_driven": "Sector sympathy",
    "market_driven": "Market-driven — the reversal case",
    "mixed": "Mixed",
    "unknown": "Unknown",
}
