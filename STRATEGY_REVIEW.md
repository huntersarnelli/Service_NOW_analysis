# Strategy Review Package

**Repository:** `Service_NOW_analysis` — dip-buying systems on US large-cap tech
**Prepared:** 21 August 2026
**Purpose:** an independent, self-contained review packet. Everything needed to
critique the systems is in this document; the repository is only needed to
reproduce the numbers.

---

## 0. What I am asking for

Two long-only strategies are implemented and running in a live dashboard. One of
them (Strategy B) had documented performance claims that had **never been
reproducible** — the backtest code was not in the repository. I have now written
that harness and run a study. This document records:

- exactly how a trade works in each system,
- what the backtest actually found,
- where I think the claims break down.

Five studies are included: the baseline reproduction (§5.1–5.11), attempts to
improve the rules (§5.12–5.13), a regime study extending the history through the
2022 bear (§5.14–5.19), a window-sensitivity and deployment study (§5.20–5.22),
and an allocation study (§5.23).

**The conclusion depends heavily on the window, and §5.20 is the section to read
first.** Over 2020–2026 the strategy loses to buy-and-hold by 6.7pp; over 2022–2026
it beats it on every metric. Neither result is statistically established.

**I would like a second opinion on the conclusions in §7 and the open questions
in §8.** Specifically: am I reading the selection-bias and walk-forward evidence
correctly, and is there a defensible version of this strategy left?

Please be adversarial. The author has real money at stake and would rather be
told the edge is illusory now than discover it later.

---

## 1. The two systems at a glance

Both are long-only, daily-bar, single-signal systems on the same idea: buy a
statistically stretched dip in a large-cap tech name. They differ almost
entirely in **how they exit**.

| | **A — Dual-Mode Tactical** | **B — Aggressive Dip Accumulation** |
|---|---|---|
| Universe | Momentum: NVDA, META, NET<br>Quality: NOW, MSFT, GOOGL, PANW, CRWD, DDOG, CRM | META, NVDA, NET<br>(live dashboard also runs DDOG) |
| Entry | Z(20) < −1.5 | Z(20) < −1.2 |
| Position size | all-in, one name at a time (backtests)<br>1%-risk reference (dashboard) | 20% of *current* equity per lot |
| Pyramiding | no | yes — multiple lots per name |
| Trailing stop | Close − 2×ATR(14), raise-only,<br>ATR **re-read daily** | Highest close since that lot's entry − 4×ATR(14),<br>ATR **frozen at entry** |
| Mean-reversion exit | **yes** — exit when Z > 0 | **no** — deliberately removed |
| Trend filter | optional Close > 50-SMA (Quality only, off by default) | none |
| Max exposure | 100% | 100% |

**The design thesis of B** is that A's `Z > 0` exit is the defect. A caps every
winner at roughly +1.5σ while risking 2×ATR to the downside — a structurally
sub-1:1 reward/risk that only survives on a very high win rate. B keeps the
mean-reversion *entry* and replaces the exit with a wide volatility trail so
winners can run.

That thesis is well-motivated by A's own evidence (§5.0), and §5.25 confirms it
quantitatively: the exit rule drives ~21pp of CAGR difference while the entry
threshold drives ~0.9pp. But see §5.26 — B wins on return capture, not on every
dimension, and A is not dominated.

---

## 2. How a trade works

### 2.1 The shared indicators

On daily closes `C`, for each name independently:

```
SMA₂₀   = 20-period simple moving average of Close
σ₂₀     = 20-period rolling standard deviation of Close
Z       = (C − SMA₂₀) / σ₂₀

TR      = max( High−Low, |High−C_prev|, |Low−C_prev| )
ATR₁₄   = 14-period simple average of TR
```

The **buy trigger price** — the price at which Z would equal the entry
threshold — is what the dashboard displays as an actionable level:

```
P_trigger = SMA₂₀ + (Z_entry × σ₂₀)
```

### 2.2 Strategy A — one trade, start to finish

1. **Entry.** On any bar where `Z < −1.5`, buy at that bar's close.
   (Optionally, for Quality names, also require `Close > 50-SMA`.)
2. **Initial stop.** `entry − 2 × ATR₁₄` at entry.
3. **Each subsequent bar,** raise the stop but never lower it:
   `stop_t = max(stop_{t−1}, C_t − 2 × ATR_t)`.
   Note ATR is re-read each bar, so the stop distance breathes with volatility.
4. **Exit** on whichever comes first:
   - `C_t ≤ stop_t` → "trail hit", or
   - `Z_t > 0` → "mean reversion complete", price is back at the 20-SMA.
5. Position is closed entirely. No pyramiding, no partial exits.

Because the reward is bounded by the distance from the trigger up to the SMA
(`1.5σ`) and the risk is `2 × ATR`, the reward/risk at entry is typically **below
1:1** — measured at 0.81:1 on NOW in the original notebooks.

### 2.3 Strategy B — one *lot*, start to finish

The unit is a **lot**, not a position. The same ticker can hold several
independent lots, each with its own entry price and its own stop.

1. **Entry.** On any bar where `Z < −1.2`, open a new lot at that bar's close,
   sized at **20% of current total equity** (cash + market value), subject to
   available cash and the 100% exposure cap.
2. **Freeze `ATR_entry`** — the ATR reading on the entry bar. This value is used
   for the life of the lot and never updated.
3. **Each subsequent bar,** track the highest close seen since *this lot* opened:
   ```
   H_t     = max(C_entry … C_t)
   stop_t  = H_t − 4 × ATR_entry
   ```
   The stop is monotonically non-decreasing because `H_t` is.
4. **Exit** when `C_t ≤ stop_t`. That is the only exit. There is no
   mean-reversion exit, no time stop, no profit target.
5. Other lots in the same name are unaffected — they exit on their own schedule.

### 2.4 A real worked example (best lot in the backtest)

```
NET — lot opened 2025-04-04
  Entry close        $97.08          (Z had dropped below −1.2)
  ATR₁₄ at entry     $7.10           → frozen for the life of the lot
  Equity at entry    ~$371,000       → 20% = $74,291 → 764.87 shares
  Initial stop       $97.08 − 4×7.10 = $68.68   (−29.3%)

  … price rallies. The stop ratchets up with each new high close:
  peak close         $253.30         (MFE +160.9%)
  stop at the peak   $253.30 − $28.40 = $224.90

  Exit 2025-11-13 at $213.54 — close fell below the ratcheted stop
  Held 223 calendar days (154 bars)
  P&L  +$88,958  (+119.7%)
```

And the worst lot, which shows the cost of the same mechanism:

```
NET — lot opened 2025-11-14 at $210.60, one day after the above exit
  ATR₁₄ at entry     $11.78 → stop $210.60 − $47.13 = $163.47
  Price never made a meaningful new high (MFE +1.4%)
  Exit 2026-02-05 at $163.05 — the *initial* stop, essentially untouched
  P&L  −$40,394  (−22.7%)
```

That pair is the strategy in miniature: a very wide stop that lets a winner run
223 days, and the same wide stop costing 22.7% when the entry is simply wrong.

### 2.5 Ambiguity in B's written spec — and why it matters

The strategy document says a lot is opened "on every new signal." When `Z`
stays below −1.2 for several consecutive days, that is ambiguous:

- **`every_bar`** — open a lot on each qualifying day.
- **`on_cross`** — open one only on the bar Z crosses down through the threshold.

This is not a detail. It is worth **34 percentage points of CAGR** (§5.3). I
tested both; the documented headline numbers only reproduce under `every_bar`.

---

## 3. Code and data provenance

| Component | Location | Status |
|---|---|---|
| Live dashboard (both strategies) | `app.py` | working |
| Shared data + indicators | `data/market.py` | working |
| Rule sets + open-lot evaluation | `data/strategies.py` | working, unit-tested |
| Portfolio tracker | `data/portfolio.py`, `ui/portfolio_tab.py` | working |
| **Strategy B backtest engine** | `studies/dip_backtest.py` | **new — written for this review** |
| **Study runner** | `studies/run_dip_study.py` | **new** |
| Results (CSV + JSON) | `studies/results/` | 16 files |
| Strategy A notebooks | `testing/test2.ipynb`, `test3.ipynb` | pre-existing |
| B's original claims | `Aggressive_Dip_Accumulation_Strategy.md` | **no code ever committed** |

**Data:** Yahoo Finance via `yfinance`, split/dividend adjusted (`auto_adjust=True`),
daily bars. Universe warm-up from 2022-09-01; study window 2023-01-03 → 2026-07-31
(896 trading bars).

**Known data caveats:** Yahoo adjusted closes are restated over time, so exact
reproduction may drift. Survivorship is not modelled — the basket in §5.7 is
today's list of large caps, which mildly favours the strategy there.

---

## 4. Backtest methodology

**Engine:** `studies/dip_backtest.py`. Portfolio-level, not single-name — lots
compete for one cash balance and position size is a fraction of an equity figure
that changes as the account grows.

**Bar sequence:** mark to market → check exits → check entries → record equity.
Exits precede entries so freed cash is redeployable the same day (the most
generous reading of the rules).

**Assumptions, stated explicitly:**

| Assumption | Value | Note |
|---|---|---|
| Fill price | that bar's close | signal and fill on the same bar |
| Commission | 5 bps per side | as documented |
| Slippage | none | defensible for these names at this size |
| Shares | fractional | matches the original notebooks |
| Leverage | none | cash constraint enforces ≤100% exposure |
| Same-day competing signals | targets scaled proportionally | removes ticker-ordering bias |
| Same-bar close-out | forbidden | a lot cannot exit on its opening bar |

**Known optimism in the model:** signal and fill on the same close means you
would need a market-on-close order placed before knowing the close. This is the
same convention the original notebooks used, so it is comparable, but it is
optimistic in absolute terms.

**Engine validation:** 27 assertions on synthetic fixtures — no trades on a flat
series, exposure never exceeds 100%, equity never goes negative, trail geometry
lands within 30% of `4×ATR` below the running peak, wider trails produce longer
holds, commissions reduce equity, determinism. All pass.

---

## 5. Results

### 5.0 The finding that motivated Strategy B

From Strategy A's own trade log on NOW (2020–2026):

```
Win rate 69.8%   Avg winner +6.36%   Avg loser −7.96%
```

Winning 70% of the time and barely making money is the signature of a truncated
right tail. The strategy document's §3.5 measured it directly: **95% of A's exits
went on to trade higher, median +53% left behind.** That is a real, well-evidenced
diagnosis, and B is the right response to it in principle.

Confirmed independently here: A's rules on NOW from 2020 return +18.1% CAGR, but
the *same rules* from 2025 return **−12.2%**, and across 17 names since 2025 A
beat buy-and-hold on only 8.

### 5.1 Does B's documented claim reproduce?

Documented rules, documented universe (META/NVDA/NET), documented window
(2023-01-03 → 2026-07-31), $100,000 start, 5 bps/side, `every_bar` pyramiding:

| Metric | Documented | Reproduced | Gap |
|---|---|---|---|
| Final equity | $931,543 | **$870,078** | −6.6% |
| Total return | +831.6% | +770.2% | −7.4% |
| CAGR | 86.8% | **83.3%** | −4.0% |
| Max drawdown | −31.1% | **−31.3%** | −0.7% |
| Sharpe (rf=0) | 1.83 | **1.71** | −6.7% |
| Avg % invested | 95.4% | **95.9%** | +0.5% |
| % days fully invested | 87.7% | 85.9% | −2.0% |
| Number of lots | 76 | **105** | +38% |
| Win rate | 57% | 54.3% | −4.8% |
| Avg holding period | 90 days | 91.4 days | +1.6% |

**Verdict: the claims are substantially honest.** Drawdown, exposure and holding
period reproduce almost exactly. The 6–7% shortfall in equity is consistent with
adjusted-close restatement and small implementation differences. The lot-count
gap (105 vs 76) is the pyramiding ambiguity from §2.5.

This is *not* a case of fabricated numbers. It is a case of correct numbers
that do not mean what they appear to mean.

### 5.2 Benchmarks — the first problem

| | Final equity | CAGR | Max DD | Sharpe | Calmar |
|---|---|---|---|---|---|
| **Aggressive Dip** | $870,078 | 83.3% | −31.3% | **1.707** | **2.661** |
| Equal-weight buy & hold, same 3 names | $819,647 | 80.3% | −34.1% | **1.753** | 2.351 |
| QQQ buy & hold | $263,600 | 31.2% | −22.8% | 1.448 | 1.371 |
| SPY buy & hold | $203,584 | 22.1% | −18.8% | 1.400 | 1.176 |

Against the same three stocks bought and held, the strategy adds **+3.0
percentage points of CAGR** and shows a **lower Sharpe ratio** (1.707 vs 1.753).
It wins on Calmar (shallower max drawdown), which is a genuine benefit.

The document claimed Sharpe 1.83 vs 1.77 in the strategy's favour. Reproduced,
that ordering **flips**. Three and a half years of a 90%+ invested, concentrated,
actively managed system produced ~3pp of excess CAGR and no risk-adjusted
improvement on the Sharpe measure.

### 5.3 Pyramiding mode — a 34-point spec ambiguity

| Mode | Final equity | CAGR | Max DD | Sharpe | Lots | Avg exposure |
|---|---|---|---|---|---|---|
| `every_bar` | $870,078 | 83.3% | −31.3% | 1.707 | 105 | 95.9% |
| `on_cross` | $420,752 | 49.6% | −29.8% | 1.391 | 83 | 80.8% |
| `none` | $406,398 | 48.1% | −21.0% | **1.822** | 39 | 60.6% |

An undocumented reading of one sentence swings CAGR from 48% to 83%. Note also
that `none` — the *least* aggressive variant — has the **best Sharpe of the
three**, at 60% average exposure.

That is the tell for what follows: return here is tracking exposure, not signal
quality.

### 5.4 Parameter surface — is −1.2 / 4×ATR really the optimum?

CAGR %, entry threshold (rows) × ATR multiple (columns):

| Z \ ATR | 2.0 | 3.0 | 3.5 | **4.0** | 4.5 | 5.0 | 6.0 |
|---|---|---|---|---|---|---|---|
| −2.0 | 24.8 | 51.5 | 64.7 | 66.7 | 66.3 | 49.7 | 55.6 |
| −1.8 | 34.9 | 47.6 | 61.8 | 68.6 | 63.2 | 53.2 | 60.1 |
| −1.5 | 50.1 | 60.3 | 72.4 | 70.7 | 70.2 | 64.5 | 67.7 |
| **−1.2** | 68.6 | 72.9 | 83.1 | **83.3** | **85.0** | 77.7 | 79.3 |
| −1.0 | 55.0 | 71.0 | 78.9 | 82.9 | 80.4 | 73.4 | 76.3 |
| −0.8 | 51.5 | 65.1 | 76.4 | 82.3 | 81.2 | 77.1 | 79.2 |
| −0.5 | 59.5 | 62.2 | 74.3 | 83.2 | 81.1 | 78.0 | 78.5 |

The documented cell ranks **2nd of 49**. Good — the parameters are genuinely near
the in-sample optimum, and the surface is a broad plateau rather than a spike,
which usually indicates robustness rather than curve-fitting.

**But one documented claim does not survive.** The strategy document's §3.5 step 6
states that loosening the entry to −1.0 or −0.8 "began to add lower-quality
signals and reduced performance." Reproduced, −1.0 gives 82.9%, −0.8 gives 82.3%,
and **−0.5 gives 83.2%** — statistically indistinguishable from −1.2's 83.3%.

The entry threshold is very nearly **irrelevant** across a 0.7σ range. A signal
whose threshold does not matter is not doing much work.

### 5.5 Position size — the mechanism revealed

| Alloc per lot | Final equity | CAGR | Max DD | Sharpe | Avg exposure |
|---|---|---|---|---|---|
| 10% | $763,306 | 76.7% | −30.7% | 1.697 | 92.5% |
| 15% | $802,980 | 79.2% | −31.5% | 1.667 | 94.8% |
| **20%** (documented) | $870,078 | 83.3% | −31.3% | 1.707 | 95.9% |
| 25% | $931,725 | 86.9% | −31.5% | 1.758 | 96.0% |
| 33% | $1,046,625 | 93.0% | −31.9% | 1.827 | 96.2% |
| 50% | $1,131,614 | 97.3% | −31.5% | 1.860 | 96.5% |
| 100% | $1,240,396 | 102.5% | −32.1% | 1.852 | 97.7% |

Return rises **monotonically** with allocation while max drawdown stays pinned
near −31%. There is no size at which the system degrades.

This is the clearest evidence in the whole study. If returns scale with exposure
and drawdown does not, the driver is **exposure to three stocks that went up**,
not timing. The 20% figure is not an optimum; it is just a number that keeps you
~96% invested in a bull market.

### 5.6 Universe variants

| Universe | CAGR | Buy & hold CAGR | Excess | Max DD | Lots |
|---|---|---|---|---|---|
| Documented: META/NVDA/NET | 83.3% | 80.3% | **+3.0pp** | −31.3% | 105 |
| Live dashboard: + DDOG | 85.6% | 73.0% | **+12.5pp** | −35.1% | 153 |
| Tactical 10-name | 58.7% | 55.8% | **+2.9pp** | −30.0% | 710 |

The dashboard's 4-name set beats *its own* buy-and-hold by more (+12.5pp), but at
a deeper drawdown. Excess return is +3pp on both 3-name and 10-name universes.

### 5.7 Selection bias — the decisive test

The same rules, run one name at a time, across 29 liquid large caps chosen for
being obvious 2022-era names rather than for how they performed:

| | Result |
|---|---|
| Names where the strategy beat buy & hold | **10 / 29 (34%)** |
| Names where it *lost* to buy & hold | **19 / 29 (66%)** |
| **Median excess CAGR** | **−2.2 pp** |
| **Mean excess CAGR** | **−4.5 pp** |

Applied to a random large-cap name, these rules **destroy value** relative to
simply holding it. Where the three chosen names sit in that distribution:

| Name | Strategy CAGR | Buy & hold CAGR | Excess | Percentile in basket |
|---|---|---|---|---|
| NVDA | 79.6% | 108.0% | **−28.3pp** | **top 0%** |
| NET | 71.8% | 69.6% | +2.3pp | **top 3%** |
| META | 20.4% | 51.0% | **−30.6pp** | top 59% (median) |

Two of the three picks are in the extreme right tail of the basket, and **on two
of the three the strategy underperformed simply holding the stock** — NVDA by
28pp and META by 31pp.

The universe was selected in 2026 by looking at what worked from 2023. That is
the edge.

### 5.8 Walk-forward — fit 2023-24, test 2025-26

| Parameters | IS CAGR | IS Sharpe | OOS CAGR | OOS Sharpe | Decay |
|---|---|---|---|---|---|
| In-sample optimum (Z<−1.2, 5.0×ATR) | 115.7% | 1.96 | 21.6% | 0.71 | −94.1pp |
| **Documented (Z<−1.2, 4.0×ATR)** | 109.0% | 2.00 | **26.5%** | **0.80** | −82.5pp |
| **Equal-weight buy & hold** | 135.9% | 2.46 | **35.5%** | **0.97** | −100.5pp |

Buy and hold beat the strategy out-of-sample **on both return (+9.0pp CAGR) and
Sharpe (0.97 vs 0.80)**.

An honest caveat: buy-and-hold decayed just as hard (−100pp). The decay is mostly
*regime*, not overfitting — 2023–24 was extraordinary for these names. But the
ordering is what matters, and out-of-sample the strategy is behind on every
measure.

### 5.9 The regime filter the document recommends

The strategy document §7 suggests gating entries on a 200-day moving average for
live deployment. Tested:

| Variant | CAGR | Max DD | Sharpe | Calmar | Avg exposure |
|---|---|---|---|---|---|
| No filter | **83.3%** | −31.3% | **1.707** | **2.661** | 95.9% |
| Own close > 100-SMA | 17.1% | −33.4% | 0.664 | 0.511 | 65.0% |
| Own close > 200-SMA | 24.0% | −33.7% | 0.833 | 0.713 | 74.4% |
| SPY > 200-SMA | 31.3% | −27.0% | 1.060 | 1.155 | 60.9% |

Every filter is **worse on every metric except drawdown**, and the own-SMA
filters do not even reduce drawdown. The gate removes exposure during exactly the
recoveries the strategy needs, because a dip deep enough to trigger `Z < −1.2`
frequently also pushes price under its own long moving average.

The document's own recommended risk control would have cut returns by roughly
two-thirds.

### 5.10 Robustness

**Commissions** — insensitive. 0 bps → 84.0% CAGR; 50 bps → 77.4%. The strategy
is not being carried by unrealistic cost assumptions.

**Start date** — excess CAGR over buy & hold, by start:

| Start | Strategy | Buy & hold | Excess |
|---|---|---|---|
| 2023-01-03 | 83.3% | 80.3% | +3.0pp |
| 2023-07-01 | 55.6% | 51.7% | +3.8pp |
| 2024-01-02 | 51.3% | 54.5% | **−3.3pp** |
| 2024-07-01 | 44.3% | 39.8% | +4.5pp |
| 2025-01-02 | 26.5% | 35.5% | **−9.0pp** |

Excess return oscillates around zero and is negative in the two most recent
windows. There is no stable edge over holding.

### 5.11 Trade statistics (baseline, 105 lots)

```
Win rate            54.3%          Profit factor      3.17
Average trade      +22.38%         Median trade      +2.54%
Best               +184.6%         Worst             −22.7%
Avg hold            91 days        Median hold        50 days
Avg MFE            +43.1%          Avg giveback      20.7 pp
Exits: 97 trail hit, 8 open at end
```

**The mean is +22.4% and the median is +2.5%.** The distribution is violently
right-skewed. Concentration of profit:

| | Share of total profit |
|---|---|
| Top 5 lots (of 105) | **49%** |
| Top 10 lots (of 105) | **83%** |
| 48 of 105 lots lost money | — |

Per ticker, on $769,654 of total profit:

| Ticker | Lots | Win rate | Total P&L | Share of profit |
|---|---|---|---|---|
| **NET** | 38 | 65.8% | **+$498,529** | **64.8%** |
| **NVDA** | 29 | 48.3% | +$295,461 | 38.4% |
| **META** | 38 | 47.4% | **−$24,336** | **−3.2%** |

One stock produced two thirds of the profit. A third of the portfolio lost money
over a period in which it rose substantially.

Average giveback of 20.7pp means a typical lot surrenders about half its peak
gain before the trail catches it. That is the honest price of a 4×ATR stop, and
it is a design choice rather than a defect — but it should be stated.


### 5.12 Null test — does the Z signal beat random entries?

The threshold insensitivity in §5.4 suggested the entry might be doing nothing.
That is testable directly: hold the universe, sizing, and exit rule fixed, and
replace `Z < −1.2` with **random entry dates at the same frequency**. 200
simulations.

| | CAGR | Sharpe |
|---|---|---|
| **Real Z signal** | **83.3%** | **1.71** |
| Random entries — mean | 72.5% | 1.62 |
| Random entries — median | 72.4% | — |
| Random entries — 5th–95th pct | 57.0% – 88.7% | — |

**The real signal beats 88% of random entry sets on CAGR and 74% on Sharpe.**

This **partially reverses** the reading in §5.4. The entry does contribute — worth
roughly **+10.8pp of CAGR** over randomly-timed entries with identical everything
else. It is not statistically overwhelming (88th percentile ≈ p 0.12 one-tailed,
and only p 0.26 on Sharpe), but it is a real effect, not noise.

The correct synthesis of §5.4 and §5.12: **buying dips helps; the specific depth
of the dip does not.** Any pullback entry beats a random entry, but −1.2σ, −0.8σ
and −0.5σ are interchangeable.

A caveat that may explain the whole effect: `Z < −1.2` clusters inside drawdowns,
while random entries are uniform in time. In a market that rose sharply over the
window, *any* rule that concentrates buying into declines gets a better average
price. The signal may be capturing "buy after a decline" rather than anything
specific to Z-scores.

### 5.13 Attempts to improve it

Four modifications tested against the baseline. Three failed.

**(a) Trail ratchet — tighten the stop once a lot is up N×ATR.** Motivated by the
20.7pp average giveback.

| Variant | CAGR | Sharpe | Giveback |
|---|---|---|---|
| Baseline flat 4×ATR | **83.3%** | **1.71** | 20.7pp |
| Tighten to 3× after +4 ATR | 80.0% | 1.57 | 19.0pp |
| 2.5× after +4, 2.0× after +8 | 75.0% | 1.55 | 15.4pp |
| Tighten to 2× after +8 ATR | 61.7% | 1.37 | 17.2pp |

Every variant lowers both CAGR and Sharpe. Giveback falls as intended, but the
trade is bad at every setting. **The wide trail is correct.** Giveback is the
price of admission, not a defect — a clean confirmation of B's core design choice
and a direct refutation of the instinct to protect open profits.

**(b) Volatility-targeted sizing** — size each lot so it risks a fixed % of equity
to its own stop, rather than a flat % of equity regardless of the name's
volatility.

| Variant | CAGR | Sharpe | Avg exposure |
|---|---|---|---|
| Baseline: 20% of equity | 83.3% | 1.71 | 95.9% |
| Vol-target 1% risk | 62.6% | 1.66 | 84.1% |
| Vol-target 3% risk | 76.4% | 1.68 | 94.4% |
| **Vol-target 5% risk** | **87.4%** | **1.78** | 96.1% |

At 5% risk per lot this is the **first variant to beat buy-and-hold on Sharpe**
(1.78 vs 1.753) as well as on CAGR. But note the exposure column: the improvement
tracks exposure again, and win rate rises across the board (54% → 56–62%), which
is what de-weighting the most volatile name should do. Marginal, real, and not a
change in kind.

**(c) Cross-sectional momentum universe** — the intended fix for selection bias.
Instead of three names chosen in hindsight, take a 30-name basket and only buy
dips in whatever is currently top-N by 12-1 momentum.

| Variant | CAGR | Sharpe | vs its own B&H |
|---|---|---|---|
| Fixed 3 names (documented) | 83.3% | 1.71 | +3.0pp |
| Broad 30-name basket, no gate | 46.8% | 1.51 | **+5.7pp** |
| Broad basket, top 3 momentum | 27.3% | 0.87 | −13.9pp |
| Broad basket, top 5 momentum | 28.1% | 0.92 | −13.1pp |
| Broad basket, top 10 momentum | 15.8% | 0.65 | −25.4pp |

**In-sample this fails badly.** Momentum gating is worse than no gating at every
N, and worse than simply holding the basket. Buying a dip in whatever has already
run hardest appears to be an actively bad combination.

But note the second row: **run on the broad basket with no gate, the strategy's
excess over its own buy-and-hold is +5.7pp — larger than the +3.0pp it manages on
the three hand-picked names.** The relative edge is roughly +3 to +6pp regardless
of universe. Absolute return is set entirely by which stocks you hold.

**(d) Out-of-sample — the one genuine surprise.**

| Variant | IS CAGR | IS Sharpe | OOS CAGR | OOS Sharpe | OOS MaxDD | Decay |
|---|---|---|---|---|---|---|
| **Momentum top 5 + ratchet** | 21.4% | 0.93 | **27.1%** | **1.12** | **−21.9%** | **+5.6pp** |
| Momentum top 5 + vol-target + ratchet | 13.0% | 0.67 | 23.9% | 1.03 | −20.0% | +10.8pp |
| Buy & hold, fixed 3 names | 135.9% | 2.46 | 35.5% | 0.97 | −36.5% | −100.5pp |
| Momentum top 5 | 20.8% | 0.91 | 22.3% | 0.91 | −27.7% | +1.4pp |
| **Documented baseline** | 109.0% | 2.00 | 26.5% | **0.80** | −35.5% | −82.5pp |

The momentum variants are far worse in-sample and **slightly better
out-of-sample**, with markedly shallower drawdowns (−21.9% vs −35.5%) and
*positive* decay. In-sample and out-of-sample results that resemble each other is
the signature of something that is not overfit.

**I do not think this is yet a result.** I tested seven variants and picked the
best by looking at the out-of-sample window — which is itself overfitting, one
level up. One 19-month OOS period with seven candidates will produce a winner by
chance. Treat it as a hypothesis worth a properly nested walk-forward, not a
finding.


### 5.14 The window problem — extending the history to 2020

Everything above uses the strategy document's window, 2023-01-03 → 2026-07-31.
Look at what happened in the calendar year immediately before it:

| 2022 total return | META | NET | NVDA |
|---|---|---|---|
| | **−64.5%** | **−64.2%** | **−51.4%** |

**The documented track record begins at a generational low in its own universe.**
All three names have data back to September 2019, so the bear market was
testable and simply was not tested. Re-running the identical rules from
2020-01-02:

| | Strategy | Buy & hold | Difference |
|---|---|---|---|
| **Documented window** (2023-01 → 2026-07) | 83.3% CAGR | 80.3% | **+3.0pp** |
| **Full history** (2020-01 → 2026-07) | **47.6% CAGR** | **54.3%** | **−6.7pp** |
| Max drawdown, full history | −66.8% | −74.5% | +7.7pp better |
| Sharpe, full history | 1.10 | 1.13 | −0.03 |
| Calmar, full history | 0.71 | 0.73 | −0.02 |

**The edge inverts.** Over a full cycle including a bear market the strategy
*loses* to buy-and-hold by 6.7 points of CAGR, and neither Sharpe nor Calmar
shows any compensating improvement.

The one genuine benefit survives: max drawdown is 7.7 points shallower. That is
real, and §5.16 shows where it comes from.

### 5.15 Calendar-year breakdown

One continuous run from 2020, against equal-weight buy & hold:

| Year | Strategy | Buy & hold | Excess | Strategy max DD | Avg exposure | Lots |
|---|---|---|---|---|---|---|
| 2020 | +117.0% | +164.8% | **−47.9pp** | −35.8% | 85.5% | 29 |
| 2021 | +35.3% | +81.4% | **−46.1pp** | −20.2% | 99.4% | 25 |
| **2022** | **−52.3%** | **−59.6%** | **+7.4pp** | −58.3% | 100.0% | 70 |
| 2023 | +203.2% | +169.5% | **+33.7pp** | −16.8% | 98.3% | 19 |
| 2024 | +62.2% | +119.9% | **−57.7pp** | −19.7% | 97.1% | 20 |
| 2025 | +97.2% | +40.9% | **+56.3pp** | −31.3% | 98.5% | 25 |
| 2026 (part) | −2.0% | +12.3% | −14.3pp | −18.5% | 95.8% | 32 |

**Beat buy & hold in 3 of 7 years. Mean excess −9.8pp, median −14.3pp.**

The pattern is consistent and interpretable: the strategy **underperforms in
strong up years** (2020, 2021, 2024 — all around −50pp) because the trail keeps
selling into advances, and **outperforms in falling or choppy years** (2022,
2025). It is a volatility-dampening overlay, not a return engine.

### 5.16 The 2022 bear market in isolation

The test the strategy had never faced:

| Period | Strategy | Buy & hold | Excess | Strategy max DD | B&H max DD |
|---|---|---|---|---|---|
| Calendar 2022 | **−49.7%** | −60.0% | **+10.4pp** | −58.2% | −64.8% |
| Peak to trough (2021-11 → 2022-12) | −58.7% | −66.5% | **+7.7pp** | −64.5% | −70.4% |
| Bear + recovery (2022 → 2023) | +52.1% | +11.7% | **+40.4pp** | −58.2% | −64.8% |

**This is the strategy's best showing anywhere in the study**, and it should be
credited. The 4×ATR trail did what it is supposed to do: it cut roughly 10 points
off a 60% decline, and the aggressive re-entry through 2023 turned a two-year
+11.7% into +52.1%.

But keep the magnitude in view. **−49.7% is still a catastrophic year.** Average
exposure through 2022 was 99.4% — the trail sold individual lots but the system
immediately redeployed into the next dip, so the book was never meaningfully in
cash. This is not a defensive system; it is a slightly less offensive one.

### 5.17 Rolling walk-forward — eight windows

24 months fit, 12 months tested, stepped 6 months, re-optimising `z_entry` and
`atr_mult` on in-sample Sharpe each time.

| OOS window | Fitted params | Re-opt CAGR | Doc params | Buy & hold | Re-opt vs B&H | Doc vs B&H |
|---|---|---|---|---|---|---|
| 2022-01 → 2023-01 | Z<−2.0, 2×ATR | −41.9% | −50.1% | −60.5% | +18.5pp | +10.4pp |
| 2022-07 → 2023-07 | Z<−1.5, 2×ATR | +66.5% | +83.7% | +96.2% | −29.7pp | −12.5pp |
| 2023-01 → 2024-01 | Z<−1.5, 3×ATR | +116.9% | +168.1% | +167.1% | −50.2pp | +1.0pp |
| 2023-07 → 2024-07 | Z<−0.8, 3×ATR | +65.6% | +59.8% | +99.1% | −33.5pp | −39.3pp |
| 2024-01 → 2025-01 | Z<−2.0, 3×ATR | +21.0% | +46.9% | +100.6% | −79.7pp | −53.8pp |
| 2024-07 → 2025-07 | Z<−2.0, 6×ATR | +80.6% | +92.8% | +62.4% | +18.2pp | +30.4pp |
| 2025-01 → 2026-01 | Z<−1.2, 2×ATR | +35.6% | +46.6% | +39.9% | −4.3pp | +6.7pp |
| 2025-07 → 2026-07 | Z<−2.0, 4×ATR | +14.5% | +5.2% | +12.2% | +2.3pp | −7.0pp |

Three results, all bad:

1. **Re-optimised parameters beat buy & hold in 3 of 8 windows** (mean −19.8pp).
2. **Fixed documented parameters beat buy & hold in 4 of 8** (mean −8.0pp).
3. **Re-optimising is worse than not bothering, by −11.8pp on average.**

Point 3 is the important one. When periodically refitting parameters does *worse*
than freezing them, the in-sample optimum is noise. The fitted parameters confirm
it — they jump between Z<−2.0 and Z<−0.8, and between 2×ATR and 6×ATR, from one
window to the next. **There is no stable optimum to find.**

### 5.18 Bootstrap — is the excess distinguishable from zero?

Stationary block bootstrap (21-day blocks, 5,000 resamples) on paired daily
returns, 2020–2026, giving a confidence interval on excess CAGR over buy & hold:

```
Observed excess CAGR      −6.74 pp
Bootstrap mean            −5.54 pp
95% confidence interval   [−37.88, +23.16] pp
P(excess ≤ 0)             0.629
```

**The interval spans zero by a wide margin.** Not only is the edge not
significantly positive, its *sign* is unresolved. The width reflects §5.11 — when
10 of 105 lots carry 83% of the profit, the outcome depends on whether a handful
of trades happen to land, and the confidence interval has to be wide enough to
admit that they might not.

### 5.19 Core + dip-add hybrid

The idea from the previous round: hold a permanent core, deploy only the
remainder into dip lots, so the signal is used where it works without ever
selling the whole book.

**Full history 2020–2026:**

| Variant | CAGR | Max DD | Sharpe | Excess vs B&H |
|---|---|---|---|---|
| 100% buy & hold | **54.3%** | −74.5% | 1.13 | 0.00 |
| Core 75% + dip lots | 53.6% | −73.1% | 1.14 | −0.76pp |
| Core 60% + dip lots | 53.3% | −72.1% | **1.15** | −1.05pp |
| Core 50% + dip lots | 53.0% | −71.4% | **1.15** | −1.33pp |
| Core 25% + dip lots | 51.3% | −69.4% | 1.14 | −2.98pp |
| Core 0% (pure strategy) | 47.6% | **−66.8%** | 1.10 | −6.74pp |

**The idea fails.** Return rises monotonically as you dilute toward pure
buy-and-hold. Sharpe peaks at 1.15 versus buy-and-hold's 1.13 — a rounding error.
There is a clean monotone trade: every 25 points of core you *remove* buys about
2 points of drawdown protection and costs about 2 points of CAGR.

**Calendar 2022 only** — the same trade, in the regime where it should pay:

| Variant | Return | Max DD |
|---|---|---|
| Core 0% (pure strategy) | **−49.7%** | **−58.2%** |
| Core 25% | −53.0% | −58.9% |
| Core 50% | −56.4% | −61.7% |
| Core 75% | −59.1% | −64.0% |
| 100% buy & hold | −60.0% | −64.8% |

Exactly inverted. In the bear year, *less* core is better. This is the cleanest
statement of what the system actually is: **the dip-and-trail machinery is a
drawdown-reduction overlay that costs return in rising markets and saves it in
falling ones.** Over 2020–2026 the cost exceeded the saving by 6.7pp, and no
risk-adjusted measure shows a net gain.


### 5.20 Window sensitivity revisited — the pandemic-exclusion argument

§5.14 extended the history to 2020 and found the edge inverting to −6.7pp. The
author's response is that 2020–2021 were pandemic outliers — panic and stimulus
rather than anything a statistical model should be fitted to — and were excluded
deliberately.

**That objection is reasonable, and it is not the same as the documented window.**
2022 was a rate-hiking bear market, not a pandemic year. So there are three
defensible windows, and the answer differs sharply between them:

| Window | Strategy CAGR | B&H CAGR | Excess | Sharpe (S / B&H) | Calmar (S / B&H) | Max DD (S / B&H) |
|---|---|---|---|---|---|---|
| 2020+ (all history) | 47.6% | 54.3% | **−6.7pp** | 1.10 / **1.13** | 0.71 / **0.73** | −66.8% / −74.5% |
| **2022+ (post-pandemic, incl. bear)** | **40.6%** | 31.1% | **+9.4pp** | **0.97** / 0.82 | **0.70** / 0.48 | −58.2% / −64.8% |
| 2023+ (documented) | 83.3% | 80.3% | +3.0pp | 1.71 / **1.75** | **2.66** / 2.35 | −31.3% / −34.2% |

**On the 2022+ window the strategy wins on every single metric** — return, Sharpe,
Sortino, Calmar and max drawdown. It is the only window in the entire study where
that is true.

Two things make this more credible than it might look:

1. **The exclusion criterion was stated before the result was seen**, and on a
   basis independent of performance (regime abnormality, not returns). That is
   the discipline that separates a legitimate sample restriction from curve-fitting.
2. **The exclusion cuts against the strategy, not for it, in the obvious way.**
   2020 and 2021 were years the strategy *lost* to buy-and-hold by 47.9pp and
   46.1pp. Removing them removes two of its worst years — so one has to ask
   whether the restriction is doing real work or just deleting bad news.

The answer to that second point is the honest complication: **2024 was not a
pandemic year, and the strategy underperformed by 49.8pp in it.** The pattern is
not "pandemic years hurt"; it is "**strong bull years hurt**," and 2020, 2021 and
2024 were all strong bull years. Excluding two of the three is defensible on
regime grounds but does not make the underlying property go away.

### 5.21 The error bar on the 2022+ result

Annual excess over buy-and-hold on the 2022+ window, using the best variant
(vol-target 5%):

| Year | Strategy | Buy & hold | Excess |
|---|---|---|---|
| 2022 | −50.4% | −60.0% | **+9.6pp** |
| 2023 | +208.7% | +182.8% | **+25.9pp** |
| 2024 | +67.0% | +116.9% | **−49.8pp** |
| 2025 | +99.1% | +33.9% | **+65.3pp** |
| 2026 (part) | −1.6% | +5.9% | −7.6pp |

```
mean excess  +8.7 pp     sd 42.4 pp     n = 5
standard error 19.0 pp   t = 0.46
95% interval [−28.5, +45.8] pp
```

**The interval contains zero comfortably.** This agrees with the independent
bootstrap in §5.18 despite using a different window and method. The 2022+ result
is the most encouraging evidence in the study and it is still not statistically
established — five annual observations with a 42-point standard deviation cannot
establish a 9-point edge. Roughly 90 years of data would be needed for t ≈ 2.

That is not an argument that the edge is absent. It is an argument that the data
cannot tell you either way, and that position sizing should reflect that.

### 5.22 Deploying new money: schedule vs dips

The one use of the signal that survived every test. $1,000/month contributed,
**nothing ever sold** — this isolates entry timing, which §5.12 showed is the one
thing the Z-score genuinely does. Dip mode force-deploys any cash held longer than
12 months, so it cannot win by sitting out.

| Universe | Window | Scheduled (DCA) | Dip-timed | Advantage |
|---|---|---|---|---|
| META/NVDA/NET | 2020+ | $379,748 | $374,932 | −1.3% |
| **META/NVDA/NET** | **2022+** | $176,896 | **$212,640** | **+20.2%** |
| META/NVDA/NET | 2023+ | $103,980 | $117,693 | **+13.2%** |
| 30-name basket | 2020+ | $188,787 | $224,571 | **+19.0%** |
| 30-name basket | 2022+ | $103,196 | $115,581 | **+12.0%** |
| 30-name basket | 2023+ | $71,470 | $75,760 | **+6.0%** |
| QQQ | 2020+ | $152,082 | $149,248 | −1.9% |
| QQQ | 2022+ | $92,446 | $91,743 | −0.8% |
| QQQ | 2023+ | $65,771 | $64,312 | −2.2% |

**Dip-timing beat scheduled investing in 5 of 9 combinations, mean +7.1%** — and
the pattern is clean rather than random: it works on **baskets of individual
volatile stocks** (5 of 6 positive, up to +20.2%) and **fails on an index** (0 of
3 positive). An index dilutes idiosyncratic dips, so there is less mispricing to
time.

This is the most robust practical finding in the whole project. It uses the signal
where it is proven, avoids the exit machinery that costs return in bull markets,
and generates no tax events.

### 5.23 How much of a portfolio should this be?

The dip strategy on the trio carries a **−57.5% max drawdown**. Blended with SPY,
rebalanced quarterly, 2022+:

| Allocation | CAGR | Max DD | Sharpe | Sortino | Calmar | Vol |
|---|---|---|---|---|---|---|
| 100% SPY | 11.6% | −24.5% | 0.72 | 0.99 | 0.47 | 17.5% |
| 20% dip / 80% SPY | 18.6% | −31.0% | 0.90 | 1.30 | 0.60 | 21.5% |
| **30% dip / 70% SPY** | **22.0%** | **−34.2%** | **0.95** | 1.39 | 0.64 | 24.0% |
| 50% dip / 50% SPY | 28.4% | −40.7% | 1.00 | 1.48 | 0.70 | 29.5% |
| 100% dip | 42.2% | **−57.5%** | **1.01** | 1.52 | 0.73 | 44.8% |

Sharpe rises monotonically with the dip weight and flattens above 50%. Nothing in
the data says "hold less than 100%" on risk-adjusted grounds — but **30% captures
94% of the peak Sharpe with 60% of the drawdown**, and the peak itself rests on
t = 0.46. When the point estimate is that uncertain, the flat part of the curve is
where you want to sit.


### 5.24 Strategy A vs B, head to head on equal terms

Strategy B was put through a full gauntlet. Strategy A never was — the case
against it rested on the original single-name notebooks, a synthetic fixture and
one config comparison. That is thinner evidence than the conclusion it was being
used to support, so both were re-run through the same portfolio engine, same
universe, same 20% sizing, same pyramiding. Only the rules differ.

| Window | | CAGR | Max DD | Sharpe | Calmar | Lots | Win % | Avg hold | Avg exposure |
|---|---|---|---|---|---|---|---|---|---|
| **2020+** | A | 21.9% | −54.1% | 0.83 | 0.40 | 400 | 66.3% | 10.5d | **28.9%** |
| | B | **47.6%** | −66.8% | **1.10** | **0.71** | 220 | 45.0% | 83.6d | 96.4% |
| | B&H | 54.3% | −74.5% | 1.13 | 0.73 | — | — | — | 100% |
| **2022+** | A | 18.3% | −54.1% | 0.70 | 0.34 | 300 | 64.0% | 11.1d | **32.7%** |
| | B | **40.6%** | −58.2% | **0.97** | **0.70** | 169 | 43.8% | 82.4d | 98.0% |
| | B&H | 31.1% | −64.8% | 0.82 | 0.48 | — | — | — | 100% |
| **2023+** | A | 39.8% | **−17.8%** | 1.59 | 2.23 | 197 | 73.1% | 10.3d | **26.2%** |
| | B | **83.3%** | −31.3% | **1.71** | **2.66** | 105 | 54.3% | 91.4d | 95.9% |
| | B&H | 80.3% | −34.2% | 1.75 | 2.35 | — | — | — | 100% |

**B beats A on CAGR and Sharpe on all three windows.** But note the last column:
**A is only 26–33% invested.** It spends roughly seventy percent of its life in
cash. Comparing raw CAGR between a 30%-exposed and a 97%-exposed strategy is not
a like-for-like comparison, which §5.26 corrects.

### 5.25 Which component actually matters — entry or exit?

A 2×2 on the 2022+ window, crossing each strategy's entry threshold with each
strategy's exit rule:

| CAGR % | A exit (2×ATR daily + Z>0) | B exit (4×ATR frozen, no mean exit) |
|---|---|---|
| **A entry** (Z < −1.5) | 18.3% | **40.4%** |
| **B entry** (Z < −1.2) | 20.0% | **40.6%** |

```
Average effect of the ENTRY threshold :  0.9 pp
Average effect of the EXIT rule       : 21.3 pp
```

**The exit rule matters roughly 23× more than the entry threshold.** This is the
single cleanest result in the entire study, and it confirms the design thesis
behind B from §1: A and B are not two strategies, they are one entry rule with
two exits, and essentially all of the difference lives in the exit.

It also closes out §5.4 and §5.12 definitively. The entry threshold is nearly
irrelevant (0.9pp across a 0.3σ change) even though the entry *signal* beats
random (§5.12). Buying dips helps; how deep, and what you do afterwards, are
entirely different questions — and only the second one matters much.

### 5.26 Where Strategy A actually wins

Three places, and they are not trivial.

**(a) Bear markets.** A's fast exit is dramatically more protective:

| Period | A | B | Buy & hold |
|---|---|---|---|
| Calendar 2022 | **−34.8%** | −49.7% | −60.0% |
| Peak to trough, 2021-11 → 2022-12 | **−34.5%** | −58.7% | −66.5% |
| Average exposure through 2022 | **54.5%** | 99.4% | 100% |

A was 24 points better than B peak-to-trough. B stays fully invested through a
bear because it sells one lot and immediately redeploys into the next dip; A goes
to cash and stays there.

**(b) Drawdown generally.** Across the 30-name basket on 2022+:

| | A | B |
|---|---|---|
| Names beating buy & hold | 16/30 | **24/30** |
| Median excess CAGR | +2.2pp | **+2.7pp** |
| Mean Sharpe | 0.40 | **0.45** |
| **Mean max drawdown** | **−28.8%** | −55.6% |
| Beat the other on CAGR | 14/30 | 16/30 |

B generalises better on beat-rate; **A has roughly half the drawdown**. The split
by name is exactly what theory predicts: A wins on the fallers (PYPL +21.6pp,
ADBE +15.9pp, TEAM +15.6pp, NOW +15.2pp), B wins on the trenders (NVDA, AVGO,
ANET, AMD, CRWD). Mean reversion protects in downtrends; trend following captures
uptrends.

**(c) Once its idle capital is credited.** A uses ~30% of the account. Putting the
rest in SPY is the fair comparison for someone with a fixed pot:

| Window | Variant | CAGR | Max DD | Sharpe | Calmar |
|---|---|---|---|---|---|
| 2020+ | A alone | 21.9% | −54.1% | 0.83 | 0.40 |
| | **A + idle cash in SPY** | 36.2% | −56.4% | **1.10** | 0.64 |
| | B alone | 47.6% | −66.8% | **1.10** | **0.71** |
| 2022+ | **A + idle cash in SPY** | 26.9% | −56.0% | 0.87 | 0.48 |
| | **B alone** | 40.6% | −58.2% | **0.97** | **0.70** |
| 2023+ | **A + idle cash in SPY** | 57.0% | **−17.7%** | **1.88** | **3.22** |
| | B alone | 83.3% | −31.3% | 1.71 | 2.66 |

**On the documented window, A-plus-cash beats B on both Sharpe (1.88 vs 1.71) and
Calmar (3.22 vs 2.66).** On the full history the Sharpes tie exactly. Only on the
2022+ window does B win outright.

A is therefore **not dominated**. It is a lower-exposure, much lower-drawdown
strategy whose apparent inferiority on raw CAGR is substantially an artifact of
leaving 70% of the capital idle.

**(d) Are they complementary?** Daily-return correlation is **0.619**. Blending:

| Mix | CAGR | Max DD | Sharpe |
|---|---|---|---|
| 100% B | 40.6% | −58.2% | **0.97** |
| 25% A / 75% B | 36.3% | −54.2% | **0.97** |
| 50% A / 50% B | 31.1% | −53.2% | 0.95 |
| 100% A | 18.3% | −54.1% | 0.70 |

A 25/75 blend matches B's Sharpe exactly while cutting 4 points off the drawdown.
Modest, but free.

### 5.27 Correction to an earlier conclusion

Earlier sections of this document, and my summary advice, described Strategy A's
mean-reversion exit as "a genuine, measured defect" and recommended scrapping A.

**The first half stands; the second was overstated.** The Z>0 exit *is* a defect
for return capture — §5.25 puts the cost at ~21pp of CAGR, and §5.0's finding that
95% of A's exits went on to trade higher is confirmed. But "defective at capturing
return" is not the same as "worthless," and I asserted the stronger claim on
weaker evidence than I had applied to B.

A is a defensive strategy that underperforms in bull markets — which is what a
defensive strategy is supposed to do. It halves the drawdown, it was 24 points
better than B through the 2022 bear, and once its idle cash is credited it ties
or beats B on risk-adjusted return on two of three windows.

The defensible recommendation is **not** "scrap A." It is: *B is the better return
engine and the exit rule is where all the difference lives; A is not a competing
return engine but a lower-exposure defensive sleeve, and which one is right
depends on whether the objective is growth or capital preservation.*


### 5.28 Adding a profit take to Strategy B

B has no profit target — it holds until the 4×ATR trail is hit, giving 96–98%
average exposure. The proposal: sell the *statistical extremes*. Not Strategy A's
`Z > 0`, which is the mean and costs ~21pp of CAGR (§5.25), but a genuinely high
bar such as `Z > +2` — roughly the top 2.3% of days — and redeploy into the next
dip.

**Only `Z > 0` had ever been tested. This was a real gap.**

Sweep on 2022+, full exits:

| Profit take | CAGR | Max DD | Sharpe | Calmar | Avg exposure | Win % |
|---|---|---|---|---|---|---|
| **B baseline — none** | 40.6% | −58.2% | 0.97 | 0.70 | **98.0%** | 43.8% |
| Z > 0.0 *(= Strategy A)* | 32.8% | −48.4% | 1.03 | 0.68 | 42.3% | 86.7% |
| Z > 0.5 | 38.4% | −51.3% | **1.11** | 0.75 | 48.3% | 82.2% |
| Z > 1.5 | 41.2% | −49.8% | 1.09 | **0.83** | 57.6% | 75.7% |
| **Z > 2.0** | **42.4%** | −53.3% | 1.05 | 0.80 | 65.1% | 68.7% |
| Z > 2.5 | 38.1% | −55.5% | 0.92 | 0.69 | 84.4% | 51.0% |
| Z > 3.0 | 40.4% | −55.9% | 0.97 | 0.72 | 92.4% | 47.6% |

**And it holds on all three windows** — the only modification tested anywhere in
this document that does:

| Window | B baseline Sharpe | + PT Z>2.0 | B baseline excess vs B&H | + PT excess |
|---|---|---|---|---|
| 2020+ | 1.10 | **1.19** | **−6.7pp** | −7.0pp |
| 2020+ *(PT Z>2.5)* | 1.10 | **1.21** | **−6.7pp** | **+1.3pp** |
| 2022+ | 0.97 | **1.05** | +9.4pp | **+11.3pp** |
| 2023+ | 1.71 | **2.01** | +3.0pp | **+5.4pp** |

Note the second row: on the full 2020+ history a `Z > 2.5` profit take turns the
strategy's −6.7pp deficit into a **+1.3pp surplus** over buy-and-hold, lifting CAGR
from 47.6% to 55.6%. The profit take partially repairs the very failure that §5.14
identified — being always-invested with a wide trail through the 2020–21 melt-up.

Every other modification tested — trail ratchet (§5.13a), momentum gating
(§5.13c), regime filters (§5.9), core hybrid (§5.19) — failed on at least one
window. This one does not.

**Implementation details that matter:**

| Variant | CAGR | Sharpe |
|---|---|---|
| Sell 100% of the lot at Z > 2.0 | **42.4%** | **1.05** |
| Sell 75% | 40.6% | 1.03 |
| Sell 50% | 38.1% | 0.98 |
| Sell 25% | 34.7% | 0.90 |
| Sell all, only if lot up ≥ 10% | 34.6% | 0.92 |
| Sell all, only if lot up ≥ 25% | 27.5% | 0.77 |

**Full exits beat partial scale-outs** — selling half generates 1,065 lots versus
233 and the churn costs more than the smoothing is worth. **A minimum-gain filter
makes it strictly worse** at every level; requiring a lot to be up 25% before
taking profit destroys 15pp of CAGR, because it forces you to hold precisely the
extended positions you wanted to trim.

A percentile-based version (sell at the 95th percentile of the trailing year)
gives the best Calmar of any variant, 0.89, with a −44.7% drawdown versus the
baseline's −58.2%, at roughly unchanged CAGR. That is the most drawdown-efficient
setting found anywhere in this study.

### 5.29 Do you actually get to buy back lower?

The mechanism only works if selling a high leads to a cheaper re-entry. Measuring
all 146 profit-take exits at Z > 2.0:

| Horizon | Price higher later | **Dipped below the exit at some point** | Mean best re-entry | Mean forward return |
|---|---|---|---|---|
| 20 days | 47% | **80%** | −9.1% | +0.0% |
| 60 days | 50% | **86%** | −13.7% | +5.8% |
| 120 days | 58% | **86%** | −18.9% | **+17.7%** |

**You get a cheaper print 80–86% of the time** — the idea is sound. And over 20
days the mean forward return is exactly zero, so selling the extreme is
essentially free in the short run.

**But the window closes.** By 120 days the price is higher 58% of the time and up
+17.7% on average. The profit take only pays if you redeploy promptly — which B
does, because the next `Z < −1.2` dip usually arrives within weeks. Sitting in
cash waiting for a *better* entry is a different and much worse strategy.

### 5.30 What the Z-score is actually doing — the thing to understand

A Z-score is `(Close − SMA20) / sd20`. Z is mean-reverting **by construction**;
price is not. Z can fall from +2 to 0 with price flat or rising, because the
moving average catches up from below.

Measuring all 185 episodes where Z crossed above +2.0 and later fell below +0.5:

```
Median time for Z to normalise   15 days
Price change over that span      mean  +2.87%   median  −1.29%
20-SMA change over that span     mean +12.65%
Price was HIGHER when Z normalised in 43% of episodes
```

**The SMA moves +12.65% while price moves +2.87%.** Roughly four-fifths of the
Z-score's decline comes from the average rising to meet the price, not from the
price falling to meet the average.

The practical consequence: the discount from waiting is **real but small** — a
median of −1.3%, against the 80% chance of touching a lower price noted in §5.29.
The profit take earns its keep by cutting exposure and drawdown during extended
periods, not by systematically buying back much cheaper. Anyone expecting the
latter will be disappointed and will hold cash too long.

### 5.31 Does the profit take generalise?

Across the 30-name basket on 2022+, comparing B with and without `Z > 2.0`:

| | Result |
|---|---|
| Improved CAGR | **12 / 30** (median **−3.4pp**) |
| Improved Sharpe | 14 / 30 |
| **Reduced max drawdown** | **28 / 30** (mean **8.6pp shallower**) |
| Mean max drawdown | −55.6% → **−47.0%** |

Split by how the name behaved under the baseline:

| Cohort | Median CAGR change |
|---|---|
| Strong performers (base CAGR > 10%, n=15) | **−9.0pp** |
| Weak performers (base CAGR ≤ 10%, n=15) | **+4.8pp** |

**This is not free alpha — it is a risk-reduction trade.** It reliably cuts
drawdown (28 of 30 names, ADBE −66.6% → −34.1%, NVDA −60.2% → −34.0%, TXN −32.3%
→ −19.9%) while costing return on strongly trending names (CRWD −35.8pp, AMD
−30.7pp, ORCL −24.0pp, AVGO −23.6pp) and adding return on choppy or falling ones
(ADBE +18.8pp, MDB +18.2pp, UBER +10.9pp, ZS +10.7pp).

It looks so good on the trio because the 2022+ window contains a bear market. The
honest framing: a profit take **buys drawdown reduction with trend-capture**, at a
price that was favourable on this universe and window and would not have been in
2020–21 alone.

### 5.32 Earnings and news

**Flattening before earnings** (2022+):

| Variant | CAGR | Max DD | Sharpe |
|---|---|---|---|
| Hold through earnings | 40.6% | −58.2% | 0.97 |
| Flatten 1 day before | 38.6% | −55.6% | 1.02 |
| Flatten 3 days before | 40.1% | −59.6% | **1.05** |
| Flatten 5 days before | 35.7% | −59.3% | 0.96 |

Marginally positive at 1–3 days and negative at 5. yfinance supplies a thin
earnings history, so this is indicative at best — not a basis for a rule.

**News sentiment cannot honestly be backtested from this repository.** The media
layer (`data/media_earnings.py`, `studies/media_backtest_lib.py`) generates
**simulated** sentiment scores by default, and Alpha Vantage's NEWS_SENTIMENT
endpoint provides only recent history, not the multi-year series a backtest needs.
Any result would be measuring the simulator, not the news. Testing this properly
requires a paid historical news-sentiment dataset; until then it should stay what
it currently is in the app — informational context that never gates a signal.

---

## 6. Summary table

| Test | Result | Reading |
|---|---|---|
| Claims reproduce? | Within 4–7% | ✅ Honest |
| Beats its own buy & hold? | +3.0pp CAGR, **lower Sharpe** | ⚠️ Marginal |
| Parameters near optimum? | Rank 2/49, broad plateau | ✅ Not curve-fit |
| Entry threshold matters? | −1.2 ≈ −0.8 ≈ −0.5 | ❌ Depth is irrelevant |
| Entry *signal* beats random? | Beats 88% of random sets, +10.8pp CAGR | ✅ **Yes — real but weak** |
| Returns scale with size? | Monotonic to 100%, flat DD | ❌ It is exposure |
| Works on other names? | 10/29 beat B&H, median −2.2pp | ❌ **Does not generalise** |
| Survives walk-forward? | B&H wins OOS on return and Sharpe | ❌ **No** |
| Recommended regime filter helps? | Cuts CAGR by two thirds | ❌ Backwards |
| Profit concentration | 10 of 105 lots = 83% of profit | ⚠️ Fragile |
| Cost-sensitive? | No | ✅ Robust |
| Tightening the trail helps? | Worse on CAGR *and* Sharpe at every setting | ✅ Wide trail vindicated |
| Vol-targeted sizing helps? | Sharpe 1.78 vs 1.71, beats B&H | ⚠️ Marginal |
| Momentum universe fixes selection bias? | Much worse in-sample, better OOS | ❓ Unresolved |
| **Survives a full cycle (2020-26)?** | **−6.7pp vs buy & hold** | ❌ **No — edge inverts** |
| **Survives 2022+ (post-pandemic, incl. bear)?** | **+9.4pp, wins on every metric** | ✅ **Yes — best evidence in the study** |
| Is the 2022+ edge statistically established? | mean +8.7pp, sd 42.4pp, n=5, t=0.46 | ❌ No — CI spans zero |
| Dip-timing new money vs scheduled? | +20.2% on the trio, +7.1% mean; fails on QQQ | ✅ **Yes — most robust finding** |
| **Entry threshold vs exit rule — which matters?** | **Entry 0.9pp spread, exit 21.3pp** | ✅ **Exit, by ~23×** |
| Does B beat A on return? | Higher CAGR and Sharpe on all 3 windows | ✅ Yes |
| Is A dominated by B? | A has ~half the DD; A+idle cash ties/beats B on 2 of 3 windows | ❌ **No — different risk profile** |
| Does A protect better in a bear? | 2022: −34.8% vs −49.7%; peak-trough 24pp better | ✅ **Yes, substantially** |
| **Does a high-Z profit take help B?** | **Sharpe up on all 3 windows; exposure 98%→65%** | ✅ **Yes — best modification found** |
| Do you buy back lower after selling a high? | Cheaper print 80–86% of the time, median only −1.3% | ⚠️ Yes, but a small discount |
| Why does Z revert? | SMA rises +12.6% vs price +2.9% | ⚠️ **Not because price falls** |
| Does the profit take generalise? | CAGR better on 12/30, **drawdown better on 28/30** | ⚠️ Risk reduction, not alpha |
| Partial scale-outs or min-gain filters? | Worse at every setting | ❌ Use full exits |
| Can news sentiment be tested? | Repo data is simulated; AV has no deep history | ❌ Not from this repo |
| Beat B&H year by year? | 3 of 7 calendar years, median −14.3pp | ❌ No |
| Helped in the 2022 bear? | −49.7% vs −60.0%, DD −58% vs −65% | ✅ **Yes — its best result** |
| Stable optimum across windows? | Refitting is 11.8pp *worse* than not | ❌ No optimum exists |
| Excess distinguishable from zero? | 95% CI [−37.9, +23.2] pp | ❌ Sign unresolved |
| Core + dip-add hybrid helps? | Monotonically worse than pure B&H | ❌ No |

---

## 7. What I read this as saying

**1. The strategy document is honest but the conclusion does not follow.**
The numbers reproduce. The interpretation — that a tested edge was discovered —
does not survive testing on anything other than the three names it was built on.

**2. It is mostly a leveraged long position in three correlated stocks — but the
entry signal is not worthless.** The exposure evidence is strong: returns scale
monotonically with position size at constant drawdown, average exposure is 96%,
and the least active variant has the best Sharpe.

*However*, I initially concluded from the threshold insensitivity that the signal
did nothing, and the null test in §5.12 shows that was too harsh. Against random
entries at the same frequency, the Z signal is worth about **+10.8pp of CAGR** and
beats 88% of random draws. The honest version: **dip-buying adds real value; the
calibration of the dip depth adds none.** Most of the return is exposure, but not
all of it.

**3. The universe is the strategy, and the universe was chosen with hindsight.**
Median excess CAGR across 29 large caps is −2.2pp. NVDA sits in the top 0% of
that basket and NET in the top 3%. Worse, on NVDA the strategy *underperformed
holding NVDA by 28 points*. The backtest is measuring a decision made in 2026
about what worked in 2023.

**4. Strategy B is still clearly better than Strategy A.** A's mean-reversion
exit is a genuine, measured defect and B fixes it. If forced to choose, B. But
"better than a strategy that loses to buy-and-hold" is a low bar.

**5. The documented window is the single biggest problem, and it is not a
subtle one.** The backtest starts 2023-01-03 — the first trading week after
META fell 64.5%, NET 64.2% and NVDA 51.4%. Extending the identical rules back to
2020 turns +3.0pp of excess into **−6.7pp** (§5.14). Beating buy-and-hold in 3 of
7 calendar years, with median excess −14.3pp, is what the strategy actually did.

**6. What the system genuinely is.** §5.19 states it cleanly: a
drawdown-reduction overlay. Removing core exposure in favour of dip-and-trail
lots buys roughly 2 points of drawdown protection per 2 points of CAGR
surrendered — a monotone, symmetric trade with no free lunch anywhere on the
curve. It loses ~50pp a year to buy-and-hold in strong bull years and gains ~10pp
in bear years. Over 2020–2026 that netted to −6.7pp.

**7. And the edge is not measurable anyway.** The bootstrap 95% interval on
excess CAGR is [−37.9, +23.2]pp with P(excess ≤ 0) = 0.63. With 10 of 105 lots
carrying 83% of the profit, three and a half years is nowhere near enough data to
establish a 3-point edge. Even the sign is unresolved.

**8. The window question has a defensible answer, and it is not the documented
one.** Excluding 2020–21 as regime outliers is legitimate — the criterion is
independent of performance and was stated in advance. But excluding 2022 as well,
as the strategy document does, is a different and much weaker claim. On the
honest middle window (2022+, post-pandemic but including the bear) the strategy
**wins on every metric**: +9.4pp CAGR, Sharpe 0.97 vs 0.82, Calmar 0.70 vs 0.48,
max drawdown −58.2% vs −64.8%. That is the strongest evidence in this study and
it deserves to be stated as plainly as the negative findings.

**9. It is still not statistically established, on any window.** Two independent
methods agree: the block bootstrap over 2020–26 gives [−37.9, +23.2]pp, and the
annual t-test over 2022+ gives [−28.5, +45.8]pp with t = 0.46. Five years of a
three-stock strategy whose annual excess has a 42-point standard deviation cannot
resolve a 9-point edge.

**10. A high-Z profit take is the one modification that survived everything.**
§5.28 shows `Z > 2.0` raising Sharpe on all three windows (1.10→1.19, 0.97→1.05,
1.71→2.01) while cutting average exposure from 98% to 65%; on the full 2020+
history a `Z > 2.5` take converts a −6.7pp deficit into a +1.3pp surplus. Nothing
else tested — trail ratchet, momentum gating, regime filters, core hybrid — held
up on every window. It should be added.

Two caveats that keep it honest. It is **risk reduction, not alpha**: across 30
names it improved CAGR on 12 but cut drawdown on 28. And it works because of
§5.30 — Z reverts mostly because the moving average rises (+12.6%) rather than
because price falls (+2.9% mean), so the "sell high, buy back lower" discount is
a median −1.3%, not the large one intuition suggests.

**11. What I would actually conclude.** *A drawdown-reduction overlay on
concentrated tech beta that looks genuinely good on the post-pandemic window and
genuinely bad when the 2020–21 melt-up is included, whose excess return is not
statistically distinguishable from zero on either, and whose one thoroughly
robust component is the entry signal used for deploying new money rather than for
timing exits.*

**12. Concentration risk is understated.** 25–35% positions across four names that
are one AI/megacap-tech factor is not a four-position portfolio. Max drawdown of
−31% was measured entirely inside a bull market.

---

## 8. Open questions for the reviewer

1. **Is the selection-bias test fair?** A 29-name basket of *current* large caps
   has survivorship bias that should favour the strategy. Median excess is still
   −2.2pp. Is there a better construction — 2022 index membership, or a
   volatility/trend-matched cohort?

2. **Is the exposure argument airtight?** Monotone returns in position size at
   flat drawdown reads to me as decisive proof that this is beta, not alpha. Is
   there a reading where a genuine signal produces that same profile?

3. **Is there a salvageable version?** §5.13 tested four candidates. Tightening
   the trail and momentum-ranking both failed in-sample; vol-targeting helped
   marginally. Two ideas remain untested:
   - Using the dip signal to *add* to a permanent core rather than to time entries
   - Sizing by forecast volatility rather than trailing ATR

4. **Is the out-of-sample momentum result (§5.13d) real, or selection?** It has
   the right shape — stable IS/OOS, shallower drawdown, positive decay — but I
   chose it by looking at the OOS window after testing seven variants. What would
   a properly nested walk-forward need to show before this is believable?

5. **Does the same-bar fill invalidate anything?** Signal and fill both use the
   bar's close. Should this be re-run with next-open fills, and would that change
   the ordering versus buy & hold?

6. **Why does the regime filter fail so badly?** My explanation is that a
   `Z < −1.2` dip often coincides with price under its own 200-SMA, so the gate
   removes precisely the recoveries the system needs. Is that right, and does it
   imply the filter should be applied to the *index* rather than the name? The
   SPY variant was less bad (31.3% vs 24.0%) but still far worse than no filter.

7. **Does the 2022 result rescue anything?** Cushioning a −60% year to −49.7% is
   the strategy's one clear win (§5.16), and §5.19 shows the effect is strongest
   with *no* core at all. Is there a version that runs the dip-and-trail machinery
   only when it pays — and is any such switch knowable in advance, given that the
   200-SMA regime filter (§5.9) fails so badly?

8. **Given all of the above, what would you actually trade?** Concentrated
   buy-and-hold with a disaster stop? A volatility-targeted version? Nothing?

---

## 9. Reproducing this

```bash
pip install -r requirements.txt
python studies/dip_backtest.py      # importable engine
python studies/run_dip_study.py     # main study  -> studies/results/
python studies/run_improvements.py  # 5.12-5.13  -> studies/results_improvements/
python studies/run_regime_study.py  # 5.14-5.19  -> studies/results_regime/
python studies/run_recommendation.py # 5.20-5.22  -> studies/results_recommendation/
python studies/run_allocation.py    # 5.23       -> studies/results_allocation/
python studies/run_a_vs_b.py        # 5.24-5.27  -> studies/results_a_vs_b/
python studies/run_profit_take.py   # 5.28-5.32  -> studies/results_profit_take/
streamlit run app.py                # live dashboard
```

Outputs land in `studies/results/` — 15 CSVs plus `summary.json`. Every number in
§5 is traceable to one of them:

| Section | File |
|---|---|
| 5.1 Claim reproduction | `01_baseline_reproduction.csv` |
| 5.2 Benchmarks | `02_benchmarks.csv` |
| 5.3 Pyramiding | `03_pyramiding_mode.csv` |
| 5.4 Parameter surface | `04_parameter_surface.csv` |
| 5.5 Position size | `05_position_size.csv` |
| 5.6 Universes | `06_universe_variants.csv` |
| 5.7 Selection bias | `07_selection_bias.csv` |
| 5.8 Walk-forward | `08_walk_forward.csv` |
| 5.9 Regime filter | `09_regime_filter.csv` |
| 5.10 Robustness | `10a_commission.csv`, `10b_start_date.csv` |
| 5.11 Trades | `11a_per_ticker.csv`, `11b_trades.csv` |
| Equity curve | `12_equity_curve.csv` |
| 5.12 Null test | `results_improvements/A_null_test.csv` |
| 5.13a Trail ratchet | `results_improvements/C_trail_ratchet.csv` |
| 5.13b Vol-target sizing | `results_improvements/B_vol_target.csv` |
| 5.13c Momentum universe | `results_improvements/D_momentum_universe.csv` |
| 5.13d Out-of-sample | `results_improvements/F_out_of_sample.csv` |
| 5.14 Extended history | `results_regime/A_extended_history.csv` |
| 5.15 Calendar years | `results_regime/B_calendar_years.csv` |
| 5.16 2022 bear | `results_regime/C_bear_market.csv` |
| 5.17 Rolling walk-forward | `results_regime/D_rolling_walk_forward.csv` |
| 5.18 Bootstrap | `results_regime/E_bootstrap_summary.csv` |
| 5.19 Core hybrid | `results_regime/F_core_hybrid.csv`, `F_core_hybrid_2022.csv` |
| 5.20 Window sensitivity | `results_recommendation/1_window_sensitivity.csv` |
| 5.21 Error bar | `results_allocation/2_annual_excess.csv` |
| 5.22 DCA vs dip-timing | `results_recommendation/3_dca_vs_dip_timing.csv` |
| 5.23 Allocation blends | `results_allocation/1_blend_spy.csv`, `3_final_comparison.csv` |
| 5.24 A vs B head to head | `results_a_vs_b/1_head_to_head.csv` |
| 5.25 Entry/exit decomposition | `results_a_vs_b/2_decomposition.csv` |
| 5.26 Bear, generalisation, blends | `results_a_vs_b/4_bear_market.csv`, `5_generalisation.csv`, `6_blends.csv`, `7_idle_cash.csv` |
| 5.28 Profit-take sweep | `results_profit_take/1_z_threshold_sweep.csv`, `4_across_windows.csv` |
| 5.29 Post-exit diagnostic | `results_profit_take/5b_post_exit_summary.csv` |
| 5.30 Z decomposition | `results_profit_take/6_z_decomposition.csv` |
| 5.31 Profit-take generalisation | `results_profit_take/8_generalisation.csv` |
| 5.32 Earnings | `results_profit_take/7_pre_earnings.csv` |

Engine assumptions are in `studies/dip_backtest.py` docstrings; every one is a
constructor parameter on `BacktestConfig`.

---

*Not investment advice. Past performance is not indicative of future results.*
