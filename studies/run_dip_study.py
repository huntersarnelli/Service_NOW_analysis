"""
Comprehensive study of the Aggressive Dip Accumulation strategy.

Run:  python studies/run_dip_study.py

Writes CSVs and a JSON summary to studies/results/01_dip_study/ so every number quoted in
docs/01_STRATEGY_REVIEW.md is reproducible and auditable.

Sections
  1  Baseline reproduction of the documented claims
  2  Benchmarks (equal-weight B&H, SPY, QQQ)
  3  Pyramiding-mode sensitivity (the spec is ambiguous here)
  4  Entry x trail parameter surface
  5  Position-size sweep
  6  Universe variants, including the live dashboard's 4-name set
  7  Selection-bias test: same rules across a broad basket
  8  Walk-forward: fit 2023-24, test 2025-26
  9  Regime filter (200-SMA gate)
 10  Commission and start-date robustness
 11  Trade-level statistics
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
    BacktestConfig,
    buy_and_hold,
    compute_metrics,
    load_prices,
    run_backtest,
    series_metrics,
    sweep,
)

RESULTS = ROOT / "studies" / "results" / "01_dip_study"
RESULTS.mkdir(parents=True, exist_ok=True)

WARMUP_START = "2022-09-01"
STUDY_START = "2023-01-03"
STUDY_END = "2026-07-31"
SPLIT = "2025-01-01"

DOC_UNIVERSE = ["META", "NVDA", "NET"]
DASH_UNIVERSE = ["META", "NVDA", "NET", "DDOG"]
TACTICAL_UNIVERSE = ["NVDA", "META", "NET", "NOW", "MSFT", "GOOGL", "PANW", "CRWD", "DDOG", "CRM"]

# A broad, pre-selected liquid large-cap basket for the selection-bias test.
# Chosen for being obvious 2022-era large caps, not for how they performed.
BROAD_BASKET = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "INTC", "QCOM", "TXN", "NOW", "PANW", "CRWD", "DDOG", "NET",
    "SNOW", "SHOP", "UBER", "ABNB", "PYPL", "SQ", "ZS", "MDB", "TEAM", "WDAY",
]

CACHE: dict = {}
DOC_CLAIMS = {
    "final_equity": 931_543, "total_return_pct": 831.6, "cagr_pct": 86.8,
    "max_drawdown_pct": -31.1, "sharpe": 1.83, "avg_exposure_pct": 95.4,
    "pct_days_fully_invested": 87.7, "num_lots": 76, "win_rate_pct": 57.0,
    "avg_days_held": 90.0,
}

KEY_METRICS = [
    "final_equity", "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe",
    "sortino", "calmar", "annual_vol_pct", "avg_exposure_pct",
    "pct_days_fully_invested", "num_lots", "win_rate_pct", "avg_trade_pct",
    "avg_days_held", "profit_factor", "avg_mfe_pct", "avg_giveback_pct",
]


def banner(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def show(df: pd.DataFrame, cols: list[str] | None = None, n: int = 40) -> None:
    d = df if cols is None else df[[c for c in cols if c in df.columns]]
    with pd.option_context("display.width", 200, "display.max_columns", 40):
        print(d.head(n).to_string(index=False))


def save(df: pd.DataFrame, name: str) -> None:
    path = RESULTS / f"{name}.csv"
    df.to_csv(path, index=False)
    print(f"  -> {path.relative_to(ROOT)}")


def metrics_row(res, label: str) -> dict:
    return {"variant": label, **{k: res.metrics.get(k) for k in KEY_METRICS}}


def main() -> dict:
    summary: dict = {}
    base = BacktestConfig()

    print("Downloading price history…")
    doc_prices = load_prices(DOC_UNIVERSE, WARMUP_START, STUDY_END, CACHE)
    print(f"  {len(doc_prices)}/{len(DOC_UNIVERSE)} names, "
          f"{min(len(d) for d in doc_prices.values())}–{max(len(d) for d in doc_prices.values())} bars")

    # ── 1. Baseline reproduction ─────────────────────────────────────
    banner("1. BASELINE — documented rules, documented universe and period")
    baseline = run_backtest(doc_prices, base, start=STUDY_START, end=STUDY_END)
    rows = []
    for k, claimed in DOC_CLAIMS.items():
        actual = baseline.metrics.get(k)
        diff = (actual - claimed) if actual is not None else None
        rows.append({
            "metric": k, "documented": claimed, "reproduced": actual,
            "difference": diff,
            "pct_gap": (diff / abs(claimed) * 100.0) if claimed else None,
        })
    repro = pd.DataFrame(rows)
    show(repro)
    save(repro, "01_baseline_reproduction")
    summary["baseline"] = baseline.metrics

    # ── 2. Benchmarks ────────────────────────────────────────────────
    banner("2. BENCHMARKS")
    bench_prices = load_prices(["SPY", "QQQ"], WARMUP_START, STUDY_END, CACHE)
    bh = buy_and_hold(doc_prices, base.start_capital, STUDY_START, STUDY_END)
    rows = [metrics_row(baseline, "Aggressive Dip (Z<-1.2, 4xATR, 20%)")]
    rows.append({"variant": "Equal-weight buy & hold (same 3 names)",
                 **{k: series_metrics(bh).get(k) for k in KEY_METRICS}})
    for t, df in bench_prices.items():
        s = buy_and_hold({t: df}, base.start_capital, STUDY_START, STUDY_END)
        rows.append({"variant": f"{t} buy & hold",
                     **{k: series_metrics(s).get(k) for k in KEY_METRICS}})
    bench = pd.DataFrame(rows)
    show(bench, ["variant", "final_equity", "cagr_pct", "max_drawdown_pct", "sharpe", "calmar"])
    save(bench, "02_benchmarks")
    summary["benchmarks"] = bench.to_dict("records")

    # ── 3. Pyramiding mode ───────────────────────────────────────────
    banner("3. PYRAMIDING MODE (the written spec is ambiguous)")
    rows = []
    for mode in ("every_bar", "on_cross", "none"):
        r = run_backtest(doc_prices, replace(base, pyramid_mode=mode),
                         start=STUDY_START, end=STUDY_END)
        rows.append(metrics_row(r, mode))
    pyr = pd.DataFrame(rows)
    show(pyr, ["variant", "final_equity", "cagr_pct", "max_drawdown_pct", "sharpe",
               "num_lots", "win_rate_pct", "avg_exposure_pct"])
    save(pyr, "03_pyramiding_mode")
    summary["pyramiding"] = pyr.to_dict("records")

    # ── 4. Parameter surface ─────────────────────────────────────────
    banner("4. ENTRY x TRAIL SURFACE (is Z<-1.2 / 4xATR really the optimum?)")
    grid = sweep(
        doc_prices, base,
        {"z_entry": [-2.0, -1.8, -1.5, -1.2, -1.0, -0.8, -0.5],
         "atr_mult": [2.0, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]},
        start=STUDY_START, end=STUDY_END,
    )
    pivot_cagr = grid.pivot(index="z_entry", columns="atr_mult", values="cagr_pct").round(1)
    pivot_sharpe = grid.pivot(index="z_entry", columns="atr_mult", values="sharpe").round(2)
    print("\nCAGR % by entry threshold (rows) x ATR multiple (cols):")
    print(pivot_cagr.to_string())
    print("\nSharpe:")
    print(pivot_sharpe.to_string())
    best = grid.sort_values("cagr_pct", ascending=False).head(5)
    print("\nTop 5 by CAGR:")
    show(best, ["z_entry", "atr_mult", "final_equity", "cagr_pct", "max_drawdown_pct", "sharpe", "num_lots"])
    doc_cell = grid[(grid.z_entry == -1.2) & (grid.atr_mult == 4.0)].iloc[0]
    rank = int((grid.cagr_pct > doc_cell.cagr_pct).sum()) + 1
    print(f"\nDocumented cell (Z<-1.2, 4xATR) ranks {rank}/{len(grid)} by CAGR "
          f"({doc_cell.cagr_pct:.1f}%), spread {grid.cagr_pct.min():.1f}%–{grid.cagr_pct.max():.1f}%")
    save(grid, "04_parameter_surface")
    summary["surface"] = {
        "doc_rank": rank, "n_cells": len(grid),
        "doc_cagr": float(doc_cell.cagr_pct),
        "best_cagr": float(grid.cagr_pct.max()),
        "worst_cagr": float(grid.cagr_pct.min()),
        "median_cagr": float(grid.cagr_pct.median()),
    }

    # ── 5. Position size ─────────────────────────────────────────────
    banner("5. POSITION SIZE PER LOT")
    alloc_grid = sweep(doc_prices, base, {"alloc": [0.10, 0.15, 0.20, 0.25, 0.33, 0.50, 1.00]},
                       start=STUDY_START, end=STUDY_END)
    show(alloc_grid, ["alloc", "final_equity", "cagr_pct", "max_drawdown_pct", "sharpe",
                      "calmar", "avg_exposure_pct", "num_lots"])
    save(alloc_grid, "05_position_size")
    summary["alloc"] = alloc_grid.to_dict("records")

    # ── 6. Universe variants ─────────────────────────────────────────
    banner("6. UNIVERSE VARIANTS")
    rows = []
    for name, tickers in [
        ("Doc: META/NVDA/NET", DOC_UNIVERSE),
        ("Dashboard: + DDOG", DASH_UNIVERSE),
        ("Tactical 10-name", TACTICAL_UNIVERSE),
    ]:
        p = load_prices(tickers, WARMUP_START, STUDY_END, CACHE)
        r = run_backtest(p, base, start=STUDY_START, end=STUDY_END)
        b = buy_and_hold(p, base.start_capital, STUDY_START, STUDY_END)
        row = metrics_row(r, name)
        row["bh_cagr_pct"] = series_metrics(b)["cagr_pct"]
        row["excess_cagr_pct"] = row["cagr_pct"] - row["bh_cagr_pct"]
        rows.append(row)
    uni = pd.DataFrame(rows)
    show(uni, ["variant", "final_equity", "cagr_pct", "bh_cagr_pct", "excess_cagr_pct",
               "max_drawdown_pct", "sharpe", "num_lots"])
    save(uni, "06_universe_variants")
    summary["universes"] = uni.to_dict("records")

    # ── 7. Selection bias ────────────────────────────────────────────
    banner("7. SELECTION-BIAS TEST — same rules, one name at a time, broad basket")
    broad = load_prices(BROAD_BASKET, WARMUP_START, STUDY_END, CACHE)
    print(f"  {len(broad)}/{len(BROAD_BASKET)} names downloaded")
    rows = []
    for t, df in broad.items():
        if len(df) < 300:
            continue
        try:
            r = run_backtest({t: df}, base, start=STUDY_START, end=STUDY_END)
            b = buy_and_hold({t: df}, base.start_capital, STUDY_START, STUDY_END)
        except Exception:
            continue
        rows.append({
            "ticker": t,
            "cagr_pct": r.metrics["cagr_pct"],
            "bh_cagr_pct": series_metrics(b)["cagr_pct"],
            "excess_cagr_pct": r.metrics["cagr_pct"] - series_metrics(b)["cagr_pct"],
            "max_drawdown_pct": r.metrics["max_drawdown_pct"],
            "sharpe": r.metrics["sharpe"],
            "num_lots": r.metrics["num_lots"],
            "win_rate_pct": r.metrics["win_rate_pct"],
            "beats_bh": r.metrics["cagr_pct"] > series_metrics(b)["cagr_pct"],
        })
    single = pd.DataFrame(rows).sort_values("cagr_pct", ascending=False)
    show(single, ["ticker", "cagr_pct", "bh_cagr_pct", "excess_cagr_pct",
                  "max_drawdown_pct", "sharpe", "num_lots", "beats_bh"], n=40)
    n = len(single)
    beat = int(single.beats_bh.sum())
    chosen = single[single.ticker.isin(DOC_UNIVERSE)]
    print(f"\n  Names where the strategy beat buy & hold: {beat}/{n} ({beat/n*100:.0f}%)")
    print(f"  Median excess CAGR across the basket: {single.excess_cagr_pct.median():+.1f} pp")
    print(f"  Mean   excess CAGR across the basket: {single.excess_cagr_pct.mean():+.1f} pp")
    for _, row in chosen.iterrows():
        pct = (single.cagr_pct > row.cagr_pct).sum() / n * 100
        print(f"  {row.ticker}: CAGR {row.cagr_pct:6.1f}%  -> top {pct:.0f}% of the basket")
    save(single, "07_selection_bias")
    summary["selection_bias"] = {
        "n": n, "beat_bh": beat,
        "median_excess_cagr": float(single.excess_cagr_pct.median()),
        "mean_excess_cagr": float(single.excess_cagr_pct.mean()),
        "chosen_percentiles": {
            row.ticker: float((single.cagr_pct > row.cagr_pct).sum() / n * 100)
            for _, row in chosen.iterrows()
        },
    }

    # ── 8. Walk-forward ──────────────────────────────────────────────
    banner("8. WALK-FORWARD — fit on 2023-24, test on 2025-26")
    fit = sweep(doc_prices, base,
                {"z_entry": [-2.0, -1.8, -1.5, -1.2, -1.0, -0.8],
                 "atr_mult": [2.0, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]},
                start=STUDY_START, end=SPLIT)
    best_is = fit.sort_values("cagr_pct", ascending=False).iloc[0]
    print(f"  Best in-sample (2023-24): Z<{best_is.z_entry}, {best_is.atr_mult}xATR "
          f"-> CAGR {best_is.cagr_pct:.1f}%, Sharpe {best_is.sharpe:.2f}")
    rows = []
    for label, z, a in [
        (f"In-sample optimum (Z<{best_is.z_entry}, {best_is.atr_mult}xATR)",
         best_is.z_entry, best_is.atr_mult),
        ("Documented (Z<-1.2, 4.0xATR)", -1.2, 4.0),
    ]:
        cfg = replace(base, z_entry=float(z), atr_mult=float(a))
        r_is = run_backtest(doc_prices, cfg, start=STUDY_START, end=SPLIT)
        r_oos = run_backtest(doc_prices, cfg, start=SPLIT, end=STUDY_END)
        rows.append({
            "params": label,
            "is_cagr_pct": r_is.metrics["cagr_pct"], "is_sharpe": r_is.metrics["sharpe"],
            "is_maxdd_pct": r_is.metrics["max_drawdown_pct"],
            "oos_cagr_pct": r_oos.metrics["cagr_pct"], "oos_sharpe": r_oos.metrics["sharpe"],
            "oos_maxdd_pct": r_oos.metrics["max_drawdown_pct"],
            "decay_pp": r_oos.metrics["cagr_pct"] - r_is.metrics["cagr_pct"],
        })
    bh_is = series_metrics(buy_and_hold(doc_prices, base.start_capital, STUDY_START, SPLIT))
    bh_oos = series_metrics(buy_and_hold(doc_prices, base.start_capital, SPLIT, STUDY_END))
    rows.append({
        "params": "Equal-weight buy & hold",
        "is_cagr_pct": bh_is["cagr_pct"], "is_sharpe": bh_is["sharpe"],
        "is_maxdd_pct": bh_is["max_drawdown_pct"],
        "oos_cagr_pct": bh_oos["cagr_pct"], "oos_sharpe": bh_oos["sharpe"],
        "oos_maxdd_pct": bh_oos["max_drawdown_pct"],
        "decay_pp": bh_oos["cagr_pct"] - bh_is["cagr_pct"],
    })
    wf = pd.DataFrame(rows)
    show(wf)
    save(wf, "08_walk_forward")
    save(fit, "08_walk_forward_insample_grid")
    summary["walk_forward"] = wf.to_dict("records")

    # ── 9. Regime filter ─────────────────────────────────────────────
    banner("9. REGIME FILTER (document section 7 suggests a 200-SMA gate)")
    rows = [metrics_row(baseline, "No regime filter")]
    for sma in (100, 200):
        r = run_backtest(doc_prices, replace(base, regime_sma=sma),
                         start=STUDY_START, end=STUDY_END)
        rows.append(metrics_row(r, f"Own close > {sma}-SMA"))
    spy = bench_prices.get("SPY")
    if spy is not None:
        r = run_backtest(doc_prices, replace(base, regime_sma=200, regime_on="benchmark"),
                         start=STUDY_START, end=STUDY_END, regime_series=spy["Close"])
        rows.append(metrics_row(r, "SPY > 200-SMA"))
    reg = pd.DataFrame(rows)
    show(reg, ["variant", "final_equity", "cagr_pct", "max_drawdown_pct", "sharpe",
               "calmar", "num_lots", "avg_exposure_pct"])
    save(reg, "09_regime_filter")
    summary["regime"] = reg.to_dict("records")

    # ── 10. Robustness ───────────────────────────────────────────────
    banner("10. ROBUSTNESS — commissions and start date")
    comm = sweep(doc_prices, base, {"commission_bps": [0.0, 5.0, 10.0, 25.0, 50.0]},
                 start=STUDY_START, end=STUDY_END)
    show(comm, ["commission_bps", "final_equity", "cagr_pct", "num_lots"])
    save(comm, "10a_commission")

    rows = []
    for s in ["2023-01-03", "2023-07-01", "2024-01-02", "2024-07-01", "2025-01-02"]:
        r = run_backtest(doc_prices, base, start=s, end=STUDY_END)
        b = series_metrics(buy_and_hold(doc_prices, base.start_capital, s, STUDY_END))
        rows.append({
            "start": s, "cagr_pct": r.metrics["cagr_pct"],
            "bh_cagr_pct": b["cagr_pct"],
            "excess_pp": r.metrics["cagr_pct"] - b["cagr_pct"],
            "max_drawdown_pct": r.metrics["max_drawdown_pct"],
            "sharpe": r.metrics["sharpe"], "num_lots": r.metrics["num_lots"],
        })
    starts = pd.DataFrame(rows)
    show(starts)
    save(starts, "10b_start_date")
    summary["robustness"] = {"commission": comm.to_dict("records"),
                             "start_date": starts.to_dict("records")}

    # ── 11. Trade statistics ─────────────────────────────────────────
    banner("11. TRADE-LEVEL STATISTICS (baseline run)")
    tr = baseline.trades.copy()
    print(f"  Lots: {len(tr)}   Win rate: {(tr.return_pct>0).mean()*100:.1f}%")
    print(f"  Avg {tr.return_pct.mean():+.2f}%   Median {tr.return_pct.median():+.2f}%   "
          f"Best {tr.return_pct.max():+.1f}%   Worst {tr.return_pct.min():+.1f}%")
    print(f"  Avg hold {tr.days_held.mean():.0f} calendar days (median {tr.days_held.median():.0f})")
    print(f"  Avg MFE {tr.mfe_pct.mean():+.1f}%   Avg giveback (MFE - realised) "
          f"{(tr.mfe_pct-tr.return_pct).mean():.1f} pp")
    print("\n  Exit reasons:")
    print(tr.exit_reason.value_counts().to_string())
    print("\n  Per ticker:")
    per = tr.groupby("ticker").agg(
        lots=("return_pct", "size"), win_rate=("return_pct", lambda s: (s > 0).mean() * 100),
        avg_pct=("return_pct", "mean"), total_pnl=("pnl", "sum"),
        avg_days=("days_held", "mean"),
    ).round(2).reset_index()
    show(per)
    save(per, "11a_per_ticker")
    save(tr, "11b_trades")
    print("\n  Return distribution (deciles):")
    print(tr.return_pct.describe(percentiles=[.1, .25, .5, .75, .9]).round(2).to_string())
    summary["trades"] = {
        "n": int(len(tr)),
        "win_rate_pct": float((tr.return_pct > 0).mean() * 100),
        "avg_pct": float(tr.return_pct.mean()),
        "median_pct": float(tr.return_pct.median()),
        "best_pct": float(tr.return_pct.max()),
        "worst_pct": float(tr.return_pct.min()),
        "avg_days": float(tr.days_held.mean()),
        "avg_mfe_pct": float(tr.mfe_pct.mean()),
        "avg_giveback_pp": float((tr.mfe_pct - tr.return_pct).mean()),
        "exit_reasons": tr.exit_reason.value_counts().to_dict(),
    }

    # ── save ─────────────────────────────────────────────────────────
    equity = pd.DataFrame({
        "date": baseline.equity.index,
        "strategy": baseline.equity.values,
        "exposure": baseline.exposure.values,
    })
    equity["buy_hold"] = bh.reindex(baseline.equity.index).values
    save(equity, "12_equity_curve")

    out = RESULTS / "summary.json"
    out.write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print(f"\n  -> {out.relative_to(ROOT)}")
    banner("STUDY COMPLETE")
    return summary


if __name__ == "__main__":
    main()
