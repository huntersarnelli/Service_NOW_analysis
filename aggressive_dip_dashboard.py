"""
Aggressive Dip Accumulation — Live Streamlit Dashboard
======================================================
Universe : META, NVDA, NET, DDOG   (performance-maximizing set)
Entry    : 20-period Z-score < -1.2
Sizing   : 25% of equity (normal) / 35% post-earnings
Exit     : Highest close since assumed entry − 4.0 × ATR (frozen at entry)
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
TICKERS = ["META", "NVDA", "NET", "DDOG"]
DEFAULT_CAPITAL = 100_000.0
DEFAULT_Z_ENTRY = -1.2
DEFAULT_ATR_MULT = 4.0
DEFAULT_NORMAL_ALLOC = 0.25
DEFAULT_POST_ALLOC = 0.35
DEFAULT_Z_WINDOW = 20
DEFAULT_ATR_WINDOW = 14
POST_EARNINGS_WINDOW = 10

# ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Aggressive Dip Accumulation",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    div[data-testid="stMetric"] {
        background: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.25);
        border-radius: 10px;
        padding: 12px 16px;
    }
    .buy-badge {
        display: inline-block; background: #16a34a; color: white;
        font-weight: 700; font-size: 0.85rem; padding: 4px 12px;
        border-radius: 999px; margin-left: 8px;
    }
    .sell-badge {
        display: inline-block; background: #dc2626; color: white;
        font-weight: 700; font-size: 0.85rem; padding: 4px 12px;
        border-radius: 999px; margin-left: 8px;
    }
    .hold-badge {
        display: inline-block; background: #2563eb; color: white;
        font-weight: 600; font-size: 0.8rem; padding: 3px 10px;
        border-radius: 999px; margin-left: 8px;
    }
    .post-badge {
        display: inline-block; background: #7c3aed; color: white;
        font-weight: 600; font-size: 0.8rem; padding: 3px 10px;
        border-radius: 999px; margin-left: 8px;
    }
    .watch-badge {
        display: inline-block; background: #ca8a04; color: white;
        font-weight: 600; font-size: 0.8rem; padding: 3px 10px;
        border-radius: 999px; margin-left: 8px;
    }
    .neutral-badge {
        display: inline-block; background: rgba(128,128,128,0.35);
        color: inherit; font-weight: 600; font-size: 0.8rem;
        padding: 3px 10px; border-radius: 999px; margin-left: 8px;
    }
    .section-header { font-size: 1.15rem; font-weight: 650; margin: 0.4rem 0 0.6rem 0; }
    .subtle { opacity: 0.75; font-size: 0.9rem; }
    .app-footer {
        margin-top: 2rem; padding-top: 1rem;
        border-top: 1px solid rgba(128,128,128,0.25);
        font-size: 0.85rem; opacity: 0.7;
    }
    .fresh-ts {
        font-size: 0.8rem; opacity: 0.7; margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# Data — NO long-lived cache on the critical path
# ─────────────────────────────────────────────────────────────
def fetch_prices(tickers: List[str], days: int = 400) -> Dict[str, pd.DataFrame]:
    """Always hits the network. Caller decides whether to cache the result."""
    end = datetime.now()
    start = end - timedelta(days=days + 80)
    raw = yf.download(
        tickers,
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(days=1)).strftime("%Y-%m-%d"),
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


def fetch_earnings(tickers: List[str]) -> Dict[str, List[pd.Timestamp]]:
    earnings = {}
    for t in tickers:
        try:
            ed = yf.Ticker(t).get_earnings_dates(limit=16)
            dates = []
            if ed is not None and len(ed) > 0:
                for idx in ed.index:
                    d = pd.Timestamp(idx).tz_localize(None).normalize()
                    dates.append(d)
            earnings[t] = sorted(set(dates))
        except Exception:
            earnings[t] = []
    return earnings


def add_indicators(df: pd.DataFrame, z_window: int = 20, atr_window: int = 14) -> pd.DataFrame:
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
    trail = highest - atr_mult * atr_at_entry
    current_close = float(df.iloc[-1]["Close"])
    return {
        "entry_date": entry_date,
        "entry_price": entry_price,
        "atr_at_entry": atr_at_entry,
        "highest": highest,
        "trail": trail,
        "trail_hit": current_close < trail,
        "days_held": (df.index[-1] - entry_date).days,
        "unrealized_pct": (current_close / entry_price - 1) * 100,
    }


def compute_levels(df, ticker, z_entry, atr_mult, capital, normal_alloc, post_alloc, earnings):
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
    risk_dollars = shares * max(close - initial_stop_today, 0)
    risk_pct = (risk_dollars / capital * 100) if capital > 0 else 0

    return {
        "ticker": ticker, "close": close, "z": z, "sma": sma, "atr": atr,
        "buy_trigger": buy_trigger, "initial_stop_today": initial_stop_today,
        "dist_pct": dist_pct, "signal": signal, "status": status,
        "is_post_earnings": post, "alloc_pct": alloc, "shares": shares,
        "notional": notional, "risk_dollars": risk_dollars, "risk_pct": risk_pct,
        "days_to_earnings": days_to_next_earnings(ticker, earnings),
        "assumed": assumed, "history": df,
        "last_bar_date": df.index[-1],
    }


# ─────────────────────────────────────────────────────────────
def fmt_price(x): return f"${x:,.2f}"
def fmt_pct(x): return f"{x:+.2f}%"
def fmt_z(x): return f"{x:+.2f}"

def status_badge(status, is_post=False):
    if status == "BUY":
        b = '<span class="buy-badge">BUY SIGNAL</span>'
        if is_post: b += '<span class="post-badge">POST-EARNINGS</span>'
        return b
    if status == "SELL": return '<span class="sell-badge">SELL — TRAIL HIT</span>'
    if status == "HOLD": return '<span class="hold-badge">HOLD (in trade)</span>'
    if status == "NEAR": return '<span class="watch-badge">NEAR TRIGGER</span>'
    if status == "WATCH": return '<span class="watch-badge">WATCH</span>'
    return '<span class="neutral-badge">—</span>'


def price_chart(info, z_entry, atr_mult):
    df = info["history"].dropna(subset=["sma"]).copy()
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="Price", increasing_line_color="#16a34a", decreasing_line_color="#dc2626"))
    fig.add_trace(go.Scatter(x=df.index, y=df["sma"], name="20-SMA",
                             line=dict(color="#3b82f6", width=1.5)))
    x0, x1 = df.index[int(len(df)*0.5)], df.index[-1]
    fig.add_shape(type="line", x0=x0, x1=x1, y0=info["buy_trigger"], y1=info["buy_trigger"],
                  line=dict(color="#16a34a", width=1.5, dash="dash"))
    fig.add_annotation(x=x1, y=info["buy_trigger"], text=f" Buy Trigger ${info['buy_trigger']:.2f}",
                       showarrow=False, xanchor="left", font=dict(size=11, color="#16a34a"))
    assumed = info.get("assumed")
    if assumed:
        fig.add_vline(x=assumed["entry_date"], line_dash="dot", line_color="#a855f7", opacity=0.7)
        fig.add_shape(type="line", x0=assumed["entry_date"], x1=x1,
                      y0=assumed["trail"], y1=assumed["trail"],
                      line=dict(color="#dc2626", width=2, dash="dot"))
        fig.add_annotation(x=x1, y=assumed["trail"], text=f" Live Trail ${assumed['trail']:.2f}",
                           showarrow=False, xanchor="left", font=dict(size=11, color="#dc2626"))
    fig.update_layout(title=f"{info['ticker']} — Price, Entry & Trail",
                      xaxis_rangeslider_visible=False, height=420,
                      margin=dict(l=40, r=150, t=50, b=40),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                      template="plotly_dark" if st.get_option("theme.base")=="dark" else "plotly_white")
    return fig


def zscore_chart(history, ticker, z_entry):
    df = history.dropna(subset=["zscore"]).copy()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df.index, y=df["zscore"], name="Z-Score",
                             line=dict(color="#38bdf8", width=2),
                             fill="tozeroy", fillcolor="rgba(56,189,248,0.12)"))
    fig.add_hline(y=z_entry, line_dash="dash", line_color="#16a34a",
                  annotation_text=f"Entry Z = {z_entry}", annotation_position="bottom right")
    fig.add_hline(y=0, line_dash="dash", line_color="#3b82f6")
    fig.update_layout(title=f"{ticker} — Z-Score", height=280,
                      margin=dict(l=40, r=40, t=50, b=40),
                      template="plotly_dark" if st.get_option("theme.base")=="dark" else "plotly_white")
    return fig


def render_overview(rows, z_entry):
    records = []
    for r in rows:
        a = r.get("assumed")
        records.append({
            "Ticker": r["ticker"], "Price": r["close"], "Z-Score": r["z"],
            "Signal": r["status"], "Post-Earn": "Yes" if r["is_post_earnings"] else "",
            "Entry": a["entry_price"] if a else None,
            "Trail Stop": a["trail"] if a else None,
            "Unrealized %": a["unrealized_pct"] if a else None,
            "Days Held": a["days_held"] if a else None,
            "Buy Trigger": r["buy_trigger"], "Dist %": r["dist_pct"],
            "Alloc": f"{r['alloc_pct']*100:.0f}%",
            "Last Bar": r["last_bar_date"].strftime("%Y-%m-%d"),
        })
    df = pd.DataFrame(records)
    order = {"SELL":0,"BUY":1,"HOLD":2,"NEAR":3,"WATCH":4,"FAR":5}
    df["_s"] = df["Signal"].map(lambda s: order.get(s,9))
    df = df.sort_values(["_s","Dist %"]).drop(columns=["_s"])

    def c_sig(v):
        if v=="BUY": return "background-color:#166534;color:#dcfce7;font-weight:700"
        if v=="SELL": return "background-color:#991b1b;color:#fecaca;font-weight:700"
        if v=="HOLD": return "background-color:#1e40af;color:#dbeafe;font-weight:600"
        if v in ("NEAR","WATCH"): return "background-color:#854d0e;color:#fef9c3;font-weight:600"
        return ""
    def c_z(v):
        if isinstance(v,(int,float)):
            if v < z_entry: return "color:#16a34a;font-weight:700"
            if v < 0: return "color:#ca8a04"
        return ""
    def c_u(v):
        if isinstance(v,(int,float)):
            if v>0: return "color:#16a34a;font-weight:600"
            if v<0: return "color:#dc2626;font-weight:600"
        return ""

    styled = (df.style
        .format({"Price":"${:,.2f}","Z-Score":"{:+.2f}","Entry":"${:,.2f}",
                 "Trail Stop":"${:,.2f}","Unrealized %":"{:+.1f}%",
                 "Buy Trigger":"${:,.2f}","Dist %":"{:+.2f}%"}, na_rep="—")
        .map(c_sig, subset=["Signal"]).map(c_z, subset=["Z-Score"]).map(c_u, subset=["Unrealized %"]))
    st.dataframe(styled, use_container_width=True, hide_index=True, height=300)


def render_card(info, z_entry, capital, atr_mult):
    st.markdown(f"### {info['ticker']}", unsafe_allow_html=True)
    st.markdown(status_badge(info["status"], info["is_post_earnings"]), unsafe_allow_html=True)
    st.caption(f"Last bar: {info['last_bar_date'].strftime('%Y-%m-%d')} · "
               f"Fetched: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Price", fmt_price(info["close"]))
    c2.metric("Z-Score", fmt_z(info["z"]))
    c3.metric("20-SMA", fmt_price(info["sma"]))
    c4.metric("ATR(14)", fmt_price(info["atr"]))
    c5.metric("Alloc", f"{info['alloc_pct']*100:.0f}%")

    assumed = info.get("assumed")
    if assumed:
        st.markdown("#### Assumed Open Position")
        p1,p2,p3,p4,p5 = st.columns(5)
        p1.metric("Entry Date", assumed["entry_date"].strftime("%Y-%m-%d"))
        p2.metric("Entry Price", fmt_price(assumed["entry_price"]))
        p3.metric("Highest Since", fmt_price(assumed["highest"]))
        p4.metric("Live Trail", fmt_price(assumed["trail"]))
        p5.metric("Unrealized", fmt_pct(assumed["unrealized_pct"]))
        if assumed["trail_hit"]:
            st.error(f"**SELL** — Price broke trail at {fmt_price(assumed['trail'])}")
        else:
            st.info(f"**HOLD** — Trail {fmt_price(assumed['trail'])} · "
                    f"Unrealized {fmt_pct(assumed['unrealized_pct'])}")

    st.markdown("#### New Entry / Add Levels")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Buy Trigger", fmt_price(info["buy_trigger"]))
    c2.metric("Initial Stop (today)", fmt_price(info["initial_stop_today"]))
    c3.metric("Dist to Trigger", fmt_pct(info["dist_pct"]))
    c4.metric("Days to Earnings", str(info["days_to_earnings"]) if info["days_to_earnings"] is not None else "—")

    if info["signal"]:
        post = " **(Post-Earnings 35%)**" if info["is_post_earnings"] else " **(Normal 25%)**"
        st.success(f"**BUY / ADD** — Z {info['z']:.2f} < {z_entry}{post}\n\n"
                   f"Suggested **{info['shares']:,} shares** · {fmt_price(info['notional'])} · "
                   f"Risk ≈ {fmt_price(info['risk_dollars'])} ({info['risk_pct']:.1f}%)")

    ch1, ch2 = st.columns([1.45, 1])
    with ch1:
        st.plotly_chart(price_chart(info, z_entry, atr_mult), use_container_width=True,
                        key=f"price_{info['ticker']}_{info['last_bar_date']}")
    with ch2:
        st.plotly_chart(zscore_chart(info["history"], info["ticker"], z_entry),
                        use_container_width=True, key=f"z_{info['ticker']}_{info['last_bar_date']}")


def render_rules(z_entry, atr_mult, normal_alloc, post_alloc):
    st.markdown("### Strategy Rules")
    st.markdown(f"""
**Universe:** META · NVDA · NET · DDOG

**Entry:** Z-score (20) < **{z_entry}**  
**Size:** {normal_alloc*100:.0f}% normal · {post_alloc*100:.0f}% if within {POST_EARNINGS_WINDOW}d after earnings  
**Exit:** Highest close since entry − **{atr_mult} × ATR** (ATR frozen at entry)

This is the performance-maximizing set from the portfolio tests.
""")


# ─────────────────────────────────────────────────────────────
def main():
    # Session state for data freshness
    if "data_version" not in st.session_state:
        st.session_state.data_version = 0
        st.session_state.last_fetch = None
        st.session_state.price_data = None
        st.session_state.earnings = None

    with st.sidebar:
        st.title("⚙️ Settings")
        st.caption("Aggressive Dip Accumulation")
        capital = st.number_input("Capital ($)", 1000.0, 50_000_000.0, DEFAULT_CAPITAL, 5000.0, format="%.0f")
        z_entry = st.slider("Z-score entry", -2.0, -0.5, DEFAULT_Z_ENTRY, 0.1)
        atr_mult = st.slider("ATR multiplier", 2.0, 6.0, DEFAULT_ATR_MULT, 0.25)
        normal_alloc = st.slider("Normal dip size", 0.10, 0.40, DEFAULT_NORMAL_ALLOC, 0.05)
        post_alloc = st.slider("Post-earnings size", 0.15, 0.50, DEFAULT_POST_ALLOC, 0.05)

        st.divider()
        if st.button("🔄 Refresh prices now", use_container_width=True, type="primary"):
            st.session_state.data_version += 1
            st.session_state.price_data = None
            st.session_state.earnings = None
            st.session_state.last_fetch = None
            st.rerun()

        st.divider()
        st.markdown("**Universe**")
        st.markdown("`META · NVDA · NET · DDOG`")
        st.caption(f"Z < {z_entry} · {atr_mult}×ATR · {normal_alloc*100:.0f}% / {post_alloc*100:.0f}%")

    st.title("Aggressive Dip Accumulation")
    st.markdown(
        f"<span class='subtle'>META · NVDA · NET · DDOG · Z < {z_entry} · {atr_mult}× ATR · "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</span>",
        unsafe_allow_html=True,
    )

    # Fetch only when needed
    need_fetch = (
        st.session_state.price_data is None
        or st.session_state.last_fetch is None
        or (datetime.now() - st.session_state.last_fetch).total_seconds() > 120
    )

    if need_fetch:
        with st.spinner("Fetching fresh market data…"):
            st.session_state.price_data = fetch_prices(TICKERS)
            st.session_state.earnings = fetch_earnings(TICKERS)
            st.session_state.last_fetch = datetime.now()

    price_data = st.session_state.price_data
    earnings = st.session_state.earnings

    rows = []
    for t in TICKERS:
        if t not in price_data:
            continue
        df = add_indicators(price_data[t])
        info = compute_levels(df, t, z_entry, atr_mult, capital, normal_alloc, post_alloc, earnings)
        if info:
            rows.append(info)

    # Show data freshness
    if st.session_state.last_fetch:
        ages = []
        for r in rows:
            ages.append(f"{r['ticker']} {r['last_bar_date'].strftime('%m-%d')}")
        st.markdown(
            f"<div class='fresh-ts'>Data fetched: {st.session_state.last_fetch.strftime('%H:%M:%S')} · "
            f"Last bars: {', '.join(ages)}</div>",
            unsafe_allow_html=True,
        )

    buys = [r for r in rows if r["status"]=="BUY"]
    sells = [r for r in rows if r["status"]=="SELL"]
    holds = [r for r in rows if r["status"]=="HOLD"]

    k1,k2,k3,k4,k5 = st.columns(5)
    k1.metric("Tracked", len(rows))
    k2.metric("BUY", len(buys))
    k3.metric("SELL", len(sells))
    k4.metric("HOLD", len(holds))
    k5.metric("Capital", f"${capital:,.0f}")

    if sells:
        st.error("**SELL SIGNAL(s):** " + ", ".join(r["ticker"] for r in sells))
    if buys:
        st.success("**BUY / ADD:** " + ", ".join(
            f"{r['ticker']}{' (Post-Earn)' if r['is_post_earnings'] else ''}" for r in buys))
    if holds and not sells and not buys:
        st.info("**Holding:** " + ", ".join(
            f"{r['ticker']} ({fmt_pct(r['assumed']['unrealized_pct'])})" for r in holds if r.get("assumed")))

    tab_ov, tab_det, tab_earn, tab_rules = st.tabs(
        ["📊 Overview", "🔎 Stock Detail", "📅 Earnings", "📘 Rules"])

    with tab_ov:
        st.markdown("<div class='section-header'>Live Scanner</div>", unsafe_allow_html=True)
        render_overview(rows, z_entry)

    with tab_det:
        if not rows:
            st.warning("No data")
        else:
            tickers = [r["ticker"] for r in rows]
            default_ix = 0
            for i,r in enumerate(rows):
                if r["status"]=="SELL": default_ix=i; break
                if r["status"]=="BUY" and default_ix==0: default_ix=i
            chosen = st.selectbox("Select ticker", tickers, index=default_ix)
            selected = next(r for r in rows if r["ticker"]==chosen)
            render_card(selected, z_entry, capital, atr_mult)

    with tab_earn:
        st.markdown("<div class='section-header'>Earnings</div>", unsafe_allow_html=True)
        today = pd.Timestamp.now().normalize()
        for t in TICKERS:
            eds = earnings.get(t, [])
            recent = [d for d in eds if d <= today][-4:]
            upcoming = [d for d in eds if d > today][:3]
            st.markdown(f"**{t}**")
            c1,c2 = st.columns(2)
            with c1:
                st.write("Recent:")
                for d in recent:
                    delta = (today-d).days
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
        "<div class='app-footer'>Aggressive Dip Accumulation · Educational only · Not investment advice · Data: Yahoo Finance</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
