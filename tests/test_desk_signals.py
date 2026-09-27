"""
Offline checks for the simplified Deployment Desk: the plain-English statuses
(Buy zone / Your call / Close to a dip), headline normalising (and that no
placeholder headlines can ever appear), and the decision journal.

Run:  python tests/test_desk_signals.py

No network required.
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import data.news as news
from data.journal import append_decision, load_journal, validate_decision
from data.signals import BUY_ZONE, NEAR, NONE, YOUR_CALL, cause, classify, reasons, short_reason

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


def row(**kw):
    base = {"ticker": "TEST", "qualifies": False, "gate_dip": False, "gate_no_earnings": True,
            "gate_market_wide": True, "gate_not_lonely": True, "dist_pct": -10.0, "days_since_earnings": 40}
    base.update(kw)
    return base


# ── 1. statuses ──────────────────────────────────────────────
check("passes every gate -> Buy zone", classify(row(qualifies=True, gate_dip=True)) == BUY_ZONE)
company = row(gate_dip=True, gate_market_wide=False)
check("dipping on company news -> Your call (not blocked)", classify(company) == YOUR_CALL)
check("company news is explained in plain words", short_reason(company) == "company news", short_reason(company))
check("cause says company-specific", cause(company) == "Company-specific")
earn = row(gate_dip=True, gate_no_earnings=False, days_since_earnings=3)
check("just after earnings -> Your call", classify(earn) == YOUR_CALL)
check("earnings reason names the days", "3 trading days ago" in reasons(earn)[0][1], reasons(earn)[0][1])
both = row(gate_dip=True, gate_market_wide=False, gate_not_lonely=False)
check("several reasons all listed", short_reason(both) == "company news, falling alone", short_reason(both))
check("within 3% of dip price -> Close to a dip", classify(row(dist_pct=-2.5)) == NEAR)
check("5% away -> nothing", classify(row(dist_pct=-5.0)) == NONE)
check("not dipping has no cause", cause(row()) == "")

# ── 2. headlines ─────────────────────────────────────────────
new_shape = {"content": {"title": "Chip maker beats", "pubDate": "2026-09-26T11:41:02Z",
                         "provider": {"displayName": "Reuters"},
                         "canonicalUrl": {"url": "https://example.com/a"}, "summary": "s"}}
old_shape = {"title": "Old style", "publisher": "Yahoo", "link": "https://example.com/b",
             "providerPublishTime": 1790000000}
a, b = news.normalise_yahoo_item(new_shape), news.normalise_yahoo_item(old_shape)
check("new Yahoo news shape parsed", a["title"] == "Chip maker beats" and a["source"] == "Reuters"
      and a["url"].endswith("/a") and a["published_at"] is not None)
check("old Yahoo news shape parsed", b["title"] == "Old style" and b["url"].endswith("/b"))
check("item without a title is dropped", news.normalise_yahoo_item({"content": {}}) is None)

news.fetch_yahoo_headlines = lambda ticker, limit=15: []  # simulate: no source has anything
empty = news.get_headlines("TEST", alpha_vantage_key=None)
check("no source -> empty list, never placeholders", empty["articles"] == [] and "No headlines" in empty["note"])

news.fetch_news_sentiment_alpha_vantage = lambda t, k, limit=15: ([], "rate limit")
fallback = news.get_headlines("TEST", alpha_vantage_key="dummy")
check("Alpha Vantage empty -> falls back, says why, no placeholders",
      fallback["articles"] == [] and "rate limit" in fallback["note"] and not fallback["has_sentiment"])

mixed = [{"title": "about NEE", "relevance": 0.8}, {"title": "bond listing", "relevance": 0.05},
         {"title": "no score", "relevance": None}]
check("low-relevance articles are hidden", [x["title"] for x in news.keep_relevant(mixed)] == ["about NEE", "no score"])
check("if nothing is relevant, keep everything", len(news.keep_relevant([{"title": "x", "relevance": 0.01}])) == 1)

# ── 3. decision journal ──────────────────────────────────────
ok, err = validate_decision({"ticker": "meta", "action": "buy", "price": 500, "confidence": 4,
                             "thesis": "lawsuit is a fine, not a business threat"})
check("valid decision accepted", err is None and ok.ticker == "META" and ok.action == "buy")
check("missing reason rejected", validate_decision({"ticker": "X", "action": "pass", "price": 5,
                                                    "confidence": 3, "thesis": " "})[1] is not None)
check("confidence outside 1-5 rejected", validate_decision({"ticker": "X", "action": "buy", "price": 5,
                                                            "confidence": 9, "thesis": "x"})[1] is not None)
check("action must be buy or pass", validate_decision({"ticker": "X", "action": "short", "price": 5,
                                                       "confidence": 3, "thesis": "x"})[1] is not None)
path = pathlib.Path(tempfile.mkdtemp()) / "j.json"
append_decision(ok, path)
p2, _ = validate_decision({"ticker": "NVDA", "action": "pass", "price": 100, "confidence": 2, "thesis": "too hot"})
append_decision(p2, path)
loaded = load_journal(path)
check("journal appends and keeps passes too", [d.ticker for d in loaded] == ["META", "NVDA"]
      and loaded[1].action == "pass")

print()
print("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
