"""
Regime, stability and robustness study — the questions left open by
run_dip_study.py and run_improvements.py.

Run:  python studies/run_regime_study.py

Results -> studies/results/03_regime/

Why this exists
---------------
The documented backtest window starts 2023-01-03. In the calendar year
immediately before it, META fell 64.5%, NET 64.2% and NVDA 51.4%. The strategy
has therefore never been tested through a bear market in its own universe — its
entire track record begins at a generational low. All three names have data back
to September 2019, so that test is available and simply was not run.

Sections
  A  Extended history 2020-2026 — COVID crash, 2021 mania, 2022 bear, recovery
  B  Calendar-year breakdown vs buy & hold
  C  The 2022 bear market in isolation
  D  Rolling walk-forward — re-optimise every window, measure out-of-sample
  E  Block bootstrap — is the excess return over buy & hold distinguishable from 0?
  F  Core + dip-add hybrid
  G  Verdict table
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
    sweep,
)

RESULTS = ROOT / "studies" / "results" / "03_regime"
RESULTS.mkdir(parents=True, exist_ok=True)

UNIVERSE = ["META", "NVDA", "NET"]
WARMUP = "2019-09-13"          # NET's first bar
FULL_START, FULL_END = "2020-01-02", "2026-07-31"
DOC_START = "2023-01-03"       # where the strategy document begins
CACHE: dict = {}

COLS = ["variant", "final_equity", "cagr_pct", "max_drawdown_pct", "sharpe",
        "calmar", "num_lots", "win_rate_pct", "avg_exposure_pct"]


def banner(t):
    print("\n" + "=" * 80); print(t); print("=" * 80)


def show(df, cols=None, n=50):
    d = df if cols is None else df[[c for c in cols if c in df.columns]]
    with pd.option_context("display.width", 215, "display.max_columns", 40):
        print(d.head(n).round(2).to_string(index=False))


def save(df, name):
    df.to_csv(RESULTS / f"{name}.csv", index=False)
    print(f"  -> studies/results/03_regime/{name}.csv")


def row(res, label):
    return {"variant": label, **{k: res.metrics.get(k) for k in COLS[1:]}}


def bh_row(series, label):
    m = series_metrics(series)
    return {"variant": label, **{k: m.get(k) for k in COLS[1:]}}


def ann(series: pd.Series) -> float:
    """Annualised return of an equity series."""
    yrs = max((series.index[-1] - series.index[0]).days / 365.25, 1e-9)
    return ((series.iloc[-1] / series.iloc[0]) ** (1 / yrs) - 1) * 100


def main():
    summary = {}
    base = BacktestConfig()

    print("Downloading 2019-2026 history…")
    px = load_prices(UNIVERSE, WARMUP, FULL_END, CACHE)
    print(f"  {len(px)}/{len(UNIVERSE)} names, first common bar "
          f"{max(d.index[0] for d in px.values()).date()}")

    # ── A. Extended history ──────────────────────────────────────────
    banner("A. EXTENDED HISTORY — 2020-2026 vs the documented 2023-2026 window")
    rows = []
    for label, start in [("Documented window (2023-01 -> 2026-07)", DOC_START),
                         ("Full history (2020-01 -> 2026-07)", FULL_START)]:
        r = run_backtest(px, base, start=start, end=FULL_END)
        b = buy_and_hold(px, base.start_capital, start, FULL_END)
        rr = row(r, f"Strategy — {label}")
        rr["bh_cagr_pct"] = series_metrics(b)["cagr_pct"]
        rr["bh_maxdd_pct"] = series_metrics(b)["max_drawdown_pct"]
        rr["bh_sharpe"] = series_metrics(b)["sharpe"]
        rr["excess_pp"] = rr["cagr_pct"] - rr["bh_cagr_pct"]
        rows.append(rr)
    ext = pd.DataFrame(rows)
    show(ext, COLS + ["bh_cagr_pct", "bh_sharpe", "excess_pp"])
    save(ext, "A_extended_history")
    summary["extended"] = ext.to_dict("records")

    # ── B. Year by year ──────────────────────────────────────────────
    banner("B. CALENDAR-YEAR BREAKDOWN (one continuous run from 2020)")
    full = run_backtest(px, base, start=FULL_START, end=FULL_END)
    bh_full = buy_and_hold(px, base.start_capital, FULL_START, FULL_END)
    eq, bhs = full.equity, bh_full.reindex(full.equity.index).ffill()

    rows = []
    for yr, grp in eq.groupby(eq.index.year):
        b = bhs.loc[grp.index]
        s_ret = (grp.iloc[-1] / grp.iloc[0] - 1) * 100
        b_ret = (b.iloc[-1] / b.iloc[0] - 1) * 100
        expo = full.exposure.loc[grp.index]
        dd = (grp / grp.cummax() - 1).min() * 100
        rows.append({
            "year": yr, "strategy_pct": s_ret, "buy_hold_pct": b_ret,
            "excess_pp": s_ret - b_ret, "strat_maxdd_pct": dd,
            "avg_exposure_pct": expo.mean() * 100,
            "lots_opened": int(((full.trades.entry_date.dt.year == yr).sum())),
        })
    yrs = pd.DataFrame(rows)
    show(yrs)
    won = int((yrs.excess_pp > 0).sum())
    print(f"\n  Strategy beat buy & hold in {won}/{len(yrs)} calendar years")
    print(f"  Mean excess {yrs.excess_pp.mean():+.1f}pp   Median {yrs.excess_pp.median():+.1f}pp")
    save(yrs, "B_calendar_years")
    summary["years"] = yrs.to_dict("records")

    # ── C. The 2022 bear in isolation ────────────────────────────────
    banner("C. THE 2022 BEAR MARKET IN ISOLATION")
    print("  META -64.5% | NET -64.2% | NVDA -51.4% over calendar 2022.\n")
    rows = []
    for label, s, e in [("2022 bear (2022-01-03 -> 2022-12-30)", "2022-01-03", "2022-12-30"),
                        ("Peak-to-trough (2021-11-19 -> 2022-12-30)", "2021-11-19", "2022-12-30"),
                        ("Bear + recovery (2022-01-03 -> 2023-12-29)", "2022-01-03", "2023-12-29")]:
        r = run_backtest(px, base, start=s, end=e)
        b = buy_and_hold(px, base.start_capital, s, e)
        m = series_metrics(b)
        rows.append({
            "period": label,
            "strategy_final": r.equity.iloc[-1],
            "strategy_ret_pct": (r.equity.iloc[-1] / base.start_capital - 1) * 100,
            "strategy_maxdd_pct": r.metrics["max_drawdown_pct"],
            "bh_final": b.iloc[-1],
            "bh_ret_pct": (b.iloc[-1] / base.start_capital - 1) * 100,
            "bh_maxdd_pct": m["max_drawdown_pct"],
            "excess_pp": (r.equity.iloc[-1] / base.start_capital - 1) * 100 - (b.iloc[-1] / base.start_capital - 1) * 100,
            "num_lots": r.metrics["num_lots"],
            "win_rate_pct": r.metrics["win_rate_pct"],
            "avg_exposure_pct": r.metrics["avg_exposure_pct"],
        })
    bear = pd.DataFrame(rows)
    show(bear)
    save(bear, "C_bear_market")
    summary["bear"] = bear.to_dict("records")

    # ── D. Rolling walk-forward ──────────────────────────────────────
    banner("D. ROLLING WALK-FORWARD — 24m fit / 12m test, stepped 6m")
    grid = {"z_entry": [-2.0, -1.5, -1.2, -1.0, -0.8],
            "atr_mult": [2.0, 3.0, 4.0, 5.0, 6.0]}
    windows = []
    cur = pd.Timestamp(FULL_START)
    end_ts = pd.Timestamp(FULL_END)
    while cur + pd.DateOffset(months=36) <= end_ts:
        is_s, is_e = cur, cur + pd.DateOffset(months=24)
        oos_s, oos_e = is_e, min(is_e + pd.DateOffset(months=12), end_ts)
        windows.append((is_s, is_e, oos_s, oos_e))
        cur = cur + pd.DateOffset(months=6)

    rows = []
    for is_s, is_e, oos_s, oos_e in windows:
        g = sweep(px, base, grid, start=str(is_s.date()), end=str(is_e.date()))
        g = g.dropna(subset=["cagr_pct"])
        if g.empty:
            continue
        best = g.sort_values("sharpe", ascending=False).iloc[0]
        cfg_opt = replace(base, z_entry=float(best.z_entry), atr_mult=float(best.atr_mult))
        r_opt = run_backtest(px, cfg_opt, start=str(oos_s.date()), end=str(oos_e.date()))
        r_doc = run_backtest(px, base, start=str(oos_s.date()), end=str(oos_e.date()))
        b = buy_and_hold(px, base.start_capital, str(oos_s.date()), str(oos_e.date()))
        rows.append({
            "oos_start": oos_s.date(), "oos_end": oos_e.date(),
            "fit_z": best.z_entry, "fit_atr": best.atr_mult,
            "reopt_cagr": r_opt.metrics["cagr_pct"],
            "doc_cagr": r_doc.metrics["cagr_pct"],
            "bh_cagr": series_metrics(b)["cagr_pct"],
            "reopt_vs_bh": r_opt.metrics["cagr_pct"] - series_metrics(b)["cagr_pct"],
            "doc_vs_bh": r_doc.metrics["cagr_pct"] - series_metrics(b)["cagr_pct"],
            "reopt_sharpe": r_opt.metrics["sharpe"],
            "doc_sharpe": r_doc.metrics["sharpe"],
            "bh_sharpe": series_metrics(b)["sharpe"],
        })
    wf = pd.DataFrame(rows)
    show(wf)
    print(f"\n  Windows: {len(wf)}")
    print(f"  Re-optimised beat buy & hold in {int((wf.reopt_vs_bh>0).sum())}/{len(wf)} "
          f"(mean {wf.reopt_vs_bh.mean():+.1f}pp)")
    print(f"  Fixed doc params beat buy & hold in {int((wf.doc_vs_bh>0).sum())}/{len(wf)} "
          f"(mean {wf.doc_vs_bh.mean():+.1f}pp)")
    print(f"  Re-optimising vs just using the documented params: "
          f"{(wf.reopt_cagr - wf.doc_cagr).mean():+.1f}pp mean")
    print(f"  Chosen params per window: {sorted(set(zip(wf.fit_z, wf.fit_atr)))}")
    save(wf, "D_rolling_walk_forward")
    summary["rolling_wf"] = {
        "n_windows": int(len(wf)),
        "reopt_beat_bh": int((wf.reopt_vs_bh > 0).sum()),
        "doc_beat_bh": int((wf.doc_vs_bh > 0).sum()),
        "reopt_mean_excess": float(wf.reopt_vs_bh.mean()),
        "doc_mean_excess": float(wf.doc_vs_bh.mean()),
        "reopt_minus_doc": float((wf.reopt_cagr - wf.doc_cagr).mean()),
    }

    # ── E. Block bootstrap on the excess return ──────────────────────
    banner("E. BLOCK BOOTSTRAP — is the excess over buy & hold distinguishable from zero?")
    s_ret = full.equity.pct_change().dropna()
    b_ret = bhs.pct_change().dropna()
    common = s_ret.index.intersection(b_ret.index)
    s_ret, b_ret = s_ret.loc[common].to_numpy(), b_ret.loc[common].to_numpy()
    n, block, n_boot = len(s_ret), 21, 5000
    rng = np.random.default_rng(0)
    n_blocks = int(np.ceil(n / block))
    yrs_span = n / 252.0
    diffs = np.empty(n_boot)
    for k in range(n_boot):
        starts = rng.integers(0, n - block, size=n_blocks)
        idx = np.concatenate([np.arange(st, st + block) for st in starts])[:n]
        sc = np.prod(1 + s_ret[idx]) ** (1 / yrs_span) - 1
        bc = np.prod(1 + b_ret[idx]) ** (1 / yrs_span) - 1
        diffs[k] = (sc - bc) * 100
    obs = ann(full.equity) - ann(bhs)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    p_neg = float((diffs <= 0).mean())
    print(f"  Observed excess CAGR (2020-2026)   : {obs:+.2f} pp")
    print(f"  Bootstrap mean                     : {diffs.mean():+.2f} pp")
    print(f"  95% confidence interval            : [{lo:+.2f}, {hi:+.2f}] pp")
    print(f"  P(excess <= 0)                     : {p_neg:.3f}")
    print(f"  {'>>> CI contains zero — the edge is NOT statistically distinguishable from zero.' if lo <= 0 <= hi else '>>> CI excludes zero.'}")
    boot = pd.DataFrame({"excess_pp": diffs})
    save(boot.describe(percentiles=[.025, .05, .5, .95, .975]).T.reset_index(), "E_bootstrap_summary")
    summary["bootstrap"] = {
        "observed_excess_pp": float(obs), "mean": float(diffs.mean()),
        "ci_low": float(lo), "ci_high": float(hi), "p_le_zero": p_neg,
        "n_boot": n_boot, "block": block,
    }

    # ── F. Core + dip hybrid ─────────────────────────────────────────
    banner("F. CORE + DIP-ADD HYBRID (full history 2020-2026)")
    print("  Hold X% permanently, deploy the rest into dip lots that trail out.\n")
    rows = [bh_row(bh_full, "100% buy & hold (no dip lots)")]
    for cw in (0.0, 0.25, 0.50, 0.60, 0.75):
        r = run_backtest(px, replace(base, core_weight=cw), start=FULL_START, end=FULL_END)
        rows.append(row(r, f"Core {cw:.0%} + dip lots"))
    core = pd.DataFrame(rows)
    core["excess_pp"] = core["cagr_pct"] - series_metrics(bh_full)["cagr_pct"]
    show(core, COLS + ["excess_pp"])
    save(core, "F_core_hybrid")
    summary["core"] = core.to_dict("records")

    # same, restricted to the bear year, to see if the core protects or hurts
    print("\n  Same variants through calendar 2022 only:")
    rows = [bh_row(buy_and_hold(px, base.start_capital, "2022-01-03", "2022-12-30"), "100% buy & hold")]
    for cw in (0.0, 0.25, 0.50, 0.60, 0.75):
        r = run_backtest(px, replace(base, core_weight=cw), start="2022-01-03", end="2022-12-30")
        rows.append(row(r, f"Core {cw:.0%} + dip lots"))
    core22 = pd.DataFrame(rows)
    core22["return_pct"] = (core22["final_equity"] / base.start_capital - 1) * 100
    show(core22, ["variant", "final_equity", "return_pct", "max_drawdown_pct", "num_lots", "avg_exposure_pct"])
    save(core22, "F_core_hybrid_2022")
    summary["core_2022"] = core22.to_dict("records")

    # ── G. Verdict ───────────────────────────────────────────────────
    banner("G. VERDICT")
    doc_row = ext.iloc[0]; full_row = ext.iloc[1]
    print(f"  Documented window 2023-2026 : strategy {doc_row.cagr_pct:.1f}% vs B&H {doc_row.bh_cagr_pct:.1f}%  ({doc_row.excess_pp:+.1f}pp)")
    print(f"  Full history      2020-2026 : strategy {full_row.cagr_pct:.1f}% vs B&H {full_row.bh_cagr_pct:.1f}%  ({full_row.excess_pp:+.1f}pp)")
    print(f"  Calendar years won          : {won}/{len(yrs)}")
    print(f"  Rolling WF windows won      : {int((wf.doc_vs_bh>0).sum())}/{len(wf)}")
    print(f"  Bootstrap 95% CI on excess  : [{lo:+.2f}, {hi:+.2f}] pp")

    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print(f"\n  -> studies/results/03_regime/summary.json")
    banner("DONE")
    return summary


if __name__ == "__main__":
    main()
