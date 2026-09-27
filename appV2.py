"""
Deployment Desk — the interface for the strategy that survived the studies.
==========================================================================

Five tabs, in the order you'd use them:

  Today         what to do with new cash, your stocks that need a decision,
                the market backdrop, your portfolio
  Stocks        your watchlists / holdings / the whole screen with a plain-English
                status; open a stock for its chart, headlines and a Buy/Pass log
  Portfolio     ticker / shares / average price, value, gain, risk
  Track record  your calls, buy-zone signals and insider paper trades, scored
  Market        how many stocks are falling; sector leadership (information only)
  How it works  glossary, statuses, the evidence, and what failed

Statuses: 🟢 Buy zone (evidence-backed) · 🟠 Your call (your judgement, logged
and scored) · 👀 Close to a dip. The app never tells you to sell -- no exit rule
survived testing (docs/03_OPTIMISATION_STUDY.md §4).

    streamlit run appV2.py
"""

from __future__ import annotations

import os
import warnings
from datetime import datetime

import pandas as pd
import streamlit as st

from data.holdings import load_holdings
from data.market import get_data_batch, get_earnings_batch
from data.market_pulse import pulse_tickers, relative_strength_table
from data.scoreboard import log_buy_zone
from data.screen import EVIDENCE, SCREENS, UNIVERSE_V2, run_screen
from data.watchlists import all_watchlist_tickers, load_watchlists
from ui.desk_howto import render_howto
from ui.desk_market import render_market
from ui.desk_portfolio import render_concentration, render_portfolio
from ui.desk_stocks import render_stocks
from ui.desk_today import render_today
from ui.desk_track import render_track

warnings.filterwarnings("ignore")

BENCHMARK = "SPY"
DATA_TTL = 300
HISTORY_DAYS = 420  # 12-month market pulse + 120d beta window + 20d dip score + slack
SPEC = SCREENS[EVIDENCE]  # one screen; the others are reference only (How it works tab)

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


@st.cache_data(ttl=DATA_TTL, show_spinner=False)
def cached_frames(tickers: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    return get_data_batch(list(tickers), days=HISTORY_DAYS)


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_earnings(tickers: tuple[str, ...]) -> dict[str, list]:
    return get_earnings_batch(list(tickers))


def alpha_vantage_key() -> str:
    """News-sentiment key from .streamlit/secrets.toml, then the environment."""
    try:
        key = str(st.secrets.get("ALPHA_VANTAGE_API_KEY", "") or "").strip()
    except Exception:  # noqa: BLE001 -- no secrets file
        key = ""
    return key or (os.environ.get("ALPHA_VANTAGE_API_KEY") or "").strip()


def main() -> None:
    with st.sidebar:
        st.title("🎯 Deployment Desk")
        st.caption("Where new money goes. Never tells you to sell — no exit rule survived testing.")
        st.divider()
        cash = st.number_input("Cash to invest ($)", min_value=0.0, max_value=10_000_000.0,
                               value=1_000.0, step=250.0, format="%.0f")
        max_names = st.slider("Split across at most", 1, 10, 4,
                              help="Cash is split equally across the top buy-zone stocks.")
        drawdown_limit = st.number_input(
            "Drop you can sit through without selling (%)", min_value=5.0, max_value=90.0,
            value=35.0, step=5.0, format="%.0f",
            help="Used by the Portfolio risk panel. Tech-only fell 51% in testing; a mixed basket 30%.")
        st.divider()
        if st.button("↻ Refresh market data", width="stretch"):
            cached_frames.clear()
            st.rerun()
        st.markdown(f"<div class='stamp'>{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>",
                    unsafe_allow_html=True)

    groups = load_watchlists()
    holdings = load_holdings()
    # Screened: the calibrated 124 + your watchlists + your holdings. Breadth stays on the 124.
    screened = list(dict.fromkeys(UNIVERSE_V2 + all_watchlist_tickers(groups) + [h.ticker for h in holdings]))
    tickers = tuple(dict.fromkeys(screened + pulse_tickers() + [BENCHMARK]))
    with st.spinner(f"Loading {len(tickers)} stocks and funds…"):
        frames = cached_frames(tickers)
        earnings = cached_earnings(tuple(screened))
    if not frames or BENCHMARK not in frames:
        st.error("No market data returned. Yahoo throttles heavily — wait a minute and hit Refresh.")
        st.stop()

    screen_frames = {t: frames[t] for t in screened + [BENCHMARK] if t in frames}
    result = run_screen(screen_frames, earnings, SPEC, breadth_universe=UNIVERSE_V2)
    if not result.rows:
        st.error("Not enough history to run the screen.")
        st.stop()
    qualifying = [r for r in result.rows if r["qualifies"]]
    log_buy_zone(qualifying)  # every buy-zone signal is scored later on the Track record tab
    pulse_table = relative_strength_table(frames, benchmark=BENCHMARK)

    tabs = st.tabs(["🏠 Today", "📋 Stocks", "📁 Portfolio", "📊 Track record", "🧭 Market",
                    "📐 How it works"])
    with tabs[0]:
        render_today(result, SPEC, qualifying, cash, max_names, groups, holdings, frames, pulse_table)
    with tabs[1]:
        render_stocks(result, SPEC, groups, holdings, frames, BENCHMARK, alpha_vantage_key())
    with tabs[2]:
        render_portfolio(holdings, frames, drawdown_limit)
        render_concentration(frames, [h.ticker for h in holdings])
    with tabs[3]:
        render_track(frames)
    with tabs[4]:
        render_market(result, SPEC, pulse_table)
    with tabs[5]:
        render_howto()


if __name__ == "__main__":
    main()
