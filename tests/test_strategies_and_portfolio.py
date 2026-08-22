"""
Correctness tests for the live app's rule engine and portfolio storage.

Covers: history-window sizing (the bug that used to blank the dashboard),
open-lot evaluation for both rule sets, trail monotonicity, excursion
metrics, JSON round-trips, lot validation and pyramided-lot blending.

Run:  python tests/test_strategies_and_portfolio.py

No network required — these run on synthetic fixtures with known answers.
"""

"""Offline checks for the exit engine, storage, and the history-window fix."""
import sys, tempfile, pathlib
import numpy as np, pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from data.market import compute_indicators, required_history_days
from data.strategies import DIP_SPEC, TACTICAL_SPEC, evaluate_lot, trail_series
from data.portfolio import JsonLotStore, Lot, validate_lot, aggregate_positions

fails = []
def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond: fails.append(name)

# ── 1. history sizing: the old flat 180 days blanked the app above ~119 SMA ──
check("required_history_days(20,14,200) covers a 200-bar SMA",
      required_history_days(20, 14, 200) > 200 * 1.45,
      f"-> {required_history_days(20,14,200)} calendar days")
check("required_history_days never shrinks below the old default",
      required_history_days(20, 14, 50) >= 180,
      f"-> {required_history_days(20,14,50)}")

# ── 2. synthetic series: flat 100, dip to 80, rally to 140, crash to 100 ──
n = 260
idx = pd.bdate_range("2024-01-01", periods=n)
close = np.concatenate([
    np.full(60, 100.0),
    np.linspace(100, 80, 20),    # the dip -> entry zone
    np.linspace(80, 140, 100),   # the rally
    np.linspace(140, 100, 40),   # the crash -> should trip a wide trail
    np.full(40, 100.0),
])[:n]
df = pd.DataFrame({
    "Open": close, "High": close * 1.01, "Low": close * 0.99,
    "Close": close, "Volume": 1_000_000,
}, index=idx)
df = compute_indicators(df, 20, 14, 50)

entry_date = idx[80]                      # bottom of the dip
entry_price = float(df["Close"].iloc[80])

ev_t = evaluate_lot(df, TACTICAL_SPEC, entry_date, entry_price, shares=100)
ev_d = evaluate_lot(df, DIP_SPEC, entry_date, entry_price, shares=100)

check("tactical lot evaluates", ev_t is not None)
check("dip lot evaluates", ev_d is not None)

# Tactical has a Z>0 mean exit, so it must bail early in the rally.
check("tactical exits (mean-reversion rule fires in the rally)",
      ev_t["status"] == "EXIT", f"reason={ev_t['exit_reason']} on {ev_t['exit_date'].date()}")
check("tactical exit reason is the Z rule", "Z >" in (ev_t["exit_reason"] or ""))

# Dip has no mean exit; it should ride the rally and stop out in the crash.
check("dip exits on the trail, not a mean rule",
      ev_d["status"] == "EXIT" and ev_d["exit_reason"] == "Trail hit",
      f"on {ev_d['exit_date'].date()} @ {ev_d['exit_price']:.2f}")
check("dip captures far more of the move than tactical",
      ev_d["pnl_pct"] > ev_t["pnl_pct"],
      f"dip {ev_d['pnl_pct']:+.1f}% vs tactical {ev_t['pnl_pct']:+.1f}%")

# ── 3. the bug the portfolio tab fixes: an exit must be detected mid-history ──
check("dip exit is strictly before the last bar (walks forward, not just today)",
      ev_d["exit_date"] < df.index[-1],
      f"exit {ev_d['exit_date'].date()} < last {df.index[-1].date()}")
check("metrics freeze at the exit bar (MFE not polluted by later bars)",
      ev_d["highest_close"] <= 140.001, f"MFE close {ev_d['highest_close']:.2f}")

# ── 4. trail mechanics ──
tr_t = trail_series(df, TACTICAL_SPEC, 80)
tr_d = trail_series(df, DIP_SPEC, 80)
check("tactical trail is monotonically non-decreasing (raise-only)",
      bool((tr_t.diff().dropna() >= -1e-9).all()))
check("dip trail is monotonically non-decreasing (tracks running high)",
      bool((tr_d.diff().dropna() >= -1e-9).all()))
check("dip trail sits below tactical trail (4xATR vs 2xATR)",
      float(tr_d.iloc[5]) < float(tr_t.iloc[5]),
      f"dip {tr_d.iloc[5]:.2f} vs tactical {tr_t.iloc[5]:.2f}")
check("no exit on the entry bar itself",
      float(df['Close'].iloc[80]) > float(tr_d.iloc[0]))

# ── 5. R-multiple and excursions are coherent ──
check("R-multiple finite", np.isfinite(ev_d["r_multiple"]), f"{ev_d['r_multiple']:+.2f}R")
check("MAE <= 0 <= MFE", ev_d["mae_pct"] <= 0 <= ev_d["mfe_pct"],
      f"MAE {ev_d['mae_pct']:+.1f}% MFE {ev_d['mfe_pct']:+.1f}%")

# ── 6. an open lot entered near the end must report HOLD ──
ev_open = evaluate_lot(df, DIP_SPEC, idx[-3], float(df["Close"].iloc[-3]), shares=10)
check("recent lot reports HOLD", ev_open["status"] == "HOLD",
      f"stop {ev_open['trail']:.2f}, {ev_open['dist_to_stop_pct']:+.1f}% away")

# ── 7. entry date outside the data returns None instead of exploding ──
check("future entry date -> None", evaluate_lot(df, DIP_SPEC, "2099-01-01", 100.0) is None)

# ── 8. storage round-trip + validation ──
with tempfile.TemporaryDirectory() as d:
    store = JsonLotStore(pathlib.Path(d) / "lots.json")
    check("empty store loads as []", store.load() == [])
    lots = [
        Lot(ticker="NVDA", shares=10, entry_price=120.5, entry_date="2025-03-04", strategy="dip"),
        Lot(ticker="NVDA", shares=5, entry_price=110.0, entry_date="2025-04-10", strategy="dip"),
        Lot(ticker="NOW", shares=3, entry_price=900.0, entry_date="2025-05-01", strategy="tactical"),
    ]
    store.save(lots)
    back = store.load()
    check("round-trips all lots", len(back) == 3)
    check("preserves entry price", back[0].entry_price == 120.5)
    check("preserves strategy tag", {l.strategy for l in back} == {"dip", "tactical"})
    agg = aggregate_positions(back)
    nvda = agg[agg.ticker == "NVDA"].iloc[0]
    check("pyramided lots blend to a weighted average entry",
          abs(nvda.avg_entry - (10*120.5 + 5*110.0)/15) < 1e-9, f"{nvda.avg_entry:.4f}")
    check("blended share count correct", nvda.shares == 15)

check("rejects zero shares", validate_lot({"ticker":"X","shares":0,"entry_price":1,"entry_date":"2025-01-01"})[1] is not None)
check("rejects future entry", validate_lot({"ticker":"X","shares":1,"entry_price":1,"entry_date":"2099-01-01"})[1] is not None)
check("rejects blank ticker", validate_lot({"ticker":"","shares":1,"entry_price":1,"entry_date":"2025-01-01"})[1] is not None)
check("accepts a good lot", validate_lot({"ticker":"nvda","shares":2,"entry_price":10,"entry_date":"2025-01-02"})[1] is None)
check("uppercases ticker", validate_lot({"ticker":"nvda","shares":2,"entry_price":10,"entry_date":"2025-01-02"})[0].ticker == "NVDA")

print("\n" + ("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
sys.exit(1 if fails else 0)
