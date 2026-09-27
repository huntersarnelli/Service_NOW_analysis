"""
Watchlist tab — the overview. No charts, no headlines (those live in the Stock tab).

  ⭐ Want to buy   one autocomplete box IS the list (type to add, ✕ to remove, saves
                   instantly) + a bar per stock showing how close it is to its dip price
  Your stocks      pick a list, see every stock's status; click a row to open it in
                   the 🔍 Stock tab. Each list is edited with the same autocomplete box.

Widget keys are stable (never contain a ticker), so switching stocks or lists never
leaves a widget in a half-state.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data.brief import watch_rows
from data.signals import BUY_ZONE, NEAR, STATUS_LABEL, YOUR_CALL, classify, move_vs_market, short_reason
from data.tickers import label, ticker_names
from data.watchlists import WANT_TO_BUY, load_watchlists, save_watchlists
from ui.desk_common import section

FAR_PCT = 10.0  # the bar is empty at 10% or more above the dip price
ALL, HOLDINGS = "All my stocks", "Holdings"


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def cached_names() -> dict[str, str]:
    return ticker_names()


def ticker_options(names: dict[str, str], extra: list[str]) -> list[str]:
    """Your tickers first (so they're always valid choices), then every SEC ticker."""
    return list(dict.fromkeys(list(extra) + sorted(names)))


def save_list_from_widget(list_name: str, widget_key: str) -> None:
    """on_change callback: the multiselect's current value becomes the saved list."""
    groups = load_watchlists()
    groups[list_name] = [str(t).strip().upper() for t in st.session_state[widget_key] if str(t).strip()]
    save_watchlists(groups)


def open_in_stock_tab(ticker: str) -> None:
    st.session_state["stock_picker"] = ticker


def render_watch(result, groups, holdings, frames) -> None:
    names = cached_names()
    mine = list(dict.fromkeys([t for ts in groups.values() for t in ts] + [h.ticker for h in holdings]))
    options = ticker_options(names, mine)

    # ── ⭐ Want to buy ────────────────────────────────────────
    section("⭐ Want to buy")
    st.multiselect(
        "Want to buy", options, default=groups.get(WANT_TO_BUY, []), key="edit_want_to_buy",
        format_func=lambda t: label(t, names), accept_new_options=True, label_visibility="collapsed",
        placeholder="Type a ticker or company name to add…",
        on_change=save_list_from_widget, args=(WANT_TO_BUY, "edit_want_to_buy"),
    )
    render_progress(result, groups)

    # ── Your stocks ──────────────────────────────────────────
    section("Your stocks")
    choices = [ALL] + [g for g in groups if g != WANT_TO_BUY] + ([HOLDINGS] if holdings else [])
    choice = st.segmented_control("List", choices, default=ALL, key="list_choice",
                                  label_visibility="collapsed") or ALL
    if choice == ALL:
        tickers = mine
    elif choice == HOLDINGS:
        tickers = [h.ticker for h in holdings]
    else:
        tickers = groups.get(choice, [])

    rows = {r["ticker"]: r for r in result.rows}
    table = stock_table([rows[t] for t in tickers if t in rows], frames)
    missing = [t for t in tickers if t not in rows]
    if table.empty:
        st.caption("No stocks in this list yet.")
    else:
        # A separate table per list means switching lists always starts with no stale selection.
        event = st.dataframe(
            table, hide_index=True, width="stretch", height=min(480, 40 + 35 * len(table)),
            on_select="rerun", selection_mode="single-row", key=f"table::{choice}",
            column_config={
                "Price": st.column_config.NumberColumn(format="$%.2f"),
                "Dip price": st.column_config.NumberColumn(format="$%.2f"),
                "To dip price": st.column_config.NumberColumn(format="%+.1f%%"),
                "5-day": st.column_config.NumberColumn(format="%+.1f%%"),
            },
        )
        picked = event.selection.rows if event is not None else []
        if picked:
            ticker = table.iloc[picked[0]]["Stock"]
            if st.session_state.get("_last_table_pick") != (choice, ticker):
                st.session_state["_last_table_pick"] = (choice, ticker)
                open_in_stock_tab(ticker)
            st.success(f"**{ticker}** is open in the 🔍 Stock tab.")
        else:
            st.caption("Click a row to open that stock in the 🔍 Stock tab.")
    if missing:
        st.caption(f"Loading on next refresh: {', '.join(missing)}")

    if choice not in (ALL, HOLDINGS):
        with st.expander(f"✏️ Edit “{choice}”"):
            key = f"edit_list::{choice}"
            st.multiselect(
                choice, options, default=groups.get(choice, []), key=key,
                format_func=lambda t: label(t, names), accept_new_options=True,
                label_visibility="collapsed", placeholder="Type a ticker or company name to add…",
                on_change=save_list_from_widget, args=(choice, key),
            )
            if st.button(f"Delete the “{choice}” list", key="delete_list"):
                save_watchlists({g: t for g, t in groups.items() if g != choice})
                st.session_state.pop("list_choice", None)
                st.session_state.pop(f"edit_list::{choice}", None)
                st.rerun()
    with st.expander("➕ New list"):
        c1, c2 = st.columns([3, 1])
        name = c1.text_input("List name", key="new_list_name", label_visibility="collapsed",
                             placeholder="e.g. Dividend payers")
        if c2.button("Create", key="create_list", width="stretch"):
            if name.strip() and name.strip() not in groups:
                save_watchlists({**groups, name.strip(): []})
                st.session_state.pop("new_list_name", None)
                st.rerun()


def render_progress(result, groups) -> None:
    watch = watch_rows(result, groups)
    if not watch:
        st.caption("Add stocks above to track how close each is to its dip price.")
        return
    for w in watch:
        if w["state"] == "no data":
            st.caption(f"{w['ticker']}: loading on next refresh")
            continue
        if w["state"] == "crossed":
            st.markdown(f"🎯 **{w['ticker']}** ${w['price']:,.2f} · **below** its dip price "
                        f"${w['dip_price']:,.2f} → {w['would_be']} if it closes here")
            st.progress(1.0)
            continue
        away = -w["distance_pct"]
        flag = "👀 " if w["state"] == "close" else ""
        st.markdown(f"{flag}**{w['ticker']}** ${w['price']:,.2f} · dip price ${w['dip_price']:,.2f} · "
                    f"**{away:.1f}% to go**")
        st.progress(max(0.0, min(1.0, 1 - away / FAR_PCT)))
    st.caption("A full bar means it has reached its dip price. Dips are judged on the closing price.")


def stock_table(rows: list[dict], frames: dict) -> pd.DataFrame:
    order = {BUY_ZONE: 0, YOUR_CALL: 1, NEAR: 2, "": 3}
    out = []
    for r in rows:
        status = classify(r)
        move, _ = move_vs_market(frames, r["ticker"])
        out.append({
            "Stock": r["ticker"],
            "Status": (STATUS_LABEL[status] + (f" · {short_reason(r)}" if status == YOUR_CALL else "")).strip(),
            "Price": r["close"], "Dip price": r["trigger"], "To dip price": r["dist_pct"], "5-day": move,
            "_order": order[status],
        })
    table = pd.DataFrame(out)
    if table.empty:
        return table
    return (table.sort_values(["_order", "To dip price"], ascending=[True, False])
            .drop(columns="_order").reset_index(drop=True))
