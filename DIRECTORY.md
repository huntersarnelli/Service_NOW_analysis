# Directory — where everything lives

A map of the repository. If you are looking for something specific, start here.

```
.
├── BRIEFING.md           ← CATCH-UP FILE. Self-contained; feed this to an AI.
├── appV2.py              ← THE LIVE APP. Start here.
├── app.py                   obsolete — kept for the portfolio tracker only
├── README.md                quickstart + what the strategy is
├── DIRECTORY.md             this file
│
├── docs/                    all research, in the order it was written
├── data/                    live app modules
├── ui/                      app.py tab renderers
├── studies/                 backtest engines, study runners, results
└── tests/                   offline correctness tests
```

---

## Start here, depending on what you want

| I want to… | Go to |
|---|---|
| **Catch up on the whole project** | **`BRIEFING.md`** — one self-contained file |
| **Hand this to an AI assistant** | **`BRIEFING.md`** — written for exactly that |
| **Run the thing** | `streamlit run appV2.py` |
| Understand what the strategy is and why | `README.md`, then `docs/02_OVERREACTION_STUDY.md` |
| **Propose an improvement** | **`docs/DEAD_ENDS.md` first** — eleven ideas have already been tested and killed |
| See the rules with their evidence | `data/screen.py` docstring, or the Evidence tab in `appV2.py` |
| Check a number I read somewhere | `studies/results/` — every figure traces to a CSV |
| Re-run a study | `python studies/run_<name>.py` |
| Add a position | `app.py` → Portfolio tab (`appV2.py` reads the same store) |

---

## `docs/` — the research, chronologically

Read them in order; each one answers a question the previous one raised.

| File | Question it settles |
|---|---|
| `01_STRATEGY_REVIEW.md` | Do the original Method A / Method B claims reproduce, and is there an edge? Eleven sections on the 3-name universe. **The longest and most important document.** |
| `02_OVERREACTION_STUDY.md` | Does the *cause* of a dip predict its recovery? 17,235 events, 124 names, 2015–2026. Establishes the entry signal's true size (+0.3–0.4pp) and its **120-bar expiry**. |
| `03_OPTIMISATION_STUDY.md` | Can a time exit or a sizing model improve it? **No, and no.** Register of closed questions. |
| `04_PORTFOLIO_STUDY.md` | Should different names be sized differently? And how many *independent bets* is this book really making? (Answer: 30 tech names = 4.6.) |
| **`DEAD_ENDS.md`** | **Everything that was tried and failed, and every file deleted, with recovery instructions.** Read before proposing anything. |
| `legacy_Aggressive_Dip_Accumulation_Strategy.md` | The original Method B strategy document. Historical — its performance claims were reproduced but its conclusions do not survive §5.14. |

---

## `data/` — live app modules

| File | Purpose | Used by |
|---|---|---|
| **`screen.py`** | **The evidence-backed dip screen.** Every threshold traces to a measured result; the docstring carries the provenance table. | `appV2.py` |
| **`advisor.py`** | Optional LLM advisory layer. Advisory only — never gates a signal, never backtested. | `appV2.py` |
| `market.py` | Batched OHLCV download, indicators, live levels | both apps |
| `portfolio.py` | Lot model + pluggable storage (`portfolio_data/lots.json`) | `app.py` |
| `holdings.py` | Simple portfolio: ticker, shares, average price (`portfolio_data/holdings.json`); imports old lots | `appV2.py` |
| `watchlists.py` | Your named ticker groups (`portfolio_data/watchlists.json`). Screened, never counted in breadth | `appV2.py` |
| `market_pulse.py` | Sector/theme funds vs SPY over 1–12 months. **Information only — not a tested signal.** | `appV2.py` |
| `signals.py` | Plain-English status: 🟢 Buy zone / 🟠 Your call / 👀 Close to a dip, with reasons and base rates | `appV2.py` |
| `news.py` | Headlines for your-call stocks (Alpha Vantage with sentiment, else Yahoo). **Never placeholders.** | `appV2.py` |
| `journal.py` | Your Buy/Pass decisions on your-call stocks (`portfolio_data/journal.json`) | `appV2.py` |
| `scoreboard.py` | Scores your calls + auto-logged buy-zone signals vs QQQ at 20/60 days | `appV2.py` |
| `insider_feed.py` | Live SEC Form 4 scan with the H10 rules (insider-trading repo). **Paper trading only.** | `appV2.py` |
| `paper_trades.py` | Insider paper-trade log; fills same-day / next-day outcomes vs SPY and QQQ | `appV2.py` |
| `sec_client.py` | Polite SEC requests (User-Agent, 5 req/s, retries) | `insider_feed.py` |
| `strategies.py` | Method A / Method B rule sets + open-lot evaluation | `app.py` |
| `media_earnings.py` | News sentiment + earnings context. **Informational only — never gates a signal.** | `app.py` |

## `ui/` — `app.py` tab renderers

`portfolio_tab.py` (positions, entry markers, trailing-stop path) and
`media_earnings_tab.py` for `app.py`. For `appV2.py` (five tabs): `desk_today.py`,
`desk_stocks.py` (watchlists + screen + your-call panel + decision log),
`desk_portfolio.py`, `desk_track.py` (Track record), `desk_market.py` (+ `desk_pulse.py`), `desk_howto.py`,
and `desk_common.py` helpers.

---

## `studies/` — engines, runners, results

**Two engines:**

| File | What it is |
|---|---|
| `dip_backtest.py` | Portfolio-level backtest engine. Lots compete for one cash balance; position size is a fraction of growing equity. Every modelling assumption is a `BacktestConfig` parameter. |
| `overreaction_lib.py` | Event-study harness: the 124-name universe, tagging, cohort tables, and month-clustered t-statistics. |

**Thirteen runners**, each writing to its own results folder:

| Runner | Writes to | Covers |
|---|---|---|
| `run_dip_study.py` | `results/01_dip_study/` | Claim reproduction, parameter surface, selection bias, walk-forward |
| `run_improvements.py` | `results/02_improvements/` | Null test, trail ratchet, vol-target, momentum universe |
| `run_regime_study.py` | `results/03_regime/` | 2020–2026 history, the 2022 bear, bootstrap, core hybrid |
| `run_recommendation.py` | `results/04_recommendation/` | Window sensitivity, DCA vs dip-timed deployment |
| `run_allocation.py` | `results/05_allocation/` | How much of a portfolio this should be |
| `run_a_vs_b.py` | `results/06_a_vs_b/` | A vs B head-to-head, entry/exit decomposition |
| `run_profit_take.py` | `results/07_profit_take/` | Profit-take sweep, buy-back diagnostic, Z decomposition |
| `run_overreaction_study.py` | `results/08_overreaction/` | News-vs-no-news cohorts |
| `run_overreaction_control.py` | `results/08_overreaction/` | Random-entry null control — **the beta stripper** |
| `run_optimisation_study.py` | `results/09_optimisation/` | Time exit + conditional sizing |
| `run_optimisation_control.py` | `results/09_optimisation/` | The risk-tilt control that killed the sizing model |
| `run_portfolio_study.py` | `results/10_portfolio/` | Sizing regimes, name caps, vol tiering, effective bets |
| `run_best_dip_study.py` | `results/11_best_dip/` | The screens, and the screens as *deployment* rules |

**`studies/results/`** — folders numbered in the order the studies were run.
Every number in `docs/` traces to a CSV here.

> **Study results are NOT in git** — they are regenerated, not stored. Every
> number in `docs/` cites a file here, but those files live only on your
> machine. To verify a claim, re-run the study that produced it (the table
> above maps each runner to its output folder). Full regeneration is ~40 min.

---

## `tests/`

```bash
python tests/test_backtest_engine.py           # 27 checks on the engine
python tests/test_strategies_and_portfolio.py  # 28 checks on rules + storage
python tests/test_desk_build1.py               # 19 checks: watchlists, holdings, pulse, breadth
python tests/test_desk_signals.py              # 22 checks: statuses, headlines, journal
python tests/test_desk_build2.py               # 25 checks: SEC feed/Form 4, H10 rules, paper trades, scoreboard
```

Synthetic fixtures with known answers. **No network needed.** The engine tests
cover exposure caps, cash solvency, trailing-stop geometry, pyramiding modes and
determinism; the rules tests cover open-lot evaluation and storage round-trips.

---

## Not in git

- `portfolio_data/` — your positions. Personal data, gitignored.
- `.streamlit/secrets.toml` — API keys. Copy `secrets.toml.example` to create it.
- `studies/.cache_overreaction/` — parquet download cache. Safe to delete; the
  studies re-download.

---

## What used to be here

`aggressive_dip_dashboard.py`, `production ready strategy.ipynb`, `testing/`,
and the media-sentiment backtest were removed. **Each is documented in
`docs/DEAD_ENDS.md` with the reason and a git command to recover it.** They are
preserved in history at commit `820aeb6`.
