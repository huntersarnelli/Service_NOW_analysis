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

# ── ⭐ Want to buy ────────────────────────────────────────────
from data.brief import brief_title, watch_line, watch_rows  # noqa: E402
from data.watchlists import WANT_TO_BUY, toggle_want_to_buy  # noqa: E402

watch_result = SimpleNamespace(breadth=0.25, rows=[
    row("AMZN", dist_pct=-1.5, close=185.0, trigger=182.2),                           # close to its dip price
    row("GOOGL", dist_pct=-8.0, close=170.0, trigger=156.4),                          # far away
    row("MSFT", gate_dip=True, qualifies=True, dist_pct=1.0, close=400.0, trigger=404.0),   # crossed, buy zone
    row("TSLA", gate_dip=True, gate_market_wide=False, dist_pct=2.0, close=200.0, trigger=204.0),  # crossed, own news
])
wgroups = {WANT_TO_BUY: ["GOOGL", "AMZN", "MSFT", "TSLA"]}
w = watch_rows(watch_result, wgroups)
check("watch list: crossed first (deepest first), then close, then far",
      [x["ticker"] for x in w] == ["TSLA", "MSFT", "AMZN", "GOOGL"], str([x["ticker"] for x in w]))
check("close-to-dip line is flagged 👀", watch_line(w[2]).startswith("👀 AMZN") and "-1.5% away" in watch_line(w[2]))
wb = build_brief(watch_result, wgroups, [], pd.DataFrame(), [])
targets = [i for i in wb["items"] if i["kind"] == "target"]
by_ticker = {i["ticker"]: i for i in targets}
check("🎯 card for each crossed want-to-buy stock", set(by_ticker) == {"MSFT", "TSLA"})
check("🎯 card says buy zone vs your call", "🟢 buy zone" in by_ticker["MSFT"]["detail"]
      and "🟠 your call" in by_ticker["TSLA"]["detail"])
check("no duplicate 🟠 card for a crossed want-to-buy stock", not any(i["kind"] == "your_call" and i["ticker"] == "TSLA"
                                                                     for i in wb["items"]))
check("telegram text includes the want-to-buy list", "⭐ Want to buy:" in brief_text(wb, "Mon") and "AMZN" in brief_text(wb, "Mon"))
check("titles follow the time of day", brief_title("pre-market", 8) == "☀️ Morning brief"
      and brief_title("market open", 15) == "🕒 Afternoon brief" and brief_title("after hours", 18) == "🌙 Evening brief")
toggled = toggle_want_to_buy({WANT_TO_BUY: ["AMZN"]}, "NVDA")
check("⭐ adds, and ⭐ again removes", toggled[WANT_TO_BUY] == ["AMZN", "NVDA"]
      and toggle_want_to_buy(toggled, "NVDA")[WANT_TO_BUY] == ["AMZN"])

check("🎯 title shows the price, then the dip price",
      by_ticker["MSFT"]["title"].startswith("MSFT $") and "is below its dip price $" in by_ticker["MSFT"]["title"])

# --- today's bar missing from Yahoo's daily data (Sept 30 2026: daily Close was NaN after the close)
from data.market import fill_missing_today  # noqa: E402

daily = pd.DataFrame({"Open": [10.0, 11.0], "High": [11.0, 12.0], "Low": [9.0, 10.0],
                      "Close": [10.5, 11.5], "Volume": [100, 100]},
                     index=pd.to_datetime(["2026-09-28", "2026-09-29"]))
five = pd.DataFrame({"Open": [12.0, 12.5, 13.0], "High": [12.6, 13.4, 13.2], "Low": [11.8, 12.4, 12.9],
                     "Close": [12.5, 13.0, 13.1], "Volume": [5, 6, 7]},
                    index=pd.to_datetime(["2026-09-29 15:55", "2026-09-30 09:30", "2026-09-30 15:55"]))
filled = fill_missing_today({"AMZN": daily}, latest_daily_row=pd.Timestamp("2026-09-30"),
                            intraday={"AMZN": five}, session_day=None)["AMZN"]
last = filled.iloc[-1]
check("missing today's bar is built from 5-minute bars", filled.index[-1] == pd.Timestamp("2026-09-30")
      and last["Close"] == 13.1 and last["Open"] == 12.5 and last["High"] == 13.4 and last["Low"] == 12.4
      and last["Volume"] == 13, str(last.to_dict()))
check("a ticker that already has today's bar is left alone",
      fill_missing_today({"X": filled}, latest_daily_row=pd.Timestamp("2026-09-30"),
                         intraday={"X": five}, session_day=None)["X"].equals(filled))
check("holiday: intraday has nothing newer, daily data kept",
      fill_missing_today({"AMZN": daily}, latest_daily_row=None, session_day=pd.Timestamp("2026-09-30"),
                         intraday={"AMZN": five[five.index < "2026-09-30"]})["AMZN"].equals(daily))

print()
print("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
