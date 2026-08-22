"""
Portfolio tab — your real lots, and where the rules say to get out.

Everything here is driven by an entry price and date you type in, not by the
old "assume the last signal cluster was my entry" inference. The trailing stop
is drawn as the path it actually takes, not a single flat level.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.portfolio import (
    LOT_COLUMNS,
    Lot,
    aggregate_positions,
    frame_to_lots,
    lots_to_frame,
)
from data.strategies import SPEC_LABELS, StrategySpec, evaluate_lot, get_spec

_EDITOR_KEY = "portfolio_lot_editor"


def _template() -> str:
    return "plotly_dark" if _is_dark() else "plotly_white"


def _is_dark() -> bool:
    """Viewer's actual theme. st.get_option reads the config file, not the user."""
    try:
        return str(st.context.theme.type).lower() == "dark"
    except Exception:
        try:
            return st.get_option("theme.base") == "dark"
        except Exception:
            return False


def _fmt_price(x) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"${x:,.2f}"


def _fmt_pct(x) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:+.2f}%"


def _fmt_r(x) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    return f"{x:+.2f}R"


def _status_badge(status: str, reason: Optional[str] = None) -> str:
    if status == "EXIT":
        label = f"EXIT — {reason}" if reason else "EXIT"
        return f'<span class="sell-badge">{label}</span>'
    if status == "HOLD":
        return '<span class="hold-badge">HOLD</span>'
    if status == "NO DATA":
        return '<span class="neutral-badge">NO DATA</span>'
    return '<span class="neutral-badge">—</span>'


# ─────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────
def evaluate_all(
    lots: list[Lot],
    frames_by_strategy: dict[str, dict[str, pd.DataFrame]],
    spec_overrides: Optional[dict] = None,
) -> list[dict]:
    """
    Attach a rule evaluation to every lot. Never raises on bad data.

    Frames are keyed by strategy because each rule set computes its indicators
    with its own windows — a lot tagged "dip" must be measured with dip windows
    even while the sidebar is showing the tactical strategy.
    """
    rows: list[dict] = []
    for lot in lots:
        spec = get_spec(lot.strategy)
        if spec_overrides and lot.strategy in spec_overrides:
            spec = spec_overrides[lot.strategy]

        frames = frames_by_strategy.get(lot.strategy) or {}
        df = frames.get(lot.ticker)
        ev = (
            evaluate_lot(df, spec, lot.entry_ts, lot.entry_price, lot.shares)
            if df is not None
            else None
        )
        rows.append({"lot": lot, "spec": spec, "eval": ev, "history": df})
    return rows


def _rows_to_frame(rows: list[dict]) -> pd.DataFrame:
    records = []
    for r in rows:
        lot, spec, ev = r["lot"], r["spec"], r["eval"]
        base = {
            "Ticker": lot.ticker,
            "Strategy": SPEC_LABELS.get(spec.key, spec.key),
            "Shares": lot.shares,
            "Entry": lot.entry_price,
            "Entry Date": lot.entry_date,
            "Cost": lot.cost_basis(),
        }
        if ev is None:
            records.append(
                {
                    **base,
                    "Price": None, "Stop": None, "To Stop %": None,
                    "P&L %": None, "P&L $": None, "R": None,
                    "MFE %": None, "MAE %": None, "Days": None,
                    "Status": "NO DATA",
                }
            )
            continue
        records.append(
            {
                **base,
                "Price": ev["current_close"],
                "Stop": ev["trail"],
                "To Stop %": ev["dist_to_stop_pct"],
                "P&L %": ev["pnl_pct"],
                "P&L $": ev["pnl_dollar"],
                "R": ev["r_multiple"],
                "MFE %": ev["mfe_pct"],
                "MAE %": ev["mae_pct"],
                "Days": ev["days_held"],
                "Status": "EXIT" if ev["status"] == "EXIT" else "HOLD",
            }
        )
    return pd.DataFrame(records)


def _style_positions(df: pd.DataFrame):
    if df.empty:
        return df

    def c_status(v):
        if v == "EXIT":
            return "background-color:#991b1b;color:#fecaca;font-weight:700"
        if v == "HOLD":
            return "background-color:#1e40af;color:#dbeafe;font-weight:600"
        return ""

    def c_signed(v):
        if isinstance(v, (int, float)) and np.isfinite(v):
            if v > 0:
                return "color:#16a34a;font-weight:600"
            if v < 0:
                return "color:#dc2626;font-weight:600"
        return ""

    def c_to_stop(v):
        if isinstance(v, (int, float)) and np.isfinite(v):
            if v <= 0:
                return "color:#dc2626;font-weight:700"
            if v < 5:
                return "color:#ca8a04;font-weight:600"
            return "color:#16a34a"
        return ""

    signed_cols = [c for c in ["P&L %", "P&L $", "R", "MFE %", "MAE %"] if c in df.columns]
    styled = df.style.format(
        {
            "Shares": "{:,.4g}",
            "Entry": "${:,.2f}",
            "Cost": "${:,.2f}",
            "Price": "${:,.2f}",
            "Stop": "${:,.2f}",
            "To Stop %": "{:+.1f}%",
            "P&L %": "{:+.2f}%",
            "P&L $": "${:+,.2f}",
            "R": "{:+.2f}",
            "MFE %": "{:+.1f}%",
            "MAE %": "{:+.1f}%",
            "Days": "{:,.0f}",
        },
        na_rep="—",
    ).map(c_status, subset=["Status"])
    if signed_cols:
        styled = styled.map(c_signed, subset=signed_cols)
    if "To Stop %" in df.columns:
        styled = styled.map(c_to_stop, subset=["To Stop %"])
    return styled


# ─────────────────────────────────────────────────────────────
# Chart with entry markers + the trail path
# ─────────────────────────────────────────────────────────────
def lot_chart(
    history: pd.DataFrame,
    lot: Lot,
    spec: StrategySpec,
    ev: dict,
    lookback_pad: int = 20,
) -> go.Figure:
    """Candles from just before entry, with entry/exit markers and the live stop."""
    entry_idx = ev["entry_index"]
    start = max(entry_idx - lookback_pad, 0)
    win = history.iloc[start:]
    trail = ev["trail_path"]

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=win.index,
            open=win["Open"], high=win["High"], low=win["Low"], close=win["Close"],
            name="Price",
            increasing_line_color="#16a34a",
            decreasing_line_color="#dc2626",
        )
    )

    if "sma" in win.columns:
        sma_name = (
            f"{spec.sma_window}-SMA (mean exit)"
            if spec.mean_reversion_exit
            else f"{spec.sma_window}-SMA"
        )
        fig.add_trace(
            go.Scatter(
                x=win.index, y=win["sma"], name=sma_name,
                line=dict(color="#3b82f6", width=1.4),
            )
        )

    # The stop as it actually moves, not a flat scalar.
    fig.add_trace(
        go.Scatter(
            x=trail.index, y=trail.values, name="Trailing stop",
            line=dict(color="#dc2626", width=2, shape="hv"),
        )
    )

    # Breakeven from entry forward.
    fig.add_trace(
        go.Scatter(
            x=[ev["entry_bar_date"], win.index[-1]],
            y=[lot.entry_price, lot.entry_price],
            name="Your entry",
            line=dict(color="#a855f7", width=1.4, dash="dash"),
        )
    )

    fig.add_trace(
        go.Scatter(
            x=[ev["entry_bar_date"]], y=[lot.entry_price],
            mode="markers+text", name="Entry",
            marker=dict(symbol="triangle-up", size=16, color="#a855f7",
                        line=dict(width=1.5, color="#f5f3ff")),
            text=[f" BUY {lot.shares:g} @ ${lot.entry_price:,.2f}"],
            textposition="middle right",
            textfont=dict(size=11, color="#a855f7"),
            showlegend=False,
        )
    )

    if ev["status"] == "EXIT" and ev["exit_date"] is not None:
        fig.add_trace(
            go.Scatter(
                x=[ev["exit_date"]], y=[ev["exit_price"]],
                mode="markers+text", name="Exit",
                marker=dict(symbol="x", size=14, color="#dc2626",
                            line=dict(width=1.5, color="#fee2e2")),
                text=[f" EXIT ${ev['exit_price']:,.2f} ({ev['exit_reason']})"],
                textposition="middle right",
                textfont=dict(size=11, color="#dc2626"),
                showlegend=False,
            )
        )

    title = f"{lot.ticker} — entry {lot.entry_date} · {spec.name}"
    fig.update_layout(
        title=title,
        xaxis_rangeslider_visible=False,
        height=440,
        margin=dict(l=40, r=40, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        template=_template(),
        hovermode="x unified",
    )
    return fig


# ─────────────────────────────────────────────────────────────
# Sections
# ─────────────────────────────────────────────────────────────
def _render_editor(lots: list[Lot], store, universe: list[str]) -> list[Lot]:
    st.markdown("#### Your positions")
    st.caption(
        "One row per purchase. Add, edit, or delete rows, then Save. "
        "Pyramiding into the same name is fine — each lot keeps its own stop."
    )

    df = lots_to_frame(lots)
    if df.empty:
        df = pd.DataFrame(columns=LOT_COLUMNS)
    display = df.copy()
    if not display.empty:
        display["entry_date"] = pd.to_datetime(display["entry_date"]).dt.date

    edited = st.data_editor(
        display,
        num_rows="dynamic",
        width="stretch",
        key=_EDITOR_KEY,
        column_order=["ticker", "shares", "entry_price", "entry_date", "strategy", "notes"],
        column_config={
            "id": None,  # hidden; regenerated for new rows
            "ticker": st.column_config.SelectboxColumn(
                "Ticker", options=universe, required=True, width="small"
            ),
            "shares": st.column_config.NumberColumn(
                "Shares", min_value=0.0001, step=1.0, format="%.4g", required=True
            ),
            "entry_price": st.column_config.NumberColumn(
                "Entry $", min_value=0.01, step=0.01, format="$%.2f", required=True
            ),
            "entry_date": st.column_config.DateColumn(
                "Entry date", max_value=date.today(), required=True
            ),
            "strategy": st.column_config.SelectboxColumn(
                "Exit rules",
                options=list(SPEC_LABELS.keys()),
                help="Which rule set governs this lot's stop.",
                width="small",
            ),
            "notes": st.column_config.TextColumn("Notes", width="medium"),
        },
    )

    # data_editor drops the hidden id for newly added rows; restore what we can.
    if "id" not in edited.columns:
        edited = edited.copy()
        edited["id"] = [
            df["id"].iloc[i] if i < len(df) else "" for i in range(len(edited))
        ]

    new_lots, errors = frame_to_lots(edited)

    c1, c2, c3 = st.columns([1, 1, 3])
    saved = c1.button("💾 Save portfolio", type="primary", width="stretch")
    reverted = c2.button("↩ Discard changes", width="stretch")

    if errors:
        for e in errors[:6]:
            st.warning(e)

    if reverted:
        st.session_state.pop(_EDITOR_KEY, None)
        st.rerun()

    if saved:
        if errors:
            st.error("Fix the rows above before saving — nothing was written.")
        else:
            store.save(new_lots)
            st.success(f"Saved {len(new_lots)} lot(s) to {store.label}.")
            st.session_state.pop(_EDITOR_KEY, None)
            st.rerun()

    # Preview against unsaved edits so the tables below stay responsive.
    return new_lots if not errors else lots


def _render_summary(rows: list[dict], capital: float):
    valued = [r for r in rows if r["eval"] is not None]
    if not valued:
        return

    cost = sum(r["lot"].cost_basis() for r in valued)
    value = sum(r["lot"].shares * r["eval"]["current_close"] for r in valued)
    pnl = value - cost
    pnl_pct = (pnl / cost * 100.0) if cost else 0.0
    exits = [r for r in valued if r["eval"]["status"] == "EXIT"]
    holds = [r for r in valued if r["eval"]["status"] == "HOLD"]

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Lots", len(valued))
    k2.metric("Cost basis", _fmt_price(cost))
    k3.metric("Market value", _fmt_price(value))
    k4.metric("Unrealized P&L", _fmt_price(pnl), _fmt_pct(pnl_pct))
    k5.metric("Deployed", f"{(value / capital * 100.0):.0f}%" if capital else "—")

    if exits:
        names = ", ".join(
            f"{r['lot'].ticker} ({r['eval']['exit_reason']})" for r in exits
        )
        st.error(f"**Exit triggered by the rules:** {names}")

    # Concentration: these universes are one factor in several wrappers.
    if value > 0:
        by_ticker: dict[str, float] = {}
        for r in valued:
            if r["eval"]["status"] != "HOLD":
                continue
            v = r["lot"].shares * r["eval"]["current_close"]
            by_ticker[r["lot"].ticker] = by_ticker.get(r["lot"].ticker, 0.0) + v
        if by_ticker:
            top, top_val = max(by_ticker.items(), key=lambda kv: kv[1])
            share = top_val / value * 100.0
            if share >= 40:
                st.warning(
                    f"**Concentration:** {top} is {share:.0f}% of open market value. "
                    "This universe is largely one AI/megacap-tech bet — position "
                    "counts overstate the real diversification."
                )
    if holds:
        tightest = min(holds, key=lambda r: r["eval"]["dist_to_stop_pct"])
        ev = tightest["eval"]
        st.info(
            f"**Closest to a stop:** {tightest['lot'].ticker} at "
            f"{_fmt_price(ev['current_close'])} · stop {_fmt_price(ev['trail'])} "
            f"({ev['dist_to_stop_pct']:+.1f}% away)"
        )


def _render_detail(rows: list[dict]):
    valued = [r for r in rows if r["eval"] is not None]
    if not valued:
        return

    st.markdown("#### Lot detail")
    labels = {
        f"{r['lot'].ticker} · {r['lot'].entry_date} · {r['lot'].shares:g} sh": i
        for i, r in enumerate(valued)
    }
    # Default to whatever is most urgent: an exit, else the tightest stop.
    default = 0
    for i, r in enumerate(valued):
        if r["eval"]["status"] == "EXIT":
            default = i
            break
    else:
        default = min(
            range(len(valued)), key=lambda i: valued[i]["eval"]["dist_to_stop_pct"]
        )

    choice = st.selectbox(
        "Select a lot", list(labels.keys()), index=default, key="portfolio_lot_pick"
    )
    r = valued[labels[choice]]
    lot, spec, ev = r["lot"], r["spec"], r["eval"]

    st.markdown(
        f"### {lot.ticker} {_status_badge(ev['status'], ev.get('exit_reason'))}",
        unsafe_allow_html=True,
    )
    st.caption(
        f"{spec.name} · Stop rule: {spec.trail_label()} · Exit: {spec.exit_label()}"
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Entry", _fmt_price(lot.entry_price))
    c2.metric("Price", _fmt_price(ev["current_close"]))
    c3.metric("P&L", _fmt_pct(ev["pnl_pct"]), _fmt_price(ev["pnl_dollar"]))
    c4.metric("Stop now", _fmt_price(ev["trail"]))
    c5.metric("To stop", _fmt_pct(ev["dist_to_stop_pct"]))
    c6.metric("R-multiple", _fmt_r(ev["r_multiple"]))

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Initial stop", _fmt_price(ev["initial_stop"]))
    c2.metric("Highest close", _fmt_price(ev["highest_close"]))
    c3.metric("Best (MFE)", _fmt_pct(ev["mfe_pct"]))
    c4.metric("Worst (MAE)", _fmt_pct(ev["mae_pct"]))
    c5.metric("Days held", f"{ev['days_held']:,}")
    c6.metric(
        "Mean target" if spec.mean_reversion_exit else "20-SMA",
        _fmt_price(ev["mean_target"]),
    )

    if ev["status"] == "EXIT":
        st.error(
            f"**The rules exited this lot on {pd.Timestamp(ev['exit_date']).date()} "
            f"at {_fmt_price(ev['exit_price'])}** — {ev['exit_reason']}. "
            f"Realized {_fmt_pct(ev['pnl_pct'])} over {ev['days_held']} days. "
            "Metrics above are frozen at the exit bar."
        )
    else:
        give_back = ev["mfe_pct"] - ev["pnl_pct"]
        msg = (
            f"**Hold.** Stop is {_fmt_price(ev['trail'])}, "
            f"{ev['dist_to_stop_pct']:+.1f}% below price "
            f"({_fmt_price(ev['dist_to_stop'])} per share, "
            f"{_fmt_price(ev['dist_to_stop'] * lot.shares)} on this lot)."
        )
        if give_back > 5:
            msg += (
                f"\n\nYou are {give_back:.1f}% off the best close since entry "
                f"({_fmt_price(ev['highest_close'])})."
            )
        st.info(msg)
        if spec.mean_reversion_exit and np.isfinite(ev["mean_target"]):
            if ev["current_close"] >= ev["mean_target"]:
                st.warning(
                    f"Price is at or above the {spec.sma_window}-SMA "
                    f"({_fmt_price(ev['mean_target'])}) — the Z > {spec.z_exit} "
                    "exit is live for this rule set."
                )

    if not ev.get("entry_was_signal", True) and np.isfinite(ev.get("entry_z", np.nan)):
        st.caption(
            f"Note: Z was {ev['entry_z']:+.2f} on your entry date, not below "
            f"{spec.z_entry} — this lot was not opened on a {spec.name} signal. "
            "The exit rules are still applied to it as tagged."
        )

    st.plotly_chart(
        lot_chart(r["history"], lot, spec, ev),
        width="stretch",
        key=f"lotchart_{lot.id}",
    )


def render_portfolio_tab(
    frames_by_strategy: dict[str, dict[str, pd.DataFrame]],
    store,
    capital: float,
    universe: list[str],
    spec_overrides: Optional[dict] = None,
):
    st.markdown(
        "<div class='section-header'>Portfolio — live exits for your real lots</div>",
        unsafe_allow_html=True,
    )

    lots = store.load()
    st.caption(
        f"Storage: {store.label}. "
        "On Streamlit Community Cloud the filesystem is ephemeral — move to the "
        "Sheets backend before relying on this remotely."
    )

    lots = _render_editor(lots, store, universe)

    if not lots:
        st.info(
            "No positions yet. Add a row above with your ticker, share count, "
            "entry price, and entry date, then Save."
        )
        return

    rows = evaluate_all(lots, frames_by_strategy, spec_overrides)
    missing = [r["lot"].ticker for r in rows if r["eval"] is None]

    st.divider()
    _render_summary(rows, capital)

    if missing:
        st.warning(
            "No price history covering the entry date for: "
            + ", ".join(sorted(set(missing)))
            + ". Check the ticker, or the entry may predate the data window."
        )

    st.divider()
    table = _rows_to_frame(rows)
    order = {"EXIT": 0, "HOLD": 1, "NO DATA": 2}
    table["_s"] = table["Status"].map(lambda s: order.get(s, 9))
    table = table.sort_values(["_s", "To Stop %"]).drop(columns=["_s"])
    st.dataframe(_style_positions(table), width="stretch", hide_index=True)

    agg = aggregate_positions(lots)
    if len(agg) < len(lots):
        with st.expander("Blended view (lots combined per ticker)", expanded=False):
            st.dataframe(
                agg.style.format(
                    {"shares": "{:,.4g}", "avg_entry": "${:,.2f}", "cost_basis": "${:,.2f}"}
                ),
                width="stretch",
                hide_index=True,
            )

    st.divider()
    _render_detail(rows)
