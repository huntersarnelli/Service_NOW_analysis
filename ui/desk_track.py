"""
Track record tab: are the calls working?

  1. Your calls & buy-zone signals, scored vs QQQ at 20 and 60 trading days
  2. Insider paper trades (H10), scored vs SPY at the same-day and next-day close,
     next to the backtest numbers they should roughly match
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data.journal import load_journal
from data.paper_trades import (BACKTEST_NEXT_DAY_EDGE, BACKTEST_SAME_DAY_EDGE, fill_outcomes,
                               load_trades, save_trades, summary, trades_frame)
from data.scoreboard import MIN_CALLS_FOR_VERDICT, build_calls, load_buy_zone_log, score_table, summarise
from ui.desk_common import GREEN, RED, section


def signed_colour(v):
    if isinstance(v, float) and pd.notna(v):
        return f"color:{GREEN}" if v > 0 else (f"color:{RED}" if v < 0 else "")
    return ""


def render_track(frames) -> None:
    section("Your calls vs QQQ")
    st.caption(
        "Every decision is scored against **QQQ** (buying the Nasdaq-100 instead) at 20 and 60 "
        "trading days. **Your buys** should beat it; **your passes** should lag it (a good pass "
        f"avoided a laggard). Judge nothing before ~{MIN_CALLS_FOR_VERDICT} scored calls — "
        "below that, luck dominates."
    )
    calls = build_calls(load_journal(), load_buy_zone_log())
    if not calls:
        st.info("No calls yet. Log Buy / Pass on 🟠 Your call stocks (Watchlist tab); "
                "🟢 Buy-zone signals are logged automatically whenever the app runs.")
    else:
        table = score_table(calls, frames)
        summary_table = summarise(table)
        st.dataframe(
            summary_table.style.format({
                "Avg vs QQQ 20d": "{:+.2f}pp", "Avg vs QQQ 60d": "{:+.2f}pp",
                "Beat QQQ 20d": "{:.0f}%", "Beat QQQ 60d": "{:.0f}%",
            }, na_rep="—"),
            width="stretch", hide_index=True,
        )
        with st.expander(f"📓 Decision log: every call and signal ({len(table)})"):
            st.dataframe(
                table.style.format({"20d vs QQQ": "{:+.2f}pp", "60d vs QQQ": "{:+.2f}pp"}, na_rep="—")
                .map(signed_colour, subset=["20d vs QQQ", "60d vs QQQ"]),
                width="stretch", hide_index=True,
            )
            st.caption("'pending (12d)' = only 12 trading days so far; the number shown is the return "
                       "vs QQQ to date and is not counted in the averages yet.")

    section("⚡ Insider paper trades")
    st.caption(
        "Every insider buy that passed the rules, logged automatically when you scan (Today tab). "
        f"Backtest expectation: **+{BACKTEST_SAME_DAY_EDGE:.2f}pp** vs SPY open→same-day close and "
        f"**+{BACKTEST_NEXT_DAY_EDGE:.2f}pp** to the next-day close. If ~30 live trades land near "
        "that, the edge is real enough to consider real money; if near zero, it was a backtest artefact."
    )
    trades = load_trades()
    if not trades:
        st.info("No paper trades yet — run the insider scan on the Today tab (evening or before 9:30 ET).")
        return
    if fill_outcomes(trades, frames):
        save_trades(trades)
    s = summary(trades)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Logged", s["n_logged"])
    c2.metric("Completed", s["n_filled"])
    c3.metric("Next-day vs SPY", f"{s['next_day_edge']:+.2f}pp" if pd.notna(s["next_day_edge"]) else "—",
              f"backtest +{BACKTEST_NEXT_DAY_EDGE:.2f}pp", delta_color="off")
    c4.metric("Same-day vs SPY", f"{s['same_day_edge']:+.2f}pp" if pd.notna(s["same_day_edge"]) else "—",
              f"backtest +{BACKTEST_SAME_DAY_EDGE:.2f}pp", delta_color="off")
    st.dataframe(
        trades_frame(trades).style.format({"Bought $": "${:,.0f}", "Same-day vs SPY": "{:+.2f}pp",
                                           "Next-day vs SPY": "{:+.2f}pp"}, na_rep="—")
        .map(signed_colour, subset=["Same-day vs SPY", "Next-day vs SPY"]),
        width="stretch", hide_index=True,
    )
    st.caption("'Tested sector: no' = outside tech, where the backtest never looked. Keep those "
               "separate in your head until they have their own record.")
