"""
The brief: a short to-do list built from everything the Desk knows, in the
order you'd act on it. Morning (pre-market), afternoon (market open; send at
~3:30pm ET, since dips are judged on the close) or evening. Used by the Brief
tab and the Telegram messages, so both always say the same thing.

Item kinds, in priority order:
  insider   ⚡ paper-buy at the open (H10: tested in tech, paper only)
  target    🎯 a ⭐ Want-to-buy stock is below its dip price (triggers if it closes there)
  gap       🔻/🔺 one of your stocks moved a lot outside market hours, or today (information)
  your_call 🟠 one of your stocks is dipping on its own news → Buy or Pass?
  buy_zone  🟢 new cash goes here (evidence-backed)
  earnings  📅 your stocks reporting in the next 7 days
"""

from __future__ import annotations

import pandas as pd

from data.premarket import BIG_MOVE_PCT, FUTURES
from data.signals import NEAR_DIP_PCT, YOUR_CALL, classify, short_reason
from data.watchlists import want_to_buy

INTRADAY_BIG_MOVE_PCT = 3.0  # during market hours only bigger moves are worth a card


def brief_title(session: str, hour: int | None) -> str:
    if session == "pre-market":
        return "☀️ Morning brief"
    if session == "market open":
        return "🕒 Afternoon brief" if hour is not None and hour >= 12 else "📈 Market open"
    if session == "after hours":
        return "🌙 Evening brief"
    return "☀️ Brief"


def watch_rows(result, groups) -> list[dict]:
    """⭐ Want-to-buy stocks with their distance to the dip price, closest first."""
    rows = {r["ticker"]: r for r in result.rows}
    out = []
    for ticker in want_to_buy(groups):
        r = rows.get(ticker)
        if r is None:
            out.append({"ticker": ticker, "state": "no data"})
            continue
        if r["gate_dip"]:
            state = "crossed"
            would_be = "🟢 buy zone" if r["qualifies"] else f"🟠 your call ({short_reason(r)})"
        else:
            state = "close" if pd.notna(r["dist_pct"]) and r["dist_pct"] > -NEAR_DIP_PCT else "watching"
            would_be = ""
        out.append({"ticker": ticker, "state": state, "price": r["close"], "dip_price": r["trigger"],
                    "distance_pct": r["dist_pct"], "would_be": would_be})
    order = {"crossed": 0, "close": 1, "watching": 2, "no data": 3}
    return sorted(out, key=lambda w: (order[w["state"]], -(w.get("distance_pct") or -999)))


def watch_line(w: dict) -> str:
    if w["state"] == "no data":
        return f"{w['ticker']}: no data"
    if w["state"] == "crossed":
        return f"🎯 {w['ticker']} ${w['price']:,.2f}: BELOW dip price ${w['dip_price']:,.2f}"
    flag = "👀 " if w["state"] == "close" else ""
    return (f"{flag}{w['ticker']} ${w['price']:,.2f}: dip price ${w['dip_price']:,.2f} "
            f"({w['distance_pct']:+.1f}% away)")


def _money(x: float) -> str:
    if x >= 1e6:
        return f"${x / 1e6:.1f}M"
    if x >= 1e3:
        return f"${x / 1e3:.0f}k"
    return f"${x:,.0f}"


def build_brief(result, groups, holdings, premarket: pd.DataFrame, pending_trades: list) -> dict:
    """Return {'title', 'market', 'watch', 'items': [{icon, kind, title, detail, ticker}], 'quiet'}."""
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

    # 🎯 a want-to-buy stock is below its dip price
    watch = watch_rows(result, groups)
    for w in watch:
        if w["state"] == "crossed":
            items.append({"icon": "🎯", "kind": "target", "ticker": w["ticker"],
                          "title": f"{w['ticker']} ${w['price']:,.2f} is below its dip price ${w['dip_price']:,.2f}",
                          "detail": f"If it closes here it's {w['would_be']}. Dips are judged on the "
                                    "closing price, so this can still change before 4pm."})

    # 🔻/🔺 your stocks moving a lot (outside market hours, or today during the session)
    if not moves.empty:
        for ticker in sorted(mine & set(moves.index)):
            m = moves.loc[ticker]
            threshold = INTRADAY_BIG_MOVE_PCT if m["session"] == "market open" else BIG_MOVE_PCT
            if pd.notna(m["move_pct"]) and abs(m["move_pct"]) >= threshold:
                down = m["move_pct"] < 0
                when = "today" if m["session"] == "market open" else m["session"]
                items.append({"icon": "🔻" if down else "🔺", "kind": "gap", "ticker": ticker,
                              "title": f"{ticker} {m['move_pct']:+.1f}% {when}"
                                       + (" (you own it)" if ticker in held else ""),
                              "detail": ("Big drop: check the news. If it's an overreaction, it may "
                                         "show up as 🟠 Your call." if down else "Big move up.")})

    # 🟠 your stocks dipping on their own news (want-to-buy crossings already have a 🎯 card)
    crossed = {w["ticker"] for w in watch if w["state"] == "crossed"}
    for ticker in sorted(mine - crossed):
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
    session, hour = "", None
    if not moves.empty and moves["as_of"].notna().any():
        latest = moves["as_of"].dropna().max()
        session = moves.loc[moves["as_of"] == latest, "session"].iloc[0]
        hour = latest.hour
    return {"title": brief_title(session, hour), "market": market, "watch": watch,
            "items": items, "quiet": not items}


def brief_text(brief: dict, as_of: str) -> str:
    """Plain-text version for Telegram / notifications."""
    lines = [f"{brief.get('title', '☀️ Brief')} — {as_of}"]
    if brief["market"]:
        lines.append(" · ".join(brief["market"]))
    lines.append("")
    if brief["quiet"]:
        lines.append("Nothing needs you today. No buy-zone stocks, no insider buys, no big moves in your stocks.")
    for item in brief["items"]:
        lines.append(f"{item['icon']} {item['title']}")
    if brief.get("watch"):
        lines.append("")
        lines.append("⭐ Want to buy:")
        lines += [f"  {watch_line(w)}" for w in brief["watch"]]
    lines.append("")
    lines.append("Open the Desk for details. Paper trades and Your-call decisions are logged there.")
    return "\n".join(lines)
