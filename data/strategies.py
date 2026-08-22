"""
Strategy definitions and open-lot evaluation.

Two rule sets share one engine:

  tactical  — Dual-Mode Tactical      Z < -1.5, trail = Close - 2*ATR (raise
              only, ATR re-read daily), exit on trail hit OR Z > 0.

  dip       — Aggressive Dip Accum.   Z < -1.2, trail = highest close since
              entry - 4*ATR_at_entry (ATR frozen), NO mean-reversion exit.

Why this module exists
----------------------
`aggressive_dip_dashboard.find_assumed_entry` *inferred* your open position by
scanning back to the most recent signal cluster and then compared only TODAY's
close to the trail. It never checked whether the stop was breached on an
intermediate bar, so a position that should have been closed months ago still
displayed as HOLD, and a stale SELL banner could persist indefinitely.

`evaluate_lot` takes a real entry date and price and walks the bars forward, so
the exit it reports is the exit the rules actually produce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from data.market import DIP_BUCKET, MOMENTUM_BUCKET, QUALITY_BUCKET

TACTICAL = "tactical"
DIP = "dip"


@dataclass(frozen=True)
class StrategySpec:
    """Everything that distinguishes one rule set from the other."""

    key: str
    name: str
    tagline: str
    tickers: list[str]
    z_entry: float
    atr_mult: float
    sma_window: int = 20
    atr_window: int = 14
    trend_sma: int = 50
    use_trend_filter: bool = False
    # Exit engine
    mean_reversion_exit: bool = True   # tactical exits at Z > z_exit
    z_exit: float = 0.0
    freeze_atr_at_entry: bool = False  # dip freezes ATR at the entry bar
    trail_from_highest_close: bool = False  # dip trails the running high
    # Sizing
    sizing_mode: str = "risk"          # "risk" (1% of capital) or "equity"
    normal_alloc: float = 0.25
    post_earnings_alloc: float = 0.35
    post_earnings_window: int = 10
    buckets: dict[str, list[str]] = field(default_factory=dict)

    @property
    def uses_buckets(self) -> bool:
        return len(self.buckets) > 1

    def trail_label(self) -> str:
        if self.trail_from_highest_close:
            return f"Highest close since entry − {self.atr_mult}×ATR (frozen at entry)"
        return f"Close − {self.atr_mult}×ATR, raise-only"

    def exit_label(self) -> str:
        if self.mean_reversion_exit:
            return f"Trail hit **or** Z > {self.z_exit}"
        return "Trail hit only (no mean-reversion exit)"


TACTICAL_SPEC = StrategySpec(
    key=TACTICAL,
    name="Dual-Mode Tactical",
    tagline="Mean-reversion entry, mean-reversion exit. Two buckets.",
    tickers=MOMENTUM_BUCKET + QUALITY_BUCKET,
    z_entry=-1.5,
    atr_mult=2.0,
    mean_reversion_exit=True,
    z_exit=0.0,
    freeze_atr_at_entry=False,
    trail_from_highest_close=False,
    sizing_mode="risk",
    buckets={"Momentum": MOMENTUM_BUCKET, "Quality": QUALITY_BUCKET},
)

DIP_SPEC = StrategySpec(
    key=DIP,
    name="Aggressive Dip Accumulation",
    tagline="Mean-reversion entry, trend-following exit. Wide trail, big size.",
    tickers=DIP_BUCKET,
    z_entry=-1.2,
    atr_mult=4.0,
    mean_reversion_exit=False,
    freeze_atr_at_entry=True,
    trail_from_highest_close=True,
    sizing_mode="equity",
    normal_alloc=0.25,
    post_earnings_alloc=0.35,
    post_earnings_window=10,
    buckets={"Dip": DIP_BUCKET},
)

SPECS: dict[str, StrategySpec] = {TACTICAL: TACTICAL_SPEC, DIP: DIP_SPEC}
SPEC_LABELS = {s.key: s.name for s in SPECS.values()}


def get_spec(key: str) -> StrategySpec:
    return SPECS.get(key, TACTICAL_SPEC)


def spec_from_overrides(base: StrategySpec, **overrides) -> StrategySpec:
    """Return a copy of `base` with sidebar overrides applied."""
    clean = {k: v for k, v in overrides.items() if v is not None}
    return StrategySpec(**{**base.__dict__, **clean})


# ─────────────────────────────────────────────────────────────
# Open-lot evaluation
# ─────────────────────────────────────────────────────────────
def _locate_entry(df: pd.DataFrame, entry_date) -> Optional[int]:
    """Index of the first bar on/after entry_date. None if out of range."""
    ts = pd.Timestamp(entry_date)
    if ts.tz is not None:
        ts = ts.tz_localize(None)
    ts = ts.normalize()
    idx = df.index.searchsorted(ts)
    if idx >= len(df):
        return None
    return int(idx)


def trail_series(df: pd.DataFrame, spec: StrategySpec, entry_idx: int) -> pd.Series:
    """
    The running stop level from the entry bar forward.

    Both dashboards previously drew the trail as a single flat scalar, which is
    misleading — the stop ratchets. This returns the actual path.
    """
    close = df["Close"].iloc[entry_idx:]
    atr = df["atr"].iloc[entry_idx:]

    if spec.freeze_atr_at_entry:
        atr_ref = float(df["atr"].iloc[entry_idx])
        if not np.isfinite(atr_ref) or atr_ref <= 0:
            atr_ref = float(atr.dropna().iloc[0]) if len(atr.dropna()) else 0.0
        base = close.cummax() if spec.trail_from_highest_close else close
        return base - spec.atr_mult * atr_ref

    raw = close - spec.atr_mult * atr
    return raw.cummax()  # raise-only


def evaluate_lot(
    df: pd.DataFrame,
    spec: StrategySpec,
    entry_date,
    entry_price: float,
    shares: float = 0.0,
) -> Optional[dict]:
    """
    Walk the bars from entry forward and report what the rules actually did.

    Returns None when the frame has no bar on/after entry_date.
    """
    if df is None or "atr" not in df.columns or len(df) == 0:
        return None
    entry_idx = _locate_entry(df, entry_date)
    if entry_idx is None:
        return None

    held = df.iloc[entry_idx:]
    if held.empty:
        return None

    close = held["Close"]
    trail = trail_series(df, spec, entry_idx)

    atr_at_entry = float(df["atr"].iloc[entry_idx])
    if not np.isfinite(atr_at_entry):
        atr_at_entry = float("nan")
    initial_stop = entry_price - spec.atr_mult * atr_at_entry

    # --- first rule-driven exit, if any -------------------------------
    breach = close <= trail
    if spec.mean_reversion_exit and "zscore" in held.columns:
        mean_hit = held["zscore"] >= spec.z_exit
    else:
        mean_hit = pd.Series(False, index=held.index)

    exited_at = None
    exit_reason = None
    hits = (breach | mean_hit).copy()
    # A lot cannot be closed by the same bar that opened it. The backtests
    # treat entry and trade-management as mutually exclusive on a given bar
    # (`if not in_trade: ... elif shares > 0: ...`), so management starts on
    # the following bar.
    if len(hits):
        hits.iloc[0] = False
    if hits.any():
        pos = int(np.argmax(hits.values))
        exited_at = held.index[pos]
        exit_reason = "Trail hit" if bool(breach.iloc[pos]) else f"Z > {spec.z_exit}"

    last_date = held.index[-1]
    current_close = float(close.iloc[-1])
    current_trail = float(trail.iloc[-1])

    if exited_at is not None:
        exit_price = float(close.loc[exited_at])
        status = "EXIT"
        marked_price = exit_price
    else:
        exit_price = None
        status = "HOLD"
        marked_price = current_close

    # Excursions are close-basis, matching the close-based stop rules.
    run_close = close.loc[:exited_at] if exited_at is not None else close
    mfe = (float(run_close.max()) / entry_price - 1.0) * 100.0
    mae = (float(run_close.min()) / entry_price - 1.0) * 100.0

    pnl_pct = (marked_price / entry_price - 1.0) * 100.0
    pnl_dollar = (marked_price - entry_price) * shares
    risk_per_share = entry_price - initial_stop
    r_multiple = (
        (marked_price - entry_price) / risk_per_share
        if np.isfinite(risk_per_share) and risk_per_share > 0
        else float("nan")
    )
    dist_to_stop = current_close - current_trail
    dist_to_stop_pct = (dist_to_stop / current_close * 100.0) if current_close else 0.0

    # Distance to the mean-reversion target, when the rule set has one.
    mean_target = float(held["sma"].iloc[-1]) if "sma" in held.columns else float("nan")

    entry_z = float(held["zscore"].iloc[0]) if "zscore" in held.columns else float("nan")
    entry_was_signal = bool(np.isfinite(entry_z) and entry_z < spec.z_entry)

    return {
        "status": status,
        "entry_z": entry_z,
        "entry_was_signal": entry_was_signal,
        "exit_date": exited_at,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "entry_index": entry_idx,
        "entry_bar_date": held.index[0],
        "last_date": last_date,
        "current_close": current_close,
        "trail": current_trail,
        "trail_path": trail,
        "atr_at_entry": atr_at_entry,
        "initial_stop": initial_stop,
        "highest_close": float(run_close.max()),
        "lowest_close": float(run_close.min()),
        "mfe_pct": mfe,
        "mae_pct": mae,
        "pnl_pct": pnl_pct,
        "pnl_dollar": pnl_dollar,
        "r_multiple": r_multiple,
        "dist_to_stop": dist_to_stop,
        "dist_to_stop_pct": dist_to_stop_pct,
        "mean_target": mean_target,
        "bars_held": int(len(run_close)),
        "days_held": int((last_date - held.index[0]).days),
    }


def is_post_earnings(date, ticker: str, earnings: dict, window: int = 10) -> bool:
    ts = pd.Timestamp(date).normalize()
    for ed in earnings.get(ticker, []) or []:
        delta = (ts - pd.Timestamp(ed).normalize()).days
        if 0 <= delta <= window:
            return True
    return False


def days_to_next_earnings(ticker: str, earnings: dict) -> Optional[int]:
    today = pd.Timestamp.now().normalize()
    future = [d for d in (earnings.get(ticker) or []) if pd.Timestamp(d) >= today]
    if not future:
        return None
    return int((pd.Timestamp(future[0]) - today).days)
