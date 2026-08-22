"""
Tactical Trading System — Live Streamlit Dashboard
==================================================
Two strategies, one app. Pick the rule set in the sidebar:

  Dual-Mode Tactical           Z < -1.5 entry, trail = Close - 2xATR (raise
                               only), exit on trail hit OR Z > 0.
                               Momentum bucket + Quality bucket.

  Aggressive Dip Accumulation  Z < -1.2 entry, trail = highest close since
                               entry - 4xATR (frozen at entry), no mean
                               exit, 25% / 35% post-earnings sizing.

Layout
------
app.py                   — entry point, sidebar, strategy tabs
data/market.py           — batched OHLCV, indicators, live levels / signals
data/strategies.py       — the two rule sets + open-lot evaluation
data/portfolio.py        — your lots and where they are stored
data/media_earnings.py   — informational media + earnings (not in signals)
ui/portfolio_tab.py      — portfolio UI, entry markers, trailing-stop path
ui/media_earnings_tab.py — Media & Earnings tab UI
"""

from __future__ import annotations

import os
import warnings
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.market import (
    UNIVERSE,
    compute_indicators,
    get_data_batch,
    get_earnings_batch,
    levels_from_frame,
    required_history_days,
)
from data.portfolio import get_store
from data.strategies import (
    DIP,
    SPECS,
    TACTICAL,
    days_to_next_earnings,
    get_spec,
    is_post_earnings,
    spec_from_overrides,
)
from ui.media_earnings_tab import clear_media_earnings_cache, render_media_earnings_tab
from ui.portfolio_tab import render_portfolio_tab

warnings.filterwarnings("ignore")

DEFAULT_CAPITAL = 100_000.0
DATA_TTL = 120  # seconds

# ─────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Tactical Trading System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    /* Card-like metric containers */
    div[data-testid="stMetric"] {
        background: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.25);
        border-radius: 10px;
        padding: 12px 16px;
    }
    .buy-badge {
        display: inline-block;
        background: #16a34a; color: white; font-weight: 700;
        font-size: 0.85rem; letter-spacing: 0.04em;
        padding: 4px 12px; border-radius: 999px; margin-left: 8px;
    }
    .sell-badge {
        display: inline-block;
        background: #dc2626; color: white; font-weight: 700;
        font-size: 0.85rem; padding: 4px 12px;
        border-radius: 999px; margin-left: 8px;
    }
    .hold-badge {
        display: inline-block;
        background: #2563eb; color: white; font-weight: 600;
        font-size: 0.8rem; padding: 3px 10px;
        border-radius: 999px; margin-left: 8px;
    }
    .post-badge {
        display: inline-block;
        background: #7c3aed; color: white; font-weight: 600;
        font-size: 0.8rem; padding: 3px 10px;
        border-radius: 999px; margin-left: 8px;
    }
    .watch-badge {
        display: inline-block;
        background: #ca8a04; color: white; font-weight: 600;
        font-size: 0.8rem; padding: 3px 10px;
        border-radius: 999px; margin-left: 8px;
    }
    .neutral-badge {
        display: inline-block;
        background: rgba(128,128,128,0.35); color: inherit;
        font-weight: 600; font-size: 0.8rem;
        padding: 3px 10px; border-radius: 999px; margin-left: 8px;
    }
    .section-header {
        font-size: 1.15rem; font-weight: 650; margin: 0.4rem 0 0.6rem 0;
    }
    .subtle { opacity: 0.75; font-size: 0.9rem; }
    .stDataFrame { font-size: 0.92rem; }
    .app-footer {
        margin-top: 2rem; padding-top: 1rem;
        border-top: 1px solid rgba(128,128,128,0.25);
        font-size: 0.85rem; opacity: 0.7;
    }
    .fresh-ts { font-size: 0.8rem; opacity: 0.7; margin-bottom: 0.5rem; }
</style>
""",
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────
# Cached data (one batched request for every symbol)
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=DATA_TTL, show_spinner=False)
def cached_frames(tickers: tuple[str, ...], days: int) -> dict[str, pd.DataFrame]:
    return get_data_batch(list(tickers), days=days)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_earnings(tickers: tuple[str, ...]) -> dict[str, list]:
    return get_earnings_batch(list(tickers))


def clear_all_caches() -> None:
    cached_frames.clear()
    cached_earnings.clear()
    clear_media_earnings_cache()


def is_dark() -> bool:
    """Viewer's actual theme; st.get_option only reads the config file."""
    try:
        return str(st.context.theme.type).lower() == "dark"
    except Exception:
        try:
            return st.get_option("theme.base") == "dark"
        except Exception:
            return False


def chart_template() -> str:
    return "plotly_dark" if is_dark() else "plotly_white"


# ─────────────────────────────────────────────────────────────
# Formatting helpers
# ─────────────────────────────────────────────────────────────
def fmt_price(x: float) -> str:
    return f"${x:,.2f}"


def fmt_pct(x: float) -> str:
    return f"{x:+.2f}%"


def fmt_z(x: float) -> str:
    return f"{x:+.2f}"


def fmt_rr(x: float) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.2f}:1"


def status_badge(status: str, post: bool = False) -> str:
    if status == "BUY":
        badge = '<span class="buy-badge">BUY SIGNAL</span>'
        if post:
            badge += '<span class="post-badge">POST-EARNINGS</span>'
        return badge
    if status == "NEAR":
        return '<span class="watch-badge">NEAR TRIGGER</span>'
    if status == "WATCH":
        return '<span class="watch-badge">WATCH</span>'
    return '<span class="neutral-badge">—</span>'


def rows_to_dataframe(rows: list[dict], dip_mode: bool = False) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    records = []
    for r in rows:
        rec = {
            "Ticker": r["ticker"],
            "Bucket": r["bucket"],
            "Price": r["close"],
            "Z-Score": r["z"],
            "20-SMA": r["sma20"],
            "Trend SMA": r["trend_sma"],
            "ATR": r["atr"],
            "Buy Trigger": r["buy_trigger"],
            "Initial Stop": r["initial_stop"],
            "Mean Exit": r["mean_exit"],
            "Dist $": r["dist_dollar"],
            "Dist %": r["dist_pct"],
            "Risk": r["risk"],
            "Reward": r["reward"],
            "R:R": r["rr"],
            "Trend OK": "✓" if r["trend_ok"] else "✗",
            "Signal": "BUY" if r["signal"] else r["status"],
        }
        if dip_mode:
            rec["Post-Earn"] = "Yes" if r.get("post_earnings") else ""
            rec["Alloc"] = f"{r.get('alloc_pct', 0) * 100:.0f}%"
            rec["Size (sh)"] = r.get("shares", 0)
            rec["To Earnings"] = r.get("days_to_earnings")
        records.append(rec)
    return pd.DataFrame(records)


def style_overview(df: pd.DataFrame, z_entry: float):
    """Conditional formatting for the scanner tables."""
    if df.empty:
        return df

    def color_signal(val):
        if val == "BUY":
            return "background-color: #166534; color: #dcfce7; font-weight: 700"
        if val in ("NEAR", "WATCH"):
            return "background-color: #854d0e; color: #fef9c3; font-weight: 600"
        return ""

    def color_z(val):
        if isinstance(val, (int, float)):
            if val < z_entry:
                return "color: #16a34a; font-weight: 700"
            if val < 0:
                return "color: #ca8a04"
        return ""

    def color_dist(val):
        if isinstance(val, (int, float)):
            if val <= 0:
                return "color: #16a34a; font-weight: 700"
            if val < 5:
                return "color: #ca8a04"
        return ""

    fmt = {
        "Price": "${:,.2f}", "Z-Score": "{:+.2f}", "20-SMA": "${:,.2f}",
        "Trend SMA": "${:,.2f}", "ATR": "${:,.2f}", "Buy Trigger": "${:,.2f}",
        "Initial Stop": "${:,.2f}", "Mean Exit": "${:,.2f}", "Dist $": "${:+,.2f}",
        "Dist %": "{:+.2f}%", "Risk": "${:,.2f}", "Reward": "${:,.2f}",
        "R:R": "{:.2f}:1", "Size (sh)": "{:,.0f}", "To Earnings": "{:,.0f}",
    }
    styled = (
        df.style.format({k: v for k, v in fmt.items() if k in df.columns}, na_rep="—")
        .map(color_signal, subset=["Signal"])
        .map(color_z, subset=["Z-Score"])
        .map(color_dist, subset=["Dist %"])
    )
    return styled


# ─────────────────────────────────────────────────────────────
# Charts
# ─────────────────────────────────────────────────────────────
def price_chart(
    history: pd.DataFrame,
    ticker: str,
    buy_trigger: float,
    initial_stop: float,
    mean_exit: float,
    trend_sma_len: int,
    z_entry: float,
    show_trend: bool = True,
    show_mean_exit: bool = True,
) -> go.Figure:
    """Candles + SMAs + trigger / stop / exit levels."""
    df = history.dropna(subset=["sma"]).copy()
    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"],
            low=df["Low"], close=df["Close"], name="Price",
            increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["sma"], name="20-SMA",
            line=dict(color="#3b82f6", width=1.5),
        )
    )
    if show_trend and "trend_sma" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["trend_sma"], name=f"{trend_sma_len}-SMA",
                line=dict(color="#a855f7", width=1.5, dash="dot"),
            )
        )

    levels = [
        (buy_trigger, f"Buy Trigger (Z={z_entry})", "#16a34a", "dash"),
        (initial_stop, "Initial Stop", "#dc2626", "dot"),
    ]
    if show_mean_exit:
        levels.append((mean_exit, "Mean Exit (Z=0)", "#3b82f6", "dash"))

    x0 = df.index[int(len(df) * 0.55)]
    x1 = df.index[-1]
    for y, name, color, dash in levels:
        fig.add_shape(
            type="line", x0=x0, x1=x1, y0=y, y1=y,
            line=dict(color=color, width=1.5, dash=dash),
        )
        fig.add_annotation(
            x=x1, y=y, text=f" {name} ${y:.2f}", showarrow=False,
            xanchor="left", font=dict(size=11, color=color),
        )

    fig.update_layout(
        title=f"{ticker} — Price & Strategy Levels",
        xaxis_rangeslider_visible=False,
        height=420,
        margin=dict(l=40, r=140, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        template=chart_template(),
    )
    return fig


def zscore_chart(history: pd.DataFrame, ticker: str, z_entry: float) -> go.Figure:
    df = history.dropna(subset=["zscore"]).copy()
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df.index, y=df["zscore"], name="Z-Score",
            line=dict(color="#38bdf8", width=2),
            fill="tozeroy", fillcolor="rgba(56,189,248,0.12)",
        )
    )
    fig.add_hline(
        y=z_entry, line_dash="dash", line_color="#16a34a",
        annotation_text=f"Entry Z = {z_entry}", annotation_position="bottom right",
    )
    fig.add_hline(
        y=0, line_dash="dash", line_color="#3b82f6",
        annotation_text="Z = 0", annotation_position="top right",
    )
    fig.update_layout(
        title=f"{ticker} — Z-Score", height=280,
        margin=dict(l=40, r=40, t=50, b=40),
        template=chart_template(), yaxis_title="Z",
    )
    return fig


# ─────────────────────────────────────────────────────────────
# Scanner sections
# ─────────────────────────────────────────────────────────────
def render_stock_card(r: dict, spec, capital: float, key_prefix: str):
    ticker = r.get("ticker", "UNKNOWN")
    bucket = r.get("bucket", "Unknown")
    dip_mode = spec.key == DIP

    st.markdown(
        f"### {ticker} <span class='subtle'>({bucket})</span>"
        + status_badge(r.get("status", ""), r.get("post_earnings", False)),
        unsafe_allow_html=True,
    )
    st.caption(
        f"Last bar: {pd.Timestamp(r['last_bar_date']).date()} · "
        f"Fetched {datetime.now().strftime('%H:%M:%S')}"
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Price", fmt_price(r.get("close", 0)))
    c2.metric("Z-Score", fmt_z(r.get("z", 0)))
    c3.metric("20-SMA", fmt_price(r.get("sma20", 0)))
    c4.metric(
        f"{r.get('trend_sma_len', 50)}-SMA",
        fmt_price(r.get("trend_sma", 0))
        if not np.isnan(r.get("trend_sma", np.nan))
        else "—",
    )
    c5.metric("ATR", fmt_price(r.get("atr", 0)))
    c6.metric("Trail (now)", fmt_price(r.get("trail_now", 0)))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Buy Trigger", fmt_price(r.get("buy_trigger", 0)))
    c2.metric("Initial Stop", fmt_price(r.get("initial_stop", 0)))
    if dip_mode:
        c3.metric("Allocation", f"{r.get('alloc_pct', 0) * 100:.0f}%")
        dte = r.get("days_to_earnings")
        c4.metric("Days to Earnings", str(dte) if dte is not None else "—")
    else:
        c3.metric("Mean-Rev Exit", fmt_price(r.get("mean_exit", 0)))
        c4.metric("R:R to SMA", fmt_rr(r.get("rr", 0)))

    dist_col, size_col, filter_col = st.columns(3)
    with dist_col:
        st.markdown(
            f"**Distance to trigger:** {fmt_price(r.get('dist_dollar', 0))} "
            f"({fmt_pct(r.get('dist_pct', 0))})"
        )
    with size_col:
        if dip_mode:
            st.markdown(
                f"**Size @ {r.get('alloc_pct', 0) * 100:.0f}% equity:** "
                f"{r.get('shares', 0):,} sh · {fmt_price(r.get('notional', 0))}"
            )
        else:
            risk_per_share = r.get("risk", 0)
            if risk_per_share > 0 and capital > 0:
                shares = int((capital * 0.01) / risk_per_share)
                notional = shares * r.get("buy_trigger", 0)
                st.markdown(
                    f"**Size @ 1% risk:** {shares:,} sh · {fmt_price(notional)} notional"
                )
            else:
                st.markdown("**Size @ 1% risk:** —")
    with filter_col:
        if dip_mode:
            st.markdown(
                f"**Post-earnings window:** "
                f"{'Yes ✓' if r.get('post_earnings') else 'No'}"
            )
        else:
            filt = f"ON (Close > {r.get('trend_sma_len', 50)}-SMA)" if r.get("use_filter") else "OFF"
            trend = "pass ✓" if r.get("trend_ok") else "fail ✗"
            st.markdown(f"**Trend filter:** {filt} · **Status:** {trend}")

    if r.get("signal"):
        extra = ""
        if dip_mode and r.get("post_earnings"):
            extra = f" — post-earnings size {r.get('alloc_pct', 0) * 100:.0f}%"
        elif r.get("use_filter"):
            extra = f" and Close > {r.get('trend_sma_len', 50)}-SMA"
        st.success(
            f"**BUY SIGNAL** — Z ({r.get('z', 0):.2f}) < {spec.z_entry}{extra}"
        )
    elif r.get("status") in ("NEAR", "WATCH"):
        st.warning(
            f"Within {r.get('dist_pct', 0):.1f}% of trigger "
            f"(${r.get('buy_trigger', 0):.2f}). Watching for Z < {spec.z_entry}."
        )

    # Stable keys: a uuid here remounts every chart on every rerun and throws
    # away the viewer's zoom/pan.
    ch1, ch2 = st.columns([1.4, 1])
    with ch1:
        st.plotly_chart(
            price_chart(
                r.get("history"), ticker,
                r.get("buy_trigger", 0), r.get("initial_stop", 0),
                r.get("mean_exit", 0),
                trend_sma_len=r.get("trend_sma_len", 50),
                z_entry=spec.z_entry,
                show_trend=True,
                show_mean_exit=spec.mean_reversion_exit,
            ),
            width="stretch",
            key=f"{key_prefix}_price_{ticker}",
        )
    with ch2:
        st.plotly_chart(
            zscore_chart(r.get("history"), ticker, spec.z_entry),
            width="stretch",
            key=f"{key_prefix}_zscore_{ticker}",
        )


def render_scanner_table(rows: list[dict], spec, dip_mode: bool, height: Optional[int] = None):
    df = rows_to_dataframe(rows, dip_mode=dip_mode)
    order = {"BUY": 0, "NEAR": 1, "WATCH": 2, "FAR": 3}
    df["_sort"] = df["Signal"].map(lambda s: order.get(s, 9))
    df = df.sort_values(["_sort", "Dist %"]).drop(columns=["_sort"])

    cols = ["Ticker", "Bucket", "Price", "Z-Score", "20-SMA", "ATR", "Buy Trigger",
            "Initial Stop"]
    if spec.mean_reversion_exit:
        cols += ["Mean Exit", "R:R"]
    cols += ["Dist $", "Dist %"]
    if dip_mode:
        cols += ["Post-Earn", "Alloc", "Size (sh)", "To Earnings"]
    else:
        cols += ["Trend SMA", "Trend OK"]
    cols += ["Signal"]
    cols = [c for c in cols if c in df.columns]

    st.dataframe(
        style_overview(df[cols], spec.z_entry),
        width="stretch",
        hide_index=True,
        height=height or min(52 + 38 * len(df), 520),
    )


def render_bucket_tab(rows: list[dict], spec, capital: float, bucket_label: str, key_prefix: str):
    st.markdown(f"<div class='section-header'>{bucket_label}</div>", unsafe_allow_html=True)

    if spec.use_trend_filter:
        st.caption(
            f"Trend filter ON: Close must be > {spec.trend_sma}-SMA "
            "(in addition to the Z entry)."
        )
    else:
        st.caption("No trend filter — entry when Z-score < threshold only.")

    if not rows:
        st.error("No data available for this bucket. Check network / yfinance.")
        return

    signals = [r for r in rows if r["signal"]]
    near = [r for r in rows if r["status"] in ("NEAR", "WATCH") and not r["signal"]]

    m1, m2, m3 = st.columns(3)
    m1.metric("Names", len(rows))
    m2.metric("Active BUY signals", len(signals))
    m3.metric("Near / Watch", len(near))

    render_scanner_table(rows, spec, dip_mode=(spec.key == DIP))

    st.divider()
    st.markdown("#### Stock detail")
    tickers = [r["ticker"] for r in rows]
    default_ix = 0
    for i, r in enumerate(rows):
        if r["signal"]:
            default_ix = i
            break
    chosen = st.selectbox("Select ticker", tickers, index=default_ix, key=f"select_{key_prefix}")
    selected = next(r for r in rows if r["ticker"] == chosen)
    render_stock_card(selected, spec, capital, key_prefix=key_prefix)


def render_filter_comparison(ticker: str, spec, frames: dict):
    """Side-by-side with filter vs without filter for any stock."""
    st.markdown(f"#### Filter comparison — **{ticker}**")
    st.caption(
        "Same mean-reversion entry, with vs without the mild trend filter "
        f"(Close > {spec.trend_sma}-SMA)."
    )

    df = frames.get(ticker)
    if df is None:
        st.error(f"Could not load data for {ticker}.")
        return

    args = (spec.z_entry, spec.atr_mult, spec.sma_window, spec.atr_window, spec.trend_sma)
    no_f = levels_from_frame(ticker, df, False, *args)
    with_f = levels_from_frame(ticker, df, True, *args)
    if not no_f or not with_f:
        st.error(f"Not enough history for {ticker}.")
        return

    left, right = st.columns(2)
    for col, r, title in [
        (left, no_f, "Without trend filter"),
        (right, with_f, f"With trend filter (Close > {spec.trend_sma}-SMA)"),
    ]:
        with col:
            st.markdown(f"**{title}**")
            st.markdown(status_badge(r["status"]), unsafe_allow_html=True)
            st.metric("Price", fmt_price(r["close"]))
            st.metric("Z-Score", fmt_z(r["z"]))
            st.metric("Trend OK", "Yes ✓" if r["trend_ok"] else "No ✗")
            st.metric("Signal", "BUY" if r["signal"] else "None")
            st.metric("Buy Trigger", fmt_price(r["buy_trigger"]))
            st.metric("Initial Stop", fmt_price(r["initial_stop"]))
            st.metric("Mean Exit", fmt_price(r["mean_exit"]))
            st.metric("Dist %", fmt_pct(r["dist_pct"]))
            st.metric("R:R", fmt_rr(r["rr"]))
            if r["signal"]:
                st.success("Entry conditions met under these rules.")
            elif r["z"] < spec.z_entry and not r["trend_ok"]:
                st.warning("Z is in the entry zone, but the trend filter blocks the trade.")
            else:
                st.info("No entry under these rules right now.")

    st.plotly_chart(
        price_chart(
            no_f["history"], ticker, no_f["buy_trigger"], no_f["initial_stop"],
            no_f["mean_exit"], trend_sma_len=spec.trend_sma, z_entry=spec.z_entry,
        ),
        width="stretch",
        key=f"compare_price_{ticker}",
    )


def render_earnings_tab(tickers: list[str], earnings: dict, window: int):
    st.markdown("<div class='section-header'>Earnings calendar</div>", unsafe_allow_html=True)
    st.caption(
        f"A BUY signal inside {window} days after a report gets the larger "
        "post-earnings allocation."
    )
    today = pd.Timestamp.now().normalize()
    for t in tickers:
        eds = earnings.get(t, []) or []
        recent = [d for d in eds if pd.Timestamp(d) <= today][-4:]
        upcoming = [d for d in eds if pd.Timestamp(d) > today][:3]
        st.markdown(f"**{t}**")
        c1, c2 = st.columns(2)
        with c1:
            st.write("Recent:")
            if recent:
                for d in recent:
                    delta = (today - pd.Timestamp(d)).days
                    flag = " ← **boost window**" if delta <= window else ""
                    st.markdown(f"• {pd.Timestamp(d).date()} ({delta}d ago){flag}")
            else:
                st.write("—")
        with c2:
            st.write("Upcoming:")
            if upcoming:
                for d in upcoming:
                    st.write(f"• {pd.Timestamp(d).date()} (in {(pd.Timestamp(d) - today).days}d)")
            else:
                st.write("—")
        st.divider()


def render_rules_tab(spec):
    st.markdown(f"### {spec.name}")
    st.caption(spec.tagline)

    buckets_md = "\n".join(
        f"| **{name}** | {', '.join(tickers)} |" for name, tickers in spec.buckets.items()
    )
    filter_note = (
        f"Close > {spec.trend_sma}-SMA (**currently ON**, Quality only)"
        if spec.use_trend_filter
        else f"Close > {spec.trend_sma}-SMA (**currently OFF** — default)"
    )

    st.markdown(
        f"""
#### Universe

| Bucket | Tickers |
|--------|---------|
{buckets_md}

#### Indicators
- **{spec.sma_window}-SMA** and rolling std → Z-score = (Close − SMA) / std
- **ATR** ({spec.atr_window}-period true range average)

#### Entry
1. **Z-score < {spec.z_entry}**
2. **Buy trigger** = SMA + ({spec.z_entry} × std) — the price where Z equals {spec.z_entry}
{"3. **Optional trend filter:** " + filter_note if spec.key == TACTICAL else ""}

#### Position sizing
{
    f"- **{spec.normal_alloc*100:.0f}% of equity** per signal"
    f"\\n- **{spec.post_earnings_alloc*100:.0f}%** when the signal lands within "
    f"{spec.post_earnings_window} days after an earnings report"
    if spec.sizing_mode == "equity"
    else "- Reference sizing on the scanner: **1% of capital** at risk to the initial stop"
}

#### Exit
- **Trailing stop:** {spec.trail_label()}
- **Initial stop** (if filled at the trigger) = Buy Trigger − ({spec.atr_mult} × ATR)
- **Exit condition:** {spec.exit_label()}

#### What the Portfolio tab does
Enter your real lots (ticker, shares, entry price, entry date) and the app walks
the bars forward from each entry to report the exit these rules actually
produce — trail path, first breach, realized or open P&L, R-multiple, and how
far price ran in your favour before you gave any back.

The previous Aggressive Dip dashboard *inferred* your entry from the most recent
signal cluster and only compared today's close to the stop, so a lot stopped out
months ago could still display as HOLD. Typing the entry in removes the guess.

#### What this dashboard does **not** do
- It does **not** place orders or connect to a broker
- Media & earnings context is informational and never gates a signal
"""
    )

    with st.expander("Formula reference", expanded=False):
        st.latex(r"Z_t = \frac{C_t - \mathrm{SMA}_n}{\sigma_n}")
        st.latex(rf"P_{{\mathrm{{trigger}}}} = \mathrm{{SMA}}_n + ({spec.z_entry})\cdot\sigma_n")
        if spec.trail_from_highest_close:
            st.latex(
                rf"Trail_t = \max_{{s \le t}}(C_s) - {spec.atr_mult}\cdot\mathrm{{ATR}}_{{entry}}"
            )
        else:
            st.latex(
                rf"Trail_t = \max_{{s \le t}}\left(C_s - {spec.atr_mult}\cdot\mathrm{{ATR}}_s\right)"
            )
        if spec.mean_reversion_exit:
            st.latex(rf"Exit: \quad C_t \le Trail_t \;\mathbf{{or}}\; Z_t > {spec.z_exit}")
        else:
            st.latex(r"Exit: \quad C_t \le Trail_t")


# ─────────────────────────────────────────────────────────────
# Secrets / API keys
# ─────────────────────────────────────────────────────────────
def resolve_alpha_vantage_key() -> tuple[str, str]:
    """Load the Alpha Vantage key from secrets.toml, then the environment."""
    placeholders = ("paste_your_key_here", "your_key_here")
    try:
        secret_val = st.secrets.get("ALPHA_VANTAGE_API_KEY", None)
        if secret_val:
            key = str(secret_val).strip()
            if key and key not in placeholders:
                return key, ".streamlit/secrets.toml"
    except Exception:
        pass

    env_val = (os.environ.get("ALPHA_VANTAGE_API_KEY") or "").strip()
    if env_val and env_val not in placeholders:
        return env_val, "environment variable ALPHA_VANTAGE_API_KEY"

    return "", "not configured"


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
def main():
    store = get_store()
    lots = store.load()

    with st.sidebar:
        st.title("⚙️ Settings")

        strategy_key = st.radio(
            "Strategy",
            options=list(SPECS.keys()),
            format_func=lambda k: SPECS[k].name,
            key="strategy_key",
        )
        base = get_spec(strategy_key)
        st.caption(base.tagline)

        capital = st.number_input(
            "Capital ($)", min_value=1_000.0, max_value=50_000_000.0,
            value=DEFAULT_CAPITAL, step=5_000.0, format="%.0f",
            help="Used for position-size references and the deployed-% metric.",
        )

        st.divider()
        z_entry = st.slider(
            "Z-score entry threshold", -3.0, -0.5, base.z_entry, 0.1,
            key=f"z_entry_{strategy_key}",
            help="Enter when Z is below this value (more negative = deeper dip).",
        )
        atr_mult = st.slider(
            "ATR multiplier (stop)", 1.0, 6.0, base.atr_mult, 0.25,
            key=f"atr_mult_{strategy_key}",
        )
        sma_window = st.number_input(
            "Z-score SMA window", 10, 50, base.sma_window, 1, key=f"sma_{strategy_key}"
        )
        atr_window = st.number_input(
            "ATR window", 5, 30, base.atr_window, 1, key=f"atrw_{strategy_key}"
        )

        use_trend_filter = base.use_trend_filter
        trend_sma = base.trend_sma
        normal_alloc = base.normal_alloc
        post_alloc = base.post_earnings_alloc

        if strategy_key == TACTICAL:
            st.divider()
            st.markdown("**Optional trend filter**")
            st.caption(
                "Off by default. When on, only the Quality bucket requires "
                "Close > N-SMA in addition to the Z entry. Your own multi-stock "
                "test cut returns on 8 of 10 names with this enabled."
            )
            use_trend_filter = st.toggle(
                "Enable trend filter (Quality only)", value=base.use_trend_filter
            )
            trend_sma = st.slider(
                "Trend SMA length", 10, 200, base.trend_sma, 5,
                disabled=not use_trend_filter,
                help="History is now sized to this window, so long SMAs no longer blank the app.",
            )
        else:
            st.divider()
            st.markdown("**Position sizing**")
            normal_alloc = st.slider("Normal dip size", 0.10, 0.40, base.normal_alloc, 0.05)
            post_alloc = st.slider("Post-earnings size", 0.15, 0.50, base.post_earnings_alloc, 0.05)

        spec = spec_from_overrides(
            base,
            z_entry=z_entry,
            atr_mult=atr_mult,
            sma_window=int(sma_window),
            atr_window=int(atr_window),
            trend_sma=int(trend_sma),
            use_trend_filter=use_trend_filter,
            normal_alloc=normal_alloc,
            post_earnings_alloc=post_alloc,
        )

        st.divider()
        st.markdown("**Media & Earnings**")
        saved_key, key_source = resolve_alpha_vantage_key()
        if saved_key:
            st.success(f"API key loaded from **{key_source}**")
            av_key = saved_key
        else:
            st.caption(
                "No saved key found. Create `.streamlit/secrets.toml` once "
                "(see secrets.toml.example). Media falls back to placeholders; "
                "earnings still work."
            )
            av_key = st.text_input(
                "Alpha Vantage API key (session only)", value="", type="password"
            )

        st.divider()
        auto = st.toggle(
            "Auto-refresh (60s)", value=False,
            help="Reruns only the scanner block — your tab, selections and zoom survive.",
        )
        if st.button("🔄 Refresh data now", width="stretch", type="primary"):
            clear_all_caches()
            st.rerun()

        st.divider()
        st.markdown("**Universe**")
        for name, tickers in spec.buckets.items():
            st.markdown(f"{name}: `{' · '.join(tickers)}`")
        st.caption(
            f"Entry Z < {spec.z_entry} · Trail {spec.atr_mult}×ATR · "
            + ("mean exit at Z > 0" if spec.mean_reversion_exit else "no mean exit")
        )

    # ── Header ───────────────────────────────────────────────
    st.title(spec.name)
    st.markdown(
        f"<span class='subtle'>{spec.tagline} · Live levels via yfinance · "
        f"Updated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</span>",
        unsafe_allow_html=True,
    )

    # ── Data ─────────────────────────────────────────────────
    # One batched download covering the scanner AND every portfolio lot.
    days = required_history_days(spec.sma_window, spec.atr_window, spec.trend_sma)
    if lots:
        earliest = min(lot.entry_ts for lot in lots)
        span = (pd.Timestamp.now().normalize() - earliest).days
        days = max(days, span + 150)  # + indicator warm-up before the entry bar

    needed = sorted(set(spec.tickers) | {lot.ticker for lot in lots} | set(UNIVERSE))
    with st.spinner("Fetching market data…"):
        frames = cached_frames(tuple(needed), days)
        earnings = cached_earnings(tuple(spec.tickers)) if spec.key == DIP else {}

    if not frames:
        st.error(
            "No market data returned. yfinance may be rate-limiting — wait a "
            "moment and press **Refresh data now**."
        )
        return

    def build_rows() -> list[dict]:
        rows: list[dict] = []
        for bucket_name, tickers in spec.buckets.items():
            gate = spec.use_trend_filter and bucket_name == "Quality"
            for t in tickers:
                df = frames.get(t)
                if df is None:
                    continue
                info = levels_from_frame(
                    t, df, gate, spec.z_entry, spec.atr_mult,
                    spec.sma_window, spec.atr_window, spec.trend_sma,
                )
                if not info:
                    continue
                info = dict(info)
                info["bucket"] = bucket_name
                if spec.key == DIP:
                    post = is_post_earnings(
                        info["last_bar_date"], t, earnings, spec.post_earnings_window
                    )
                    alloc = spec.post_earnings_alloc if (info["signal"] and post) else spec.normal_alloc
                    notional = capital * alloc
                    info.update(
                        post_earnings=post,
                        alloc_pct=alloc,
                        notional=notional,
                        shares=int(notional / info["close"]) if info["close"] > 0 else 0,
                        days_to_earnings=days_to_next_earnings(t, earnings),
                    )
                rows.append(info)
        return rows

    all_rows = build_rows()
    dip_mode = spec.key == DIP

    # ── Tabs ─────────────────────────────────────────────────
    tab_names = ["📊 Overview", "💼 Portfolio"]
    if spec.uses_buckets:
        tab_names += [f"◆ {name}" for name in spec.buckets]
    else:
        tab_names += ["🔎 Stock Detail"]
    if dip_mode:
        tab_names += ["📅 Earnings"]
    tab_names += ["📰 Media & Earnings"]
    if spec.key == TACTICAL:
        tab_names += ["🔀 Filter Compare"]
    tab_names += ["📘 Rules"]

    tabs = dict(zip(tab_names, st.tabs(tab_names)))

    with tabs["📊 Overview"]:
        # A fragment reruns just this block on a timer, instead of the old
        # <meta http-equiv="refresh"> which reloaded the page and wiped state.
        @st.fragment(run_every=60 if auto else None)
        def scanner():
            rows = build_rows() if auto else all_rows
            buys = [r for r in rows if r["signal"]]
            near = [r for r in rows if r["status"] in ("NEAR", "WATCH") and not r["signal"]]

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Tracked", len(rows))
            k2.metric("BUY signals", len(buys))
            k3.metric("Near / Watch", len(near))
            k4.metric("Z threshold", f"{spec.z_entry}")
            k5.metric("Capital", f"${capital:,.0f}")

            if rows:
                bars = ", ".join(
                    f"{r['ticker']} {pd.Timestamp(r['last_bar_date']).strftime('%m-%d')}"
                    for r in rows[:6]
                )
                st.markdown(
                    f"<div class='fresh-ts'>Last bars: {bars}"
                    + (" · auto-refreshing every 60s" if auto else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )

            if buys:
                names = ", ".join(
                    r["ticker"] + (" (Post-Earn)" if r.get("post_earnings") else "")
                    for r in buys
                )
                st.success(f"**Active BUY SIGNAL(s):** {names}")
            elif near:
                names = ", ".join(f"{r['ticker']} ({r['dist_pct']:+.1f}%)" for r in near)
                st.info(f"No active buys. Watching: {names}")
            else:
                st.info("No stocks near a buy trigger right now.")

            st.markdown(
                "<div class='section-header'>Live scanner</div>", unsafe_allow_html=True
            )
            if not rows:
                st.error("No market data returned for this universe.")
                return
            render_scanner_table(rows, spec, dip_mode=dip_mode)

            highlight = buys + near
            if highlight:
                st.divider()
                st.markdown("#### Priority names")
                cols = st.columns(min(len(highlight), 4))
                for i, r in enumerate(highlight[:8]):
                    with cols[i % len(cols)]:
                        st.markdown(
                            f"**{r['ticker']}** {status_badge(r['status'], r.get('post_earnings', False))}",
                            unsafe_allow_html=True,
                        )
                        st.write(
                            f"{fmt_price(r['close'])} · Z {fmt_z(r['z'])}\n\n"
                            f"Trigger {fmt_price(r['buy_trigger'])} · "
                            f"Dist {fmt_pct(r['dist_pct'])}"
                        )

        scanner()

        if all_rows:
            st.divider()
            st.markdown("#### Deep dive")
            pick = st.selectbox(
                "Select any ticker", [r["ticker"] for r in all_rows], key="overview_pick"
            )
            render_stock_card(
                next(r for r in all_rows if r["ticker"] == pick),
                spec, capital, key_prefix="overview",
            )

    with tabs["💼 Portfolio"]:
        # Indicator frames per rule set, so a lot tagged "dip" is measured with
        # dip windows even while the sidebar is on the tactical strategy.
        frames_by_strategy: dict[str, dict[str, pd.DataFrame]] = {}
        for key in {lot.strategy for lot in lots} | {spec.key}:
            s = spec if key == spec.key else get_spec(key)
            frames_by_strategy[key] = {
                t: compute_indicators(df, s.sma_window, s.atr_window, s.trend_sma)
                for t, df in frames.items()
            }
        render_portfolio_tab(
            frames_by_strategy=frames_by_strategy,
            store=store,
            capital=capital,
            universe=UNIVERSE,
            spec_overrides={spec.key: spec},
        )

    if spec.uses_buckets:
        for name, tickers in spec.buckets.items():
            with tabs[f"◆ {name}"]:
                bucket_rows = [r for r in all_rows if r["bucket"] == name]
                render_bucket_tab(
                    bucket_rows, spec, capital, f"{name} bucket", key_prefix=name.lower()
                )
    else:
        with tabs["🔎 Stock Detail"]:
            render_bucket_tab(all_rows, spec, capital, spec.name, key_prefix="detail")

    if dip_mode:
        with tabs["📅 Earnings"]:
            render_earnings_tab(spec.tickers, earnings, spec.post_earnings_window)

    with tabs["📰 Media & Earnings"]:
        render_media_earnings_tab(tickers=spec.tickers, api_key=av_key or "")

    if spec.key == TACTICAL:
        with tabs["🔀 Filter Compare"]:
            st.markdown(
                "<div class='section-header'>With filter vs without filter</div>",
                unsafe_allow_html=True,
            )
            cmp_ticker = st.selectbox(
                "Ticker", spec.tickers,
                index=spec.tickers.index("NOW") if "NOW" in spec.tickers else 0,
                key="compare_ticker",
            )
            render_filter_comparison(cmp_ticker, spec, frames)

    with tabs["📘 Rules"]:
        render_rules_tab(spec)

    st.markdown(
        "<div class='app-footer'>"
        "Tactical Trading System · Educational / research use only · "
        "Not investment advice · Data: Yahoo Finance via yfinance · "
        "Media: Alpha Vantage NEWS_SENTIMENT (optional)"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
