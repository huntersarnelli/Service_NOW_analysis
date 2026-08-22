"""
Portfolio construction study — should different names be treated differently?

The question
------------
Everything tested so far has aimed at RETURN and failed: nine interventions in
OPTIMISATION_STUDY.md §4's graveyard. This study aims at RISK instead, which is
a different objective and mostly untested at breadth.

Specifically: the strategy currently gives every name the same 20% of equity
per lot. A 60%-vol name and a 20%-vol name get identical dollars, so the
volatile name dominates the book's risk. And nothing caps cumulative exposure
to one ticker -- four lots in NVDA is 80% of the account in NVDA.

Four parts:

  1. SIZING REGIME   equal-dollar (current) vs equal-risk (vol parity) vs
                     equal-risk with a per-name cap.
  2. PER-NAME CAP    sweep the cumulative per-ticker exposure limit.
  3. VOL TIERING     split the universe into volatility terciles and give each
                     tier a different base allocation, in both directions.
  4. EFFECTIVE BETS  how many independent bets is this book actually making?
                     If 30 names are really 3 bets, no sizing rule fixes that,
                     and it should be known before optimising around it.

A warning carried from OPTIMISATION_STUDY.md §3: STRATEGY_REVIEW.md §5.13b
found vol-targeting at 5% risk RAISED CAGR to 87.4%, which reads like free
alpha. It is not -- at 5% risk per lot the rule increases average exposure to
96%, so it is a leverage tilt, not risk parity. This study sweeps risk_frac
explicitly and reports exposure alongside every result so that confusion
cannot recur.

Expect risk parity to LOWER raw CAGR. It underweights exactly the high-vol
names that produced the returns. It buys Sharpe and drawdown. That is the
trade; the question is whether the exchange rate is good.

    python studies/run_portfolio_study.py

Writes studies/results_portfolio/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from studies.dip_backtest import BacktestConfig, load_prices, run_backtest  # noqa: E402

RESULTS = ROOT / "studies" / "results_portfolio"
RESULTS.mkdir(parents=True, exist_ok=True)

END = "2026-08-22"
WINDOWS = {"2020+": "2020-01-02", "2022+": "2022-01-03", "2023+": "2023-01-03"}

BASKET = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "INTC", "QCOM", "TXN", "NOW", "PANW", "CRWD", "DDOG", "NET",
    "SNOW", "SHOP", "UBER", "ABNB", "PYPL", "ZS", "MDB", "TEAM", "WDAY", "INTU",
]
# A deliberately mixed-risk basket: the 30 above are all tech. Adding
# defensives is the only way to find out whether tiering helps because of
# volatility itself or merely because it de-weights one sector.
MIXED = BASKET + [
    "JNJ", "PG", "KO", "PEP", "WMT", "COST", "UNH", "MRK", "ABBV", "LLY",
    "JPM", "V", "MA", "HON", "CAT", "XOM", "CVX", "LIN", "MCD", "UNP",
]

CACHE: dict = {}
summary: dict = {}
KEY = ["cagr_pct", "max_drawdown_pct", "sharpe", "sortino", "calmar",
       "annual_vol_pct", "avg_exposure_pct", "num_lots", "win_rate_pct"]


def banner(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def show(df: pd.DataFrame, n: int = 60) -> None:
    with pd.option_context("display.width", 220, "display.max_columns", 40,
                           "display.float_format", lambda v: f"{v:,.2f}"):
        print(df.head(n).to_string(index=False))


def save(df: pd.DataFrame, name: str) -> None:
    p = RESULTS / f"{name}.csv"
    df.to_csv(p, index=False)
    print(f"  -> {p.relative_to(ROOT)}")


def row(res, label: str, window: str, universe: str, bh_cagr: float) -> dict:
    m = res.metrics
    r = {"variant": label, "window": window, "universe": universe}
    r.update({k: m[k] for k in KEY})
    r["excess_vs_bh_pp"] = m["cagr_pct"] - bh_cagr
    return r


def bh_cagr(prices, start) -> float:
    res = run_backtest(
        prices,
        BacktestConfig(z_entry=99, alloc=1.0 / len(prices), core_weight=1.0),
        start=start, end=END,
    )
    return res.metrics["cagr_pct"]


# ═════════════════════════════════════════════════════════════
# 1 + 2. sizing regime and per-name cap
# ═════════════════════════════════════════════════════════════
def part_1_sizing(prices, uni_name: str) -> pd.DataFrame:
    banner(f"1. SIZING REGIME — {uni_name} ({len(prices)} names)")
    rows = []
    for win, start in WINDOWS.items():
        b = bh_cagr(prices, start)
        variants = [
            ("equal-dollar 20% (current)", BacktestConfig()),
            ("equal-dollar 10%", BacktestConfig(alloc=0.10)),
            ("equal-risk 1% per lot", BacktestConfig(sizing_mode="vol_target", risk_frac=0.01)),
            ("equal-risk 2% per lot", BacktestConfig(sizing_mode="vol_target", risk_frac=0.02)),
            ("equal-risk 3% per lot", BacktestConfig(sizing_mode="vol_target", risk_frac=0.03)),
            ("equal-risk 5% per lot", BacktestConfig(sizing_mode="vol_target", risk_frac=0.05)),
            ("equal-risk 2% + 15%/name cap",
             BacktestConfig(sizing_mode="vol_target", risk_frac=0.02, max_ticker_weight=0.15)),
            ("equal-dollar 20% + 15%/name cap",
             BacktestConfig(max_ticker_weight=0.15)),
        ]
        for label, cfg in variants:
            res = run_backtest(prices, cfg, start=start, end=END)
            rows.append(row(res, label, win, uni_name, b))
        print(f"  {win}: {len(variants)} variants (B&H {b:.1f}% CAGR)")

    df = pd.DataFrame(rows)
    for win in WINDOWS:
        print(f"\n  --- {win} ---")
        show(df[df.window == win][["variant", "cagr_pct", "excess_vs_bh_pp",
                                   "max_drawdown_pct", "sharpe", "calmar",
                                   "annual_vol_pct", "avg_exposure_pct", "num_lots"]])
    return df


def part_2_caps(prices, uni_name: str) -> pd.DataFrame:
    banner(f"2. PER-NAME CAP SWEEP — {uni_name}")
    rows = []
    caps = [0.05, 0.10, 0.15, 0.20, 0.25, 0.35, None]
    for win, start in WINDOWS.items():
        b = bh_cagr(prices, start)
        for cap in caps:
            cfg = BacktestConfig(max_ticker_weight=cap)
            res = run_backtest(prices, cfg, start=start, end=END)
            label = f"{cap:.0%}/name" if cap is not None else "no cap (current)"
            rows.append(row(res, label, win, uni_name, b))
    df = pd.DataFrame(rows)
    for win in WINDOWS:
        print(f"\n  --- {win} ---")
        show(df[df.window == win][["variant", "cagr_pct", "excess_vs_bh_pp",
                                   "max_drawdown_pct", "sharpe", "calmar",
                                   "avg_exposure_pct", "num_lots"]])

    print("\n  Mean across the three windows:")
    agg = df.groupby("variant")[["cagr_pct", "max_drawdown_pct", "sharpe",
                                 "calmar", "excess_vs_bh_pp"]].mean().reset_index()
    order = [f"{c:.0%}/name" for c in caps[:-1]] + ["no cap (current)"]
    agg = agg.set_index("variant").reindex(order).reset_index()
    show(agg)
    return df


# ═════════════════════════════════════════════════════════════
# 3. volatility tiering
# ═════════════════════════════════════════════════════════════
def vol_tiers(prices, start: str, lookback: int = 252) -> dict[str, str]:
    """
    Assign each name to a volatility tercile using only data BEFORE the window
    opens. Using the window's own volatility would be lookahead.
    """
    vols = {}
    for t, df in prices.items():
        pre = df[df.index < pd.Timestamp(start)]
        if len(pre) < 60:
            continue
        r = pre["Close"].pct_change().tail(lookback)
        vols[t] = float(r.std() * np.sqrt(252) * 100)
    s = pd.Series(vols).dropna().sort_values()
    if s.empty:
        return {}
    q1, q2 = s.quantile(1 / 3), s.quantile(2 / 3)
    return {t: ("low" if v <= q1 else "high" if v > q2 else "mid")
            for t, v in s.items()}


def part_3_tiering(prices, uni_name: str) -> pd.DataFrame:
    banner(f"3. VOLATILITY TIERING — {uni_name}")
    rows = []
    for win, start in WINDOWS.items():
        tiers = vol_tiers(prices, start)
        if not tiers:
            continue
        counts = pd.Series(tiers).value_counts().to_dict()
        print(f"\n  {win}: tiers assigned from pre-{start} data -> {counts}")
        b = bh_cagr(prices, start)

        schemes = {
            "flat 20% (current)": {"low": 0.20, "mid": 0.20, "high": 0.20},
            "de-risk: low 30 / mid 20 / high 10": {"low": 0.30, "mid": 0.20, "high": 0.10},
            "de-risk hard: low 35 / mid 20 / high 5": {"low": 0.35, "mid": 0.20, "high": 0.05},
            "tilt to vol: low 10 / mid 20 / high 30": {"low": 0.10, "mid": 0.20, "high": 0.30},
            "barbell: low 30 / mid 10 / high 30": {"low": 0.30, "mid": 0.10, "high": 0.30},
        }
        for label, sch in schemes.items():
            alloc = tuple((t, sch[tier]) for t, tier in tiers.items())
            cfg = BacktestConfig(alloc_by_ticker=alloc)
            res = run_backtest(prices, cfg, start=start, end=END)
            rows.append(row(res, label, win, uni_name, b))

    df = pd.DataFrame(rows)
    for win in WINDOWS:
        part = df[df.window == win]
        if part.empty:
            continue
        print(f"\n  --- {win} ---")
        show(part[["variant", "cagr_pct", "excess_vs_bh_pp", "max_drawdown_pct",
                   "sharpe", "calmar", "annual_vol_pct", "avg_exposure_pct"]])

    print("\n  Mean across the three windows:")
    agg = df.groupby("variant")[["cagr_pct", "max_drawdown_pct", "sharpe",
                                 "calmar", "annual_vol_pct"]].mean().reset_index()
    show(agg.sort_values("sharpe", ascending=False))
    return df


# ═════════════════════════════════════════════════════════════
# 4. how many independent bets?
# ═════════════════════════════════════════════════════════════
def part_4_effective_bets(prices, uni_name: str) -> pd.DataFrame:
    banner(f"4. EFFECTIVE NUMBER OF BETS — {uni_name}")
    rows = []
    for win, start in WINDOWS.items():
        rets = pd.DataFrame({t: df["Close"].pct_change() for t, df in prices.items()})
        rets = rets[(rets.index >= pd.Timestamp(start)) & (rets.index <= pd.Timestamp(END))]
        rets = rets.dropna(axis=1, thresh=int(len(rets) * 0.8)).dropna()
        if rets.shape[1] < 3:
            continue
        n = rets.shape[1]
        corr = rets.corr().values

        # average off-diagonal pairwise correlation
        off = corr[~np.eye(n, dtype=bool)]
        avg_corr = float(off.mean())

        # participation ratio of the eigenvalue spectrum: (sum L)^2 / sum L^2.
        # Equals n when every name is independent, and 1 when all names are the
        # same bet. This is the number to look at.
        lam = np.linalg.eigvalsh(corr)
        lam = np.clip(lam, 0, None)
        enb = float(lam.sum() ** 2 / (lam ** 2).sum())

        # share of total variance explained by the first principal component
        pc1 = float(lam.max() / lam.sum() * 100)

        # the classic diversification identity: with n names of average
        # correlation rho, the portfolio behaves like this many independent ones
        n_equiv = float(1.0 / ((1 - avg_corr) / n + avg_corr)) if avg_corr > 0 else float(n)

        rows.append({
            "universe": uni_name, "window": win, "n_names": n,
            "avg_pairwise_corr": avg_corr,
            "effective_bets_eigen": enb,
            "effective_bets_corr": n_equiv,
            "pc1_variance_pct": pc1,
        })
    df = pd.DataFrame(rows)
    show(df)
    return df


def main() -> None:
    banner("0. DATA")
    basket = load_prices(BASKET, "2018-06-01", END, CACHE)
    mixed = load_prices(MIXED, "2018-06-01", END, CACHE)
    print(f"  tech30: {len(basket)}/{len(BASKET)}   mixed50: {len(mixed)}/{len(MIXED)}")

    s1 = pd.concat([part_1_sizing(basket, "tech30"),
                    part_1_sizing(mixed, "mixed50")], ignore_index=True)
    save(s1, "1_sizing_regime")

    s2 = pd.concat([part_2_caps(basket, "tech30"),
                    part_2_caps(mixed, "mixed50")], ignore_index=True)
    save(s2, "2_name_caps")

    s3 = pd.concat([part_3_tiering(basket, "tech30"),
                    part_3_tiering(mixed, "mixed50")], ignore_index=True)
    save(s3, "3_vol_tiering")

    s4 = pd.concat([part_4_effective_bets(basket, "tech30"),
                    part_4_effective_bets(mixed, "mixed50"),
                    part_4_effective_bets(
                        load_prices(["META", "NVDA", "NET"], "2018-06-01", END, CACHE),
                        "trio")],
                   ignore_index=True)
    save(s4, "4_effective_bets")

    banner("VERDICT — best Sharpe per universe x window, across every variant tested")
    allv = pd.concat([s1, s2, s3], ignore_index=True)
    best = (allv.sort_values("sharpe", ascending=False)
                .groupby(["universe", "window"])
                .head(1)
                .sort_values(["universe", "window"]))
    show(best[["universe", "window", "variant", "cagr_pct", "excess_vs_bh_pp",
               "max_drawdown_pct", "sharpe", "calmar"]])

    baseline = allv[allv.variant.isin(["equal-dollar 20% (current)", "no cap (current)",
                                       "flat 20% (current)"])]
    print("\n  Baseline (current rules) for comparison:")
    show(baseline.groupby(["universe", "window"])[
        ["cagr_pct", "max_drawdown_pct", "sharpe", "calmar"]].mean().reset_index())

    summary["best"] = best.to_dict("records")
    summary["effective_bets"] = s4.to_dict("records")
    with open(RESULTS / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n  -> {(RESULTS / 'summary.json').relative_to(ROOT)}")
    banner("DONE")


if __name__ == "__main__":
    main()
