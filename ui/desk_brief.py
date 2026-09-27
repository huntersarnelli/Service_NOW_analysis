"""
Brief tab — the morning to-do list. Phone-first: one narrow column of cards,
most important first, every card an action. Details live in expanders.
The same brief (data/brief.py) will be sent to Telegram at 8:45am ET.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from data.brief import brief_text, build_brief
from data.insider_feed import scan as insider_scan
from data.paper_trades import add_signals, load_trades
from data.screen import SECTORS
from ui.desk_common import fmt_money
from ui.desk_portfolio import portfolio_snapshot

CARD_COLOUR = {"insider": "#1F4E8C", "gap": "#8C2F39", "your_call": "#8A6014",
               "buy_zone": "#1F6F54", "earnings": "#64757B"}

BRIEF_CSS = """
<style>
  .brief-head { font-size: 1.6rem; font-weight: 700; margin: 0.2rem 0 0.1rem; }
  .brief-sub  { font-size: 0.85rem; opacity: 0.65; margin-bottom: 0.8rem; }
  .chip { display: inline-block; padding: 3px 10px; margin: 0 6px 6px 0; border-radius: 12px;
          font-size: 0.82rem; background: rgba(128,128,128,0.12); }
  .brief-card { border-left: 5px solid var(--c); background: rgba(128,128,128,0.07);
                border-radius: 6px; padding: 0.75rem 0.9rem; margin: 0 0 0.6rem; }
  .brief-title { font-size: 1.05rem; font-weight: 650; line-height: 1.3; }
  .brief-detail { font-size: 0.88rem; opacity: 0.8; margin-top: 0.2rem; line-height: 1.4; }
  .brief-quiet { text-align: center; padding: 1.4rem 0.6rem; opacity: 0.75; }
</style>
"""


def as_of_label(premarket: pd.DataFrame) -> str:
    if premarket is None or premarket.empty or not premarket["as_of"].notna().any():
        return ""
    latest = premarket["as_of"].dropna().max()
    session = premarket.loc[premarket["as_of"] == latest, "session"].iloc[0]
    return f"{latest:%a %b %d, %I:%M %p} ET · {session}"


def render_brief(result, qualifying, cash, max_names, groups, holdings, frames, premarket) -> None:
    st.markdown(BRIEF_CSS, unsafe_allow_html=True)
    pending = [t for t in load_trades() if t.status == "pending"]
    brief = build_brief(result, groups, holdings, premarket, pending)
    as_of = as_of_label(premarket)

    # Phone-width column in the middle of the page; on a phone Streamlit stacks columns,
    # so the brief fills the screen there.
    _, centre, _ = st.columns([1, 2.2, 1])
    with centre:
        st.markdown(f"<div class='brief-head'>☀️ Morning brief</div><div class='brief-sub'>{as_of}</div>",
                    unsafe_allow_html=True)
        if brief["market"]:
            st.markdown("".join(f"<span class='chip'>{m}</span>" for m in brief["market"]),
                        unsafe_allow_html=True)

        if brief["quiet"]:
            st.markdown("<div class='brief-card brief-quiet' style='--c:#64757B'>✅ Nothing needs you today."
                        "<br>No buy-zone stocks, no insider buys, no big moves in your stocks.</div>",
                        unsafe_allow_html=True)
        for item in brief["items"]:
            st.markdown(
                f"<div class='brief-card' style='--c:{CARD_COLOUR[item['kind']]}'>"
                f"<div class='brief-title'>{item['icon']} {item['title']}</div>"
                f"<div class='brief-detail'>{item['detail']}</div></div>",
                unsafe_allow_html=True,
            )
        st.caption("🟢 tested rule · ⚡ tested in tech, paper only · 🟠 your judgement, logged · "
                   "🔻🔺📅 information. Open a stock in **Stocks** for its chart and headlines.")

        render_your_stocks_now(groups, holdings, premarket)
        if qualifying:
            render_buy_zone(qualifying, cash, max_names)
        with st.expander("⚡ Scan SEC filings for insider buys"):
            render_insider_scan(result, frames)
        if holdings:
            with st.expander("📁 Your portfolio"):
                snap = portfolio_snapshot(holdings, frames)
                gain_pct = snap["gain"] / snap["cost"] * 100 if snap["cost"] else float("nan")
                st.metric("Value", fmt_money(snap["value"]))
                st.metric("Total gain", fmt_money(snap["gain"]),
                          f"{gain_pct:+.1f}%" if pd.notna(gain_pct) else None)
                st.metric("Last session", fmt_money(snap["day_change"]))
        with st.expander("📱 Telegram preview (what the 8:45am message will say)"):
            st.code(brief_text(brief, as_of or "today"), language=None)


def render_your_stocks_now(groups, holdings, premarket) -> None:
    mine = list(dict.fromkeys([t for tickers in groups.values() for t in tickers] + [h.ticker for h in holdings]))
    with st.expander("📈 Your stocks right now (incl. pre-market / after hours)"):
        if premarket is None or premarket.empty:
            st.caption("No extended-hours data right now.")
            return
        table = premarket[premarket["ticker"].isin(mine)].sort_values("move_pct")
        st.dataframe(
            table[["ticker", "price", "move_pct", "session"]]
            .rename(columns={"ticker": "Stock", "price": "Price", "move_pct": "Move", "session": "When"})
            .style.format({"Price": "${:,.2f}", "Move": "{:+.1f}%"}, na_rep="—"),
            width="stretch", hide_index=True, height=min(420, 40 + 35 * len(table)),
        )
        st.caption("Move = latest price vs the last regular close. Pre-market moves are information, "
                   "not a tested signal.")


def render_buy_zone(qualifying, cash, max_names) -> None:
    picks = qualifying[:max_names]
    per = cash / len(picks)
    with st.expander(f"🟢 How to split {fmt_money(cash)} of new cash"):
        st.dataframe(
            pd.DataFrame([{"Stock": p["ticker"], "Price": p["close"], "Invest": per,
                           "Shares (approx)": per / p["close"] if p["close"] else np.nan} for p in picks])
            .style.format({"Price": "${:,.2f}", "Invest": "${:,.2f}", "Shares (approx)": "{:,.3f}"}),
            width="stretch", hide_index=True,
        )


def render_insider_scan(result, frames) -> None:
    st.caption(
        "Checks the SEC's live Form 4 feed for open-market insider **purchases** in the stocks this app "
        "screens. Backtest (tech, 2013–2026): buying at the first open after the filing beat random days "
        "by ~+0.5pp same day and ~+0.7pp by the next close. About 70% of the move happens overnight, so "
        "scan in the **evening or before 9:30 ET**. The feed only holds about the last business day, so "
        "scan daily. Every passing signal is logged as a **paper trade** (Track record tab)."
    )
    if st.button("⚡ Scan EDGAR now", type="primary"):
        screened = {r["ticker"] for r in result.rows}
        trading_days = pd.DatetimeIndex(frames["SPY"].index)
        bar = st.progress(0.0, text="Reading the SEC feed…")

        def progress(i, n):
            bar.progress(i / n, text=f"Checking filing {i} of {n}…")
        try:
            found = insider_scan(48, screened, SECTORS, frames, trading_days, progress)
        except Exception as exc:  # noqa: BLE001 -- network / SEC hiccup
            st.error(f"Scan failed: {exc}. The SEC throttles at times — try again in a minute.")
            return
        bar.empty()
        st.session_state["insider_scan"] = found
        added = add_signals(found)
        st.success(f"{len(found)} insider purchase filing(s) in your stocks; {added} new paper trade(s) logged.")
    found = st.session_state.get("insider_scan")
    if found is None:
        return
    if found.empty:
        st.caption("No insider purchases in your stocks in the feed. (Sales and grants are ignored.)")
        return
    view = found.assign(
        Signal=found["passes"].map({True: "✅ paper trade", False: "skipped"}),
        Plan=[f"buy at {t} on {d}" for t, d in zip(found["entry_type"], found["entry_date"])],
        Sector=found["tested_sector"].map({True: "tech (tested)", False: "untested"}),
    )
    st.dataframe(
        view[["Signal", "ticker", "insider", "role", "value_usd", "accepted", "Plan", "Sector", "fails"]]
        .rename(columns={"ticker": "Stock", "insider": "Insider", "role": "Role", "value_usd": "Bought $",
                         "accepted": "Filed (ET)", "fails": "Why skipped"})
        .style.format({"Bought $": "${:,.0f}"}),
        width="stretch", hide_index=True,
    )
