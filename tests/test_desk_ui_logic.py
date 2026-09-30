"""
Offline checks for the Watchlist / Stock tab logic: autocomplete labels and
option order, the "most urgent first" default stock, and table sorting.

Run:  python tests/test_desk_ui_logic.py
"""

import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from data.tickers import label  # noqa: E402
from ui.desk_stock import urgent_first  # noqa: E402
from ui.desk_watch import stock_table, ticker_options  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


names = {"AMZN": "Amazon Com Inc", "AAPL": "Apple Inc.", "ZZZZ": "Z Corp"}
check("label shows ticker and company", label("AMZN", names) == "AMZN · Amazon Com Inc")
check("unknown ticker labels as itself", label("XYZ", names) == "XYZ")
options = ticker_options(names, ["NOW", "AMZN"])
check("your tickers come first, then the directory (no duplicates)",
      options == ["NOW", "AMZN", "AAPL", "ZZZZ"], str(options))


def row(ticker, **kw):
    base = {"ticker": ticker, "qualifies": False, "gate_dip": False, "gate_no_earnings": True,
            "gate_market_wide": True, "gate_not_lonely": True, "dist_pct": -10.0, "close": 100.0,
            "trigger": 90.0, "days_since_earnings": 40}
    base.update(kw)
    return base


rows = [row("FAR"), row("NEAR", dist_pct=-1.0), row("CALL", gate_dip=True, gate_market_wide=False),
        row("BUY", gate_dip=True, qualifies=True)]
result = SimpleNamespace(rows=rows)
groups = {"Mine": ["FAR", "NEAR", "CALL", "BUY"]}
check("default stock: buy zone, then your call, then close to a dip",
      urgent_first(result, groups) == ["BUY", "CALL", "NEAR", "FAR"], str(urgent_first(result, groups)))
table = stock_table(rows, frames={})
check("table sorted by what needs you first", list(table["Stock"]) == ["BUY", "CALL", "NEAR", "FAR"],
      str(list(table["Stock"])))
check("your-call rows say why", table.loc[table["Stock"] == "CALL", "Status"].iloc[0] == "🟠 Your call · company news")

print()
print("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
