"""
Telegram — the brief and alerts on your phone. One bot for everyone; each user
links their own chat, so each person only ever gets their own messages.

Linking (no chat IDs to copy by hand):
  1. the app makes a one-time code and a link  https://t.me/<bot>?start=<code>
  2. the user taps it and presses Start in Telegram (Telegram sends "/start <code>")
  3. the app reads the bot's recent messages (getUpdates), finds that code and
     saves the user's chat id in their settings

Plain `requests` against the Bot API; the token lives only in secrets
(TELEGRAM_BOT_TOKEN), never in the code.
"""

from __future__ import annotations

import os
import secrets as pysecrets
from typing import Optional

import requests

API = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE = 4000  # Telegram's limit is 4096 characters


def bot_token(secrets=None) -> str:
    token = ""
    if secrets is not None:
        try:
            token = str(secrets.get("TELEGRAM_BOT_TOKEN", "") or "")
        except Exception:  # noqa: BLE001
            token = ""
    return (token or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()


def _call(token: str, method: str, **params) -> dict:
    response = requests.post(API.format(token=token, method=method), json=params, timeout=20)
    data = response.json() if response.content else {}
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"Telegram {method} failed ({response.status_code})")
    return data["result"]


def bot_username(token: str) -> str:
    return _call(token, "getMe")["username"]


def new_link_code() -> str:
    """URL-safe one-time code for the /start deep link (letters and digits only)."""
    return pysecrets.token_hex(8)


def deep_link(username: str, code: str) -> str:
    return f"https://t.me/{username}?start={code}"


def find_chat_for_code(token: str, code: str) -> Optional[int]:
    """Chat id of whoever sent '/start <code>' to the bot recently, or None."""
    for update in _call(token, "getUpdates", allowed_updates=["message"]):
        message = update.get("message") or {}
        if (message.get("text") or "").strip() == f"/start {code}":
            return int(message["chat"]["id"])
    return None


def send(token: str, chat_id: int, text: str) -> None:
    """Send plain text (split if longer than Telegram allows)."""
    for start in range(0, max(len(text), 1), MAX_MESSAGE):
        _call(token, "sendMessage", chat_id=chat_id, text=text[start:start + MAX_MESSAGE],
              disable_web_page_preview=True)
