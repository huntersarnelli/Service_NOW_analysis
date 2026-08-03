"""
Aggressive Dip Accumulation — Live Streamlit Dashboard
======================================================
Universe     : META, NVDA, NET
Entry        : 20-period Z-score < -1.2
Sizing       : 25% of equity (normal) / 35% if within 10 days after earnings
Exit         : Highest close since entry − 4.0 × ATR(14)   [ATR frozen at entry]
Pyramiding   : Allowed

Layout
------
Sidebar      — Capital, Z threshold, ATR multiple, refresh
Overview     — Live scanner + signal status for all names
Detail       — Per-ticker card with charts, levels, sizing
Earnings     — Upcoming & recent earnings + post-earnings flag
Rules        — Full strategy documentation
"""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# Strategy Defaults
# ─────────────────────────────────────────────────────────────
TICKERS = ["META", "NVDA", "NET"]
DEFAULT_CAPITAL = 100_000.0
DEFAULT_Z_ENTRY = -1.2
DEFAULT_ATR_MULT = 4.0
DEFAULT_NORMAL_ALLOC = 0.25
DEFAULT_POST_ALLOC = 0.35
DEFAULT_Z_WINDOW = 20
DEFAULT_ATR_WINDOW = 14
POST_EARNINGS_WINDOW = 10   # days

# ─────────────────────────────────────────────────────────────
# Page Config & CSS
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Aggressive Dip Accumulation",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    div[data-testid="stMetric"] {
        background: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.25);
        border-radius: 10px;
        padding: 12px 16px;
    }
    .buy-badge {
        display: inline-block;
        background: #16a34a;
        color: white;
        font-weight: 700;
        font-size: 0.85rem;
        letter-spacing: 0.04em;
        padding: 4px 12px;
        border-radius: 999px;
        margin-left: 8px;
    }
    .post-badge {
        display: inline-block;
        background: #7c3aed;
        color: white;
        font-weight: 600;
        font-size: 0.8rem;
        padding: 3px 10px;
        border-radius: 999px;
        margin-left: 8px;
    }
    .watch-badge {
        display: inline-block;
        background: #ca8a04;
        color: white;
        font-weight: 600;
        font-size: 0.8rem;
        padding: 3px 10px;
        border-radius: 999px;
        margin-left: 8px;
    }
    .neutral-badge {
        display: inline-block;
        background: rgba(128,128,128,0.35);
        color: inherit;
        font-weight: 600;
        font-size: 0.8rem;
        padding: 3px 10px;
        border-radius: 999px;
        margin-left: 8px;
    }
    .section-header {
        font-size: 1.15rem;
        font-weight: 650;
        margin: 0.4rem 0 0.6rem 0;
    }
    .subtle { opacity: 0.75; font-size: 0.9rem; }
    .app-footer {
        margin-top: 2rem;
        padding-top: 1rem;
        border-top: 1px solid rgba(128,128,128,0.25);
        font-size: 0.85rem;
        opacity: 0.7;
    }
</style>
""",
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────
# Data Layer
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def load_price_data(tickers: Tuple[str, ...], days: int = 250) -> Dict[str, pd.DataFrame]:
    end = datetime.now()
    start = end - timedelta(days=days + 50)
    raw = yf.download(
        list(tickers),
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    data = {}
    for t in tickers:
        try:
            if len(tickers) == 1:
                df = raw.copy()
            else:
                df = raw[t].copy()
            df = df.dropna(subset=["Close"])
            df.index = pd.to_datetime(df.index)
            data[t] = df
        except Exception:
            continue
    return data


@st.cache_data(ttl=3600, show_spinner=False)
def load_earnings_dates(tickers: Tuple[str, ...]) -> Dict[str, List[pd.Timestamp]]:
    earnings = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            ed = tk.get_earnings_dates(limit=12)
            dates = []
            if ed is not None and len(ed) > 0:
                for idx in ed.index:
                    d = pd.Timestamp(idx).tz_localize(None).normalize()
                    dates.append(d)
            earnings[t] = sorted(set(dates))
        except Exception:
            earnings[t] = []
    return earnings


def add_indicators(df: pd.DataFrame, z_window: int, atr_window: int) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    sma = c.rolling(z_window).mean()
    std = c.rolling(z_window).std()
    df["sma"] = sma
    df["zscore"] = (c - sma) / std

    prev = c.shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev).abs(),
        (df["Low"] - prev).abs()
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(atr_window).mean()
    return df


def is_post_earnings(date: pd.Timestamp, ticker: str, earnings: Dict, window: int = 10) -> bool:
    for ed in earnings.get(ticker, []):
        delta = (date.normalize() - ed.normalize()).days
        if 0 <= delta <= window:
            return True
    return False


def days_to_next_earnings(ticker: str, earnings: Dict) -> Optional[int]:
    today = pd.Timestamp.now().normalize()
    future = [d for d in earnings.get(ticker, []) if d >= today]
    if not future:
        return None
    return (future[0] - today).days


def compute_levels(
    df: pd.DataFrame,
    ticker: str,
    z_entry: float,
    atr_mult: float,
    capital: float,
    normal_alloc: float,
    post_alloc: float,
    earnings: Dict,
) -> Optional[dict]:
    if df is None or len(df) < 30:
        return None

    row = df.iloc[-1]
    if pd.isna(row["zscore"]) or pd.isna(row["atr"]) or row["atr"] <= 0:
        return None

    close = float(row["Close"])
    z = float(row["zscore"])
    atr = float(row["atr"])
    sma = float(row["sma"])

    # Theoretical trigger price (where Z would equal z_entry)
    # Z = (C - SMA) / std  →  C = SMA + z_entry * std
    std = float(df["Close"].rolling(20).std().iloc[-1])
    buy_trigger = sma + z_entry * std

    signal = z < z_entry
    post = is_post_earnings(df.index[-1], ticker, earnings, POST_EARNINGS_WINDOW)
    alloc = post_alloc if (signal and post) else normal_alloc

    # Initial stop if entered today at close
    initial_stop = close - atr_mult * atr

    # Distance to trigger
    dist_dollar = close - buy_trigger
    dist_pct = (close / buy_trigger - 1) * 100 if buy_trigger > 0 else 0

    # Status
    if signal:
        status = "BUY"
    elif z < z_entry + 0.35:
        status = "NEAR"
    elif z < 0:
        status = "WATCH"
    else:
        status = "FAR"

    # Position sizing
    notional = capital * alloc
    shares = int(notional / close) if close > 0 else 0

    # Risk if stopped out immediately
    risk_per_share = close - initial_stop
    risk_dollars = shares * risk_per_share if risk_per_share > 0 else 0
    risk_pct = (risk_dollars / capital * 100) if capital > 0 else 0

    return {
        "ticker": ticker,
        "close": close,
        "z": z,
        "sma": sma,
        "atr": atr,
        "buy_trigger": buy_trigger,
        "initial_stop": initial_stop,
        "dist_dollar": dist_dollar,
        "dist_pct": dist_pct,
        "signal": signal,
        "status": status,
        "is_post_earnings": post,
        "alloc_pct": alloc,
        "shares": shares,
        "notional": notional,
        "risk_dollars": risk_dollars,
        "risk_pct": risk_pct,
        "days_to_earnings": days_to_next_earnings(ticker, earnings),
        "history": df,
    }


# ─────────────────────────────────────────────────────────────
# Formatting
# ─────────────────────────────────────────────────────────────
def fmt_price(x: float) -> str:
    return f"${x:,.2f}"

def fmt_pct(x: float) -> str:
    return f"{x:+.2f}%"

def fmt_z(x: float) -> str:
    return f"{x:+.2f}"

def status_badge(status: str, is_post: bool = False) -> str:
    if status == "BUY":
        badge = '<span class="buy-badge">BUY SIGNAL</span>'
        if is_post:
            badge += '<span class="post-badge">POST-EARNINGS</span>'
        return badge
    if status == "NEAR":
        return '<span class="watch-badge">NEAR TRIGGER</span>'
    if status == "WATCH":
        return '<span class="watch-badge">WATCH</span>'
    return '<span class="neutral-badge">—</span>'


# ─────────────────────────────────────────────────────────────
# Charts
# ─────────────────────────────────────────────────────────────
def price_chart(history: pd.DataFrame, ticker: str, buy_trigger: float,
                initial_stop: float, atr_mult: float) -> go.Figure:
    df = history.dropna(subset=["sma"]).copy()
    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"], name="Price",
        increasing_line_color="#16a34a", decreasing_line_color="#dc2626",
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=df["sma"], name="20-SMA",
        line=dict(color="#3b82f6", width=1.5),
    ))

    # Levels on last 40% of chart
    x0 = df.index[int(len(df) * 0.55)]
    x1 = df.index[-1]
    for y, name, color, dash in [
        (buy_trigger, f"Buy Trigger (Z={DEFAULT_Z_ENTRY})", "#16a34a", "dash"),
        (initial_stop, f"Initial Stop (4×ATR)", "#dc2626", "dot"),
    ]:
        fig.add_shape(type="line", x0=x0, x1=x1, y0=y, y1=y,
                      line=dict(color=color, width=1.5, dash=dash))
        fig.add_annotation(x=x1, y=y, text=f" {name} ${y:.2f}",
                           showarrow=False, xanchor="left",
                           font=dict(size=11, color=color))

    fig.update_layout(
        title=f"{ticker} — Price & Strategy Levels",
        xaxis_rangeslider_visible=False,
        height=420,
        margin=dict(l=40, r=140, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        template="plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white",
    )
    return fig


def zscore_chart(history: pd.DataFrame, ticker: str, z_entry: float) -> go.Figure:
    df = history.dropna(subset=["zscore"]).copy()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df.index, y=df["zscore"], name="Z-Score",
        line=dict(color="#38bdf8", width=2),
        fill="tozeroy", fillcolor="rgba(56,189,248,0.12)",
    ))
    fig.add_hline(y=z_entry, line_dash="dash", line_color="#16a34a",
                  annotation_text=f"Entry Z = {z_entry}", annotation_position="bottom right")
    fig.add_hline(y=0, line_dash="dash", line_color="#3b82f6",
                  annotation_text="Mean (Z=0)", annotation_position="top right")
    fig.update_layout(
        title=f"{ticker} — Z-Score",
        height=280, margin=dict(l=40, r=40, t=50, b=40),
        template="plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white",
        yaxis_title="Z",
    )
    return fig


# ─────────────────────────────────────────────────────────────
# UI Sections
# ─────────────────────────────────────────────────────────────
def render_stock_card(info: dict, z_entry: float, capital: float):
    ticker = info["ticker"]
    st.markdown(f"### {ticker}", unsafe_allow_html=True)

    # Badges
    st.markdown(status_badge(info["status"], info["is_post_earnings"]), unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Price", fmt_price(info["close"]))
    c2.metric("Z-Score", fmt_z(info["z"]))
    c3.metric("20-SMA", fmt_price(info["sma"]))
    c4.metric("ATR(14)", fmt_price(info["atr"]))
    c5.metric("Alloc", f"{info['alloc_pct']*100:.0f}%")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Buy Trigger", fmt_price(info["buy_trigger"]))
    c2.metric("Initial Stop (4×ATR)", fmt_price(info["initial_stop"]))
    c3.metric("Dist to Trigger", f"{fmt_price(info['dist_dollar'])} ({fmt_pct(info['dist_pct'])})")
    c4.metric("Days to Earnings", 
              str(info["days_to_earnings"]) if info["days_to_earnings"] is not None else "—")

    # Sizing
    st.markdown(
        f"**Suggested size:** {info['shares']:,} shares · "
        f"{fmt_price(info['notional'])} notional · "
        f"Risk if stopped immediately: {fmt_price(info['risk_dollars'])} "
        f"({info['risk_pct']:.1f}% of capital)"
    )

    if info["signal"]:
        post_txt = " **(Post-Earnings — 35% size)**" if info["is_post_earnings"] else " **(Normal — 25% size)**"
        st.success(f"**BUY SIGNAL** — Z ({info['z']:.2f}) < {z_entry}{post_txt}")
    elif info["status"] in ("NEAR", "WATCH"):
        st.warning(f"Within {info['dist_pct']:.1f}% of trigger. Watching for Z < {z_entry}.")

    # Charts
    ch1, ch2 = st.columns([1.4, 1])
    with ch1:
        st.plotly_chart(
            price_chart(info["history"], ticker, info["buy_trigger"],
                        info["initial_stop"], DEFAULT_ATR_MULT),
            use_container_width=True, key=f"price_{ticker}"
        )
    with ch2:
        st.plotly_chart(
            zscore_chart(info["history"], ticker, z_entry),
            use_container_width=True, key=f"z_{ticker}"
        )


def render_overview_table(rows: List[dict], z_entry: float):
    if not rows:
        st.error("No data available.")
        return

    records = []
    for r in rows:
        records.append({
            "Ticker": r["ticker"],
            "Price": r["close"],
            "Z-Score": r["z"],
            "20-SMA": r["sma"],
            "ATR": r["atr"],
            "Buy Trigger": r["buy_trigger"],
            "Initial Stop": r["initial_stop"],
            "Dist %": r["dist_pct"],
            "Alloc": f"{r['alloc_pct']*100:.0f}%",
            "Post-Earn": "Yes" if r["is_post_earnings"] else "",
            "Days to Earn": r["days_to_earnings"] if r["days_to_earnings"] is not None else "—",
            "Signal": "BUY" if r["signal"] else r["status"],
        })
    df = pd.DataFrame(records)

    # Sort: BUY first, then by distance
    order = {"BUY": 0, "NEAR": 1, "WATCH": 2, "FAR": 3}
    df["_sort"] = df["Signal"].map(lambda s: order.get(s, 9))
    df = df.sort_values(["_sort", "Dist %"]).drop(columns=["_sort"])

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

    styled = (
        df.style.format({
            "Price": "${:,.2f}",
            "Z-Score": "{:+.2f}",
            "20-SMA": "${:,.2f}",
            "ATR": "${:,.2f}",
            "Buy Trigger": "${:,.2f}",
            "Initial Stop": "${:,.2f}",
            "Dist %": "{:+.2f}%",
        }, na_rep="—")
        .map(color_signal, subset=["Signal"])
        .map(color_z, subset=["Z-Score"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def render_rules(z_entry, atr_mult, normal_alloc, post_alloc):
    st.markdown("### Aggressive Dip Accumulation — Strategy Rules")
    st.markdown(
        f"""
#### Universe
**META · NVDA · NET**

#### Indicators
- **Z-Score** = (Close − 20-SMA) / 20-period standard deviation
- **ATR** = 14-period Average True Range

#### Entry / Add
1. Z-score < **{z_entry}**
2. **Size**
   - Normal dip → **{normal_alloc*100:.0f}%** of current equity
   - Post-earnings dip (within {POST_EARNINGS_WINDOW} days after earnings) → **{post_alloc*100:.0f}%** of current equity
3. Pyramiding allowed (multiple lots in the same name)

#### Exit
- Trailing stop = Highest close since the lot was opened − **{atr_mult} × ATR**
- ATR is **frozen at the value on the entry day** of that lot
- No mean-reversion (Z > 0) exit — we let winners run

#### Design Intent
Buy temporary pullbacks in strong secular leaders with meaningful size,  
then refuse to sell them easily. Post-earnings dips receive a size premium  
because historical analysis showed they produce higher average returns.
"""
    )
    with st.expander("Formula reference", expanded=False):
        st.latex(r"Z_t = \dfrac{C_t - \mathrm{SMA}_{20}}{\sigma_{20}}")
        st.latex(rf"P_{{\mathrm{{trigger}}}} = \mathrm{{SMA}}_{{20}} + ({z_entry})\cdot\sigma_{{20}}")
        st.latex(rf"Stop_t = H_t - {atr_mult}\cdot\mathrm{{ATR}}_{{\mathrm{{entry}}}}")
        st.markdown("Where \( H_t \) is the highest close since the lot was opened.")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
def main():
    # Sidebar
    with st.sidebar:
        st.title("⚙️ Settings")
        st.caption("Aggressive Dip Accumulation")

        capital = st.number_input(
            "Capital ($)", min_value=1_000.0, max_value=50_000_000.0,
            value=DEFAULT_CAPITAL, step=5_000.0, format="%.0f"
        )
        z_entry = st.slider(
            "Z-score entry threshold", min_value=-2.0, max_value=-0.5,
            value=DEFAULT_Z_ENTRY, step=0.1
        )
        atr_mult = st.slider(
            "ATR multiplier (trail)", min_value=2.0, max_value=6.0,
            value=DEFAULT_ATR_MULT, step=0.25
        )
        normal_alloc = st.slider(
            "Normal dip size", min_value=0.10, max_value=0.40,
            value=DEFAULT_NORMAL_ALLOC, step=0.05, format="%.0f%%",
            help="Fraction of equity for normal dips"
        )
        # Streamlit slider format is a bit awkward for %, so we treat as fraction
        normal_alloc = normal_alloc  # already fraction
        post_alloc = st.slider(
            "Post-earnings dip size", min_value=0.15, max_value=0.50,
            value=DEFAULT_POST_ALLOC, step=0.05, format="%.0f%%"
        )

        st.divider()
        if st.button("🔄 Refresh data now", use_container_width=True, type="primary"):
            load_price_data.clear()
            load_earnings_dates.clear()
            st.rerun()

        st.divider()
        st.markdown("**Universe**")
        st.markdown("`META · NVDA · NET`")
        st.caption(f"Entry Z < {z_entry} · Trail {atr_mult}×ATR · "
                   f"Size {normal_alloc*100:.0f}% / {post_alloc*100:.0f}% post-earn")

    # Header
    st.title("Aggressive Dip Accumulation")
    st.markdown(
        f"<span class='subtle'>META · NVDA · NET · "
        f"Z < {z_entry} · 4× ATR trail · "
        f"Updated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</span>",
        unsafe_allow_html=True,
    )

    # Load data
    with st.spinner("Fetching market data & earnings…"):
        price_data = load_price_data(tuple(TICKERS))
        earnings = load_earnings_dates(tuple(TICKERS))

        rows = []
        for t in TICKERS:
            if t not in price_data:
                continue
            df = add_indicators(price_data[t], DEFAULT_Z_WINDOW, DEFAULT_ATR_WINDOW)
            info = compute_levels(
                df, t, z_entry, atr_mult, capital,
                normal_alloc, post_alloc, earnings
            )
            if info:
                rows.append(info)

    # KPI strip
    buy_signals = [r for r in rows if r["signal"]]
    near = [r for r in rows if r["status"] in ("NEAR", "WATCH") and not r["signal"]]
    post_signals = [r for r in buy_signals if r["is_post_earnings"]]

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Tracked", len(rows))
    k2.metric("BUY signals", len(buy_signals))
    k3.metric("Post-Earnings BUYs", len(post_signals))
    k4.metric("Near / Watch", len(near))
    k5.metric("Capital", f"${capital:,.0f}")

    if buy_signals:
        names = ", ".join(
            f"{r['ticker']}{' (Post-Earn)' if r['is_post_earnings'] else ''}"
            for r in buy_signals
        )
        st.success(f"**Active BUY SIGNAL(s):** {names}")
    elif near:
        names = ", ".join(f"{r['ticker']} ({r['dist_pct']:+.1f}%)" for r in near)
        st.info(f"No active buys. Watching: {names}")
    else:
        st.info("No stocks near a buy trigger right now.")

    # Tabs
    tab_overview, tab_detail, tab_earnings, tab_rules = st.tabs([
        "📊 Overview",
        "🔎 Stock Detail",
        "📅 Earnings",
        "📘 Rules",
    ])

    with tab_overview:
        st.markdown("<div class='section-header'>Live Scanner</div>", unsafe_allow_html=True)
        render_overview_table(rows, z_entry)

        if buy_signals or near:
            st.divider()
            st.markdown("#### Priority names")
            cols = st.columns(min(len(buy_signals + near), 3))
            for i, r in enumerate((buy_signals + near)[:3]):
                with cols[i % len(cols)]:
                    st.markdown(
                        f"**{r['ticker']}** {status_badge(r['status'], r['is_post_earnings'])}",
                        unsafe_allow_html=True,
                    )
                    st.write(
                        f"{fmt_price(r['close'])} · Z {fmt_z(r['z'])}\n\n"
                        f"Trigger {fmt_price(r['buy_trigger'])} · "
                        f"Size {r['alloc_pct']*100:.0f}%"
                    )

    with tab_detail:
        if not rows:
            st.warning("No data.")
        else:
            tickers = [r["ticker"] for r in rows]
            # Default to first BUY if any
            default_ix = 0
            for i, r in enumerate(rows):
                if r["signal"]:
                    default_ix = i
                    break
            chosen = st.selectbox("Select ticker", tickers, index=default_ix)
            selected = next(r for r in rows if r["ticker"] == chosen)
            render_stock_card(selected, z_entry, capital)

    with tab_earnings:
        st.markdown("<div class='section-header'>Earnings Calendar & Post-Earnings Window</div>",
                    unsafe_allow_html=True)
        st.caption(f"Post-earnings size boost applies for {POST_EARNINGS_WINDOW} days after the report.")

        for t in TICKERS:
            eds = earnings.get(t, [])
            today = pd.Timestamp.now().normalize()
            recent = [d for d in eds if d <= today][-3:]
            upcoming = [d for d in eds if d > today][:3]

            st.markdown(f"**{t}**")
            c1, c2 = st.columns(2)
            with c1:
                st.write("Recent:")
                if recent:
                    for d in recent:
                        delta = (today - d).days
                        flag = " ← in boost window" if delta <= POST_EARNINGS_WINDOW else ""
                        st.write(f"  • {d.date()} ({delta}d ago){flag}")
                else:
                    st.write("  —")
            with c2:
                st.write("Upcoming:")
                if upcoming:
                    for d in upcoming:
                        st.write(f"  • {d.date()} ({(d - today).days}d)")
                else:
                    st.write("  —")
            st.divider()

    with tab_rules:
        render_rules(z_entry, atr_mult, normal_alloc, post_alloc)

    st.markdown(
        "<div class='app-footer'>"
        "Aggressive Dip Accumulation · Educational / research use only · "
        "Not investment advice · Data: Yahoo Finance"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
