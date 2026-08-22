"""
Portfolio lot storage.

One row per purchase ("lot"), not per ticker — the Aggressive Dip rules allow
pyramiding, and every lot carries its own trailing stop anchored to the highest
close since *that* lot opened. Aggregating to a position view is easy; splitting
a blended position back into lots is not.

Storage is behind a two-method interface so the backend can change without
touching the UI:

    store = get_store()
    lots  = store.load()
    store.save(lots)

Backends
--------
JsonLotStore    default. Writes portfolio_data/lots.json next to the repo.
                Perfect locally. NOTE: Streamlit Community Cloud has an
                ephemeral filesystem — files written at runtime are not
                guaranteed to survive a reboot, so this backend WILL lose data
                once deployed there.
SheetsLotStore  not yet implemented. When you deploy, add a
                [connections.gsheets] block to secrets.toml and implement this
                class; get_store() will pick it up automatically and nothing
                else in the app needs to change.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Protocol

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "portfolio_data"
DEFAULT_PATH = DEFAULT_DATA_DIR / "lots.json"

LOT_COLUMNS = [
    "id",
    "ticker",
    "shares",
    "entry_price",
    "entry_date",
    "strategy",
    "notes",
]


@dataclass
class Lot:
    ticker: str
    shares: float
    entry_price: float
    entry_date: str  # ISO yyyy-mm-dd
    strategy: str = "tactical"
    notes: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def cost_basis(self) -> float:
        return self.shares * self.entry_price

    @property
    def entry_ts(self) -> pd.Timestamp:
        return pd.Timestamp(self.entry_date).normalize()


def _coerce_date(value) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    try:
        return pd.Timestamp(str(value)).strftime("%Y-%m-%d")
    except Exception:
        return None


def validate_lot(raw: dict) -> tuple[Optional[Lot], Optional[str]]:
    """Return (lot, None) or (None, error message). Never raises."""
    ticker = str(raw.get("ticker") or "").strip().upper()
    if not ticker:
        return None, "Ticker is required."

    try:
        shares = float(raw.get("shares") or 0)
    except (TypeError, ValueError):
        return None, f"{ticker}: shares must be a number."
    if shares <= 0:
        return None, f"{ticker}: shares must be greater than 0."

    try:
        entry_price = float(raw.get("entry_price") or 0)
    except (TypeError, ValueError):
        return None, f"{ticker}: entry price must be a number."
    if entry_price <= 0:
        return None, f"{ticker}: entry price must be greater than 0."

    entry_date = _coerce_date(raw.get("entry_date"))
    if not entry_date:
        return None, f"{ticker}: needs a valid entry date."
    if pd.Timestamp(entry_date).normalize() > pd.Timestamp.now().normalize():
        return None, f"{ticker}: entry date is in the future."

    strategy = str(raw.get("strategy") or "tactical").strip() or "tactical"
    notes = str(raw.get("notes") or "")
    lot_id = str(raw.get("id") or "").strip() or uuid.uuid4().hex[:12]

    return (
        Lot(
            ticker=ticker,
            shares=shares,
            entry_price=entry_price,
            entry_date=entry_date,
            strategy=strategy,
            notes=notes,
            id=lot_id,
        ),
        None,
    )


def lots_to_frame(lots: list[Lot]) -> pd.DataFrame:
    if not lots:
        return pd.DataFrame(columns=LOT_COLUMNS)
    df = pd.DataFrame([asdict(lot) for lot in lots])
    return df[LOT_COLUMNS]


def frame_to_lots(df: pd.DataFrame) -> tuple[list[Lot], list[str]]:
    """Convert an edited data_editor frame back to lots, collecting errors."""
    lots: list[Lot] = []
    errors: list[str] = []
    if df is None or df.empty:
        return lots, errors
    for _, row in df.iterrows():
        raw = {c: row.get(c) for c in LOT_COLUMNS if c in df.columns}
        # A fully blank row is just an unused spare in the editor grid.
        if not str(raw.get("ticker") or "").strip():
            continue
        lot, err = validate_lot(raw)
        if err:
            errors.append(err)
        elif lot:
            lots.append(lot)
    return lots, errors


class LotStore(Protocol):
    label: str

    def load(self) -> list[Lot]: ...
    def save(self, lots: list[Lot]) -> None: ...


class JsonLotStore:
    """Local JSON file. Durable on your machine, ephemeral on Community Cloud."""

    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self.label = f"local file ({self.path.name})"

    def load(self) -> list[Lot]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        records = payload.get("lots", payload) if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            return []
        lots = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            lot, err = validate_lot(rec)
            if lot and not err:
                lots.append(lot)
        return lots

    def save(self, lots: list[Lot]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": 1,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "lots": [asdict(lot) for lot in lots],
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic; never leaves a half-written file


def _sheets_configured() -> bool:
    """True once a [connections.gsheets] block exists in secrets.toml."""
    try:
        import streamlit as st

        return "gsheets" in st.secrets.get("connections", {})
    except Exception:
        return False


def get_store(path: Optional[Path] = None) -> LotStore:
    """
    Pick a backend. JSON today; Google Sheets the moment it is configured.

    Keeping this a factory means swapping storage for deployment is a config
    change, not a rewrite of the portfolio tab.
    """
    if _sheets_configured():
        try:
            from data.portfolio_sheets import SheetsLotStore  # optional module

            return SheetsLotStore()
        except ImportError:
            pass  # fall through to JSON until the backend is written
    return JsonLotStore(path or DEFAULT_PATH)


# ─────────────────────────────────────────────────────────────
# Aggregation helpers
# ─────────────────────────────────────────────────────────────
def aggregate_positions(lots: list[Lot]) -> pd.DataFrame:
    """Blend lots into one row per (ticker, strategy) with a weighted entry."""
    if not lots:
        return pd.DataFrame(
            columns=["ticker", "strategy", "shares", "avg_entry", "cost_basis", "lots"]
        )
    df = lots_to_frame(lots).copy()
    df["cost_basis"] = df["shares"] * df["entry_price"]
    grouped = (
        df.groupby(["ticker", "strategy"], as_index=False)
        .agg(shares=("shares", "sum"), cost_basis=("cost_basis", "sum"), lots=("id", "count"))
    )
    grouped["avg_entry"] = grouped["cost_basis"] / grouped["shares"]
    return grouped[["ticker", "strategy", "shares", "avg_entry", "cost_basis", "lots"]]
