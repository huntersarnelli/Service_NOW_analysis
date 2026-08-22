# Tactical Trading System — Live Dashboard

One Streamlit app, two strategies, plus a portfolio tracker that tells you where
your stops actually are.

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens at `http://localhost:8501`. Pick the strategy in the sidebar.

## The two strategies

| | **Dual-Mode Tactical** | **Aggressive Dip Accumulation** |
|---|---|---|
| Universe | Momentum: NVDA, META, NET<br>Quality: NOW, MSFT, GOOGL, PANW, CRWD, DDOG, CRM | META, NVDA, NET, DDOG |
| Entry | Z(20) < −1.5 | Z(20) < −1.2 |
| Trailing stop | Close − 2×ATR, raise-only (ATR re-read daily) | Highest close since entry − 4×ATR (**ATR frozen at entry**) |
| Exit | Trail hit **or** Z > 0 | Trail hit only — no mean-reversion exit |
| Sizing | 1%-of-capital risk reference | 25% of equity, 35% within 10d after earnings |
| Optional filter | Close > 50-SMA, Quality bucket only (off by default) | none |

Buy trigger for both = `SMA + (Z_entry × std)` — the price at which Z equals the
entry threshold. Every parameter is adjustable in the sidebar.

**The difference that matters:** Tactical caps every winner at the mean while
risking 2×ATR, which is a sub-1:1 reward/risk. Dip removes that cap and lets the
trend pay. See `Aggressive_Dip_Accumulation_Strategy.md` §3.5 — 95% of tactical
exits went on to trade higher, median +53% left behind.

### Read the evidence before trading either

Three review documents, in the order they were written:

| Document | What it settles |
|---|---|
| **[`STRATEGY_REVIEW.md`](STRATEGY_REVIEW.md)** | Do the documented claims reproduce, and is there an edge? Eleven sections of results on the 3-name universe. |
| **[`OVERREACTION_STUDY.md`](OVERREACTION_STUDY.md)** | Does the *cause* of a dip predict its recovery? 17,235 events, 124 names, 2015–2026. Establishes the entry signal's true size (+0.3–0.4pp) and its **120-bar expiry**. |
| **[`OPTIMISATION_STUDY.md`](OPTIMISATION_STUDY.md)** | **Register of closed questions.** Time exits and model-based sizing, both tested with out-of-sample controls, both rejected. Read this before proposing an improvement. |
| **[`PORTFOLIO_STUDY.md`](PORTFOLIO_STUDY.md)** | Should different names be sized differently? Risk parity, per-name caps, volatility tiering — and the measurement that explains the rest: **30 tech names are only 4.6 independent bets.** |

**[`STRATEGY_REVIEW.md`](STRATEGY_REVIEW.md) is the document to read first.** It is a
self-contained review packet: exact trade mechanics for both systems, full backtest
methodology, and eleven sections of results. Headline findings:

- The Aggressive Dip claims **do reproduce** — $870,078 vs the documented $931,543,
  with max drawdown (−31.3% vs −31.1%) and average exposure (95.9% vs 95.4%) matching
  almost exactly.
- **But the documented window starts 2023-01-03 — the week after META fell 64.5%,
  NET 64.2% and NVDA 51.4% in 2022.** Extending the same rules back to 2020 turns
  a +3.0pp edge into **−6.7pp**, and the strategy beat buy-and-hold in only
  **3 of 7 calendar years** (median −14.3pp).
- A block bootstrap puts the 95% interval on excess CAGR at **[−37.9, +23.2]pp** —
  the sign of the edge is unresolved.
- Rolling walk-forward over 8 windows: periodically re-optimising the parameters is
  **11.8pp worse** than freezing them. There is no stable optimum.
- **However** — 2022 was a rate-hiking bear, not a pandemic year. On the honest
  middle window (**2022+**, post-pandemic but including the bear) the strategy
  **wins on every metric**: +9.4pp CAGR, Sharpe 0.97 vs 0.82, Calmar 0.70 vs 0.48,
  max drawdown −58.2% vs −64.8%. That is the strongest evidence in the study.
- Neither result is statistically established. Two independent methods agree:
  bootstrap over 2020-26 gives [−37.9, +23.2]pp; annual t-test over 2022+ gives
  [−28.5, +45.8]pp with **t = 0.46**.
- **Most robust finding of all:** using the dip signal to deploy *new money*
  (never to exit) beat scheduled investing in 5 of 9 combinations — **+20.2%** on
  META/NVDA/NET since 2022 — and works on stock baskets but not on an index.
- **A high-Z profit take is the one modification that survived every test.**
  Selling at **Z > +2.0** raised Sharpe on all three windows (1.10→1.19, 0.97→1.05,
  1.71→2.01) while cutting average exposure from 98% to 65%. On the full 2020+
  history a Z > 2.5 take turns a −6.7pp deficit into **+1.3pp** over buy-and-hold.
  Use full exits — partial scale-outs and minimum-gain filters are worse.
- But it is **risk reduction, not alpha**: across 30 names it improved CAGR on
  12/30 and cut drawdown on **28/30** (−55.6% → −47.0% mean).
- **Why "sell high, buy back lower" only half works:** Z reverts mostly because
  the 20-SMA rises (+12.6%), not because price falls (+2.9% mean, −1.3% median).
  You get a cheaper print 80–86% of the time, but the discount is small and the
  window closes — 120 days out the price is higher 58% of the time, up +17.7%.
- **A vs B:** a 2×2 on entry threshold × exit rule shows the **exit matters ~23×
  more than the entry** (21.3pp vs 0.9pp spread). B beats A on CAGR and Sharpe on
  every window — but A is only ~30% invested, has **half the drawdown** (−28.8% vs
  −55.6% across 30 names), was **24 points better than B** through the 2022 bear,
  and once its idle cash is credited it ties or beats B on 2 of 3 windows. A is a
  defensive sleeve, not a dominated strategy.
- But it beats buy-and-hold of the same three names by only **+3.0pp CAGR, with a
  lower Sharpe** (1.707 vs 1.753).
- Run on 29 large caps instead of the three it was built on, it beats buy-and-hold
  on **10 of 29**, median excess CAGR **−2.2pp**.
- Walk-forward (fit 2023-24, test 2025-26): buy-and-hold wins out-of-sample on both
  return (35.5% vs 26.5%) and Sharpe (0.97 vs 0.80).
- Returns scale **monotonically** with position size at constant drawdown — evidence
  that the driver is exposure, not signal.
- **10 of 105 lots produced 83% of all profit.** NET alone made 65% of it; META lost money.
- But a null test *does* vindicate the entry: against random entries at the same
  frequency, the Z signal beats **88% of 200 random draws** and is worth ~+10.8pp CAGR.
  Dip-buying works; the calibration of the dip depth does not.
- Improvement attempts: tightening the trail is worse at every setting (the wide trail
  is correct), momentum-ranking the universe fails badly in-sample, vol-targeted sizing
  helps marginally (Sharpe 1.78 vs 1.71).

Tactical fares worse: `testing/test2.ipynb` shows +18.1% CAGR on NOW from 2020 and
**−12.2%** on the same rules from 2025; `testing/test3.ipynb` shows it beating
buy-and-hold on only 8 of 17 names since 2025.

## Tabs

1. **Overview** — live scanner for the selected strategy, BUY / NEAR / WATCH, deep dive
2. **Portfolio** — your real lots and where the rules say to get out (below)
3. **Bucket / Stock Detail** — per-bucket tables and per-name cards
4. **Earnings** *(Dip only)* — calendar and the post-earnings boost window
5. **Media & Earnings** — news sentiment, informational only, never gates a signal
6. **Filter Compare** *(Tactical only)* — entry eligibility with vs without the trend filter
7. **Rules** — the active rule set, written out with formulas

## Portfolio tracker

Add one row per purchase — ticker, shares, entry price, entry date, and which
rule set governs that lot. The app then walks the bars forward from your entry
and reports what the rules actually did:

- **Trailing stop as a path**, not a flat level — you see it ratchet under the price
- **Entry and exit markers** on the chart, with your breakeven line
- **Distance to stop** in $ and %, per share and per lot — the number you act on
- **MFE / MAE** — how far it ran in your favour, and how much you gave back
- **R-multiple** against the initial stop
- Weighted-average blending when you pyramid into the same name
- Concentration warning, because these universes are largely one AI/megacap bet

Lots are stored per purchase rather than per ticker because the Dip rules allow
pyramiding and each lot carries its own stop anchored to the highest close since
*that* lot opened.

### Where positions are stored

`data/portfolio.py` puts storage behind `load()` / `save()` so the backend can
change without touching the UI. Default is `portfolio_data/lots.json` (gitignored).

> **Before deploying:** Streamlit Community Cloud has an ephemeral filesystem —
> files written at runtime are **not** guaranteed to survive a reboot. Add a
> `[connections.gsheets]` block to `secrets.toml` and implement
> `data/portfolio_sheets.SheetsLotStore`; `get_store()` picks it up automatically.

## Layout

```
app.py                     entry point, sidebar, strategy selector, tabs
data/market.py             batched OHLCV, indicators, live levels / signals
data/strategies.py         the two rule sets + open-lot evaluation engine
data/portfolio.py          lot model + pluggable storage
data/media_earnings.py     informational media + earnings
ui/portfolio_tab.py        portfolio UI, entry markers, trailing-stop path
ui/media_earnings_tab.py   Media & Earnings tab
studies/dip_backtest.py    Strategy B portfolio backtest engine (lots, pyramiding)
studies/run_dip_study.py   the main study — writes studies/results/
studies/run_improvements.py  null test + improvement attempts
studies/run_regime_study.py  2020-2026 history, bear market, bootstrap, walk-forward
studies/run_recommendation.py  window sensitivity, DCA vs dip-timed deployment
studies/run_allocation.py    how much of a portfolio this should be
studies/run_a_vs_b.py        A vs B head-to-head, entry/exit decomposition
studies/run_profit_take.py   profit-take sweep, buy-back diagnostic, Z decomposition
studies/overreaction_lib.py  event-study harness: tagging, cohorts, clustered t-stats
studies/run_overreaction_study.py  news-vs-no-news cohorts -> results_overreaction/
studies/run_overreaction_control.py  random-entry null control (the beta stripper)
studies/run_optimisation_study.py  time exit + conditional sizing -> results_optimisation/
studies/run_optimisation_control.py  the risk-tilt control that rejected the sizing model
studies/run_portfolio_study.py  sizing regimes, name caps, vol tiering, effective bets
studies/results/           CSVs + summary.json backing every cited number
studies/media_backtest_lib.py  research harness for the media-sentiment study
tests/                     offline correctness tests (no network needed)
testing/                   the notebooks the strategies came out of
```

## Tests

```bash
python tests/test_backtest_engine.py          # 27 checks on the backtest engine
python tests/test_strategies_and_portfolio.py # 28 checks on rules + storage
```

Both run on synthetic fixtures with known answers and need no network. The engine
tests cover exposure caps, cash solvency, trailing-stop geometry, pyramiding modes
and determinism; the rules tests cover open-lot evaluation, the history-window
sizing fix, and portfolio storage round-trips.

## Backtesting

```bash
python studies/run_dip_study.py     # ~3 min  -> studies/results/
python studies/run_improvements.py  # ~4 min  -> studies/results_improvements/
python studies/run_regime_study.py  # ~5 min  -> studies/results_regime/
python studies/run_recommendation.py # ~4 min -> studies/results_recommendation/
python studies/run_allocation.py    # ~1 min  -> studies/results_allocation/
python studies/run_a_vs_b.py        # ~4 min  -> studies/results_a_vs_b/
python studies/run_profit_take.py   # ~6 min  -> studies/results_profit_take/
python studies/run_overreaction_study.py   # ~3 min -> studies/results_overreaction/
python studies/run_overreaction_control.py # ~4 min -> null control
python studies/run_optimisation_study.py   # ~4 min -> studies/results_optimisation/
python studies/run_optimisation_control.py # ~2 min -> risk-tilt control
python studies/run_portfolio_study.py      # ~15 min -> studies/results_portfolio/
```

Reproduces the documented claims, then stress-tests them: parameter surface,
position-size sweep, universe variants, a selection-bias test across 29 large caps,
walk-forward, the regime filter the strategy doc recommends, and commission /
start-date robustness. The regime study extends the history back through the 2022
bear market, adds a rolling walk-forward and a block bootstrap, and tests a
core-plus-dip hybrid. Every number in `STRATEGY_REVIEW.md` §5 is traceable to a
CSV in `studies/results/`.

The engine (`studies/dip_backtest.py`) is portfolio-level — lots compete for one
cash balance and position size is a fraction of a growing equity figure, which the
single-name notebooks in `testing/` cannot express. Every modelling assumption is a
constructor parameter on `BacktestConfig`.

`aggressive_dip_dashboard.py` is superseded by `app.py` and kept for reference only.

## Notes

- Prices cached ~120s; **Refresh data now** forces a reload. Auto-refresh reruns
  only the scanner block, so your tab and chart zoom survive.
- All symbols download in **one** batched yfinance request. This matters on a
  cloud host, where Yahoo throttles datacenter IPs far harder than home IPs.
- Requirements are pinned — yfinance ships breaking changes often, and an
  unpinned deploy can break without a commit on your side.
- Optional Alpha Vantage key for live media: copy `.streamlit/secrets.toml.example`
  to `secrets.toml`. Without it, media falls back to placeholders; earnings still work.
- No broker connection. This app never places an order.
- Research / educational use only — not investment advice.
