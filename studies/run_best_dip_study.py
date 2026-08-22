"""
Best-dip study — what does a good dip look like, and does screening for one
actually put more money in your pocket?

Two gaps this closes
--------------------
1. OVERREACTION_STUDY.md §7's screen table tested "+ idiosyncratic" -- the
   WORSE side of the idiosyncratic/market-wide split. The better side
   (market-wide declines) was measured in §5 but never screened, and neither
   was breadth. So the best available combination was never actually tried.

2. Every screen so far was measured as forward excess return per event. That is
   the right way to test a signal and the wrong way to test a STRATEGY. The
   strategy this project has converged on is: hold the basket, never sell,
   deploy new money into dips. So the screens have to be tested as DEPLOYMENT
   rules on contributed cash, which is what §5.22 did for the unfiltered dip
   signal and found its most robust result (+20.2%).

Part 2 is the one that matters. A screen that raises per-event excess but fires
so rarely that contributions sit in cash for months can easily lose to plain
scheduled investing -- the cash drag eats the edge. Forcing deployment after
`max_cash_months` is what keeps that honest, exactly as §5.22 did.

    python studies/run_best_dip_study.py

Writes studies/results_best_dip/.
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

RESULTS = ROOT / "studies" / "results_best_dip"
RESULTS.mkdir(parents=True, exist_ok=True)

WARMUP, START, END = "2014-06-01", "2015-01-01", "2026-08-22"
Z_ENTRY = -1.2

# Deployment windows. 2015+ is the full history the event study uses; the
# others are carried over from STRATEGY_REVIEW.md for comparability.
DEPLOY_WINDOWS = {"2015+": "2015-01-01", "2020+": "2020-01-02", "2022+": "2022-01-03"}

summary: dict = {}


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


# ═════════════════════════════════════════════════════════════
# PART 1 — the screens, this time including the good side
# ═════════════════════════════════════════════════════════════
def part_1_screens(ev: pd.DataFrame) -> pd.DataFrame:
    banner("1. SCREENS — including the market-wide and breadth cuts never tested")

    iq = ev.idio_z.quantile([0.33, 0.67])
    ilo, ihi = float(iq.iloc[0]), float(iq.iloc[1])
    bq = ev.breadth.quantile([0.33, 0.67])
    blo, bhi = float(bq.iloc[0]), float(bq.iloc[1])
    vq = ev.vol_ratio.quantile(0.33)
    vlo = float(vq)

    no_earn = ev.days_since_earnings > 20
    mkt_wide = ev.idio_z > ihi          # the GOOD side -- market dragged it down
    idio = ev.idio_z <= ilo             # the bad side, screened in §7 by mistake
    not_lonely = ev.breadth > blo       # lonely fallers were the worst cohort
    mid_breadth = (ev.breadth > blo) & (ev.breadth <= bhi)
    low_vol = ev.vol_ratio <= vlo

    screens = {
        "0. untagged dip (baseline)": pd.Series(True, index=ev.index),
        "1. no earnings within 20d": no_earn,
        "2. market-wide decline": mkt_wide,
        "3. not a lonely faller": not_lonely,
        "4. mid breadth": mid_breadth,
        "5. no-earn + market-wide": no_earn & mkt_wide,
        "6. no-earn + not lonely": no_earn & not_lonely,
        "7. no-earn + mid breadth": no_earn & mid_breadth,
        "8. no-earn + market-wide + not lonely": no_earn & mkt_wide & not_lonely,
        "9. no-earn + low vol (old best)": no_earn & low_vol,
        "X. idiosyncratic (the wrong side)": idio,
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
        r["hit_20"] = monthly_tstat(part, "exc_20")["hit_rate"]
        rows.append(r)

    df = pd.DataFrame(rows)
    show(df)
    save(df, "1_screens")
    summary["screens"] = df.to_dict("records")

    banner("1b. SPLIT-SAMPLE — do the best screens hold in both halves?")
    mid = ev.date.quantile(0.5)
    rows = []
    for label, mask in screens.items():
        m = mask.fillna(False)
        r = {"screen": label}
        for half, hm in [("first", ev.date <= mid), ("second", ev.date > mid)]:
            part = ev[m & hm]
            base = ev[hm]
            st = monthly_tstat(part, "exc_20")
            bs = monthly_tstat(base, "exc_20")
            r[f"{half}_exc20"] = st["mean"]
            r[f"{half}_vs_base"] = st["mean"] - bs["mean"]
            r[f"{half}_n"] = st["n"]
        r["both_halves_positive"] = bool(
            r["first_vs_base"] > 0 and r["second_vs_base"] > 0)
        rows.append(r)
    sp = pd.DataFrame(rows)
    show(sp)
    save(sp, "1b_split_sample")
    summary["split_sample"] = sp.to_dict("records")
    return df


# ═════════════════════════════════════════════════════════════
# PART 2 — the screens as DEPLOYMENT rules
# ═════════════════════════════════════════════════════════════
def contribution_sim(
    frames: dict[str, pd.DataFrame],
    start: str,
    end: str,
    monthly: float = 1_000.0,
    mode: str = "dca",
    screen: str = "none",
    z_entry: float = Z_ENTRY,
    max_cash_months: int = 12,
    commission_bps: float = 5.0,
    thresholds: dict | None = None,
) -> pd.Series:
    """
    Contribute `monthly` on the first bar of each month, then deploy it.
    NOTHING IS EVER SOLD -- this isolates entry timing on new money, which is
    the one thing the null test showed the signal genuinely does.

    mode="dca"  invest immediately, equal-weight across the universe
    mode="dip"  hold as cash until a qualifying dip prints, then buy it.
                Cash is force-deployed after `max_cash_months` so a screen
                cannot win merely by sitting out of a rising market.

    `screen` narrows which dips qualify. This is the whole question: a tighter
    screen buys better entries but fires less often, and the cash drag from
    waiting has to be paid out of the improvement.
    """
    th = thresholds or {}
    calendar = pd.DatetimeIndex(sorted(set().union(*[set(d.index) for d in frames.values()])))
    calendar = calendar[(calendar >= pd.Timestamp(start)) & (calendar <= pd.Timestamp(end))]

    close = pd.DataFrame({t: d["Close"] for t, d in frames.items()}).reindex(calendar)
    zsc = pd.DataFrame({t: d["z"] for t, d in frames.items()}).reindex(calendar)
    idio = pd.DataFrame({t: d["idio_z"] for t, d in frames.items()}).reindex(calendar)
    dse = pd.DataFrame({t: d["days_since_earnings"] for t, d in frames.items()}).reindex(calendar)
    breadth = (zsc < z_entry).sum(axis=1) / zsc.notna().sum(axis=1)

    fee = commission_bps / 10_000.0
    cash = 0.0
    shares = {t: 0.0 for t in frames}
    pending_since = None
    equity, deploy_lags, n_deploys, n_forced = [], [], 0, 0

    month_starts = set(
        pd.Series(calendar).groupby([calendar.year, calendar.month]).min().values
    )

    for i, date in enumerate(calendar):
        if date.to_datetime64() in month_starts:
            cash += monthly
            if pending_since is None:
                pending_since = date

        if cash > 0:
            live = [t for t in frames if np.isfinite(close.iat[i, close.columns.get_loc(t)])]
            if live:
                if mode == "dca":
                    per = cash / len(live)
                    for t in live:
                        shares[t] += (per / (1 + fee)) / close.iat[i, close.columns.get_loc(t)]
                    cash = 0.0
                    pending_since = None
                else:
                    b = breadth.get(date, np.nan)
                    picks = []
                    for t in live:
                        z = zsc.iat[i, zsc.columns.get_loc(t)]
                        if pd.isna(z) or z >= z_entry:
                            continue
                        if screen in ("no_earn", "no_earn_mkt", "no_earn_not_lonely",
                                      "no_earn_mkt_breadth"):
                            e = dse.iat[i, dse.columns.get_loc(t)]
                            if pd.isna(e) or e <= 20:
                                continue
                        if screen in ("mkt_wide", "no_earn_mkt", "no_earn_mkt_breadth"):
                            iz = idio.iat[i, idio.columns.get_loc(t)]
                            if pd.isna(iz) or iz <= th.get("idio_hi", -1.09):
                                continue
                        if screen in ("not_lonely", "no_earn_not_lonely",
                                      "no_earn_mkt_breadth"):
                            if pd.isna(b) or b <= th.get("breadth_lo", 0.18):
                                continue
                        picks.append(t)

                    stale = (pending_since is not None
                             and (date - pending_since).days >= max_cash_months * 30)
                    if picks:
                        per = cash / len(picks)
                        for t in picks:
                            shares[t] += (per / (1 + fee)) / close.iat[i, close.columns.get_loc(t)]
                        if pending_since is not None:
                            deploy_lags.append((date - pending_since).days)
                        n_deploys += 1
                        cash = 0.0
                        pending_since = None
                    elif stale:
                        per = cash / len(live)
                        for t in live:
                            shares[t] += (per / (1 + fee)) / close.iat[i, close.columns.get_loc(t)]
                        deploy_lags.append((date - pending_since).days)
                        n_forced += 1
                        cash = 0.0
                        pending_since = None

        mkt = 0.0
        for t in frames:
            px = close.iat[i, close.columns.get_loc(t)]
            if np.isfinite(px):
                mkt += shares[t] * px
        equity.append(cash + mkt)

    s = pd.Series(equity, index=calendar, name=mode)
    s.attrs["avg_deploy_lag_days"] = float(np.mean(deploy_lags)) if deploy_lags else 0.0
    s.attrs["n_deploys"] = n_deploys
    s.attrs["n_forced"] = n_forced
    return s


def part_2_deployment(frames: dict[str, pd.DataFrame], ev: pd.DataFrame) -> pd.DataFrame:
    banner("2. THE SCREENS AS DEPLOYMENT RULES — $1,000/month, nothing ever sold")

    th = {
        "idio_hi": float(ev.idio_z.quantile(0.67)),
        "breadth_lo": float(ev.breadth.quantile(0.33)),
    }
    print(f"  thresholds: market-wide = idio_z > {th['idio_hi']:.2f}, "
          f"not-lonely = breadth > {th['breadth_lo']:.0%}")

    variants = [
        ("scheduled (DCA)", "dca", "none"),
        ("dip, unfiltered", "dip", "none"),
        ("dip + no earnings 20d", "dip", "no_earn"),
        ("dip + market-wide", "dip", "mkt_wide"),
        ("dip + not lonely", "dip", "not_lonely"),
        ("dip + no-earn + not lonely", "dip", "no_earn_not_lonely"),
        ("dip + no-earn + market-wide", "dip", "no_earn_mkt"),
        ("dip + no-earn + mkt + not lonely", "dip", "no_earn_mkt_breadth"),
    ]

    rows = []
    for win, start in DEPLOY_WINDOWS.items():
        base_final = None
        for label, mode, screen in variants:
            s = contribution_sim(frames, start, END, mode=mode, screen=screen,
                                 thresholds=th)
            months = len(pd.Series(s.index).groupby([s.index.year, s.index.month]).min())
            contributed = months * 1000.0
            final = float(s.iloc[-1])
            if base_final is None:
                base_final = final
            rows.append({
                "window": win, "variant": label,
                "contributed": contributed, "final_value": final,
                "multiple": final / contributed,
                "vs_dca_pct": 100 * (final / base_final - 1.0),
                "avg_wait_days": s.attrs["avg_deploy_lag_days"],
                "n_deploys": s.attrs["n_deploys"],
                "n_forced": s.attrs["n_forced"],
            })
        print(f"  {win}: {len(variants)} variants")

    df = pd.DataFrame(rows)
    for win in DEPLOY_WINDOWS:
        print(f"\n  --- {win} ---")
        show(df[df.window == win][["variant", "contributed", "final_value", "multiple",
                                   "vs_dca_pct", "avg_wait_days", "n_deploys", "n_forced"]])
    save(df, "2_deployment")

    print("\n  Mean advantage over scheduled investing, across the three windows:")
    agg = (df[df.variant != "scheduled (DCA)"]
           .groupby("variant")
           .agg(mean_vs_dca_pct=("vs_dca_pct", "mean"),
                worst_vs_dca_pct=("vs_dca_pct", "min"),
                windows_won=("vs_dca_pct", lambda s: int((s > 0).sum())),
                avg_wait_days=("avg_wait_days", "mean"),
                forced_deploys=("n_forced", "mean"))
           .reset_index()
           .sort_values("mean_vs_dca_pct", ascending=False))
    show(agg)
    save(agg, "2b_deployment_verdict")
    summary["deployment"] = agg.to_dict("records")
    return df


def main() -> None:
    banner("0. DATA")
    prices = load_prices(UNIVERSE + [BENCHMARK], WARMUP, END)
    tickers = [t for t in prices if t != BENCHMARK]
    earnings = load_earnings(tickers)
    spy = prices[BENCHMARK]
    frames = {BENCHMARK: add_indicators(spy, spy)}
    for t in tickers:
        frames[t] = attach_earnings(add_indicators(prices[t], spy), earnings.get(t))
    ev = extract_events(frames, z_entry=Z_ENTRY, start=START)
    print(f"  {len(ev):,} events, {ev.ticker.nunique()} names")

    stock_frames = {t: f for t, f in frames.items() if t != BENCHMARK}

    part_1_screens(ev)
    part_2_deployment(stock_frames, ev)

    with open(RESULTS / "summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n  -> {(RESULTS / 'summary.json').relative_to(ROOT)}")
    banner("DONE")


if __name__ == "__main__":
    main()
