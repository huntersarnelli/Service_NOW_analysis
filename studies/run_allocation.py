"""
How much of a portfolio should the dip strategy actually be?

Run:  python studies/run_allocation.py   -> studies/results/05_allocation/

The 2022+ window (post-pandemic, including the 2022 bear) is the fairest test:
it excludes the stimulus-distorted 2020-21 melt-up without also excluding the
bear market, and on it the dip strategy beats buy-and-hold on every metric.

But it still carries a ~58% max drawdown. That is a satellite, not a portfolio.
This script blends it with a broad index at various weights, rebalanced
quarterly, to find where the risk-adjusted return actually peaks — and puts an
honest error bar on the result.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from studies.dip_backtest import (  # noqa: E402
    BacktestConfig, buy_and_hold, load_prices, run_backtest, series_metrics,
)

RESULTS = ROOT / "studies" / "results" / "05_allocation"
RESULTS.mkdir(parents=True, exist_ok=True)

TRIO = ["META", "NVDA", "NET"]
WARMUP, END = "2019-09-13", "2026-07-31"
START = "2022-01-03"
CACHE: dict = {}


def banner(t):
    print("\n" + "=" * 80); print(t); print("=" * 80)


def show(df, n=50):
    with pd.option_context("display.width", 210, "display.max_columns", 30):
        print(df.head(n).round(2).to_string(index=False))


def save(df, name):
    df.to_csv(RESULTS / f"{name}.csv", index=False)
    print(f"  -> studies/results/05_allocation/{name}.csv")


def blend(a: pd.Series, b: pd.Series, w: float, rebal: str = "Q") -> pd.Series:
    """Blend two equity curves at weight w on `a`, rebalanced periodically."""
    idx = a.index.intersection(b.index)
    ra, rb = a.reindex(idx).pct_change().fillna(0), b.reindex(idx).pct_change().fillna(0)
    # First trading day of each rebalance period.
    periods = idx.to_period(rebal)
    marks = set(pd.Series(idx, index=periods).groupby(level=0).min().values)
    marks = set(pd.DatetimeIndex(list(marks)))

    eq, va, vb = [], w, 1 - w
    for d in idx:
        va *= 1 + ra.loc[d]
        vb *= 1 + rb.loc[d]
        tot = va + vb
        if d in marks:
            va, vb = tot * w, tot * (1 - w)
        eq.append(tot)
    return pd.Series(eq, index=idx) * 100_000.0


def stats(s: pd.Series, label: str) -> dict:
    m = series_metrics(s)
    return {"allocation": label, "cagr_pct": m["cagr_pct"],
            "max_drawdown_pct": m["max_drawdown_pct"], "sharpe": m["sharpe"],
            "sortino": m["sortino"], "calmar": m["calmar"],
            "annual_vol_pct": m["annual_vol_pct"], "final_equity": m["final_equity"]}


def main():
    summary = {}
    base = BacktestConfig()
    print("Downloading…")
    trio = load_prices(TRIO, WARMUP, END, CACHE)
    bench = load_prices(["SPY", "QQQ"], WARMUP, END, CACHE)

    strat = run_backtest(
        trio, replace(base, sizing_mode="vol_target", risk_frac=0.05),
        start=START, end=END,
    )
    dip = strat.equity
    spy = buy_and_hold({"SPY": bench["SPY"]}, 100_000.0, START, END)
    qqq = buy_and_hold({"QQQ": bench["QQQ"]}, 100_000.0, START, END)

    # ── 1. Blends ────────────────────────────────────────────────────
    banner("1. BLENDING THE DIP SLEEVE WITH A BROAD INDEX (2022+, quarterly rebalance)")
    for core_name, core in (("SPY", spy), ("QQQ", qqq)):
        rows = [stats(core, f"100% {core_name}")]
        for w in (0.10, 0.20, 0.30, 0.40, 0.50, 0.75, 1.00):
            rows.append(stats(blend(dip, core, w), f"{w:.0%} dip / {1-w:.0%} {core_name}"))
        df = pd.DataFrame(rows)
        print(f"\n  Core = {core_name}")
        show(df)
        best = df.sort_values("sharpe", ascending=False).iloc[0]
        print(f"  Peak Sharpe at: {best.allocation}  "
              f"(Sharpe {best.sharpe:.2f}, CAGR {best.cagr_pct:.1f}%, DD {best.max_drawdown_pct:.1f}%)")
        save(df, f"1_blend_{core_name.lower()}")
        summary[f"blend_{core_name}"] = df.to_dict("records")

    # ── 2. How much of this is luck? ─────────────────────────────────
    banner("2. ERROR BAR ON THE 2022+ EDGE")
    bh = buy_and_hold(trio, 100_000.0, START, END)
    eq_s = strat.equity
    eq_b = bh.reindex(eq_s.index).ffill()
    yr_rows = []
    for yr, grp in eq_s.groupby(eq_s.index.year):
        b = eq_b.loc[grp.index]
        yr_rows.append({
            "year": yr,
            "strategy_pct": (grp.iloc[-1] / grp.iloc[0] - 1) * 100,
            "buy_hold_pct": (b.iloc[-1] / b.iloc[0] - 1) * 100,
        })
    yrs = pd.DataFrame(yr_rows)
    yrs["excess_pp"] = yrs.strategy_pct - yrs.buy_hold_pct
    show(yrs)
    n = len(yrs)
    mean, sd = yrs.excess_pp.mean(), yrs.excess_pp.std(ddof=1)
    se = sd / np.sqrt(n)
    t = mean / se if se else 0.0
    print(f"\n  Annual excess over buy & hold: mean {mean:+.1f}pp, sd {sd:.1f}pp, n={n}")
    print(f"  Standard error {se:.1f}pp  ->  t = {t:.2f}")
    print(f"  Rough 95% interval: [{mean - 1.96*se:+.1f}, {mean + 1.96*se:+.1f}] pp")
    print(f"  {'>>> Interval contains zero: the edge is real-looking but NOT statistically established.' if mean - 1.96*se <= 0 <= mean + 1.96*se else '>>> Interval excludes zero.'}")
    save(yrs, "2_annual_excess")
    summary["error_bar"] = {
        "n": int(n), "mean_pp": float(mean), "sd_pp": float(sd),
        "se_pp": float(se), "t": float(t),
        "ci_low": float(mean - 1.96 * se), "ci_high": float(mean + 1.96 * se),
    }

    # ── 3. Final comparison table ────────────────────────────────────
    banner("3. WHAT YOU WOULD ACTUALLY HOLD (2022-01 -> 2026-07)")
    rows = [
        stats(spy, "100% SPY"),
        stats(qqq, "100% QQQ"),
        stats(bh, "100% buy & hold META/NVDA/NET"),
        stats(dip, "100% dip strategy (vol-target 5%)"),
        stats(blend(dip, spy, 0.20), "20% dip / 80% SPY"),
        stats(blend(dip, spy, 0.30), "30% dip / 70% SPY"),
        stats(blend(dip, qqq, 0.30), "30% dip / 70% QQQ"),
    ]
    final = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    show(final)
    save(final, "3_final_comparison")
    summary["final"] = final.to_dict("records")

    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print("\n  -> studies/results/05_allocation/summary.json")
    banner("DONE")
    return summary


if __name__ == "__main__":
    main()
