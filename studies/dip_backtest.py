"""
Aggressive Dip Accumulation — portfolio backtest engine.

This is the harness that was missing from the repo. The strategy document
(docs/legacy_Aggressive_Dip_Accumulation_Strategy.md) quotes $931,543 / 86.8% CAGR /
1.83 Sharpe, but no code producing those numbers was ever committed, so the
claims could not be checked. This module reproduces the documented rules
exactly and makes every design choice an explicit, testable parameter.

Rules as documented
-------------------
Universe        META, NVDA, NET  (the live dashboard also runs DDOG)
Entry / add     20-period Z-score < -1.2
Sizing          20% of CURRENT portfolio equity per lot
Pyramiding      allowed — multiple independent lots per name
Max exposure    100% (no leverage; cash constraint enforces it)
Exit            trailing stop = highest close since THAT lot's entry
                minus 4.0 x ATR(14), with ATR frozen at the entry bar
Mean exit       none (deliberately removed)
Trend filter    none
Commission      5 bps per side

Differences from a single-name backtest
---------------------------------------
This is a portfolio-level simulation: lots compete for one cash balance, and
position size is a fraction of equity that changes as the account grows. The
single-name all-in/all-out loops in testing/ cannot express any of that.

Ambiguities in the written spec, made explicit here
---------------------------------------------------
pyramid_mode    "Every new signal" is ambiguous when Z stays below the
                threshold for several consecutive days. "every_bar" opens a
                lot each qualifying day; "on_cross" opens one only when Z
                crosses down through the threshold. Both are tested.
allocation      Same-day signals across names can exceed available cash. Here
                targets are scaled proportionally rather than filled in ticker
                order, so results do not depend on alphabetisation.

Usage
-----
    from studies.dip_backtest import BacktestConfig, run_backtest, load_prices

    prices = load_prices(["META", "NVDA", "NET"], "2022-09-01", "2026-07-31")
    result = run_backtest(prices, BacktestConfig())
    print(result.metrics)
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Optional

import numpy as np
import pandas as pd
import yfinance as yf

TRADING_DAYS = 252


# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class BacktestConfig:
    z_entry: float = -1.2
    atr_mult: float = 4.0
    alloc: float = 0.20              # fraction of current equity per lot
    sma_window: int = 20
    atr_window: int = 14
    start_capital: float = 100_000.0
    commission_bps: float = 5.0      # per side
    pyramid_mode: str = "every_bar"  # "every_bar" | "on_cross" | "none"
    max_lots_per_ticker: Optional[int] = None
    max_exposure: float = 1.0
    min_trade_notional: float = 250.0
    # Optional regime gate (document section 7 suggests this for live use)
    regime_sma: Optional[int] = None       # e.g. 200
    regime_on: str = "self"                # "self" or "benchmark"
    # Post-earnings sizing (the live dashboard's variant; off by default)
    post_earnings_alloc: Optional[float] = None
    post_earnings_window: int = 10
    # Mean-reversion exit (off — this is what separates B from A)
    mean_reversion_exit: bool = False
    z_exit: float = 0.0

    # Trailing-stop construction. The two strategies differ here as well as on
    # the mean-reversion exit, so both must be switchable to compare them fairly.
    #   "frozen_high"  (B) stop = highest close since entry - k * ATR_at_entry
    #                      ATR frozen, so the stop distance never changes.
    #   "daily_close"  (A) stop = max over s<=t of (close_s - k * ATR_s)
    #                      ATR re-read every bar, so the stop breathes with vol.
    trail_mode: str = "frozen_high"   # "frozen_high" | "daily_close"

    # ---- profit taking on statistical extremes --------------------------
    # Strategy A exits at Z > 0 (the mean), which costs ~21pp of CAGR. A far
    # higher bar is a different proposition: sell only the genuinely extreme
    # highs and redeploy the cash into the next dip.
    #   profit_take_z         sell when Z >= this (e.g. 2.0 = ~97.7th pctile)
    #   profit_take_frac      fraction of the lot to sell (1.0 = all, 0.5 = half)
    #   profit_take_min_gain  only take profit if the lot is up at least this
    #                         much, as a fraction (0.20 = +20%)
    profit_take_z: Optional[float] = None
    profit_take_frac: float = 1.0
    profit_take_min_gain: float = 0.0

    # Percentile profit take: sell when close is at/above this quantile of its
    # own trailing `pct_window` distribution. A distribution-free alternative
    # to Z that does not assume normality.
    profit_take_pct: Optional[float] = None
    pct_window: int = 252

    # Event risk: flatten a lot this many trading days before a known earnings
    # date. Requires the `earnings` argument to run_backtest.
    exit_before_earnings_days: Optional[int] = None

    # ---- time exit ------------------------------------------------------
    # Close a lot unconditionally after this many trading bars, regardless of
    # where the trail sits. docs/02_OVERREACTION_STUDY.md measures the entry signal's
    # excess over random entries decaying to exactly zero by 120 bars, so a
    # lot held past that point is no longer expressing the signal it was
    # opened on -- it is holding beta with a stop under it. This makes the
    # holding period an explicit, testable parameter rather than an emergent
    # property of the trail.
    max_hold_days: Optional[int] = None

    # ---- variants explored in studies/run_improvements.py ----------------
    # Sizing. "equity_frac" is the documented rule: a flat % of equity per lot,
    # which gives a 60%-vol name the same dollars as a 25%-vol name.
    # "vol_target" instead sizes so every lot risks `risk_frac` of equity to its
    # own initial stop, equalising risk contribution across names.
    sizing_mode: str = "equity_frac"      # "equity_frac" | "vol_target"
    risk_frac: float = 0.02               # vol_target: equity risked per lot
    max_weight: float = 0.35              # vol_target: cap on any one LOT

    # ---- portfolio construction ------------------------------------------
    # max_weight above caps a single lot. It does NOT stop pyramiding from
    # accumulating an unbounded position: four 20% lots in one name is 80% of
    # the book in one ticker, which is what docs/01_STRATEGY_REVIEW.md §7.12 warns
    # about ("25-35% positions across four names that are one AI/megacap-tech
    # factor is not a four-position portfolio"). max_ticker_weight caps the
    # CUMULATIVE market value of all open lots in a ticker, as a fraction of
    # current equity, and is checked against existing exposure at entry.
    max_ticker_weight: Optional[float] = None

    # Per-ticker allocation overrides, as a tuple of (ticker, alloc) pairs.
    # A tuple rather than a dict so the config stays hashable and printable.
    # Used to give volatility tiers different base weights: a 60%-vol name and
    # a 20%-vol name should arguably not receive the same 20% of equity.
    alloc_by_ticker: tuple = ()

    # Trail ratchet: tighten the stop once a lot is up N times its initial risk.
    # List of (gain_in_R, new_atr_mult), applied at the highest R reached.
    # The baseline gives back ~21pp of MFE; this trades some upside for less.
    trail_ratchet: tuple = ()

    # Cross-sectional gate: only buy dips in names currently in the top
    # `momentum_top_n` by 12-1 momentum. Turns a hindsight-fixed universe into
    # a rule that picks whatever is leading at the time.
    momentum_top_n: Optional[int] = None
    momentum_lookback: int = 252
    momentum_skip: int = 21

    # Null test: replace the Z signal with random entries of the same frequency.
    random_entry_seed: Optional[int] = None
    random_entry_rate: Optional[float] = None

    # Permanent core. Buy `core_weight` of starting capital equal-weight on bar
    # one and never sell it; dip lots are funded from what is left. This uses
    # the dip signal where it demonstrably works (buying declines) without ever
    # selling the whole book on a whipsaw.
    core_weight: float = 0.0

    def label(self) -> str:
        bits = [f"Z<{self.z_entry}", f"{self.atr_mult}xATR", f"{self.alloc:.0%}"]
        if self.pyramid_mode != "every_bar":
            bits.append(self.pyramid_mode)
        if self.regime_sma:
            bits.append(f"regime>{self.regime_sma}SMA")
        if self.mean_reversion_exit:
            bits.append(f"meanexit Z>{self.z_exit}")
        if self.trail_mode != "frozen_high":
            bits.append(self.trail_mode)
        if self.profit_take_z is not None:
            bits.append(f"PT Z>{self.profit_take_z}"
                        + (f" x{self.profit_take_frac:.0%}" if self.profit_take_frac < 1 else ""))
        if self.profit_take_pct is not None:
            bits.append(f"PT pct>{self.profit_take_pct}")
        if self.max_hold_days is not None:
            bits.append(f"hold<={self.max_hold_days}d")
        if self.max_ticker_weight is not None:
            bits.append(f"cap {self.max_ticker_weight:.0%}/name")
        if self.alloc_by_ticker:
            bits.append("tiered")
        return " ".join(bits)


@dataclass
class OpenLot:
    ticker: str
    shares: float
    entry_date: pd.Timestamp
    entry_price: float
    atr_at_entry: float
    highest_close: float
    lowest_close: float
    atr_mult: float = 4.0          # may tighten over the life of the lot
    is_core: bool = False          # core lots are never sold
    running_stop: float = float("-inf")  # daily_close mode: raise-only stop
    entry_bar: int = -1            # calendar index at entry, for the time exit

    def risk_per_share(self) -> float:
        return self.atr_mult * self.atr_at_entry

    def trail(self, atr_mult: Optional[float] = None) -> float:
        """Frozen-ATR trail from the running high (Strategy B's rule)."""
        return self.highest_close - (atr_mult or self.atr_mult) * self.atr_at_entry

    def stop_level(self, mode: str) -> float:
        return self.running_stop if mode == "daily_close" else self.trail()

    def update_stop(self, mode: str, close_px: float, atr_today: float) -> None:
        """Raise-only stop using today's ATR (Strategy A's rule)."""
        if mode != "daily_close":
            return
        if np.isfinite(atr_today) and atr_today > 0:
            candidate = close_px - self.atr_mult * atr_today
            if candidate > self.running_stop:
                self.running_stop = candidate

    def apply_ratchet(self, ratchet: tuple) -> None:
        """Tighten the multiple once the lot is up enough R. Never loosens."""
        if not ratchet:
            return
        base_risk = self.entry_price * 0.0 + self.atr_at_entry
        if base_risk <= 0:
            return
        gain_r = (self.highest_close - self.entry_price) / base_risk
        for trigger_r, new_mult in sorted(ratchet, key=lambda x: x[0]):
            if gain_r >= trigger_r:
                self.atr_mult = min(self.atr_mult, float(new_mult))


@dataclass
class BacktestResult:
    config: BacktestConfig
    equity: pd.Series
    exposure: pd.Series
    trades: pd.DataFrame
    metrics: dict
    benchmark: Optional[pd.Series] = None


# ─────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────
def load_prices(
    tickers: Iterable[str],
    start: str,
    end: str,
    cache: Optional[dict] = None,
) -> dict[str, pd.DataFrame]:
    """Download OHLCV per ticker. `cache` lets a study reuse one download."""
    tickers = list(dict.fromkeys(tickers))
    out: dict[str, pd.DataFrame] = {}
    todo = []
    for t in tickers:
        if cache is not None and t in cache:
            out[t] = cache[t]
        else:
            todo.append(t)

    if todo:
        raw = yf.download(
            todo, start=start, end=end, group_by="ticker",
            auto_adjust=True, threads=True, progress=False,
        )
        multi = isinstance(raw.columns, pd.MultiIndex)
        for t in todo:
            try:
                df = (raw[t] if multi else raw).copy()
            except KeyError:
                continue
            df = df.dropna(subset=["Close"])
            if df.empty:
                continue
            df.index = pd.to_datetime(df.index)
            if getattr(df.index, "tz", None) is not None:
                df.index = df.index.tz_localize(None)
            out[t] = df
            if cache is not None:
                cache[t] = df
    return out


def add_indicators(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    out = df.copy()
    c = out["Close"]
    sma = c.rolling(cfg.sma_window).mean()
    std = c.rolling(cfg.sma_window).std()
    out["sma"] = sma
    out["zscore"] = (c - sma) / std

    prev = c.shift(1)
    tr = pd.concat(
        [out["High"] - out["Low"], (out["High"] - prev).abs(), (out["Low"] - prev).abs()],
        axis=1,
    ).max(axis=1)
    out["atr"] = tr.rolling(cfg.atr_window).mean()
    if cfg.regime_sma:
        out["regime_sma"] = c.rolling(cfg.regime_sma).mean()
    return out


def momentum_rank(
    close: pd.DataFrame, lookback: int, skip: int, top_n: int
) -> pd.DataFrame:
    """Boolean frame: is this name in the top_n by 12-1 momentum on this bar?"""
    mom = close.shift(skip) / close.shift(lookback) - 1.0
    ranked = mom.rank(axis=1, ascending=False, na_option="bottom")
    return ranked <= top_n


# ─────────────────────────────────────────────────────────────
# Engine
# ─────────────────────────────────────────────────────────────
def run_backtest(
    prices: dict[str, pd.DataFrame],
    cfg: BacktestConfig,
    start: Optional[str] = None,
    end: Optional[str] = None,
    earnings: Optional[dict[str, list]] = None,
    regime_series: Optional[pd.Series] = None,
) -> BacktestResult:
    """
    Daily loop. Order within a bar: mark to market -> exits -> entries.

    Exits run before entries so freed cash is redeployable the same day, which
    is the most generous reading of the written rules; it is also what a real
    end-of-day rebalance would do.
    """
    frames = {t: add_indicators(df, cfg) for t, df in prices.items() if not df.empty}
    if not frames:
        raise ValueError("no price data")

    calendar = sorted(set().union(*[set(df.index) for df in frames.values()]))
    calendar = pd.DatetimeIndex(calendar)
    if start:
        calendar = calendar[calendar >= pd.Timestamp(start)]
    if end:
        calendar = calendar[calendar <= pd.Timestamp(end)]
    if len(calendar) == 0:
        raise ValueError("empty calendar after date filter")

    close = pd.DataFrame({t: df["Close"] for t, df in frames.items()}).reindex(calendar)
    zsc = pd.DataFrame({t: df["zscore"] for t, df in frames.items()}).reindex(calendar)
    atr = pd.DataFrame({t: df["atr"] for t, df in frames.items()}).reindex(calendar)
    regime = None
    if cfg.regime_sma:
        if cfg.regime_on == "benchmark" and regime_series is not None:
            bench = regime_series.reindex(calendar).ffill()
            bench_sma = bench.rolling(cfg.regime_sma).mean()
            regime = pd.DataFrame(
                {t: (bench > bench_sma) for t in frames}, index=calendar
            )
        else:
            regime = pd.DataFrame(
                {t: (df["Close"] > df["regime_sma"]) for t, df in frames.items()}
            ).reindex(calendar)

    pct_rank = None
    if cfg.profit_take_pct is not None:
        pct_rank = close.rolling(cfg.pct_window, min_periods=60).apply(
            lambda w: (w <= w[-1]).mean(), raw=True
        )

    earnings_soon = None
    if cfg.exit_before_earnings_days is not None and earnings:
        earnings_soon = pd.DataFrame(False, index=calendar, columns=close.columns)
        for t in close.columns:
            for ed in earnings.get(t, []) or []:
                ed = pd.Timestamp(ed).normalize()
                locs = calendar[(calendar < ed) &
                                (calendar >= ed - pd.Timedelta(days=cfg.exit_before_earnings_days * 2))]
                if len(locs):
                    window = locs[-cfg.exit_before_earnings_days:]
                    earnings_soon.loc[window, t] = True

    mom_ok = None
    if cfg.momentum_top_n:
        mom_ok = momentum_rank(
            close, cfg.momentum_lookback, cfg.momentum_skip, cfg.momentum_top_n
        )

    rand_mask = None
    if cfg.random_entry_seed is not None:
        rate = cfg.random_entry_rate
        if rate is None:  # match the real signal's frequency
            rate = float((zsc < cfg.z_entry).to_numpy().mean())
        rng = np.random.default_rng(cfg.random_entry_seed)
        rand_mask = pd.DataFrame(
            rng.random(close.shape) < rate, index=close.index, columns=close.columns
        )

    fee = cfg.commission_bps / 10_000.0
    cash = float(cfg.start_capital)
    open_lots: list[OpenLot] = []
    trades: list[dict] = []
    equity_path, exposure_path = [], []
    prev_signal = {t: False for t in frames}

    def price_of(t: str, i: int) -> float:
        v = close.iat[i, close.columns.get_loc(t)]
        return float(v) if pd.notna(v) else float("nan")

    # ---- seed the permanent core on the first bar ------------------
    if cfg.core_weight > 0:
        investable = [t for t in frames if np.isfinite(price_of(t, 0)) and price_of(t, 0) > 0]
        if investable:
            per = (cfg.start_capital * cfg.core_weight) / len(investable)
            for t in investable:
                px0 = price_of(t, 0)
                sh = (per / (1.0 + fee)) / px0
                cash -= sh * px0 * (1.0 + fee)
                a0 = atr.iat[0, atr.columns.get_loc(t)]
                open_lots.append(
                    OpenLot(
                        ticker=t, shares=sh, entry_date=calendar[0], entry_price=px0,
                        atr_at_entry=float(a0) if pd.notna(a0) else 0.0,
                        highest_close=px0, lowest_close=px0,
                        atr_mult=cfg.atr_mult, is_core=True,
                        running_stop=float("-inf"), entry_bar=0,
                    )
                )

    alloc_override = dict(cfg.alloc_by_ticker)

    for i, date in enumerate(calendar):
        # ---- 1. mark to market -------------------------------------
        for lot in open_lots:
            px = price_of(lot.ticker, i)
            if np.isfinite(px):
                lot.highest_close = max(lot.highest_close, px)
                lot.lowest_close = min(lot.lowest_close, px)
                if not lot.is_core:
                    lot.apply_ratchet(cfg.trail_ratchet)
                    lot.update_stop(
                        cfg.trail_mode, px,
                        float(atr.iat[i, atr.columns.get_loc(lot.ticker)]),
                    )

        # ---- 2. exits ----------------------------------------------
        still_open: list[OpenLot] = []
        for lot in open_lots:
            px = price_of(lot.ticker, i)
            if not np.isfinite(px):
                still_open.append(lot)
                continue

            reason = None
            if lot.is_core:
                still_open.append(lot)
                continue
            if date > lot.entry_date:  # a lot cannot close on its opening bar
                if px <= lot.stop_level(cfg.trail_mode):
                    reason = "Trail hit"
                elif cfg.mean_reversion_exit:
                    z = zsc.iat[i, zsc.columns.get_loc(lot.ticker)]
                    if pd.notna(z) and z >= cfg.z_exit:
                        reason = f"Z > {cfg.z_exit}"

                if reason is None and cfg.profit_take_z is not None:
                    z = zsc.iat[i, zsc.columns.get_loc(lot.ticker)]
                    gain = px / lot.entry_price - 1.0
                    if (pd.notna(z) and z >= cfg.profit_take_z
                            and gain >= cfg.profit_take_min_gain):
                        reason = f"Profit take Z>{cfg.profit_take_z}"

                if reason is None and pct_rank is not None:
                    q = pct_rank.iat[i, pct_rank.columns.get_loc(lot.ticker)]
                    gain = px / lot.entry_price - 1.0
                    if (pd.notna(q) and q >= cfg.profit_take_pct
                            and gain >= cfg.profit_take_min_gain):
                        reason = f"Profit take pct>{cfg.profit_take_pct}"

                if reason is None and cfg.max_hold_days is not None:
                    if i - lot.entry_bar >= cfg.max_hold_days:
                        reason = f"Time exit {cfg.max_hold_days}d"

                if reason is None and earnings_soon is not None:
                    e = earnings_soon.iat[i, earnings_soon.columns.get_loc(lot.ticker)]
                    if bool(e):
                        reason = "Pre-earnings flat"

            if reason is None:
                still_open.append(lot)
                continue

            # A partial profit take sells a slice and leaves the rest running.
            partial = (
                reason.startswith("Profit take")
                and 0.0 < cfg.profit_take_frac < 1.0
            )
            sold = lot.shares * (cfg.profit_take_frac if partial else 1.0)

            proceeds = sold * px * (1.0 - fee)
            cost = sold * lot.entry_price * (1.0 + fee)
            cash += proceeds
            trades.append(
                {
                    "ticker": lot.ticker,
                    "entry_date": lot.entry_date,
                    "exit_date": date,
                    "entry_price": lot.entry_price,
                    "exit_price": px,
                    "shares": sold,
                    "cost": cost,
                    "proceeds": proceeds,
                    "pnl": proceeds - cost,
                    "return_pct": (proceeds / cost - 1.0) * 100.0,
                    "days_held": (date - lot.entry_date).days,
                    "bars_held": int(
                        close.index.get_loc(date) - close.index.get_loc(lot.entry_date)
                    ),
                    "exit_reason": reason,
                    "mfe_pct": (lot.highest_close / lot.entry_price - 1.0) * 100.0,
                    "mae_pct": (lot.lowest_close / lot.entry_price - 1.0) * 100.0,
                    "atr_at_entry": lot.atr_at_entry,
                }
            )
            if partial:
                lot.shares -= sold
                if lot.shares > 1e-9:
                    still_open.append(lot)
        open_lots = still_open

        # ---- 3. equity before new entries --------------------------
        mkt = 0.0
        for lot in open_lots:
            px = price_of(lot.ticker, i)
            mkt += lot.shares * (px if np.isfinite(px) else lot.entry_price)
        equity = cash + mkt

        # ---- 4. entries --------------------------------------------
        candidates: list[str] = []
        for t in frames:
            z = zsc.iat[i, zsc.columns.get_loc(t)]
            a = atr.iat[i, atr.columns.get_loc(t)]
            px = price_of(t, i)
            if rand_mask is not None:
                fired = bool(rand_mask.iat[i, rand_mask.columns.get_loc(t)])
            else:
                fired = bool(pd.notna(z) and z < cfg.z_entry)

            gate = True
            if mom_ok is not None:
                m = mom_ok.iat[i, mom_ok.columns.get_loc(t)]
                gate = bool(m) if pd.notna(m) else False
            if regime is not None:
                g = regime.iat[i, regime.columns.get_loc(t)]
                gate = bool(g) if pd.notna(g) else False

            eligible = (
                fired and gate
                and np.isfinite(px) and px > 0
                and pd.notna(a) and float(a) > 0
            )
            if eligible and cfg.pyramid_mode == "on_cross" and prev_signal[t]:
                eligible = False  # only the bar Z crosses down
            if eligible and cfg.pyramid_mode == "none":
                if any(lot.ticker == t for lot in open_lots):
                    eligible = False
            if eligible and cfg.max_lots_per_ticker is not None:
                if sum(1 for lot in open_lots if lot.ticker == t) >= cfg.max_lots_per_ticker:
                    eligible = False

            prev_signal[t] = fired
            if eligible:
                candidates.append(t)

        if candidates:
            headroom = max(cfg.max_exposure * equity - mkt, 0.0)
            budget = min(cash, headroom)
            targets = {}
            for t in candidates:
                if cfg.sizing_mode == "vol_target":
                    # Risk the same slice of equity on every lot: shares are set
                    # so shares * (atr_mult * ATR) == equity * risk_frac. A 60%-vol
                    # name therefore gets far fewer dollars than a 25%-vol name.
                    a_entry = float(atr.iat[i, atr.columns.get_loc(t)])
                    px_t = price_of(t, i)
                    stop_dist = cfg.atr_mult * a_entry
                    if stop_dist <= 0 or not np.isfinite(px_t) or px_t <= 0:
                        continue
                    notional = (equity * cfg.risk_frac) * px_t / stop_dist
                    targets[t] = min(notional, equity * cfg.max_weight)
                    continue

                a = alloc_override.get(t, cfg.alloc)
                if cfg.post_earnings_alloc is not None and earnings:
                    for ed in earnings.get(t, []) or []:
                        delta = (date - pd.Timestamp(ed).normalize()).days
                        if 0 <= delta <= cfg.post_earnings_window:
                            a = cfg.post_earnings_alloc
                            break
                targets[t] = equity * a

            # Cumulative per-ticker cap: subtract what is already held in that
            # name so pyramiding cannot walk past the limit one lot at a time.
            if cfg.max_ticker_weight is not None and equity > 0:
                held: dict[str, float] = {}
                for lot in open_lots:
                    lp = price_of(lot.ticker, i)
                    if np.isfinite(lp):
                        held[lot.ticker] = held.get(lot.ticker, 0.0) + lot.shares * lp
                room_cap = cfg.max_ticker_weight * equity
                for t in list(targets):
                    room = max(room_cap - held.get(t, 0.0), 0.0)
                    targets[t] = min(targets[t], room)
                targets = {t: v for t, v in targets.items() if v > 0}

            total = sum(targets.values())
            if total > budget > 0:
                scale = budget / total
                targets = {t: v * scale for t, v in targets.items()}

            for t in sorted(targets, key=lambda k: -targets[k]):
                spend = min(targets[t], cash / (1.0 + fee))
                if spend < cfg.min_trade_notional:
                    continue
                px = price_of(t, i)
                shares = spend / px
                cash -= shares * px * (1.0 + fee)
                a_entry = float(atr.iat[i, atr.columns.get_loc(t)])
                open_lots.append(
                    OpenLot(
                        ticker=t, shares=shares, entry_date=date, entry_price=px,
                        atr_at_entry=a_entry, highest_close=px, lowest_close=px,
                        atr_mult=cfg.atr_mult,
                        running_stop=px - cfg.atr_mult * a_entry,
                        entry_bar=i,
                    )
                )

        # ---- 5. record ---------------------------------------------
        mkt = 0.0
        for lot in open_lots:
            px = price_of(lot.ticker, i)
            mkt += lot.shares * (px if np.isfinite(px) else lot.entry_price)
        equity = cash + mkt
        equity_path.append(equity)
        exposure_path.append(mkt / equity if equity > 0 else 0.0)

    # ---- close survivors at the last bar ---------------------------
    last_date = calendar[-1]
    for lot in open_lots:
        if lot.is_core:
            continue  # core is held, not traded; it never produces a trade record
        px = price_of(lot.ticker, len(calendar) - 1)
        if not np.isfinite(px):
            px = lot.entry_price
        proceeds = lot.shares * px * (1.0 - fee)
        cost = lot.shares * lot.entry_price * (1.0 + fee)
        trades.append(
            {
                "ticker": lot.ticker, "entry_date": lot.entry_date, "exit_date": last_date,
                "entry_price": lot.entry_price, "exit_price": px, "shares": lot.shares,
                "cost": cost, "proceeds": proceeds, "pnl": proceeds - cost,
                "return_pct": (proceeds / cost - 1.0) * 100.0,
                "days_held": (last_date - lot.entry_date).days,
                "bars_held": int(len(calendar) - 1 - close.index.get_loc(lot.entry_date)),
                "exit_reason": "Open at end",
                "mfe_pct": (lot.highest_close / lot.entry_price - 1.0) * 100.0,
                "mae_pct": (lot.lowest_close / lot.entry_price - 1.0) * 100.0,
                "atr_at_entry": lot.atr_at_entry,
            }
        )

    equity_s = pd.Series(equity_path, index=calendar, name="equity")
    exposure_s = pd.Series(exposure_path, index=calendar, name="exposure")
    trades_df = pd.DataFrame(trades)
    metrics = compute_metrics(equity_s, exposure_s, trades_df, cfg)
    return BacktestResult(cfg, equity_s, exposure_s, trades_df, metrics)


# ─────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────
def compute_metrics(
    equity: pd.Series,
    exposure: pd.Series,
    trades: pd.DataFrame,
    cfg: Optional[BacktestConfig] = None,
) -> dict:
    start_cap = float(equity.iloc[0]) if len(equity) else 0.0
    final = float(equity.iloc[-1]) if len(equity) else 0.0
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    rets = equity.pct_change().dropna()

    downside = rets[rets < 0]
    dd = equity / equity.cummax() - 1.0

    m = {
        "final_equity": final,
        "total_return_pct": (final / start_cap - 1.0) * 100.0 if start_cap else 0.0,
        "cagr_pct": ((final / start_cap) ** (1.0 / years) - 1.0) * 100.0 if start_cap > 0 else 0.0,
        "max_drawdown_pct": float(dd.min()) * 100.0,
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(TRADING_DAYS)) if rets.std() > 0 else 0.0,
        "sortino": float(rets.mean() / downside.std() * np.sqrt(TRADING_DAYS)) if len(downside) and downside.std() > 0 else 0.0,
        "annual_vol_pct": float(rets.std() * np.sqrt(TRADING_DAYS)) * 100.0,
        "avg_exposure_pct": float(exposure.mean()) * 100.0,
        "pct_days_fully_invested": float((exposure >= 0.99).mean()) * 100.0,
        "pct_days_95_invested": float((exposure >= 0.95).mean()) * 100.0,
        "years": years,
    }
    m["calmar"] = m["cagr_pct"] / abs(m["max_drawdown_pct"]) if m["max_drawdown_pct"] else 0.0

    if len(trades):
        wins = trades[trades["return_pct"] > 0]
        losses = trades[trades["return_pct"] <= 0]
        gross_win = float(wins["pnl"].sum()) if len(wins) else 0.0
        gross_loss = float(-losses["pnl"].sum()) if len(losses) else 0.0
        m.update(
            {
                "num_lots": int(len(trades)),
                "win_rate_pct": float((trades["return_pct"] > 0).mean()) * 100.0,
                "avg_trade_pct": float(trades["return_pct"].mean()),
                "median_trade_pct": float(trades["return_pct"].median()),
                "avg_winner_pct": float(wins["return_pct"].mean()) if len(wins) else 0.0,
                "avg_loser_pct": float(losses["return_pct"].mean()) if len(losses) else 0.0,
                "best_trade_pct": float(trades["return_pct"].max()),
                "worst_trade_pct": float(trades["return_pct"].min()),
                "avg_days_held": float(trades["days_held"].mean()),
                "median_days_held": float(trades["days_held"].median()),
                "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf"),
                "avg_mfe_pct": float(trades["mfe_pct"].mean()),
                "avg_mae_pct": float(trades["mae_pct"].mean()),
                "avg_giveback_pct": float((trades["mfe_pct"] - trades["return_pct"]).mean()),
            }
        )
    else:
        m.update({"num_lots": 0, "win_rate_pct": 0.0, "avg_trade_pct": 0.0})
    return m


def buy_and_hold(
    prices: dict[str, pd.DataFrame],
    start_capital: float = 100_000.0,
    start: Optional[str] = None,
    end: Optional[str] = None,
    commission_bps: float = 5.0,
) -> pd.Series:
    """Equal-weight, bought on day one, never rebalanced."""
    frames = {t: df for t, df in prices.items() if not df.empty}
    calendar = pd.DatetimeIndex(sorted(set().union(*[set(df.index) for df in frames.values()])))
    if start:
        calendar = calendar[calendar >= pd.Timestamp(start)]
    if end:
        calendar = calendar[calendar <= pd.Timestamp(end)]
    close = pd.DataFrame({t: df["Close"] for t, df in frames.items()}).reindex(calendar).ffill()
    close = close.dropna(axis=1, how="all")
    per_name = start_capital / close.shape[1]
    fee = commission_bps / 10_000.0
    shares = (per_name * (1 - fee)) / close.iloc[0]
    return (close * shares).sum(axis=1).rename("buy_hold")


def series_metrics(equity: pd.Series, label: str = "") -> dict:
    flat = pd.Series(1.0, index=equity.index)
    m = compute_metrics(equity, flat, pd.DataFrame())
    m["label"] = label
    return m


def sweep(
    prices: dict[str, pd.DataFrame],
    base: BacktestConfig,
    grid: dict[str, list],
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """Cartesian sweep over one or two config fields."""
    import itertools

    keys = list(grid)
    rows = []
    for combo in itertools.product(*[grid[k] for k in keys]):
        cfg = replace(base, **dict(zip(keys, combo)))
        try:
            res = run_backtest(prices, cfg, start=start, end=end)
        except Exception as exc:  # a degenerate combo should not kill the sweep
            rows.append({**dict(zip(keys, combo)), "error": str(exc)})
            continue
        rows.append({**dict(zip(keys, combo)), **res.metrics})
    return pd.DataFrame(rows)
