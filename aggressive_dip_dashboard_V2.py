"""
Aggressive Dip Accumulation — Live Streamlit Dashboard
======================================================
Universe     : META, NVDA, NET
Entry        : 20-period Z-score < -1.2
Sizing       : 25% of equity (normal) / 35% if within 10 days after earnings
Exit         : Highest close since assumed entry − 4.0 × ATR(14)
               (ATR frozen at the assumed entry day)

Automatic position logic
------------------------
- Finds the most recent day Z crossed below the entry threshold
- Assumes entry at that day's close
- Tracks highest close since then → live trailing stop
- Emits SELL when Close < live trail
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
POST_EARNINGS_WINDOW = 10

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
    .sell-badge {
        display: inline-block;
        background: #dc2626;
        color: white;
        font-weight: 700;
        font-size: 0.85rem;
        letter-spacing: 0.04em;
        padding: 4px 12px;
        border-radius: 999px;
        margin-left: 8px;
    }
    .hold-badge {
        display: inline-block;
        background: #2563eb;
        color: white;
        font-weight: 600;
        font-size: 0.8rem;
        padding: 3px 10px;
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
def load_price_data(tickers: Tuple[str, ...], days: int = 400) -> Dict[str, pd.DataFrame]:
    end = datetime.now()
    start = end - timedelta(days=days + 80)
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
            ed = tk.get_earnings_dates(limit=16)
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


def find_assumed_entry(df: pd.DataFrame, z_entry: float, atr_mult: float) -> Optional[dict]:
    """
    Find the most recent day Z dropped below z_entry and treat it as entry.
    Returns entry date, entry price, ATR at entry, highest close since entry,
    current trailing stop, and whether the trail is currently hit.
    """
    if df is None or len(df) < 30:
        return None

    z = df["zscore"]
    signal = z < z_entry
    if not signal.any():
        return None

    signal_int = signal.astype(int)
    true_idx = np.where(signal_int.values == 1)[0]
    if len(true_idx) == 0:
        return None

    last_true = true_idx[-1]
    start_idx = last_true
    while start_idx > 0 and signal_int.iloc[start_idx - 1] == 1:
        start_idx -= 1

    entry_row = df.iloc[start_idx]
    if pd.isna(entry_row["atr"]) or entry_row["atr"] <= 0:
        return None

    entry_date = df.index[start_idx]
    entry_price = float(entry_row["Close"])
    atr_at_entry = float(entry_row["atr"])

    since = df.iloc[start_idx:]
    highest = float(since["Close"].max())
    highest_date = since["Close"].idxmax()

    trail = highest - atr_mult * atr_at_entry
    current_close = float(df.iloc[-1]["Close"])
    trail_hit = current_close < trail
    days_held = (df.index[-1] - entry_date).days
    unrealized_pct = (current_close / entry_price - 1) * 100

    return {
        "entry_date": entry_date,
        "entry_price": entry_price,
        "atr_at_entry": atr_at_entry,
        "highest": highest,
        "highest_date": highest_date,
        "trail": trail,
        "trail_hit": trail_hit,
        "days_held": days_held,
        "unrealized_pct": unrealized_pct,
        "still_in_signal": bool(signal.iloc[-1]),
    }


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

    std = float(df["Close"].rolling(20).std().iloc[-1])
    buy_trigger = sma + z_entry * std

    signal = z < z_entry
    post = is_post_earnings(df.index[-1], ticker, earnings, POST_EARNINGS_WINDOW)
    alloc = post_alloc if (signal and post) else normal_alloc

    initial_stop_today = close - atr_mult * atr

    dist_dollar = close - buy_trigger
    dist_pct = (close / buy_trigger - 1) * 100 if buy_trigger > 0 else 0

    assumed = find_assumed_entry(df, z_entry, atr_mult)

    if assumed and assumed["trail_hit"]:
        status = "SELL"
    elif signal:
        status = "BUY"
    elif assumed and not assumed["trail_hit"]:
        status = "HOLD"
    elif z < z_entry + 0.35:
        status = "NEAR"
    elif z < 0:
        status = "WATCH"
    else:
        status = "FAR"

    notional = capital * alloc
    shares = int(notional / close) if close > 0 else 0
    risk_per_share = max(close - initial_stop_today, 0)
    risk_dollars = shares * risk_per_share
    risk_pct = (risk_dollars / capital * 100) if capital > 0 else 0

    return {
        "ticker": ticker,
        "close": close,
        "z": z,
        "sma": sma,
        "atr": atr,
        "buy_trigger": buy_trigger,
        "initial_stop_today": initial_stop_today,
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
        "assumed": assumed,
        "history": df,
    }


# ─────────────────────────────────────────────────────────────
# Formatting helpers
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
    if status == "SELL":
        return '<span class="sell-badge">SELL — TRAIL HIT</span>'
    if status == "HOLD":
        return '<span class="hold-badge">HOLD (in trade)</span>'
    if status == "NEAR":
        return '<span class="watch-badge">NEAR TRIGGER</span>'
    if status == "WATCH":
        return '<span class="watch-badge">WATCH</span>'
    return '<span class="neutral-badge">—</span>'


# ─────────────────────────────────────────────────────────────
# Charts
# ─────────────────────────────────────────────────────────────
def price_chart(info: dict, z_entry: float, atr_mult: float) -> go.Figure:
    history = info["history"]
    ticker = info["ticker"]
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

    x0 = df.index[int(len(df) * 0.50)]
    x1 = df.index[-1]

    fig.add_shape(type="line", x0=x0, x1=x1, y0=info["buy_trigger"], y1=info["buy_trigger"],
                  line=dict(color="#16a34a", width=1.5, dash="dash"))
    fig.add_annotation(x=x1, y=info["buy_trigger"],
                       text=f" Buy Trigger ${info['buy_trigger']:.2f}",
                       showarrow=False, xanchor="left", font=dict(size=11, color="#16a34a"))

    assumed = info.get("assumed")
    if assumed:
        entry_date = assumed["entry_date"]
        fig.add_vline(x=entry_date, line_dash="dot", line_color="#a855f7", opacity=0.7)
        fig.add_annotation(x=entry_date, y=assumed["entry_price"],
                           text=" Entry", showarrow=False, yshift=12,
                           font=dict(size=10, color="#a855f7"))

        fig.add_shape(type="line",
                      x0=entry_date, x1=x1,
                      y0=assumed["trail"], y1=assumed["trail"],
                      line=dict(color="#dc2626", width=2, dash="dot"))
        fig.add_annotation(x=x1, y=assumed["trail"],
                           text=f" Live Trail ${assumed['trail']:.2f}",
                           showarrow=False, xanchor="left",
                           font=dict(size=11, color="#dc2626"))

    fig.update_layout(
        title=f"{ticker} — Price, Entry & Trailing Stop",
        xaxis_rangeslider_visible=False,
        height=440,
        margin=dict(l=40, r=150, t=50, b=40),
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
                  annotation_text="Mean", annotation_position="top right")
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
def render_stock_card(info: dict, z_entry: float, capital: float, atr_mult: float):
    ticker = info["ticker"]
    assumed = info.get("assumed")

    st.markdown(f"### {ticker}", unsafe_allow_html=True)
    st.markdown(status_badge(info["status"], info["is_post_earnings"]), unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Price", fmt_price(info["close"]))
    c2.metric("Z-Score", fmt_z(info["z"]))
    c3.metric("20-SMA", fmt_price(info["sma"]))
    c4.metric("ATR(14)", fmt_price(info["atr"]))
    c5.metric("Alloc", f"{info['alloc_pct']*100:.0f}%")

    if assumed:
        st.markdown("#### Assumed Open Position")
        p1, p2, p3, p4, p5 = st.columns(5)
        p1.metric("Entry Date", assumed["entry_date"].strftime("%Y-%m-%d"))
        p2.metric("Entry Price", fmt_price(assumed["entry_price"]))
        p3.metric("Highest Since", fmt_price(assumed["highest"]))
        p4.metric("Live Trail Stop", fmt_price(assumed["trail"]))
        p5.metric("Unrealized", fmt_pct(assumed["unrealized_pct"]))

        st.caption(
            f"Days held: {assumed['days_held']} · "
            f"ATR at entry: {fmt_price(assumed['atr_at_entry'])} · "
            f"Trail = Highest − {atr_mult}×ATR"
        )

        if assumed["trail_hit"]:
            st.error(
                f"**SELL SIGNAL** — Price ({fmt_price(info['close'])}) has broken the "
                f"trailing stop at {fmt_price(assumed['trail'])}."
            )
        else:
            st.info(
                f"**HOLD** — Trail is at {fmt_price(assumed['trail'])}. "
                f"Unrealized {fmt_pct(assumed['unrealized_pct'])}."
            )
    else:
        st.markdown("#### No assumed open position")
        st.caption("No recent Z-entry signal found in the lookback window.")

    st.markdown("#### New Entry / Add Levels")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Buy Trigger", fmt_price(info["buy_trigger"]))
    c2.metric("Initial Stop (today)", fmt_price(info["initial_stop_today"]))
    c3.metric("Dist to Trigger", f"{fmt_price(info['dist_dollar'])} ({fmt_pct(info['dist_pct'])})")
    c4.metric("Days to Earnings",
              str(info["days_to_earnings"]) if info["days_to_earnings"] is not None else "—")

    if info["signal"]:
        post_txt = " **(Post-Earnings — 35% size)**" if info["is_post_earnings"] else " **(Normal — 25% size)**"
        st.success(
            f"**BUY / ADD SIGNAL** — Z ({info['z']:.2f}) < {z_entry}{post_txt}\n\n"
            f"Suggested: **{info['shares']:,} shares** · {fmt_price(info['notional'])} notional · "
            f"Risk ≈ {fmt_price(info['risk_dollars'])} ({info['risk_pct']:.1f}% of capital)"
        )
    elif info["status"] in ("NEAR", "WATCH"):
        st.warning(f"Within {info['dist_pct']:.1f}% of trigger. Watching for Z < {z_entry}.")

    ch1, ch2 = st.columns([1.45, 1])
    with ch1:
        st.plotly_chart(
            price_chart(info, z_entry, atr_mult),
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
        assumed = r.get("assumed")
        records.append({
            "Ticker": r["ticker"],
            "Price": r["close"],
            "Z-Score": r["z"],
            "Signal": r["status"],
            "Post-Earn": "Yes" if r["is_post_earnings"] else "",
            "Entry": assumed["entry_price"] if assumed else None,
            "Trail Stop": assumed["trail"] if assumed else None,
            "Unrealized %": assumed["unrealized_pct"] if assumed else None,
            "Days Held": assumed["days_held"] if assumed else None,
            "Buy Trigger": r["buy_trigger"],
            "Dist %": r["dist_pct"],
            "Alloc": f"{r['alloc_pct']*100:.0f}%",
        })
    df = pd.DataFrame(records)

    order = {"SELL": 0, "BUY": 1, "HOLD": 2, "NEAR": 3, "WATCH": 4, "FAR": 5}
    df["_sort"] = df["Signal"].map(lambda s: order.get(s, 9))
    df = df.sort_values(["_sort", "Dist %"]).drop(columns=["_sort"])

    def color_signal(val):
        if val == "BUY":
            return "background-color: #166534; color: #dcfce7; font-weight: 700"
        if val == "SELL":
            return "background-color: #991b1b; color: #fecaca; font-weight: 700"
        if val == "HOLD":
            return "background-color: #1e40af; color: #dbeafe; font-weight: 600"
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

    def color_unreal(val):
        if isinstance(val, (int, float)):
            if val > 0:
                return "color: #16a34a; font-weight: 600"
            if val < 0:
                return "color: #dc2626; font-weight: 600"
        return ""

    styled = (
        df.style.format({
            "Price": "${:,.2f}",
            "Z-Score": "{:+.2f}",
            "Entry": "${:,.2f}",
            "Trail Stop": "${:,.2f}",
            "Unrealized %": "{:+.1f}%",
            "Buy Trigger": "${:,.2f}",
            "Dist %": "{:+.2f}%",
        }, na_rep="—")
        .map(color_signal, subset=["Signal"])
        .map(color_z, subset=["Z-Score"])
        .map(color_unreal, subset=["Unrealized %"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True, height=280)


def render_rules(z_entry, atr_mult, normal_alloc, post_alloc):
    st.markdown("### Aggressive Dip Accumulation — Strategy Rules")
    st.markdown(
        f"""
#### Universe
**META · NVDA · NET**

#### Entry / Add
- Z-score (20) < **{z_entry}**
- **Size**
  - Normal dip → **{normal_alloc*100:.0f}%** of equity
  - Post-earnings dip (≤ {POST_EARNINGS_WINDOW} days after report) → **{post_alloc*100:.0f}%** of equity
- Pyramiding allowed

#### Exit (Automatic in this dashboard)
- Finds the most recent day Z crossed below {z_entry}
- Assumes entry at that day’s close
- Freezes ATR from that day
- Live Trail = Highest close since entry − **{atr_mult} × ATR**
- **SELL** when Close < Live Trail

#### Design Intent
Buy temporary pullbacks in strong leaders with meaningful size,  
then let the wide volatility trail keep you in the trend.
"""
    )
    with st.expander("Formulas", expanded=False):
        st.latex(r"Z_t = \dfrac{C_t - \mathrm{SMA}_{20}}{\sigma_{20}}")
        st.latex(rf"Stop = H_t - {atr_mult}\cdot\mathrm{{ATR}}_{{\mathrm{{entry}}}}")
        st.markdown("Where \( H_t \) is the highest close since the assumed entry day.")


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
def main():
    with st.sidebar:
        st.title("⚙️ Settings")
        st.caption("Aggressive Dip Accumulation")

        capital = st.number_input(
            "Capital ($)", min_value=1_000.0, max_value=50_000_000.0,
            value=DEFAULT_CAPITAL, step=5_000.0, format="%.0f"
        )
        z_entry = st.slider("Z-score entry", -2.0, -0.5, DEFAULT_Z_ENTRY, 0.1)
        atr_mult = st.slider("ATR multiplier", 2.0, 6.0, DEFAULT_ATR_MULT, 0.25)
        normal_alloc = st.slider("Normal dip size", 0.10, 0.40, DEFAULT_NORMAL_ALLOC, 0.05)
        post_alloc = st.slider("Post-earnings size", 0.15, 0.50, DEFAULT_POST_ALLOC, 0.05)

        st.divider()
        if st.button("🔄 Refresh data", use_container_width=True, type="primary"):
            load_price_data.clear()
            load_earnings_dates.clear()
            st.rerun()

        st.divider()
        st.markdown("**Universe** `META · NVDA · NET`")
        st.caption(f"Z < {z_entry} · Trail {atr_mult}×ATR · "
                   f"{normal_alloc*100:.0f}% / {post_alloc*100:.0f}% post-earn")

    st.title("Aggressive Dip Accumulation")
    st.markdown(
        f"<span class='subtle'>META · NVDA · NET · Z < {z_entry} · {atr_mult}× ATR trail · "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}</span>",
        unsafe_allow_html=True,
    )

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

    buys = [r for r in rows if r["status"] == "BUY"]
    sells = [r for r in rows if r["status"] == "SELL"]
    holds = [r for r in rows if r["status"] == "HOLD"]

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Tracked", len(rows))
    k2.metric("BUY", len(buys))
    k3.metric("SELL", len(sells))
    k4.metric("HOLD (in trade)", len(holds))
    k5.metric("Capital", f"${capital:,.0f}")

    if sells:
        names = ", ".join(r["ticker"] for r in sells)
        st.error(f"**SELL SIGNAL(s) — trailing stop hit:** {names}")
    if buys:
        names = ", ".join(
            f"{r['ticker']}{' (Post-Earn)' if r['is_post_earnings'] else ''}"
            for r in buys
        )
        st.success(f"**BUY / ADD SIGNAL(s):** {names}")
    if holds and not sells and not buys:
        names = ", ".join(
            f"{r['ticker']} ({fmt_pct(r['assumed']['unrealized_pct'])})"
            for r in holds if r.get("assumed")
        )
        st.info(f"**Currently holding:** {names}")

    tab_ov, tab_det, tab_earn, tab_rules = st.tabs([
        "📊 Overview", "🔎 Stock Detail", "📅 Earnings", "📘 Rules"
    ])

    with tab_ov:
        st.markdown("<div class='section-header'>Live Scanner — Buy & Sell Signals</div>",
                    unsafe_allow_html=True)
        render_overview_table(rows, z_entry)

    with tab_det:
        if not rows:
            st.warning("No data.")
        else:
            tickers = [r["ticker"] for r in rows]
            default_ix = 0
            for i, r in enumerate(rows):
                if r["status"] == "SELL":
                    default_ix = i
                    break
                if r["status"] == "BUY" and default_ix == 0:
                    default_ix = i
            chosen = st.selectbox("Select ticker", tickers, index=default_ix)
            selected = next(r for r in rows if r["ticker"] == chosen)
            render_stock_card(selected, z_entry, capital, atr_mult)

    with tab_earn:
        st.markdown("<div class='section-header'>Earnings & Post-Earnings Window</div>",
                    unsafe_allow_html=True)
        st.caption(f"Post-earnings size boost active for {POST_EARNINGS_WINDOW} days after the report.")
        today = pd.Timestamp.now().normalize()
        for t in TICKERS:
            eds = earnings.get(t, [])
            recent = [d for d in eds if d <= today][-4:]
            upcoming = [d for d in eds if d > today][:3]
            st.markdown(f"**{t}**")
            c1, c2 = st.columns(2)
            with c1:
                st.write("Recent:")
                for d in recent:
                    delta = (today - d).days
                    flag = " ← **boost window**" if delta <= POST_EARNINGS_WINDOW else ""
                    st.markdown(f"• {d.date()} ({delta}d ago){flag}")
            with c2:
                st.write("Upcoming:")
                if upcoming:
                    for d in upcoming:
                        st.write(f"• {d.date()} (in {(d-today).days}d)")
                else:
                    st.write("—")
            st.divider()

    with tab_rules:
        render_rules(z_entry, atr_mult, normal_alloc, post_alloc)

    st.markdown(
        "<div class='app-footer'>"
        "Aggressive Dip Accumulation · Educational use only · Not investment advice · Data: Yahoo Finance"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
