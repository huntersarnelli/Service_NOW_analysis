# 05 — Momentum as a holding rule

**Status:** PRE-REGISTRATION. The rules below were written and committed **before any
momentum return was computed**. Results are appended later in §6; §1–§5 do not change.

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

*(Appended after the run. Nothing above this line changes.)*
