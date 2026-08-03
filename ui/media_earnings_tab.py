"""
Media & Earnings tab — presentation layer only.

Data comes from data.media_earnings. Nothing here modifies BUY signals,
Z-scores, stops, or universe filters.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.media_earnings import (
    get_all_media_earnings_summary,
    get_ticker_media_earnings,
    media_score_label,
    score_to_sentiment_label,
)

# ─────────────────────────────────────────────────────────────
# Cached loaders (Streamlit-only; notebooks call data layer directly)
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=900, show_spinner=False)
def _cached_summary(tickers: tuple[str, ...], api_key: str) -> pd.DataFrame:
    # Free AV tier: gentle pacing when a real key is present
    sleep = 12.0 if api_key else 0.0
    return get_all_media_earnings_summary(
        list(tickers),
        api_key=api_key or None,
        sleep_between_av=sleep,
    )


@st.cache_data(ttl=900, show_spinner=False)
def _cached_detail(ticker: str, api_key: str) -> dict:
    return get_ticker_media_earnings(ticker, api_key=api_key or None)


def clear_media_earnings_cache() -> None:
    """Clear Streamlit caches for media/earnings loaders (used by Refresh)."""
    _cached_summary.clear()
    _cached_detail.clear()


# ─────────────────────────────────────────────────────────────
# Formatting / styling
# ─────────────────────────────────────────────────────────────
def _fmt_score(x: Optional[float]) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:+.2f}"


def _fmt_surprise(x: Optional[float]) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:+.1f}%"


def _badge_html(badge: str) -> str:
    colors = {
        "Good": ("#166534", "#dcfce7"),
        "Neutral": ("rgba(100,116,139,0.45)", "inherit"),
        "Bad": ("#991b1b", "#fee2e2"),
    }
    bg, fg = colors.get(badge, colors["Neutral"])
    return (
        f'<span style="display:inline-block;background:{bg};color:{fg};'
        f'font-weight:700;font-size:0.78rem;padding:3px 10px;border-radius:999px;">'
        f"{badge}</span>"
    )


def _sentiment_pill(label: str) -> str:
    palette = {
        "Bullish": "#16a34a",
        "Somewhat Bullish": "#65a30d",
        "Neutral": "#64748b",
        "Somewhat Bearish": "#d97706",
        "Bearish": "#dc2626",
    }
    color = palette.get(label, "#64748b")
    return (
        f'<span style="display:inline-block;background:{color};color:white;'
        f'font-weight:600;font-size:0.75rem;padding:2px 8px;border-radius:999px;">'
        f"{label}</span>"
    )


def _style_summary(df: pd.DataFrame):
    if df.empty:
        return df

    def color_badge(val):
        if val == "Good":
            return "background-color: #166534; color: #dcfce7; font-weight: 700"
        if val == "Bad":
            return "background-color: #991b1b; color: #fee2e2; font-weight: 700"
        if val == "Neutral":
            return "background-color: #334155; color: #e2e8f0;"
        return ""

    def color_beat(val):
        if val == "Beat":
            return "background-color: #166534; color: #dcfce7; font-weight: 700"
        if val == "Miss":
            return "background-color: #991b1b; color: #fee2e2; font-weight: 700"
        if val == "Inline":
            return "background-color: #854d0e; color: #fef9c3; font-weight: 600"
        return ""

    def color_score(val):
        if isinstance(val, (int, float)) and not np.isnan(val):
            if val > 0.15:
                return "color: #16a34a; font-weight: 700"
            if val < -0.15:
                return "color: #dc2626; font-weight: 700"
        return ""

    display = df.copy()
    # Format next earnings for display
    if "Next Earnings" in display.columns:
        display["Next Earnings"] = display["Next Earnings"].apply(
            lambda d: d.isoformat() if hasattr(d, "isoformat") and d is not None else ("—" if d is None or (isinstance(d, float) and np.isnan(d)) else str(d))
        )

    subset_badge = [c for c in ("Media Badge 7D", "Media Badge 30D") if c in display.columns]
    subset_beat = [c for c in ("Last Beat/Miss",) if c in display.columns]
    subset_score = [c for c in ("Media 7D", "Media 30D") if c in display.columns]

    styled = display.style.format(
        {
            "Media 7D": lambda v: _fmt_score(v),
            "Media 30D": lambda v: _fmt_score(v),
            "Last Surprise %": lambda v: _fmt_surprise(v),
            "Days to Earnings": lambda v: (
                "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{int(v)}"
            ),
        },
        na_rep="—",
    )
    if subset_badge:
        styled = styled.map(color_badge, subset=subset_badge)
    if subset_beat:
        styled = styled.map(color_beat, subset=subset_beat)
    if subset_score:
        styled = styled.map(color_score, subset=subset_score)
    return styled


def _style_earnings_history(df: pd.DataFrame):
    if df.empty:
        return df

    show = df.copy()
    if "Earnings Date" in show.columns:
        show["Earnings Date"] = show["Earnings Date"].apply(
            lambda d: pd.Timestamp(d).strftime("%Y-%m-%d") if pd.notna(d) else "—"
        )

    def color_beat(val):
        if val == "Beat":
            return "background-color: #166534; color: #dcfce7; font-weight: 700"
        if val == "Miss":
            return "background-color: #991b1b; color: #fee2e2; font-weight: 700"
        if val == "Inline":
            return "background-color: #854d0e; color: #fef9c3; font-weight: 600"
        return ""

    def color_surp(val):
        if isinstance(val, (int, float)) and not np.isnan(val):
            if val > 0:
                return "color: #16a34a; font-weight: 700"
            if val < 0:
                return "color: #dc2626; font-weight: 700"
        return ""

    def color_rx(val):
        if isinstance(val, (int, float)) and not np.isnan(val):
            if val > 0:
                return "color: #16a34a; font-weight: 600"
            if val < 0:
                return "color: #dc2626; font-weight: 600"
        return ""

    styled = show.style.format(
        {
            "EPS Estimate": lambda v: "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.2f}",
            "Reported EPS": lambda v: "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.2f}",
            "Surprise %": lambda v: _fmt_surprise(v),
            "Reaction 1D %": lambda v: _fmt_surprise(v),
        },
        na_rep="—",
    )
    if "Beat/Miss" in show.columns:
        styled = styled.map(color_beat, subset=["Beat/Miss"])
    if "Surprise %" in show.columns:
        styled = styled.map(color_surp, subset=["Surprise %"])
    if "Reaction 1D %" in show.columns:
        styled = styled.map(color_rx, subset=["Reaction 1D %"])
    return styled


# ─────────────────────────────────────────────────────────────
# Charts
# ─────────────────────────────────────────────────────────────
def _sentiment_trend_chart(daily: pd.Series, ticker: str) -> go.Figure:
    s = daily.dropna() if daily is not None else pd.Series(dtype=float)
    fig = go.Figure()
    if s.empty:
        fig.add_annotation(
            text="No sentiment history available",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
    else:
        fig.add_trace(
            go.Scatter(
                x=s.index,
                y=s.values,
                name="Avg media score",
                line=dict(color="#38bdf8", width=2),
                fill="tozeroy",
                fillcolor="rgba(56,189,248,0.12)",
            )
        )
        fig.add_hline(y=0.15, line_dash="dot", line_color="#16a34a", annotation_text="Good")
        fig.add_hline(y=-0.15, line_dash="dot", line_color="#dc2626", annotation_text="Bad")
        fig.add_hline(y=0, line_dash="dash", line_color="#64748b")

    template = "plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white"
    fig.update_layout(
        title=f"{ticker} — Media sentiment (daily avg)",
        height=320,
        margin=dict(l=40, r=40, t=50, b=40),
        template=template,
        yaxis_title="Score (−1 … +1)",
        yaxis=dict(range=[-1.05, 1.05]),
        showlegend=False,
    )
    return fig


def _earnings_surprise_chart(history: pd.DataFrame, ticker: str) -> go.Figure:
    fig = go.Figure()
    if history is None or history.empty or "Surprise %" not in history.columns:
        fig.add_annotation(
            text="No earnings surprise history",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
        )
    else:
        df = history.dropna(subset=["Surprise %"]).copy()
        if "Earnings Date" in df.columns:
            df = df.sort_values("Earnings Date")
            x = df["Earnings Date"].apply(
                lambda d: pd.Timestamp(d).strftime("%Y-%m-%d") if pd.notna(d) else "?"
            )
        else:
            x = list(range(len(df)))

        colors = [
            "#16a34a" if (isinstance(v, (int, float)) and v > 0) else "#dc2626"
            for v in df["Surprise %"]
        ]
        fig.add_trace(
            go.Bar(
                x=list(x),
                y=df["Surprise %"],
                marker_color=colors,
                name="Surprise %",
            )
        )
        fig.add_hline(y=0, line_color="#64748b", line_width=1)

    template = "plotly_dark" if st.get_option("theme.base") == "dark" else "plotly_white"
    fig.update_layout(
        title=f"{ticker} — Earnings surprise history",
        height=320,
        margin=dict(l=40, r=40, t=50, b=40),
        template=template,
        yaxis_title="Surprise %",
        showlegend=False,
    )
    return fig


# ─────────────────────────────────────────────────────────────
# Main tab
# ─────────────────────────────────────────────────────────────
def render_media_earnings_tab(
    tickers: list[str],
    api_key: str = "",
):
    """
    Informational Media & Earnings tab.

    Parameters
    ----------
    tickers : universe currently tracked by the app
    api_key : Alpha Vantage key (empty → placeholder media)
    """
    st.markdown(
        "<div class='section-header'>Media & Earnings — context only</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        "News sentiment and earnings calendar for research context. "
        "**Not** used in Z-score entries, stops, or BUY signals."
    )

    key = (api_key or "").strip()
    if not key:
        st.info(
            "Media feed is running on **placeholder** data. "
            "Set `ALPHA_VANTAGE_API_KEY` in the environment or paste a key in the sidebar "
            "to load live Alpha Vantage NEWS_SENTIMENT. Earnings still come from yfinance."
        )
    else:
        st.caption(
            "Live NEWS_SENTIMENT enabled. Free Alpha Vantage tiers are rate-limited "
            "(~5 calls/min) — first universe load can take 1–2 minutes, then caches ~15 min."
        )

    spinner_msg = (
        "Loading media & earnings (rate-limited live news)…"
        if key
        else "Loading media & earnings context…"
    )
    with st.spinner(spinner_msg):
        summary = _cached_summary(tuple(tickers), key)

    if summary is None or summary.empty:
        st.error("Could not build media/earnings summary.")
        return

    # ── Top KPIs ─────────────────────────────────────────────
    n = len(summary)
    good_7 = int((summary["Media Badge 7D"] == "Good").sum()) if "Media Badge 7D" in summary else 0
    bad_7 = int((summary["Media Badge 7D"] == "Bad").sum()) if "Media Badge 7D" in summary else 0
    beats = int((summary["Last Beat/Miss"] == "Beat").sum()) if "Last Beat/Miss" in summary else 0
    misses = int((summary["Last Beat/Miss"] == "Miss").sum()) if "Last Beat/Miss" in summary else 0
    # Upcoming within 14 days
    soon = 0
    if "Days to Earnings" in summary.columns:
        dte = pd.to_numeric(summary["Days to Earnings"], errors="coerce")
        soon = int(((dte >= 0) & (dte <= 14)).sum())

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Names covered", n)
    k2.metric("Media Good (7D)", good_7)
    k3.metric("Media Bad (7D)", bad_7)
    k4.metric("Last print Beat / Miss", f"{beats} / {misses}")
    k5.metric("Earnings ≤ 14d", soon)

    # ── Main flags table ─────────────────────────────────────
    st.markdown("#### Universe snapshot")
    show_cols = [
        c
        for c in [
            "Ticker",
            "Media 7D",
            "Media Badge 7D",
            "Media 30D",
            "Media Badge 30D",
            "Next Earnings",
            "Days to Earnings",
            "Last Beat/Miss",
            "Last Surprise %",
        ]
        if c in summary.columns
    ]
    st.dataframe(
        _style_summary(summary[show_cols]),
        use_container_width=True,
        hide_index=True,
        height=min(52 + 38 * len(summary), 480),
    )

    with st.expander("How scores work (for later notebook / backtest use)", expanded=False):
        st.markdown(
            """
- **Media score** averages article-level sentiment in \\([-1, +1]\\) over the lookback window.
- **Badges**: Good if score \\(> 0.15\\), Bad if \\(< -0.15\\), else Neutral.
- **Labels**: Bullish / Somewhat Bullish / Neutral / Somewhat Bearish / Bearish.
- **Live source**: Alpha Vantage `NEWS_SENTIMENT` (ticker-specific score when present).
- **Earnings**: yfinance dates + EPS estimate/actual/surprise; **Reaction 1D %** =
  next-session close vs earnings-session close.
- Import path for research:
  `from data.media_earnings import get_ticker_media_earnings, get_all_media_earnings_summary`
- **Not wired into** `get_levels` / BUY logic.
            """
        )

    st.divider()
    st.markdown("#### Stock detail")

    default_ix = 0
    # Prefer names with earnings soon, then Bad media, then first
    if "Days to Earnings" in summary.columns:
        dte = pd.to_numeric(summary["Days to Earnings"], errors="coerce")
        soon_mask = (dte >= 0) & (dte <= 21)
        if soon_mask.any():
            default_ix = int(soon_mask.to_numpy().nonzero()[0][0])
        elif "Media Badge 7D" in summary.columns and (summary["Media Badge 7D"] == "Bad").any():
            default_ix = int((summary["Media Badge 7D"] == "Bad").to_numpy().nonzero()[0][0])

    pick = st.selectbox(
        "Select ticker",
        list(summary["Ticker"]),
        index=min(default_ix, len(summary) - 1),
        key="media_earnings_pick",
    )

    with st.spinner(f"Loading detail for {pick}…"):
        detail = _cached_detail(pick, key)

    _render_detail(detail)


def _render_detail(detail: dict):
    ticker = detail.get("ticker", "?")

    # Header metrics
    c1, c2, c3, c4, c5 = st.columns(5)
    s7 = detail.get("media_score_7d")
    s30 = detail.get("media_score_30d")
    c1.metric("Media score 7D", _fmt_score(s7), delta=media_score_label(s7))
    c2.metric("Media score 30D", _fmt_score(s30), delta=media_score_label(s30))

    ne = detail.get("next_earnings")
    ne_str = pd.Timestamp(ne).strftime("%Y-%m-%d") if ne is not None else "—"
    dte = detail.get("days_to_earnings")
    dte_str = "—" if dte is None else f"{dte}d"
    c3.metric("Next earnings", ne_str)
    c4.metric("Days to earnings", dte_str)
    c5.metric(
        "Last beat/miss",
        str(detail.get("last_beat_miss") or "—"),
        delta=_fmt_surprise(detail.get("last_surprise_pct")),
    )

    src = detail.get("source", "")
    if detail.get("is_placeholder"):
        st.caption(f"Media source: {src}")
    else:
        st.caption(f"Media source: {src} · Earnings: {detail.get('earnings_source', 'yfinance')}")

    # Charts
    ch1, ch2 = st.columns(2)
    with ch1:
        st.plotly_chart(
            _sentiment_trend_chart(detail.get("sentiment_daily"), ticker),
            use_container_width=True,
            key=f"me_sent_{ticker}",
        )
    with ch2:
        st.plotly_chart(
            _earnings_surprise_chart(detail.get("earnings_history"), ticker),
            use_container_width=True,
            key=f"me_earn_{ticker}",
        )

    # Articles
    st.markdown("##### Recent headlines")
    articles = detail.get("articles") or []
    if not articles:
        st.write("No articles available.")
    else:
        # Show newest ~15
        for a in articles[:15]:
            label = a.get("sentiment_label") or score_to_sentiment_label(
                a.get("sentiment_score") or 0
            )
            pub = a.get("published_at")
            pub_s = (
                pub.strftime("%Y-%m-%d %H:%M UTC")
                if hasattr(pub, "strftime")
                else "—"
            )
            title = a.get("title") or "(no title)"
            url = a.get("url") or ""
            source = a.get("source") or "—"
            score = a.get("sentiment_score")
            score_s = _fmt_score(score)

            title_md = f"[{title}]({url})" if url else title
            st.markdown(
                f"{_sentiment_pill(label)}&nbsp;&nbsp;**{title_md}**  \n"
                f"<span class='subtle'>{source} · {pub_s} · score {score_s}</span>",
                unsafe_allow_html=True,
            )
            summary = a.get("summary") or ""
            if summary:
                with st.expander("Summary", expanded=False):
                    st.write(summary)

    # Earnings table
    st.markdown("##### Earnings history")
    hist = detail.get("earnings_history")
    note = detail.get("earnings_history_note") or ""
    if note:
        st.caption(note)
    if hist is None or (isinstance(hist, pd.DataFrame) and hist.empty):
        st.write("No earnings history returned from yfinance for this ticker.")
    else:
        st.dataframe(
            _style_earnings_history(hist),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "Beat/Miss from Surprise % (or Reported vs Estimate). "
            "Reaction 1D % = next trading day’s close vs earnings-day close "
            "(or quarter-end date when announcement dates are unavailable)."
        )
