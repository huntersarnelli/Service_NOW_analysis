"""
Optimisation study — the risk-tilt control.

Why this exists
---------------
run_optimisation_study.py finds that weighting dip lots by a predicted edge
beats equal weighting out of sample by ~+0.2pp per trade, in both split
directions and at both horizons. Before that gets acted on, one thing has to
be ruled out.

`rvol20` -- the name's own trailing volatility -- carries the largest
coefficient in every fit. If the model is mostly learning "put more money in
the jumpy names," then the improvement is not skill. It is the same finding
docs/01_STRATEGY_REVIEW.md §5.5 already documented: returns scale monotonically with
position size at roughly constant drawdown, because the driver is exposure,
not signal. Dressing a volatility tilt up as a predictive model would be that
mistake with extra steps.

Three variants, same fit/test protocol:

  full       all nine ex-ante features
  vol_only   rvol20 alone
  no_vol     the full feature set MINUS rvol20 and log_dollar_vol
             (log_dollar_vol is a size/liquidity proxy and correlates with
             volatility, so leaving it in would smuggle the tilt back)

If `no_vol` keeps most of the improvement, there is a real conditioning signal
underneath. If the improvement lives entirely in `vol_only`, this is a
volatility tilt and should be judged as one -- on risk-adjusted terms, against
simply sizing up.

Each variant also reports the weighted-average trailing volatility and beta of
the book it produces, so the risk tilt is visible rather than inferred.

    python studies/run_optimisation_control.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studies.overreaction_lib import (  # noqa: E402
    BENCHMARK, UNIVERSE,
    add_indicators, attach_earnings, extract_events, load_earnings, load_prices,
)

RESULTS = ROOT / "studies" / "results" / "09_optimisation"
RESULTS.mkdir(parents=True, exist_ok=True)

WARMUP, START, END = "2014-06-01", "2015-01-01", "2026-08-22"

ALL_FEATURES = [
    "z", "idio_z", "vol_ratio", "gap_atr", "breadth",
    "days_since_earnings", "rvol20", "log_dollar_vol", "dist_52w",
]
VARIANTS = {
    "full": ALL_FEATURES,
    "vol_only": ["rvol20"],
    "no_vol": [f for f in ALL_FEATURES if f not in ("rvol20", "log_dollar_vol")],
}


def banner(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def show(df: pd.DataFrame) -> None:
    with pd.option_context("display.width", 215, "display.max_columns", 40,
                           "display.float_format", lambda v: f"{v:,.3f}"):
        print(df.to_string(index=False))


def fit_ols(X, y):
    A = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    return coef


def evaluate(d: pd.DataFrame, feats: list[str], target: str,
             fit_mask, test_mask, label: str, split: str) -> dict:
    tr, te = d[fit_mask], d[test_mask].copy()
    mu, sd = tr[feats].mean(), tr[feats].std().replace(0, 1.0)
    coef = fit_ols(((tr[feats] - mu) / sd).values, tr[target].values)
    Xte = ((te[feats] - mu) / sd).values
    te["pred"] = coef[0] + Xte @ coef[1:]

    raw = te["pred"] - te["pred"].min()
    te["w"] = raw / raw.mean() if raw.mean() > 0 else 1.0

    def wmean(g, col, wcol=None):
        if wcol is None:
            return float(g[col].mean())
        w = g[wcol]
        return float((g[col] * w).sum() / w.sum()) if w.sum() > 0 else np.nan

    m_eq = te.groupby("month").apply(lambda g: wmean(g, target), include_groups=False)
    m_w = te.groupby("month").apply(lambda g: wmean(g, target, "w"), include_groups=False)
    j = pd.concat([m_eq, m_w], axis=1, keys=["eq", "w"]).dropna()
    diff = j["w"] - j["eq"]
    se = diff.std(ddof=1) / np.sqrt(len(diff)) if len(diff) > 1 else np.nan

    # the risk tilt, made visible
    wsum = te["w"].sum()
    return {
        "variant": label,
        "split": split,
        "n_test": len(te),
        "equal_weight_pp": float(j["eq"].mean()),
        "weighted_pp": float(j["w"].mean()),
        "improvement_pp": float(diff.mean()),
        "t": float(diff.mean() / se) if se and se > 0 else np.nan,
        "eq_avg_rvol": float(te["rvol20"].mean()),
        "wt_avg_rvol": float((te["rvol20"] * te["w"]).sum() / wsum),
        "eq_avg_beta": float(te["beta"].mean()),
        "wt_avg_beta": float((te["beta"] * te["w"]).sum() / wsum),
        "weight_gini": float(te["w"].std() / te["w"].mean()),
    }


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
    print(f"  {len(ev):,} events")

    out_rows = []
    for horizon in (20, 60):
        target = f"exc_{horizon}"
        d = ev.dropna(subset=ALL_FEATURES + [target, "beta"]).copy()
        d["days_since_earnings"] = d["days_since_earnings"].clip(upper=90)
        mid = d.date.quantile(0.5)
        splits = {
            "fit_first_test_second": (d.date <= mid, d.date > mid),
            "fit_second_test_first": (d.date > mid, d.date <= mid),
        }
        banner(f"{horizon}d — three model variants, both split directions")
        rows = []
        for label, feats in VARIANTS.items():
            for split, (fm, tm) in splits.items():
                r = evaluate(d, feats, target, fm, tm, label, split)
                r["horizon"] = horizon
                rows.append(r)
        df = pd.DataFrame(rows)
        show(df[["variant", "split", "equal_weight_pp", "weighted_pp",
                 "improvement_pp", "t", "eq_avg_rvol", "wt_avg_rvol",
                 "eq_avg_beta", "wt_avg_beta"]])
        out_rows.append(df)

        print(f"\n  Mean improvement across both splits ({horizon}d):")
        agg = df.groupby("variant").agg(
            improvement_pp=("improvement_pp", "mean"),
            min_t=("t", "min"),
            vol_tilt=("wt_avg_rvol", "mean"),
            eq_vol=("eq_avg_rvol", "mean"),
            beta_tilt=("wt_avg_beta", "mean"),
            eq_beta=("eq_avg_beta", "mean"),
        ).reset_index()
        agg["vol_tilt_pct"] = 100 * (agg.vol_tilt / agg.eq_vol - 1)
        agg["beta_tilt_pct"] = 100 * (agg.beta_tilt / agg.eq_beta - 1)
        show(agg[["variant", "improvement_pp", "min_t",
                  "vol_tilt_pct", "beta_tilt_pct"]])

    full = pd.concat(out_rows, ignore_index=True)
    full.to_csv(RESULTS / "3_risk_tilt_control.csv", index=False)
    print(f"\n  -> studies/results/09_optimisation/3_risk_tilt_control.csv")

    banner("VERDICT")
    for horizon in (20, 60):
        part = full[full.horizon == horizon]
        fu = part[part.variant == "full"].improvement_pp.mean()
        vo = part[part.variant == "vol_only"].improvement_pp.mean()
        nv = part[part.variant == "no_vol"].improvement_pp.mean()
        nv_t = part[part.variant == "no_vol"].t.min()
        share = 100 * vo / fu if fu != 0 else np.nan
        print(f"  {horizon}d: full {fu:+.3f}pp | vol_only {vo:+.3f}pp "
              f"({share:.0f}% of full) | no_vol {nv:+.3f}pp (worst t {nv_t:.2f})")

    with open(RESULTS / "summary_control.json", "w") as f:
        json.dump(full.to_dict("records"), f, indent=2, default=str)


if __name__ == "__main__":
    main()
