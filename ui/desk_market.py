"""Market tab: how many stocks are falling (breadth), then sector and theme leadership."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from ui.desk_common import section
from ui.desk_pulse import render_pulse


def render_market(result, spec, pulse_table) -> None:
    section("How many stocks are falling")
    st.caption(
        "Share of the 124 core stocks currently dipping (dip score below −1.2). "
        "A dip while **many** stocks fall is the market dragging good companies down — "
        "that tends to reverse. A dip while almost nothing else falls is company news — "
        "that tends to keep drifting."
    )
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=result.breadth * 100,
        number={"suffix": "%", "font": {"size": 34}},
        gauge={
            "axis": {"range": [0, 60]},
            "bar": {"color": "#8C2F39", "thickness": 0.7},
            "steps": [
                {"range": [0, spec.breadth_lo * 100], "color": "rgba(100,117,123,0.28)"},
                {"range": [spec.breadth_lo * 100, 39], "color": "rgba(31,111,84,0.28)"},
                {"range": [39, 60], "color": "rgba(138,96,20,0.28)"},
            ],
        },
    ))
    fig.update_layout(height=220, margin=dict(l=20, r=20, t=10, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption(f"Grey (below {spec.breadth_lo:.0%}): quiet market — lone fallers, the weakest dips. "
               "Green: broad pullback — the best backdrop. Amber: big sell-off — fine, no better.")

    render_pulse(pulse_table)
