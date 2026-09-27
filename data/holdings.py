"""
Holdings — the simple portfolio: ticker, number of shares, average price.

The older lot store (data/portfolio.py) keeps one row per purchase because the
retired Method A/B exit rules needed per-lot trailing stops. Nothing in the
current strategy sells, so the Deployment Desk only needs what you own and what
it cost on average. import_from_lots() blends existing lots into this format.

Stored in portfolio_data/holdings.json (gitignored). NOTE: Streamlit Community
Cloud has an ephemeral filesystem, so this file does not survive a redeploy
there. Run locally, or add a durable backend before relying on the cloud copy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from data.portfolio import aggregate_positions

REPO_ROOT = Path(__file__).resolve().parent.parent
HOLDINGS_DOC = "holdings"
HOLDING_COLUMNS = ["ticker", "shares", "avg_price"]


@dataclass
class Holding:
    ticker: str
    shares: float
    avg_price: float  # what the position averages out to per share, not today's price

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_price


def validate_holding(raw: dict) -> tuple[Optional[Holding], Optional[str]]:
    """Return (holding, None) or (None, error message). Never raises."""
    ticker = str(raw.get("ticker") or "").strip().upper()
    if not ticker:
        return None, "Ticker is required."
    try:
        shares = float(raw.get("shares"))
    except (TypeError, ValueError):
        return None, f"{ticker}: shares must be a number."
    if not shares > 0:
        return None, f"{ticker}: shares must be greater than 0."
    try:
        avg_price = float(raw.get("avg_price"))
    except (TypeError, ValueError):
        return None, f"{ticker}: average price must be a number."
    if not avg_price > 0:
        return None, f"{ticker}: average price must be greater than 0."
    return Holding(ticker=ticker, shares=shares, avg_price=avg_price), None


def frame_to_holdings(df: pd.DataFrame) -> tuple[list[Holding], list[str]]:
    """Convert the edited table back to holdings. Blank rows are ignored.

    The same ticker entered twice is merged into one position with a
    share-weighted average price, and a note is returned so the user sees it.
    """
    holdings: list[Holding] = []
    errors: list[str] = []
    if df is None or df.empty:
        return holdings, errors
    for _, row in df.iterrows():
        raw = {column: row.get(column) for column in HOLDING_COLUMNS}
        if not str(raw.get("ticker") or "").strip() or str(raw.get("ticker")) == "nan":
            continue
        holding, error = validate_holding(raw)
        if error:
            errors.append(error)
        elif holding:
            holdings.append(holding)
    return merge_duplicates(holdings, errors)


def merge_duplicates(holdings: list[Holding], notes: list[str]) -> tuple[list[Holding], list[str]]:
    merged: dict[str, Holding] = {}
    for holding in holdings:
        if holding.ticker in merged:
            existing = merged[holding.ticker]
            total_shares = existing.shares + holding.shares
            average = (existing.cost_basis + holding.cost_basis) / total_shares
            merged[holding.ticker] = Holding(holding.ticker, total_shares, average)
            notes.append(f"{holding.ticker}: entered twice, merged into one position.")
        else:
            merged[holding.ticker] = holding
    return list(merged.values()), notes


def holdings_to_frame(holdings: list[Holding]) -> pd.DataFrame:
    if not holdings:
        return pd.DataFrame(columns=HOLDING_COLUMNS)
    return pd.DataFrame([asdict(h) for h in holdings])[HOLDING_COLUMNS]


def load_holdings(store) -> list[Holding]:
    """This user's holdings (store: data.store.FileStore or SupabaseStore)."""
    payload = store.get(HOLDINGS_DOC) or {}
    holdings = []
    for record in payload.get("holdings", []):
        if isinstance(record, dict):
            holding, error = validate_holding(record)
            if holding and not error:
                holdings.append(holding)
    return holdings


def save_holdings(holdings: list[Holding], store) -> None:
    store.put(HOLDINGS_DOC, {"schema": 1, "updated_at": datetime.now().isoformat(timespec="seconds"),
                             "holdings": [asdict(h) for h in holdings]})


def import_from_lots(lots: list) -> list[Holding]:
    """Blend old per-purchase lots into one holding per ticker (share-weighted average)."""
    if not lots:
        return []
    positions = aggregate_positions(lots)
    by_ticker = positions.groupby("ticker", as_index=False).agg(
        shares=("shares", "sum"), cost_basis=("cost_basis", "sum")
    )
    return [
        Holding(row.ticker, float(row.shares), float(row.cost_basis / row.shares))
        for row in by_ticker.itertuples(index=False)
        if row.shares > 0
    ]


def value_holdings(holdings: list[Holding], prices: dict[str, float]) -> pd.DataFrame:
    """One row per holding with today's value, gain in $ and %, and weight."""
    rows = []
    for h in holdings:
        price = prices.get(h.ticker, float("nan"))
        value = h.shares * price
        rows.append({
            "Ticker": h.ticker,
            "Shares": h.shares,
            "Avg price": h.avg_price,
            "Price": price,
            "Cost": h.cost_basis,
            "Value": value,
            "Gain $": value - h.cost_basis,
            "Gain %": (price / h.avg_price - 1) * 100 if h.avg_price else float("nan"),
        })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    total = frame["Value"].sum(min_count=1)
    frame["Weight %"] = frame["Value"] / total * 100 if total else float("nan")
    return frame.sort_values("Value", ascending=False, na_position="last").reset_index(drop=True)


def hypothetical_drawdown(holdings: list[Holding], frames: dict[str, pd.DataFrame],
                          lookback: int = 252) -> dict:
    """Worst peak-to-trough drop if today's holdings had been held unchanged
    over the last `lookback` trading days, and the drop from the peak today."""
    series = {}
    for h in holdings:
        df = frames.get(h.ticker)
        if df is not None and not df.empty:
            series[h.ticker] = df["Close"].tail(lookback) * h.shares
    if not series:
        return {"max_drawdown_pct": float("nan"), "current_drawdown_pct": float("nan"), "days": 0}
    value = pd.DataFrame(series).ffill().dropna().sum(axis=1)
    if len(value) < 2:
        return {"max_drawdown_pct": float("nan"), "current_drawdown_pct": float("nan"), "days": len(value)}
    running_peak = value.cummax()
    drawdown = value / running_peak - 1
    return {
        "max_drawdown_pct": float(drawdown.min() * 100),
        "current_drawdown_pct": float(drawdown.iloc[-1] * 100),
        "days": int(len(value)),
    }
