# Aggressive Dip Accumulation Strategy
### META • NVDA • NET  
**Version 1.0 — August 2026**

---

## 1. Strategy Overview

This is a concentrated, long-only, volatility-aware trend-following system that uses short-term mean-reversion signals purely as **entry and add triggers**.  

The core philosophy is simple:

> In strong secular bull markets, the highest-probability way to stay invested in the leaders is to buy their temporary pullbacks aggressively and then refuse to sell them easily.

The system deliberately keeps a very high percentage of capital in the market at all times while still using volatility (measured by Z-score) to time entries and adds.

**Final Rules (Optimized)**

| Component              | Rule                                      |
|------------------------|-------------------------------------------|
| **Universe**           | META, NVDA, NET                           |
| **Entry / Add Signal** | 20-period Z-score < –1.2                  |
| **Position Sizing**    | 20% of current portfolio equity per lot   |
| **Pyramiding**         | Allowed (multiple lots in the same name)  |
| **Maximum Exposure**   | 100%                                      |
| **Exit**               | Trailing stop = Highest close since lot entry − **4.0 × ATR(14)** |
| **Mean-reversion Exit**| None (deliberately removed)               |
| **Trend Filter**       | None (price can be below intermediate moving averages) |

---

## 2. Performance Summary  
**Period: 3 January 2023 – 31 July 2026**  
**Starting Capital: $100,000**

| Metric                    | Aggressive Dip Strategy | Equal-Weight Buy & Hold |
|---------------------------|-------------------------|-------------------------|
| Final Equity              | **$931,543**           | $834,732               |
| Total Return              | **+831.6%**            | +734.7%                |
| CAGR                      | **86.8%**              | 81.1%                  |
| Max Drawdown              | –31.1%                 | –34.1%                 |
| Sharpe Ratio (rf = 0)     | **1.83**               | 1.77                   |
| Average % Invested        | 95.4%                  | 100%                   |
| % of Days Fully Invested  | 87.7%                  | 100%                   |
| Number of Lots            | 76                     | —                      |
| Win Rate                  | 57%                    | —                      |
| Average Holding Period    | 90 days                | —                      |

The strategy outperformed a pure buy-and-hold of the same three names on total return, CAGR, and risk-adjusted return while producing a slightly shallower maximum drawdown.

---

## 3. Why This Strategy Works

### 3.1 The Nature of the Universe

META, NVDA, and NET (during 2023–2026) shared several critical characteristics:

- Extremely strong multi-year secular uptrends driven by structural demand (AI infrastructure, digital advertising recovery, edge/cloud networking).
- High but “healthy” volatility — frequent sharp pullbacks that did **not** turn into new primary downtrends.
- Persistent institutional sponsorship. Large buyers consistently appeared on weakness.
- Exceptionally high mean-reversion success rate on short-term Z-score dips.

When we measured historical recovery rates (2023 onward):

- META: ~98% of Z < –1.5 dips recovered to the 20-SMA within 20 trading days  
- NVDA: ~100%  
- NET: ~76%  

These names simply did not stay “cheap” for long. The market repeatedly bought their dips.

### 3.2 Separation of Entry Logic from Exit Logic

Most mean-reversion systems fail in strong trends because they exit at the mean (Z ≈ 0). This strategy **rejects** that idea.

- **Entry engine** = short-term mean reversion (Z-score)  
- **Exit engine** = volatility-adjusted trailing stop that only moves higher  

By decoupling the two, the system can buy weakness aggressively while still participating in the large subsequent advances. The 4× ATR trail is wide enough to survive normal pullbacks inside an uptrend but still provides a rational, volatility-based exit if the character of the stock changes.

### 3.3 High Time-in-Market by Design

Earlier versions that used tight risk (1% of capital) or strict mean-reversion exits spent too much time in cash and dramatically underperformed.  

By switching to **20% of equity per lot** and allowing pyramiding, the portfolio naturally stays 90–97% invested most of the time. In a persistent bull market this is a feature, not a bug.

### 3.4 Volatility as Both Opportunity and Risk Measure

- Z-score identifies when price is statistically extended to the downside relative to its recent distribution.
- ATR defines how far price must fall from the highest point before we admit the swing (or the trend) has failed.

This combination is adaptive. NVDA automatically receives wider dollar stops than a less volatile name, which is exactly what is required.

### 3.5 Research Path That Led Here

The final rules were not guessed. They emerged from systematic testing:

1. Original pure mean-reversion (Z < –1.5 + exit at Z > 0) produced high win rates but left massive upside on the table.
2. Switching to trailing stops improved results; 3× ATR was still too tight.
3. Analysis of post-exit price action showed that 95% of exits eventually went higher, with median upside left of +53% (and far more on NVDA/NET).
4. Widening to 4× ATR captured a large portion of the missed moves.
5. Loosening the entry threshold from –1.5 to –1.2 increased opportunity set and average exposure without destroying edge.
6. Further loosening to –1.0 / –0.8 began to add lower-quality signals and reduced performance.

The combination of Z < –1.2 + 4× ATR emerged as the clear local optimum on this universe and time period.

---

## 4. Detailed Mechanics

### 4.1 Z-Score Calculation
\[
Z_t = \frac{C_t - \text{SMA}_{20}(C)}{\sigma_{20}(C)}
\]

Entry/add occurs when \( Z_t < -1.2 \).

### 4.2 Average True Range (ATR)
True Range on day \( t \) is the greatest of:
- High − Low
- |High − Previous Close|
- |Low − Previous Close|

ATR(14) is the 14-period average of True Range.  
Stop for each lot = Highest close since that lot was opened − 4.0 × ATR(14) at the time of entry (fixed ATR for the life of the lot in the tested implementation).

### 4.3 Position Sizing & Pyramiding
On every new signal:
- Calculate 20% of *current* total equity.
- Deploy that amount into a new lot (subject to available cash and 100% maximum exposure).
- Multiple independent lots in the same ticker are permitted. Each lot has its own entry price and its own trailing stop.

This creates a natural scaling-in effect during multi-leg pullbacks.

### 4.4 Portfolio Construction Intent
With only three names and 20% lots, the system is designed so that it can be fully invested across the three names while still having dry powder to add on fresh dips. In practice it spent the large majority of the backtest period near full investment.

---

## 5. Risk Characteristics

- **Concentration risk** is high. The entire portfolio lives in three highly correlated technology names.
- Maximum observed drawdown was –31.1% — better than buy-and-hold of the same names but still substantial.
- The strategy will underperform (and can lose money) in prolonged bear markets or if the secular themes supporting these three stocks break.
- Because position sizes are equity-percentage based rather than volatility-targeted risk, larger absolute losses can occur after a strong run-up (the classic “big position into a big drawdown” risk).

This is **not** a low-risk or market-neutral strategy. It is a high-conviction, high-exposure trend system that uses dips as fuel.

---

## 6. Implementation Notes

- Daily bars are sufficient.
- Data source used in research: Yahoo Finance (adjusted closes).
- Commission assumption: 5 basis points per side.
- No slippage modeled (realistic for these highly liquid names at the position sizes tested).
- The strategy can be run with a simple daily scan: compute Z-score and ATR for each name, check for new signals, update trailing stops on existing lots, and rebalance cash accordingly.

---

## 7. Limitations & Regime Dependency

This system was optimized on a powerful bull market in a specific set of leadership stocks. Its edge is conditional on:

1. The universe remaining in primary uptrends.
2. Pullbacks continuing to be bought by the market (high mean-reversion success rate).
3. Volatility remaining elevated enough to generate frequent Z < –1.2 readings.

In a multi-year sideways or bear market the same rules would likely produce mediocre or negative results. A practical deployment should include a higher-timeframe regime filter (for example, only allow new entries when the stock or the Nasdaq is above its 200-day moving average) if capital preservation becomes a higher priority than maximum participation.

---

## 8. Summary

The Aggressive Dip Accumulation strategy succeeds because it aligns three realities of certain high-quality growth stocks in strong bull markets:

1. They trend powerfully for long periods.  
2. They experience frequent, tradable pullbacks.  
3. Those pullbacks are usually temporary.

By buying the pullbacks with meaningful size and then using a deliberately wide volatility-based trailing stop, the system stays invested in the leaders most of the time while still having a rational, rules-based reason to exit when the character of the move changes.

It is a simple idea executed with discipline and calibrated parameters. The research process that produced the final Z < –1.2 + 4× ATR combination demonstrated that both the entry threshold and the trailing distance materially affect results — and that the combination of a moderately loose entry with a moderately wide trail currently offers the best balance of return, risk-adjusted performance, and capital utilization on this universe.

---

*Research period: January 2023 – July 2026*  
*Document version: 1.0*  
*Not investment advice. Past performance is not indicative of future results.*
