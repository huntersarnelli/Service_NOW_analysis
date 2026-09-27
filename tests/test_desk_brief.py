"""
Offline checks for the morning brief: pre-market / after-hours move maths and the
to-do list (order, contents, quiet day, Telegram text).

Run:  python tests/test_desk_brief.py
"""

import pathlib
import sys
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from data.brief import brief_text, build_brief
from data.holdings import Holding
from data.paper_trades import PaperTrade
from data.premarket import move_since_close, session_label

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def bars(points):
    idx = pd.DatetimeIndex([pd.Timestamp(t, tz="America/New_York") for t, _ in points])
    return pd.Series([p for _, p in points], index=idx)


friday_close_then_monday_premarket = bars([
    ("2026-09-25 15:55", 100.0), ("2026-09-25 17:00", 101.0),   # Friday close bar, after hours
    ("2026-09-28 07:30", 95.0), ("2026-09-28 08:40", 94.0),     # Monday pre-market
])
m = move_since_close(friday_close_then_monday_premarket)
check("pre-market move is vs the previous session's close", abs(m["move_pct"] + 6.0) < 1e-9 and m["session"] == "pre-market",
      f"{m['move_pct']:.2f} {m['session']}")

after_hours = bars([("2026-09-24 15:55", 50.0), ("2026-09-25 15:55", 52.0), ("2026-09-25 18:00", 54.6)])
m = move_since_close(after_hours)
check("after-hours move is vs today's close", abs(m["move_pct"] - 5.0) < 1e-9 and m["session"] == "after hours")

during = bars([("2026-09-24 15:55", 200.0), ("2026-09-25 09:30", 198.0), ("2026-09-25 11:00", 210.0)])
m = move_since_close(during)
check("during market hours: vs the previous close", abs(m["move_pct"] - 5.0) < 1e-9 and m["session"] == "market open")
check("session labels", session_label(pd.Timestamp("2026-09-25 04:05")) == "pre-market"
      and session_label(pd.Timestamp("2026-09-25 16:00")) == "after hours")


def row(ticker, **kw):
    base = {"ticker": ticker, "qualifies": False, "gate_dip": False, "gate_no_earnings": True,
            "gate_market_wide": True, "gate_not_lonely": True, "dist_pct": -10.0, "z": -0.5,
            "close": 100.0, "days_to_earnings": 30.0, "days_since_earnings": 40}
    base.update(kw)
    return base


result = SimpleNamespace(breadth=0.23, rows=[
    row("META", gate_dip=True, gate_market_wide=False, z=-2.1),       # your call
    row("NVDA", days_to_earnings=3.0),                                 # earnings soon
    row("XOM", qualifies=True, gate_dip=True, z=-1.5),                 # buy zone (not on your lists)
    row("AMD"),
])
groups = {"Mine": ["META", "NVDA", "AMD"]}
premarket = pd.DataFrame([
    {"ticker": "AMD", "price": 150.0, "move_pct": -4.2, "session": "pre-market", "as_of": pd.Timestamp("2026-09-28 08:40")},
    {"ticker": "NVDA", "price": 200.0, "move_pct": 0.5, "session": "pre-market", "as_of": pd.Timestamp("2026-09-28 08:40")},
    {"ticker": "ES=F", "price": 7800.0, "move_pct": -0.4, "session": "pre-market", "as_of": pd.Timestamp("2026-09-28 08:40")},
])
pending = [PaperTrade(accession="A", ticker="CRWD", insider="Kurtz George", role="CEO", value_usd=1_200_000,
                      accepted="2026-09-25T18:05", entry_date="2026-09-28", entry_type="open", tested_sector=True)]
brief = build_brief(result, groups, [Holding("AMD", 10, 120)], premarket, pending)
kinds = [i["kind"] for i in brief["items"]]
check("items in action order: insider, gap, your call, buy zone, earnings",
      kinds == ["insider", "gap", "your_call", "buy_zone", "earnings"], str(kinds))
check("insider card says what to do", brief["items"][0]["title"] == "Paper-buy CRWD at the open (2026-09-28)")
check("gap card flags a holding", "(you own it)" in brief["items"][1]["title"] and "-4.2%" in brief["items"][1]["title"])
check("small pre-market moves are not listed", not any(i["ticker"] == "NVDA" and i["kind"] == "gap" for i in brief["items"]))
check("market line has futures and breadth", brief["market"] == ["S&P 500 futures -0.4%", "23% of core stocks dipping"],
      str(brief["market"]))

quiet = build_brief(SimpleNamespace(breadth=0.1, rows=[row("AMD")]), {"Mine": ["AMD"]}, [], pd.DataFrame(), [])
check("quiet day says so", quiet["quiet"] and "Nothing needs you today" in brief_text(quiet, "Mon"))
text = brief_text(brief, "Mon Sep 28, 08:40 AM ET")
check("telegram text lists every item", all(i["title"] in text for i in brief["items"]))

print()
print("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
