# Project Briefing — read this first

**Purpose of this file:** a single self-contained catch-up. If you are an AI
assistant or a new collaborator, reading only this document should be enough to
work on the project usefully. Everything else in the repo is detail behind the
claims made here.

**Last updated:** 22 August 2026
**Repo:** `Service_NOW_analysis` (the name is historical — the project long ago
stopped being about ServiceNow)

---

## 1. What this project is

A systematic dip-buying system for US large-cap equities, plus an unusually
adversarial body of research testing whether it actually works.

The short answer to "does it work": **there is a small, real, measurable edge in
*when* you buy, and no edge whatsoever in when you sell.** Almost all of the
return is beta — exposure to a rising equity market. Four studies were run
largely to establish that, and to kill eleven plausible-sounding improvements.

**The owner has real money at stake and has consistently asked to be told the
edge is illusory rather than discover it later.** Do not soften findings. The
project's whole value is that its negative results are trustworthy.

---

## 2. Who you are working with

- Individual retail investor, not a fund. Deploys personal savings.
- **Stated objective: maximise profit.** Has explicitly said so when offered
  risk-reduction alternatives. Tell them the risk cost anyway, then do what they
  asked.
- Writes and reads code; comfortable with pandas, backtests, and statistics.
- **Wants brevity.** Has asked more than once for shorter answers. Lead with the
  answer, then the evidence. Tables over paragraphs.
- Pushes back on conclusions and asks "is there anything there?" — wants a
  yes/no before the nuance.
- Prefers to be shown a plan before a large build, then says "yes run it."

---

## 3. The history, in the order it happened

### Phase 1 — two strategies, both about exits

**Method A — Dual-Mode Tactical**
Entry `Z(20) < −1.5`. Trailing stop `Close − 2×ATR(14)`, raise-only, ATR re-read
daily. Exit on trail hit **or** `Z > 0` (mean reversion complete).

**Method B — Aggressive Dip Accumulation**
Entry `Z(20) < −1.2`. Trailing stop = highest close since that lot's entry
`− 4×ATR`, with **ATR frozen at entry**. **No mean-reversion exit.** 20% of
current equity per lot, pyramiding allowed. Universe META/NVDA/NET.

B was designed to fix A's defect: A caps every winner at the mean while risking
2×ATR, a structurally sub-1:1 reward/risk. That diagnosis was correct — 95% of
A's exits went on to trade higher, median +53% left behind.

### Phase 2 — `01_STRATEGY_REVIEW.md`: B's claims reproduce, its conclusions don't

B's documented numbers reproduced within 4–7%. But:

| Finding | Number |
|---|---|
| Documented window (2023-01→) excess vs buy & hold | **+3.0pp CAGR, lower Sharpe** |
| Full history (2020-01→) excess | **−6.7pp — the edge inverts** |
| 2022+ (post-pandemic, includes the bear) | **+9.4pp, wins on every metric** |
| Beat buy & hold in how many calendar years? | **3 of 7**, median −14.3pp |
| Bootstrap 95% CI on excess CAGR | **[−37.9, +23.2]pp**, P(excess ≤ 0) = 0.63 |
| Annual t-test on 2022+ | mean +8.7pp, sd 42.4pp, n=5, **t = 0.46** |
| Applied to 29 other large caps | Beat B&H on **10/29**, median **−2.2pp** |
| Re-optimising parameters on walk-forward | **11.8pp WORSE than freezing them** |
| Returns vs position size | **Monotonic at constant drawdown → it's exposure** |
| Profit concentration | **10 of 105 lots = 83% of all profit** |

**The decisive decomposition (§5.25):** crossing each strategy's entry with each
strategy's exit shows the **exit rule drives 21.3pp of CAGR and the entry
threshold 0.9pp.** They are one entry rule with two exits, and essentially all
the difference lives in the exit.

**But the documented window starts 2023-01-03 — the week after META fell 64.5%,
NET 64.2% and NVDA 51.4% in 2022.** The track record begins at a generational
low in its own universe.

### Phase 3 — `02_OVERREACTION_STUDY.md`: what a good dip actually looks like

The owner's hypothesis: *"If GOOGL drops 10% on earnings news but the business
is strong, that's clearly an overreaction — I can buy it."*

Tested on **17,235 dip events, 124 names, 2015–2026**, with month-clustered
t-statistics (events cluster hard in time; naive t-tests badly overstate
significance).

**The null control is the single most important result in the project.** Random
entry dates on the same names at the same frequency:

| Horizon | Dip entries | Random entries | **True edge** |
|---|---|---|---|
| 5d | +0.29pp | +0.14pp | **+0.16pp** |
| 20d | +0.83pp | +0.49pp | **+0.34pp** |
| 60d | +1.86pp | +1.46pp | **+0.40pp** |
| **120d** | +3.15pp | +3.15pp | **−0.00pp** |

Beats **200 of 200** random draws at 5/20/60 days (p < 0.005). So the signal is
real and cleanly significant — **and it is worth +0.3 to +0.4pp per trade, and it
is completely dead by 120 bars.** Everything past that is beta.

> **Direct consequence:** Method B holds lots **83 bars on average**. The signal
> it entered on has stopped paying well before then.

**Three tags tested against the literature** (Chan 2003 *Stock Price Reaction to
News and No-News*; Savor 2012; Bernard & Thomas 1989 on post-earnings drift):

| Hypothesis | Verdict | Number |
|---|---|---|
| Volume as a news proxy | **Rejected** | t < 1 everywhere; sign flips across halves (+0.17 → −0.57) |
| Earnings proximity | **Confirmed** | No-earnings dips beat post-earnings by **+0.80pp @20d, t = 2.35**; stable in both halves (+0.79 / +0.71) |
| Idiosyncratic vs market-wide | **Confirmed** | Market-wide dips beat name-specific at **every** horizon (−0.48pp, t = −2.30 at 5d) |
| Breadth | Confirmed | Lonely fallers were the **worst** cohort (+1.04pp @60d vs +2.60pp for mid-breadth) |

**The synthesis, and it is the core insight of the project:**

> **Dips caused by something specific to the company DRIFT. Dips caused by the
> market dragging the company down REVERSE.**

Which makes the owner's original hypothesis **wrong on both counts** — a
post-earnings drop in a specific name is simultaneously the worst earnings
cohort *and* the worst idiosyncratic cohort. It also means the old dashboard's
rule of **sizing up to 35% within 10 days after earnings is backwards**.

### Phase 4 — `03_OPTIMISATION_STUDY.md`: two structural fixes, both rejected

**Time exit** (leave at a fixed bar count, since the signal expires at 120 bars):
worse than the trail at *every* setting across 6 universe × window combinations.
Mean Sharpe 1.15 for trail-only vs 1.14 at best.

> **The reasoning error, worth remembering: "the signal has expired" is not the
> same claim as "the position has negative expected value."** After the dip edge
> decays what remains is beta, which was positive. Exiting on a clock converts a
> positive-expected-return asset into cash. Exposure fell 96–99% → 44–66%.

**Model-predicted sizing** (9-feature OLS on ex-ante tags, weight by predicted
edge): looked good — +0.2pp per trade, both split directions, quintiles sorting
out of sample. Then the control killed it:

| Variant | 20d gain | 60d gain | Vol tilt |
|---|---|---|---|
| Full (9 features) | +0.216pp | +0.195pp | +17.8% |
| **`rvol20` alone** | **+0.419pp** | **+0.847pp** | **+36.9%** |
| Vol & size removed | +0.229pp (t 1.51) | +0.130pp (t 0.38) | +13.4% |

**One volatility feature beat the whole model, 2× at 20d and 4× at 60d.** The
"edge model" was sizing up the jumpy names. That is the exposure finding again,
wearing a regression.

> **Second error worth remembering: always check which feature is doing the work
> before believing a sizing model.**

### Phase 5 — `04_PORTFOLIO_STUDY.md`: the measurement that explains everything

**Effective number of independent bets** (participation ratio of the correlation
eigenvalue spectrum — equals *n* if all names are independent, 1 if they are all
the same bet):

| Universe | Tickers | **Effective bets** | Largest factor |
|---|---|---|---|
| META / NVDA / NET | 3 | **2.10** | **64% of variance** |
| 30 tech names | 30 | **4.65** | 44% |
| 50 mixed-sector names | 50 | **8.47** | 31% |

**This is the binding constraint on the whole project.** Position sizing across
30 tickers that are really 4.6 bets cannot accomplish much — which is exactly
what the cap sweep found (Sharpe flat from a 5% cap to no cap).

And the biggest single effect found anywhere:

| Same rules, 2020+ | CAGR | Max DD | Sharpe |
|---|---|---|---|
| 30 tech names | 27.5% | **−51.2%** | 0.90 |
| 50 mixed sectors | 26.4% | **−30.2%** | **1.10** |

**21 points less drawdown for 1 point of CAGR.** No sizing rule tested anywhere
comes close to that exchange rate.

Risk parity (equal-risk instead of equal-dollar) helps **only on the mixed
universe** — 2022+ Sharpe 0.63 → 0.77, drawdown −40.2% → −29.4%. On all-tech it
does nothing, because there is no dispersion in risk to equalise.

### Phase 6 — the screens, and the strategy that came out of it

The best screens, measured two ways:

| Screen | Per-event @20d | As a deployment rule |
|---|---|---|
| Unfiltered dip | +0.83pp (t 4.76) | **LOST to DCA** (−2.8% mean) |
| + no earnings 20d | +1.09pp (t 4.92) | −2.4% |
| **+ no earnings + not lonely** | **+1.94pp (t 5.40)**, both halves positive | +0.7% |
| **+ no earnings + market-wide + not lonely** | +1.20pp (t 2.43), fails 2nd half | **+8.0% mean, won all 3 windows** |

**A surprise worth knowing:** unfiltered dip-deployment *lost* to scheduled
investing on 124 names. With that many names something is always dipping (average
wait: 0.02 days), so it degenerates into DCA with worse selection. **The screen
is what makes dip-timing work.**

**Caveat on the +8.0%:** those three windows are *nested* (2022+ ⊂ 2020+ ⊂
2015+), so it is roughly **one** independent observation, not three. The
per-event evidence is statistically much stronger than the deployment evidence.

---

## 4. The current strategy

1. Hold a wide basket of large caps — **many sectors, not just tech**
2. **Never sell.** No exit rule has ever survived a control
3. Deploy new money into **dips**, not on a schedule
4. Only dips that are **not near earnings** and where the **market** is dragging
   the name down — not the company's own news
5. **Depth is irrelevant** beyond the −1.2 threshold (−1.2 ≈ −0.8 ≈ −0.5)
6. Do not expect the signal to pay past ~60–120 bars

### The economics, honestly

+0.34pp per trade × ~12 twenty-day trades a year ≈ **4pp gross**. Commissions
eat ~1pp; cash drag from waiting eats ~1pp. **Net +1 to +3pp/year before tax.**

On $10,000 that is roughly **$200/year**. The same basket swings ±$3,000. The
edge is a rounding error next to the risk. **The owner's contribution rate
dominates everything in this repository.** This makes a concentrated equity bet
slightly more efficient; it does not make it safe and it is not a return engine.

---

### Deployment Desk v3 (Sep 2026) — the "Your call" lane

Dips the rules skip (company news, just after earnings, falling alone) are no
longer hidden: they show as 🟠 **Your call** with headlines, the historical base
rate, and a Buy/Pass log (`data/journal.py`). The owner's view: a rule cannot
read a headline (the META lawsuit dip was a correct overreaction call). The
data's view: these drift lower on average. The journal settles it — score the
owner's calls vs QQQ after ~30 decisions (Build 2) before trusting either.

## 5. The graveyard — do not re-propose these

Eleven interventions, all tested with out-of-sample or null controls, all failed.
Full detail with numbers in `docs/DEAD_ENDS.md`.

| Intervention | Result |
|---|---|
| Re-optimise `z_entry` / `atr_mult` | −11.8pp vs freezing. No stable optimum exists |
| Tighten the trailing stop | Worse on CAGR *and* Sharpe at every setting |
| Momentum-gate the universe | Much worse at every N |
| 200-SMA regime filter on entries | **CAGR cut by two thirds.** Dips print below the 200-SMA, so the gate removes the recoveries |
| Permanent core + dip lots | Monotonically worse than pure buy-and-hold |
| Partial scale-outs / min-gain filters | Worse at every setting |
| Volume as a news proxy | t < 1; sign flips across halves |
| Stacking every event-tag filter | Triple screen: 17,235 events → 786, significance gone |
| Fixed-bar time exit | Worse than the trail at every setting |
| Model-predicted position sizing | Collapses into a volatility tilt |
| Per-name exposure cap | Sharpe flat; only costs return |

**Also settled:** buy-and-hold beats the dip-and-trail machinery on return
(§5.19 — return rises monotonically as you dilute toward pure B&H). The
machinery buys drawdown protection at a roughly fixed exchange rate, everywhere
on the curve. There is no free lunch anywhere on that trade.

---

## 6. What is still genuinely open

- **Cross-sectional ranking** — take the *best available* dip each day from a
  ranked list rather than every dip clearing an absolute bar. Different
  mechanism from anything tested; never tried.
- **Explicit volatility targeting** as a risk decision rather than a return
  model, judged on risk-adjusted terms against simply holding less.
- **The LLM advisory layer** (`data/advisor.py`) has **never been backtested**
  and cannot be from this repo — see §8.
- **Non-linear conditioning.** The sizing model was linear. But note its failure
  was not functional form; one feature dominated and that feature was risk.

---

## 7. Repo layout and commands

```
appV2.py          ← THE LIVE APP.  streamlit run appV2.py
app.py               obsolete (banner in file + UI). Keeps the Portfolio tab
BRIEFING.md          this file
README.md            quickstart
DIRECTORY.md         the map

docs/    01_STRATEGY_REVIEW · 02_OVERREACTION_STUDY · 03_OPTIMISATION_STUDY
         04_PORTFOLIO_STUDY · DEAD_ENDS · legacy_*
data/    screen.py (the live rules) · advisor.py (LLM) · market · portfolio
         strategies (A/B) · media_earnings (informational only)
         holdings · watchlists · market_pulse · signals · news · journal (Desk v3)
ui/      desk_*.py — appV2's five tabs: Today · Stocks · Portfolio · Market · How it works
studies/ dip_backtest.py (portfolio engine) · overreaction_lib.py (event study)
         run_*.py × 13 · results/<nn>_<name>/ (97 CSVs, committed on purpose)
tests/   96 checks, synthetic fixtures, no network
```

```bash
python tests/test_backtest_engine.py           # 27 checks
python tests/test_strategies_and_portfolio.py  # 28 checks
python studies/run_overreaction_control.py     # the null control
```

**Conventions that matter:**

- Every claim in `docs/` traces to a CSV in `studies/results/`. Keep it that
  way — cite the file whenever you state a number.
- **`studies/results/` is gitignored**, so a fresh clone has the claims but not
  the files behind them. If you need to verify something, re-run the runner
  that produces it (`DIRECTORY.md` maps runner → folder). Full set is ~40 min.
- Events cluster in time. Always collapse to monthly means before a t-test, and
  pair cohorts by month so the common market factor cancels.
- The repo lives in a **OneDrive folder**, which has been observed renaming
  directories mid-operation as sync conflicts. Verify after bulk moves.
- `portfolio_data/` and `.streamlit/secrets.toml` are gitignored and contain
  real personal data. Never commit or transmit them.

---

## 8. Rules for an AI working on this

1. **Check `docs/DEAD_ENDS.md` before proposing an improvement.** Eleven ideas
   are already dead. Re-proposing one wastes a study.
2. **Be adversarial.** The owner has repeatedly asked to be told the edge is
   illusory rather than find out later. A negative result delivered plainly is
   the most valuable output here.
3. **Always run a control.** The project's two biggest mistakes both came from
   accepting a result that looked good before asking what was actually driving
   it. Null tests against random entries; cohort differences paired by month;
   split-sample stability checks. A result without a control is a hypothesis.
4. **Distinguish beta from alpha, every time.** This universe rose over the
   sample. Any long-only strategy on it shows a positive "excess vs SPY". Only
   the *difference* between cohorts, or against randomly-timed entries on the
   same names, is informative.
5. **Watch for exposure in disguise.** Returns scale monotonically with position
   size here. Anything that raises return by raising volatility, leverage, or
   time-in-market is not a signal — say so.
6. **Lookahead is the largest risk in any LLM feature.** A model scoring 2023
   news knows what happened in 2024. Any backtest of the advisory layer without
   point-in-time data and a knowledge-cutoff-aware model will look brilliant and
   be worthless. This is why `data/advisor.py` is advisory-only.
7. **Do not add sell logic** without evidence that clears the graveyard bar.
8. **Answer briefly.** Yes/no first, then the number, then the caveat.

---

## 9. Academic references the project relies on

| Paper | Relevance |
|---|---|
| Chan (2003), *Stock Price Reaction to News and No-News* | The core result: news-driven moves drift, no-news moves reverse. Reproduced here twice, independently |
| Savor (2012), *Stock Returns After Major Price Shocks* | Same split, confirms Chan |
| Bernard & Thomas (1989), post-earnings announcement drift | Prices under-react to surprises; drift runs 60–90 days. Directionally present here but underpowered (n = 403 misses) |
| De Bondt & Thaler (1985) | Long-horizon overreaction — real, but at 3–5 years, not at the horizon this system trades |
| Jegadeesh & Titman (1993) | Cross-sectional momentum — the *opposite* of dip-buying, which is why momentum gating failed |
| Moskowitz, Ooi & Pedersen (2012) | Time-series momentum works on indices, not single-name dips |
| McLean & Pontiff (2016) | Published anomalies lose ~58% of their return. Calibrate expectations accordingly |
| Kim, Muhn & Nikolaev (2024) | GPT-4 beat analysts at predicting earnings direction from anonymised financials — the strongest precedent for the LLM layer |
| Lopez-Lira & Tang (2023) | LLM headline sentiment predicted next-day returns; concentrated in small caps, has decayed |

---

*Research and educational use only. Not investment advice. Past performance is
not indicative of future results.*
