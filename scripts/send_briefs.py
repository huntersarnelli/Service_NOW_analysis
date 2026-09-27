"""
Scheduled briefs and alerts, per user, over Telegram. Run by GitHub Actions
(.github/workflows/desk-alerts.yml) — no one's PC needs to be on.

    python scripts/send_briefs.py morning     [--at 08:30] [--dry-run] [--force]
    python scripts/send_briefs.py afternoon   [--at 15:30]
    python scripts/send_briefs.py crossings   (every 30 min in market hours; only sends news)
    python scripts/send_briefs.py insider     [--at 18:30]  (SEC scan; logs paper trades)

--at HH:MM   run only within 45 minutes of that Eastern time (the workflow fires two UTC
             times per slot to cover daylight saving; the wrong one exits quietly)
--dry-run    print the messages instead of sending them
--force      ignore the weekend / time window / already-sent-today checks

Users: every account with Telegram connected and that alert switched on (Settings in the
app). Each user's brief uses only their own lists and holdings. Local mode (no Supabase
settings in the environment) sends to the single local user.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.accounts import load_settings, save_settings  # noqa: E402
from data.brief import brief_text, build_brief, watch_rows  # noqa: E402
from data.holdings import load_holdings  # noqa: E402
from data.insider_feed import scan as insider_scan  # noqa: E402
from data.market import get_data_batch, get_earnings_batch  # noqa: E402
from data.paper_trades import add_signals, load_trades  # noqa: E402
from data.premarket import FUTURES, fetch_moves  # noqa: E402
from data.screen import EVIDENCE, SCREENS, SECTORS, UNIVERSE_V2, run_screen  # noqa: E402
from data.store import FileStore, SupabaseStore, shared_store, supabase_settings, user_store  # noqa: E402
from data.telegram import bot_token, send  # noqa: E402
from data.watchlists import all_watchlist_tickers, load_watchlists  # noqa: E402

SPEC = SCREENS[EVIDENCE]
BENCHMARK = "SPY"
HISTORY_DAYS = 420
WINDOW_MINUTES = 45


def eastern_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    except Exception:  # noqa: BLE001 -- no tz database (e.g. bare Windows): assume UTC-4
        return datetime.utcnow() - timedelta(hours=4)


def in_window(now: datetime, at: str | None) -> bool:
    if not at:
        return True
    hour, minute = (int(x) for x in at.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return abs((now - target).total_seconds()) <= WINDOW_MINUTES * 60


def market_open(now: datetime) -> bool:
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


def users() -> list[tuple[str, object]]:
    """(owner, store) for every user who has saved settings."""
    settings = supabase_settings()
    if settings:
        owners = SupabaseStore(*settings, owner="_").owners_with("settings")
        return [(owner, user_store(owner)) for owner in owners]
    return [("local", FileStore())]


def market_data(all_groups: list[dict], all_holdings: list[list]) -> tuple[dict, dict, list[str]]:
    personal = []
    for groups, holdings in zip(all_groups, all_holdings):
        personal += all_watchlist_tickers(groups) + [h.ticker for h in holdings]
    screened = list(dict.fromkeys(UNIVERSE_V2 + personal))
    frames = get_data_batch(list(dict.fromkeys(screened + [BENCHMARK])), days=HISTORY_DAYS)
    earnings = get_earnings_batch(screened)
    return frames, earnings, screened


def screen_user(groups, holdings, frames, earnings):
    names = list(dict.fromkeys(UNIVERSE_V2 + all_watchlist_tickers(groups) + [h.ticker for h in holdings]))
    subset = {t: frames[t] for t in names + [BENCHMARK] if t in frames}
    return run_screen(subset, earnings, SPEC, breadth_universe=UNIVERSE_V2)


def deliver(token, settings, text, dry_run, owner) -> None:
    if dry_run:
        print(f"\n===== to {owner} =====\n{text}")
    else:
        send(token, settings["telegram_chat_id"], text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["morning", "afternoon", "crossings", "insider"])
    parser.add_argument("--at")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    now = eastern_now()
    today = now.date().isoformat()
    if not args.force:
        if now.weekday() >= 5:
            print("Weekend — nothing to send.")
            return 0
        if not in_window(now, args.at):
            print(f"Outside the {args.at} ET window (now {now:%H:%M} ET) — exiting.")
            return 0
        if args.mode == "crossings" and not market_open(now):
            print("Market closed — no crossing checks.")
            return 0

    token = bot_token()
    if not token and not args.dry_run:
        print("TELEGRAM_BOT_TOKEN is not set.")
        return 1

    recipients = []
    for owner, store in users():
        settings = load_settings(store)
        if not settings.get("telegram_chat_id") and not args.dry_run:
            continue
        if not settings["alerts"].get(args.mode, True):
            continue
        if args.mode in ("morning", "afternoon", "insider") and not args.force \
                and settings.get("last_sent", {}).get(args.mode) == today:
            continue
        recipients.append((owner, store, settings, load_watchlists(store), load_holdings(store)))
    if not recipients:
        print("No recipients for this alert.")
        return 0

    frames, earnings, screened = market_data([r[3] for r in recipients], [r[4] for r in recipients])
    if BENCHMARK not in frames:
        print("No market data (Yahoo throttling?) — try again next run.")
        return 1
    shared = shared_store()

    if args.mode == "insider":
        found = insider_scan(48, set(screened), SECTORS, frames, pd.DatetimeIndex(frames[BENCHMARK].index))
        added = add_signals(found, shared)
        passing = found[found["passes"]] if not found.empty else found
        print(f"Insider scan: {len(found)} purchase filings, {added} new paper trades.")

    mine_all = list(dict.fromkeys(t for r in recipients for t in all_watchlist_tickers(r[3]) + [h.ticker for h in r[4]]))
    premarket = fetch_moves(mine_all + list(FUTURES)) if args.mode in ("morning", "afternoon") else pd.DataFrame()
    pending = [t for t in load_trades(shared) if t.status == "pending"]

    for owner, store, settings, groups, holdings in recipients:
        result = screen_user(groups, holdings, frames, earnings)
        text = None
        if args.mode in ("morning", "afternoon"):
            brief = build_brief(result, groups, holdings, premarket, pending)
            text = brief_text(brief, f"{now:%a %b %d, %I:%M %p} ET")
        elif args.mode == "crossings":
            alerted = settings.get("alerted", {}).get(today, [])
            new = [w for w in watch_rows(result, groups) if w["state"] == "crossed" and w["ticker"] not in alerted]
            if new:
                text = "\n".join(f"🎯 {w['ticker']} just crossed its dip price (${w['dip_price']:,.2f}); now "
                                 f"${w['price']:,.2f}. If it closes here it's {w['would_be']}." for w in new)
                settings["alerted"] = {today: alerted + [w["ticker"] for w in new]}
        elif args.mode == "insider" and not passing.empty:
            mine = set(all_watchlist_tickers(groups)) | {h.ticker for h in holdings}
            lines = [f"⚡ {r.ticker}: {r.insider} ({r.role}) bought ${r.value_usd:,.0f}. Paper-buy at the "
                     f"{r.entry_type} on {r.entry_date}" + (" (on your lists)" if r.ticker in mine else "")
                     for r in passing.itertuples()]
            text = "Insider buys tonight (paper trades, tested in tech):\n" + "\n".join(lines)
        if text:
            deliver(token, settings, text, args.dry_run, owner)
        if not args.dry_run:
            if args.mode in ("morning", "afternoon", "insider"):
                settings.setdefault("last_sent", {})[args.mode] = today
            save_settings(settings, store)
    print(f"{args.mode}: processed {len(recipients)} user(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
