"""
Watchlist tab — stock-first. Top: ⭐ Want to buy with a bar showing how close each
stock is to its dip price. Then one table of your stocks (filter by list, or look
up any ticker); click a row to open that stock: status, 4 numbers, chart,
headlines on request, and Buy / Pass for 🟠 Your call stocks. Lists are edited
with simple add / remove controls at the bottom.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.brief import watch_rows
from data.journal import append_decision, validate_decision
from data.news import get_headlines
from data.screen import add_screen_indicators
from data.signals import (BASE_RATE, BUY_ZONE, NEAR, STATUS_LABEL, YOUR_CALL, cause, classify,
                          move_vs_market, reasons, short_reason)
from data.watchlists import WANT_TO_BUY, clean_ticker_list, groups_for_ticker, save_watchlists, toggle_want_to_buy
from ui.desk_common import AMBER, GREEN, GREY, fmt_money, section, verdict_card

STATUS_COLOUR = {BUY_ZONE: GREEN, YOUR_CALL: AMBER, NEAR: GREY, "": GREY}
FAR_PCT = 10.0  # the progress bar is empty at 10% or more above the dip price


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_headlines(ticker: str, key: str) -> dict:
    return get_headlines(ticker, key or None)


def render_watch(result, spec, groups, holdings, frames, benchmark, av_key) -> None:
    rows = {r["ticker"]: r for r in result.rows}
    render_want_to_buy(result, groups)

    section("Your stocks")
    held = [h.ticker for h in holdings]
    lists = ["All"] + [g for g in groups if g != WANT_TO_BUY] + (["Holdings"] if held else [])
    picked_list = st.pills("List", lists, default="All", label_visibility="collapsed") or "All"
    if picked_list == "All":
        tickers = list(dict.fromkeys([t for ts in groups.values() for t in ts] + held))
    elif picked_list == "Holdings":
        tickers = held
    else:
        tickers = groups.get(picked_list, [])

    lookup = st.text_input("Look up any stock", placeholder="Ticker, e.g. COST").strip().upper()
    if lookup:
        tickers = [lookup]

    table = stock_rows([rows[t] for t in tickers if t in rows], groups, frames)
    if lookup and lookup not in rows:
        st.info(f"{lookup} isn't screened yet. Add it to a list below and it will be on the next refresh.")
    if table.empty:
        render_list_manager(groups)
        return

    event = st.dataframe(
        table.drop(columns=["_order"]), hide_index=True, width="stretch",
        height=min(460, 40 + 35 * len(table)), on_select="rerun", selection_mode="single-row",
        key="watch_table",
        column_config={
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Dip price": st.column_config.NumberColumn(format="$%.2f"),
            "To dip price": st.column_config.NumberColumn(format="%+.1f%%"),
            "5-day": st.column_config.NumberColumn(format="%+.1f%%"),
        },
    )
    selected = event.selection.rows if event is not None else []
    ticker = table.iloc[selected[0]]["Stock"] if selected else table.iloc[0]["Stock"]
    st.caption("Click a row to open it. Sorted by what needs you first.")

    render_detail(rows[ticker], groups, spec, frames, benchmark, av_key)
    render_list_manager(groups)


def render_want_to_buy(result, groups) -> None:
    section("⭐ Want to buy")
    watch = watch_rows(result, groups)
    if not watch:
        st.caption("Empty. Open any stock below and press ⭐ to track it against its dip price.")
        return
    for w in watch:
        if w["state"] == "no data":
            st.caption(f"{w['ticker']}: no data yet (refresh after adding)")
            continue
        if w["state"] == "crossed":
            label = f"🎯 **{w['ticker']}** ${w['price']:,.2f}: **below** its dip price ${w['dip_price']:,.2f} → {w['would_be']} if it closes here"
            closeness = 1.0
        else:
            away = -w["distance_pct"]
            flag = "👀 " if w["state"] == "close" else ""
            label = f"{flag}**{w['ticker']}** ${w['price']:,.2f} · dip price ${w['dip_price']:,.2f} · {away:.1f}% to go"
            closeness = max(0.0, min(1.0, 1 - away / FAR_PCT))
        st.markdown(label)
        st.progress(closeness)
    st.caption("A full bar means the stock has reached its dip price. Dips are judged on the close.")


def stock_rows(rows: list[dict], groups: dict, frames: dict) -> pd.DataFrame:
    order = {BUY_ZONE: 0, YOUR_CALL: 1, NEAR: 2, "": 3}
    out = []
    for r in rows:
        status = classify(r)
        move, _ = move_vs_market(frames, r["ticker"])
        out.append({
            "Stock": r["ticker"],
            "Status": (STATUS_LABEL[status] + (f" · {short_reason(r)}" if status == YOUR_CALL else "")).strip(),
            "Price": r["close"], "Dip price": r["trigger"], "To dip price": r["dist_pct"], "5-day": move,
            "Lists": ", ".join(g.replace(WANT_TO_BUY, "⭐") for g in groups_for_ticker(groups, r["ticker"])),
            "_order": order[status],
        })
    table = pd.DataFrame(out)
    if table.empty:
        return table
    return table.sort_values(["_order", "To dip price"], ascending=[True, False]).reset_index(drop=True)


def render_detail(row, groups, spec, frames, benchmark, av_key) -> None:
    status, ticker = classify(row), row["ticker"]
    headline = {BUY_ZONE: "🟢 Buy zone", YOUR_CALL: "🟠 Your call", NEAR: "👀 Close to a dip",
                "": "No dip right now"}[status]
    sub = short_reason(row) if status == YOUR_CALL else ("passes every evidence rule" if status == BUY_ZONE else "")
    verdict_card(f"{ticker} · {headline}", sub, STATUS_COLOUR[status])

    starred = ticker in groups.get(WANT_TO_BUY, [])
    c_star, c_news = st.columns(2)
    if c_star.button("★ Remove from Want to buy" if starred else "⭐ Add to Want to buy",
                     key=f"star_{ticker}", width="stretch"):
        save_watchlists(toggle_want_to_buy(groups, ticker))
        st.rerun()
    show_news = c_news.toggle("📰 Headlines", key=f"news_{ticker}", value=(status == YOUR_CALL))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Price", fmt_money(row["close"]))
    m2.metric("Dip price", fmt_money(row["trigger"]), f"{row['dist_pct']:+.1f}%" if pd.notna(row["dist_pct"]) else None,
              delta_color="off", help="Where the dip score would hit −1.2 (recalculated daily).")
    m3.metric("Cause", cause(row) or "—", help="Market-wide drops historically bounce; company-specific ones drift.")
    m4.metric("Next earnings", f"{row['days_to_earnings']:.0f} days" if row.get("days_to_earnings") is not None
              and pd.notna(row["days_to_earnings"]) else "—")

    render_chart(row, spec, frames, benchmark)

    if status == YOUR_CALL:
        for key, sentence in reasons(row):
            st.markdown(f"**{sentence}** <span class='evidence-note'>{BASE_RATE[key]}</span>", unsafe_allow_html=True)
    if show_news:
        render_headlines(ticker, av_key)
    if status == YOUR_CALL:
        render_decision_form(row)


def render_chart(row, spec, frames, benchmark) -> None:
    df = frames.get(row["ticker"])
    if df is None or df.empty:
        return
    d = add_screen_indicators(df, frames[benchmark]).tail(120)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d.index, y=d["sma"] + spec.z_entry * d["sd"], name="Dip price",
                             line=dict(width=1.3, color="#8C2F39", dash="dot")))
    fig.add_trace(go.Scatter(x=d.index, y=d["Close"], name=row["ticker"], line=dict(width=2.2, color="#1F6F54")))
    fig.update_layout(height=260, margin=dict(l=8, r=8, t=8, b=8), hovermode="x unified",
                      legend=dict(orientation="h", y=1.12), showlegend=True)
    st.plotly_chart(fig, width="stretch")


def render_headlines(ticker, av_key) -> None:
    news = cached_headlines(ticker, av_key or "")
    if news["has_sentiment"] and news["score_7d"] is not None:
        st.caption(f"Media mood, 7 days: **{news['badge_7d']}** ({news['score_7d']:+.2f}) · information only")
    if news["note"]:
        st.caption(news["note"])
    for a in news["articles"][:8]:
        when = a["published_at"].strftime("%b %d") if a["published_at"] else ""
        mood = f" · {a['sentiment_label']}" if a.get("sentiment_label") else ""
        link = f"[{a['title']}]({a['url']})" if a["url"] else a["title"]
        st.markdown(f"- {link} <span class='stamp'>{a['source']} · {when}{mood}</span>", unsafe_allow_html=True)


def render_decision_form(row) -> None:
    with st.form(f"decision_{row['ticker']}", clear_on_submit=True, border=True):
        st.markdown("**Your call: Buy or Pass?** Logged either way, and scored on Track record.")
        c1, c2 = st.columns([1, 1])
        action = c1.radio("Decision", ["Buy", "Pass"], horizontal=True, label_visibility="collapsed")
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


def render_list_manager(groups) -> None:
    with st.expander("✏️ Manage lists"):
        names = list(groups)
        c1, c2, c3 = st.columns([2, 2, 1])
        new_tickers = c1.text_input("Add ticker(s)", placeholder="AMZN, COST", key="add_tickers")
        target = c2.selectbox("to list", names, key="add_target")
        if c3.button("Add", width="stretch"):
            valid, bad = clean_ticker_list(new_tickers)
            if bad:
                st.error("Not tickers: " + ", ".join(bad))
            elif valid:
                updated = {g: list(t) for g, t in groups.items()}
                updated[target] += [t for t in valid if t not in updated[target]]
                save_watchlists(updated)
                st.rerun()

        c1, c2, c3 = st.columns([2, 2, 1])
        from_list = c1.selectbox("Remove from list", names, key="rm_list")
        victim = c2.selectbox("ticker", groups.get(from_list, []) or ["—"], key="rm_ticker")
        if c3.button("Remove", width="stretch") and victim != "—":
            updated = {g: list(t) for g, t in groups.items()}
            updated[from_list].remove(victim)
            save_watchlists(updated)
            st.rerun()

        c1, c2 = st.columns([4, 1])
        new_list = c1.text_input("New list name", key="new_list")
        if c2.button("Create", width="stretch") and new_list.strip() and new_list.strip() not in groups:
            save_watchlists({**groups, new_list.strip(): []})
            st.rerun()
        deletable = [g for g in names if g != WANT_TO_BUY]
        c1, c2 = st.columns([4, 1])
        doomed = c1.selectbox("Delete a list", ["—"] + deletable, key="del_list")
        if c2.button("Delete", width="stretch") and doomed != "—":
            save_watchlists({g: t for g, t in groups.items() if g != doomed})
            st.rerun()
