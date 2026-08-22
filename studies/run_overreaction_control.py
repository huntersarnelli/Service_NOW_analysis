"""
Overreaction study — the null control.

run_overreaction_study.py measures forward EXCESS return over SPY. On a
universe of high-beta names in a period when high-beta tech beat SPY, that
level is contaminated: holding any of these names on any random day beat SPY,
so a positive excess after a dip proves nothing on its own.

This is the control docs/01_STRATEGY_REVIEW.md §5.12 ran for the 3-name study, applied
here: draw random dates on the SAME names at the SAME frequency, measure the
same forward excess, and ask whether the dip dates beat the random dates.

That difference is beta-free by construction — same names, same period, same
holding horizon, only the entry dates differ.

    python studies/run_overreaction_control.py
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
    BENCHMARK, HORIZONS, UNIVERSE,
    add_indicators, attach_earnings, extract_events, load_earnings,
    load_prices, monthly_tstat,
)

RESULTS = ROOT / "studies" / "results" / "08_overreaction"
RESULTS.mkdir(parents=True, exist_ok=True)

WARMUP, START, END = "2014-06-01", "2015-01-01", "2026-08-22"
Z_ENTRY = -1.2
N_DRAWS = 200


def banner(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def show(df: pd.DataFrame) -> None:
    with pd.option_context("display.width", 210, "display.max_columns", 40,
                           "display.float_format", lambda v: f"{v:,.3f}"):
        print(df.to_string(index=False))


def random_events(frames, counts: dict[str, int], rng, start: str) -> pd.DataFrame:
    """Random entry dates, per name, matching that name's dip-event count."""
    spy_close = frames[BENCHMARK]["Close"]
    rows = []
    for t, n in counts.items():
        if n == 0 or t not in frames:
            continue
        d = frames[t]
        elig = np.flatnonzero(
            (d.index >= pd.Timestamp(start)) & d["z"].notna().values
        )
        if len(elig) == 0:
            continue
        picks = rng.choice(elig, size=min(n, len(elig)), replace=False)
        c = d["Close"]
        spy_al = spy_close.reindex(d.index).ffill()
        for i in picks:
            r = {"ticker": t, "date": d.index[i]}
            for h in HORIZONS:
                j = i + h
                if j < len(d):
                    fwd = float(c.iloc[j] / c.iloc[i] - 1.0)
                    mkt = float(spy_al.iloc[j] / spy_al.iloc[i] - 1.0)
                    r[f"exc_{h}"] = (fwd - mkt) * 100
                else:
                    r[f"exc_{h}"] = np.nan
            rows.append(r)
    ev = pd.DataFrame(rows)
    ev["month"] = ev["date"].dt.to_period("M").astype(str)
    return ev


def main() -> None:
    banner("0. DATA")
    prices = load_prices(UNIVERSE + [BENCHMARK], WARMUP, END)
    tickers = [t for t in prices if t != BENCHMARK]
    earnings = load_earnings(tickers)
    spy = prices[BENCHMARK]
    frames = {BENCHMARK: add_indicators(spy, spy)}
    for t in tickers:
        frames[t] = attach_earnings(add_indicators(prices[t], spy), earnings.get(t))
    print(f"  {len(tickers)} names")

    ev = extract_events(frames, z_entry=Z_ENTRY, start=START)
    counts = ev.groupby("ticker").size().to_dict()
    print(f"  {len(ev):,} dip events")

    banner(f"1. NULL CONTROL — {N_DRAWS} random-date draws, same names, same counts")
    real = {h: monthly_tstat(ev, f"exc_{h}")["mean"] for h in HORIZONS}
    rng = np.random.default_rng(20260822)
    draws = {h: [] for h in HORIZONS}
    for k in range(N_DRAWS):
        rev = random_events(frames, counts, rng, START)
        for h in HORIZONS:
            draws[h].append(monthly_tstat(rev, f"exc_{h}")["mean"])
        if (k + 1) % 50 == 0:
            print(f"  {k + 1}/{N_DRAWS} draws")

    rows = []
    for h in HORIZONS:
        arr = np.array(draws[h], dtype=float)
        pct = float((arr < real[h]).mean() * 100)
        rows.append({
            "horizon_days": h,
            "dip_excess_pct": real[h],
            "random_mean_pct": float(arr.mean()),
            "random_p5": float(np.percentile(arr, 5)),
            "random_p95": float(np.percentile(arr, 95)),
            "dip_minus_random_pp": real[h] - float(arr.mean()),
            "percentile_of_dip": pct,
            "p_value_one_tailed": float((arr >= real[h]).mean()),
        })
    out = pd.DataFrame(rows)
    show(out)
    out.to_csv(RESULTS / "10_null_control.csv", index=False)
    print(f"  -> studies/results/08_overreaction/10_null_control.csv")

    banner("2. READING")
    for r in rows:
        verdict = ("beats random" if r["percentile_of_dip"] >= 95
                   else "inside the random band")
        print(f"  {r['horizon_days']:>4}d: dip {r['dip_excess_pct']:+.2f}pp vs "
              f"random {r['random_mean_pct']:+.2f}pp  "
              f"(pctile {r['percentile_of_dip']:.0f}, p={r['p_value_one_tailed']:.3f}) "
              f"-> {verdict}")

    with open(RESULTS / "summary_control.json", "w") as f:
        json.dump(rows, f, indent=2, default=str)


if __name__ == "__main__":
    main()
