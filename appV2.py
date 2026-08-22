"""
Deployment Desk — the interface for the strategy that survived the studies.
==========================================================================

app.py runs Method A and Method B: two dip strategies built around EXIT rules.
Three studies later, neither exit rule has any evidence behind it, and the
things that do have evidence are all about ENTRY. This app implements those and
nothing else.

What it does
------------
Answers one question: **you have cash to deploy — deploy it today, or wait?**

  Overview     the deploy/wait call, market breadth, and today's candidates
  Candidates   every name in the 124-name universe with each screen gate shown
               separately, so you can see WHY something did or did not qualify
  Advisor      optional LLM read on a candidate -- advisory only, never a gate
  Portfolio    what you hold, and how many INDEPENDENT bets that really is
  Evidence     every rule with the number behind it, and the graveyard of what
               was tested and failed

What it deliberately does NOT do
--------------------------------
No sell signals. No trailing stops. No position-size model. Those were all
tested and all failed -- see the Evidence tab, or docs/03_OPTIMISATION_STUDY.md §4.

    streamlit run appV2.py
"""

from __future__ import annotations

import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.advisor import (
    CLASSIFICATION_LABEL,
    DRIFT_COLOR,
    available as advisor_available,
    get_advice,
)
from data.market import get_data_batch, get_earnings_batch
from data.portfolio import get_store
from data.screen import (
    EVIDENCE,
    SCREENS,
    UNIVERSE_V2,
    add_screen_indicators,
    effective_bets,
    failed_gates,
    run_screen,
)

warnings.filterwarnings("ignore")

BENCHMARK = "SPY"
DATA_TTL = 300
HISTORY_DAYS = 420  # 120d beta window + 20d Z + slack

st.set_page_config(
    page_title="Deployment Desk",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 2.4rem; max-width: 1400px; }
      .verdict-card {
          border-radius: 4px; padding: 1.4rem 1.6rem; margin: 0.4rem 0 1.2rem;
          border-left: 4px solid var(--vc); background: rgba(128,128,128,0.06);
      }
      .verdict-head {
          font-size: 1.55rem; font-weight: 650; line-height: 1.2;
          color: var(--vc); margin-bottom: 0.35rem;
      }
      .verdict-sub { font-size: 0.95rem; opacity: 0.82; line-height: 1.5; }
      .section-header {
          font-size: 1.05rem; font-weight: 650; letter-spacing: 0.01em;
          margin: 1.6rem 0 0.6rem; padding-bottom: 0.35rem;
          border-bottom: 1px solid rgba(128,128,128,0.25);
      }
      .gate { display: inline-block; padding: 2px 9px; border-radius: 3px;
              font-size: 0.72rem; font-weight: 600; margin-right: 5px;
              letter-spacing: 0.03em; }
      .gate-pass { background: rgba(31,111,84,0.16); color: #1F6F54; }
      .gate-fail { background: rgba(140,47,57,0.14); color: #8C2F39; }
      .evidence-note {
          font-size: 0.83rem; opacity: 0.72; font-style: italic;
          margin-top: 0.3rem; line-height: 1.45;
      }
      .stamp { font-size: 0.78rem; opacity: 0.6; font-family: monospace; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=DATA_TTL, show_spinner=False)
def cached_frames(tickers: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    return get_data_batch(list(tickers), days=HISTORY_DAYS)


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_earnings(tickers: tuple[str, ...]) -> dict[str, list]:
    return get_earnings_batch(list(tickers))


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def cached_advice(ticker: str, bar: str, breadth: float, spec_name: str,
                  _row: dict) -> dict:
    """Cached per (ticker, bar, screen) so re-running on the same bar is free."""
    return get_advice(_row, breadth, spec_name).to_dict()


def fmt_money(x: float) -> str:
    return "—" if pd.isna(x) else f"${x:,.2f}"


def fmt_pct(x: float) -> str:
    return "—" if pd.isna(x) else f"{x:+.1f}%"


def fmt_z(x: float) -> str:
    return "—" if pd.isna(x) else f"{x:+.2f}"


def gate_chip(label: str, passed: bool) -> str:
    cls = "gate-pass" if passed else "gate-fail"
    mark = "✓" if passed else "✗"
    return f"<span class='gate {cls}'>{mark} {label}</span>"


# ─────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────
def main() -> None:
    with st.sidebar:
        st.title("🎯 Deployment Desk")
        st.caption(
            "Where new money goes. This app never tells you to sell — "
            "no exit rule ever survived testing."
        )

        st.divider()
        spec_key = st.radio(
            "Screen",
            options=list(SCREENS.keys()),
            index=list(SCREENS.keys()).index(EVIDENCE),
            format_func=lambda k: SCREENS[k].name,
        )
        spec = SCREENS[spec_key]
        st.caption(spec.tagline)
        st.markdown(f"<div class='evidence-note'>{spec.evidence}</div>",
                    unsafe_allow_html=True)

        st.divider()
        cash = st.number_input(
            "Cash to deploy ($)", min_value=0.0, max_value=10_000_000.0,
            value=1_000.0, step=250.0, format="%.0f",
            help="The contribution you are deciding what to do with today.",
        )
        max_names = st.slider(
            "Max names to split across", 1, 10, 4,
            help="Cash is split equally across the top-ranked qualifying names.",
        )

        st.divider()
        with st.expander("Thresholds", expanded=False):
            st.caption(
                "Fitted on the 17,235-event panel, 2015–2026. "
                "Depth beyond −1.2 is irrelevant (§5.4), so widening the Z "
                "threshold changes how often you trade, not how well."
            )
            st.write(f"**Z entry** {spec.z_entry}")
            st.write(f"**Earnings window** {spec.earnings_window} bars")
            st.write(f"**Market-wide** idio-Z > {spec.idio_hi}")
            st.write(f"**Not lonely** breadth > {spec.breadth_lo:.0%}")

        st.divider()
        if st.button("↻ Refresh market data", width="stretch"):
            cached_frames.clear()
            st.rerun()
        st.markdown(
            f"<div class='stamp'>{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>",
            unsafe_allow_html=True,
        )

    tickers = tuple(UNIVERSE_V2 + [BENCHMARK])
    with st.spinner(f"Loading {len(tickers)} names…"):
        frames = cached_frames(tickers)
        earnings = cached_earnings(tuple(UNIVERSE_V2))

    if not frames or BENCHMARK not in frames:
        st.error(
            "No market data returned. Yahoo throttles heavily — wait a minute "
            "and hit Refresh."
        )
        st.stop()

    result = run_screen(frames, earnings, spec)
    if not result.rows:
        st.error("Not enough history to run the screen.")
        st.stop()

    qualifying = [r for r in result.rows if r["qualifies"]]
    dipping = [r for r in result.rows if r["gate_dip"]]

    tabs = st.tabs([
        "🎯 Deploy", "🔬 Candidates", "🤖 Advisor", "📁 Portfolio", "📐 Evidence",
    ])

    # ── Deploy ────────────────────────────────────────────────
    with tabs[0]:
        render_deploy(result, spec, qualifying, dipping, cash, max_names)

    # ── Candidates ────────────────────────────────────────────
    with tabs[1]:
        render_candidates(result, spec, frames)

    # ── Advisor ───────────────────────────────────────────────
    with tabs[2]:
        render_advisor(result, spec, qualifying, dipping)

    # ── Portfolio ─────────────────────────────────────────────
    with tabs[3]:
        render_portfolio(frames)

    # ── Evidence ──────────────────────────────────────────────
    with tabs[4]:
        render_evidence()


def render_deploy(result, spec, qualifying, dipping, cash, max_names) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Universe", result.n_scanned)
    c2.metric("Dipping (Z < −1.2)", result.n_dipping)
    c3.metric("Breadth", f"{result.breadth:.0%}",
              help="Share of the universe below the dip threshold. Low breadth "
                   "means any faller is falling alone — the worst cohort measured.")
    c4.metric("Qualifying", len(qualifying))

    if qualifying:
        picks = qualifying[:max_names]
        per = cash / len(picks) if picks else 0.0
        names = ", ".join(p["ticker"] for p in picks)
        st.markdown(
            f"<div class='verdict-card' style='--vc:#1F6F54'>"
            f"<div class='verdict-head'>Deploy — {len(picks)} name"
            f"{'s' if len(picks) != 1 else ''}</div>"
            f"<div class='verdict-sub'><b>{names}</b> · "
            f"{fmt_money(per)} each, {fmt_money(cash)} total</div></div>",
            unsafe_allow_html=True,
        )
        rows = []
        for p in picks:
            rows.append({
                "Ticker": p["ticker"],
                "Sector": p["sector"],
                "Price": p["close"],
                "Z": p["z"],
                "Market-neutral Z": p["idio_z"],
                "Bars since earnings": p["days_since_earnings"],
                "Allocate": per,
                "Shares (approx)": per / p["close"] if p["close"] else np.nan,
            })
        st.dataframe(
            pd.DataFrame(rows).style.format({
                "Price": "${:,.2f}", "Z": "{:+.2f}", "Market-neutral Z": "{:+.2f}",
                "Bars since earnings": "{:,.0f}", "Allocate": "${:,.2f}",
                "Shares (approx)": "{:,.3f}",
            }),
            width="stretch", hide_index=True,
        )
    else:
        why = ""
        if dipping:
            blocked = {}
            for r in dipping:
                for g in failed_gates(r, spec):
                    blocked[g] = blocked.get(g, 0) + 1
            if blocked:
                why = " · ".join(f"{v} blocked by: {k}" for k, v in
                                 sorted(blocked.items(), key=lambda kv: -kv[1])[:3])
        st.markdown(
            f"<div class='verdict-card' style='--vc:#64757B'>"
            f"<div class='verdict-head'>Hold the cash</div>"
            f"<div class='verdict-sub'>{result.n_dipping} name"
            f"{'s are' if result.n_dipping != 1 else ' is'} dipping but none "
            f"passes the screen.<br>{why}</div></div>",
            unsafe_allow_html=True,
        )
        st.info(
            "**Do not hold cash indefinitely.** The study forced deployment "
            "after 12 months so a screen could not win by sitting out of a "
            "rising market — that constraint is what makes the +8.0% result "
            "honest. If nothing has qualified in months, deploy equal-weight."
        )

    st.markdown("<div class='section-header'>Market breadth</div>",
                unsafe_allow_html=True)
    st.caption(
        "The single most useful number on this page. A dip while **many** names "
        "are falling is the market dragging a good company down — that reverses. "
        "A dip while almost nothing else is falling is company-specific — that drifts."
    )
    b = result.breadth
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=b * 100,
        number={"suffix": "%", "font": {"size": 34}},
        gauge={
            "axis": {"range": [0, 60]},
            "bar": {"color": "#8C2F39", "thickness": 0.7},
            "steps": [
                {"range": [0, spec.breadth_lo * 100], "color": "rgba(100,117,123,0.28)"},
                {"range": [spec.breadth_lo * 100, 39], "color": "rgba(31,111,84,0.28)"},
                {"range": [39, 60], "color": "rgba(138,96,20,0.28)"},
            ],
            "threshold": {"line": {"color": "#8C2F39", "width": 3},
                          "value": spec.breadth_lo * 100},
        },
    ))
    fig.update_layout(height=230, margin=dict(l=20, r=20, t=10, b=10))
    st.plotly_chart(fig, width="stretch")
    st.caption(
        f"Grey below {spec.breadth_lo:.0%} = lonely-faller territory, the worst "
        "cohort measured (+1.04pp at 60d vs +2.60pp for mid-breadth). "
        "Green = the sweet spot. Amber above 39% = broad selloff, still good "
        "but no better than mid."
    )


def render_candidates(result, spec, frames) -> None:
    st.markdown("<div class='section-header'>Every name, every gate</div>",
                unsafe_allow_html=True)
    st.caption(
        "Gates are shown separately so a near-miss is visible. A name failing "
        "only the earnings gate becomes a candidate ~20 bars after it reported."
    )

    show_all = st.toggle("Show the whole universe", value=False)
    rows = result.rows if show_all else [r for r in result.rows if r["gate_dip"]]
    if not rows:
        st.info("Nothing is currently below the dip threshold.")
        return

    df = pd.DataFrame([{
        "Ticker": r["ticker"], "Sector": r["sector"], "Price": r["close"],
        "Z": r["z"], "Market-neutral Z": r["idio_z"],
        "Trigger": r["trigger"], "Dist %": r["dist_pct"],
        "Bars since earn": r["days_since_earnings"],
        "Vol %": r["rvol20"], "Beta": r["beta"],
        "Dip": r["gate_dip"], "No earnings": r["gate_no_earnings"],
        "Market-wide": r["gate_market_wide"], "Not lonely": r["gate_not_lonely"],
        "Qualifies": r["qualifies"],
    } for r in rows])

    st.dataframe(
        df.style.format({
            "Price": "${:,.2f}", "Z": "{:+.2f}", "Market-neutral Z": "{:+.2f}",
            "Trigger": "${:,.2f}", "Dist %": "{:+.1f}%",
            "Bars since earn": "{:,.0f}", "Vol %": "{:,.0f}%", "Beta": "{:.2f}",
        }).map(
            lambda v: "color:#1F6F54;font-weight:600" if v is True
            else ("color:#8C2F39" if v is False else ""),
            subset=["Dip", "No earnings", "Market-wide", "Not lonely", "Qualifies"],
        ),
        width="stretch", hide_index=True, height=460,
    )

    st.markdown("<div class='section-header'>Deep dive</div>", unsafe_allow_html=True)
    pick = st.selectbox("Ticker", [r["ticker"] for r in rows])
    row = next(r for r in rows if r["ticker"] == pick)

    chips = "".join([
        gate_chip("Dip", row["gate_dip"]),
        gate_chip("No earnings", row["gate_no_earnings"]),
        gate_chip("Market-wide", row["gate_market_wide"]),
        gate_chip("Not lonely", row["gate_not_lonely"]),
    ])
    st.markdown(chips, unsafe_allow_html=True)

    if not row["qualifies"]:
        reasons = failed_gates(row, spec)
        if reasons:
            st.warning("Blocked by: " + "; ".join(reasons))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Close", fmt_money(row["close"]))
    m2.metric("Z (20d)", fmt_z(row["z"]))
    m3.metric("Market-neutral Z", fmt_z(row["idio_z"]),
              help="Higher = more of the decline is the market, not the company. "
                   "Market-driven declines reverse; company-specific ones drift.")
    m4.metric("Bars since earnings", f"{row['days_since_earnings']:,.0f}")

    df_px = frames.get(pick)
    if df_px is not None and not df_px.empty:
        d = add_screen_indicators(df_px, frames[BENCHMARK]).tail(180)
        band_hi = d["sma"] + spec.z_entry * d["sd"] * -1
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=d.index, y=d["sma"], name="20-SMA",
                                 line=dict(width=1.2, dash="dot", color="#8B999D")))
        fig.add_trace(go.Scatter(
            x=d.index, y=d["sma"] + spec.z_entry * d["sd"],
            name=f"Trigger (Z={spec.z_entry})",
            line=dict(width=1.4, color="#8C2F39")))
        fig.add_trace(go.Scatter(x=d.index, y=band_hi, name="+1.2σ",
                                 line=dict(width=0.8, color="rgba(100,117,123,0.5)")))
        fig.add_trace(go.Scatter(x=d.index, y=d["Close"], name=pick,
                                 line=dict(width=2.1, color="#1F6F54")))
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=28, b=10),
                          hovermode="x unified", title=f"{pick} — price vs trigger",
                          legend=dict(orientation="h", y=1.12))
        st.plotly_chart(fig, width="stretch")


def render_advisor(result, spec, qualifying, dipping) -> None:
    st.markdown("<div class='section-header'>LLM advisory — never a gate</div>",
                unsafe_allow_html=True)

    st.warning(
        "**This does not decide anything.** The screen already picked the "
        "candidates; the model only characterises *why* a name fell, so you are "
        "not blindsided by something you did not know.\n\n"
        "Two reasons it stays advisory. The ceiling is small — the entire "
        "news-vs-no-news effect is **+0.80pp per trade at 20 days**, and you "
        "already capture it for free with the earnings calendar. And the one "
        "other crude proxy that should have worked (volume) found nothing and "
        "flipped sign across sample halves.\n\n"
        "**The trap:** a model asked *\"is there risk here?\"* says yes 100% of "
        "the time. Every name at Z < −1.2 has a scary story attached — that is "
        "why it fell. Filtering on scary stories mostly filters out returns."
    )

    ok, reason = advisor_available()
    if not ok:
        st.info(f"Advisor unavailable — {reason}")
        return

    pool = qualifying or dipping
    if not pool:
        st.info("No candidates to analyse right now.")
        return

    pick = st.selectbox("Candidate", [r["ticker"] for r in pool],
                        key="advisor_pick")
    row = next(r for r in pool if r["ticker"] == pick)

    st.caption(
        "One call per name per bar, then cached. Only the name you pick is sent."
    )
    if st.button(f"Analyse {pick}", type="primary"):
        with st.spinner("Asking Claude…"):
            bar = str(row["last_bar"].date() if hasattr(row["last_bar"], "date")
                      else row["last_bar"])
            adv = cached_advice(pick, bar, float(result.breadth), spec.name, row)

        if adv.get("error"):
            st.error(adv["error"])
            return

        colour = DRIFT_COLOR.get(adv["drift_risk"], "#64757B")
        st.markdown(
            f"<div class='verdict-card' style='--vc:{colour}'>"
            f"<div class='verdict-head'>"
            f"{CLASSIFICATION_LABEL.get(adv['classification'], adv['classification'])}"
            f"</div><div class='verdict-sub'>Drift risk: "
            f"<b>{adv['drift_risk'].upper()}</b></div></div>",
            unsafe_allow_html=True,
        )
        st.write(adv["summary"])

        if adv["known_issues"]:
            st.markdown("**Known overhangs**")
            for issue in adv["known_issues"]:
                st.markdown(f"- {issue}")
        else:
            st.caption("No specific company overhangs known to the model.")

        if adv["what_would_change_it"]:
            st.markdown(f"**What would change this:** {adv['what_would_change_it']}")
        if adv["knowledge_caveat"]:
            st.info(adv["knowledge_caveat"])

        st.caption(
            "Advisory only. This output has never been backtested — and it "
            "cannot be, from this repository. A model scoring old news knows "
            "what happened next, so any backtest without point-in-time data "
            "would look brilliant and be worthless."
        )


def render_portfolio(frames) -> None:
    st.markdown("<div class='section-header'>What you hold</div>",
                unsafe_allow_html=True)
    try:
        lots = get_store().load()
    except Exception as e:  # noqa: BLE001
        st.error(f"Could not load positions: {e}")
        return

    if not lots:
        st.info(
            "No positions recorded. Add them in the original `app.py` Portfolio "
            "tab — this app reads the same store."
        )
        held = []
    else:
        rows = []
        for lot in lots:
            t = getattr(lot, "ticker", None) or lot.get("ticker")
            sh = getattr(lot, "shares", None) or lot.get("shares", 0)
            ep = getattr(lot, "entry_price", None) or lot.get("entry_price", 0)
            df = frames.get(t)
            px = float(df["Close"].iloc[-1]) if df is not None and not df.empty else np.nan
            rows.append({
                "Ticker": t, "Shares": sh, "Entry": ep, "Price": px,
                "Value": sh * px if pd.notna(px) else np.nan,
                "P&L %": (px / ep - 1) * 100 if ep and pd.notna(px) else np.nan,
            })
        pf = pd.DataFrame(rows)
        total = pf["Value"].sum()
        pf["Weight %"] = pf["Value"] / total * 100 if total else np.nan
        st.dataframe(
            pf.style.format({
                "Shares": "{:,.3f}", "Entry": "${:,.2f}", "Price": "${:,.2f}",
                "Value": "${:,.2f}", "P&L %": "{:+.1f}%", "Weight %": "{:.1f}%",
            }),
            width="stretch", hide_index=True,
        )
        held = sorted(set(pf["Ticker"].dropna().tolist()))

    st.markdown("<div class='section-header'>How many bets is that really?</div>",
                unsafe_allow_html=True)
    st.caption(
        "The measurement that explains every negative result in this project. "
        "Thirty tech names are only **4.6 independent bets**; the original "
        "META/NVDA/NET trio is **2.1**, with one factor driving 64% of all "
        "variance. Spreading capital across tickers that are the same bet does "
        "not diversify anything — which is why every position-sizing rule "
        "tested moved nothing."
    )

    choice = st.radio(
        "Measure", ["My holdings", "Full 124-name universe", "META / NVDA / NET"],
        horizontal=True,
    )
    if choice == "My holdings":
        names = held
    elif choice == "META / NVDA / NET":
        names = ["META", "NVDA", "NET"]
    else:
        names = UNIVERSE_V2

    if len(names) < 2:
        st.info("Need at least two names to measure concentration.")
        return

    eb = effective_bets(frames, names)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Names", eb["n_names"])
    c2.metric("Effective bets", f"{eb['effective_bets']:.1f}" if
              pd.notna(eb["effective_bets"]) else "—")
    c3.metric("Avg correlation", f"{eb['avg_corr']:.2f}" if
              pd.notna(eb["avg_corr"]) else "—")
    c4.metric("Largest factor", f"{eb['pc1_pct']:.0f}%" if
              pd.notna(eb["pc1_pct"]) else "—",
              help="Share of total variance explained by the single biggest "
                   "common factor. Above ~45% you own one bet wearing many tickers.")

    if pd.notna(eb["effective_bets"]) and eb["n_names"]:
        ratio = eb["effective_bets"] / eb["n_names"]
        if ratio < 0.2:
            st.error(
                f"**{eb['n_names']} tickers, {eb['effective_bets']:.1f} bets.** "
                "This is a concentrated single-factor position. Widening past "
                "one sector was worth 21 points of drawdown in testing — more "
                "than every sizing rule combined."
            )
        elif ratio < 0.35:
            st.warning(
                f"{eb['n_names']} tickers behaving like {eb['effective_bets']:.1f} "
                "bets. Adding names outside the dominant sector buys more than "
                "resizing the ones you have."
            )
        else:
            st.success(
                f"{eb['n_names']} tickers, {eb['effective_bets']:.1f} effective "
                "bets — reasonably diversified for a concentrated book."
            )


def render_evidence() -> None:
    st.markdown("<div class='section-header'>Why each rule is here</div>",
                unsafe_allow_html=True)
    st.dataframe(
        pd.DataFrame([
            {"Rule": "Z(20) < −1.2 crossing",
             "Evidence": "Beats 200/200 random draws at 5/20/60 bars; worth +0.3–0.4pp per trade",
             "Source": "OVERREACTION_STUDY §2"},
            {"Rule": "Depth beyond −1.2 ignored",
             "Evidence": "−1.2 ≈ −0.8 ≈ −0.5. A deeper dip is not a better dip",
             "Source": "STRATEGY_REVIEW §5.4"},
            {"Rule": "No earnings within 20 bars",
             "Evidence": "+0.80pp at 20d, t = 2.35, stable in both sample halves",
             "Source": "OVERREACTION_STUDY §4"},
            {"Rule": "Market-wide, not company-specific",
             "Evidence": "Market-driven dips beat name-specific dips at every horizon",
             "Source": "OVERREACTION_STUDY §5"},
            {"Rule": "Not a lonely faller",
             "Evidence": "Lonely fallers were the worst cohort: +1.04pp vs +2.60pp at 60d",
             "Source": "OVERREACTION_STUDY §5"},
            {"Rule": "Never sell",
             "Evidence": "Return rises monotonically as you dilute toward buy-and-hold",
             "Source": "STRATEGY_REVIEW §5.19"},
            {"Rule": "Wide universe, many sectors",
             "Evidence": "−30% drawdown vs −51% for the same rules on tech only",
             "Source": "PORTFOLIO_STUDY §1"},
        ]),
        width="stretch", hide_index=True,
    )

    st.markdown("<div class='section-header'>The graveyard</div>",
                unsafe_allow_html=True)
    st.caption(
        "Eleven interventions tested with out-of-sample or null controls. "
        "All failed. Read this before proposing an improvement."
    )
    st.dataframe(
        pd.DataFrame([
            {"Intervention": "Re-optimise entry / trail parameters",
             "Result": "−11.8pp vs freezing them", "Source": "§5.17"},
            {"Intervention": "Tighten the trailing stop",
             "Result": "Worse at every setting", "Source": "§5.13a"},
            {"Intervention": "Momentum-gate the universe",
             "Result": "Much worse in-sample", "Source": "§5.13c"},
            {"Intervention": "200-SMA regime filter",
             "Result": "CAGR cut by two thirds", "Source": "§5.9"},
            {"Intervention": "Permanent core + dip lots",
             "Result": "Monotonically worse", "Source": "§5.19"},
            {"Intervention": "Partial scale-outs / min-gain filters",
             "Result": "Worse at every setting", "Source": "§5.28"},
            {"Intervention": "Volume as a news proxy",
             "Result": "t < 1; sign flips across halves", "Source": "OVERREACTION §3"},
            {"Intervention": "Stack every event-tag filter",
             "Result": "Loses significance entirely", "Source": "OVERREACTION §7"},
            {"Intervention": "Fixed-bar time exit",
             "Result": "Worse than the trail at every setting", "Source": "OPTIMISATION §2"},
            {"Intervention": "Model-predicted position sizing",
             "Result": "Collapses into a volatility tilt", "Source": "OPTIMISATION §3"},
            {"Intervention": "Per-name exposure cap",
             "Result": "Sharpe flat; only costs return", "Source": "PORTFOLIO §3"},
        ]),
        width="stretch", hide_index=True,
    )

    st.markdown("<div class='section-header'>What this is worth</div>",
                unsafe_allow_html=True)
    st.info(
        "**Be clear-eyed about size.** The entry edge is roughly **+0.3–0.4pp "
        "per trade** and it is **gone by 120 bars** — after that you are "
        "holding beta. On $10,000 the timing edge is worth a few hundred "
        "dollars a year, while the stocks themselves swing thousands.\n\n"
        "This makes a concentrated equity bet slightly more efficient. It does "
        "not make it safe, and it is not a return engine. Your contribution "
        "rate dominates everything on this page."
    )
    st.caption(
        "Research and educational use only. Not investment advice. "
        "This app never places an order."
    )


if __name__ == "__main__":
    main()
