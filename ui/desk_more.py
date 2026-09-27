"""More tab: 📱 phone & alerts (and 👥 friends for admins), the market backdrop
(information only), and how the Desk works."""

from __future__ import annotations

import streamlit as st

from ui.desk_account import render_account
from ui.desk_howto import render_howto
from ui.desk_market import render_market


def render_more(result, spec, pulse_table, secrets) -> None:
    render_account(secrets)
    render_market(result, spec, pulse_table)
    with st.expander("📐 How it works: words, statuses, evidence, and what failed"):
        render_howto()
