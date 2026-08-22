# Optimisation Study — two structural levers, both rejected

**Prepared:** 22 August 2026
**Code:** `studies/run_optimisation_study.py`, `studies/run_optimisation_control.py`
**Results:** `studies/results_optimisation/`
**Engine change:** `BacktestConfig.max_hold_days` added to `studies/dip_backtest.py`

---

## 0. Register of closed questions

**This document exists so these are not re-opened.** Each row was tested with an
out-of-sample or null control, not a grid search.

| Question | Answer | Where |
|---|---|---|
| Should a dip lot be closed at a fixed bar count instead of on the trail? | **No.** Worse mean Sharpe at every setting, 10d through 120d | §2 |
| Does the signal expiring at 120 bars mean the position should be exited? | **No** — the two are different claims, and conflating them was the error | §2.3 |
| Can lots be sized by a model of predicted edge? | **Only as a volatility tilt.** The model is ~all `rvol20` | §3 |
| Does predicted edge sort realised edge out of sample? | Yes, weakly — but a single volatility feature does it *better* | §3.3 |
| Is there conditioning signal left after neutralising volatility? | **Not established.** +0.13 to +0.23pp, t between 0.38 and 1.51 | §3.4 |
| Should `z_entry` / `atr_mult` be re-optimised? | **No** — already closed by `01_STRATEGY_REVIEW.md` §5.17 | §1 |

**Net effect on the strategy: nothing changes.** The trail stays, flat sizing
stays. Two plausible ideas were tested properly and neither survived.

---

## 1. The constraint every optimisation attempt has to respect

`01_STRATEGY_REVIEW.md` §5.17 ran a rolling walk-forward that re-optimised
`z_entry` and `atr_mult` on in-sample Sharpe. Re-optimising was **11.8pp worse
than freezing the parameters**, and the fitted values jumped between Z<−0.8 and
Z<−2.0, and between 2×ATR and 6×ATR, from one adjacent window to the next.

**There is no stable optimum on those knobs.** So this study tests no
parameters. It tests two *structural* changes, each motivated by a measured
finding rather than by a search.

---

## 2. Lever 1 — the time exit

### 2.1 The hypothesis

`02_OVERREACTION_STUDY.md` §2 measures the entry signal's excess over random
entries as **+0.16 / +0.34 / +0.40 / −0.00 pp** at 5 / 20 / 60 / 120 bars. The
signal expires.

Strategy B holds a lot **83 bars on average** and exits only on a 4×ATR trail —
so it routinely holds long past the point where the reason for entering has
stopped paying. §5.13a tightened the trail (worse at every setting) but nobody
had ever tested simply *leaving at a fixed bar count*.

`max_hold_days` was added to `BacktestConfig` for this. It is checked before
the earnings exit and after the trail, so a time exit never masks a trail hit
on the same bar. All 27 engine tests still pass.

### 2.2 The result

Swept across **6 combinations** — trio and 30-name basket × 2020+ / 2022+ /
2023+ — against the trail-only baseline:

| max_hold_days | Mean Sharpe | Mean excess vs B&H | Δ Sharpe vs trail | Sharpe wins | Δ CAGR |
|---|---|---|---|---|---|
| 10 | 1.07 | −10.53pp | −0.08 | 2 / 6 | −12.44pp |
| 20 | 1.11 | −5.28pp | −0.04 | 2 / 6 | −7.19pp |
| 40 | 1.04 | −5.93pp | −0.11 | 3 / 6 | −7.85pp |
| 60 | 1.08 | −3.43pp | −0.08 | 2 / 6 | −5.34pp |
| 90 | 1.03 | −6.58pp | −0.13 | 1 / 6 | −8.49pp |
| 120 | 1.14 | −0.31pp | −0.01 | 4 / 6 | −2.22pp |
| **none (trail only)** | **1.15** | **+1.91pp** | — | — | — |

**Rejected.** Every setting is worse on mean Sharpe, worse on mean CAGR, and
none wins on a majority of the six combinations. The pattern is monotone in the
wrong direction: the shorter the leash, the worse the outcome.

The one thing time exits do buy is drawdown — 10d and 20d cut max drawdown in
**5 of 6** combinations. That is the same monotone trade §5.19 already
documented for the core hybrid: you can buy drawdown protection with return, at
roughly a fixed exchange rate, anywhere on the curve. It is not new and it is
not free.

### 2.3 Why the hypothesis was wrong — the part worth remembering

The reasoning was: *the signal is dead by 120 bars, therefore holding past 120
bars is not expressing the signal, therefore exit.*

The first two clauses are true. The third does not follow.

> **"The signal has expired" is not the same claim as "the position has
> negative expected value."**

After the dip edge decays, what remains is beta — and beta on this universe was
strongly positive. Exiting on a clock converts an asset with positive expected
return into cash with none. The exposure column shows the mechanism directly:
average exposure falls from **96–99% to 44–66%** at short holds, and
`01_STRATEGY_REVIEW.md` §5.5 already established that returns on this system scale
monotonically with exposure.

So the trail is not doing what it was assumed to be doing. **The trail's job is
not to harvest the dip signal — it is to stay invested until something actually
goes wrong.** That is why tightening it fails (§5.13a), and why clocking it
fails here. Both interventions do the same thing: reduce time in the market.

---

## 3. Lever 2 — conditional sizing

### 3.1 The hypothesis

Every lot is currently a flat 20% of equity. `02_OVERREACTION_STUDY.md` §7 showed
that *filtering* on the event tags destroys the sample — the triple screen cut
17,235 events to 786 and lost significance entirely.

**Weighting does not have that problem.** Every event is still taken; the
better-conditioned ones just get more capital. So: fit a model of forward
excess return on ex-ante tags, and size proportional to predicted edge.

**Protocol.** OLS, standardised features, no interactions, no regularisation
tuning — deliberately the simplest thing that could work. Fit on the first half
of the history, test on the second, then **reverse the split**. Nine features,
all observable on the event bar, none derived from the name's own realised
performance (the §5.7 selection-bias trap):

`z`, `idio_z`, `vol_ratio`, `gap_atr`, `breadth`, `days_since_earnings`
(capped at 90), `rvol20`, `log_dollar_vol`, `dist_52w`.

### 3.2 The raw result looked good

| Horizon | Split | Equal weight | Edge weight | Improvement | t |
|---|---|---|---|---|---|
| 20d | fit 1st → test 2nd | +0.33pp | +0.54pp | **+0.21pp** | 1.37 |
| 20d | fit 2nd → test 1st | +1.17pp | +1.39pp | **+0.22pp** | 3.96 |
| 60d | fit 1st → test 2nd | +0.78pp | +0.95pp | +0.17pp | 0.62 |
| 60d | fit 2nd → test 1st | +2.75pp | +2.97pp | **+0.22pp** | 3.12 |

Consistent in both directions and both horizons, at roughly +0.2pp per trade —
which, against a base edge of +0.34pp, would be a ~60% improvement.

Out-of-sample quintiles of predicted edge sorted, too:

| Split | Q1 | Q5 | Spread |
|---|---|---|---|
| 20d, fit 1st | −0.06pp | +1.33pp | +1.39pp |
| 20d, fit 2nd | +0.26pp | +3.25pp | +2.99pp |
| 60d, fit 1st | −0.18pp | +1.54pp | +1.72pp |
| 60d, fit 2nd | +1.66pp | +5.86pp | +4.20pp |

### 3.3 The control that kills it

**`rvol20` — the name's own trailing volatility — carried the largest
coefficient in every single fit.** That is a red flag, because "put more money
in the jumpy names" is not a prediction, it is leverage.

Three variants, same protocol (`studies/run_optimisation_control.py`):

- **full** — all nine features
- **vol_only** — `rvol20` alone
- **no_vol** — the full set *minus* `rvol20` and `log_dollar_vol` (a size /
  liquidity proxy that correlates with volatility, so leaving it in would
  smuggle the tilt back)

| Horizon | full | vol_only | no_vol |
|---|---|---|---|
| **20d** | +0.216pp | **+0.419pp** *(194% of full)* | +0.229pp (worst t **1.51**) |
| **60d** | +0.195pp | **+0.847pp** *(436% of full)* | +0.130pp (worst t **0.38**) |

**A single volatility feature beats the whole nine-feature model, by 2× at 20
days and 4× at 60.** Eight of the nine features are not adding prediction —
they are diluting a volatility tilt.

And the tilt is large. The book the model builds, versus equal weight:

| Variant | Trailing vol tilt | Beta tilt |
|---|---|---|
| full | **+17.8%** | +8.7% |
| no_vol | +13.4% | +7.5% |
| vol_only | **+36.9%** | **+16.5%** |

### 3.4 Verdict

**This is `01_STRATEGY_REVIEW.md` §5.5 again, wearing a regression.** That section
established that returns on this system scale monotonically with position size
at roughly constant drawdown, because the driver is exposure rather than signal.
A "predicted edge" model whose dominant term is trailing volatility, producing a
book with 17–37% more volatility and 8–16% more beta, is that same finding
rediscovered.

After neutralising volatility and size, the residual conditioning effect is
**+0.23pp at 20 days (worst t = 1.51)** and **+0.13pp at 60 days (worst t =
0.38)**. Not established. Not actionable.

> **If you want the volatility tilt, take it explicitly as leverage and judge it
> on risk-adjusted terms.** Do not take it dressed as a model — that way you get
> the risk without knowing you chose it.

Note also that `no_vol` still shows a **+13.4%** volatility tilt. `gap_atr` and
`z` are themselves volatility-correlated, so a naive "just drop rvol20" fix does
not produce a genuinely vol-neutral book.

---

## 4. What this leaves

**Confirmed by elimination, across three independent studies:** the return of
this system is exposure to a high-beta universe. Every attempt to improve it by
being *cleverer about when to be in* has now failed —

| Intervention | Result | Source |
|---|---|---|
| Re-optimise entry / trail parameters | −11.8pp vs freezing | §5.17 |
| Tighten the trail | Worse at every setting | §5.13a |
| Momentum-gate the universe | Much worse in-sample | §5.13c |
| 200-SMA regime filter | CAGR cut by two thirds | §5.9 |
| Permanent core + dip lots | Monotonically worse | §5.19 |
| Partial scale-outs / min-gain filters | Worse at every setting | §5.28 |
| Stack event-tag filters | Loses significance entirely | Overreaction §7 |
| **Fixed-bar time exit** | **Worse at every setting** | **§2 here** |
| **Model-predicted sizing** | **A volatility tilt** | **§3 here** |

The three things that *did* survive testing, in order of how well evidenced
they are:

1. **Dip-timing new money** — never selling. `01_STRATEGY_REVIEW.md` §5.22.
2. **The entry signal itself** — beats 200/200 random draws, worth
   +0.3 to +0.4pp per trade, dead by 120 bars. `02_OVERREACTION_STUDY.md` §2.
3. **Excluding dips within 20 days of earnings** — +0.80pp at 20 days,
   t = 2.35, stable across both halves. `02_OVERREACTION_STUDY.md` §4.

All three are about **entry**. Nothing about exits, sizing, or filtering has
ever improved this system in a way that survived a control.

---

## 5. Still untested

Recorded so it is clear what this document does *not* close:

- **Cross-sectional ranking.** Taking the *best available* dip each day from a
  ranked list, rather than every dip clearing an absolute `Z < −1.2` bar. This
  is a different mechanism from both levers above and was not tested here.
- **Explicit volatility targeting** as a risk decision rather than a return
  model. §5.13b found vol-target sizing marginally positive (Sharpe 1.78 vs
  1.71); §3 above says any "edge model" collapses into this, so it deserves to
  be evaluated on its own terms.
- **Non-linear conditioning.** The model here is deliberately linear. A tree
  model might find interactions — but note that §3.3's failure is not a
  functional-form problem, it is that one feature dominates and that feature is
  risk.

---

## 6. Reproducing

```bash
python studies/run_optimisation_study.py    # ~4 min -> studies/results_optimisation/
python studies/run_optimisation_control.py  # ~2 min -> 3_risk_tilt_control.csv
python tests/test_backtest_engine.py        # 27 checks, all pass after the engine change
```

| Section | File |
|---|---|
| §2.2 Time-exit sweep | `1_time_exit_sweep.csv` |
| §2.2 Time-exit verdict | `1b_time_exit_verdict.csv` |
| §3.2 Fitted coefficients | `2_coefficients_20d.csv`, `2_coefficients_60d.csv` |
| §3.2 OOS quintiles | `2b_oos_quintiles_20d.csv`, `2b_oos_quintiles_60d.csv` |
| §3.2 OOS portfolio | `2c_oos_portfolio_20d.csv`, `2c_oos_portfolio_60d.csv` |
| §3.3 Risk-tilt control | `3_risk_tilt_control.csv` |

---

*Not investment advice. Past performance is not indicative of future results.*
