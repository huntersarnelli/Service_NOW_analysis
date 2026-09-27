"""
Stocks tab: every stock you watch (or hold, or the whole screen), with a plain-
English status. Pick one to see its chart, why it has that status, and — for
🟠 Your call stocks — headlines, the historical base rate, and a Buy / Pass log.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.advisor import CLASSIFICATION_LABEL, DRIFT_COLOR, available as advisor_available, get_advice
from data.journal import append_decision, journal_frame, load_journal, validate_decision
from data.news import get_headlines
from data.screen import add_screen_indicators
from data.signals import (BASE_RATE, BUY_ZONE, NEAR, STATUS_LABEL, YOUR_CALL, cause, classify,
                          move_vs_market, reasons, short_reason)
from data.watchlists import DEFAULT_WATCHLISTS, clean_ticker_list, groups_for_ticker, save_watchlists
from ui.desk_common import AMBER, GREEN, GREY, fmt_money, section, verdict_card

STATUS_COLOUR = {BUY_ZONE: GREEN, YOUR_CALL: AMBER, NEAR: GREY, "": GREY}


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_headlines(ticker: str, key: str) -> dict:
    return get_headlines(ticker, key or None)


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def cached_advice(ticker: str, bar: str, breadth: float, spec_name: str, _row: dict) -> dict:
    return get_advice(_row, breadth, spec_name).to_dict()


def stock_table(rows: list[dict], groups: dict, frames: dict) -> pd.DataFrame:
    """One plain-English row per screened stock."""
    out = []
    for r in rows:
        move, market = move_vs_market(frames, r["ticker"])
        out.append({
            "Stock": r["ticker"],
            "Status": STATUS_LABEL[classify(r)],
            "Why": short_reason(r),
            "Price": r["close"],
            "Dip score": r["z"],
            "Dip price": r["trigger"],
            "To dip price": r["dist_pct"],
            "5-day move": move,
            "Market 5-day": market,
            "Cause": cause(r),
            "Lists": ", ".join(groups_for_ticker(groups, r["ticker"])),
            "Sector": r["sector"],
            "_status": classify(r),
        })
    return pd.DataFrame(out)


def render_stocks(result, spec, groups, holdings, frames, benchmark, av_key) -> None:
    held = {h.ticker for h in holdings}
    table = stock_table(result.rows, groups, frames)
    if table.empty:
        st.info("No stock data right now — try Refresh in a minute.")
        return

    views = ["My watchlists & holdings", "🟢 Buy zone", "🟠 Your call", "👀 Close to a dip", "Everything screened"]
    view = st.radio("Show", views, horizontal=True)
    if view == views[0]:
        mine = set(t for tickers in groups.values() for t in tickers) | held
        shown = table[table["Stock"].isin(mine)]
    elif view == views[4]:
        shown = table
    else:
        wanted = {views[1]: BUY_ZONE, views[2]: YOUR_CALL, views[3]: NEAR}[view]
        shown = table[table["_status"] == wanted]
    order = {BUY_ZONE: 0, YOUR_CALL: 1, NEAR: 2, "": 3}
    shown = shown.assign(_order=shown["_status"].map(order)).sort_values(["_order", "Dip score"])

    if shown.empty:
        st.info("Nothing to show in this view right now.")
    else:
        st.dataframe(
            shown.drop(columns=["_status", "_order"]).style.format({
                "Price": "${:,.2f}", "Dip score": "{:+.2f}", "Dip price": "${:,.2f}",
                "To dip price": "{:+.1f}%", "5-day move": "{:+.1f}%", "Market 5-day": "{:+.1f}%",
            }, na_rep="—"),
            width="stretch", hide_index=True, height=min(480, 40 + 35 * len(shown)),
        )
        st.caption("**Dip score** below −1.2 = dipping. **Dip price** = where the dip score "
                   "would hit −1.2. **To dip price** = how far the price must fall to get there.")

        pick = st.selectbox("Open a stock", shown["Stock"].tolist())
        row = next(r for r in result.rows if r["ticker"] == pick)
        render_detail(row, result, spec, frames, benchmark, av_key)

    render_watchlist_editor(groups)
    render_journal()


def render_detail(row, result, spec, frames, benchmark, av_key) -> None:
    status = classify(row)
    ticker = row["ticker"]
    move, market = move_vs_market(frames, ticker)
    headline = {BUY_ZONE: "🟢 Buy zone — the rules say this dip is worth buying",
                YOUR_CALL: "🟠 Your call — a dip the rules would skip",
                NEAR: "👀 Close to a dip — not there yet",
                "": "Nothing happening"}[status]
    verdict_card(f"{ticker}: {headline}",
                 f"5-day move {move:+.1f}% vs market {market:+.1f}% · "
                 f"price {fmt_money(row['close'])} · dip price {fmt_money(row['trigger'])}",
                 STATUS_COLOUR[status])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Dip score", f"{row['z']:+.2f}", help="How far below its 20-day average, in "
              "units of its normal daily swing. Below −1.2 = dipping.")
    c2.metric("Cause", cause(row) or "—", help="Market-wide = the market dragged it down "
              "(the good kind). Company-specific = its own news.")
    c3.metric("Since earnings", f"{row['days_since_earnings']:.0f} days"
              if row["days_since_earnings"] < 999 else "—")
    c4.metric("Next earnings", f"in {row['days_to_earnings']:.0f} days"
              if row.get("days_to_earnings") is not None and pd.notna(row["days_to_earnings"]) else "—")

    render_chart(row, spec, frames, benchmark)

    if status == YOUR_CALL:
        render_your_call(row, av_key)
    elif status == BUY_ZONE:
        st.success("Passes every rule: the market dragged it down, it is not near earnings, "
                   "and other stocks are falling too. Evidence: +0.3–0.4pp per trade vs a random day.")

    render_advisor(row, result, spec)


def render_chart(row, spec, frames, benchmark) -> None:
    df = frames.get(row["ticker"])
    if df is None or df.empty:
        return
    d = add_screen_indicators(df, frames[benchmark]).tail(180)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=d.index, y=d["sma"], name="20-day average",
                             line=dict(width=1.2, dash="dot", color="#8B999D")))
    fig.add_trace(go.Scatter(x=d.index, y=d["sma"] + spec.z_entry * d["sd"], name="Dip price",
                             line=dict(width=1.4, color="#8C2F39")))
    fig.add_trace(go.Scatter(x=d.index, y=d["Close"], name=row["ticker"],
                             line=dict(width=2.1, color="#1F6F54")))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                      hovermode="x unified", legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig, width="stretch")


def render_your_call(row, av_key) -> None:
    section("Your call — what the rules can't read")
    for key, sentence in reasons(row):
        st.markdown(f"- **{sentence}**  \n  <span class='evidence-note'>{BASE_RATE[key]}</span>",
                    unsafe_allow_html=True)

    st.markdown("**Headlines**")
    news = cached_headlines(row["ticker"], av_key or "")
    if news["note"]:
        st.caption(news["note"])
    if news["has_sentiment"]:
        s7 = news["score_7d"]
        st.metric("Media mood, last 7 days", news["badge_7d"],
                  f"{s7:+.2f}" if s7 is not None else None,
                  help="Average Alpha Vantage sentiment, −1 (bearish) to +1 (bullish). "
                       "Information only — never tested as a signal.")
    for article in news["articles"][:10]:
        when = article["published_at"].strftime("%b %d") if article["published_at"] else ""
        mood = f" · {article['sentiment_label']}" if article.get("sentiment_label") else ""
        link = f"[{article['title']}]({article['url']})" if article["url"] else article["title"]
        st.markdown(f"- {link}  \n  <span class='stamp'>{article['source']} · {when}{mood}</span>",
                    unsafe_allow_html=True)
    st.caption(f"Source: {news['source']}. Headlines are context for your judgement, not a signal.")

    st.markdown("**Log your decision** — buys *and* passes, so the journal can score your judgement.")
    with st.form(f"decision_{row['ticker']}", clear_on_submit=True):
        action = st.radio("Decision", ["Buy", "Pass"], horizontal=True)
        thesis = st.text_input("Why? (one line)", placeholder="e.g. lawsuit is a fine, not a business threat")
        confidence = st.slider("Confidence", 1, 5, 3)
        if st.form_submit_button("Log decision", type="primary"):
            decision, error = validate_decision({
                "ticker": row["ticker"], "action": action.lower(), "price": row["close"],
                "status": YOUR_CALL, "why_flagged": short_reason(row), "thesis": thesis,
                "confidence": confidence, "media_score_7d": news.get("score_7d"),
            })
            if error:
                st.error(error)
            else:
                append_decision(decision)
                st.success(f"Logged: {action.upper()} {row['ticker']} at {fmt_money(row['close'])}.")


def render_advisor(row, result, spec) -> None:
    with st.expander("🤖 AI advisor read (advisory only — never tested)"):
        ok, why = advisor_available()
        if not ok:
            st.caption(f"Unavailable — {why}")
            return
        st.caption("Characterises *why* the stock fell. Caution: asked 'is there risk?', a model "
                   "says yes almost every time — every dipping stock has a scary story.")
        if st.button(f"Ask about {row['ticker']}", key=f"advisor_{row['ticker']}"):
            bar = str(row["last_bar"].date() if hasattr(row["last_bar"], "date") else row["last_bar"])
            with st.spinner("Asking Claude…"):
                advice = cached_advice(row["ticker"], bar, float(result.breadth), spec.name, row)
            if advice.get("error"):
                st.error(advice["error"])
                return
            verdict_card(CLASSIFICATION_LABEL.get(advice["classification"], advice["classification"]),
                         f"Drift risk: <b>{advice['drift_risk'].upper()}</b>",
                         DRIFT_COLOR.get(advice["drift_risk"], GREY))
            st.write(advice["summary"])
            for issue in advice.get("known_issues") or []:
                st.markdown(f"- {issue}")
            if advice.get("knowledge_caveat"):
                st.info(advice["knowledge_caveat"])


def render_watchlist_editor(groups) -> None:
    with st.expander("✏️ Edit watchlists"):
        st.caption("One row per group; tickers separated by commas or spaces. "
                   "Stocks you add are screened like any other.")
        edited = st.data_editor(
            pd.DataFrame([{"Group": g, "Tickers": ", ".join(t)} for g, t in groups.items()]),
            num_rows="dynamic", width="stretch", key="watchlist_editor",
            column_config={"Group": st.column_config.TextColumn(required=True)},
        )
        c1, c2 = st.columns(2)
        if c1.button("💾 Save watchlists", type="primary"):
            new_groups, rejected = {}, []
            for _, r in edited.iterrows():
                name = str(r.get("Group") or "").strip()
                if not name or name == "nan":
                    continue
                valid, bad = clean_ticker_list(str(r.get("Tickers") or ""))
                new_groups[name] = valid
                rejected += bad
            if rejected:
                st.error("Not saved — these don't look like tickers: " + ", ".join(rejected))
            else:
                save_watchlists(new_groups)
                st.rerun()
        if c2.button("↺ Reset to starter groups"):
            save_watchlists({g: list(t) for g, t in DEFAULT_WATCHLISTS.items()})
            st.rerun()


def render_journal() -> None:
    decisions = load_journal()
    with st.expander(f"📓 Your decision log ({len(decisions)})"):
        if not decisions:
            st.caption("No decisions yet. Your-call stocks have a Buy / Pass form.")
            return
        st.dataframe(journal_frame(decisions).style.format({"Price": "${:,.2f}"}),
                     width="stretch", hide_index=True)
        st.caption("Build 2 adds how each call did vs QQQ at 20 and 60 trading days. "
                   "Judge your edge after ~30 calls, not 3.")
