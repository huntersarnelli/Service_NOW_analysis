"""Market pulse tab: which sectors and themes are leading or lagging the market."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data.market_pulse import WINDOWS, leaders_and_laggards
from ui.desk_common import section


def colour_by_sign(value: float) -> str:
    """Green when beating SPY, red when lagging; stronger colour for bigger gaps."""
    if pd.isna(value):
        return ""
    strength = min(abs(value) / 15, 1) * 0.35 + 0.05
    rgb = "31,111,84" if value > 0 else "140,47,57"
    return f"background-color: rgba({rgb},{strength:.2f})"


def render_pulse(pulse_table: pd.DataFrame) -> None:
    section("Where the market is looking")
    st.caption(
        "Each fund's return **minus SPY's** over the same window, in percentage "
        "points. Green = beating the market, red = lagging it."
    )
    st.warning(
        "**Information only, not a signal.** Momentum was tested as a holding rule "
        "(docs/05_MOMENTUM_STUDY.md) and **failed narrowly**: +0.7pp/month vs random "
        "stocks but not reliable (t 1.80), mostly from 2020 and the AI boom, with a −62% "
        "worst drop. Use this to see where money is flowing, not as a reason to buy."
    )
    if pulse_table is None or pulse_table.empty:
        st.info("No fund data returned. Yahoo throttles heavily — try Refresh in a minute.")
        return

    leaders, laggards = leaders_and_laggards(pulse_table)
    c1, c2 = st.columns(2)
    c1.metric("Leading sectors (3M vs SPY)", ", ".join(leaders) or "—")
    c2.metric("Lagging sectors (3M vs SPY)", ", ".join(laggards) or "—")

    columns = [f"{name} vs SPY" for name in WINDOWS]
    st.dataframe(
        pulse_table.style.format({c: "{:+.1f}pp" for c in columns}, na_rep="—")
        .map(colour_by_sign, subset=columns),
        width="stretch", hide_index=True, height=520,
    )
    st.caption(
        "Sector funds: SPDR XL* series. Themes: SMH (semiconductors), IGV (software), "
        "QQQ (Nasdaq-100). Sorted by the 3-month column."
    )
