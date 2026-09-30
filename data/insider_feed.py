"""
Live insider-buy scan — the H10 "filing reaction" trade, for PAPER TRADING.

Evidence (insider-trading repo, docs/01_INSIDER_STUDY.md §5b): in established,
liquid tech stocks, buying at the first open after an insider-purchase filing
beat random days by +0.48pp to the same-day close and +0.69pp to the next
close (t ~= 3, 1,125 events, 2013-2026). About 70% of the reaction happens
overnight, before a regular-hours buyer can act. Tested on TECH only; other
sectors are shown but labelled untested. Paper-trade before real money.

Coverage: the SEC "latest filings" feed holds only the newest ~1,000 Form 4
entries, which is roughly the last business day from mid-afternoon on (checked
26 Sep 2026: Friday 14:06-21:57). That covers the evening and pre-market filings
this trade acts on (998 of the 1,125 backtest events); an intraday filing from an
earlier day has already passed its entry (that day's close). So: scan every
evening or morning. Missed days are not recoverable from this feed.

Flow: SEC "latest filings" Atom feed (Form 4) -> keep filings whose issuer is a
stock this app screens -> read the Form 4 XML -> apply the H10 event rules ->
decide the entry (next open, or same-day close for filings made during market
hours) -> log to data/paper_trades.py.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from data.sec_client import sec_get

FEED_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&company="
            "&dateb=&owner=include&start={start}&count=100&output=atom")
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
CACHE_DIR = Path(__file__).resolve().parent.parent / "portfolio_data" / "cache"

MARKET_OPEN, MARKET_CLOSE = dtime(9, 30), dtime(16, 0)
MIN_PURCHASE_USD = 10_000        # H1/H8 filter 5
MIN_PRICE_USD = 5.0              # H8 rule
MIN_DOLLAR_VOLUME_USD = 10e6     # H8 rule (20-day average)
MAX_FEED_PAGES = 12              # the feed itself ends around 1,000 entries


# ─────────────────────────────────────────────────────────────
# Feed and ticker map
# ─────────────────────────────────────────────────────────────
def parse_feed(atom_text: str) -> list[dict]:
    """Issuer entries from the SEC Atom feed: cik, accession, index_url, accepted (naive Eastern), form."""
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(atom_text.encode("latin-1", errors="replace"))
    out = []
    for entry in root.findall("a:entry", ns):
        title = entry.findtext("a:title", default="", namespaces=ns)
        if not title.endswith("(Issuer)"):
            continue  # each filing appears once for the owner and once for the issuer
        form = title.split(" - ", 1)[0].strip()
        cik_match = re.search(r"\((\d{10})\)\s*\(Issuer\)$", title)
        link = entry.find("a:link", ns)
        acc_match = re.search(r"accession-number=([\d-]+)", entry.findtext("a:id", default="", namespaces=ns))
        updated = entry.findtext("a:updated", default="", namespaces=ns)
        if not (cik_match and link is not None and acc_match and updated):
            continue
        accepted = datetime.fromisoformat(updated).replace(tzinfo=None)  # feed times are Eastern
        out.append({"form": form, "cik": int(cik_match.group(1)), "accession": acc_match.group(1),
                    "index_url": link.get("href"), "accepted": accepted})
    return out


def fetch_recent_filings(window_hours: float = 24) -> list[dict]:
    """Form 4 issuer entries accepted within `window_hours` of the newest filing in the feed.

    The window is measured from the feed's own latest timestamp (Eastern), so the
    scan does not depend on this computer's clock or time zone.
    """
    entries: list[dict] = []
    since = None
    for page in range(MAX_FEED_PAGES):
        response = sec_get(FEED_URL.format(start=page * 100))
        if response.status_code != 200:
            break
        batch = parse_feed(response.text)
        if not batch:
            break
        if since is None:
            since = max(e["accepted"] for e in batch) - timedelta(hours=window_hours)
        entries += [e for e in batch if e["accepted"] >= since]
        if min(e["accepted"] for e in batch) < since:
            break
    return entries


def load_ticker_map(max_age_hours: int = 24) -> dict[int, str]:
    """CIK -> ticker, from the SEC's company_tickers.json (cached for a day)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "company_tickers.json"
    fresh = path.exists() and (datetime.now().timestamp() - path.stat().st_mtime) < max_age_hours * 3600
    if not fresh:
        response = sec_get(TICKER_MAP_URL)
        if response.status_code == 200:
            path.write_text(response.text, encoding="utf-8")
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {int(v["cik_str"]): str(v["ticker"]).upper().replace(".", "-") for v in raw.values()}


# ─────────────────────────────────────────────────────────────
# Form 4 XML
# ─────────────────────────────────────────────────────────────
def _text(node, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def parse_form4(xml_text: str) -> dict:
    """The fields the H10 rules need, summed over the filing's code-P lots in common stock."""
    root = ET.fromstring(xml_text)
    owner = root.find("reportingOwner")
    relationship = owner.find("reportingOwnerRelationship") if owner is not None else None
    shares = value = 0.0
    lots = 0
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        title = _text(tx, "securityTitle/value").lower()
        code = _text(tx, "transactionCoding/transactionCode")
        acquired = _text(tx, "transactionAmounts/transactionAcquiredDisposedCode/value")
        if code != "P" or acquired != "A" or not ("common" in title or "ordinary" in title):
            continue
        try:
            lot_shares = float(_text(tx, "transactionAmounts/transactionShares/value"))
            lot_price = float(_text(tx, "transactionAmounts/transactionPricePerShare/value"))
        except ValueError:
            continue
        shares += lot_shares
        value += lot_shares * lot_price
        lots += 1
    return {
        "document_type": _text(root, "documentType"),
        "ticker": _text(root, "issuer/issuerTradingSymbol").upper(),
        "issuer": _text(root, "issuer/issuerName"),
        "insider": _text(owner, "reportingOwnerId/rptOwnerName") if owner is not None else "",
        "title": _text(relationship, "officerTitle") if relationship is not None else "",
        "is_director": _text(relationship, "isDirector") in ("1", "true") if relationship is not None else False,
        "plan_10b5_1": _text(root, "aff10b5One") in ("1", "true"),
        "purchase_lots": lots,
        "shares": shares,
        "value_usd": value,
        "avg_price": value / shares if shares else float("nan"),
    }


def fetch_form4(entry: dict) -> Optional[dict]:
    """Download and parse the Form 4 XML for one feed entry."""
    folder = entry["index_url"].rsplit("/", 1)[0]
    listing = sec_get(f"{folder}/index.json")
    if listing.status_code != 200:
        return None
    names = [item["name"] for item in listing.json().get("directory", {}).get("item", [])]
    xml_names = [n for n in names if n.lower().endswith(".xml")]
    if not xml_names:
        return None
    response = sec_get(f"{folder}/{xml_names[0]}")
    if response.status_code != 200:
        return None
    try:
        return parse_form4(response.text)
    except ET.ParseError:
        return None


# ─────────────────────────────────────────────────────────────
# H10 rules and entry timing
# ─────────────────────────────────────────────────────────────
def next_weekday(day: pd.Timestamp) -> pd.Timestamp:
    day = day + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def planned_entry(accepted: datetime, trading_days: pd.DatetimeIndex) -> tuple[pd.Timestamp, str]:
    """H10 entry: filed before 9:30 on a trading day -> that day's open; during market
    hours -> that day's close; after 16:00 or on a non-trading day -> next trading day's open.
    Days after the last known bar are assumed to be weekdays (holidays not known ahead)."""
    day = pd.Timestamp(accepted.date())
    last_known = trading_days.max()
    is_trading_day = day in trading_days or (day > last_known and day.weekday() < 5)
    if is_trading_day and accepted.time() < MARKET_OPEN:
        return day, "open"
    if is_trading_day and accepted.time() < MARKET_CLOSE:
        return day, "close"
    later = trading_days[trading_days > day]
    return (later[0] if len(later) else next_weekday(day)), "open"


def dollar_volume_20(df: Optional[pd.DataFrame]) -> float:
    if df is None or len(df) < 20 or "Volume" not in df:
        return float("nan")
    tail = df.tail(20)
    return float((tail["Close"] * tail["Volume"]).mean())


def rule_check(filing: dict, frame: Optional[pd.DataFrame]) -> list[str]:
    """Reasons a filing fails the H10 event rules; empty list = passes."""
    fails = []
    if filing["document_type"] != "4":
        fails.append("amendment (4/A)")
    if filing["purchase_lots"] == 0:
        fails.append("no open-market purchase")
    elif filing["value_usd"] < MIN_PURCHASE_USD:
        fails.append("under $10k")
    if filing["plan_10b5_1"]:
        fails.append("10b5-1 plan (pre-scheduled)")
    price = float(frame["Close"].iloc[-1]) if frame is not None and len(frame) else float("nan")
    if not price >= MIN_PRICE_USD:
        fails.append("price under $5")
    if not dollar_volume_20(frame) >= MIN_DOLLAR_VOLUME_USD:
        fails.append("under $10M/day traded")
    return fails


def scan(window_hours: float, screened: set[str], sectors: dict[str, str],
         frames: dict[str, pd.DataFrame], trading_days: pd.DatetimeIndex, progress=None) -> pd.DataFrame:
    """Insider purchases in your screened stocks over the last `window_hours`, with the H10 verdict."""
    ticker_map = load_ticker_map()
    entries = [e for e in fetch_recent_filings(window_hours) if ticker_map.get(e["cik"]) in screened]
    rows = []
    for i, entry in enumerate(entries):
        if progress:
            progress(i + 1, len(entries))
        filing = fetch_form4(entry)
        if filing is None or filing["purchase_lots"] == 0:
            continue  # sales, grants, option exercises: not signals
        ticker = ticker_map[entry["cik"]]
        fails = rule_check(filing, frames.get(ticker))
        entry_date, entry_type = planned_entry(entry["accepted"], trading_days)
        rows.append({
            "accession": entry["accession"], "ticker": ticker, "insider": filing["insider"],
            "role": filing["title"] or ("Director" if filing["is_director"] else "Other"),
            "value_usd": filing["value_usd"], "avg_price": filing["avg_price"],
            "accepted": entry["accepted"].isoformat(timespec="minutes"),
            "entry_date": entry_date.date().isoformat(), "entry_type": entry_type,
            "tested_sector": sectors.get(ticker) == "Tech",
            "passes": not fails, "fails": ", ".join(fails),
        })
    return pd.DataFrame(rows)
