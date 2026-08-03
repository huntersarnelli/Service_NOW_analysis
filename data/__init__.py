"""
Data layer for the Dual-Mode Tactical Trading System.

Modules:
  market          — OHLCV download, indicators, live levels / signals
  media_earnings  — informational media sentiment + earnings context

These modules are intentionally free of Streamlit UI so you can import them
into a Jupyter notebook for research / backtesting later, e.g.:

    from data.media_earnings import get_ticker_media_earnings, media_score_label
    from data.market import get_data, compute_indicators

Trading signals live only in market.get_levels / scan_bucket.
Media & earnings are context-only and are NOT wired into entry/exit logic.
"""

from data.market import (
    ALL_TICKERS,
    HISTORY_DAYS,
    MOMENTUM_BUCKET,
    QUALITY_BUCKET,
    compute_indicators,
    get_data,
    get_levels,
    scan_bucket,
)
from data.media_earnings import (
    get_all_media_earnings_summary,
    get_ticker_media_earnings,
    media_score_label,
)

__all__ = [
    "ALL_TICKERS",
    "HISTORY_DAYS",
    "MOMENTUM_BUCKET",
    "QUALITY_BUCKET",
    "compute_indicators",
    "get_data",
    "get_levels",
    "scan_bucket",
    "get_all_media_earnings_summary",
    "get_ticker_media_earnings",
    "media_score_label",
]
