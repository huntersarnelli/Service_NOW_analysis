"""
Storage for everything a user saves: holdings, watchlists, journal, settings — plus
shared docs (insider paper trades, buy-zone log, the invite list).

One tiny interface, two backends:

    store.get("holdings")  -> dict | None
    store.put("holdings", {...})

  FileStore       JSON files in a folder. Local single-user mode (portfolio_data/),
                  so everything saved before keeps working unchanged.
  SupabaseStore   one row per (owner, doc) in a Supabase table, via its REST API
                  (plain `requests`). Permanent storage for the cloud app; every
                  signed-in user has their own owner key (their email).

SECURITY: there is deliberately NO module-level "current user". Streamlit serves
every visitor from one Python process, so a global would leak one user's data to
another. Every load/save takes its store explicitly; the app keeps each visitor's
store in their own st.session_state.

Supabase table (created once, see docs/DEPLOY.md):

    create table user_docs (owner text not null, doc text not null,
      payload jsonb not null, updated_at timestamptz default now(),
      primary key (owner, doc));
    alter table user_docs enable row level security;   -- no public access at all
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = REPO_ROOT / "portfolio_data"
SHARED_OWNER = "_shared"


class FileStore:
    """Each doc is <root>/<doc>.json, written atomically."""

    def __init__(self, root: Path = LOCAL_DIR):
        self.root = Path(root)

    def get(self, doc: str) -> Optional[dict]:
        path = self.root / f"{doc}.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return payload if isinstance(payload, dict) else None

    def put(self, doc: str, payload: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{doc}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, path)

    def owners_with(self, doc: str) -> list[str]:
        return ["local"] if (self.root / f"{doc}.json").exists() else []


class SupabaseStore:
    """Rows in the `user_docs` table, scoped to one owner (a user's email, or _shared)."""

    TABLE = "user_docs"

    def __init__(self, url: str, key: str, owner: str, timeout: int = 15):
        # Accept the project URL either bare or as Supabase's "Data API URL" (…/rest/v1).
        self.url = url.strip().rstrip("/").removesuffix("/rest/v1").rstrip("/")
        self.owner = owner.strip().lower()
        self.timeout = timeout
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def get(self, doc: str) -> Optional[dict]:
        response = requests.get(
            f"{self.url}/rest/v1/{self.TABLE}",
            params={"owner": f"eq.{self.owner}", "doc": f"eq.{doc}", "select": "payload"},
            headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        rows = response.json()
        return rows[0]["payload"] if rows else None

    def put(self, doc: str, payload: dict) -> None:
        body = [{"owner": self.owner, "doc": doc, "payload": payload,
                 "updated_at": datetime.now(timezone.utc).isoformat()}]
        response = requests.post(
            f"{self.url}/rest/v1/{self.TABLE}", params={"on_conflict": "owner,doc"},
            headers={**self.headers, "Prefer": "resolution=merge-duplicates,return=minimal"},
            data=json.dumps(body, default=str), timeout=self.timeout)
        response.raise_for_status()

    def owners_with(self, doc: str) -> list[str]:
        """Every user (not _shared) that has saved this doc — the scheduler uses it to find users."""
        response = requests.get(f"{self.url}/rest/v1/{self.TABLE}",
                                params={"doc": f"eq.{doc}", "select": "owner"},
                                headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        return [r["owner"] for r in response.json() if not r["owner"].startswith("_")]


def supabase_settings(secrets=None) -> Optional[tuple[str, str]]:
    """(url, service key) from Streamlit secrets or environment variables, or None."""
    url = key = ""
    if secrets is not None:
        try:
            url = str(secrets.get("SUPABASE_URL", "") or "")
            key = str(secrets.get("SUPABASE_SERVICE_KEY", "") or "")
        except Exception:  # noqa: BLE001 -- no secrets file
            pass
    url = url or os.environ.get("SUPABASE_URL", "")
    key = key or os.environ.get("SUPABASE_SERVICE_KEY", "")
    return (url, key) if url and key else None


def user_store(email: Optional[str], secrets=None):
    """A user's own store: Supabase (owner = email) if configured, else the local folder."""
    settings = supabase_settings(secrets)
    if settings and email:
        return SupabaseStore(*settings, owner=email)
    return FileStore(LOCAL_DIR)


def shared_store(secrets=None):
    """The store every user shares (insider paper trades, buy-zone log, invite list)."""
    settings = supabase_settings(secrets)
    if settings:
        return SupabaseStore(*settings, owner=SHARED_OWNER)
    return FileStore(LOCAL_DIR)
