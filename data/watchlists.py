"""
Watchlists — named groups of tickers you care about, edited in the app.

Watchlists are a VIEW over the market, not a change to the screen. The screen's
breadth gate was calibrated on the frozen 124-name UNIVERSE_V2, so names you add
here are screened like any other name but never counted in breadth
(see run_screen(breadth_universe=...)).

Stored in portfolio_data/watchlists.json (gitignored, like your positions).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_DOC = "watchlists"

WANT_TO_BUY = "⭐ Want to buy"  # the short list the brief tracks against each stock's dip price

# Starter groups. Edit them in the app (Stocks tab → Edit watchlists, or ⭐ on any stock).
DEFAULT_WATCHLISTS: dict[str, list[str]] = {
    WANT_TO_BUY: ["AMZN"],
    "Mag 7": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
    "AI software": ["NOW", "CRM", "ORCL", "SNOW", "DDOG", "MDB", "PLTR", "PANW", "CRWD", "ADBE"],
    "AI hardware & chips": ["AVGO", "AMD", "MU", "ANET", "MRVL", "AMAT", "LRCX", "KLAC"],
    "AI power & energy": ["CEG", "VST", "GEV", "VRT", "NEE", "XOM", "CVX"],
}

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def clean_ticker_list(raw: str | list[str]) -> tuple[list[str], list[str]]:
    """Parse 'aapl, msft nvda' (or a list) into (valid tickers, rejected entries).

    Upper-cases, splits on commas/spaces, drops duplicates, keeps order.
    """
    items = raw if isinstance(raw, list) else re.split(r"[,\s]+", raw or "")
    valid: list[str] = []
    rejected: list[str] = []
    for item in items:
        ticker = str(item).strip().upper()
        if not ticker:
            continue
        if _TICKER_RE.match(ticker):
            if ticker not in valid:
                valid.append(ticker)
        else:
            rejected.append(str(item))
    return valid, rejected


def load_watchlists(store) -> dict[str, list[str]]:
    """This user's watchlists, or the starter groups if they have never saved any."""
    payload = store.get(WATCHLIST_DOC)
    if not payload:
        return {name: list(tickers) for name, tickers in DEFAULT_WATCHLISTS.items()}
    out: dict[str, list[str]] = {}
    for name, tickers in (payload.get("watchlists") or {}).items():
        valid, _ = clean_ticker_list(tickers if isinstance(tickers, list) else [])
        if str(name).strip():
            out[str(name).strip()] = valid
    return out


def save_watchlists(groups: dict[str, list[str]], store) -> None:
    store.put(WATCHLIST_DOC, {"schema": 1, "updated_at": datetime.now().isoformat(timespec="seconds"),
                              "watchlists": {name: list(tickers) for name, tickers in groups.items()}})


def all_watchlist_tickers(groups: dict[str, list[str]]) -> list[str]:
    """Every ticker across all groups, de-duplicated, in first-seen order."""
    seen: list[str] = []
    for tickers in groups.values():
        for ticker in tickers:
            if ticker not in seen:
                seen.append(ticker)
    return seen


def groups_for_ticker(groups: dict[str, list[str]], ticker: str) -> list[str]:
    """Names of the watchlists that contain this ticker."""
    return [name for name, tickers in groups.items() if ticker in tickers]


def want_to_buy(groups: dict[str, list[str]]) -> list[str]:
    return list(groups.get(WANT_TO_BUY, []))


def toggle_want_to_buy(groups: dict[str, list[str]], ticker: str) -> dict[str, list[str]]:
    """Add the ticker to ⭐ Want to buy, or remove it if it is already there."""
    updated = {name: list(tickers) for name, tickers in groups.items()}
    current = updated.setdefault(WANT_TO_BUY, [])
    if ticker in current:
        current.remove(ticker)
    else:
        current.append(ticker)
    return updated
