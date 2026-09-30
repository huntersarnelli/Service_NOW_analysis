"""Small formatting helpers shared by the Deployment Desk (appV2.py) tabs."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def fmt_money(x: float) -> str:
    return "—" if pd.isna(x) else f"${x:,.2f}"


def fmt_pct(x: float) -> str:
    return "—" if pd.isna(x) else f"{x:+.1f}%"


def section(title: str) -> None:
    st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)


def verdict_card(headline: str, sub: str, colour: str) -> None:
    st.markdown(
        f"<div class='verdict-card' style='--vc:{colour}'>"
        f"<div class='verdict-head'>{headline}</div>"
        f"<div class='verdict-sub'>{sub}</div></div>",
        unsafe_allow_html=True,
    )


def last_close(frames: dict[str, pd.DataFrame], ticker: str) -> float:
    df = frames.get(ticker)
    if df is None or df.empty:
        return float("nan")
    return float(df["Close"].iloc[-1])


def previous_close(frames: dict[str, pd.DataFrame], ticker: str) -> float:
    df = frames.get(ticker)
    if df is None or len(df) < 2:
        return float("nan")
    return float(df["Close"].iloc[-2])


def user_store():
    """This visitor's own store, set once per session by appV2 after sign-in.
    Kept in st.session_state (per visitor) — never in a module global, which
    would be shared by everyone using the app at the same time."""
    return st.session_state["user_store"]


def shared_store():
    """The store everyone shares: insider paper trades, buy-zone log, invite list."""
    return st.session_state["shared_store"]


GREEN = "#1F6F54"
RED = "#8C2F39"
GREY = "#64757B"
AMBER = "#8A6014"
