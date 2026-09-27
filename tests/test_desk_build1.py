"""
Offline checks for Deployment Desk v3, Build 1: watchlists, simple holdings,
market pulse, and the rule that extra (watchlist) names never move breadth.

Run:  python tests/test_desk_build1.py

No network required — synthetic fixtures with known answers.
"""

import pathlib
import sys
import tempfile

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from data.holdings import (Holding, frame_to_holdings, hypothetical_drawdown, import_from_lots,
                           load_holdings, save_holdings, validate_holding, value_holdings)
from data.market_pulse import leaders_and_laggards, relative_strength_table, window_return
from data.portfolio import Lot
from data.screen import SCREENS, RAW, run_screen
from data.watchlists import clean_ticker_list, load_watchlists, save_watchlists, DEFAULT_WATCHLISTS

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


tmp = pathlib.Path(tempfile.mkdtemp())

# ── 1. watchlists ────────────────────────────────────────────
valid, bad = clean_ticker_list("aapl, msft  nvda,, brk.b, $$$, AAPL")
check("tickers are upper-cased, split and de-duplicated", valid == ["AAPL", "MSFT", "NVDA", "BRK.B"], str(valid))
check("junk entries are rejected, not silently kept", bad == ["$$$"], str(bad))
check("missing file -> starter groups", load_watchlists(tmp / "none.json") == DEFAULT_WATCHLISTS)
save_watchlists({"Mine": ["AAPL", "CEG"]}, tmp / "w.json")
check("watchlists round-trip", load_watchlists(tmp / "w.json") == {"Mine": ["AAPL", "CEG"]})

# ── 2. holdings ──────────────────────────────────────────────
h, err = validate_holding({"ticker": " meta ", "shares": "10", "avg_price": 500})
check("holding validates and upper-cases", err is None and h.ticker == "META" and h.shares == 10.0)
check("zero shares rejected", validate_holding({"ticker": "X", "shares": 0, "avg_price": 5})[1] is not None)
check("missing price rejected", validate_holding({"ticker": "X", "shares": 1, "avg_price": None})[1] is not None)

edited = pd.DataFrame({"ticker": ["NVDA", "", "NVDA", "MSFT"],
                       "shares": [10, None, 30, 5], "avg_price": [100, None, 200, 400]})
holdings, notes = frame_to_holdings(edited)
nvda = next(x for x in holdings if x.ticker == "NVDA")
check("blank rows ignored; duplicate ticker merged", len(holdings) == 2 and nvda.shares == 40)
check("merged average price is share-weighted", abs(nvda.avg_price - 175.0) < 1e-9, f"{nvda.avg_price}")
check("merge is reported to the user", any("merged" in n for n in notes))

save_holdings(holdings, tmp / "h.json")
check("holdings round-trip", [(x.ticker, x.shares, x.avg_price) for x in load_holdings(tmp / "h.json")]
      == [(x.ticker, x.shares, x.avg_price) for x in holdings])

lots = [Lot("AMD", 10, 100, "2024-01-02"), Lot("AMD", 10, 150, "2024-06-03", strategy="dip"),
        Lot("CRM", 4, 250, "2024-02-01")]
imported = {x.ticker: x for x in import_from_lots(lots)}
check("import blends lots across strategies into one holding",
      imported["AMD"].shares == 20 and abs(imported["AMD"].avg_price - 125.0) < 1e-9)

valued = value_holdings([Holding("AAA", 10, 50.0)], {"AAA": 60.0})
check("value / gain / gain % computed from average price",
      valued.loc[0, "Value"] == 600 and valued.loc[0, "Gain $"] == 100 and abs(valued.loc[0, "Gain %"] - 20) < 1e-9)

idx = pd.bdate_range("2025-01-01", periods=10)
frames_dd = {"AAA": pd.DataFrame({"Close": [100, 110, 120, 90, 60, 80, 100, 110, 115, 118.0]}, index=idx)}
dd = hypothetical_drawdown([Holding("AAA", 1, 100)], frames_dd)
check("drawdown: 120 -> 60 is -50%", abs(dd["max_drawdown_pct"] + 50) < 1e-9, f"{dd['max_drawdown_pct']}")

# ── 3. market pulse ──────────────────────────────────────────
n = 300
idx = pd.bdate_range("2024-01-01", periods=n)
def frame(daily):
    close = 100 * (1 + daily) ** np.arange(n)
    return pd.DataFrame({"Close": close, "High": close, "Low": close}, index=idx)

pulse_frames = {"SPY": frame(0.0), "XLE": frame(0.001), "XLK": frame(-0.001), "SMH": frame(0.002)}
check("window_return over 21 bars", abs(window_return(pulse_frames["XLE"]["Close"], 21) - (1.001 ** 21 - 1)) < 1e-9)
table = relative_strength_table(pulse_frames)
check("pulse table ranks the stronger fund first", table.iloc[0]["Fund"] == "SMH", table["Fund"].tolist())
leaders, laggards = leaders_and_laggards(table, n=1)
check("leaders/laggards use sectors only (themes excluded)", leaders == ["Energy"] and laggards == ["Technology"],
      f"{leaders} / {laggards}")

# ── 4. breadth stays on the calibrated universe ─────────────
rng = np.random.default_rng(0)
def noisy(drop_last=False):
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    if drop_last:
        close[-3:] -= 25  # a sharp dip -> Z well below -1.2
    return pd.DataFrame({"Close": close, "High": close + 0.5, "Low": close - 0.5}, index=idx)

base = {"SPY": noisy(), "AAA": noisy(), "BBB": noisy(), "CCC": noisy()}
with_extra = {**base, "EXTRA": noisy(drop_last=True)}
spec = SCREENS[RAW]
r_base = run_screen(base, {}, spec, breadth_universe=["AAA", "BBB", "CCC"])
r_extra = run_screen(with_extra, {}, spec, breadth_universe=["AAA", "BBB", "CCC"])
check("a dipping watchlist name does NOT change breadth", r_base.breadth == r_extra.breadth,
      f"{r_base.breadth} vs {r_extra.breadth}")
check("...but it is still screened", any(r["ticker"] == "EXTRA" and r["gate_dip"] for r in r_extra.rows))

print()
print("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
