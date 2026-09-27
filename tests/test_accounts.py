"""
Offline checks for accounts, storage isolation and Telegram linking — the
security-relevant parts of the multi-user setup. No network: requests is faked.

Run:  python tests/test_accounts.py
"""

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import data.store as store_mod  # noqa: E402
import data.telegram as tg  # noqa: E402
from data.accounts import is_allowed, load_invites, load_settings, save_invites  # noqa: E402
from data.store import FileStore, SupabaseStore, shared_store, user_store  # noqa: E402

fails = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra else ""))
    if not cond:
        fails.append(name)


# ── 1. Supabase store: every read/write is scoped to its owner ──────────────
calls = []


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self._payload, self.status_code, self.content = payload, status, b"x"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def fake_get(url, params=None, headers=None, timeout=None):
    calls.append(("GET", url, params, headers))
    return FakeResponse([{"payload": {"owner_was": params.get("owner")}}])


def fake_post(url, params=None, headers=None, data=None, timeout=None, json=None):
    calls.append(("POST", url, params, headers, data))
    return FakeResponse(None)


store_mod.requests.get, store_mod.requests.post = fake_get, fake_post
alice = SupabaseStore("https://x.supabase.co", "service-key", owner="Alice@Example.com")
bob = SupabaseStore("https://x.supabase.co", "service-key", owner="bob@example.com")
got = alice.get("holdings")
check("reads are filtered to the owner (lower-cased email)", calls[-1][2]["owner"] == "eq.alice@example.com"
      and got == {"owner_was": "eq.alice@example.com"})
bob.put("holdings", {"holdings": []})
body = json.loads(calls[-1][4])
check("writes are stamped with the owner and upsert on (owner, doc)",
      body[0]["owner"] == "bob@example.com" and calls[-1][2] == {"on_conflict": "owner,doc"}
      and "merge-duplicates" in calls[-1][3]["Prefer"])
check("the service key is sent only as auth headers", calls[-1][3]["apikey"] == "service-key"
      and "service-key" not in calls[-1][1])

secrets = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "k"}
a, b = user_store("a@x.com", secrets), user_store("b@x.com", secrets)
check("two signed-in users get two different owners", a.owner != b.owner and a.owner == "a@x.com")
check("the shared store is its own owner", shared_store(secrets).owner == "_shared")
check("without a database, the local file store is used (single-user mode)",
      isinstance(user_store("a@x.com", {}), FileStore))

# ── 2. invite rules ─────────────────────────────────────────────────────────
shared = FileStore(pathlib.Path(tempfile.mkdtemp()))
save_invites(["Friend@Mail.com", "not-an-email", "friend@mail.com"], shared)
check("invites are lower-cased, de-duplicated, and junk dropped", load_invites(shared) == ["friend@mail.com"])
sec = {"ADMIN_EMAILS": ["owner@mail.com"]}
check("admin is allowed", is_allowed("OWNER@mail.com", sec, shared))
check("invited friend is allowed", is_allowed("friend@mail.com", sec, shared))
check("anyone else is refused", not is_allowed("stranger@mail.com", sec, shared))
check("empty email is refused", not is_allowed("", sec, shared))
check("settings default to every alert on", load_settings(FileStore(pathlib.Path(tempfile.mkdtemp())))["alerts"]
      == {"morning": True, "afternoon": True, "crossings": True, "insider": True})

# ── 3. Telegram linking ─────────────────────────────────────────────────────
updates = [{"message": {"text": "/start wrongcode", "chat": {"id": 1}}},
           {"message": {"text": "/start abc123", "chat": {"id": 42}}}]
tg._call = lambda token, method, **p: updates if method == "getUpdates" else {"username": "desk_bot"}
check("finds the chat that pressed Start with this code", tg.find_chat_for_code("t", "abc123") == 42)
check("ignores other codes", tg.find_chat_for_code("t", "nope") is None)
check("deep link format", tg.deep_link("desk_bot", "abc123") == "https://t.me/desk_bot?start=abc123")
code = tg.new_link_code()
check("link codes are 16 hex characters (URL-safe)", len(code) == 16 and all(c in "0123456789abcdef" for c in code))

# ── 4. the app refuses to run signed-in users without a database ────────────
from streamlit.testing.v1 import AppTest  # noqa: E402

app = AppTest.from_file(str(pathlib.Path(__file__).resolve().parent.parent / "appV2.py"), default_timeout=120)
app.secrets["auth"] = {"redirect_uri": "http://localhost:8501/oauth2callback", "cookie_secret": "x",
                       "client_id": "x", "client_secret": "x",
                       "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration"}
app.run()
check("sign-in on + no database -> refuses to start", any("Refusing to start" in e.value for e in app.error),
      str([e.value[:60] for e in app.error]))

print()
print("ALL CHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
