"""
Ticker directory for autocomplete: every SEC-registered ticker with its company
name (from the SEC's company_tickers.json, cached for a day in portfolio_data/cache/).
Tickers use Yahoo's format (BRK.B -> BRK-B). Funds (SPY, QQQ, sector ETFs) are not
in the SEC list; the app accepts them as typed tickers.
"""

from __future__ import annotations

import json
from datetime import datetime

from data.insider_feed import CACHE_DIR, TICKER_MAP_URL
from data.sec_client import sec_get

KNOWN_FUNDS = {"SPY": "SPDR S&P 500 ETF", "QQQ": "Invesco QQQ (Nasdaq-100)", "SMH": "VanEck Semiconductor ETF",
               "IGV": "iShares Software ETF", "XLK": "Technology Select Sector SPDR", "XLE": "Energy Select Sector SPDR",
               "XLU": "Utilities Select Sector SPDR", "DIA": "SPDR Dow Jones ETF", "IWM": "iShares Russell 2000 ETF"}


def ticker_names(max_age_hours: int = 24) -> dict[str, str]:
    """{ticker: company name}. Falls back to an empty dict if the SEC can't be reached."""
    path = CACHE_DIR / "company_tickers.json"
    fresh = path.exists() and (datetime.now().timestamp() - path.stat().st_mtime) < max_age_hours * 3600
    if not fresh:
        try:
            response = sec_get(TICKER_MAP_URL)
            if response.status_code == 200:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path.write_text(response.text, encoding="utf-8")
        except Exception:  # noqa: BLE001 -- offline: use the old cache if there is one
            pass
    names = dict(KNOWN_FUNDS)
    if path.exists():
        for v in json.loads(path.read_text(encoding="utf-8")).values():
            ticker = str(v["ticker"]).upper().replace(".", "-")
            title = str(v["title"])
            names.setdefault(ticker, title.title() if title.isupper() else title)  # "AMAZON COM INC" -> "Amazon Com Inc"
    return names


def label(ticker: str, names: dict[str, str]) -> str:
    """'AMZN · Amazon.com, Inc.' for autocomplete; just the ticker if the name is unknown."""
    name = names.get(ticker)
    return f"{ticker} · {name[:40]}" if name else ticker
