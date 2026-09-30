# 05 — Momentum as a holding rule

**Status:** COMPLETE — **FAIL** (t = 1.80 vs 2.0; see §6). The rules in §1–§5 were committed
(2cd3cde) **before any momentum return was computed** and were not changed afterwards.

---

## 1. Question

Among liquid US stocks, does holding the stocks that rose most over the past year
(skipping the latest month) beat holding **randomly chosen stocks from the same
universe**, month after month, after trading costs?

**Why.** This is the most replicated anomaly in finance (Jegadeesh & Titman 1993;
Asness, Moskowitz & Pedersen 2013), and unlike insider buying it is documented in
large caps. This repo only ever tested momentum as a *gate on dip entries*
(DEAD_ENDS #3, which failed); as a *holding rule* it is untested. §5.13d of the
strategy review showed an unconfirmed out-of-sample hint.

**What a pass would change.** The Market tab would get a tested "what to hold"
tilt. The buy zone stays the rule for *when* to add cash.

## 2. Data

- **Prices:** yfinance daily history already cached by the insider-trading study
  (`C:\Users\hunte\insider-trading\data\raw\prices`, ~5,450 stocks). No new download.
  Adjusted close for returns; as-traded close (split adjustment undone) for the price floor.
- **Known bias (stated up front):** that cache holds only stocks that (a) had an
  insider open-market purchase of at least $10k in 2006–2026 and (b) still have Yahoo data.
  Delisted failures are mostly missing (survivor bias). This probably **flatters
  momentum**, because momentum buys stocks that have run up, and the ones that then
  collapsed and delisted are under-represented. **A pass is weaker evidence for that
  reason; a fail is strong evidence.**
- **Bad-print screen:** tickers with a one-day move of at least 4x up or at least 75% down that
  reverts within 5 trading days are excluded (the rule from the insider study).

## 3. Rules (fixed)

- **Calendar:** month-ends, using the SPY trading calendar. **Primary period:**
  portfolios formed at month-ends from **2006-01** to the last month with a full next month.
- **Eligible universe each month-end t** (only data available at t is used):
  1. as-traded close ≥ **$5**;
  2. at least **13 months** of price history (needed for the score);
  3. then the **200** most-traded stocks by 20-day average dollar volume (close × volume);
  4. SPY and QQQ are excluded (they are funds).
- **Momentum score:** return from month-end t−12 to month-end t−1 (the "12-1" definition;
  it skips the latest month, which tends to reverse).
- **Portfolio:** the **top 20** by score, equal-weight, held from month-end t to t+1, then rebalanced.
- **Holding return:** adjusted close at t+1 divided by adjusted close at t, minus 1. A stock with
  no price at t+1 (data ends) earns the return to its last available price in that month; if
  there is none at all, 0% (and the count is reported).
- **Trading costs:** **0.10% per side**, applied to the share of the portfolio replaced
  each month (turnover × 2 sides × 0.10%).
- **Control:** each month, **200 random portfolios** of 20 stocks drawn from the same
  eligible 200. The **edge** for month t is the momentum portfolio's return *net of costs*
  minus the average random-portfolio return (gross, a conservative comparison).
- **Statistics:** mean monthly edge; t-statistic on the monthly edges (months are the
  unit, so there is no clustering problem); split halves (first vs second half of months);
  and an empirical p-value: the share of the 200 random portfolios, compounded over the whole
  period, that end above the momentum portfolio.
- **Also reported, not deciding:** the edge against SPY, QQQ and the equal-weight universe;
  maximum drawdown of each; the worst months (momentum is known for crashes such as 2009);
  turnover; top-10 and top-30 portfolios; 2013+ and 2020+ sub-periods; and a secondary
  universe of the 124 Deployment Desk names (labelled **hindsight-biased**, since those
  names were chosen in 2026 because they are big now).

## 4. Pass bar (fixed)

Momentum **passes** only if **all** of these hold for the primary test (top 20, 200-stock
universe, 2006+, net of costs, vs random):

| Criterion | Threshold |
|---|---|
| Mean monthly edge vs random | ≥ **+0.25pp per month** (~3pp a year) |
| t-statistic of monthly edges | ≥ **2.0** |
| Split halves | Edge positive in **both** halves |
| Sample | ≥ **120** months |

Otherwise it is a **fail**, recorded in DEAD_ENDS.md with the numbers. The secondary
universe, other portfolio sizes and sub-periods **cannot rescue a fail**.

## 5. What would be done with a pass

The Market tab gets a "top-ranked stocks this month" list, labelled with the test's
numbers and the survivor-bias caveat, and paper-tracked on the Track record tab before
any real money follows it.

---

## 6. Results

*(Appended after the run on 27 Sep 2026. Nothing above this line changed.)*

### **Verdict: FAIL.** A big but unreliable edge: t = 1.80 against a bar of 2.0 (`studies/results/12_momentum/criteria.csv`).

| Criterion (top 20 of 200, 2006-01 to 2026-08, net of costs, vs random) | Result | Pass |
|---|---|---|
| Mean monthly edge ≥ +0.25pp | **+0.70pp** | ✅ |
| t ≥ 2.0 | **1.80** | ❌ |
| Positive in both halves | +0.04 / +1.36 | ✅ (the first half is ≈ 0) |
| ≥ 120 months | 248 | ✅ |

**Where the edge comes from** (`summary.csv`, `edge_by_year.csv`, `monthly_primary.csv`):
- **Concentrated in a few years.** By year, the average monthly edge was:

  | Year | Edge per month |
  |---|---|
  | 2020 | **+7.0pp** (pandemic winners: TSLA, TTD, ROKU, AMD, NVAX) |
  | 2024 | +4.0pp |
  | 2025 | +2.5pp |
  | 2026 | +3.9pp (AI, quantum and nuclear leaders) |
  | 2006 | −1.2pp |
  | 2009 | −1.8pp (the classic momentum crash) |
  | 2021 | −3.3pp |

- **Excluding 2020:** +0.38pp a month, **t = 1.0**. The median month is +0.41pp, and 54% of months beat random portfolios.
- **The first half (2006–2016) shows essentially no edge** (+0.04pp a month). The second half does (+1.36pp).

**What it's like to hold** (`summary.csv`, `worst_months.csv`):
- **Returns:** 16.4% a year after costs, against 11.1% for SPY. Against SPY that's +0.69pp a month; against QQQ, +0.30pp.
- **Worst drop: −62%**, against −51% for SPY and −54% for the equal-weight universe.
- **Crash months,** relative to the equal-weight universe:
  - one recent month lost 25.6% while the market was flat (−22pp relative);
  - October 2025 −15.8pp;
  - November 2021 −15.3pp;
  - March 2009 −12.7pp.
- **Turnover:** 35% a month.

**Exploratory results** (these can't rescue the fail):

| Variant | Edge per month | t |
|---|---|---|
| Top 10 | +1.14pp | 2.09 |
| Top 30 | +0.41pp | 1.32 |
| 2013 onward | +1.12pp | 2.11 |
| 2020 onward | +2.12pp | 2.06 |
| 124 Desk names (hindsight-biased) | +0.34pp | 1.55 |

Choosing whichever variant clears the bar after seeing results is exactly what pre-registration rules out.

**Data:** 5,460 cached stocks, of which 489 were excluded by the bad-print screen (`data_log.csv`). Spot-checked holdings in the extreme months were real names with plausible moves (e.g. TSLA +49% and TTD +52% in April 2020; RGTI +49% and QBTS +50% in October 2025).

### What this means

- **Not a reliable edge.** Momentum made money on average in this sample, but the result rests on a handful of speculative boom years. It has no measurable edge in 2006–2016 and crashes hard when leadership flips. The survivor bias in this data (§2) flatters momentum, and it *still* failed the bar.
- **The recent strength is real but regime-dependent.** Since 2020 it has ridden the pandemic, AI, quantum and nuclear leaders. That matches "where the market is looking", but that's a description of the recent past, not a rule that has held over time.
- **Dashboard:** the Market tab stays **information only**. No momentum tilt is added.
- **If revisited:** a fresh pre-registration on data that includes delisted stocks (e.g. CRSP), with a crash-protection rule defined in advance (for example, volatility scaling as in Barroso & Santa-Clara 2015). Don't re-run this data with tweaked settings.
