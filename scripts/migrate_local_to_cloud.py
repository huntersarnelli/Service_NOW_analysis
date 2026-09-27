"""
One-time copy of your local Desk data (portfolio_data/*.json) into your cloud account,
so you don't retype anything after moving to Streamlit Cloud.

    set SUPABASE_URL=...  &  set SUPABASE_SERVICE_KEY=...      (PowerShell: $env:SUPABASE_URL="...")
    python scripts/migrate_local_to_cloud.py you@gmail.com [--dry-run]

Copies to YOUR account: watchlists, holdings (or your old app.py lots, averaged per ticker,
if you never saved holdings), journal, settings.
Copies to the SHARED space: insider paper trades and the buy-zone log.
Never overwrites a cloud doc that already has data unless --overwrite is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.holdings import import_from_lots, save_holdings  # noqa: E402
from data.portfolio import get_store  # noqa: E402
from data.store import FileStore, shared_store, supabase_settings, user_store  # noqa: E402

USER_DOCS = ["watchlists", "holdings", "journal", "settings"]
SHARED_DOCS = ["paper_trades", "buy_zone_log"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("email")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if supabase_settings() is None:
        print("Set SUPABASE_URL and SUPABASE_SERVICE_KEY first (see docs/DEPLOY.md).")
        return 1

    local = FileStore()
    cloud_user, cloud_shared = user_store(args.email), shared_store()
    for doc in USER_DOCS + SHARED_DOCS:
        target = cloud_user if doc in USER_DOCS else cloud_shared
        payload = local.get(doc)
        if payload is None:
            print(f"  {doc}: nothing saved locally")
            continue
        if target.get(doc) and not args.overwrite:
            print(f"  {doc}: already in the cloud, skipped (use --overwrite to replace)")
            continue
        print(f"  {doc}: {'would copy' if args.dry_run else 'copied'}")
        if not args.dry_run:
            target.put(doc, payload)

    if local.get("holdings") is None and cloud_user.get("holdings") is None:
        lots = get_store().load()
        if lots:
            holdings = import_from_lots(lots)
            print(f"  holdings: {'would import' if args.dry_run else 'imported'} {len(holdings)} from your old lots")
            if not args.dry_run:
                save_holdings(holdings, cloud_user)
    print("Done." if not args.dry_run else "Dry run only — nothing written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
