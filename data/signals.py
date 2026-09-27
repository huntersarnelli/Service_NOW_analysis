"""
Plain-English status for every screened stock.

    🟢 Buy zone      a dip that passes every evidence rule (the market dragged it
                     down, not near earnings, other stocks falling too)
    🟠 Your call     a dip the rules would skip because it is falling on its own
                     (company news) or just after earnings. The data says these
                     drift lower ON AVERAGE, but a rule cannot read a headline --
                     so the app hands them to you, with headlines, and logs your
                     decision so the journal can score your judgement later.
    👀 Close to a dip within 3% of the dip price
    (blank)          nothing happening

Only the Buy zone is evidence-backed. Your-call decisions are measured, not assumed.
"""

from __future__ import annotations

import pandas as pd

BUY_ZONE = "buy_zone"
YOUR_CALL = "your_call"
NEAR = "near"
NONE = ""

STATUS_LABEL = {
    BUY_ZONE: "🟢 Buy zone",
    YOUR_CALL: "🟠 Your call",
    NEAR: "👀 Close to a dip",
    NONE: "",
}
NEAR_DIP_PCT = 3.0  # "close to a dip" = price within 3% of the dip price

# One-line base rates, from docs/02_OVERREACTION_STUDY.md (shown next to your-call stocks)
BASE_RATE = {
    "company": "Historically, stocks falling on their own news kept drifting lower on "
               "average (market-wide dips beat them at every horizon; OVERREACTION §5). "
               "You're betting this one is different.",
    "earnings": "Historically, dips right after earnings did worse than dips away from "
                "earnings (−0.80pp at 20 days, t = 2.35; OVERREACTION §4). "
                "You're betting the market over-reacted to the report.",
    "lonely": "Historically, stocks falling while little else fell were the weakest group "
              "(+1.04pp vs +2.60pp at 60 days; OVERREACTION §5).",
}


def classify(row: dict) -> str:
    if row.get("qualifies"):
        return BUY_ZONE
    if row.get("gate_dip"):
        return YOUR_CALL
    distance = row.get("dist_pct")
    if distance is not None and pd.notna(distance) and -NEAR_DIP_PCT < distance <= 0:
        return NEAR
    return NONE


def cause(row: dict) -> str:
    """'Market-wide' when most of the drop is the market's; 'Company-specific' otherwise."""
    if not row.get("gate_dip"):
        return ""
    return "Market-wide" if row.get("gate_market_wide", False) else "Company-specific"


def reasons(row: dict) -> list[tuple[str, str]]:
    """Why a dipping stock is not in the buy zone, as (base-rate key, plain sentence)."""
    out = []
    if not row.get("gate_dip") or row.get("qualifies"):
        return out
    if not row.get("gate_market_wide"):
        out.append(("company", "It is falling on its own — the drop is mostly company "
                               "news, not the market."))
    if not row.get("gate_no_earnings"):
        days = row.get("days_since_earnings")
        when = f"{days:.0f} trading days ago" if days is not None and pd.notna(days) else "recently"
        out.append(("earnings", f"It reported earnings {when}."))
    if not row.get("gate_not_lonely"):
        out.append(("lonely", "Few other stocks are falling today, so this drop "
                              "is not part of a broad sell-off."))
    return out


def short_reason(row: dict) -> str:
    """Compact reason for a table cell."""
    parts = []
    for key, _ in reasons(row):
        parts.append({"company": "company news", "earnings": "just reported",
                      "lonely": "falling alone"}[key])
    return ", ".join(parts)


def move_vs_market(frames: dict[str, pd.DataFrame], ticker: str, bars: int = 5,
                   benchmark: str = "SPY") -> tuple[float, float]:
    """(stock % move, SPY % move) over the last `bars` trading days."""
    def pct(t):
        df = frames.get(t)
        if df is None or len(df) <= bars:
            return float("nan")
        close = df["Close"]
        return float((close.iloc[-1] / close.iloc[-1 - bars] - 1) * 100)
    return pct(ticker), pct(benchmark)
