"""
Offline checks for Build 2: the SEC feed / Form 4 parser, the H10 entry rule and
event rules, the insider paper-trade log, and the QQQ scoreboard.

Run:  python tests/test_desk_build2.py

No network required — sample SEC documents and synthetic prices with known answers.
"""

import pathlib
import sys
import tempfile
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from data.insider_feed import parse_feed, parse_form4, planned_entry, rule_check
from data.journal import validate_decision
from data.paper_trades import add_signals, fill_outcomes, load_trades, summary
from data.store import FileStore
from data.scoreboard import build_calls, log_buy_zone, load_buy_zone_log, score_call, score_table, summarise

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


tmp = pathlib.Path(tempfile.mkdtemp())

# ── 1. SEC feed ──────────────────────────────────────────────
ATOM = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>4 - Smith Jane (0000000001) (Reporting)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/0000000001-26-000001-index.htm"/>
<updated>2026-09-25T18:05:00-04:00</updated><id>urn:tag:sec.gov,2008:accession-number=0000000001-26-000001</id></entry>
<entry><title>4 - Acme Corp (0000320193) (Issuer)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/320193/000000000126000001/0000000001-26-000001-index.htm"/>
<updated>2026-09-25T18:05:00-04:00</updated><id>urn:tag:sec.gov,2008:accession-number=0000000001-26-000001</id></entry>
</feed>"""
entries = parse_feed(ATOM)
check("feed keeps only the issuer copy of each filing", len(entries) == 1 and entries[0]["cik"] == 320193)
check("feed time kept as Eastern clock time", entries[0]["accepted"] == datetime(2026, 9, 25, 18, 5))

# ── 2. Form 4 XML ────────────────────────────────────────────
def form4(code_rows, plan="0", doc="4"):
    txs = "".join(f"""<nonDerivativeTransaction><securityTitle><value>{title}</value></securityTitle>
      <transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>{sh}</value></transactionShares>
      <transactionPricePerShare><value>{px}</value></transactionPricePerShare>
      <transactionAcquiredDisposedCode><value>{ad}</value></transactionAcquiredDisposedCode></transactionAmounts>
      </nonDerivativeTransaction>""" for title, code, sh, px, ad in code_rows)
    return f"""<?xml version="1.0"?><ownershipDocument><documentType>{doc}</documentType>
      <issuer><issuerTradingSymbol>acme</issuerTradingSymbol><issuerName>Acme</issuerName></issuer>
      <reportingOwner><reportingOwnerId><rptOwnerName>Jane Smith</rptOwnerName></reportingOwnerId>
      <reportingOwnerRelationship><isDirector>0</isDirector><officerTitle>CEO</officerTitle></reportingOwnerRelationship>
      </reportingOwner><aff10b5One>{plan}</aff10b5One><nonDerivativeTable>{txs}</nonDerivativeTable></ownershipDocument>"""

f = parse_form4(form4([("Common Stock", "P", 100, 50, "A"), ("Common Stock", "P", 300, 60, "A"),
                       ("Common Stock", "S", 999, 70, "D"), ("Preferred Stock", "P", 50, 10, "A")]))
check("only code-P common-stock lots are summed", f["purchase_lots"] == 2 and f["shares"] == 400)
check("dollar value and average price", f["value_usd"] == 23000 and abs(f["avg_price"] - 57.5) < 1e-9)
check("ticker, insider and title read", f["ticker"] == "ACME" and f["insider"] == "Jane Smith" and f["title"] == "CEO")
check("10b5-1 flag read", parse_form4(form4([("Common Stock", "P", 1, 1, "A")], plan="1"))["plan_10b5_1"])

# ── 3. H10 entry rule and event rules ────────────────────────
days = pd.DatetimeIndex(pd.bdate_range("2026-09-21", "2026-09-25"))  # Mon-Fri, last known bar Fri
check("evening filing -> next open", planned_entry(datetime(2026, 9, 22, 17, 30), days) == (pd.Timestamp("2026-09-23"), "open"))
check("pre-market filing -> same-day open", planned_entry(datetime(2026, 9, 23, 7, 0), days) == (pd.Timestamp("2026-09-23"), "open"))
check("intraday filing -> same-day close", planned_entry(datetime(2026, 9, 23, 11, 0), days) == (pd.Timestamp("2026-09-23"), "close"))
check("Friday evening -> Monday open (beyond known bars)",
      planned_entry(datetime(2026, 9, 25, 18, 5), days) == (pd.Timestamp("2026-09-28"), "open"))

idx = pd.bdate_range("2026-08-01", periods=30)
liquid = pd.DataFrame({"Close": np.full(30, 50.0), "Volume": np.full(30, 1e6)}, index=idx)   # $50M/day
thin = pd.DataFrame({"Close": np.full(30, 50.0), "Volume": np.full(30, 1e4)}, index=idx)     # $0.5M/day
good = parse_form4(form4([("Common Stock", "P", 1000, 50, "A")]))
check("liquid, $50k purchase passes", rule_check(good, liquid) == [], str(rule_check(good, liquid)))
check("thin stock fails the $10M/day rule", "under $10M/day traded" in rule_check(good, thin))
small = parse_form4(form4([("Common Stock", "P", 10, 50, "A")]))
check("$500 purchase fails the $10k rule", "under $10k" in rule_check(small, liquid))

# ── 4. paper trades ──────────────────────────────────────────
scan = pd.DataFrame([
    {"accession": "A1", "ticker": "AAA", "insider": "X", "role": "CEO", "value_usd": 50000.0,
     "avg_price": 50.0, "accepted": "2026-09-22T17:30", "entry_date": "2026-09-23", "entry_type": "open",
     "tested_sector": True, "passes": True, "fails": ""},
    {"accession": "A2", "ticker": "BBB", "insider": "Y", "role": "Director", "value_usd": 900.0,
     "avg_price": 9.0, "accepted": "2026-09-22T17:40", "entry_date": "2026-09-23", "entry_type": "open",
     "tested_sector": True, "passes": False, "fails": "under $10k"},
])
path = FileStore(tmp / "paper")
check("only passing signals are logged", add_signals(scan, path) == 1)
check("re-scanning does not duplicate", add_signals(scan, path) == 0)

pidx = pd.DatetimeIndex(["2026-09-22", "2026-09-23", "2026-09-24"])
frames = {
    "AAA": pd.DataFrame({"Open": [100, 102, 105], "Close": [101, 104, 106.08]}, index=pidx),
    "SPY": pd.DataFrame({"Open": [500, 500, 505], "Close": [500, 505, 510]}, index=pidx),
    "QQQ": pd.DataFrame({"Open": [400, 400, 404], "Close": [400, 402, 404]}, index=pidx),
}
trades = load_trades(path)
fill_outcomes(trades, frames)
t = trades[0]
check("entry at the open of the entry day", t.entry_price == 102 and t.status == "filled")
check("same-day return open->close", abs(t.same_day_return - (104 / 102 - 1) * 100) < 1e-9)
check("next-day return vs SPY from the same open", abs(t.next_day_return - 4.0) < 1e-9 and abs(t.next_day_spy - 2.0) < 1e-9)
s = summary(trades)
check("summary: next-day edge +2pp, 100% hit", abs(s["next_day_edge"] - 2.0) < 1e-9 and s["next_day_hit"] == 1.0)

# ── 5. scoreboard ────────────────────────────────────────────
sidx = pd.bdate_range("2026-01-01", periods=80)
sframes = {"AAA": pd.DataFrame({"Close": 100 * 1.002 ** np.arange(80)}, index=sidx),
           "QQQ": pd.DataFrame({"Close": 100 * 1.001 ** np.arange(80)}, index=sidx)}
scored = score_call("AAA", sidx[0].date().isoformat(), sframes, 20)
expected = ((1.002 ** 20) - (1.001 ** 20)) * 100
check("20-day edge vs QQQ", scored["status"] == "scored" and abs(scored["edge"] - expected) < 1e-9, f"{scored['edge']:.4f}")
pending = score_call("AAA", sidx[70].date().isoformat(), sframes, 20)
check("recent call is pending with days so far", pending["status"] == "pending" and pending["days"] == 9)
weekend = score_call("AAA", "2026-01-03", sframes, 20)  # a Saturday -> uses Friday's close
check("weekend decision uses the prior close", weekend["status"] == "scored")

buy, _ = validate_decision({"ticker": "AAA", "action": "buy", "price": 100, "confidence": 3,
                            "thesis": "x", "decided_on": sidx[0].date().isoformat()})
calls = build_calls([buy], [{"ticker": "AAA", "date": sidx[5].date().isoformat(), "price": 1}])
summary_table = summarise(score_table(calls, sframes))
check("groups summarised", list(summary_table["Group"]) == ["Your buys", "Your passes", "Buy-zone signals"])
check("too few calls -> 'Too early'", summary_table.loc[0, "Verdict (20d)"].startswith("Too early"))

bz = FileStore(tmp / "bz")
rows = [{"ticker": "AAA", "close": 10.0, "last_bar": pd.Timestamp("2026-09-25")}]
check("buy-zone signal logged once per day", log_buy_zone(rows, bz) == 1 and log_buy_zone(rows, bz) == 0
      and len(load_buy_zone_log(bz)) == 1)

print()
print("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
