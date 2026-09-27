"""
Portfolio tab: edit what you own (ticker, shares, average price), see today's
value and gain, and the risk panel (sector mix, independent bets, drawdown).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from data.holdings import (
    HOLDINGS_PATH,
    frame_to_holdings,
    holdings_to_frame,
    hypothetical_drawdown,
    import_from_lots,
    save_holdings,
    value_holdings,
)
from data.portfolio import get_store
from data.screen import SECTORS, effective_bets
from ui.desk_common import GREEN, RED, fmt_money, last_close, previous_close, section


def portfolio_snapshot(holdings, frames) -> dict:
    """Totals used by both the Today and Portfolio tabs."""
    prices = {h.ticker: last_close(frames, h.ticker) for h in holdings}
    valued = value_holdings(holdings, prices)
    if valued.empty:
        return {"valued": valued, "value": 0.0, "cost": 0.0, "gain": 0.0, "day_change": float("nan")}
    previous = sum(h.shares * previous_close(frames, h.ticker) for h in holdings)
    value = float(valued["Value"].sum(min_count=1))
    return {
        "valued": valued,
        "value": value,
        "cost": float(valued["Cost"].sum()),
        "gain": float(valued["Gain $"].sum(min_count=1)),
        "day_change": value - previous if previous else float("nan"),
    }


def render_portfolio(holdings, frames, drawdown_limit_pct: float) -> None:
    section("What you own")
    snapshot = portfolio_snapshot(holdings, frames)
    if holdings:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Value", fmt_money(snapshot["value"]))
        c2.metric("Cost", fmt_money(snapshot["cost"]))
        gain_pct = snapshot["gain"] / snapshot["cost"] * 100 if snapshot["cost"] else np.nan
        c3.metric("Gain", fmt_money(snapshot["gain"]), f"{gain_pct:+.1f}%" if pd.notna(gain_pct) else None)
        c4.metric("Today", fmt_money(snapshot["day_change"]))
        st.dataframe(
            snapshot["valued"].style.format({
                "Shares": "{:,.4f}", "Avg price": "${:,.2f}", "Price": "${:,.2f}",
                "Cost": "${:,.2f}", "Value": "${:,.2f}", "Gain $": "${:+,.2f}",
                "Gain %": "{:+.1f}%", "Weight %": "{:.1f}%",
            }, na_rep="—").map(
                lambda v: f"color:{GREEN}" if isinstance(v, float) and v > 0
                else (f"color:{RED}" if isinstance(v, float) and v < 0 else ""),
                subset=["Gain $", "Gain %"],
            ),
            width="stretch", hide_index=True,
        )
        missing = [t for t, p in zip(snapshot["valued"]["Ticker"], snapshot["valued"]["Price"]) if pd.isna(p)]
        if missing:
            st.warning(f"No price for {', '.join(missing)} — check the ticker spelling, or Refresh.")

    render_editor(holdings)
    if holdings:
        render_risk(holdings, frames, snapshot, drawdown_limit_pct)


def render_editor(holdings) -> None:
    with st.expander("✏️ Edit holdings", expanded=not holdings):
        st.caption(
            "One row per stock: **ticker, number of shares, average price** "
            "(what your position averages out to per share — your broker shows it "
            "as 'avg cost'). Add rows at the bottom; select a row and press Delete "
            "to remove it. Nothing is saved until you press **Save**."
        )
        edited = st.data_editor(
            holdings_to_frame(holdings),
            num_rows="dynamic",
            width="stretch",
            key="holdings_editor",
            column_config={
                "ticker": st.column_config.TextColumn("Ticker", required=True, max_chars=10),
                "shares": st.column_config.NumberColumn("Shares", min_value=0.0, format="%.4f", required=True),
                "avg_price": st.column_config.NumberColumn("Average price ($)", min_value=0.0, format="$%.2f", required=True),
            },
        )
        c1, c2 = st.columns([1, 3])
        if c1.button("💾 Save holdings", type="primary"):
            new_holdings, notes = frame_to_holdings(edited)
            problems = [n for n in notes if "merged" not in n]
            if problems:
                st.error("Not saved — fix these first:\n\n- " + "\n- ".join(problems))
            else:
                save_holdings(new_holdings)
                for note in notes:
                    st.info(note)
                st.success(f"Saved {len(new_holdings)} holdings.")
                st.rerun()
        c2.caption(f"Saved locally in `{HOLDINGS_PATH.relative_to(HOLDINGS_PATH.parent.parent)}` "
                   "(gitignored — never committed).")

        if not holdings:
            try:
                old_lots = get_store().load()
            except Exception:  # noqa: BLE001
                old_lots = []
            if old_lots:
                st.info(f"Found {len(old_lots)} lots in the old portfolio store (app.py).")
                if st.button("⬇️ Import them as holdings (averages each ticker's lots)"):
                    save_holdings(import_from_lots(old_lots))
                    st.rerun()


def render_risk(holdings, frames, snapshot, drawdown_limit_pct: float) -> None:
    section("Risk")
    valued = snapshot["valued"].dropna(subset=["Value"])
    valued = valued.assign(Sector=valued["Ticker"].map(lambda t: SECTORS.get(t, "Other")))
    by_sector = valued.groupby("Sector")["Value"].sum().sort_values(ascending=False)
    total = by_sector.sum()

    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("**Sector mix**")
        st.dataframe(
            pd.DataFrame({"Sector": by_sector.index, "Weight %": (by_sector / total * 100).values})
            .style.format({"Weight %": "{:.1f}%"}),
            width="stretch", hide_index=True,
        )
    with c2:
        bets = effective_bets(frames, [h.ticker for h in holdings])
        st.metric("Independent bets", f"{bets['effective_bets']:.1f}" if pd.notna(bets["effective_bets"]) else "—",
                  help="How many truly independent bets your holdings add up to. "
                       "30 tech names measured only 4.6 (Portfolio study).")
        drawdown = hypothetical_drawdown(holdings, frames)
        worst = drawdown["max_drawdown_pct"]
        st.metric("Worst drop, past year", f"{worst:.1f}%" if pd.notna(worst) else "—",
                  help="If today's holdings had been held unchanged for the past year.")
        st.metric("Below peak now", f"{drawdown['current_drawdown_pct']:.1f}%"
                  if pd.notna(drawdown["current_drawdown_pct"]) else "—")

    if pd.notna(worst):
        if abs(worst) > drawdown_limit_pct:
            st.error(f"This mix fell **{abs(worst):.0f}%** in the past year — more than the "
                     f"**{drawdown_limit_pct:.0f}%** you said you can sit through. "
                     "Either the limit or the mix needs to change.")
        else:
            st.success(f"Past-year worst drop {abs(worst):.0f}% is inside your "
                       f"{drawdown_limit_pct:.0f}% limit. A bad year can still be worse — "
                       "the tech-only basket fell 51% in testing.")
