"""
Today tab: the one-screen summary. What (if anything) to do with new cash, what
is happening on your watchlists, where the market is leaning, and how your
portfolio stands. Every card says how much evidence is behind it.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data.market_pulse import leaders_and_laggards
from ui.desk_common import AMBER, GREEN, GREY, fmt_money, section, verdict_card
from ui.desk_portfolio import portfolio_snapshot
from ui.desk_watchlists import watchlist_rows


def render_today(result, qualifying, cash, max_names, groups, holdings, frames, pulse_table) -> None:
    # 1 — the deploy call (evidence-backed)
    if qualifying:
        picks = qualifying[:max_names]
        names = ", ".join(p["ticker"] for p in picks)
        verdict_card(
            f"✅ Deploy new cash — {len(picks)} name{'s' if len(picks) != 1 else ''}",
            f"<b>{names}</b> · {fmt_money(cash / len(picks))} each. "
            "Evidence: market-wide dips away from earnings beat random days "
            "(+0.3–0.4pp per trade, 200/200 random draws). Details on the Deploy tab.",
            GREEN,
        )
    else:
        verdict_card(
            "⏸ Nothing qualifies today — hold new cash",
            f"{result.n_dipping} of {result.n_scanned} names are dipping, but none passes "
            "every gate. That is normal; see the Deploy tab for what is blocking them.",
            GREY,
        )

    # 2 — watchlists
    section("On your watchlists")
    table = watchlist_rows(groups, result.rows)
    interesting = table[table["Status"].isin(["✅ qualifies", "🟡 dipping, blocked", "👀 within 3% of trigger"])] \
        if not table.empty else table
    if interesting.empty:
        st.caption("Nothing on your watchlists is dipping or close to its trigger.")
    else:
        st.dataframe(
            interesting.drop_duplicates("Ticker")[["Ticker", "Group", "Status", "Price", "To trigger %"]]
            .style.format({"Price": "${:,.2f}", "To trigger %": "{:+.1f}%"}, na_rep="—"),
            width="stretch", hide_index=True,
        )

    # 3 — market pulse (information only)
    section("Where the market is leaning")
    if pulse_table is not None and not pulse_table.empty:
        leaders, laggards = leaders_and_laggards(pulse_table)
        c1, c2 = st.columns(2)
        c1.markdown(f"**Leading (3 months):** {', '.join(leaders) or '—'}")
        c2.markdown(f"**Lagging (3 months):** {', '.join(laggards) or '—'}")
        st.caption("ℹ️ Information only — not a tested signal. Full table on the Market pulse tab.")
    else:
        st.caption("No fund data right now.")

    # 4 — portfolio
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
    held_and_dipping = [r["ticker"] for r in result.rows
                        if r["gate_dip"] and r["ticker"] in {h.ticker for h in holdings}]
    if held_and_dipping:
        st.markdown(
            f"<div class='evidence-note' style='color:{AMBER}'>You hold {', '.join(held_and_dipping)}, "
            "which are dipping now. The app never says sell — no exit rule survived testing.</div>",
            unsafe_allow_html=True,
        )
