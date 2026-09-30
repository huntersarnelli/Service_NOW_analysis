"""
Offline checks for the momentum study rules (docs/05_MOMENTUM_STUDY.md §3):
eligibility (price floor, history, stale data, funds), the 12-1 score, next-month
returns, turnover and the bad-print screen.

Run:  python tests/test_momentum.py
"""

import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from studies.momentum_lib import (eligible_universe, max_drawdown, momentum_scores, next_month_returns,
                                  reverting_spikes, turnover)

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


months = pd.period_range("2020-01", "2021-06", freq="M")
tickers = ["UP", "FLAT", "CHEAP", "NEW", "STALE", "SPY"]
adj = pd.DataFrame(index=months, columns=tickers, dtype=float)
adj["UP"] = 100 * 1.05 ** np.arange(len(months))      # +5% a month
adj["FLAT"] = 100.0
adj["CHEAP"] = 3.0 * 1.02 ** np.arange(len(months))    # rising, but still under $5
adj["NEW"] = np.nan
adj.loc[months[-4]:, "NEW"] = 50.0                      # only 4 months of history
adj["STALE"] = 80.0
adj["SPY"] = 300.0
traded = adj.copy()
dv20 = pd.DataFrame(1e9, index=months, columns=tickers)
dv20["FLAT"] = 2e9                                      # most traded
last = pd.DataFrame({t: [m.to_timestamp(how="end").normalize() for m in months] for t in tickers}, index=months)
last.loc[months[13], "STALE"] = months[13].to_timestamp() + pd.Timedelta(days=2)  # stopped trading early in month
panels = {"adj": adj, "traded": traded, "dv20": dv20, "last": last}

t = months[13]  # 2021-02: 13 months of history for the old names
names = eligible_universe(panels, t, size=None)
check("funds are excluded", "SPY" not in names)
check("stocks under $5 are excluded", "CHEAP" not in names, f"CHEAP traded {traded.loc[t, 'CHEAP']:.2f}")
check("stocks without 13 months of history are excluded", "NEW" not in names)
check("stocks that stopped trading early in the month are excluded", "STALE" not in names)
check("ranked by dollar volume", names[:2] == ["FLAT", "UP"], str(names))
check("size cap applies", eligible_universe(panels, t, size=1) == ["FLAT"])

scores = momentum_scores(panels, t, ["UP", "FLAT"])
check("12-1 score skips the latest month", abs(scores["UP"] - (1.05 ** 11 - 1)) < 1e-9, f"{scores['UP']:.4f}")
returns, missing = next_month_returns(panels, t, ["UP", "FLAT"])
check("next-month return", abs(returns["UP"] - 0.05) < 1e-9 and missing == 0)
panels["adj"].loc[months[14], "FLAT"] = np.nan
returns, missing = next_month_returns(panels, t, ["UP", "FLAT"])
check("missing next price -> 0% and counted", returns["FLAT"] == 0 and missing == 1)

check("turnover: first month is 100%", turnover([], ["A", "B"]) == 1.0)
check("turnover: one of two names replaced = 50%", turnover(["A", "B"], ["A", "C"]) == 0.5)
check("max drawdown of +10%, -50%", abs(max_drawdown(pd.Series([0.10, -0.50])) + 50) < 1e-9)
check("bad print detected", reverting_spikes(np.array([10, 10, 1000, 10, 10, 10, 10.0])) >= 1)
check("real crash not flagged", reverting_spikes(np.array([10, 10, 2, 1.9, 1.8, 1.7, 1.6])) == 0)

print()
print("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
