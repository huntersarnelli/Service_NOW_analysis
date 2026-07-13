"""
Dual-Mode Tactical Trading System — Live Streamlit Dashboard
=============================================================
Momentum bucket  : NVDA, META, NET          — Z < -1.5 (no trend filter)
Quality bucket   : NOW, MSFT, GOOGL, ...   — Z < -1.5 AND Close > 50-SMA

Entry  : Z-score < threshold (and trend filter for Quality)
Trail  : Close - ATR_mult × ATR  (only raise)
Exit   : Trailing stop hit OR Z-score > 0
"""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# Defaults (overridable in sidebar)
# ─────────────────────────────────────────────────────────────
DEFAULT_Z_ENTRY = -1.5
DEFAULT_ATR_MULT = 2.0
DEFAULT_SMA_WINDOW = 20
DEFAULT_ATR_WINDOW = 14
DEFAULT_TREND_SMA = 50
DEFAULT_CAPITAL = 100_000.0
HISTORY_DAYS = 180

MOMENTUM_BUCKET = ["NVDA", "META", "NET"]
QUALITY_BUCKET = ["NOW", "MSFT", "GOOGL", "PANW", "CRWD", "DDOG", "CRM"]
ALL_TICKERS = MOMENTUM_BUCKET + QUALITY_BUCKET

# ─────────────────────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Dual-Mode Tactical Trading System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS — dark/light friendly, professional
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
    /* Buy signal badge */
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
    .subtle {
        opacity: 0.75;
        font-size: 0.9rem;
    }
    /* Tighten dataframe cell padding slightly */
    .stDataFrame { font-size: 0.92rem; }
    /* Footer */
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
# Data & indicators
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def get_data(ticker: str, days: int = HISTORY_DAYS) -> Optional[pd.DataFrame]:
    """Download OHLCV history for a single ticker."""
    end = datetime.now().date() + timedelta(days=1)
    start = end - timedelta(days=days)
    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        )
        if df is None or df.empty:
            return None
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        return df[cols].dropna().copy()
    except Exception:
        return None


def compute_indicators(
    df: pd.DataFrame,
    sma_window: int,
    atr_window: int,
    trend_sma: int,
) -> pd.DataFrame:
    """Add SMA, std, Z-score, trend SMA, and ATR columns."""
    out = df.copy()
    out["sma"] = out["Close"].rolling(sma_window).mean()
    out["std"] = out["Close"].rolling(sma_window).std()
    out["zscore"] = (out["Close"] - out["sma"]) / out["std"]
    out["trend_sma"] = out["Close"].rolling(trend_sma).mean()

    tr = pd.concat(
        [
            out["High"] - out["Low"],
            (out["High"] - out["Close"].shift(1)).abs(),
            (out["Low"] - out["Close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(atr_window).mean()
    return out


def get_levels(
    ticker: str,
    use_filter: bool,
    z_entry: float,
    atr_mult: float,
    sma_window: int,
    atr_window: int,
    trend_sma: int,
) -> Optional[dict]:
    """
    Compute live levels and signal for one ticker.

    Exact strategy logic:
      buy_trigger = SMA + z_entry * std
      initial_stop (if buy at trigger) = buy_trigger - atr_mult * ATR
      mean_exit   = SMA  (Z > 0)
      signal      = (Z < z_entry) and (trend_ok if filter else True)
      trail       = Close - atr_mult * ATR  (raised only when in a trade)
    """
    df = get_data(ticker)
    if df is None or len(df) < max(60, trend_sma + 5):
        return None

    df = compute_indicators(df, sma_window, atr_window, trend_sma)
    last = df.iloc[-1]

    close = float(last["Close"])
    sma = float(last["sma"])
    std = float(last["std"])
    atr = float(last["atr"])
    z = float(last["zscore"])
    trend_sma_val = (
        float(last["trend_sma"]) if pd.notna(last["trend_sma"]) else float("nan")
    )

    if any(np.isnan(x) for x in (sma, std, atr, z)) or std == 0:
        return None

    buy_trigger = sma + (z_entry * std)
    initial_stop = buy_trigger - (atr_mult * atr)
    mean_exit = sma
    trail_now = close - (atr_mult * atr)

    trend_ok = True
    if use_filter and not np.isnan(trend_sma_val):
        trend_ok = close > trend_sma_val

    signal = (z < z_entry) and trend_ok
    dist_pct = (close - buy_trigger) / close * 100.0
    dist_dollar = close - buy_trigger
    risk = buy_trigger - initial_stop
    reward = mean_exit - buy_trigger
    rr = (reward / risk) if risk > 0 else float("nan")

    # Proximity tiers for UI
    if signal:
        status = "BUY"
    elif dist_pct < 5:
        status = "NEAR"
    elif dist_pct < 12:
        status = "WATCH"
    else:
        status = "FAR"

    return {
        "ticker": ticker,
        "close": close,
        "z": z,
        "sma20": sma,
        "std": std,
        "atr": atr,
        "trend_sma": trend_sma_val,
        "buy_trigger": buy_trigger,
        "initial_stop": initial_stop,
        "mean_exit": mean_exit,
        "trail_now": trail_now,
        "trend_ok": trend_ok,
        "use_filter": use_filter,
        "signal": signal,
        "status": status,
        "dist_pct": dist_pct,
        "dist_dollar": dist_dollar,
        "risk": risk,
        "reward": reward,
        "rr": rr,
        "history": df,
    }


def scan_bucket(
    tickers: list[str],
    use_filter: bool,
    z_entry: float,
    atr_mult: float,
    sma_window: int,
    atr_window: int,
    trend_sma: int,
    bucket_name: str,
) -> list[dict]:
    rows = []
    for t in tickers:
        info = get_levels(
            t, use_filter, z_entry, atr_mult, sma_window, atr_window, trend_sma
        )
        if info:
            info["bucket"] = bucket_name
            rows.append(info)
    return rows


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


def status_badge(status: str) -> str:
    if status == "BUY":
        return '<span class="buy-badge">BUY SIGNAL</span>'
    if status == "NEAR":
        return '<span class="watch-badge">NEAR TRIGGER</span>'
    if status == "WATCH":
        return '<span class="watch-badge">WATCH</span>'
    return '<span class="neutral-badge">—</span>'


def z_color(z: float, z_entry: float) -> str:
    if z < z_entry:
        return "#16a34a"  # green — entry zone
    if z < 0:
        return "#ca8a04"  # amber — below mean
    return "#64748b"  # slate — above mean


def rows_to_dataframe(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    records = []
    for r in rows:
        records.append(
            {
                "Ticker": r["ticker"],
                "Bucket": r["bucket"],
                "Price": r["close"],
                "Z-Score": r["z"],
                "20-SMA": r["sma20"],
                "50-SMA": r["trend_sma"],
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
        )
    return pd.DataFrame(records)


def style_overview(df: pd.DataFrame, z_entry: float):
    """Apply conditional formatting to the overview table."""
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

    styled = (
        df.style.format(
            {
                "Price": "${:,.2f}",
                "Z-Score": "{:+.2f}",
                "20-SMA": "${:,.2f}",
                "50-SMA": "${:,.2f}",
                "ATR": "${:,.2f}",
                "Buy Trigger": "${:,.2f}",
                "Initial Stop": "${:,.2f}",
                "Mean Exit": "${:,.2f}",
                "Dist $": "${:+,.2f}",
                "Dist %": "{:+.2f}%",
                "Risk": "${:,.2f}",
                "Reward": "${:,.2f}",
                "R:R": "{:.2f}:1",
            },
            na_rep="—",
        )
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
    show_trend: bool = True,
) -> go.Figure:
    """Candles + SMAs + trigger / stop / exit levels."""
    df = history.dropna(subset=["sma"]).copy()
    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="Price",
            increasing_line_color="#16a34a",
            decreasing_line_color="#dc2626",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["sma"],
            name="20-SMA",
            line=dict(color="#3b82f6", width=1.5),
        )
    )
    if show_trend and "trend_sma" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df["trend_sma"],
                name=f"{trend_sma_len}-SMA",
                line=dict(color="#a855f7", width=1.5, dash="dot"),
            )
        )

    # Horizontal levels (last 40% of chart for clarity)
    x0 = df.index[int(len(df) * 0.55)]
    x1 = df.index[-1]
    for y, name, color, dash in [
        (buy_trigger, "Buy Trigger (Z=-1.5)", "#16a34a", "dash"),
        (initial_stop, "Initial Stop", "#dc2626", "dot"),
        (mean_exit, "Mean Exit (Z=0)", "#3b82f6", "dash"),
    ]:
        fig.add_shape(
            type="line",
            x0=x0,
            x1=x1,
            y0=y,
            y1=y,
            line=dict(color=color, width=1.5, dash=dash),
        )
        fig.add_annotation(
            x=x1,
            y=y,
            text=f" {name} ${y:.2f}",
            showarrow=False,
            xanchor="left",
            font=dict(size=11, color=color),
        )

    fig.update_layout(
        title=f"{ticker} — Price & Strategy Levels",
        xaxis_rangeslider_visible=False,
        height=420,
        margin=dict(l=40, r=120, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        template="plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white",
    )
    return fig


def zscore_chart(history: pd.DataFrame, ticker: str, z_entry: float) -> go.Figure:
    df = history.dropna(subset=["zscore"]).copy()
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["zscore"],
            name="Z-Score",
            line=dict(color="#38bdf8", width=2),
            fill="tozeroy",
            fillcolor="rgba(56,189,248,0.12)",
        )
    )
    fig.add_hline(
        y=z_entry,
        line_dash="dash",
        line_color="#16a34a",
        annotation_text=f"Entry Z = {z_entry}",
        annotation_position="bottom right",
    )
    fig.add_hline(
        y=0,
        line_dash="dash",
        line_color="#3b82f6",
        annotation_text="Exit Z = 0",
        annotation_position="top right",
    )
    fig.update_layout(
        title=f"{ticker} — Z-Score",
        height=280,
        margin=dict(l=40, r=40, t=50, b=40),
        template="plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white",
        yaxis_title="Z",
    )
    return fig


# ─────────────────────────────────────────────────────────────
# UI sections
# ─────────────────────────────────────────────────────────────
def render_stock_card(r: dict, z_entry: float, capital: float):
    """Detailed card for a single stock."""
    badge = status_badge(r["status"])
    st.markdown(
        f"### {r['ticker']}  "
        f"<span class='subtle'>({r['bucket']})</span>  {badge}",
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Price", fmt_price(r["close"]))
    c2.metric("Z-Score", fmt_z(r["z"]))
    c3.metric("20-SMA", fmt_price(r["sma20"]))
    c4.metric("50-SMA", fmt_price(r["trend_sma"]) if not np.isnan(r["trend_sma"]) else "—")
    c5.metric("ATR", fmt_price(r["atr"]))
    c6.metric("Trail (now)", fmt_price(r["trail_now"]))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Buy Trigger", fmt_price(r["buy_trigger"]), delta=fmt_pct(-r["dist_pct"]))
    c2.metric("Initial Stop", fmt_price(r["initial_stop"]))
    c3.metric("Mean-Rev Exit", fmt_price(r["mean_exit"]))
    c4.metric("R:R to SMA", fmt_rr(r["rr"]))

    # Distance & position sizing hint
    dist_col, size_col, filter_col = st.columns(3)
    with dist_col:
        st.markdown(
            f"**Distance to trigger:** {fmt_price(r['dist_dollar'])} "
            f"({fmt_pct(r['dist_pct'])})"
        )
    with size_col:
        risk_per_share = r["risk"]
        if risk_per_share > 0 and capital > 0:
            # 1% risk of capital by default as a sizing reference
            shares = int((capital * 0.01) / risk_per_share)
            notional = shares * r["buy_trigger"]
            st.markdown(
                f"**Size @ 1% risk:** {shares:,} sh · "
                f"{fmt_price(notional)} notional"
            )
        else:
            st.markdown("**Size @ 1% risk:** —")
    with filter_col:
        filt = "ON (Close > 50-SMA)" if r["use_filter"] else "OFF"
        trend = "pass ✓" if r["trend_ok"] else "fail ✗"
        st.markdown(f"**Trend filter:** {filt} · **Status:** {trend}")

    if r["signal"]:
        st.success(
            f"**BUY SIGNAL** — Z ({r['z']:.2f}) < {z_entry}"
            + (" and Close > 50-SMA" if r["use_filter"] else " (no trend filter)")
        )
    elif r["status"] in ("NEAR", "WATCH"):
        st.warning(
            f"Within {r['dist_pct']:.1f}% of trigger "
            f"(${r['buy_trigger']:.2f}). Watching for Z < {z_entry}."
        )

    # Charts
    ch1, ch2 = st.columns([1.4, 1])
    with ch1:
        st.plotly_chart(
            price_chart(
                r["history"],
                r["ticker"],
                r["buy_trigger"],
                r["initial_stop"],
                r["mean_exit"],
                trend_sma_len=50,
                show_trend=True,
            ),
            use_container_width=True,
        )
    with ch2:
        st.plotly_chart(
            zscore_chart(r["history"], r["ticker"], z_entry),
            use_container_width=True,
        )


def render_bucket_tab(
    rows: list[dict],
    z_entry: float,
    capital: float,
    bucket_label: str,
    filter_desc: str,
):
    st.markdown(f"<div class='section-header'>{bucket_label}</div>", unsafe_allow_html=True)
    st.caption(filter_desc)

    if not rows:
        st.error("No data available for this bucket. Check network / yfinance.")
        return

    signals = [r for r in rows if r["signal"]]
    near = [r for r in rows if r["status"] in ("NEAR", "WATCH") and not r["signal"]]

    m1, m2, m3 = st.columns(3)
    m1.metric("Names", len(rows))
    m2.metric("Active BUY signals", len(signals))
    m3.metric("Near / Watch", len(near))

    # Compact table
    df = rows_to_dataframe(rows)
    display_cols = [
        "Ticker",
        "Price",
        "Z-Score",
        "20-SMA",
        "50-SMA",
        "ATR",
        "Buy Trigger",
        "Initial Stop",
        "Mean Exit",
        "Dist $",
        "Dist %",
        "R:R",
        "Trend OK",
        "Signal",
    ]
    st.dataframe(
        style_overview(df[display_cols], z_entry),
        use_container_width=True,
        hide_index=True,
    )

    st.divider()
    st.markdown("#### Stock detail")
    tickers = [r["ticker"] for r in rows]
    default_ix = 0
    for i, r in enumerate(rows):
        if r["signal"]:
            default_ix = i
            break
        if r["status"] in ("NEAR", "WATCH") and default_ix == 0:
            default_ix = i

    chosen = st.selectbox(
        "Select ticker",
        tickers,
        index=default_ix,
        key=f"select_{bucket_label}",
    )
    selected = next(r for r in rows if r["ticker"] == chosen)
    render_stock_card(selected, z_entry, capital)


def render_filter_comparison(
    ticker: str,
    z_entry: float,
    atr_mult: float,
    sma_window: int,
    atr_window: int,
    trend_sma: int,
    capital: float,
):
    """Side-by-side with filter vs without filter for any stock."""
    st.markdown(f"#### Filter comparison — **{ticker}**")
    st.caption(
        "Same mean-reversion entry, with vs without the mild trend filter "
        f"(Close > {trend_sma}-SMA)."
    )

    no_f = get_levels(
        ticker, False, z_entry, atr_mult, sma_window, atr_window, trend_sma
    )
    with_f = get_levels(
        ticker, True, z_entry, atr_mult, sma_window, atr_window, trend_sma
    )

    if not no_f or not with_f:
        st.error(f"Could not load data for {ticker}.")
        return

    left, right = st.columns(2)
    for col, r, title in [
        (left, no_f, "Without trend filter (Momentum rules)"),
        (right, with_f, f"With trend filter (Close > {trend_sma}-SMA)"),
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
            elif r["z"] < z_entry and not r["trend_ok"]:
                st.warning(
                    "Z is in entry zone, but trend filter blocks the trade."
                )
            else:
                st.info("No entry under these rules right now.")

    # Shared price chart
    st.plotly_chart(
        price_chart(
            no_f["history"],
            ticker,
            no_f["buy_trigger"],
            no_f["initial_stop"],
            no_f["mean_exit"],
            trend_sma_len=trend_sma,
            show_trend=True,
        ),
        use_container_width=True,
    )


def render_rules_tab(z_entry: float, atr_mult: float, sma_window: int, atr_window: int, trend_sma: int):
    st.markdown("### Dual-Mode Strategy Rules")

    st.markdown(
        f"""
#### Universe

| Bucket | Tickers | Trend filter |
|--------|---------|--------------|
| **Momentum** | {", ".join(MOMENTUM_BUCKET)} | None — pure mean reversion |
| **Quality** | {", ".join(QUALITY_BUCKET)} | Mild: Close > {trend_sma}-SMA |

#### Indicators
- **{sma_window}-SMA** and rolling std → Z-score = (Close − SMA) / std
- **ATR** ({atr_window}-period true range average)
- **{trend_sma}-SMA** — trend filter for Quality only

#### Entry
1. **Z-score < {z_entry}** (price stretched below the {sma_window}-SMA)
2. **Quality only:** Close must also be **above the {trend_sma}-SMA**
3. **Buy Trigger Price** = SMA + ({z_entry} × std)  
   → the price level where Z equals {z_entry}

#### Risk management
- **Initial stop** (if filled at trigger) = Buy Trigger − ({atr_mult} × ATR)
- **Trailing stop** = Close − ({atr_mult} × ATR) — **only raised**, never lowered
- Position sizing reference on the dashboard: **1% of capital** at risk to initial stop

#### Exit (whichever first)
1. **Trailing stop hit**
2. **Mean-reversion exit:** Z-score **> 0** (price back at / above the {sma_window}-SMA)

#### Design intent
| Mode | Philosophy |
|------|------------|
| Momentum | Catch deep dips in high-beta names with no trend gate — faster entries |
| Quality | Same dip-buy math, but only when the intermediate trend is still intact |

#### What this dashboard does **not** do
- It does **not** place orders or connect to a broker
- Trailing-stop path is shown as the *current* trail level (`Close − {atr_mult}×ATR`);
  live management of an open position still requires your own order management
"""
    )

    with st.expander("Formula reference", expanded=False):
        st.latex(r"Z_t = \frac{C_t - \mathrm{SMA}_n}{\sigma_n}")
        st.latex(rf"P_{{\mathrm{{trigger}}}} = \mathrm{{SMA}}_n + ({z_entry})\cdot\sigma_n")
        st.latex(
            rf"Stop_{{\mathrm{{init}}}} = P_{{\mathrm{{trigger}}}} - {atr_mult}\cdot\mathrm{{ATR}}"
        )
        st.latex(
            rf"Trail_t = C_t - {atr_mult}\cdot\mathrm{{ATR}}_t \quad (\text{{raise only}})"
        )
        st.latex(r"Exit: \quad Trail\ hit \;\mathbf{or}\; Z_t > 0")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
def main():
    # ── Sidebar ──────────────────────────────────────────────
    with st.sidebar:
        st.title("⚙️ Settings")
        st.caption("Dual-Mode Tactical Trading System")

        capital = st.number_input(
            "Capital ($)",
            min_value=1_000.0,
            max_value=50_000_000.0,
            value=DEFAULT_CAPITAL,
            step=5_000.0,
            format="%.0f",
            help="Used for 1% risk position-size reference only.",
        )
        z_entry = st.slider(
            "Z-score entry threshold",
            min_value=-3.0,
            max_value=-0.5,
            value=DEFAULT_Z_ENTRY,
            step=0.1,
            help="Enter when Z is below this value (more negative = deeper dip).",
        )
        atr_mult = st.slider(
            "ATR multiplier (stop)",
            min_value=1.0,
            max_value=4.0,
            value=DEFAULT_ATR_MULT,
            step=0.25,
        )
        trend_sma = st.slider(
            "Trend SMA length (Quality)",
            min_value=20,
            max_value=200,
            value=DEFAULT_TREND_SMA,
            step=5,
        )
        sma_window = st.number_input(
            "Z-score SMA window",
            min_value=10,
            max_value=50,
            value=DEFAULT_SMA_WINDOW,
            step=1,
        )
        atr_window = st.number_input(
            "ATR window",
            min_value=5,
            max_value=30,
            value=DEFAULT_ATR_WINDOW,
            step=1,
        )

        st.divider()
        auto = st.toggle("Auto-refresh (60s)", value=False)
        if st.button("🔄 Refresh data now", use_container_width=True, type="primary"):
            get_data.clear()
            st.rerun()

        st.divider()
        st.markdown("**Buckets**")
        st.markdown(f"Momentum: `{' · '.join(MOMENTUM_BUCKET)}`")
        st.markdown(f"Quality: `{' · '.join(QUALITY_BUCKET)}`")
        st.caption(
            f"Entry Z < {z_entry} · Trail {atr_mult}×ATR · "
            f"Quality filter: Close > {trend_sma}-SMA"
        )

        if auto:
            st.caption("Auto-refresh armed — page reloads ~every 60s.")
            # Lightweight JS-free approach: Streamlit fragment / meta refresh
            st.markdown(
                '<meta http-equiv="refresh" content="60">',
                unsafe_allow_html=True,
            )

    # ── Header ───────────────────────────────────────────────
    st.title("Dual-Mode Tactical Trading System")
    st.markdown(
        f"<span class='subtle'>ServiceNow & related names · "
        f"Live levels via yfinance · "
        f"Updated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</span>",
        unsafe_allow_html=True,
    )

    # ── Load data ────────────────────────────────────────────
    with st.spinner("Fetching market data…"):
        momentum_rows = scan_bucket(
            MOMENTUM_BUCKET,
            use_filter=False,
            z_entry=z_entry,
            atr_mult=atr_mult,
            sma_window=int(sma_window),
            atr_window=int(atr_window),
            trend_sma=int(trend_sma),
            bucket_name="Momentum",
        )
        quality_rows = scan_bucket(
            QUALITY_BUCKET,
            use_filter=True,
            z_entry=z_entry,
            atr_mult=atr_mult,
            sma_window=int(sma_window),
            atr_window=int(atr_window),
            trend_sma=int(trend_sma),
            bucket_name="Quality",
        )

    all_rows = momentum_rows + quality_rows
    buy_signals = [r for r in all_rows if r["signal"]]
    near_signals = [
        r for r in all_rows if r["status"] in ("NEAR", "WATCH") and not r["signal"]
    ]

    # KPI strip
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Tracked", len(all_rows))
    k2.metric("BUY signals", len(buy_signals))
    k3.metric("Near / Watch", len(near_signals))
    k4.metric("Z threshold", f"{z_entry}")
    k5.metric("Capital", f"${capital:,.0f}")

    if buy_signals:
        names = ", ".join(r["ticker"] for r in buy_signals)
        st.success(f"**Active BUY SIGNAL(s):** {names}")
    elif near_signals:
        names = ", ".join(
            f"{r['ticker']} ({r['dist_pct']:+.1f}%)" for r in near_signals
        )
        st.info(f"No active buys. Watching: {names}")
    else:
        st.info("No stocks near a buy trigger right now (all > ~12% away).")

    # ── Tabs ─────────────────────────────────────────────────
    tab_overview, tab_mom, tab_qual, tab_compare, tab_rules = st.tabs(
        [
            "📊 Overview",
            "⚡ Momentum Bucket",
            "◆ Quality Bucket",
            "🔀 Filter Compare",
            "📘 Rules",
        ]
    )

    with tab_overview:
        st.markdown(
            "<div class='section-header'>Live scanner — both buckets</div>",
            unsafe_allow_html=True,
        )
        if not all_rows:
            st.error("No market data returned. Check your connection and try Refresh.")
        else:
            df = rows_to_dataframe(all_rows)
            # Sort: BUY first, then by distance ascending
            order = {"BUY": 0, "NEAR": 1, "WATCH": 2, "FAR": 3}
            df["_sort"] = df["Signal"].map(lambda s: order.get(s, 9))
            df = df.sort_values(["_sort", "Dist %"]).drop(columns=["_sort"])

            show_cols = [
                "Ticker",
                "Bucket",
                "Price",
                "Z-Score",
                "20-SMA",
                "50-SMA",
                "ATR",
                "Buy Trigger",
                "Initial Stop",
                "Mean Exit",
                "Dist $",
                "Dist %",
                "Risk",
                "Reward",
                "R:R",
                "Trend OK",
                "Signal",
            ]
            st.dataframe(
                style_overview(df[show_cols], z_entry),
                use_container_width=True,
                hide_index=True,
                height=min(52 + 38 * len(df), 520),
            )

            st.divider()
            # Quick cards for active / near
            highlight = buy_signals + near_signals
            if highlight:
                st.markdown("#### Priority names")
                cols = st.columns(min(len(highlight), 4))
                for i, r in enumerate(highlight[:8]):
                    with cols[i % len(cols)]:
                        st.markdown(
                            f"**{r['ticker']}** {status_badge(r['status'])}",
                            unsafe_allow_html=True,
                        )
                        st.write(
                            f"{fmt_price(r['close'])} · Z {fmt_z(r['z'])}\n\n"
                            f"Trigger {fmt_price(r['buy_trigger'])} · "
                            f"Dist {fmt_pct(r['dist_pct'])}"
                        )

            st.divider()
            st.markdown("#### Deep dive")
            pick = st.selectbox(
                "Select any ticker",
                [r["ticker"] for r in all_rows],
                key="overview_pick",
            )
            render_stock_card(
                next(r for r in all_rows if r["ticker"] == pick),
                z_entry,
                capital,
            )

    with tab_mom:
        render_bucket_tab(
            momentum_rows,
            z_entry,
            capital,
            "Momentum bucket",
            "Original strategy — no trend filter. Entry when Z-score < threshold only.",
        )

    with tab_qual:
        render_bucket_tab(
            quality_rows,
            z_entry,
            capital,
            "Quality bucket",
            f"Mild trend filter: Close must be above the {trend_sma}-SMA, "
            f"and Z-score < {z_entry}.",
        )

    with tab_compare:
        st.markdown(
            "<div class='section-header'>With filter vs without filter</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Compare entry eligibility for any name under Momentum rules "
            "(no filter) vs Quality rules (trend filter on)."
        )
        cmp_ticker = st.selectbox(
            "Ticker",
            ALL_TICKERS,
            index=ALL_TICKERS.index("NOW") if "NOW" in ALL_TICKERS else 0,
            key="compare_ticker",
        )
        render_filter_comparison(
            cmp_ticker,
            z_entry,
            atr_mult,
            int(sma_window),
            int(atr_window),
            int(trend_sma),
            capital,
        )

    with tab_rules:
        render_rules_tab(
            z_entry, atr_mult, int(sma_window), int(atr_window), int(trend_sma)
        )

    st.markdown(
        "<div class='app-footer'>"
        "Dual-Mode Tactical Trading System · Educational / research use only · "
        "Not investment advice · Data: Yahoo Finance via yfinance"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
