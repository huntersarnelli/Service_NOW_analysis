# Overreaction Study — does the *cause* of a dip predict its forward return?

**Prepared:** 22 August 2026
**Code:** `studies/overreaction_lib.py`, `studies/run_overreaction_study.py`,
`studies/run_overreaction_control.py`
**Results:** `studies/results_overreaction/`

---

## 0. Why this study exists

`01_STRATEGY_REVIEW.md` establishes two things about the `Z < −1.2` entry:

- it beats random entries (§5.12), so dip-buying does something real, and
- the *depth* of the dip is irrelevant (§5.4) — −1.2σ, −0.8σ and −0.5σ are
  interchangeable.

That leaves an obvious gap. **A Z-score measures the magnitude of a move and
says nothing about its cause.** The premise being tested here — the one that
motivated the whole line of questioning — is that a 10% drop on an earnings
headline in a fundamentally strong company is "clearly an overreaction" and can
be bought.

The academic literature says the opposite:

| Paper | Finding |
|---|---|
| Chan (2003), *Stock Price Reaction to News and No-News* | Big moves **with** public news **continue**; big moves **without** news **reverse** |
| Savor (2012), *Stock Returns After Major Price Shocks* | Same split — shocks carrying information drift, shocks without it reverse |
| Bernard & Thomas (1989), PEAD | Prices **under**-react to earnings surprises; drift runs 60–90 days *in the direction of the surprise* |

If that holds here, then buying a dip that follows an earnings miss is buying
into a negative drift, and the live dashboard's rule of sizing **up to 35%
within 10 days after earnings** is backwards.

This study settles that before any language-model work is attempted. If the
cause of a dip does not predict its forward return, classifying causes with an
LLM is pointless.

---

## 1. Method

**Universe.** 124 liquid US names, $20B+, spanning mega / large / mid across
tech, financials, healthcare, consumer, industrials and energy. Deliberately
includes names that did badly over the window (INTC, PYPL, DIS, NKE, MRNA, ZM,
DOCU) so the basket is not a list of winners.

**Window.** 2015-01-01 → 2026-08-22 (11.6 years), warm-up from 2014-06.

**Event.** The bar on which `Z(20)` **crosses down** through −1.2. Crossings
rather than every qualifying bar, so one decline contributes one observation —
`every_bar` would count a single five-day slide five times and badly overstate
the sample.

**17,235 events.**

**Tags on the event bar** — all three chosen for being orthogonal to Z(20):

| Tag | Construction | What it proxies |
|---|---|---|
| `vol_ratio` | Volume ÷ 20-day median volume | News arrives with volume; noise does not |
| `days_since_earnings` | Trading days since the last report, after-close reports shifted to the next bar | News, precisely dated |
| `idio_z` | Z(20) recomputed on a market-neutralised index: rolling 120d beta on SPY → residual return → cumulative residual index | Name-specific decline vs. market-wide drag |
| `breadth` | Share of the universe simultaneously below −1.2 | Market event vs. lone faller |

**Forward returns.** Raw and market-excess (minus SPY over the identical span)
at 5 / 20 / 60 / 120 trading days.

**Inference.** Dip events cluster hard in time — a market selloff prints dozens
in the same week — so a naive t-test on 17,235 rows treats correlated
observations as independent and overstates significance badly. Every t-statistic
here collapses the panel to **one mean per calendar month first**, then tests
that series. Cohort comparisons are **paired by month**, which cancels the
common market factor.

---

## 2. The null control — and why the raw numbers are not what they look like

The untagged dip's forward excess over SPY looks impressive:

| Horizon | Raw return | Excess vs SPY | t | Hit rate |
|---|---|---|---|---|
| 5d | +0.91% | **+0.29pp** | 3.63 | 50.8% |
| 20d | +2.53% | **+0.83pp** | 4.76 | 50.9% |
| 60d | +5.93% | **+1.86pp** | 5.40 | 51.6% |
| 120d | +10.58% | **+3.15pp** | 5.41 | 51.0% |

**It is mostly beta.** This is a high-beta universe in a period when high-beta
US equity beat SPY, so holding *any* of these names on *any* random day beat
SPY. The control — 200 draws of random entry dates on the same names at the
same frequency, the §5.12 test applied here — separates the two:

| Horizon | Dip entries | Random entries | **Dip − random** | Percentile | p |
|---|---|---|---|---|---|
| 5d | +0.29pp | +0.14pp | **+0.16pp** | 100th | <0.005 |
| 20d | +0.83pp | +0.49pp | **+0.34pp** | 100th | <0.005 |
| 60d | +1.86pp | +1.46pp | **+0.40pp** | 100th | <0.005 |
| **120d** | +3.15pp | +3.15pp | **−0.00pp** | 49th | 0.51 |

Two findings, and both matter more than anything else in this document.

**The dip signal is real and cleanly significant.** It beats **200 of 200**
random draws at 5, 20 and 60 days. This is far stronger evidence than §5.12's
three-name test, on 124 names across a full cycle.

**And it is small, and it has a half-life.** The genuine contribution is
**+0.3 to +0.4 percentage points per trade**, and it is **completely gone by
120 days**. Roughly two-thirds of the sixty-day excess and *all* of the
hundred-and-twenty-day excess is beta you would have earned by throwing a dart.

> **Direct consequence for Strategy B.** B holds its lots an average of **83
> days** on a 4×ATR trail. The signal it entered on has stopped paying by then.
> What B is holding after roughly sixty days is not a dip trade — it is
> leveraged beta with a stop under it. That is the same conclusion
> `01_STRATEGY_REVIEW.md` §5.5 reached from the position-size sweep, arrived at
> from a completely independent direction.

---

## 3. Hypothesis 1 — volume as a news proxy. **Rejected.**

If information arrives with volume, a dip on thin volume is a no-news dip and
should reverse harder.

| Cohort | 5d | 20d | 60d | 120d |
|---|---|---|---|---|
| Low volume (no-news) | +0.34 | +0.78 | +2.10 | +3.63 |
| Mid volume | +0.23 | +0.73 | +1.82 | +3.06 |
| High volume (news) | +0.25 | +0.93 | +1.76 | +3.00 |

Paired by month, low-vol minus high-vol:

| Horizon | Difference | t |
|---|---|---|
| 5d | +0.09pp | 0.70 |
| 20d | −0.15pp | −0.52 |
| 60d | +0.34pp | 0.63 |
| 120d | +0.68pp | 0.98 |

**Nothing.** No horizon reaches even t = 1, and the sign flips across horizons.

Worse, it fails the stability test. Split the sample at 2021-06-04:

| | First half | Second half |
|---|---|---|
| low-vol − high-vol @ 20d | +0.17pp | **−0.57pp** |

The sign reverses. Volume is not a usable proxy for whether news arrived.

---

## 4. Hypothesis 2 — earnings proximity. **Confirmed.**

| Cohort | n | 5d | 20d | 60d | 120d |
|---|---|---|---|---|---|
| **Post-earnings (0–5d)** | 2,020 | **−0.06** | **+0.26** | +1.41 | +2.86 |
| Recent (6–20d) | 3,465 | +0.31 | +0.64 | +1.55 | +4.06 |
| **No earnings (>20d)** | 11,731 | **+0.38** | **+1.09** | +1.97 | +3.00 |

Paired by month, no-earnings minus post-earnings:

| Horizon | Difference | t | 95% CI |
|---|---|---|---|
| **5d** | **+0.44pp** | **2.36** | [+0.07, +0.80] |
| **20d** | **+0.80pp** | **2.35** | [+0.13, +1.47] |
| 60d | +0.54pp | 0.85 | [−0.70, +1.78] |
| 120d | +0.09pp | 0.10 | [−1.61, +1.80] |

**A dip away from earnings beats a dip right after earnings by 0.80pp over
twenty days, t = 2.35.** That is Chan and Savor, reproduced on this universe.

The post-earnings cohort is the **worst cohort in the study at short horizon**:
−0.06pp excess at five days with a **47.2% hit rate**. Buying the earnings drop
is, on average, buying nothing.

And unlike the volume result, **it is stable across the split sample**:

| | First half | Second half |
|---|---|---|
| no-earn − post-earn @ 20d | +0.79pp | +0.71pp |

Same sign, near-identical magnitude in both halves. Each half is individually
underpowered (t ≈ 1.3–1.8), but consistency across independent periods is the
signature the volume result lacked.

The effect decays to nothing by 60 days. **This is a twenty-day effect.**

### 4b. PEAD itself — directionally right, underpowered

Splitting post-earnings dips by the EPS surprise that caused them:

| Cohort | n | 5d | 20d | 60d | 120d |
|---|---|---|---|---|---|
| Miss | 403 | −0.08 | +0.41 | +0.50 | +2.82 |
| Beat | 1,615 | +0.00 | +0.30 | **+1.77** | +3.28 |

Beat minus miss, paired: **+1.44pp at 60d (t = 1.32)**, +1.29pp at 120d
(t = 0.69). The direction is Bernard & Thomas — dips after a beat recover, dips
after a miss keep drifting — but with 403 misses it does not clear
significance. Suggestive, not established.

---

## 5. Hypothesis 3 — idiosyncratic vs. market-wide. **Confirmed, with the sign inverted from expectation.**

| Cohort | 5d | 20d | 60d | 120d |
|---|---|---|---|---|
| Idiosyncratic drop (name-specific) | +0.31 | +0.75 | +1.68 | +2.72 |
| Mid | +0.11 | +0.74 | +1.69 | +3.24 |
| **Market-wide drop** | **+0.74** | **+1.19** | **+3.36** | **+3.51** |

Paired by month, idiosyncratic minus market-wide:

| Horizon | Difference | t |
|---|---|---|
| 5d | **−0.48pp** | **−2.30** |
| 20d | −0.49pp | −1.35 |
| 60d | −1.68pp | −1.61 |
| 120d | −1.14pp | −1.47 |

**Every horizon is negative.** The stock that fell because the whole market fell
outperforms the stock that fell on its own — significantly so at five days.

This looks like a refutation until the labels are read correctly. **An
idiosyncratic drop *is* the news case.** Something specific happened to that
company. A market-wide drop is the no-news case for that company — nothing
happened to it; it was dragged down by the index.

So this is Chan **confirmed a second time, through an entirely independent
construction**. The breadth tag says the same thing a third time:

| Cohort | 5d | 20d | 60d | 120d |
|---|---|---|---|---|
| Lonely (<18% of universe dipping) | −0.06 | +0.32 | +1.04 | +2.08 |
| Mid | +0.55 | +1.58 | +2.60 | +4.69 |
| Everything (>39% dipping) | +0.32 | +0.74 | +1.91 | +2.76 |

Being the only name falling is the worst place to be.

---

## 6. The synthesis

Three tags, three constructions, one answer:

> **Dips caused by something specific to the company drift. Dips caused by the
> market dragging the company down reverse.**

Which makes the premise this study was built to test **the losing side of both
tests that worked.** "GOOGL drops 10% on earnings news but the underlying
business is strong" is simultaneously:

- a **post-earnings** dip — the worst cohort at 5 and 20 days, and
- an **idiosyncratic** dip — the worse side of the idio split at every horizon.

The trade that the data supports is the one that feels least clever: **buy the
strong company that fell because the whole market fell**, not the one that fell
because of anything about itself.

### The dashboard rule this indicts

The live app sizes **up to 35% of equity within 10 days after earnings**. On
this evidence that is levering into the single worst cohort measured. It should
be inverted or removed.

---

## 7. The screens, ranked

| Screen | n | % of events | 5d | 20d | t@20d | 60d |
|---|---|---|---|---|---|---|
| Untagged dip *(current Method A/B entry)* | 17,235 | 100% | +0.29 | +0.83 | 4.76 | +1.86 |
| **+ no earnings within 20d** | 11,731 | 68% | **+0.38** | **+1.09** | **4.92** | +1.97 |
| + low volume | 5,688 | 33% | +0.34 | +0.78 | 3.01 | +2.10 |
| + idiosyncratic | 5,646 | 33% | +0.31 | +0.75 | 3.68 | +1.76 |
| + low vol & no earnings | 3,856 | 22% | +0.56 | +1.01 | 3.61 | +1.65 |
| + low vol & no earnings & idio | 786 | 4.6% | +0.63 | +0.59 | 1.16 | +1.40 |
| News dip (high vol **or** post-earnings) | 6,379 | 37% | +0.22 | +0.85 | 3.90 | +1.80 |

**One filter is worth adding: exclude dips within 20 days of an earnings
report.** It raises 20-day excess from +0.83 to +1.09pp, improves the
t-statistic, and still keeps 68% of events.

**Stacking filters destroys it.** The triple screen cuts the sample to 786
events and loses significance entirely — classic over-filtering. The marginal
tags are not independent enough to compound.

---

## 8. What this means for the LLM idea

The honest read is mixed, and it cuts both ways.

**For.** The axis that produced a real, stable effect is exactly the axis an LLM
would operate on — *is this decline about the company or about the market, and
if about the company, is the news material?* Earnings proximity is the crudest
possible version of that question and it still delivered +0.80pp at t = 2.35.
A classifier that distinguished a material guidance cut from a downgrade note
or a sympathy move would be a strictly finer instrument on a proven axis.

**Against.** The one crude proxy that *should* have worked — volume — produced
nothing and flipped sign across halves. That is evidence the axis is thin, not
that a better instrument would find more. And the ceiling is visible: the whole
earnings effect is +0.80pp per trade at 20 days, decaying to zero by 60. An LLM
layer would be splitting an effect of that size.

**The pitfall that will fool you.** An LLM scoring 2023 news knows what happened
next. Any backtest without point-in-time data and a knowledge-cutoff-aware model
will look brilliant and be worthless. This is the single largest risk in the
build, larger than cost or latency.

**Order of operations, if it is built.** Statistics narrow the field first —
124 names down to the handful printing a qualifying dip — and the model judges
only those. Model-first is expensive, slow, non-deterministic, and inverts the
one thing already known to work.

---

## 9. What is now established about the entry signal

| Question | Answer | Evidence |
|---|---|---|
| Does the Z-dip entry beat random? | **Yes** — 200/200 draws at 5/20/60d | §2 |
| How much is it worth? | **+0.3 to +0.4pp per trade** | §2 |
| How long does it last? | **Dead by 120 days** | §2 |
| Is the rest beta? | **Yes** — random entries earn +3.15pp at 120d | §2 |
| Does volume separate news from no-news? | **No** — t < 1, sign flips across halves | §3 |
| Does earnings proximity? | **Yes** — +0.80pp @20d, t = 2.35, stable across halves | §4 |
| Is PEAD present? | Directionally, underpowered (n = 403 misses) | §4b |
| Do idiosyncratic dips underperform market-wide dips? | **Yes**, every horizon | §5 |
| Is "buy the earnings overreaction" supported? | **No — it is the worst cohort measured** | §4, §6 |
| Best single filter? | Exclude dips within 20d of earnings | §7 |
| Do filters stack? | **No** — the triple screen loses significance | §7 |

---

## 10. Caveats

- **Survivorship.** The universe is names listed today. Companies that were
  large caps in 2015 and are gone are absent, which mildly favours any
  dip-buying result.
- **Same-bar fill.** Events are recorded and priced at the same close, matching
  the convention in `studies/dip_backtest.py`. Optimistic in absolute terms,
  consistent for comparisons.
- **Overlapping events.** Monthly clustering is a coarse correction. Events
  within a month on correlated names are still not independent, so the true
  standard errors are somewhat wider than reported.
- **Excess vs SPY is not risk-adjusted.** No beta adjustment is applied to the
  cohort levels. The *differences* are beta-free by pairing; the *levels* are
  not, which is precisely what §2 demonstrates.
- **Earnings dates from yfinance.** Roughly 12 years of history — deeper than
  `01_STRATEGY_REVIEW.md` §5.32 assumed — but restatements and timing errors are
  not audited. After-close reports are assigned to the next trading bar.

---

## 11. Reproducing

```bash
python studies/run_overreaction_study.py     # ~3 min -> studies/results_overreaction/
python studies/run_overreaction_control.py   # ~4 min -> 10_null_control.csv
```

| Section | File |
|---|---|
| §2 Baseline | `2_baseline.csv` |
| §2 Null control | `10_null_control.csv` |
| §3 Volume | `3_volume_cohorts.csv`, `3b_volume_difference.csv` |
| §4 Earnings | `4_earnings_cohorts.csv`, `4b_earnings_difference.csv` |
| §4b PEAD | `4c_pead_surprise.csv`, `4d_pead_difference.csv` |
| §5 Idiosyncratic | `5_idio_cohorts.csv`, `5b_idio_difference.csv` |
| §5 Breadth | `6_breadth_cohorts.csv` |
| §6 Quadrants | `7_quadrants.csv`, `7b_quadrant_difference.csv` |
| §4 Split sample | `8_split_sample.csv` |
| §7 Screens | `9_screens.csv` |
| Event panel | `1_events.csv` (17,235 rows, all tags) |

---

*Not investment advice. Past performance is not indicative of future results.*
