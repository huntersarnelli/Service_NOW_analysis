"""How it works tab: plain-English glossary, the statuses, the rules with their
evidence, the screens not used by default, and the graveyard of failed ideas."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data.screen import SCREENS
from ui.desk_common import section


def render_howto() -> None:
    section("The words on this dashboard")
    st.dataframe(pd.DataFrame([
        {"Term": "Dip score", "Meaning": "How far a stock is below its 20-day average, in units of its "
         "normal daily swing. 0 = normal; below −1.2 = dipping."},
        {"Term": "Dip price", "Meaning": "The price at which the dip score would hit −1.2. "
         "Usable as a limit-order price."},
        {"Term": "To dip price", "Meaning": "How far the price must fall to reach the dip price."},
        {"Term": "Cause", "Meaning": "Market-wide = the market dragged it down (historically reverses). "
         "Company-specific = its own news (historically keeps drifting)."},
        {"Term": "How many stocks are falling", "Meaning": "Share of the 124 core stocks dipping. "
         "Your added stocks never change this number, because its thresholds were calibrated on those 124."},
    ]), width="stretch", hide_index=True)

    section("The statuses")
    st.dataframe(pd.DataFrame([
        {"Status": "🟢 Buy zone", "When": "Dipping, market-wide cause, not within 20 days of earnings, "
         "and enough other stocks falling", "Backed by": "Evidence: +0.3–0.4pp per trade vs a random day"},
        {"Status": "🟠 Your call", "When": "Dipping, but on its own news, right after earnings, or while "
         "little else falls", "Backed by": "Your judgement — logged in the decision journal and scored later"},
        {"Status": "👀 Close to a dip", "When": "Within 3% of its dip price", "Backed by": "Heads-up only"},
        {"Status": "(blank)", "When": "Nowhere near a dip", "Backed by": "—"},
    ]), width="stretch", hide_index=True)

    section("Why each buy-zone rule is here")
    st.dataframe(pd.DataFrame([
        {"Rule": "Dip score below −1.2", "Evidence": "Beats 200/200 random draws at 5/20/60 days; "
         "+0.3–0.4pp per trade", "Source": "OVERREACTION_STUDY §2"},
        {"Rule": "Deeper is not better", "Evidence": "−1.2 ≈ −0.8 ≈ −0.5", "Source": "STRATEGY_REVIEW §5.4"},
        {"Rule": "Not within 20 days of earnings", "Evidence": "+0.80pp at 20 days, t = 2.35, "
         "stable in both halves", "Source": "OVERREACTION_STUDY §4"},
        {"Rule": "Market-wide cause", "Evidence": "Market-driven dips beat company-specific ones "
         "at every horizon", "Source": "OVERREACTION_STUDY §5"},
        {"Rule": "Not falling alone", "Evidence": "Lone fallers were weakest: +1.04pp vs +2.60pp at 60 days",
         "Source": "OVERREACTION_STUDY §5"},
        {"Rule": "Never sell", "Evidence": "No exit rule survived testing; return rises toward buy-and-hold",
         "Source": "STRATEGY_REVIEW §5.19"},
        {"Rule": "Many sectors", "Evidence": "−30% worst drop vs −51% for tech only, same rules",
         "Source": "PORTFOLIO_STUDY §1"},
    ]), width="stretch", hide_index=True)

    section("Other screens (reference — the app uses the evidence screen)")
    st.dataframe(pd.DataFrame([{"Screen": s.name, "Rules": s.tagline, "Evidence": s.evidence.replace("**", "")}
                               for s in SCREENS.values()]), width="stretch", hide_index=True)

    section("Tested and failed")
    st.dataframe(pd.DataFrame([
        {"Idea": "Re-optimise entry / trail settings", "Result": "−11.8pp vs freezing them"},
        {"Idea": "Tighter trailing stop", "Result": "Worse at every setting"},
        {"Idea": "Only buy dips in momentum leaders", "Result": "Much worse"},
        {"Idea": "200-day-average regime filter", "Result": "Cut returns by two thirds"},
        {"Idea": "Core position + dip lots", "Result": "Worse than holding"},
        {"Idea": "Partial profit-taking", "Result": "Worse at every setting"},
        {"Idea": "Volume as a news signal", "Result": "No effect; flips sign"},
        {"Idea": "Stacking every filter", "Result": "Significance disappears"},
        {"Idea": "Sell after a fixed number of days", "Result": "Worse than holding"},
        {"Idea": "Model-based position sizing", "Result": "Just a volatility bet in disguise"},
        {"Idea": "Cap per stock", "Result": "Costs return, no risk benefit"},
        {"Idea": "Insider buying → hold tech for weeks (insider-trading repo, H8)", "Result": "No edge"},
    ]), width="stretch", hide_index=True)

    section("What this is worth")
    st.info("The buy-zone edge is about **+0.3–0.4pp per trade**, gone by ~120 days. On $10,000 "
            "that's a few hundred dollars a year while the stocks swing thousands. How much you "
            "invest, and not panic-selling, matter more than any signal here.")
    st.caption("Research and educational use only. Not investment advice. This app never places an order.")
