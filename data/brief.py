"""
The morning brief: a short to-do list built from everything the Desk knows,
in the order you'd act on it before the open. Used by the Brief tab and (later)
the 8:45am Telegram message, so both always say the same thing.

Item kinds, in priority order:
  insider   ⚡ paper-buy at the open (H10: tested in tech, paper only)
  gap       🔻/🔺 one of your stocks moved ≥ 2% outside market hours (information)
  your_call 🟠 one of your stocks is dipping on its own news → Buy or Pass?
  buy_zone  🟢 new cash goes here (evidence-backed)
  earnings  📅 your stocks reporting in the next 7 days
"""

from __future__ import annotations

import pandas as pd

from data.premarket import BIG_MOVE_PCT, FUTURES
from data.signals import YOUR_CALL, classify, short_reason


def _money(x: float) -> str:
    if x >= 1e6:
        return f"${x / 1e6:.1f}M"
    if x >= 1e3:
        return f"${x / 1e3:.0f}k"
    return f"${x:,.0f}"


def build_brief(result, groups, holdings, premarket: pd.DataFrame, pending_trades: list) -> dict:
    """Return {'market': [...lines], 'items': [{icon, kind, title, detail, ticker}], 'quiet': bool}."""
    mine = set(t for tickers in groups.values() for t in tickers) | {h.ticker for h in holdings}
    held = {h.ticker for h in holdings}
    rows = {r["ticker"]: r for r in result.rows}
    moves = premarket.set_index("ticker") if premarket is not None and not premarket.empty else pd.DataFrame()
    items: list[dict] = []

    # ⚡ insider paper trades waiting for their entry
    for t in pending_trades:
        when = "at the open" if t.entry_type == "open" else "at the close"
        items.append({"icon": "⚡", "kind": "insider", "ticker": t.ticker,
                      "title": f"Paper-buy {t.ticker} {when} ({t.entry_date})",
                      "detail": f"{t.insider} ({t.role}) bought {_money(t.value_usd)}. "
                                "Exit by the next day's close. Paper only."})

    # 🔻/🔺 your stocks moving outside market hours
    if not moves.empty:
        for ticker in sorted(mine & set(moves.index)):
            m = moves.loc[ticker]
            if pd.notna(m["move_pct"]) and abs(m["move_pct"]) >= BIG_MOVE_PCT and m["session"] != "market open":
                down = m["move_pct"] < 0
                items.append({"icon": "🔻" if down else "🔺", "kind": "gap", "ticker": ticker,
                              "title": f"{ticker} {m['move_pct']:+.1f}% {m['session']}"
                                       + (" (you own it)" if ticker in held else ""),
                              "detail": ("Big drop before the open: check the news. If it's an "
                                         "overreaction, it may show up as 🟠 Your call." if down
                                         else "Moving up before the open.")})

    # 🟠 your stocks dipping on their own news
    for ticker in sorted(mine):
        r = rows.get(ticker)
        if r and classify(r) == YOUR_CALL:
            items.append({"icon": "🟠", "kind": "your_call", "ticker": ticker,
                          "title": f"{ticker}: your call ({short_reason(r)})",
                          "detail": f"Dip score {r['z']:+.2f}, price ${r['close']:,.2f}. Read the headlines, "
                                    "then log Buy or Pass."})

    # 🟢 buy zone
    buy_zone = [r["ticker"] for r in result.rows if r["qualifies"]]
    if buy_zone:
        items.append({"icon": "🟢", "kind": "buy_zone", "ticker": ",".join(buy_zone),
                      "title": f"New cash: {', '.join(buy_zone[:6])}",
                      "detail": "Passed every evidence rule (+0.3–0.4pp per trade vs a random day)."})

    # 📅 earnings in the next 7 days
    soon = sorted((r["days_to_earnings"], r["ticker"]) for t, r in rows.items()
                  if t in mine and r.get("days_to_earnings") is not None
                  and pd.notna(r["days_to_earnings"]) and r["days_to_earnings"] <= 7)
    if soon:
        items.append({"icon": "📅", "kind": "earnings", "ticker": ",".join(t for _, t in soon),
                      "title": "Earnings this week: " + ", ".join(f"{t} ({d:.0f}d)" for d, t in soon),
                      "detail": "Dips right after earnings are 🟠 your call, not buy zone."})

    market = []
    if not moves.empty:
        for fut, label in FUTURES.items():
            if fut in moves.index and pd.notna(moves.loc[fut, "move_pct"]):
                move = moves.loc[fut, "move_pct"]
                market.append(f"{label} {'flat' if abs(move) < 0.05 else f'{move:+.1f}%'}")
    if pd.notna(result.breadth):
        market.append(f"{result.breadth:.0%} of core stocks dipping")
    return {"market": market, "items": items, "quiet": not items}


def brief_text(brief: dict, as_of: str) -> str:
    """Plain-text version for Telegram / notifications."""
    lines = [f"☀️ Morning brief — {as_of}"]
    if brief["market"]:
        lines.append(" · ".join(brief["market"]))
    lines.append("")
    if brief["quiet"]:
        lines.append("Nothing needs you today. No buy-zone stocks, no insider buys, no big moves in your stocks.")
    for item in brief["items"]:
        lines.append(f"{item['icon']} {item['title']}")
    lines.append("")
    lines.append("Open the Desk for details. Paper trades and Your-call decisions are logged there.")
    return "\n".join(lines)
