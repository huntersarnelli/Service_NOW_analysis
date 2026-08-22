"""
Can the Aggressive Dip strategy be improved?

Run:  python studies/run_improvements.py

The main study (run_dip_study.py) concluded that the documented edge is mostly
exposure to three hindsight-selected stocks. This script tests whether anything
can be done about that. Results land in studies/results_improvements/.

Sections
  A  NULL TEST — does the Z signal beat random entries of the same frequency?
  B  Volatility-targeted sizing instead of a flat % of equity
  C  Trail ratchet — trade some upside for less giveback
  D  Cross-sectional momentum universe instead of a fixed one
  E  Best combination vs the baseline and buy & hold
  F  Out-of-sample check on whatever wins
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
    load_prices,
    run_backtest,
    series_metrics,
)

RESULTS = ROOT / "studies" / "results_improvements"
RESULTS.mkdir(parents=True, exist_ok=True)

WARMUP = "2021-09-01"          # 12-1 momentum needs a year before the study starts
START, END = "2023-01-03", "2026-07-31"
SPLIT = "2025-01-01"

DOC = ["META", "NVDA", "NET"]
BROAD = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "INTC", "QCOM", "TXN", "NOW", "PANW", "CRWD", "DDOG", "NET",
    "SNOW", "SHOP", "UBER", "ABNB", "PYPL", "ZS", "MDB", "TEAM", "WDAY", "ANET",
]
N_NULL = 200
CACHE: dict = {}

COLS = ["variant", "final_equity", "cagr_pct", "max_drawdown_pct", "sharpe",
        "calmar", "num_lots", "win_rate_pct", "avg_exposure_pct", "avg_giveback_pct"]


def banner(t):
    print("\n" + "=" * 78); print(t); print("=" * 78)


def row(res, label, bh_cagr=None):
    r = {"variant": label, **{k: res.metrics.get(k) for k in COLS[1:]}}
    if bh_cagr is not None:
        r["bh_cagr_pct"] = bh_cagr
        r["excess_pp"] = r["cagr_pct"] - bh_cagr
    return r


def show(df, cols=None, n=40):
    d = df if cols is None else df[[c for c in cols if c in df.columns]]
    with pd.option_context("display.width", 210, "display.max_columns", 40):
        print(d.head(n).round(2).to_string(index=False))


def save(df, name):
    df.to_csv(RESULTS / f"{name}.csv", index=False)
    print(f"  -> studies/results_improvements/{name}.csv")


def main():
    summary = {}
    base = BacktestConfig()

    print("Downloading…")
    doc_px = load_prices(DOC, WARMUP, END, CACHE)
    broad_px = load_prices(BROAD, WARMUP, END, CACHE)
    print(f"  doc {len(doc_px)}/3, broad {len(broad_px)}/{len(BROAD)}")

    baseline = run_backtest(doc_px, base, start=START, end=END)
    bh = buy_and_hold(doc_px, base.start_capital, START, END)
    bh_cagr = series_metrics(bh)["cagr_pct"]
    print(f"  baseline CAGR {baseline.metrics['cagr_pct']:.1f}%  |  B&H {bh_cagr:.1f}%")

    # ── A. NULL TEST ─────────────────────────────────────────────────
    banner("A. NULL TEST — Z signal vs random entries at the same frequency")
    print(f"  Running {N_NULL} random-entry simulations (same lot count, same sizing,")
    print("  same exit rule — only the entry DATES are randomised)…")
    null = []
    for seed in range(N_NULL):
        r = run_backtest(doc_px, replace(base, random_entry_seed=seed), start=START, end=END)
        null.append({"seed": seed, "cagr_pct": r.metrics["cagr_pct"],
                     "sharpe": r.metrics["sharpe"],
                     "max_drawdown_pct": r.metrics["max_drawdown_pct"],
                     "num_lots": r.metrics["num_lots"]})
    nd = pd.DataFrame(null)
    real = baseline.metrics["cagr_pct"]
    pct = float((nd.cagr_pct < real).mean() * 100)
    pct_sh = float((nd.sharpe < baseline.metrics["sharpe"]).mean() * 100)
    print(f"\n  Real signal CAGR      : {real:.1f}%   Sharpe {baseline.metrics['sharpe']:.2f}")
    print(f"  Random entries (n={N_NULL}):")
    print(f"    mean   {nd.cagr_pct.mean():.1f}%   median {nd.cagr_pct.median():.1f}%")
    print(f"    5th–95th pct  {nd.cagr_pct.quantile(.05):.1f}% – {nd.cagr_pct.quantile(.95):.1f}%")
    print(f"    mean Sharpe {nd.sharpe.mean():.2f}")
    print(f"\n  >>> The real Z signal beats {pct:.0f}% of random entry sets on CAGR")
    print(f"  >>> and {pct_sh:.0f}% on Sharpe.  (50% = the signal adds nothing.)")
    save(nd, "A_null_test")
    summary["null_test"] = {
        "real_cagr": real, "real_sharpe": baseline.metrics["sharpe"],
        "random_mean_cagr": float(nd.cagr_pct.mean()),
        "random_median_cagr": float(nd.cagr_pct.median()),
        "random_p5": float(nd.cagr_pct.quantile(.05)),
        "random_p95": float(nd.cagr_pct.quantile(.95)),
        "percentile_cagr": pct, "percentile_sharpe": pct_sh, "n": N_NULL,
    }

    # ── B. Volatility-targeted sizing ────────────────────────────────
    banner("B. VOLATILITY-TARGETED SIZING (equal risk per lot, not equal dollars)")
    rows = [row(baseline, "Baseline: 20% of equity per lot", bh_cagr)]
    for rf in (0.01, 0.02, 0.03, 0.05):
        cfg = replace(base, sizing_mode="vol_target", risk_frac=rf)
        r = run_backtest(doc_px, cfg, start=START, end=END)
        rows.append(row(r, f"Vol-target, {rf:.0%} equity risked per lot", bh_cagr))
    vt = pd.DataFrame(rows)
    show(vt, COLS + ["excess_pp"])
    save(vt, "B_vol_target")
    summary["vol_target"] = vt.to_dict("records")

    # ── C. Trail ratchet ─────────────────────────────────────────────
    banner("C. TRAIL RATCHET — tighten the stop once a lot is up N x ATR")
    print(f"  Baseline gives back {baseline.metrics['avg_giveback_pct']:.1f}pp of peak gain.\n")
    rows = [row(baseline, "Baseline: flat 4xATR", bh_cagr)]
    for rt, name in [
        (((4, 3.0),), "tighten to 3xATR after +4 ATR"),
        (((4, 2.5), (8, 2.0)), "3-step: 2.5x after +4, 2.0x after +8"),
        (((6, 3.0),), "tighten to 3xATR after +6 ATR"),
        (((8, 2.0),), "tighten to 2xATR after +8 ATR"),
        (((10, 2.5),), "tighten to 2.5xATR after +10 ATR"),
    ]:
        r = run_backtest(doc_px, replace(base, trail_ratchet=rt), start=START, end=END)
        rows.append(row(r, name, bh_cagr))
    rt_df = pd.DataFrame(rows)
    show(rt_df, COLS + ["excess_pp"])
    save(rt_df, "C_trail_ratchet")
    summary["ratchet"] = rt_df.to_dict("records")

    # ── D. Cross-sectional momentum universe ─────────────────────────
    banner("D. CROSS-SECTIONAL UNIVERSE — buy dips only in current momentum leaders")
    print(f"  Broad basket of {len(broad_px)} names; rank by 12-1 momentum each bar.\n")
    broad_bh = series_metrics(buy_and_hold(broad_px, base.start_capital, START, END))["cagr_pct"]
    rows = [
        row(baseline, "Fixed 3-name universe (documented)", bh_cagr),
        {"variant": f"Broad basket, no momentum gate", **{
            k: run_backtest(broad_px, base, start=START, end=END).metrics.get(k)
            for k in COLS[1:]}, "bh_cagr_pct": broad_bh},
    ]
    rows[1]["excess_pp"] = rows[1]["cagr_pct"] - broad_bh
    for n in (3, 5, 8, 10, 15):
        cfg = replace(base, momentum_top_n=n)
        r = run_backtest(broad_px, cfg, start=START, end=END)
        rr = row(r, f"Broad basket, top {n} by 12-1 momentum", broad_bh)
        rows.append(rr)
    mom = pd.DataFrame(rows)
    show(mom, COLS + ["bh_cagr_pct", "excess_pp"])
    print(f"\n  Equal-weight buy & hold of the whole {len(broad_px)}-name basket: {broad_bh:.1f}% CAGR")
    save(mom, "D_momentum_universe")
    summary["momentum"] = mom.to_dict("records")

    # ── E. Combination ───────────────────────────────────────────────
    banner("E. COMBINING WHAT WORKED")
    best_n = int(mom[mom.variant.str.contains("top ")].sort_values("sharpe").iloc[-1].variant.split("top ")[1].split()[0])
    print(f"  Using top {best_n} momentum names (best Sharpe in section D).\n")
    combos = [
        ("Documented baseline (fixed 3 names)", doc_px, base),
        ("Buy & hold, fixed 3 names", None, None),
        (f"Momentum top {best_n}", broad_px, replace(base, momentum_top_n=best_n)),
        (f"Momentum top {best_n} + vol-target 2%", broad_px,
         replace(base, momentum_top_n=best_n, sizing_mode="vol_target", risk_frac=0.02)),
        (f"Momentum top {best_n} + ratchet",  broad_px,
         replace(base, momentum_top_n=best_n, trail_ratchet=((4, 2.5), (8, 2.0)))),
        (f"Momentum top {best_n} + vol-target + ratchet", broad_px,
         replace(base, momentum_top_n=best_n, sizing_mode="vol_target", risk_frac=0.02,
                 trail_ratchet=((4, 2.5), (8, 2.0)))),
        ("Buy & hold, broad basket", None, None),
    ]
    rows = []
    for name, px, cfg in combos:
        if cfg is None:
            s = bh if "fixed 3" in name else buy_and_hold(broad_px, base.start_capital, START, END)
            m = series_metrics(s)
            rows.append({"variant": name, **{k: m.get(k) for k in COLS[1:]}})
        else:
            r = run_backtest(px, cfg, start=START, end=END)
            rows.append(row(r, name))
    comb = pd.DataFrame(rows)
    show(comb, COLS)
    save(comb, "E_combinations")
    summary["combinations"] = comb.to_dict("records")

    # ── F. Out-of-sample ─────────────────────────────────────────────
    banner("F. OUT-OF-SAMPLE (2025-01 -> 2026-07) — does any of it survive?")
    rows = []
    for name, px, cfg in combos:
        if cfg is None:
            src = doc_px if "fixed 3" in name else broad_px
            m_is = series_metrics(buy_and_hold(src, base.start_capital, START, SPLIT))
            m_oos = series_metrics(buy_and_hold(src, base.start_capital, SPLIT, END))
        else:
            m_is = run_backtest(px, cfg, start=START, end=SPLIT).metrics
            m_oos = run_backtest(px, cfg, start=SPLIT, end=END).metrics
        rows.append({
            "variant": name,
            "is_cagr": m_is["cagr_pct"], "is_sharpe": m_is["sharpe"],
            "oos_cagr": m_oos["cagr_pct"], "oos_sharpe": m_oos["sharpe"],
            "oos_maxdd": m_oos["max_drawdown_pct"],
            "decay_pp": m_oos["cagr_pct"] - m_is["cagr_pct"],
        })
    oos = pd.DataFrame(rows).sort_values("oos_sharpe", ascending=False)
    show(oos)
    save(oos, "F_out_of_sample")
    summary["out_of_sample"] = oos.to_dict("records")

    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print(f"\n  -> studies/results_improvements/summary.json")
    banner("DONE")
    return summary


if __name__ == "__main__":
    main()
