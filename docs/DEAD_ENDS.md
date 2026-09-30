# Dead Ends

**Read this before proposing an improvement.** Every entry below was tested
properly — with an out-of-sample split, a null control, or a stability check —
and failed. They are recorded so the same ground is not covered twice.

Nothing here is lost. Files removed from the working tree are preserved in git
history at commit **`820aeb6`** (`820aeb60c934fcbbda53f84bfb6c3079e9170f2a`).
Recover any of them with:

```bash
git show 820aeb6:<path>                 # print it
git checkout 820aeb6 -- <path>          # restore it to the working tree
```

---

## Part 1 — Ideas that were tested and failed

Eleven interventions. All were aimed at making the strategy better; none
survived a control.

| # | Intervention | Result | Source |
|---|---|---|---|
| 1 | Re-optimise `z_entry` / `atr_mult` on a rolling walk-forward | **−11.8pp worse than freezing them.** Fitted values jumped between Z<−0.8 and Z<−2.0, and 2×ATR and 6×ATR, between adjacent windows | `01_STRATEGY_REVIEW.md` §5.17 |
| 2 | Tighten the trailing stop once a lot is up N×ATR | Worse on CAGR **and** Sharpe at every setting | §5.13a |
| 3 | Momentum-gate the universe (buy dips only in top-N by 12-1 momentum) | Much worse in-sample at every N; worse than holding the basket | §5.13c |
| 4 | 200-SMA regime filter on entries | **CAGR cut by two thirds** (83.3% → 24.0%). A dip usually prints below the 200-SMA, so the gate removes precisely the recoveries the system needs | §5.9 |
| 5 | Permanent core + dip lots (hybrid) | Monotonically worse — return rises as you dilute toward pure buy-and-hold | §5.19 |
| 6 | Partial scale-outs and minimum-gain filters on the profit take | Worse at every setting. Full exits beat partials; a min-gain filter destroys 15pp of CAGR | §5.28 |
| 7 | Volume as a news proxy | t < 1 at every horizon, and the **sign flips** between sample halves (+0.17 → −0.57) | `02_OVERREACTION_STUDY.md` §3 |
| 8 | Stacking every event-tag filter | The triple screen cut 17,235 events to 786 and **lost significance entirely** | §7 |
| 9 | Fixed-bar time exit (10/20/40/60/90/120 bars) | Worse than the trail at every setting, on all 6 universe × window combinations | `03_OPTIMISATION_STUDY.md` §2 |
| 10 | Model-predicted position sizing (9-feature OLS) | Collapses into a **volatility tilt** — one feature (`rvol20`) alone captured 194% of the gain at 20d and 436% at 60d | §3 |
| 11 | Per-name cumulative exposure cap | Sharpe flat from 5% to no cap; capping only costs return | `04_PORTFOLIO_STUDY.md` §3 |
| 12 | Momentum as a holding rule (top 20 of the 200 most-traded stocks by 12-1 return, monthly, pre-registered) | **FAIL, narrowly:** +0.70pp a month vs random portfolios but **t = 1.80** (bar 2.0). About half the edge is from 2020 (excluding it: +0.38pp, t = 1.0); 2006–2016 ≈ 0; worst drop −62% vs −51% for SPY. Survivor bias flatters it and it still failed | `05_MOMENTUM_STUDY.md` §6 |
| 13 | Insider buying → hold established tech for weeks (insider-trading repo, H8) | No edge: −0.22pp at 60 days (t −0.24), 1,125 events | insider-trading `docs/01_INSIDER_STUDY.md` §5 |

### The two mistakes worth remembering

**"The signal has expired" is not the same claim as "the position has negative
expected value."** Dead end #9 came from correct premises: the entry signal's
excess over random decays to exactly zero by 120 bars, and Strategy B holds 83
bars on average. The inference — therefore exit on a clock — does not follow.
After the dip edge decays what remains is beta, and beta on this universe was
strongly positive. Exiting on a clock converts a positive-expected-return asset
into cash. Average exposure fell from 96–99% to 44–66%, and returns on this
system scale with exposure.

**A model whose dominant feature is risk is not predicting returns.** Dead end
#10 produced a clean-looking out-of-sample result — +0.2pp per trade, consistent
across both split directions and both horizons, with quintiles that sorted. It
was a volatility tilt. The book it built carried 17–37% more volatility and
8–16% more beta than equal weight. Always check *which feature is doing the
work* before believing a sizing model.

---

## Part 2 — Code deleted from the working tree

### `studies/media_backtest_lib.py` + `studies/media_sentiment_backtest_study.ipynb`

**The media-sentiment research line. Cannot be honestly backtested from this
repository, and no amount of further work on it changes that.**

1,089 lines of library plus a 36-cell notebook, built to test whether daily or
rolling media-sentiment scores improve the mean-reversion entry.

**Why it is a dead end.** The daily media scores default to a **reproducible
simulator** — `load_or_simulate_media()` generates them from a hash. Any result
the notebook produces is measuring the simulator, not the news. Alpha Vantage's
`NEWS_SENTIMENT` endpoint only serves recent history, not the multi-year series
a backtest needs, so there is no way to swap real data in without a paid
historical news dataset.

**What would be needed to revive it:** a licensed point-in-time news-sentiment
dataset covering 2015 onward. Until that exists, this cannot produce a real
result. See `01_STRATEGY_REVIEW.md` §5.32.

**Still live and untouched:** `data/media_earnings.py` and
`ui/media_earnings_tab.py` — the informational Media & Earnings tab in `app.py`.
That layer never gates a signal and is not affected by this deletion.

**A second reason to be sceptical of reviving it.** `02_OVERREACTION_STUDY.md`
§3 tested the crudest available news proxy — volume on the dip bar — and found
nothing, with the sign flipping across sample halves. The one news-related axis
that *did* work (earnings proximity) needs no sentiment data at all, just a
calendar.

---

### `testing/test1.ipynb`, `test2.ipynb`, `test3.ipynb`, `test_4.ipynb`

**The origin notebooks. Superseded by the portfolio-level engine, and their
central conclusion has been reversed.**

Roughly 1.7 MB of exploratory single-name backtests where Methods A and B were
originally developed:

| File | Contents | Superseded by |
|---|---|---|
| `test1.ipynb` | First mean-reversion experiments on single names | `studies/dip_backtest.py` |
| `test2.ipynb` | Strategy A on NOW, 2020+ — the +18.1% CAGR result and the trade log showing 69.8% win rate with +6.36% average winner | §5.0, §5.24 |
| `test3.ipynb` | Multi-stock mean-reversion tester — Strategy A across 17 names since 2025 | §5.7, §5.26b |
| `test_4.ipynb` | Dual-mode tactical production system, the direct ancestor of `app.py` | `app.py` |

**Why they are a dead end.** They are all-in / all-out single-name loops. They
cannot express a portfolio where lots compete for one cash balance and position
size is a fraction of a growing equity figure — which is where every result in
this project that mattered came from. More importantly, the conclusion they were
used to support has since been overturned: `test2`/`test3` were the evidence for
"Strategy A is defective," and §5.27 records that this was **overstated**. A is
a lower-exposure defensive sleeve, not a broken strategy.

**Every claim they supported has been reproduced** in the portfolio engine with
a null control attached, which the notebooks never had.

**Provenance note.** `01_STRATEGY_REVIEW.md` §3 and §5.0 cite these files. Those
citations now point here. The underlying numbers are reproduced in
`studies/results/06_a_vs_b/` and `studies/results/01_dip_study/`.

---

### `aggressive_dip_dashboard.py`

**A superseded standalone dashboard.** 600 lines implementing the Aggressive Dip
strategy as its own Streamlit app before `app.py` absorbed both strategies
behind a sidebar selector. It was already marked "kept for reference only."

**Why it is a dead end.** Two things it did are actively wrong by current
evidence. It sized **up to 35% within 10 days after earnings** — which
`02_OVERREACTION_STUDY.md` §4 shows is levering into the single worst cohort
measured (post-earnings dips returned −0.06pp at 5 days with a 47.2% hit rate).
And `find_assumed_entry()` *inferred* your open position from price history
rather than reading recorded lots, which `data/strategies.py` explicitly
replaced because the inference was unreliable.

---

### `production ready strategy.ipynb`

**A single-cell notebook holding an early compact version of the dual-mode
dashboard.** Entirely superseded by `app.py`, which does the same thing with
tested modules behind it.

---

## Part 3 — What actually survived

Three things, across four studies. **All three are about entry.** Nothing about
exits, position sizing, or filtering has ever improved this system in a way that
survived a control.

| Rule | Evidence |
|---|---|
| **Dip-time new money, never sell** | Beat scheduled investing; the most robust finding in the project — `01_STRATEGY_REVIEW.md` §5.22, `02_OVERREACTION_STUDY.md` |
| **The `Z < −1.2` entry signal** | Beats 200/200 random draws at 5/20/60 bars. Worth **+0.3 to +0.4pp per trade**, and **gone by 120 bars** — §2 |
| **Exclude dips within 20 bars of earnings** | +0.80pp at 20 days, t = 2.35, stable in both sample halves — §4 |

Plus one portfolio-level finding that outweighed every sizing rule tested:

| Finding | Evidence |
|---|---|
| **Widen the universe past one sector** | Same rules, **−30% drawdown instead of −51%**, on a better Sharpe. Thirty tech names are only **4.6 independent bets**; the original META/NVDA/NET trio is **2.1** — `04_PORTFOLIO_STUDY.md` §1, §5 |

---

## Part 4 — Open questions this does *not* close

Recorded so it is clear what has and has not been ruled out:

- **Cross-sectional ranking.** Taking the *best available* dip each day from a
  ranked list, rather than every dip clearing an absolute `Z < −1.2` bar. A
  different mechanism from anything above; never tested.
- **Explicit volatility targeting** as a risk decision rather than a return
  model. Dead end #10 says any "edge model" collapses into this, so it deserves
  evaluating on its own terms — on risk-adjusted grounds, against simply
  holding less.
- **The LLM advisory layer.** `data/advisor.py` has **never been backtested**,
  and cannot be from this repository: a model scoring old news knows what
  happened next, so any backtest without point-in-time data would look
  brilliant and be worthless. It is advisory-only for that reason, not out of
  caution.
- **Deployment-window evidence is thinner than it looks.** The +8.0% result for
  the full screen was measured on three windows that are *nested*
  (2022+ ⊂ 2020+ ⊂ 2015+), so it is roughly **one** independent observation,
  not three.

---

*Not investment advice. Past performance is not indicative of future results.*
