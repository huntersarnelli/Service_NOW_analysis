"""
Window sensitivity and a concrete recommendation.

Run:  python studies/run_recommendation.py     -> studies/results_recommendation/

Context
-------
The strategy document's window starts 2023-01-03. The regime study (§5.14) showed
that extending back to 2020 flips the edge from +3.0pp to -6.7pp. The author's
objection is that 2020-2021 were pandemic outliers driven by panic and stimulus
rather than anything a statistical model should be fitted to.

That objection is reasonable and this script takes it seriously. Crucially it is
NOT the same as the documented window: 2022 was a rate-hiking bear market, not a
pandemic year. So there are three defensible windows, and the answer differs
between them:

    2020+  everything, pandemic included
    2022+  post-pandemic, INCLUDING the 2022 bear   <- the honest compromise
    2023+  the documented window, excluding the bear

Sections
  1  Window sensitivity — the same rules across all three
  2  Candidate strategies compared on the 2022+ window
  3  Dollar-cost averaging vs dip-timed deployment (the practical question)
  4  Recommendation
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
)

RESULTS = ROOT / "studies" / "results_recommendation"
RESULTS.mkdir(parents=True, exist_ok=True)

TRIO = ["META", "NVDA", "NET"]
BROAD = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "INTC", "QCOM", "TXN", "NOW", "PANW", "CRWD", "DDOG", "NET",
    "SNOW", "SHOP", "UBER", "ABNB", "PYPL", "ZS", "MDB", "TEAM", "WDAY", "ANET",
]
BENCH = ["QQQ", "SPY"]
WARMUP = "2019-09-13"
END = "2026-07-31"
WINDOWS = {
    "2020+ (all history)": "2020-01-02",
    "2022+ (post-pandemic, incl. bear)": "2022-01-03",
    "2023+ (documented window)": "2023-01-03",
}
CACHE: dict = {}
COLS = ["final_equity", "cagr_pct", "max_drawdown_pct", "sharpe", "calmar",
        "num_lots", "win_rate_pct", "avg_exposure_pct"]


def banner(t):
    print("\n" + "=" * 82); print(t); print("=" * 82)


def show(df, cols=None, n=50):
    d = df if cols is None else df[[c for c in cols if c in df.columns]]
    with pd.option_context("display.width", 220, "display.max_columns", 40):
        print(d.head(n).round(2).to_string(index=False))


def save(df, name):
    df.to_csv(RESULTS / f"{name}.csv", index=False)
    print(f"  -> studies/results_recommendation/{name}.csv")


# ─────────────────────────────────────────────────────────────
# Contribution-based simulation (the realistic retail question)
# ─────────────────────────────────────────────────────────────
def contribution_sim(
    prices: dict[str, pd.DataFrame],
    start: str,
    end: str,
    monthly: float = 1_000.0,
    mode: str = "dca",
    z_entry: float = -1.2,
    sma_window: int = 20,
    max_cash_months: int = 12,
    commission_bps: float = 5.0,
) -> pd.Series:
    """
    Contribute `monthly` on the first bar of each month, then deploy it.

    mode="dca"  : invest immediately, equal-weight across the universe.
    mode="dip"  : hold the contribution as cash until some name prints
                  Z < z_entry, then buy that name. Cash is force-deployed
                  after `max_cash_months` so the comparison cannot win merely
                  by sitting out.

    Nothing is ever sold — this isolates *entry timing* on new money, which is
    the one thing the null test showed the signal genuinely does.
    """
    frames = {}
    for t, df in prices.items():
        d = df.copy()
        c = d["Close"]
        d["zscore"] = (c - c.rolling(sma_window).mean()) / c.rolling(sma_window).std()
        frames[t] = d

    calendar = pd.DatetimeIndex(sorted(set().union(*[set(d.index) for d in frames.values()])))
    calendar = calendar[(calendar >= pd.Timestamp(start)) & (calendar <= pd.Timestamp(end))]
    close = pd.DataFrame({t: d["Close"] for t, d in frames.items()}).reindex(calendar)
    zsc = pd.DataFrame({t: d["zscore"] for t, d in frames.items()}).reindex(calendar)

    fee = commission_bps / 10_000.0
    cash = 0.0
    shares = {t: 0.0 for t in frames}
    pending_since = None
    equity = []

    month_starts = set(
        pd.Series(calendar).groupby([calendar.year, calendar.month]).min().values
    )

    for i, date in enumerate(calendar):
        if date.to_datetime64() in month_starts:
            cash += monthly
            if pending_since is None:
                pending_since = date

        if cash > 0:
            names = [t for t in frames if np.isfinite(close.iat[i, close.columns.get_loc(t)])]
            if names:
                if mode == "dca":
                    per = cash / len(names)
                    for t in names:
                        px = close.iat[i, close.columns.get_loc(t)]
                        shares[t] += (per / (1 + fee)) / px
                    cash = 0.0
                    pending_since = None
                else:
                    dips = [
                        t for t in names
                        if pd.notna(zsc.iat[i, zsc.columns.get_loc(t)])
                        and zsc.iat[i, zsc.columns.get_loc(t)] < z_entry
                    ]
                    stale = (
                        pending_since is not None
                        and (date - pending_since).days >= max_cash_months * 30
                    )
                    if dips:
                        per = cash / len(dips)
                        for t in dips:
                            px = close.iat[i, close.columns.get_loc(t)]
                            shares[t] += (per / (1 + fee)) / px
                        cash = 0.0
                        pending_since = None
                    elif stale:
                        per = cash / len(names)
                        for t in names:
                            px = close.iat[i, close.columns.get_loc(t)]
                            shares[t] += (per / (1 + fee)) / px
                        cash = 0.0
                        pending_since = None

        mkt = 0.0
        for t in frames:
            px = close.iat[i, close.columns.get_loc(t)]
            if np.isfinite(px):
                mkt += shares[t] * px
        equity.append(cash + mkt)

    return pd.Series(equity, index=calendar, name=mode)


def irr_from_contributions(equity: pd.Series, monthly: float) -> tuple[float, float]:
    """Return (total contributed, money-weighted annualised return %)."""
    months = len(pd.Series(equity.index).groupby(
        [equity.index.year, equity.index.month]).min())
    contributed = months * monthly
    yrs = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    # Solve for r where sum of contributions compounded at r == final value.
    lo, hi = -0.99, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        fv = sum(monthly * (1 + mid) ** ((yrs * 12 - k) / 12) for k in range(months))
        if fv < equity.iloc[-1]:
            lo = mid
        else:
            hi = mid
    return contributed, lo * 100


def main():
    summary = {}
    base = BacktestConfig()

    print("Downloading…")
    trio = load_prices(TRIO, WARMUP, END, CACHE)
    broad = load_prices(BROAD, WARMUP, END, CACHE)
    bench = load_prices(BENCH, WARMUP, END, CACHE)
    print(f"  trio {len(trio)}/3, broad {len(broad)}/{len(BROAD)}, bench {len(bench)}/2")

    # ── 1. Window sensitivity ────────────────────────────────────────
    banner("1. WINDOW SENSITIVITY — identical rules, three defensible windows")
    print("  2022 was a rate-hiking bear market, not a pandemic year. Excluding")
    print("  2020-2021 is defensible; excluding 2022 as well is a different claim.\n")
    rows = []
    for label, start in WINDOWS.items():
        r = run_backtest(trio, base, start=start, end=END)
        b = series_metrics(buy_and_hold(trio, base.start_capital, start, END))
        rows.append({
            "window": label,
            "strategy_cagr": r.metrics["cagr_pct"],
            "bh_cagr": b["cagr_pct"],
            "excess_pp": r.metrics["cagr_pct"] - b["cagr_pct"],
            "strategy_sharpe": r.metrics["sharpe"], "bh_sharpe": b["sharpe"],
            "strategy_maxdd": r.metrics["max_drawdown_pct"], "bh_maxdd": b["max_drawdown_pct"],
            "strategy_calmar": r.metrics["calmar"], "bh_calmar": b["calmar"],
        })
    win = pd.DataFrame(rows)
    show(win)
    print("\n  Note which way the exclusion cuts: 2020 and 2021 were years the")
    print("  strategy LOST to buy & hold by 47.9pp and 46.1pp. Removing them")
    print("  helps the strategy's record, it does not flatter buy & hold.")
    save(win, "1_window_sensitivity")
    summary["windows"] = win.to_dict("records")

    # ── 2. Candidates on the 2022+ window ────────────────────────────
    banner("2. CANDIDATE STRATEGIES — 2022+ (post-pandemic, including the bear)")
    START = WINDOWS["2022+ (post-pandemic, incl. bear)"]
    rows = []

    def add(label, res=None, series=None):
        if res is not None:
            rows.append({"strategy": label, **{k: res.metrics.get(k) for k in COLS}})
        else:
            m = series_metrics(series)
            rows.append({"strategy": label, **{k: m.get(k) for k in COLS}})

    add("Buy & hold — META/NVDA/NET", series=buy_and_hold(trio, base.start_capital, START, END))
    add("Buy & hold — 30-name basket", series=buy_and_hold(broad, base.start_capital, START, END))
    for t in BENCH:
        add(f"Buy & hold — {t}", series=buy_and_hold({t: bench[t]}, base.start_capital, START, END))
    add("Dip strategy — trio, documented (Z<-1.2, 4xATR, 20%)",
        res=run_backtest(trio, base, start=START, end=END))
    add("Dip strategy — trio, vol-target 5%",
        res=run_backtest(trio, replace(base, sizing_mode="vol_target", risk_frac=0.05),
                         start=START, end=END))
    add("Dip strategy — 30-name basket, documented",
        res=run_backtest(broad, base, start=START, end=END))
    add("Dip strategy — 30-name basket, vol-target 5%",
        res=run_backtest(broad, replace(base, sizing_mode="vol_target", risk_frac=0.05),
                         start=START, end=END))
    add("Dip strategy — trio, core 50% + dip lots",
        res=run_backtest(trio, replace(base, core_weight=0.50), start=START, end=END))
    cand = pd.DataFrame(rows).sort_values("sharpe", ascending=False)
    show(cand, ["strategy"] + COLS)
    save(cand, "2_candidates_2022plus")
    summary["candidates"] = cand.to_dict("records")

    # ── 3. DCA vs dip-timed deployment ───────────────────────────────
    banner("3. THE PRACTICAL QUESTION — deploying NEW money: schedule vs dips")
    print("  $1,000/month, nothing ever sold. This isolates entry timing, which the")
    print("  null test showed is the one thing the Z signal genuinely does.")
    print("  Dip mode force-deploys after 12 months so it cannot win by sitting out.\n")
    rows = []
    for uni_name, uni in [("META/NVDA/NET", trio), ("30-name basket", broad),
                          ("QQQ", {"QQQ": bench["QQQ"]})]:
        for start_label, start in WINDOWS.items():
            dca = contribution_sim(uni, start, END, mode="dca")
            dip = contribution_sim(uni, start, END, mode="dip")
            c_dca, irr_dca = irr_from_contributions(dca, 1000.0)
            c_dip, irr_dip = irr_from_contributions(dip, 1000.0)
            rows.append({
                "universe": uni_name, "window": start_label,
                "contributed": c_dca,
                "dca_final": dca.iloc[-1], "dip_final": dip.iloc[-1],
                "dca_irr_pct": irr_dca, "dip_irr_pct": irr_dip,
                "dip_advantage_pct": (dip.iloc[-1] / dca.iloc[-1] - 1) * 100,
            })
    contrib = pd.DataFrame(rows)
    show(contrib)
    wins = int((contrib.dip_advantage_pct > 0).sum())
    print(f"\n  Dip-timing beat scheduled investing in {wins}/{len(contrib)} combinations")
    print(f"  Mean advantage {contrib.dip_advantage_pct.mean():+.2f}%  "
          f"Median {contrib.dip_advantage_pct.median():+.2f}%")
    save(contrib, "3_dca_vs_dip_timing")
    summary["contributions"] = {
        "wins": wins, "n": int(len(contrib)),
        "mean_advantage_pct": float(contrib.dip_advantage_pct.mean()),
        "median_advantage_pct": float(contrib.dip_advantage_pct.median()),
        "rows": contrib.to_dict("records"),
    }

    # ── 4. Recommendation ────────────────────────────────────────────
    banner("4. RECOMMENDATION — ranked by Sharpe on the 2022+ window")
    top = cand.head(5)[["strategy", "cagr_pct", "max_drawdown_pct", "sharpe", "calmar"]]
    show(top)
    best = cand.iloc[0]
    print(f"\n  Best risk-adjusted: {best.strategy}")
    print(f"    CAGR {best.cagr_pct:.1f}%  MaxDD {best.max_drawdown_pct:.1f}%  "
          f"Sharpe {best.sharpe:.2f}  Calmar {best.calmar:.2f}")
    summary["best"] = best.to_dict()

    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print(f"\n  -> studies/results_recommendation/summary.json")
    banner("DONE")
    return summary


if __name__ == "__main__":
    main()
