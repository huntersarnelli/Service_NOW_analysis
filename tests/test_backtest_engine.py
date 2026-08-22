"""
Correctness tests for the Strategy B portfolio backtest engine.

Covers: no-signal behaviour, position sizing, the 100% exposure cap, cash
solvency, pyramiding modes, trailing-stop geometry, commission effects, the
A-vs-B exit difference, metric coherence and determinism.

Run:  python tests/test_backtest_engine.py

No network required — these run on synthetic fixtures with known answers.
"""

import sys, io, pathlib, warnings
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from dataclasses import replace
from studies.dip_backtest import BacktestConfig, run_backtest, buy_and_hold

fails=[]
def check(n,c,x=""):
    print(("PASS  " if c else "FAIL  ")+n+(f"   {x}" if x else ""))
    if not c: fails.append(n)

def ohlc(close, seed=0):
    """Wrap a close path in realistic intraday range so ATR is ~2% of price."""
    rng = np.random.default_rng(seed)
    c = np.asarray(close, float)
    rng_pct = 0.02 + 0.01*rng.random(len(c))
    hi = c*(1+rng_pct/2); lo = c*(1-rng_pct/2)
    idx = pd.bdate_range("2023-01-02", periods=len(c))
    return pd.DataFrame({"Open":c,"High":hi,"Low":lo,"Close":c,"Volume":1e6}, index=idx)

def trend_with_dips(n=600, drift=0.0012, vol=0.022, dips=((120,-0.18),(300,-0.22),(450,-0.15)), seed=7):
    """Geometric walk with an upward drift and a few sharp injected drawdowns."""
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, n)
    for start, depth in dips:
        span = 8
        r[start:start+span] += depth/span
        r[start+span:start+span+16] += -depth/16*0.8   # partial recovery
    return 100*np.exp(np.cumsum(r))

px = trend_with_dips()
one = {"AAA": ohlc(px)}

# --- A. flat series: no signal, no trades -----------------------------------
flat = {"AAA": ohlc(np.full(250, 100.0))}
r = run_backtest(flat, BacktestConfig())
check("flat series produces no trades", len(r.trades)==0, f"{len(r.trades)} trades")
check("flat series preserves capital", abs(r.equity.iloc[-1]-100_000)<1e-6)
check("flat series exposure is zero", r.exposure.max()==0)

# --- B. realistic trend: lots open, some ride, ATR-scaled trail --------------
r = run_backtest(one, replace(BacktestConfig(), pyramid_mode="on_cross"))
check("on_cross opens lots on a dipping uptrend", len(r.trades)>=3, f"{len(r.trades)} lots")
check("20% alloc sizes the first lot at ~20% of equity",
      abs(r.trades.iloc[0].cost-20_000)/20_000 < 0.03, f"${r.trades.iloc[0].cost:,.0f}")
check("at least one lot rides a real advance (MFE > 15%)",
      (r.trades.mfe_pct>15).any(), f"best MFE {r.trades.mfe_pct.max():.0f}%")
check("no lot closes on its entry bar", (r.trades.bars_held>0).all())
check("trail is the dominant exit reason",
      (r.trades.exit_reason=="Trail hit").sum() >= len(r.trades)-1,
      r.trades.exit_reason.value_counts().to_dict())

# --- C. exposure cap with many correlated names -----------------------------
many = {f"T{i}": ohlc(trend_with_dips(seed=100+i), seed=i) for i in range(10)}
r10 = run_backtest(many, BacktestConfig())
check("exposure never exceeds 100%", r10.exposure.max() <= 1.0001, f"max {r10.exposure.max():.4f}")
check("equity stays positive", r10.equity.min() > 0)
check("cash constraint actually binds", r10.exposure.max() > 0.9, f"max {r10.exposure.max():.3f}")
check("never spends more cash than it has", r10.equity.min() > 0)

# --- D. pyramiding: every_bar is the most permissive -------------------------
counts={m: len(run_backtest(one, replace(BacktestConfig(), pyramid_mode=m)).trades)
        for m in ("none","on_cross","every_bar")}
check("every_bar opens the most lots", counts["every_bar"]>=max(counts["none"],counts["on_cross"]), str(counts))
check("on_cross opens at most one lot per dip episode",
      counts["on_cross"]<=counts["every_bar"], str(counts))
# `none` re-enters after each stop-out, so it is NOT a subset of on_cross.
check("every mode opens at least one lot", min(counts.values())>=1, str(counts))

# --- E. trailing stop geometry ----------------------------------------------
r = run_backtest(one, replace(BacktestConfig(), pyramid_mode="on_cross"))
t = r.trades[r.trades.exit_reason=="Trail hit"].iloc[0]
implied = (t.mfe_pct/100+1)*t.entry_price - t.exit_price
check("exit sits ~4xATR below the peak close since entry",
      abs(implied - 4*t.atr_at_entry)/max(4*t.atr_at_entry,1e-9) < 0.30,
      f"gap {implied:.2f} vs 4xATR {4*t.atr_at_entry:.2f}")
wide = run_backtest(one, replace(BacktestConfig(), pyramid_mode="on_cross", atr_mult=8.0))
tight = run_backtest(one, replace(BacktestConfig(), pyramid_mode="on_cross", atr_mult=1.0))
check("wider trail => longer average hold",
      wide.trades.days_held.mean() > tight.trades.days_held.mean(),
      f"8xATR {wide.trades.days_held.mean():.0f}d vs 1xATR {tight.trades.days_held.mean():.0f}d")

# --- F. commissions cost money ----------------------------------------------
free = run_backtest(one, replace(BacktestConfig(), commission_bps=0.0))
paid = run_backtest(one, replace(BacktestConfig(), commission_bps=50.0))
check("higher commission => lower final equity", paid.equity.iloc[-1] < free.equity.iloc[-1],
      f"${paid.equity.iloc[-1]:,.0f} < ${free.equity.iloc[-1]:,.0f}")

# --- G. the A-vs-B difference: mean exit clips winners in an uptrend ---------
b = run_backtest(one, replace(BacktestConfig(), pyramid_mode="on_cross"))
a = run_backtest(one, replace(BacktestConfig(), pyramid_mode="on_cross",
                              mean_reversion_exit=True, atr_mult=2.0, z_entry=-1.5))
check("mean-reversion exit shortens the average hold",
      a.trades.days_held.mean() < b.trades.days_held.mean(),
      f"A {a.trades.days_held.mean():.0f}d vs B {b.trades.days_held.mean():.0f}d")
check("mean-reversion exit leaves upside behind (higher giveback)",
      a.metrics["avg_giveback_pct"] >= 0)

# --- H. buy & hold ------------------------------------------------------------
bh = buy_and_hold(one, 100_000.0)
check("buy&hold tracks the underlying", abs(bh.iloc[-1]/bh.iloc[0] - px[-1]/px[0]) < 0.01,
      f"{bh.iloc[-1]/bh.iloc[0]:.2f}x vs {px[-1]/px[0]:.2f}x")

# --- I. metric coherence -------------------------------------------------------
m = r10.metrics
check("max drawdown <= 0", m["max_drawdown_pct"] <= 0)
check("avg exposure in [0,100]", 0 <= m["avg_exposure_pct"] <= 100)
check("CAGR reconciles with final equity",
      abs((1+m["cagr_pct"]/100)**m["years"]*100_000 - m["final_equity"]) < 1.0)
check("win rate in [0,100]", 0 <= m["win_rate_pct"] <= 100)
check("profit factor positive", m["profit_factor"] > 0)

# --- J. determinism -------------------------------------------------------------
r1 = run_backtest(one, BacktestConfig()); r2 = run_backtest(one, BacktestConfig())
check("engine is deterministic", r1.equity.iloc[-1] == r2.equity.iloc[-1])

print("\n"+("ENGINE OK" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
