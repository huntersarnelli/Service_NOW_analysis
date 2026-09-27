"""Watchlists tab: edit your groups and see how each name stands on the screen today."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data.watchlists import DEFAULT_WATCHLISTS, clean_ticker_list, save_watchlists
from ui.desk_common import section


def watchlist_rows(groups: dict[str, list[str]], screen_rows: list[dict]) -> pd.DataFrame:
    """One row per (group, ticker) with the screen's view of that name today."""
    by_ticker = {r["ticker"]: r for r in screen_rows}
    rows = []
    for group, tickers in groups.items():
        for ticker in tickers:
            r = by_ticker.get(ticker)
            if r is None:
                status = "no data"
            elif r["qualifies"]:
                status = "✅ qualifies"
            elif r["gate_dip"]:
                status = "🟡 dipping, blocked"
            elif pd.notna(r["dist_pct"]) and r["dist_pct"] > -3:
                status = "👀 within 3% of trigger"
            else:
                status = "—"
            rows.append({
                "Group": group, "Ticker": ticker, "Status": status,
                "Price": r["close"] if r else float("nan"),
                "Z": r["z"] if r else float("nan"),
                "Trigger": r["trigger"] if r else float("nan"),
                "To trigger %": r["dist_pct"] if r else float("nan"),
                "Days to earnings": r["days_to_earnings"] if r else float("nan"),
            })
    return pd.DataFrame(rows)


def render_watchlists(groups: dict[str, list[str]], screen_rows: list[dict]) -> None:
    section("Your watchlists today")
    table = watchlist_rows(groups, screen_rows)
    if table.empty:
        st.info("No watchlists yet — add one below.")
    else:
        pick = st.radio("Group", ["All"] + list(groups), horizontal=True)
        shown = table if pick == "All" else table[table["Group"] == pick]
        st.dataframe(
            shown.style.format({
                "Price": "${:,.2f}", "Z": "{:+.2f}", "Trigger": "${:,.2f}",
                "To trigger %": "{:+.1f}%", "Days to earnings": "{:,.0f}",
            }, na_rep="—"),
            width="stretch", hide_index=True, height=min(520, 40 + 35 * len(shown)),
        )
        st.caption(
            "**To trigger %** = how far the price must fall to reach the dip "
            "threshold (Z = −1.2). Names you add are screened like any other, "
            "but the breadth gate is always measured on the original 124 names."
        )

    with st.expander("✏️ Edit watchlists"):
        st.caption("One row per group. Tickers separated by commas or spaces. "
                   "Add rows at the bottom; delete a row to remove a group.")
        editable = pd.DataFrame(
            [{"Group": g, "Tickers": ", ".join(t)} for g, t in groups.items()]
        )
        edited = st.data_editor(editable, num_rows="dynamic", width="stretch", key="watchlist_editor",
                                column_config={"Group": st.column_config.TextColumn(required=True)})
        c1, c2 = st.columns(2)
        if c1.button("💾 Save watchlists", type="primary"):
            new_groups, rejected = {}, []
            for _, row in edited.iterrows():
                name = str(row.get("Group") or "").strip()
                if not name or name == "nan":
                    continue
                valid, bad = clean_ticker_list(str(row.get("Tickers") or ""))
                new_groups[name] = valid
                rejected += bad
            if rejected:
                st.error("Not saved — these don't look like tickers: " + ", ".join(rejected))
            else:
                save_watchlists(new_groups)
                st.success(f"Saved {len(new_groups)} groups.")
                st.rerun()
        if c2.button("↺ Reset to starter groups"):
            save_watchlists({g: list(t) for g, t in DEFAULT_WATCHLISTS.items()})
            st.rerun()
