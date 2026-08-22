"""
Optimisation study — the two structural levers, tested honestly.

Context
-------
STRATEGY_REVIEW.md §5.17 is the constraint every optimisation attempt in this
repo has to respect: re-optimising `z_entry` and `atr_mult` on a rolling
walk-forward was 11.8pp WORSE than freezing them, and the fitted values jumped
from Z<-0.8 to Z<-2.0 and 2xATR to 6xATR between adjacent windows. There is no
stable optimum on those knobs and searching them harder only overfits.

So this study does not tune parameters. It tests two STRUCTURAL changes, each
motivated by a measured finding rather than by a grid search.

LEVER 1 — the time exit
    OVERREACTION_STUDY.md §2 measures the entry signal's excess over random
    entries as +0.16 / +0.34 / +0.40 / -0.00 pp at 5 / 20 / 60 / 120 bars.
    The signal expires. Strategy B holds a lot 83 bars on average and exits on
    a 4xATR trail, so it routinely holds long past the point where the reason
    for entering has stopped paying. Nobody has tested simply leaving at a
    fixed bar count -- §5.13a tightened the trail (worse at every setting) but
    never removed the trail's role in deciding WHEN to leave.

LEVER 2 — conditional sizing
    Every lot is currently a flat 20% of equity. §5.31's profit-take result and
    §7's screen table both show that FILTERING on the event tags destroys the
    sample: the triple screen cut 17,235 events to 786 and lost significance
    entirely. Weighting does not have that problem -- every event is still
    taken, the better-conditioned ones just get more capital.

    The model is deliberately the simplest thing that could work: an OLS fit of
    forward excess return on ex-ante tags, standardised, no interactions, no
    regularisation tuning. It is fit on the FIRST half of the history and
    tested on the SECOND, then the split is reversed. If predicted edge does
    not sort realised edge out-of-sample in both directions, the idea is dead
    and no amount of model sophistication rescues it.

    Features are all observable on the event bar. None of them is derived from
    the name's own realised performance -- that is the §5.7 selection-bias trap.

    python studies/run_optimisation_study.py

Writes studies/results_optimisation/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studies.dip_backtest import BacktestConfig, load_prices as load_bt_prices, run_backtest  # noqa: E402
from studies.overreaction_lib import (  # noqa: E402
    BENCHMARK, UNIVERSE,
    add_indicators, attach_earnings, extract_events, load_earnings,
    load_prices, monthly_tstat,
)

RESULTS = ROOT / "studies" / "results_optimisation"
RESULTS.mkdir(parents=True, exist_ok=True)

WARMUP, START, END = "2014-06-01", "2015-01-01", "2026-08-22"

# Windows carried over from STRATEGY_REVIEW.md so results are comparable
WINDOWS = {
    "2020+": "2020-01-02",
    "2022+": "2022-01-03",
    "2023+": "2023-01-03",
}
TRIO = ["META", "NVDA", "NET"]
BASKET = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "INTC", "QCOM", "TXN", "NOW", "PANW", "CRWD", "DDOG", "NET",
    "SNOW", "SHOP", "UBER", "ABNB", "PYPL", "ZS", "MDB", "TEAM", "WDAY", "INTU",
]

HOLDS = [10, 20, 40, 60, 90, 120, None]

FEATURES = [
    "z", "idio_z", "vol_ratio", "gap_atr", "breadth",
    "days_since_earnings", "rvol20", "log_dollar_vol", "dist_52w",
]

summary: dict = {}


def banner(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def show(df: pd.DataFrame, n: int = 60) -> None:
    with pd.option_context("display.width", 215, "display.max_columns", 40,
                           "display.float_format", lambda v: f"{v:,.2f}"):
        print(df.head(n).to_string(index=False))


def save(df: pd.DataFrame, name: str) -> None:
    p = RESULTS / f"{name}.csv"
    df.to_csv(p, index=False)
    print(f"  -> {p.relative_to(ROOT)}")


# ═════════════════════════════════════════════════════════════
# LEVER 1 — time exit
# ═════════════════════════════════════════════════════════════
def lever_1_time_exit() -> pd.DataFrame:
    banner("LEVER 1 — TIME EXIT: does leaving at a fixed bar count beat the trail?")
    cache: dict = {}
    rows = []

    for uni_name, uni in [("trio", TRIO), ("basket30", BASKET)]:
        prices = load_bt_prices(uni, "2019-06-01", END, cache)
        print(f"\n  {uni_name}: {len(prices)}/{len(uni)} names")

        for win_name, win_start in WINDOWS.items():
            # equal-weight buy & hold on the same names, same window
            bh = run_backtest(
                prices,
                BacktestConfig(z_entry=99, alloc=1.0 / len(prices), core_weight=1.0),
                start=win_start, end=END,
            )
            bh_cagr = bh.metrics["cagr_pct"]

            for hold in HOLDS:
                cfg = BacktestConfig(max_hold_days=hold)
                res = run_backtest(prices, cfg, start=win_start, end=END)
                m = res.metrics
                rows.append({
                    "universe": uni_name,
                    "window": win_name,
                    "max_hold_days": hold if hold is not None else "none (trail only)",
                    "cagr_pct": m["cagr_pct"],
                    "excess_vs_bh_pp": m["cagr_pct"] - bh_cagr,
                    "max_dd_pct": m["max_drawdown_pct"],
                    "sharpe": m["sharpe"],
                    "calmar": m["calmar"],
                    "avg_exposure_pct": m["avg_exposure_pct"],
                    "num_lots": m["num_lots"],
                    "win_rate_pct": m["win_rate_pct"],
                    "avg_days_held": m["avg_days_held"],
                    "bh_cagr_pct": bh_cagr,
                })
            print(f"    {win_name}: swept {len(HOLDS)} holding periods "
                  f"(B&H {bh_cagr:.1f}% CAGR)")

    df = pd.DataFrame(rows)
    for uni_name in ("trio", "basket30"):
        for win_name in WINDOWS:
            part = df[(df.universe == uni_name) & (df.window == win_name)]
            print(f"\n  --- {uni_name} / {win_name} "
                  f"(buy & hold {part.bh_cagr_pct.iloc[0]:.1f}% CAGR) ---")
            show(part[["max_hold_days", "cagr_pct", "excess_vs_bh_pp", "max_dd_pct",
                       "sharpe", "calmar", "avg_exposure_pct", "num_lots",
                       "win_rate_pct", "avg_days_held"]])
    save(df, "1_time_exit_sweep")

    banner("LEVER 1 — VERDICT")
    base = df[df.max_hold_days == "none (trail only)"]
    piv = df.pivot_table(index="max_hold_days", values=["sharpe", "excess_vs_bh_pp"],
                         aggfunc="mean")
    piv = piv.reindex([10, 20, 40, 60, 90, 120, "none (trail only)"])
    print("  Mean across all 6 universe x window combinations:\n")
    show(piv.reset_index())
    best = piv.sharpe.idxmax()
    print(f"\n  Best mean Sharpe: max_hold_days = {best}")
    print(f"  Baseline (trail only) mean Sharpe: {piv.loc['none (trail only)', 'sharpe']:.3f}")

    wins = []
    for uni_name in ("trio", "basket30"):
        for win_name in WINDOWS:
            part = df[(df.universe == uni_name) & (df.window == win_name)]
            b = part[part.max_hold_days == "none (trail only)"].iloc[0]
            for _, r in part[part.max_hold_days != "none (trail only)"].iterrows():
                wins.append({
                    "universe": uni_name, "window": win_name,
                    "max_hold_days": r.max_hold_days,
                    "sharpe_delta": r.sharpe - b.sharpe,
                    "cagr_delta_pp": r.cagr_pct - b.cagr_pct,
                    "dd_delta_pp": r.max_dd_pct - b.max_dd_pct,
                })
    w = pd.DataFrame(wins)
    agg = w.groupby("max_hold_days").agg(
        sharpe_delta_mean=("sharpe_delta", "mean"),
        sharpe_wins=("sharpe_delta", lambda s: int((s > 0).sum())),
        cagr_delta_mean=("cagr_delta_pp", "mean"),
        dd_improved=("dd_delta_pp", lambda s: int((s > 0).sum())),
        n=("sharpe_delta", "size"),
    ).reset_index()
    print("\n  vs the trail-only baseline, per holding period "
          "(wins are out of 6 universe x window combinations):\n")
    show(agg)
    save(agg, "1b_time_exit_verdict")
    summary["time_exit"] = agg.to_dict("records")
    return df


# ═════════════════════════════════════════════════════════════
# LEVER 2 — conditional sizing
# ═════════════════════════════════════════════════════════════
def fit_ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Least squares with an intercept column prepended."""
    A = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    return coef


def predict(coef: np.ndarray, X: np.ndarray) -> np.ndarray:
    return coef[0] + X @ coef[1:]


def lever_2_conditional_sizing(ev: pd.DataFrame, horizon: int = 20) -> pd.DataFrame:
    banner(f"LEVER 2 — CONDITIONAL SIZING: does predicted edge sort realised edge? "
           f"({horizon}d)")

    target = f"exc_{horizon}"
    d = ev.dropna(subset=FEATURES + [target]).copy()
    # cap the earnings distance -- "300 days since the last report" is a data
    # artifact, not a signal, and an uncapped tail dominates a linear fit
    d["days_since_earnings"] = d["days_since_earnings"].clip(upper=90)
    print(f"  {len(d):,} events with complete features")

    mid = d.date.quantile(0.5)
    print(f"  split at {pd.Timestamp(mid).date()}")

    halves = {
        "fit_first_test_second": (d.date <= mid, d.date > mid),
        "fit_second_test_first": (d.date > mid, d.date <= mid),
    }

    coef_rows, quint_rows, port_rows = [], [], []

    for split_name, (fit_mask, test_mask) in halves.items():
        tr, te = d[fit_mask], d[test_mask]

        mu, sd = tr[FEATURES].mean(), tr[FEATURES].std().replace(0, 1.0)
        Xtr = ((tr[FEATURES] - mu) / sd).values
        Xte = ((te[FEATURES] - mu) / sd).values
        coef = fit_ols(Xtr, tr[target].values)

        for name, c in zip(["intercept"] + FEATURES, coef):
            coef_rows.append({"split": split_name, "feature": name, "coef_pp": c})

        te = te.copy()
        te["pred"] = predict(coef, Xte)
        # in-sample R^2, reported only to show how little of the variance any
        # linear model on these tags explains
        r2_is = 1 - np.var(tr[target].values - predict(coef, Xtr)) / np.var(tr[target].values)
        r2_oos = 1 - np.var(te[target].values - te["pred"].values) / np.var(te[target].values)

        te["quintile"] = pd.qcut(te["pred"], 5, labels=[f"Q{i}" for i in range(1, 6)])
        for q, grp in te.groupby("quintile", observed=True):
            st = monthly_tstat(grp, target)
            quint_rows.append({
                "split": split_name, "quintile": str(q), "n": len(grp),
                "mean_pred_pp": grp["pred"].mean(),
                "realised_exc_pp": st["mean"], "t": st["t"],
                "hit_rate_pct": st["hit_rate"],
            })

        # rank correlation between prediction and outcome, out of sample
        rho = te["pred"].corr(te[target], method="spearman")

        # portfolio comparison: every event is taken either way, only the
        # weight differs. Weights are shifted to be non-negative and
        # normalised within each month, so both variants deploy the same
        # capital on the same days.
        te["w_eq"] = 1.0
        raw = te["pred"] - te["pred"].min()
        te["w_pred"] = raw / raw.mean() if raw.mean() > 0 else 1.0

        def wmean(g, wcol):
            w = g[wcol]
            return float((g[target] * w).sum() / w.sum()) if w.sum() > 0 else np.nan

        m_eq = te.groupby("month").apply(wmean, "w_eq", include_groups=False)
        m_pr = te.groupby("month").apply(wmean, "w_pred", include_groups=False)
        joined = pd.concat([m_eq, m_pr], axis=1, keys=["eq", "pred"]).dropna()
        diff = joined["pred"] - joined["eq"]
        se = diff.std(ddof=1) / np.sqrt(len(diff))
        port_rows.append({
            "split": split_name, "n_test": len(te), "n_months": len(joined),
            "r2_in_sample": r2_is, "r2_out_of_sample": r2_oos,
            "spearman_oos": rho,
            "equal_weight_pp": float(joined["eq"].mean()),
            "edge_weight_pp": float(joined["pred"].mean()),
            "improvement_pp": float(diff.mean()),
            "t": float(diff.mean() / se) if se > 0 else np.nan,
        })

    cf = pd.DataFrame(coef_rows)
    print("\n  Fitted coefficients (pp of 20d excess per 1 sd of the feature):")
    show(cf.pivot(index="feature", columns="split", values="coef_pp").reset_index())
    save(cf, f"2_coefficients_{horizon}d")

    qt = pd.DataFrame(quint_rows)
    print("\n  Out-of-sample quintiles of PREDICTED edge "
          "(Q1 = lowest predicted, Q5 = highest):")
    show(qt)
    save(qt, f"2b_oos_quintiles_{horizon}d")

    pt = pd.DataFrame(port_rows)
    print("\n  Portfolio: equal weight vs weight-by-predicted-edge, out of sample:")
    show(pt)
    save(pt, f"2c_oos_portfolio_{horizon}d")

    print("\n  Monotonicity check (does Q5 beat Q1 out of sample?):")
    for split_name in halves:
        part = qt[qt.split == split_name].set_index("quintile")
        q1, q5 = part.loc["Q1", "realised_exc_pp"], part.loc["Q5", "realised_exc_pp"]
        spear = pt[pt.split == split_name].spearman_oos.iloc[0]
        print(f"    {split_name}: Q1 {q1:+.2f}pp  Q5 {q5:+.2f}pp  "
              f"spread {q5 - q1:+.2f}pp  rank-corr {spear:+.4f}")

    summary[f"conditional_sizing_{horizon}d"] = {
        "portfolio": pt.to_dict("records"),
        "quintiles": qt.to_dict("records"),
    }
    return pt


def main() -> None:
    banner("0. DATA")
    prices = load_prices(UNIVERSE + [BENCHMARK], WARMUP, END)
    tickers = [t for t in prices if t != BENCHMARK]
    earnings = load_earnings(tickers)
    spy = prices[BENCHMARK]
    frames = {BENCHMARK: add_indicators(spy, spy)}
    for t in tickers:
        frames[t] = attach_earnings(add_indicators(prices[t], spy), earnings.get(t))
    ev = extract_events(frames, z_entry=-1.2, start=START)
    print(f"  {len(ev):,} events, {ev.ticker.nunique()} names")

    lever_1_time_exit()
    lever_2_conditional_sizing(ev, horizon=20)
    lever_2_conditional_sizing(ev, horizon=60)

    with open(RESULTS / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n  -> {(RESULTS / 'summary.json').relative_to(ROOT)}")
    banner("DONE")


if __name__ == "__main__":
    main()
