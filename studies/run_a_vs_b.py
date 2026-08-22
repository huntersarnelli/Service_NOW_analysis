"""
Strategy A vs Strategy B — head to head, on equal terms.

Run:  python studies/run_a_vs_b.py   -> studies/results/06_a_vs_b/

Why this exists
---------------
Strategy B was put through a full gauntlet: baseline reproduction, a 49-cell
parameter surface, a 29-name selection-bias test, rolling walk-forward, a
bootstrap and a regime study. Strategy A was never given the same treatment —
the case against it rested on the original single-name notebooks, a synthetic
fixture, and one config comparison. Recommending that A be scrapped on that basis
would be asserting more than the evidence supports.

There are also untested arguments FOR A:
  - it exits faster, so it may protect better in a bear market
  - a ~64-70% win rate is far easier to actually run than B's ~45%
  - in a range-bound regime, mean reversion should beat trend following
  - short holds mean less overnight/gap exposure

Both strategies are run through the same portfolio engine, on the same universe,
with the same sizing and pyramiding, so the only thing that differs is the rule
being tested.

Sections
  1  Head to head across all three defensible windows
  2  2x2 decomposition — which component actually matters, entry or exit?
  3  Calendar year by year
  4  The 2022 bear market — does A's fast exit protect better?
  5  Selection-bias basket — does A generalise better than B?
  6  Are they complementary? Correlation and blends
  7  Verdict
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

RESULTS = ROOT / "studies" / "results" / "06_a_vs_b"
RESULTS.mkdir(parents=True, exist_ok=True)

TRIO = ["META", "NVDA", "NET"]
BASKET = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "INTC", "QCOM", "TXN", "NOW", "PANW", "CRWD", "DDOG", "NET",
    "SNOW", "SHOP", "UBER", "ABNB", "PYPL", "ZS", "MDB", "TEAM", "WDAY", "ANET",
]
WARMUP, END = "2019-09-13", "2026-07-31"
WINDOWS = {
    "2020+ (all history)": "2020-01-02",
    "2022+ (post-pandemic, incl. bear)": "2022-01-03",
    "2023+ (documented)": "2023-01-03",
}
CACHE: dict = {}

BASE = BacktestConfig()
# Strategy A: Z<-1.5, trail = Close - 2xATR raise-only (ATR re-read daily),
#             exit on trail hit OR Z > 0.
SPEC_A = replace(BASE, z_entry=-1.5, atr_mult=2.0,
                 mean_reversion_exit=True, z_exit=0.0, trail_mode="daily_close")
# Strategy B: Z<-1.2, trail = highest close - 4xATR (frozen), no mean exit.
SPEC_B = replace(BASE, z_entry=-1.2, atr_mult=4.0,
                 mean_reversion_exit=False, trail_mode="frozen_high")

COLS = ["cagr_pct", "max_drawdown_pct", "sharpe", "sortino", "calmar",
        "num_lots", "win_rate_pct", "avg_days_held", "avg_exposure_pct"]


def banner(t):
    print("\n" + "=" * 84); print(t); print("=" * 84)


def show(df, cols=None, n=60):
    d = df if cols is None else df[[c for c in cols if c in df.columns]]
    with pd.option_context("display.width", 225, "display.max_columns", 40):
        print(d.head(n).round(2).to_string(index=False))


def save(df, name):
    df.to_csv(RESULTS / f"{name}.csv", index=False)
    print(f"  -> studies/results/06_a_vs_b/{name}.csv")


def main():
    summary = {}
    print("Downloading…")
    trio = load_prices(TRIO, WARMUP, END, CACHE)
    basket = load_prices(BASKET, WARMUP, END, CACHE)
    print(f"  trio {len(trio)}/3, basket {len(basket)}/{len(BASKET)}")

    # ── 1. Head to head ──────────────────────────────────────────────
    banner("1. HEAD TO HEAD — same universe, same 20% sizing, only the rules differ")
    rows = []
    for wlabel, start in WINDOWS.items():
        bh = series_metrics(buy_and_hold(trio, BASE.start_capital, start, END))
        for name, cfg in (("A — mean-reversion exit", SPEC_A), ("B — trail only", SPEC_B)):
            r = run_backtest(trio, cfg, start=start, end=END)
            rows.append({"window": wlabel, "strategy": name,
                         **{k: r.metrics.get(k) for k in COLS},
                         "excess_vs_bh_pp": r.metrics["cagr_pct"] - bh["cagr_pct"]})
        rows.append({"window": wlabel, "strategy": "Buy & hold",
                     **{k: bh.get(k) for k in COLS}, "excess_vs_bh_pp": 0.0})
    h2h = pd.DataFrame(rows)
    for w in WINDOWS:
        print(f"\n  {w}")
        show(h2h[h2h.window == w], ["strategy"] + COLS + ["excess_vs_bh_pp"])
    save(h2h, "1_head_to_head")
    summary["head_to_head"] = h2h.to_dict("records")

    # ── 2. 2x2 decomposition ─────────────────────────────────────────
    banner("2. WHICH COMPONENT MATTERS — entry threshold x exit rule (2022+)")
    START = WINDOWS["2022+ (post-pandemic, incl. bear)"]
    rows = []
    for z, zl in ((-1.5, "A entry Z<-1.5"), (-1.2, "B entry Z<-1.2")):
        for exit_name, ex in (
            ("A exit (2xATR daily + Z>0)",
             dict(atr_mult=2.0, mean_reversion_exit=True, z_exit=0.0, trail_mode="daily_close")),
            ("B exit (4xATR frozen, no mean exit)",
             dict(atr_mult=4.0, mean_reversion_exit=False, trail_mode="frozen_high")),
        ):
            cfg = replace(BASE, z_entry=z, **ex)
            r = run_backtest(trio, cfg, start=START, end=END)
            rows.append({"entry": zl, "exit": exit_name,
                         **{k: r.metrics.get(k) for k in COLS}})
    dec = pd.DataFrame(rows)
    show(dec, ["entry", "exit"] + COLS)
    piv = dec.pivot(index="entry", columns="exit", values="cagr_pct").round(1)
    print("\n  CAGR % by entry (rows) x exit (cols):")
    print(piv.to_string())
    ent_eff = dec.groupby("entry").cagr_pct.mean()
    exit_eff = dec.groupby("exit").cagr_pct.mean()
    print(f"\n  Average effect of the ENTRY threshold: "
          f"{abs(ent_eff.iloc[0] - ent_eff.iloc[1]):.1f}pp spread")
    print(f"  Average effect of the EXIT rule       : "
          f"{abs(exit_eff.iloc[0] - exit_eff.iloc[1]):.1f}pp spread")
    save(dec, "2_decomposition")
    summary["decomposition"] = {
        "rows": dec.to_dict("records"),
        "entry_spread_pp": float(abs(ent_eff.iloc[0] - ent_eff.iloc[1])),
        "exit_spread_pp": float(abs(exit_eff.iloc[0] - exit_eff.iloc[1])),
    }

    # ── 3. Year by year ──────────────────────────────────────────────
    banner("3. CALENDAR YEAR BY YEAR (continuous run from 2020)")
    ra = run_backtest(trio, SPEC_A, start=WINDOWS["2020+ (all history)"], end=END)
    rb = run_backtest(trio, SPEC_B, start=WINDOWS["2020+ (all history)"], end=END)
    bhs = buy_and_hold(trio, BASE.start_capital, WINDOWS["2020+ (all history)"], END)
    idx = ra.equity.index
    bhs = bhs.reindex(idx).ffill()
    rows = []
    for yr in sorted(set(idx.year)):
        m = idx.year == yr
        a, b, h = ra.equity[m], rb.equity[m], bhs[m]
        rows.append({
            "year": yr,
            "A_pct": (a.iloc[-1] / a.iloc[0] - 1) * 100,
            "B_pct": (b.iloc[-1] / b.iloc[0] - 1) * 100,
            "bh_pct": (h.iloc[-1] / h.iloc[0] - 1) * 100,
            "A_maxdd": (a / a.cummax() - 1).min() * 100,
            "B_maxdd": (b / b.cummax() - 1).min() * 100,
            "A_exposure": ra.exposure[m].mean() * 100,
            "B_exposure": rb.exposure[m].mean() * 100,
        })
    yrs = pd.DataFrame(rows)
    yrs["A_vs_B_pp"] = yrs.A_pct - yrs.B_pct
    show(yrs)
    print(f"\n  A beat B in {int((yrs.A_vs_B_pp > 0).sum())}/{len(yrs)} calendar years")
    print(f"  A beat buy & hold in {int((yrs.A_pct > yrs.bh_pct).sum())}/{len(yrs)}; "
          f"B in {int((yrs.B_pct > yrs.bh_pct).sum())}/{len(yrs)}")
    save(yrs, "3_calendar_years")
    summary["years"] = yrs.to_dict("records")

    # ── 4. The bear market ───────────────────────────────────────────
    banner("4. THE 2022 BEAR — does A's fast exit protect better than B's wide trail?")
    rows = []
    for label, s, e in (("Calendar 2022", "2022-01-03", "2022-12-30"),
                        ("Peak to trough 2021-11 -> 2022-12", "2021-11-19", "2022-12-30")):
        bh = buy_and_hold(trio, BASE.start_capital, s, e)
        for name, cfg in (("A", SPEC_A), ("B", SPEC_B)):
            r = run_backtest(trio, cfg, start=s, end=e)
            rows.append({
                "period": label, "strategy": name,
                "return_pct": (r.equity.iloc[-1] / BASE.start_capital - 1) * 100,
                "max_drawdown_pct": r.metrics["max_drawdown_pct"],
                "avg_exposure_pct": r.metrics["avg_exposure_pct"],
                "num_lots": r.metrics["num_lots"],
                "win_rate_pct": r.metrics["win_rate_pct"],
            })
        rows.append({
            "period": label, "strategy": "Buy & hold",
            "return_pct": (bh.iloc[-1] / BASE.start_capital - 1) * 100,
            "max_drawdown_pct": series_metrics(bh)["max_drawdown_pct"],
            "avg_exposure_pct": 100.0, "num_lots": 0, "win_rate_pct": 0.0,
        })
    bear = pd.DataFrame(rows)
    show(bear)
    save(bear, "4_bear_market")
    summary["bear"] = bear.to_dict("records")

    # ── 5. Generalisation ────────────────────────────────────────────
    banner("5. SELECTION-BIAS BASKET — which rule set generalises better? (2022+)")
    rows = []
    for t, df in basket.items():
        if len(df) < 400:
            continue
        try:
            bh = series_metrics(buy_and_hold({t: df}, BASE.start_capital, START, END))
            ra_ = run_backtest({t: df}, SPEC_A, start=START, end=END)
            rb_ = run_backtest({t: df}, SPEC_B, start=START, end=END)
        except Exception:
            continue
        rows.append({
            "ticker": t, "bh_cagr": bh["cagr_pct"],
            "A_cagr": ra_.metrics["cagr_pct"], "B_cagr": rb_.metrics["cagr_pct"],
            "A_excess": ra_.metrics["cagr_pct"] - bh["cagr_pct"],
            "B_excess": rb_.metrics["cagr_pct"] - bh["cagr_pct"],
            "A_sharpe": ra_.metrics["sharpe"], "B_sharpe": rb_.metrics["sharpe"],
            "A_maxdd": ra_.metrics["max_drawdown_pct"], "B_maxdd": rb_.metrics["max_drawdown_pct"],
        })
    gen = pd.DataFrame(rows).sort_values("B_excess", ascending=False)
    show(gen, ["ticker", "bh_cagr", "A_cagr", "B_cagr", "A_excess", "B_excess",
               "A_sharpe", "B_sharpe"], n=40)
    n = len(gen)
    print(f"\n  Names beating buy & hold:  A {int((gen.A_excess>0).sum())}/{n}   "
          f"B {int((gen.B_excess>0).sum())}/{n}")
    print(f"  Median excess CAGR:        A {gen.A_excess.median():+.1f}pp   "
          f"B {gen.B_excess.median():+.1f}pp")
    print(f"  Mean Sharpe:               A {gen.A_sharpe.mean():.2f}   B {gen.B_sharpe.mean():.2f}")
    print(f"  Mean max drawdown:         A {gen.A_maxdd.mean():.1f}%   B {gen.B_maxdd.mean():.1f}%")
    print(f"  A beat B on:               {int((gen.A_cagr>gen.B_cagr).sum())}/{n} names")
    save(gen, "5_generalisation")
    summary["generalisation"] = {
        "n": n,
        "A_beat_bh": int((gen.A_excess > 0).sum()), "B_beat_bh": int((gen.B_excess > 0).sum()),
        "A_median_excess": float(gen.A_excess.median()), "B_median_excess": float(gen.B_excess.median()),
        "A_mean_sharpe": float(gen.A_sharpe.mean()), "B_mean_sharpe": float(gen.B_sharpe.mean()),
        "A_mean_maxdd": float(gen.A_maxdd.mean()), "B_mean_maxdd": float(gen.B_maxdd.mean()),
        "A_beat_B": int((gen.A_cagr > gen.B_cagr).sum()),
    }

    # ── 6. Complementary? ────────────────────────────────────────────
    banner("6. ARE THEY COMPLEMENTARY? (2022+)")
    a = run_backtest(trio, SPEC_A, start=START, end=END).equity
    b = run_backtest(trio, SPEC_B, start=START, end=END).equity
    idx = a.index.intersection(b.index)
    corr = a.reindex(idx).pct_change().corr(b.reindex(idx).pct_change())
    print(f"  Correlation of daily returns: {corr:.3f}")
    rows = []
    for w in (0.0, 0.25, 0.50, 0.75, 1.0):
        ra_, rb_ = a.reindex(idx).pct_change().fillna(0), b.reindex(idx).pct_change().fillna(0)
        blended = (100_000 * (1 + w * ra_ + (1 - w) * rb_).cumprod())
        m = series_metrics(blended)
        rows.append({"mix": f"{w:.0%} A / {1-w:.0%} B",
                     **{k: m.get(k) for k in ["cagr_pct", "max_drawdown_pct", "sharpe", "calmar"]}})
    mix = pd.DataFrame(rows)
    show(mix)
    best = mix.sort_values("sharpe", ascending=False).iloc[0]
    print(f"\n  Best blend by Sharpe: {best['mix']} (Sharpe {best.sharpe:.2f}, "
          f"CAGR {best.cagr_pct:.1f}%, DD {best.max_drawdown_pct:.1f}%)")
    save(mix, "6_blends")
    summary["blend"] = {"correlation": float(corr), "rows": mix.to_dict("records")}

    # ── 7. Verdict ───────────────────────────────────────────────────
    banner("7. VERDICT")
    for w in WINDOWS:
        sub = h2h[h2h.window == w].set_index("strategy")
        print(f"  {w:<36} A {sub.loc['A — mean-reversion exit','cagr_pct']:6.1f}%  "
              f"B {sub.loc['B — trail only','cagr_pct']:6.1f}%  "
              f"B&H {sub.loc['Buy & hold','cagr_pct']:6.1f}%   |  Sharpe "
              f"A {sub.loc['A — mean-reversion exit','sharpe']:.2f} "
              f"B {sub.loc['B — trail only','sharpe']:.2f} "
              f"B&H {sub.loc['Buy & hold','sharpe']:.2f}")

    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print("\n  -> studies/results/06_a_vs_b/summary.json")
    banner("DONE")
    return summary


if __name__ == "__main__":
    main()
