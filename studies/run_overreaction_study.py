"""
Overreaction event study — runner.

Tests the Chan (2003) / Savor (2012) news-vs-no-news split and the
Bernard & Thomas (1989) post-earnings drift on this repo's own universe,
using the three tags that are orthogonal to Z(20):

  1. volume on the dip bar      (news proxy, needs no news data)
  2. earnings proximity          (news, precisely dated)
  3. idiosyncratic Z             (name-specific vs market-wide decline)

The question this settles before any LLM work is attempted:
does the CAUSE of a dip predict its forward return on this universe?
If it does not, classifying causes with a language model is pointless.

    python studies/run_overreaction_study.py

Writes studies/results_overreaction/.
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
    add_indicators, attach_earnings, cohort_table, diff_test,
    extract_events, load_earnings, load_prices, monthly_tstat,
)

RESULTS = ROOT / "studies" / "results_overreaction"
RESULTS.mkdir(parents=True, exist_ok=True)

WARMUP = "2014-06-01"   # 120d beta + 20d Z need a run-up
START = "2015-01-01"    # first bar an event may be recorded on
END = "2026-08-22"
Z_ENTRY = -1.2

summary: dict = {}


def banner(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def show(df: pd.DataFrame, n: int = 40) -> None:
    with pd.option_context("display.width", 210, "display.max_columns", 40,
                           "display.float_format", lambda v: f"{v:,.2f}"):
        print(df.head(n).to_string(index=False))


def save(df: pd.DataFrame, name: str) -> None:
    p = RESULTS / f"{name}.csv"
    df.to_csv(p, index=False)
    print(f"  -> {p.relative_to(ROOT)}")


def main() -> None:
    banner("0. DATA")
    prices = load_prices(UNIVERSE + [BENCHMARK], WARMUP, END)
    print(f"  prices: {len(prices)}/{len(UNIVERSE) + 1} names")
    if BENCHMARK not in prices:
        raise SystemExit("benchmark download failed")

    tickers = [t for t in prices if t != BENCHMARK]
    print("  earnings: downloading (cached after first run)...")
    earnings = load_earnings(tickers)
    have_earn = sum(1 for t in tickers if len(earnings.get(t, [])) > 0)
    print(f"  earnings: {have_earn}/{len(tickers)} names with history")

    spy = prices[BENCHMARK]
    frames = {BENCHMARK: add_indicators(spy, spy)}
    for t in tickers:
        d = add_indicators(prices[t], spy)
        d = attach_earnings(d, earnings.get(t))
        frames[t] = d

    banner("1. EVENTS")
    ev = extract_events(frames, z_entry=Z_ENTRY, start=START)
    print(f"  {len(ev):,} dip events (Z crossing below {Z_ENTRY}) "
          f"across {ev.ticker.nunique()} names, {ev.date.min().date()} -> {ev.date.max().date()}")
    print(f"  events per name per year: {len(ev) / ev.ticker.nunique() / 11.6:.1f}")
    save(ev, "1_events")

    # ---- baseline: what does an untagged dip do? -----------------------
    banner("2. BASELINE — the untagged dip (this is what Method A/B buys)")
    base_rows = []
    for h in HORIZONS:
        st = monthly_tstat(ev, f"exc_{h}")
        raw = monthly_tstat(ev, f"fwd_{h}")
        base_rows.append({
            "horizon_days": h, "n": st["n"], "n_months": st["n_months"],
            "raw_mean_pct": raw["mean"],
            "excess_mean_pct": st["mean"], "excess_median_pct": st["median"],
            "t": st["t"], "ci_lo": st["ci_lo"], "ci_hi": st["ci_hi"],
            "hit_rate_pct": st["hit_rate"],
        })
    base = pd.DataFrame(base_rows)
    show(base)
    save(base, "2_baseline")
    summary["baseline"] = base.to_dict("records")

    # ---- 3. the Chan test: volume as a news proxy ----------------------
    banner("3. CHAN (2003) TEST A — volume on the dip bar as a news proxy")
    q = ev.vol_ratio.quantile([0.33, 0.67])
    lo, hi = float(q.iloc[0]), float(q.iloc[1])
    print(f"  volume terciles: low < {lo:.2f}x median, high > {hi:.2f}x median")
    ev["vol_bucket"] = pd.cut(
        ev.vol_ratio, [-np.inf, lo, hi, np.inf],
        labels=["1_low_vol_(no-news)", "2_mid_vol", "3_high_vol_(news)"],
    )
    vt = cohort_table(ev.dropna(subset=["vol_bucket"]), "vol_bucket")
    show(vt)
    save(vt, "3_volume_cohorts")

    vol_diffs = []
    for h in HORIZONS:
        vol_diffs.append(diff_test(
            ev, ev.vol_bucket == "1_low_vol_(no-news)",
            ev.vol_bucket == "3_high_vol_(news)",
            f"exc_{h}", f"low_vol - high_vol @ {h}d",
        ))
    vd = pd.DataFrame(vol_diffs)
    print("\n  Paired by month (removes the common market factor):")
    show(vd)
    save(vd, "3b_volume_difference")
    summary["volume_difference"] = vd.to_dict("records")

    # ---- 4. the Chan test: earnings proximity --------------------------
    banner("4. CHAN TEST B / PEAD — dips near an earnings report vs away from one")
    dse = ev.days_since_earnings
    ev["earn_bucket"] = np.select(
        [dse <= 5, (dse > 5) & (dse <= 20), dse > 20],
        ["1_post_earnings_(0-5d)", "2_recent_(6-20d)", "3_no_earnings_(>20d)"],
        default="4_unknown",
    )
    et = cohort_table(ev[ev.earn_bucket != "4_unknown"], "earn_bucket")
    show(et)
    save(et, "4_earnings_cohorts")

    earn_diffs = []
    for h in HORIZONS:
        earn_diffs.append(diff_test(
            ev, ev.earn_bucket == "3_no_earnings_(>20d)",
            ev.earn_bucket == "1_post_earnings_(0-5d)",
            f"exc_{h}", f"no-news - post-earnings @ {h}d",
        ))
    ed = pd.DataFrame(earn_diffs)
    print("\n  Paired by month:")
    show(ed)
    save(ed, "4b_earnings_difference")
    summary["earnings_difference"] = ed.to_dict("records")

    # ---- 4c. PEAD proper: split post-earnings dips by the surprise -----
    banner("4c. PEAD — post-earnings dips split by the EPS surprise itself")
    pe = ev[(ev.earn_bucket == "1_post_earnings_(0-5d)") & ev.eps_surprise_pct.notna()].copy()
    if len(pe) > 40:
        pe["surprise_bucket"] = np.where(
            pe.eps_surprise_pct < 0, "1_miss", "2_beat")
        pt = cohort_table(pe, "surprise_bucket")
        show(pt)
        save(pt, "4c_pead_surprise")
        pd_diffs = [diff_test(pe, pe.surprise_bucket == "2_beat",
                              pe.surprise_bucket == "1_miss",
                              f"exc_{h}", f"beat - miss @ {h}d") for h in HORIZONS]
        pdd = pd.DataFrame(pd_diffs)
        print("\n  Paired by month (positive => PEAD: beats drift up vs misses):")
        show(pdd)
        save(pdd, "4d_pead_difference")
        summary["pead_difference"] = pdd.to_dict("records")
    else:
        print(f"  only {len(pe)} post-earnings dips with a surprise figure — skipping")

    # ---- 5. idiosyncratic vs market-wide dips --------------------------
    banner("5. IDIOSYNCRATIC Z — is the name down, or is everything down?")
    sub = ev.dropna(subset=["idio_z"]).copy()
    qq = sub.idio_z.quantile([0.33, 0.67])
    ilo, ihi = float(qq.iloc[0]), float(qq.iloc[1])
    print(f"  idio_z terciles: strongly idiosyncratic < {ilo:.2f}, market-wide > {ihi:.2f}")
    sub["idio_bucket"] = pd.cut(
        sub.idio_z, [-np.inf, ilo, ihi, np.inf],
        labels=["1_idiosyncratic_drop", "2_mid", "3_market_wide_drop"],
    )
    it = cohort_table(sub, "idio_bucket")
    show(it)
    save(it, "5_idio_cohorts")

    idio_diffs = [diff_test(
        sub, sub.idio_bucket == "1_idiosyncratic_drop",
        sub.idio_bucket == "3_market_wide_drop",
        f"exc_{h}", f"idiosyncratic - market-wide @ {h}d") for h in HORIZONS]
    idd = pd.DataFrame(idio_diffs)
    print("\n  Paired by month:")
    show(idd)
    save(idd, "5b_idio_difference")
    summary["idio_difference"] = idd.to_dict("records")

    # ---- 6. breadth ----------------------------------------------------
    banner("6. BREADTH — how much of the universe was dipping that day?")
    bq = ev.breadth.quantile([0.33, 0.67])
    blo, bhi = float(bq.iloc[0]), float(bq.iloc[1])
    ev["breadth_bucket"] = pd.cut(
        ev.breadth, [-np.inf, blo, bhi, np.inf],
        labels=[f"1_lonely_(<{blo:.0%})", "2_mid", f"3_everything_(>{bhi:.0%})"],
    )
    bt = cohort_table(ev.dropna(subset=["breadth_bucket"]), "breadth_bucket")
    show(bt)
    save(bt, "6_breadth_cohorts")

    # ---- 7. the 2x2 that is the actual Chan test -----------------------
    banner("7. THE 2x2 — news (high vol OR post-earnings) x idiosyncratic")
    ev["is_news"] = (ev.vol_bucket == "3_high_vol_(news)") | (ev.days_since_earnings <= 5)
    ev["is_idio"] = ev.idio_z <= ilo
    ev["quad"] = np.where(
        ev.is_news,
        np.where(ev.is_idio, "A_news_+_idiosyncratic", "B_news_+_market"),
        np.where(ev.is_idio, "C_nonews_+_idiosyncratic", "D_nonews_+_market"),
    )
    qt = cohort_table(ev, "quad")
    show(qt)
    save(qt, "7_quadrants")
    summary["quadrants"] = qt.to_dict("records")

    quad_diffs = [diff_test(
        ev, ev.quad == "C_nonews_+_idiosyncratic",
        ev.quad == "A_news_+_idiosyncratic",
        f"exc_{h}", f"no-news idio - news idio @ {h}d") for h in HORIZONS]
    qd = pd.DataFrame(quad_diffs)
    print("\n  The Chan hypothesis, paired by month "
          "(positive => no-news dips reverse harder than news dips):")
    show(qd)
    save(qd, "7b_quadrant_difference")
    summary["quadrant_difference"] = qd.to_dict("records")

    # ---- 8. does it survive out of sample? -----------------------------
    banner("8. SPLIT-SAMPLE — first half vs second half")
    mid = ev.date.quantile(0.5)
    print(f"  split at {pd.Timestamp(mid).date()}")
    halves = []
    for name, mask in [("1_first_half", ev.date <= mid), ("2_second_half", ev.date > mid)]:
        part = ev[mask]
        for h in (20, 60):
            d1 = diff_test(part, part.vol_bucket == "1_low_vol_(no-news)",
                           part.vol_bucket == "3_high_vol_(news)",
                           f"exc_{h}", f"{name}: low-vol - high-vol @ {h}d")
            d2 = diff_test(part, part.earn_bucket == "3_no_earnings_(>20d)",
                           part.earn_bucket == "1_post_earnings_(0-5d)",
                           f"exc_{h}", f"{name}: no-earn - post-earn @ {h}d")
            halves.extend([d1, d2])
    hf = pd.DataFrame(halves)
    show(hf)
    save(hf, "8_split_sample")
    summary["split_sample"] = hf.to_dict("records")

    # ---- 9. the actionable screen --------------------------------------
    banner("9. THE SCREEN — best combination vs the untagged dip")
    screens = {
        "untagged dip (Method A/B entry)": pd.Series(True, index=ev.index),
        "+ low volume": ev.vol_bucket == "1_low_vol_(no-news)",
        "+ no earnings within 20d": ev.earn_bucket == "3_no_earnings_(>20d)",
        "+ idiosyncratic": ev.is_idio,
        "+ low vol & no earnings": (ev.vol_bucket == "1_low_vol_(no-news)")
                                   & (ev.earn_bucket == "3_no_earnings_(>20d)"),
        "+ low vol & no earnings & idio": (ev.vol_bucket == "1_low_vol_(no-news)")
                                          & (ev.earn_bucket == "3_no_earnings_(>20d)")
                                          & ev.is_idio,
        "NEWS dip (high vol or post-earn)": ev.is_news,
    }
    rows = []
    for label, mask in screens.items():
        part = ev[mask.fillna(False)]
        r = {"screen": label, "n": len(part),
             "pct_of_events": 100 * len(part) / len(ev)}
        for h in HORIZONS:
            st = monthly_tstat(part, f"exc_{h}")
            r[f"exc_{h}"] = st["mean"]
            r[f"t_{h}"] = st["t"]
        rows.append(r)
    sc = pd.DataFrame(rows)
    show(sc)
    save(sc, "9_screens")
    summary["screens"] = sc.to_dict("records")

    with open(RESULTS / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n  -> {(RESULTS / 'summary.json').relative_to(ROOT)}")

    banner("DONE")


if __name__ == "__main__":
    main()
