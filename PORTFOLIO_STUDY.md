# Portfolio Construction Study — should different names be treated differently?

**Prepared:** 22 August 2026
**Code:** `studies/run_portfolio_study.py`
**Results:** `studies/results_portfolio/`
**Engine change:** `max_ticker_weight` and `alloc_by_ticker` added to `studies/dip_backtest.py`

---

## 0. Register of closed questions

| Question | Answer | Where |
|---|---|---|
| Should lots be sized by equal risk instead of equal dollars? | **Only if the universe has risk dispersion.** Nothing on all-tech; real on a mixed basket | §2 |
| Should cumulative exposure to one ticker be capped? | **No.** Sharpe is flat from 5% to no cap; capping only costs return | §3 |
| Should high-volatility names get a smaller allocation? | **It is a dial, not an improvement.** De-risking cuts return and drawdown together | §4 |
| Is there a free-lunch allocation rule anywhere? | **No.** Every variant that cut drawdown cut CAGR | §5 |
| How many independent bets is this book actually making? | **tech30 = 4.6. The trio = 2.1.** This is the binding constraint | §5 |
| Does widening the universe beyond tech help? | **Yes — more than any sizing rule tested** | §1 |

---

## 1. The finding that dominates everything else

Before any sizing rule, compare the two universes **on identical current rules**
(equal-dollar 20% per lot, no caps):

| Window | Universe | CAGR | Max DD | Sharpe | Vol |
|---|---|---|---|---|---|
| 2020+ | tech30 | 27.5% | **−51.2%** | 0.90 | 33.1% |
| 2020+ | **mixed50** | 26.4% | **−30.2%** | **1.10** | 23.9% |
| 2023+ | tech30 | 48.8% | −29.6% | 1.57 | 27.8% |
| 2023+ | **mixed50** | 38.4% | **−21.8%** | **1.77** | 19.5% |

**Twenty-one points less drawdown for one point of CAGR.** No sizing rule tested
anywhere in this repository comes close to that exchange rate.

`mixed50` is the same 30 tech names plus 20 defensives, financials, healthcare
and energy. Nothing clever — just not being a single-sector bet.

---

## 2. Sizing regime — equal dollars vs equal risk

Equal-dollar gives a 60%-vol name the same capital as a 20%-vol name, so the
volatile name dominates the book's risk. Equal-risk (`sizing_mode="vol_target"`)
sizes each lot so it risks the same fraction of equity to its own stop.

**On tech30 — no effect:**

| 2022+ | CAGR | Max DD | Sharpe | Vol |
|---|---|---|---|---|
| Equal-dollar 20% | 15.9% | −50.4% | 0.61 | 33.1% |
| Equal-risk 1%/lot | 13.9% | −45.9% | 0.59 | 29.0% |

**On mixed50 — wins on Sharpe in all three windows:**

| Window | Variant | CAGR | Max DD | Sharpe | Vol |
|---|---|---|---|---|---|
| 2020+ | Equal-dollar | 26.4% | −30.2% | 1.10 | 23.9% |
| 2020+ | Equal-risk 3% | 22.6% | −26.4% | **1.14** | 19.8% |
| **2022+** | Equal-dollar | 13.2% | −40.2% | 0.63 | 24.5% |
| **2022+** | **Equal-risk 1%** | 12.2% | **−29.4%** | **0.77** | **16.8%** |
| 2023+ | Equal-dollar | 38.4% | −21.8% | 1.77 | 19.5% |
| 2023+ | Equal-risk 1% | 28.8% | **−17.1%** | **1.84** | 14.4% |

**Risk parity can only equalise dispersion that exists.** Thirty tech names all
carry similar volatility, so there is nothing to equalise. Add defensives and
the rule has something to work with — 10.8pp off the 2022+ drawdown for 1pp of
CAGR.

### A correction to §5.13b

`STRATEGY_REVIEW.md` §5.13b found vol-targeting at 5% risk *raised* CAGR to
87.4% and read it as the first variant to beat buy-and-hold on Sharpe. The
exposure column here explains it: at 5% risk per lot the rule pushes average
exposure to ~96%, so it is **a leverage tilt, not risk parity**. Sweeping
`risk_frac` from 1% to 5% shows the pattern cleanly — return tracks exposure,
not risk equalisation.

---

## 3. Per-name cap — rejected

Nothing currently stops pyramiding from accumulating an unbounded position in
one ticker. `max_ticker_weight` was added to cap cumulative market value per
name. Swept, mean of three windows:

| Cap | tech30 CAGR | tech30 DD | tech30 Sharpe | mixed50 Sharpe |
|---|---|---|---|---|
| 5% / name | 28.5% | **−41.9%** | 0.98 | 1.16 |
| 10% | 29.5% | −43.4% | 1.00 | 1.16 |
| 15% | 30.1% | −43.5% | 1.02 | 1.16 |
| 25% | 30.8% | −43.7% | 1.03 | 1.17 |
| **no cap (current)** | **30.8%** | −43.7% | **1.03** | **1.17** |

**Sharpe is flat across the entire range and CAGR falls monotonically as the cap
tightens.** The tightest cap buys 1.8pp of drawdown for 2.3pp of CAGR — a worse
exchange rate than simply holding less.

The reason is §5: with only ~4.6 independent bets in a 30-name book, spreading
capital more evenly across those 30 names does not spread it across more *bets*.

---

## 4. Volatility tiering — a dial, not an improvement

Names split into volatility terciles using **only data from before each window
opens**, then given different base allocations.

**tech30, mean of three windows:**

| Scheme | CAGR | Max DD | Sharpe | Vol |
|---|---|---|---|---|
| **Tilt to vol** (low 10 / mid 20 / high 30) | **34.3%** | −46.9% | **1.04** | 34.8% |
| Flat 20% (current) | 30.8% | −43.7% | 1.03 | 31.4% |
| De-risk (low 30 / mid 20 / high 10) | 27.5% | −40.0% | 1.02 | 28.3% |
| De-risk hard (low 35 / mid 20 / high 5) | 25.8% | **−38.7%** | 0.99 | 27.2% |

**mixed50, mean of three windows:**

| Scheme | CAGR | Max DD | Sharpe | Calmar | Vol |
|---|---|---|---|---|---|
| **De-risk** (low 30 / mid 20 / high 10) | 21.1% | **−25.1%** | **1.25** | 0.97 | 17.1% |
| De-risk hard | 18.9% | **−23.7%** | 1.24 | 0.94 | 15.6% |
| Flat 20% (current) | 26.0% | −30.7% | 1.17 | **0.99** | 22.6% |
| Tilt to vol | **30.9%** | −38.5% | 1.12 | 0.95 | 28.8% |

**This is a clean risk/return dial with no free lunch on it.** Tilting toward
volatile names raises CAGR and drawdown together; de-risking lowers both. The
ordering is perfectly monotone in both universes.

Two things worth noting:

- The highest Sharpe anywhere in this study is **mixed50 de-risk at 1.25** — but
  its **Calmar is 0.97 versus flat's 0.99**. Sharpe improves because volatility
  falls; drawdown-adjusted return does not improve at all. The gain is
  vol reduction, not better return per unit of the risk that actually hurts.
- The highest CAGR anywhere is **tech30 tilt-to-vol at 34.3%**, +3.5pp over flat
  with Sharpe essentially unchanged (1.04 vs 1.03). This is the same effect
  `OPTIMISATION_STUDY.md` §3 identified: **it is the exposure lever again**,
  expressed as an allocation tilt rather than as margin. It is leverage without
  a margin account, and it costs 3.1pp of drawdown.

---

## 5. How many independent bets is this book making?

The measure is the participation ratio of the correlation matrix's eigenvalue
spectrum, `(Σλ)² / Σλ²`. It equals *n* when every name is independent and 1 when
every name is the same bet.

| Universe | Names | Avg pairwise corr | **Effective bets** | Corr-equivalent names | PC1 variance |
|---|---|---|---|---|---|
| **trio** (META/NVDA/NET) | 3 | 0.46 | **2.10** | 1.56 | **64.1%** |
| **tech30** | 30 | 0.42 | **4.65** | 2.28 | 44.5% |
| **mixed50** | 50 | 0.27 | **8.47** | 3.56 | 30.9% |

*(2020+ window; 2022+ is nearly identical, 2023+ slightly better for all three.)*

**This is the binding constraint on the entire project, and it explains most of
the negative results in the other studies.**

- The original three-name universe is **2.1 independent bets**, with a single
  principal component driving **64% of all variance**. `STRATEGY_REVIEW.md`
  §7.12 called the concentration risk understated; this quantifies it.
- Thirty tech names is **4.6 bets**, not thirty. Position sizing across thirty
  names that are really 4.6 bets cannot accomplish much — which is exactly what
  §3's flat cap sweep found.
- Adding twenty non-tech names **nearly doubles** the effective bets, 4.65 →
  8.47, and that is where the drawdown improvement in §1 comes from.

**Diversification has to happen at the level of bets, not tickers.** Every
allocation rule tested here operates *within* a fixed set of bets and is
therefore fighting for scraps. Widening the set of bets was worth more than all
of them combined.

---

## 6. Verdict

**Nothing here raises returns except taking more risk.**

| Change | Return | Risk | Verdict |
|---|---|---|---|
| Widen universe beyond tech | −1pp CAGR | **−21pp drawdown** | **Best trade in the study** |
| Equal-risk sizing *(on a mixed universe)* | −1 to −10pp | −4 to −11pp drawdown | Worth it if you want the ride smoother |
| Equal-risk sizing *(on all-tech)* | −2pp | −4pp | Pointless — no dispersion to equalise |
| Per-name cap | −2.3pp | −1.8pp | **Rejected** — bad exchange rate |
| De-risk tiering | −5pp | −5.6pp | A dial. Sharpe up, Calmar flat |
| Tilt-to-vol tiering | **+3.5pp** | +3.1pp drawdown | Leverage without margin |

If the objective is maximum profit, this study says the same thing
`STRATEGY_REVIEW.md` §5.19 said: **every risk-reducing rule costs return, at a
roughly fixed exchange rate, everywhere on the curve.** The only variant that
raised CAGR did so by raising volatility.

If the objective is surviving the ride, **widen the universe first** — it is
worth more than every sizing rule tested here put together — and then apply
equal-risk sizing, which only works once the universe has dispersion to
equalise.

---

## 7. Reproducing

```bash
python studies/run_portfolio_study.py   # ~15 min -> studies/results_portfolio/
python tests/test_backtest_engine.py    # 27 checks, all pass after the engine change
```

| Section | File |
|---|---|
| §1–2 Sizing regime | `1_sizing_regime.csv` |
| §3 Per-name caps | `2_name_caps.csv` |
| §4 Volatility tiering | `3_vol_tiering.csv` |
| §5 Effective bets | `4_effective_bets.csv` |

---

*Not investment advice. Past performance is not indicative of future results.*
