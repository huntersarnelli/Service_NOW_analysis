"""
Accounts: who may use the Desk, and each user's settings.

  Sign-in       Google, via Streamlit's built-in st.login (configured in secrets as
                [auth]). Google handles passwords and 2-step verification; this app
                never sees or stores a password.
  Invite-only   an email may enter only if it is an admin (ADMIN_EMAILS in secrets)
                or on the invite list (shared doc "invites", edited by an admin in
                the app). Unverified Google emails are refused.
  Settings      per-user doc "settings": Telegram chat, alert switches.

Local mode (no [auth] in secrets) is single-user and skips all of this.
"""

from __future__ import annotations

import re
from datetime import datetime

INVITES_DOC = "invites"
SETTINGS_DOC = "settings"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_ALERTS = {"morning": True, "afternoon": True, "crossings": True, "insider": True}


def auth_configured(secrets) -> bool:
    try:
        return "auth" in secrets
    except Exception:  # noqa: BLE001 -- no secrets file at all
        return False


def admin_emails(secrets) -> set[str]:
    try:
        raw = secrets.get("ADMIN_EMAILS", [])
    except Exception:  # noqa: BLE001
        raw = []
    if isinstance(raw, str):
        raw = raw.split(",")
    return {str(e).strip().lower() for e in raw if str(e).strip()}


def load_invites(shared) -> list[str]:
    return list((shared.get(INVITES_DOC) or {}).get("emails", []))


def save_invites(emails: list[str], shared) -> None:
    cleaned = sorted({e.strip().lower() for e in emails if EMAIL_RE.match(e.strip())})
    shared.put(INVITES_DOC, {"updated_at": datetime.now().isoformat(timespec="seconds"), "emails": cleaned})


def is_allowed(email: str, secrets, shared) -> bool:
    email = (email or "").strip().lower()
    return bool(email) and (email in admin_emails(secrets) or email in load_invites(shared))


def load_settings(store) -> dict:
    settings = store.get(SETTINGS_DOC) or {}
    settings.setdefault("alerts", dict(DEFAULT_ALERTS))
    for key, value in DEFAULT_ALERTS.items():
        settings["alerts"].setdefault(key, value)
    return settings


def save_settings(settings: dict, store) -> None:
    store.put(SETTINGS_DOC, {**settings, "updated_at": datetime.now().isoformat(timespec="seconds")})
