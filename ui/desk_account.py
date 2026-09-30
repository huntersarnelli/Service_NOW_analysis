"""
Account screens: the sign-in page, the not-invited page, and (in the More tab)
📱 Phone & alerts — add to iPhone, connect Telegram, alert switches, test message —
plus 👥 Friends for admins (the invite list).
"""

from __future__ import annotations

from urllib.parse import quote, urlparse

import streamlit as st

from data.accounts import (DEFAULT_ALERTS, EMAIL_RE, admin_emails, load_invites, load_settings,
                           save_invites, save_settings)
from data.telegram import bot_token, bot_username, deep_link, find_chat_for_code, new_link_code, send
from ui.desk_common import section, shared_store, user_store

ALERT_LABELS = {
    "morning": "☀️ Morning brief (~8:30am ET, trading days)",
    "afternoon": "🕒 Afternoon brief (~3:30pm ET): what triggers if it closes there",
    "crossings": "🎯 Ping me when a ⭐ Want-to-buy stock crosses its dip price",
    "insider": "⚡ Insider buys found in the evening scan (paper trades)",
}


def provider_logout_url(secrets) -> str | None:
    """Auth0 keeps its own login session in the browser, so after a sign-in with the wrong
    account every new sign-in silently reuses it. This URL clears that session and returns
    to the Desk. (None if the provider isn't Auth0.)"""
    try:
        auth = secrets["auth"]
        host = urlparse(str(auth["server_metadata_url"])).netloc
        back = urlparse(str(auth["redirect_uri"]))
    except Exception:  # noqa: BLE001
        return None
    if not host.endswith(".auth0.com"):
        return None
    return_to = quote(f"{back.scheme}://{back.netloc}", safe="")
    return f"https://{host}/v2/logout?client_id={quote(str(auth['client_id']))}&returnTo={return_to}"


def render_sign_in(secrets=None) -> None:
    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        st.markdown("## 🎯 Deployment Desk")
        st.write("A private, invite-only dashboard: your watchlists, dip alerts, the morning brief, and a "
                 "track record of your calls.")
        if st.button("Sign in with Google", type="primary", width="stretch"):
            st.login()
        st.caption("Sign-in is handled by Auth0, so this app never sees your password. New accounts must "
                   "verify their email first. Research tool, not investment advice.")
        reset = provider_logout_url(secrets) if secrets is not None else None
        if reset:
            st.link_button("Use a different account", reset, width="stretch")


def render_not_invited(email: str, secrets=None) -> None:
    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        st.markdown("## 🎯 Deployment Desk")
        st.warning(f"**{email}** isn't on the invite list. If that's the wrong account, sign out and "
                   "sign in with the right one. Otherwise ask the owner to add you.")
        if st.button("Sign out and use a different account", type="primary", width="stretch"):
            st.logout()


def render_account(secrets) -> None:
    email = st.session_state.get("signed_in_email")
    store = user_store()
    settings = load_settings(store)

    section("📱 Phone & alerts")
    if email:
        c1, c2 = st.columns([3, 1])
        c1.caption(f"Signed in as **{email}**")
        if c2.button("Sign out", key="sign_out", width="stretch"):
            st.logout()
    with st.expander("📲 Put the Desk on your iPhone Home Screen"):
        st.markdown("1. Open this page in **Safari** on your iPhone.\n"
                    "2. Tap **Share** (the square with the arrow).\n"
                    "3. Tap **Add to Home Screen**, then **Add**.\n\n"
                    "It opens like an app. If it's been idle it may take ~30 seconds to wake up.")

    token = bot_token(secrets)
    if not token:
        st.info("Telegram alerts aren't set up yet (the owner adds TELEGRAM_BOT_TOKEN to the app's secrets).")
    elif settings.get("telegram_chat_id"):
        render_connected(token, settings, store)
    else:
        render_connect(token, settings, store)

    if email and email in admin_emails(secrets):
        render_friends()


def render_connect(token, settings, store) -> None:
    st.markdown("**💬 Get the brief and alerts on Telegram**")
    if not settings.get("telegram_link_code"):
        if st.button("Connect Telegram", type="primary", key="tg_start"):
            settings["telegram_link_code"] = new_link_code()
            save_settings(settings, store)
            st.rerun()
        return
    try:
        username = bot_username(token)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Couldn't reach the Telegram bot: {exc}")
        return
    st.markdown("1. Tap the button below (it opens Telegram).\n2. Press **Start** in the chat.\n"
                "3. Come back and press **I pressed Start**.")
    c1, c2 = st.columns(2)
    c1.link_button("Open Telegram", deep_link(username, settings["telegram_link_code"]), width="stretch")
    if c2.button("I pressed Start", key="tg_check", width="stretch"):
        chat_id = find_chat_for_code(token, settings["telegram_link_code"])
        if chat_id is None:
            st.warning("Not seen yet. Make sure you pressed Start in the chat the button opened, then try again.")
        else:
            settings["telegram_chat_id"] = chat_id
            settings.pop("telegram_link_code", None)
            save_settings(settings, store)
            send(token, chat_id, "✅ Connected to the Deployment Desk. Your briefs and alerts will arrive here.")
            st.rerun()


def render_connected(token, settings, store) -> None:
    st.success("💬 Telegram connected")
    changed = False
    for key, text in ALERT_LABELS.items():
        value = st.toggle(text, value=settings["alerts"].get(key, DEFAULT_ALERTS[key]), key=f"alert_{key}")
        if value != settings["alerts"].get(key):
            settings["alerts"][key] = value
            changed = True
    if changed:
        save_settings(settings, store)
    c1, c2 = st.columns(2)
    if c1.button("Send a test message", key="tg_test", width="stretch"):
        try:
            send(token, settings["telegram_chat_id"], "👋 Test from the Deployment Desk. Alerts will look like this.")
            st.toast("Sent — check Telegram.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Telegram said: {exc}")
    if c2.button("Disconnect Telegram", key="tg_disconnect", width="stretch"):
        settings.pop("telegram_chat_id", None)
        save_settings(settings, store)
        st.rerun()


def render_friends() -> None:
    section("👥 Friends (only you see this)")
    invites = load_invites(shared_store())
    st.caption("Only emails on this list can sign in (plus you). Each friend gets their own private "
               "watchlists, portfolio, journal and alerts; nobody sees anyone else's.")
    edited = st.multiselect("Invited emails", invites, default=invites, key="invite_list",
                            accept_new_options=True, placeholder="Type an email and press Enter…",
                            label_visibility="collapsed")
    cleaned = sorted({e.strip().lower() for e in edited})
    bad = [e for e in cleaned if not EMAIL_RE.match(e)]
    if bad:
        st.error("Not an email address: " + ", ".join(bad) + ". Remove it to save the list.")
    elif cleaned != sorted(invites):
        save_invites(cleaned, shared_store())
        st.toast("Invite list saved.")
        st.rerun()
