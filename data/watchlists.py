"""
Watchlists — named groups of tickers you care about, edited in the app.

Watchlists are a VIEW over the market, not a change to the screen. The screen's
breadth gate was calibrated on the frozen 124-name UNIVERSE_V2, so names you add
here are screened like any other name but never counted in breadth
(see run_screen(breadth_universe=...)).

Stored in portfolio_data/watchlists.json (gitignored, like your positions).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = REPO_ROOT / "portfolio_data" / "watchlists.json"

# Starter groups. Edit them in the app's Watchlists tab.
DEFAULT_WATCHLISTS: dict[str, list[str]] = {
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


def load_watchlists(path: Path = WATCHLIST_PATH) -> dict[str, list[str]]:
    """Saved watchlists, or the starter groups if nothing has been saved yet."""
    if not Path(path).exists():
        return {name: list(tickers) for name, tickers in DEFAULT_WATCHLISTS.items()}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {name: list(tickers) for name, tickers in DEFAULT_WATCHLISTS.items()}
    groups = payload.get("watchlists", {}) if isinstance(payload, dict) else {}
    out: dict[str, list[str]] = {}
    for name, tickers in groups.items():
        valid, _ = clean_ticker_list(tickers if isinstance(tickers, list) else [])
        if str(name).strip():
            out[str(name).strip()] = valid
    return out


def save_watchlists(groups: dict[str, list[str]], path: Path = WATCHLIST_PATH) -> None:
    """Write atomically, so a crash never leaves a half-written file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "watchlists": {name: list(tickers) for name, tickers in groups.items()},
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


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
