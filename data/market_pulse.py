"""
Market pulse — "where is the market looking?"

Ranks sector and theme funds by how much they have beaten (or lagged) SPY over
1, 3, 6 and 12 months. This is INFORMATION ONLY: momentum as a holding rule was
tested (docs/05_MOMENTUM_STUDY.md, pre-registered) and failed narrowly (t 1.80),
and momentum as a gate on dips failed earlier (DEAD_ENDS #3). Nothing here is a
buy signal.
"""

from __future__ import annotations

import pandas as pd

SECTOR_FUNDS: dict[str, str] = {
    "XLK": "Technology",
    "XLC": "Communication services",
    "XLY": "Consumer discretionary",
    "XLP": "Consumer staples",
    "XLE": "Energy",
    "XLU": "Utilities",
    "XLF": "Financials",
    "XLV": "Health care",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLRE": "Real estate",
}
THEME_FUNDS: dict[str, str] = {
    "SMH": "Semiconductors",
    "IGV": "Software",
    "QQQ": "Nasdaq-100 (big tech)",
}
WINDOWS = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}


def pulse_tickers() -> list[str]:
    return list(SECTOR_FUNDS) + list(THEME_FUNDS)


def window_return(close: pd.Series, bars: int) -> float:
    """Return over the last `bars` trading days, or NaN if history is too short."""
    close = close.dropna()
    if len(close) <= bars:
        return float("nan")
    return float(close.iloc[-1] / close.iloc[-1 - bars] - 1)


def relative_strength_table(frames: dict[str, pd.DataFrame], benchmark: str = "SPY") -> pd.DataFrame:
    """One row per fund: return minus SPY over each window (percentage points).

    Sorted by the 3-month figure, the middle of the horizons shown.
    """
    spy = frames.get(benchmark)
    if spy is None or spy.empty:
        return pd.DataFrame()
    labels = {**SECTOR_FUNDS, **THEME_FUNDS}
    rows = []
    for ticker, label in labels.items():
        df = frames.get(ticker)
        if df is None or df.empty:
            continue
        row = {"Fund": ticker, "What it holds": label,
               "Kind": "Sector" if ticker in SECTOR_FUNDS else "Theme"}
        for name, bars in WINDOWS.items():
            fund = window_return(df["Close"], bars)
            market = window_return(spy["Close"], bars)
            row[f"{name} vs SPY"] = (fund - market) * 100
        rows.append(row)
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    return table.sort_values("3M vs SPY", ascending=False, na_position="last").reset_index(drop=True)


def leaders_and_laggards(table: pd.DataFrame, column: str = "3M vs SPY", n: int = 3) -> tuple[list[str], list[str]]:
    """Top-n and bottom-n sector names by the given column (sectors only, not themes)."""
    sectors = table[table["Kind"] == "Sector"].dropna(subset=[column])
    if sectors.empty:
        return [], []
    ranked = sectors.sort_values(column, ascending=False)
    leaders = ranked.head(n)["What it holds"].tolist()
    laggards = ranked.tail(n)["What it holds"].tolist()[::-1]
    return leaders, laggards
