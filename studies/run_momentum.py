"""
Momentum study runner (docs/05_MOMENTUM_STUDY.md). Implements the pre-registered
rules in §3 and the pass bar in §4; writes every table to studies/results/12_momentum/.

    python studies/run_momentum.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.screen import UNIVERSE_V2  # noqa: E402
from studies.momentum_lib import (  # noqa: E402
    COST_PER_SIDE, N_RANDOM, TOP_N, eligible_universe, load_panels, max_drawdown,
    momentum_scores, next_month_returns, t_stat, turnover,
)

RESULTS = ROOT / "studies" / "results" / "12_momentum"
RESULTS.mkdir(parents=True, exist_ok=True)
START = pd.Period("2006-01", "M")
SEED = 2026
PASS_EDGE_PP, PASS_T, PASS_MONTHS = 0.25, 2.0, 120


def run_strategy(panels, months, top_n, allowed=None, universe_size=200, seed=SEED):
    """One monthly row per formation month: momentum (gross/net), random mean, EW universe, SPY, QQQ."""
    rng = np.random.default_rng(seed + top_n + (0 if allowed is None else 7))
    rows, random_paths, previous = [], [], []
    for month in months:
        names = eligible_universe(panels, month, allowed=allowed, size=universe_size)
        if len(names) < top_n * 2:
            continue
        scores = momentum_scores(panels, month, names).dropna()
        picks = list(scores.sort_values(ascending=False).index[:top_n])
        returns, missing = next_month_returns(panels, month, names)
        gross = float(returns[picks].mean())
        cost = turnover(previous, picks) * 2 * COST_PER_SIDE
        draws = np.array([returns.to_numpy()[rng.choice(len(names), top_n, replace=False)].mean()
                          for _ in range(N_RANDOM)])
        spy = panels["adj"]["SPY"]
        qqq = panels["adj"]["QQQ"]
        rows.append({
            "month": str(month), "n_universe": len(names), "missing_next_month": missing,
            "momentum_gross": gross * 100, "cost": cost * 100, "momentum_net": (gross - cost) * 100,
            "random_mean": draws.mean() * 100, "edge_vs_random": (gross - cost - draws.mean()) * 100,
            "equal_weight_universe": float(returns.mean()) * 100,
            "spy": float(spy[month + 1] / spy[month] - 1) * 100,
            "qqq": float(qqq[month + 1] / qqq[month] - 1) * 100 if pd.notna(qqq.get(month)) else np.nan,
            "turnover": turnover(previous, picks), "holdings": " ".join(picks),
        })
        random_paths.append(draws)
        previous = picks
    return pd.DataFrame(rows), np.array(random_paths)


def summarise(label, monthly, random_paths):
    edge = monthly["edge_vs_random"].to_numpy()
    half = len(edge) // 2
    mom = monthly["momentum_net"] / 100
    terminal_mom = float((1 + mom).prod())
    terminal_random = (1 + random_paths).prod(axis=0) if len(random_paths) else np.array([])
    return {
        "test": label, "months": len(edge), "first_month": monthly["month"].iloc[0] if len(edge) else "",
        "mean_edge_pp_per_month": float(np.nanmean(edge)), "t_stat": t_stat(edge),
        "first_half_edge": float(np.nanmean(edge[:half])), "second_half_edge": float(np.nanmean(edge[half:])),
        "share_months_positive": float((edge > 0).mean() * 100),
        "empirical_p_random_beats_momentum": float((terminal_random >= terminal_mom).mean()) if len(terminal_random) else np.nan,
        "momentum_net_pp_per_month": float(monthly["momentum_net"].mean()),
        "vs_spy_pp_per_month": float((monthly["momentum_net"] - monthly["spy"]).mean()),
        "vs_qqq_pp_per_month": float((monthly["momentum_net"] - monthly["qqq"]).mean()),
        "vs_equal_weight_pp_per_month": float((monthly["momentum_net"] - monthly["equal_weight_universe"]).mean()),
        "avg_turnover": float(monthly["turnover"].mean()),
        "max_drawdown_momentum_pct": max_drawdown(monthly["momentum_net"] / 100),
        "max_drawdown_equal_weight_pct": max_drawdown(monthly["equal_weight_universe"] / 100),
        "max_drawdown_spy_pct": max_drawdown(monthly["spy"] / 100),
        "annualised_momentum_net_pct": float(((1 + mom).prod() ** (12 / len(mom)) - 1) * 100) if len(mom) else np.nan,
        "annualised_spy_pct": float(((1 + monthly["spy"] / 100).prod() ** (12 / len(mom)) - 1) * 100) if len(mom) else np.nan,
    }


def main() -> None:
    print("Loading monthly panels from the price cache…")
    panels, log = load_panels()
    print(f"  {log['files']} files, {len(log['bad_print_tickers'])} bad-print tickers excluded")
    last_formation = panels["adj"].index.max() - 1
    months = [m for m in pd.period_range(START, last_formation, freq="M")]

    summaries = []
    primary, primary_paths = run_strategy(panels, months, TOP_N)
    primary.to_csv(RESULTS / "monthly_primary.csv", index=False)
    summaries.append(summarise("PRIMARY: top 20 of 200, 2006+", primary, primary_paths))

    for n in (10, 30):
        m, p = run_strategy(panels, months, n)
        summaries.append(summarise(f"top {n} of 200, 2006+ (exploratory)", m, p))
    for start in ("2013-01", "2020-01"):
        sub = primary[primary["month"] >= start]
        summaries.append(summarise(f"top 20 of 200, {start}+ (exploratory)", sub,
                                   primary_paths[primary["month"].to_numpy() >= start]))
    desk, desk_paths = run_strategy(panels, months, TOP_N, allowed=set(UNIVERSE_V2), universe_size=None)
    desk.to_csv(RESULTS / "monthly_desk124.csv", index=False)
    summaries.append(summarise("top 20 of the 124 Desk names, 2006+ (HINDSIGHT-BIASED, exploratory)",
                               desk, desk_paths))

    table = pd.DataFrame(summaries)
    table.to_csv(RESULTS / "summary.csv", index=False)

    p = table.iloc[0]
    criteria = pd.DataFrame([
        {"criterion": "mean monthly edge vs random >= +0.25pp", "value": p["mean_edge_pp_per_month"],
         "passes": p["mean_edge_pp_per_month"] >= PASS_EDGE_PP},
        {"criterion": "t >= 2.0", "value": p["t_stat"], "passes": p["t_stat"] >= PASS_T},
        {"criterion": "positive in both halves", "value": f"{p['first_half_edge']:+.3f} / {p['second_half_edge']:+.3f}",
         "passes": p["first_half_edge"] > 0 and p["second_half_edge"] > 0},
        {"criterion": ">= 120 months", "value": p["months"], "passes": p["months"] >= PASS_MONTHS},
    ])
    criteria.to_csv(RESULTS / "criteria.csv", index=False)
    verdict = "PASS" if criteria["passes"].all() else "FAIL"

    worst = primary.assign(vs_ew=primary["momentum_net"] - primary["equal_weight_universe"]) \
        .nsmallest(8, "vs_ew")[["month", "momentum_net", "equal_weight_universe", "spy", "vs_ew", "holdings"]]
    worst.to_csv(RESULTS / "worst_months.csv", index=False)
    yearly = primary.assign(year=primary["month"].str[:4]).groupby("year")["edge_vs_random"].agg(["mean", "count"])
    yearly.to_csv(RESULTS / "edge_by_year.csv")
    pd.DataFrame([{"files": log["files"], "bad_print_tickers": len(log["bad_print_tickers"]),
                   "months_missing_next_price_total": int(primary["missing_next_month"].sum())}]) \
        .to_csv(RESULTS / "data_log.csv", index=False)

    pd.set_option("display.width", 250)
    pd.set_option("display.float_format", "{:.3f}".format)
    print(table.T.to_string())
    print(criteria.to_string(index=False))
    print(f"\nVERDICT: {verdict}")
    print(yearly.to_string())
    print(worst.drop(columns="holdings").to_string(index=False))


if __name__ == "__main__":
    main()
