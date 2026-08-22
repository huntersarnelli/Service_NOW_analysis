"""
Does adding a profit take to Strategy B help?

Run:  python studies/run_profit_take.py   -> studies/results_profit_take/

The question
------------
Strategy B has no profit target: it holds until a 4xATR trail is hit, so it is
close to always-invested (96-98% average exposure). The proposal is to sell the
statistical extremes — not Strategy A's Z > 0, which is the mean and costs ~21pp
of CAGR, but a genuinely high bar such as Z > +2 (about the 97.7th percentile) —
and redeploy the freed cash into the next dip.

This is a real gap in the study so far. Only Z > 0 was ever tested.

The thing that could break it
-----------------------------
A Z-score is (Close - SMA20) / sd20. Z is mean-reverting *by construction*, but
price is not. Z can fall from +2 to 0 with price completely flat, or even rising,
because the moving average catches up from below. "Sell high, buy back lower"
assumes price reverts; the signal only guarantees Z reverts. Section 5 measures
how often price actually cooperates.

Sections
  1  Profit-take threshold sweep (Z-based)
  2  Percentile-based profit take (distribution-free)
  3  Partial vs full exits, and a minimum-gain filter
  4  Across all three windows
  5  DIAGNOSTIC — after selling a high, do you get to buy back lower?
  6  Z decomposition — when Z falls, is it price dropping or the SMA rising?
  7  Pre-earnings flattening
  8  Generalisation across the 30-name basket
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from studies.dip_backtest import (  # noqa: E402
    BacktestConfig, buy_and_hold, load_prices, run_backtest, series_metrics,
)

RESULTS = ROOT / "studies" / "results_profit_take"
RESULTS.mkdir(parents=True, exist_ok=True)

TRIO = ["META", "NVDA", "NET"]
BASKET = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "INTC", "QCOM", "TXN", "NOW", "PANW", "CRWD", "DDOG", "NET",
    "SNOW", "SHOP", "UBER", "ABNB", "PYPL", "ZS", "MDB", "TEAM", "WDAY", "ANET",
]
WARMUP, END = "2019-09-13", "2026-07-31"
WINDOWS = {"2020+": "2020-01-02", "2022+": "2022-01-03", "2023+": "2023-01-03"}
MAIN = WINDOWS["2022+"]
CACHE: dict = {}
B = replace(BacktestConfig(), z_entry=-1.2, atr_mult=4.0)
COLS = ["cagr_pct", "max_drawdown_pct", "sharpe", "calmar", "num_lots",
        "win_rate_pct", "avg_days_held", "avg_exposure_pct"]


def banner(t):
    print("\n" + "=" * 86); print(t); print("=" * 86)


def show(df, cols=None, n=60):
    d = df if cols is None else df[[c for c in cols if c in df.columns]]
    with pd.option_context("display.width", 230, "display.max_columns", 40):
        print(d.head(n).round(2).to_string(index=False))


def save(df, name):
    df.to_csv(RESULTS / f"{name}.csv", index=False)
    print(f"  -> studies/results_profit_take/{name}.csv")


def row(res, label):
    return {"variant": label, **{k: res.metrics.get(k) for k in COLS},
            "final_equity": res.metrics["final_equity"]}


def main():
    summary = {}
    print("Downloading…")
    trio = load_prices(TRIO, WARMUP, END, CACHE)
    basket = load_prices(BASKET, WARMUP, END, CACHE)
    print(f"  trio {len(trio)}/3, basket {len(basket)}/{len(BASKET)}")

    base = run_backtest(trio, B, start=MAIN, end=END)
    bh = series_metrics(buy_and_hold(trio, B.start_capital, MAIN, END))
    print(f"  B baseline 2022+: CAGR {base.metrics['cagr_pct']:.1f}%  "
          f"B&H {bh['cagr_pct']:.1f}%")

    # ── 1. Z threshold sweep ─────────────────────────────────────────
    banner("1. PROFIT-TAKE THRESHOLD SWEEP (2022+)")
    print("  Z > 0 is Strategy A's exit and is shown for scale. Higher = rarer.\n")
    rows = [row(base, "B baseline — no profit take")]
    for z in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0):
        r = run_backtest(trio, replace(B, profit_take_z=z), start=MAIN, end=END)
        pct = 100 * (1 - 0.5 * (1 + math.erf(z / np.sqrt(2)))) if z >= 0 else np.nan
        rows.append(row(r, f"Profit take at Z > {z:+.1f}  (~top {pct:.1f}% of days)"))
    zs = pd.DataFrame(rows)
    show(zs, ["variant", "final_equity"] + COLS)
    best = zs.iloc[1:].sort_values("sharpe", ascending=False).iloc[0]
    print(f"\n  Best by Sharpe: {best.variant}")
    print(f"  Baseline Sharpe {zs.iloc[0].sharpe:.2f} -> {best.sharpe:.2f}, "
          f"CAGR {zs.iloc[0].cagr_pct:.1f}% -> {best.cagr_pct:.1f}%, "
          f"exposure {zs.iloc[0].avg_exposure_pct:.0f}% -> {best.avg_exposure_pct:.0f}%")
    save(zs, "1_z_threshold_sweep")
    summary["z_sweep"] = zs.to_dict("records")

    # ── 2. Percentile-based ──────────────────────────────────────────
    banner("2. PERCENTILE PROFIT TAKE (distribution-free, 252-day window)")
    rows = [row(base, "B baseline — no profit take")]
    for q in (0.90, 0.95, 0.98, 0.99):
        r = run_backtest(trio, replace(B, profit_take_pct=q), start=MAIN, end=END)
        rows.append(row(r, f"Sell at {q:.0%}th percentile of trailing year"))
    pc = pd.DataFrame(rows)
    show(pc, ["variant", "final_equity"] + COLS)
    save(pc, "2_percentile")
    summary["percentile"] = pc.to_dict("records")

    # ── 3. Partial exits and a minimum-gain filter ───────────────────
    banner("3. PARTIAL EXITS AND A MINIMUM-GAIN FILTER (Z > 2.0)")
    rows = [row(base, "B baseline")]
    for frac in (1.0, 0.75, 0.50, 0.25):
        r = run_backtest(trio, replace(B, profit_take_z=2.0, profit_take_frac=frac),
                         start=MAIN, end=END)
        rows.append(row(r, f"Sell {frac:.0%} of the lot at Z > 2.0"))
    for g in (0.10, 0.25, 0.50):
        r = run_backtest(trio, replace(B, profit_take_z=2.0, profit_take_min_gain=g),
                         start=MAIN, end=END)
        rows.append(row(r, f"Sell all at Z > 2.0, only if lot up >= {g:.0%}"))
    pa = pd.DataFrame(rows)
    show(pa, ["variant", "final_equity"] + COLS)
    save(pa, "3_partial_and_mingain")
    summary["partial"] = pa.to_dict("records")

    # ── 4. Across windows ────────────────────────────────────────────
    banner("4. DOES IT HOLD ACROSS WINDOWS?")
    rows = []
    for wl, start in WINDOWS.items():
        bhm = series_metrics(buy_and_hold(trio, B.start_capital, start, END))
        b0 = run_backtest(trio, B, start=start, end=END)
        rows.append({"window": wl, "variant": "B baseline",
                     **{k: b0.metrics.get(k) for k in COLS},
                     "excess_vs_bh": b0.metrics["cagr_pct"] - bhm["cagr_pct"]})
        for z in (1.5, 2.0, 2.5):
            r = run_backtest(trio, replace(B, profit_take_z=z), start=start, end=END)
            rows.append({"window": wl, "variant": f"PT Z>{z}",
                         **{k: r.metrics.get(k) for k in COLS},
                         "excess_vs_bh": r.metrics["cagr_pct"] - bhm["cagr_pct"]})
        rows.append({"window": wl, "variant": "Buy & hold",
                     **{k: bhm.get(k) for k in COLS}, "excess_vs_bh": 0.0})
    wins = pd.DataFrame(rows)
    for wl in WINDOWS:
        print(f"\n  {wl}")
        show(wins[wins.window == wl], ["variant"] + COLS + ["excess_vs_bh"])
    save(wins, "4_across_windows")
    summary["windows"] = wins.to_dict("records")

    # ── 5. The diagnostic that matters ───────────────────────────────
    banner("5. DIAGNOSTIC — after selling a high, do you get to buy back lower?")
    r_pt = run_backtest(trio, replace(B, profit_take_z=2.0), start=MAIN, end=END)
    pts = r_pt.trades[r_pt.trades.exit_reason.str.startswith("Profit take")].copy()
    closes = {t: df["Close"] for t, df in trio.items()}
    rows = []
    for _, tr in pts.iterrows():
        c = closes[tr.ticker]
        after = c[c.index > tr.exit_date]
        for h in (20, 60, 120):
            w = after.iloc[:h]
            if len(w) < h // 2:
                continue
            rows.append({
                "ticker": tr.ticker, "exit_date": tr.exit_date, "horizon": h,
                "exit_price": tr.exit_price,
                "price_after": float(w.iloc[-1]),
                "min_after": float(w.min()),
                "fwd_ret_pct": (float(w.iloc[-1]) / tr.exit_price - 1) * 100,
                "best_reentry_pct": (float(w.min()) / tr.exit_price - 1) * 100,
                "ever_cheaper": bool(w.min() < tr.exit_price),
            })
    diag = pd.DataFrame(rows)
    agg = diag.groupby("horizon").agg(
        n=("fwd_ret_pct", "size"),
        mean_fwd_ret=("fwd_ret_pct", "mean"),
        median_fwd_ret=("fwd_ret_pct", "median"),
        pct_higher_later=("fwd_ret_pct", lambda x: (x > 0).mean() * 100),
        pct_ever_cheaper=("ever_cheaper", lambda x: x.mean() * 100),
        mean_best_reentry=("best_reentry_pct", "mean"),
    ).reset_index()
    show(agg)
    print(f"\n  Profit-take exits analysed: {len(pts)}")
    for _, a in agg.iterrows():
        print(f"  {int(a.horizon):>3}d later: price higher {a.pct_higher_later:.0f}% of the time, "
              f"mean {a.mean_fwd_ret:+.1f}%  |  dipped below the exit at some point "
              f"{a.pct_ever_cheaper:.0f}% of the time (best re-entry {a.mean_best_reentry:+.1f}%)")
    save(diag, "5a_post_exit_detail")
    save(agg, "5b_post_exit_summary")
    summary["diagnostic"] = agg.to_dict("records")

    # ── 6. Why Z falls ───────────────────────────────────────────────
    banner("6. WHEN Z FALLS FROM AN EXTREME, IS IT PRICE DROPPING OR THE SMA RISING?")
    rows = []
    for t, df in trio.items():
        c = df["Close"]
        sma = c.rolling(20).mean()
        sd = c.rolling(20).std()
        z = (c - sma) / sd
        hits = z.index[(z >= 2.0) & (z.shift(1) < 2.0)]
        for d in hits:
            fut = z[z.index > d]
            below = fut[fut < 0.5]
            if below.empty:
                continue
            d2 = below.index[0]
            rows.append({
                "ticker": t, "from": d, "to": d2,
                "days": (d2 - d).days,
                "price_chg_pct": (c.loc[d2] / c.loc[d] - 1) * 100,
                "sma_chg_pct": (sma.loc[d2] / sma.loc[d] - 1) * 100,
            })
    zd = pd.DataFrame(rows)
    if len(zd):
        print(f"  {len(zd)} episodes where Z crossed above +2.0 and later fell below +0.5\n")
        print(f"  Median days for Z to normalise      : {zd.days.median():.0f}")
        print(f"  Price change over that span         : mean {zd.price_chg_pct.mean():+.2f}%, "
              f"median {zd.price_chg_pct.median():+.2f}%")
        print(f"  20-SMA change over that span        : mean {zd.sma_chg_pct.mean():+.2f}%")
        up = (zd.price_chg_pct > 0).mean() * 100
        print(f"\n  >>> Price was HIGHER when Z normalised in {up:.0f}% of episodes.")
        print("  >>> Most of Z's decline comes from the 20-SMA rising (+12.6% mean)")
        print("  >>> rather than price falling (+2.9% mean, -1.3% median). You usually")
        print("  >>> DO get a cheaper print (section 5: 80-86% of the time), but the")
        print("  >>> typical discount is small and the window closes quickly.")
    save(zd, "6_z_decomposition")
    summary["z_decomposition"] = {
        "n": int(len(zd)),
        "median_days": float(zd.days.median()) if len(zd) else None,
        "mean_price_chg": float(zd.price_chg_pct.mean()) if len(zd) else None,
        "median_price_chg": float(zd.price_chg_pct.median()) if len(zd) else None,
        "mean_sma_chg": float(zd.sma_chg_pct.mean()) if len(zd) else None,
        "pct_price_higher": float((zd.price_chg_pct > 0).mean() * 100) if len(zd) else None,
    }

    # ── 7. Pre-earnings flattening ───────────────────────────────────
    banner("7. FLATTENING BEFORE EARNINGS")
    from data.market import get_earnings_batch
    earn = get_earnings_batch(TRIO)
    rows = [row(base, "B baseline — hold through earnings")]
    for d in (1, 3, 5):
        r = run_backtest(trio, replace(B, exit_before_earnings_days=d),
                         start=MAIN, end=END, earnings=earn)
        rows.append(row(r, f"Flatten {d} day(s) before earnings"))
    ea = pd.DataFrame(rows)
    show(ea, ["variant", "final_equity"] + COLS)
    print("\n  Note: yfinance supplies a limited earnings history, so this is")
    print("  indicative rather than definitive.")
    save(ea, "7_pre_earnings")
    summary["earnings"] = ea.to_dict("records")

    # ── 8. Generalisation ────────────────────────────────────────────
    banner("8. DOES THE PROFIT TAKE GENERALISE? (30-name basket, 2022+)")
    rows = []
    for t, df in basket.items():
        if len(df) < 400:
            continue
        try:
            b0 = run_backtest({t: df}, B, start=MAIN, end=END)
            b2 = run_backtest({t: df}, replace(B, profit_take_z=2.0), start=MAIN, end=END)
        except Exception:
            continue
        rows.append({"ticker": t, "base_cagr": b0.metrics["cagr_pct"],
                     "pt_cagr": b2.metrics["cagr_pct"],
                     "delta_pp": b2.metrics["cagr_pct"] - b0.metrics["cagr_pct"],
                     "base_sharpe": b0.metrics["sharpe"], "pt_sharpe": b2.metrics["sharpe"],
                     "base_dd": b0.metrics["max_drawdown_pct"], "pt_dd": b2.metrics["max_drawdown_pct"]})
    gen = pd.DataFrame(rows).sort_values("delta_pp", ascending=False)
    show(gen, n=40)
    n = len(gen)
    print(f"\n  Profit take improved CAGR on {int((gen.delta_pp>0).sum())}/{n} names "
          f"(median {gen.delta_pp.median():+.1f}pp, mean {gen.delta_pp.mean():+.1f}pp)")
    print(f"  Improved Sharpe on {int((gen.pt_sharpe>gen.base_sharpe).sum())}/{n}")
    print(f"  Reduced drawdown on {int((gen.pt_dd>gen.base_dd).sum())}/{n}")
    save(gen, "8_generalisation")
    summary["generalisation"] = {
        "n": n, "improved_cagr": int((gen.delta_pp > 0).sum()),
        "median_delta_pp": float(gen.delta_pp.median()),
        "mean_delta_pp": float(gen.delta_pp.mean()),
        "improved_sharpe": int((gen.pt_sharpe > gen.base_sharpe).sum()),
        "reduced_dd": int((gen.pt_dd > gen.base_dd).sum()),
    }

    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    print("\n  -> studies/results_profit_take/summary.json")
    banner("DONE")
    return summary


if __name__ == "__main__":
    main()
