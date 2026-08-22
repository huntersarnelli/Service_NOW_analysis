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
    DIP_BUCKET,
    HISTORY_DAYS,
    MOMENTUM_BUCKET,
    QUALITY_BUCKET,
    UNIVERSE,
    compute_indicators,
    get_data,
    get_data_batch,
    get_levels,
    levels_from_frame,
    required_history_days,
    scan_bucket,
)
from data.portfolio import Lot, get_store
from data.strategies import DIP_SPEC, TACTICAL_SPEC, evaluate_lot, get_spec
from data.media_earnings import (
    get_all_media_earnings_summary,
    get_ticker_media_earnings,
    media_score_label,
)

__all__ = [
    "ALL_TICKERS",
    "DIP_BUCKET",
    "HISTORY_DAYS",
    "MOMENTUM_BUCKET",
    "QUALITY_BUCKET",
    "UNIVERSE",
    "compute_indicators",
    "get_data",
    "get_data_batch",
    "get_levels",
    "levels_from_frame",
    "required_history_days",
    "scan_bucket",
    "DIP_SPEC",
    "TACTICAL_SPEC",
    "Lot",
    "evaluate_lot",
    "get_spec",
    "get_store",
    "get_all_media_earnings_summary",
    "get_ticker_media_earnings",
    "media_score_label",
]
