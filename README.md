# Dip Deployment System

A dip-buying system for US large caps, and four studies that spent most of their
effort proving what *doesn't* work.

```bash
pip install -r requirements.txt
streamlit run appV2.py
```

Opens at `http://localhost:8501`.

> **New here — or handing this to an AI?** Read
> **[`BRIEFING.md`](BRIEFING.md)** first. It is one self-contained file with the
> whole project: history, every established number, the graveyard, and what is
> still open. **[`DIRECTORY.md`](DIRECTORY.md)** is the map of where files live.

---

## The strategy, in six lines

1. Hold a wide basket of large caps — **many sectors, not just tech**
2. **Never sell.** No exit rule has ever survived a control here
3. Deploy new money into **dips**, not on a schedule
4. Buy the dip only when it is **not near earnings** and the **market** is
   dragging the name down — not the company's own news
5. Depth doesn't matter. A −2σ dip is not better than a −1.2σ dip
6. Expect **+0.3 to +0.4pp per trade**, gone by 120 bars. Your contribution rate
   matters more than any of this

Every one of those is a measured result, not a preference. The evidence is in
[`docs/`](docs/), and every number traces to a CSV in `studies/results/`.

---

## The two apps

| | **`appV2.py`** — Deployment Desk | `app.py` — legacy dashboard |
|---|---|---|
| Status | **Current** | **Obsolete** |
| Answers | "Deploy this cash today, or wait?" | "Is anything a buy, and where's my stop?" |
| Universe | 124 names, six sectors | 3–10 tech names |
| Sells? | Never | Trailing stops |
| Keep it for | Everything | The Portfolio tab — both apps share one store |

`app.py` still runs and still holds your positions, but its scanner is built on
rules that four studies contradict — including a 35% post-earnings size-up that
levers into the worst cohort ever measured here. It carries a banner saying so.

### `appV2.py` tabs

**Deploy** — the call, plus a market-breadth gauge. **Candidates** — every name
with each gate shown separately, so a near-miss is visible. **Advisor** —
optional LLM read, advisory only, never a gate. **Portfolio** — what you hold and
how many *independent bets* that really is. **Evidence** — every rule with its
number, and the graveyard.

---

## Read the evidence before trading this

**Start with [`docs/DEAD_ENDS.md`](docs/DEAD_ENDS.md)** if you are about to
propose an improvement. Eleven have already been tested and killed.

| Document | Question it settles |
|---|---|
| [`01_STRATEGY_REVIEW.md`](docs/01_STRATEGY_REVIEW.md) | Do the original Method A / B claims reproduce, and is there an edge? Eleven sections. The foundational document. |
| [`02_OVERREACTION_STUDY.md`](docs/02_OVERREACTION_STUDY.md) | Does the *cause* of a dip predict its recovery? 17,235 events, 124 names, 2015–2026. |
| [`03_OPTIMISATION_STUDY.md`](docs/03_OPTIMISATION_STUDY.md) | Can a time exit or a sizing model improve it? No, and no. |
| [`04_PORTFOLIO_STUDY.md`](docs/04_PORTFOLIO_STUDY.md) | Should names be sized differently? And how many independent bets is this book *really* making? |
| [`DEAD_ENDS.md`](docs/DEAD_ENDS.md) | Everything tried that failed, every file deleted, and how to recover it. |

### What survived

- **Dip-timing new money, never selling** — the most robust finding in the
  project. Works on stock baskets, fails on an index.
- **The `Z < −1.2` entry** — beats **200 of 200** random draws at 5, 20 and 60
  bars. Worth **+0.3–0.4pp per trade** and **dead by 120 bars**; everything past
  that is beta.
- **Excluding dips within 20 bars of earnings** — +0.80pp at 20 days, t = 2.35,
  stable across both sample halves.
- **Widening past one sector** — the single biggest effect found anywhere: same
  rules, **−30% drawdown instead of −51%**, on a better Sharpe.

### What didn't

Parameter re-optimisation (−11.8pp vs freezing), tighter trails, momentum gating,
200-SMA regime filters (−two thirds of CAGR), core-plus-dip hybrids, partial
scale-outs, volume as a news proxy, stacked filters, fixed-bar time exits,
model-predicted sizing, per-name caps. All eleven are in `DEAD_ENDS.md` with the
number that killed them.

### The finding that explains the rest

**Thirty tech names are only 4.6 independent bets.** The original META/NVDA/NET
trio is **2.1**, with one factor driving 64% of all variance. That is why no
position-sizing rule ever moved the needle — you cannot diversify across tickers
that are the same bet. Diversification has to happen at the level of *bets*.

---

## Be clear-eyed about size

The entry edge is roughly **+0.3–0.4pp per trade** and it **expires**. On
$10,000, the timing edge is worth a few hundred dollars a year while the stocks
themselves swing thousands. This makes a concentrated equity bet slightly more
efficient. It does not make it safe, and it is not a return engine.

---

## Tests

```bash
python tests/test_backtest_engine.py           # 27 checks
python tests/test_strategies_and_portfolio.py  # 28 checks
```

Synthetic fixtures, known answers, no network. Covers exposure caps, cash
solvency, trailing-stop geometry, pyramiding modes, determinism, open-lot
evaluation and storage round-trips.

## Re-running the studies

```bash
python studies/run_overreaction_study.py    # ~3 min
python studies/run_overreaction_control.py  # ~4 min  the null control
python studies/run_best_dip_study.py        # ~6 min  the screens
python studies/run_portfolio_study.py       # ~15 min
```

Full list in [`DIRECTORY.md`](DIRECTORY.md). Outputs land in
`studies/results/<nn>_<name>/`, which is **gitignored** — results are
regenerated, not stored. Every number in `docs/` cites a file there, so
verifying a claim means re-running the study that produced it.

## Notes

- All symbols download in **one** batched yfinance request. This matters on a
  cloud host, where Yahoo throttles datacenter IPs far harder than home IPs.
- Requirements are pinned. yfinance ships breaking changes often, and an
  unpinned deploy can break without a commit on your side.
- The Advisor tab needs `pip install anthropic` and an API key. Without either,
  the tab explains what's missing rather than erroring.
- Positions live in `portfolio_data/` and are gitignored. On Streamlit Community
  Cloud the filesystem is ephemeral — implement `data/portfolio_sheets` before
  relying on it there.
- **No broker connection. This app never places an order.**

---

*Research and educational use only. Not investment advice. Past performance is
not indicative of future results.*
