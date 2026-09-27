"""
Today tab: the one-screen summary, in the order you'd act on it.

  1. 🟢 Buy zone      — what the evidence says to do with new cash
  2. 🟠 Your call     — your stocks dipping on their own news or after earnings
  3. 👀 Close to a dip — your stocks within 3% of their dip price
  4. ⚡ Insider buys   — scan EDGAR for insider purchases (paper trading)
  5. The market       — how many stocks are falling; which sectors lead
  6. Your portfolio
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from data.insider_feed import scan as insider_scan
from data.market_pulse import leaders_and_laggards
from data.paper_trades import add_signals
from data.screen import SECTORS
from data.signals import NEAR, YOUR_CALL
from ui.desk_common import GREEN, GREY, fmt_money, section, verdict_card
from ui.desk_portfolio import portfolio_snapshot
from ui.desk_stocks import stock_table


def breadth_sentence(breadth: float, breadth_lo: float) -> str:
    if pd.isna(breadth):
        return "Market breadth unavailable."
    share = f"{breadth:.0%} of the 124 core stocks are dipping"
    if breadth <= breadth_lo:
        return f"{share} — a quiet market, so any single faller is probably falling on its own news."
    if breadth < 0.39:
        return f"{share} — a broad pullback, the best backdrop for buying dips."
    return f"{share} — a big sell-off. Still a fine time to buy dips, no better than a moderate one."


def render_today(result, spec, qualifying, cash, max_names, groups, holdings, frames, pulse_table) -> None:
    # 1 — Buy zone
    if qualifying:
        picks = qualifying[:max_names]
        per = cash / len(picks)
        verdict_card(
            f"🟢 Buy zone — {len(picks)} stock{'s' if len(picks) != 1 else ''} for new cash",
            f"<b>{', '.join(p['ticker'] for p in picks)}</b> · {fmt_money(per)} each "
            f"({fmt_money(cash)} total). These passed every evidence rule.",
            GREEN,
        )
        st.dataframe(
            pd.DataFrame([{"Stock": p["ticker"], "Sector": p["sector"], "Price": p["close"],
                           "Invest": per, "Shares (approx)": per / p["close"] if p["close"] else np.nan}
                          for p in picks]).style.format(
                {"Price": "${:,.2f}", "Invest": "${:,.2f}", "Shares (approx)": "{:,.3f}"}),
            width="stretch", hide_index=True,
        )
    else:
        verdict_card("Nothing in the buy zone today — hold new cash",
                     "No dip passes every evidence rule right now. That is normal. "
                     "If nothing qualifies for months, invest on a schedule instead of waiting forever.",
                     GREY)

    table = stock_table(result.rows, groups, frames)
    mine = set(t for tickers in groups.values() for t in tickers) | {h.ticker for h in holdings}
    my_table = table[table["Stock"].isin(mine)] if not table.empty else table

    # 2 — Your call
    section("🟠 Your call — your stocks dipping on their own news")
    calls = my_table[my_table["_status"] == YOUR_CALL] if not my_table.empty else my_table
    if calls.empty:
        st.caption("None of your stocks are dipping on their own right now.")
    else:
        st.dataframe(
            calls[["Stock", "Why", "5-day move", "Market 5-day", "Lists"]].style.format(
                {"5-day move": "{:+.1f}%", "Market 5-day": "{:+.1f}%"}, na_rep="—"),
            width="stretch", hide_index=True,
        )
        st.caption("The rules would skip these — company news usually keeps drifting. But a rule "
                   "can't read a headline. Open one in the **Stocks** tab to see the news and log "
                   "Buy or Pass.")
    others = int((table["_status"] == YOUR_CALL).sum()) - len(calls) if not table.empty else 0
    if others > 0:
        st.caption(f"{others} more outside your lists — Stocks tab → 🟠 Your call.")

    # 3 — Close to a dip
    near = my_table[my_table["_status"] == NEAR] if not my_table.empty else my_table
    if not near.empty:
        section("👀 Close to a dip")
        st.dataframe(near[["Stock", "Price", "Dip price", "To dip price", "Lists"]].style.format(
            {"Price": "${:,.2f}", "Dip price": "${:,.2f}", "To dip price": "{:+.1f}%"}),
            width="stretch", hide_index=True)

    # 4 — Insider buys (paper trading)
    render_insider_scan(result, frames)

    # 5 — Market
    section("The market")
    st.markdown(breadth_sentence(result.breadth, spec.breadth_lo))
    if pulse_table is not None and not pulse_table.empty:
        leaders, laggards = leaders_and_laggards(pulse_table)
        st.markdown(f"**Leading sectors (3 months):** {', '.join(leaders) or '—'} · "
                    f"**Lagging:** {', '.join(laggards) or '—'}")
        st.caption("ℹ️ Sector leadership is information, not a tested signal. Details: Market tab.")

    # 6 — Portfolio
    section("Your portfolio")
    if not holdings:
        st.caption("No holdings saved yet — add them on the Portfolio tab.")
        return
    snap = portfolio_snapshot(holdings, frames)
    c1, c2, c3 = st.columns(3)
    c1.metric("Value", fmt_money(snap["value"]))
    gain_pct = snap["gain"] / snap["cost"] * 100 if snap["cost"] else float("nan")
    c2.metric("Total gain", fmt_money(snap["gain"]), f"{gain_pct:+.1f}%" if pd.notna(gain_pct) else None)
    c3.metric("Today", fmt_money(snap["day_change"]))


def render_insider_scan(result, frames) -> None:
    section("⚡ Insider buys — paper trading")
    st.caption(
        "Scans the SEC's live Form 4 feed for open-market insider **purchases** in the stocks this "
        "app screens. Backtest (tech, 2013–2026): buying at the first open after the filing beat "
        "random days by ~+0.5pp same day, ~+0.7pp by the next close — but ~70% of the move happens "
        "overnight, so run this in the **evening or before 9:30 ET**. Every passing signal is logged "
        "as a paper trade (Track record tab). **Paper only until ~30 trades confirm it.**"
    )
    st.caption("The SEC's live feed only holds about the **last business day** of filings (from "
               "mid-afternoon on), which covers the evening and pre-market filings this trade uses. "
               "Scan once every evening or morning — a missed day can't be recovered here.")
    hours = 48  # the feed's own depth is the real limit (~1 business day)
    if st.button("⚡ Scan EDGAR now", type="primary"):
        screened = {r["ticker"] for r in result.rows}
        trading_days = pd.DatetimeIndex(frames["SPY"].index)
        bar = st.progress(0.0, text="Reading the SEC feed…")
        def progress(i, n):
            bar.progress(i / n, text=f"Checking filing {i} of {n}…")
        try:
            found = insider_scan(hours, screened, SECTORS, frames, trading_days, progress)
        except Exception as exc:  # noqa: BLE001 -- network / SEC hiccup
            st.error(f"Scan failed: {exc}. The SEC throttles at times — try again in a minute.")
            return
        bar.empty()
        st.session_state["insider_scan"] = found
        added = add_signals(found)
        st.success(f"{len(found)} insider purchase filing(s) in your stocks; "
                   f"{added} new paper trade(s) logged.")
    found = st.session_state.get("insider_scan")
    if found is None:
        return
    if found.empty:
        st.caption("No insider purchases in your stocks in that window. (Sales and grants are ignored.)")
        return
    view = found.assign(
        Signal=found["passes"].map({True: "✅ paper trade", False: "skipped"}),
        Plan=[f"buy at {t} on {d}" for t, d in zip(found["entry_type"], found["entry_date"])],
        Sector=found["tested_sector"].map({True: "tech (tested)", False: "untested"}),
    )
    st.dataframe(
        view[["Signal", "ticker", "insider", "role", "value_usd", "accepted", "Plan", "Sector", "fails"]]
        .rename(columns={"ticker": "Stock", "insider": "Insider", "role": "Role", "value_usd": "Bought $",
                         "accepted": "Filed (ET)", "fails": "Why skipped"})
        .style.format({"Bought $": "${:,.0f}"}),
        width="stretch", hide_index=True,
    )
