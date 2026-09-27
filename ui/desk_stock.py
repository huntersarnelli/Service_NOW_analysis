"""
Stock tab — one stock at a time. Search any US stock (autocomplete by ticker or
company name) or arrive here by clicking a row on the Watchlist tab.

  header    status (🟢 / 🟠 / 👀) and the ⭐ Want-to-buy switch
  numbers   price · dip price (and % away) · cause · next earnings
  chart     1M / 3M / 6M / 1Y with the dip-price line
  why       for 🟠 Your call: the reasons and the historical base rate
  news      headlines on a switch (saves the Alpha Vantage daily quota)
  decide    for 🟠 Your call: Buy / Pass, logged and scored on Track record

A stock you look up that isn't screened yet is added for this session and loaded
on the spot. Every widget key is stable (never contains a ticker).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.journal import append_decision, validate_decision
from data.news import get_headlines
from data.screen import add_screen_indicators
from data.signals import BASE_RATE, BUY_ZONE, NEAR, YOUR_CALL, cause, classify, reasons, short_reason
from data.tickers import label
from data.watchlists import WANT_TO_BUY, save_watchlists, toggle_want_to_buy
from ui.desk_common import AMBER, GREEN, GREY, fmt_money, verdict_card
from ui.desk_watch import cached_names, ticker_options

STATUS = {BUY_ZONE: ("🟢 Buy zone", GREEN, "Passes every evidence rule: the market dragged it down, "
                                         "no recent earnings, other stocks falling too."),
          YOUR_CALL: ("🟠 Your call", AMBER, ""),
          NEAR: ("👀 Close to a dip", GREY, "Within 3% of its dip price."),
          "": ("No dip right now", GREY, "")}
RANGES = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252}


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_headlines(ticker: str, key: str) -> dict:
    return get_headlines(ticker, key or None)


def urgent_first(result, groups) -> list[str]:
    """Your stocks, most in need of attention first (for the default pick)."""
    mine = [t for ts in groups.values() for t in ts]
    rows = {r["ticker"]: r for r in result.rows}
    order = {BUY_ZONE: 0, YOUR_CALL: 1, NEAR: 2, "": 3}
    return sorted(dict.fromkeys(mine), key=lambda t: order[classify(rows[t])] if t in rows else 9)


def render_stock(result, spec, groups, frames, benchmark, av_key) -> None:
    names = cached_names()
    mine = urgent_first(result, groups)
    options = ticker_options(names, mine)
    if st.session_state.get("stock_picker") not in options:
        st.session_state["stock_picker"] = mine[0] if mine else "AMZN"
        if st.session_state["stock_picker"] not in options:
            options.insert(0, st.session_state["stock_picker"])

    ticker = st.selectbox("Stock", options, key="stock_picker", format_func=lambda t: label(t, names),
                          accept_new_options=True, placeholder="Type a ticker or company name…",
                          label_visibility="collapsed")
    ticker = str(ticker or "").strip().upper()
    if not ticker:
        return

    row = next((r for r in result.rows if r["ticker"] == ticker), None)
    if row is None:
        extra = st.session_state.setdefault("extra_tickers", [])
        if ticker not in extra:
            extra.append(ticker)  # screened from the next run on, for this session only
            st.rerun()
        st.warning(f"No usable price history for **{ticker}** (needs about 6 months of daily data).")
        return

    render_header(row, groups)
    render_numbers(row)
    render_chart(row, spec, frames, benchmark)
    status = classify(row)
    if status == YOUR_CALL:
        for key, sentence in reasons(row):
            st.markdown(f"**{sentence}**  \n<span class='evidence-note'>{BASE_RATE[key]}</span>",
                        unsafe_allow_html=True)
    if st.toggle("📰 Headlines", key="show_headlines",
                 help="Loads only when switched on (the Alpha Vantage free tier allows ~25 a day)."):
        render_headlines(ticker, av_key)
    elif status == YOUR_CALL:
        st.caption("Switch on 📰 Headlines to see what's behind the drop before you decide.")
    if status == YOUR_CALL:
        render_decision_form(row)


def render_header(row, groups) -> None:
    status, ticker = classify(row), row["ticker"]
    title, colour, sub = STATUS[status]
    if status == YOUR_CALL:
        sub = f"The rules would skip it ({short_reason(row)}). Your judgement decides; log it below."
    verdict_card(f"{ticker} · {title}", sub, colour)
    starred = ticker in groups.get(WANT_TO_BUY, [])
    if st.button("★ Remove from Want to buy" if starred else "⭐ Add to Want to buy", key="star_button"):
        save_watchlists(toggle_want_to_buy(groups, ticker))
        st.session_state.pop("edit_want_to_buy", None)  # let the Watchlist box pick up the change
        st.rerun()


def render_numbers(row) -> None:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Price", fmt_money(row["close"]))
    away = f"{row['dist_pct']:+.1f}% away" if pd.notna(row["dist_pct"]) else None
    m2.metric("Dip price", fmt_money(row["trigger"]), away, delta_color="off",
              help="Where the dip score would hit −1.2. Recalculated daily from the last 20 closes.")
    m3.metric("Cause", cause(row) or "—",
              help="Only for dipping stocks. Market-wide drops historically bounce; company-specific ones drift.")
    days = row.get("days_to_earnings")
    m4.metric("Next earnings", f"{days:.0f} days" if days is not None and pd.notna(days) else "—")


def render_chart(row, spec, frames, benchmark) -> None:
    df = frames.get(row["ticker"])
    if df is None or df.empty:
        return
    window = st.segmented_control("Range", list(RANGES), default="3M", key="chart_range",
                                  label_visibility="collapsed") or "3M"
    d = add_screen_indicators(df, frames[benchmark]).tail(RANGES[window])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d.index, y=d["sma"] + spec.z_entry * d["sd"], name="Dip price",
                             line=dict(width=1.4, color="#8C2F39", dash="dot")))
    fig.add_trace(go.Scatter(x=d.index, y=d["sma"], name="20-day average",
                             line=dict(width=1.0, color="#8B999D")))
    fig.add_trace(go.Scatter(x=d.index, y=d["Close"], name=row["ticker"], line=dict(width=2.3, color="#1F6F54")))
    fig.update_layout(height=300, margin=dict(l=6, r=6, t=6, b=6), hovermode="x unified",
                      legend=dict(orientation="h", y=1.1, x=0))
    st.plotly_chart(fig, width="stretch", key="stock_chart")


def render_headlines(ticker, av_key) -> None:
    news = cached_headlines(ticker, av_key or "")
    if news["has_sentiment"] and news["score_7d"] is not None:
        st.caption(f"Media mood, last 7 days: **{news['badge_7d']}** ({news['score_7d']:+.2f}), information only")
    if news["note"]:
        st.caption(news["note"])
    for a in news["articles"][:8]:
        when = a["published_at"].strftime("%b %d") if a["published_at"] else ""
        mood = f" · {a['sentiment_label']}" if a.get("sentiment_label") else ""
        link = f"[{a['title']}]({a['url']})" if a["url"] else a["title"]
        st.markdown(f"- {link}  \n  <span class='stamp'>{a['source']} · {when}{mood}</span>", unsafe_allow_html=True)


def render_decision_form(row) -> None:
    with st.form("decision_form", clear_on_submit=True):
        st.markdown(f"**{row['ticker']}: Buy or Pass?** Logged either way and scored against QQQ on Track record.")
        c1, c2 = st.columns(2)
        action = c1.radio("Decision", ["Buy", "Pass"], horizontal=True)
        confidence = c2.slider("Confidence", 1, 5, 3)
        thesis = st.text_input("Why? (one line)", placeholder="e.g. lawsuit is a fine, not a business threat")
        if st.form_submit_button("Log decision", type="primary"):
            decision, error = validate_decision({
                "ticker": row["ticker"], "action": action.lower(), "price": row["close"], "status": YOUR_CALL,
                "why_flagged": short_reason(row), "thesis": thesis, "confidence": confidence})
            if error:
                st.error(error)
            else:
                append_decision(decision)
                st.success(f"Logged {action.upper()} {row['ticker']} at {fmt_money(row['close'])}.")
