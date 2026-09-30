# Deploying the Deployment Desk — phone, Telegram, friends

**Result:** the Desk runs in the cloud 24/7, you and invited friends sign in (Auth0) on
any phone or PC, everyone's data is private and permanent, and briefs/alerts arrive on
Telegram with no PC switched on. **Cost: $0** (all free tiers).

| Piece | Service | What it does |
|---|---|---|
| App | Streamlit Community Cloud | Hosts `appV2.py`; you add it to your iPhone Home Screen |
| Sign-in | Auth0 (via Streamlit's `st.login`) | Free, no card; passwords and email verification are Auth0's; the app never sees a password |
| Data | Supabase (Postgres) | Each user's holdings, lists, journal, settings — permanent; app restarts don't touch it |
| Alerts | Telegram bot | One bot; each user links their own chat and only gets their own messages |
| Schedule | GitHub Actions | 8:30am + 3:30pm ET briefs, dip-price crossings every 30 min, 6:30pm insider scan |

Allow ~30–40 minutes the first time. Do the steps in order.

---

## 1. Telegram bot (2 min)

1. In Telegram, open **@BotFather** → send `/newbot`.
2. Name it (e.g. *Deployment Desk*), then a username ending in `bot` (e.g. `hunter_desk_bot`).
3. Copy the **token** it replies with (`123456789:AA…`). Treat it like a password.

## 2. Supabase database (8 min)

1. Go to **supabase.com** → *Start your project* → sign in with GitHub → **New project**
   (any name, a strong database password you save somewhere, region *East US*).
2. When it's ready: left menu **SQL Editor** → *New query* → paste and **Run**:

   ```sql
   create table user_docs (
     owner text not null,
     doc text not null,
     payload jsonb not null,
     updated_at timestamptz default now(),
     primary key (owner, doc)
   );
   alter table user_docs enable row level security;  -- no policies = no public access at all
   ```
   With row-level security on and no policies, the table is unreachable except with the
   server-side service key, which only the app and the scheduler hold.
3. **Project Settings → API** (or *Data API*): copy the **Project URL** and the
   **service_role** key (the secret one, *not* `anon`). Never paste the service key anywhere
   except the secrets boxes below.

Note: free projects pause after about a week with no activity; the daily briefs keep it
active. A paused project keeps its data — press *Restore* in the dashboard if it ever pauses.

## 3. Sign-in with Auth0 (10 min, free, no card)

We use **Auth0** (by Okta) instead of a Google Cloud project: free up to 25,000 users,
no card at signup, and Streamlit's `st.login` supports it directly.

1. **auth0.com** → *Sign up* → region **US**. Your tenant domain looks like `dev-xxxx.us.auth0.com`.
2. **Applications → Applications → + Create Application** → name *Deployment Desk*, type
   **Regular Web Applications** → *Create* (skip the quickstart).
3. **Settings** tab → *Application URIs*:
   - **Allowed Callback URLs:** `http://localhost:8501/oauth2callback` (add the cloud one in step 5)
   - **Allowed Logout URLs:** `http://localhost:8501` (add the cloud one in step 5)
   → **Save**.
4. **Connections** tab: keep **Username-Password-Authentication** on (and *google-oauth2* if you
   like). New email/password users must click Auth0's verification email; the Desk refuses
   unverified emails.
5. Copy **Domain**, **Client ID**, **Client Secret** for the `[auth]` block in step 4.

## 4. Try it on your PC first (5 min)

1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (keep your
   `ALPHA_VANTAGE_API_KEY` line) and fill in: `TELEGRAM_BOT_TOKEN`, `SUPABASE_URL`,
   `SUPABASE_SERVICE_KEY`, `ADMIN_EMAILS = ["your@email.com"]`, and — **last in the file** — the
   `[auth]` block (see `.streamlit/secrets.toml.example`): `redirect_uri =
   "http://localhost:8501/oauth2callback"`, the Auth0 client id/secret, `server_metadata_url =
   "https://YOUR-DOMAIN/.well-known/openid-configuration"`, `client_kwargs = { prompt = "login" }`
   (always show the sign-in screen, so a wrong account is never silently reused) and a random
   `cookie_secret` (never share it):
   ```
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
2. Copy your existing lists/portfolio into your cloud account (PowerShell):
   ```powershell
   $env:SUPABASE_URL="https://xxxx.supabase.co"; $env:SUPABASE_SERVICE_KEY="eyJ..."
   python scripts/migrate_local_to_cloud.py your@gmail.com --dry-run   # shows what it will copy
   python scripts/migrate_local_to_cloud.py your@gmail.com
   ```
3. `streamlit run appV2.py` → **Sign in** → Auth0 → your lists should all be there. Signed in
   with the wrong account? Use **Sign out and use a different account** (or *Use a different
   account* on the sign-in page).
4. **More → 📱 Phone & alerts → Connect Telegram** → tap *Open Telegram* → **Start** →
   back in the app press **I pressed Start** → you get "✅ Connected". Try *Send a test message*.

To go back to plain local mode at any time, remove the `[auth]` block from secrets.toml.

## 5. Put it in the cloud (8 min)

1. Merge your work into `main` on GitHub (scheduled GitHub Actions only run from the
   default branch): open a pull request `momentum-study → main` and merge it.
2. **share.streamlit.io** → sign in with GitHub → **Create app** → *Deploy a public app from
   GitHub*: repo `huntersarnelli/Service_NOW_analysis`, branch `main`, main file `appV2.py`,
   pick a custom URL (e.g. `hunter-desk`) → **Advanced settings**: Python 3.12, and paste your
   whole `secrets.toml` into **Secrets**, changing `redirect_uri` to
   `https://hunter-desk.streamlit.app/oauth2callback`. **Deploy.**
3. Back in Auth0 → your application → Settings: add `https://hunter-desk.streamlit.app/oauth2callback`
   to **Allowed Callback URLs** and `https://hunter-desk.streamlit.app` to **Allowed Logout URLs**. Save.
4. Open the app URL → sign in. The public URL shows only the sign-in page to anyone not invited.

## 6. Turn on the schedule (3 min)

1. GitHub → `Service_NOW_analysis` → **Settings → Secrets and variables → Actions → New
   repository secret**, three times: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `TELEGRAM_BOT_TOKEN`.
2. **Actions** tab → *desk-alerts* → **Run workflow** (mode `morning`, force ✓) → a brief
   should arrive on Telegram within ~2 minutes. After that it runs by itself on trading days.

## 7. iPhone

Open the app URL in **Safari** → **Share** → **Add to Home Screen** → **Add**. It opens like
an app. After a quiet spell it can take ~30 s to wake; your data is unaffected.

## 8. Invite friends

**More → 👥 Friends** (only you see it) → type their Gmail address → Enter. Send them the app
URL. They sign in with Google, then connect their own Telegram. Remove someone by deleting
their email; they're locked out on their next visit.

---

## Security checklist

- Invite-only; unverified Google emails refused; nobody can sign up on their own.
- No passwords stored by the Desk; Auth0 handles them and requires email verification.
- Each user's data is keyed to their email; the app never keeps "the current user" in a
  global (Streamlit serves everyone from one process), and it refuses to start if sign-in is
  on without the database, so users can never share a local file.
- The Supabase table has row-level security on with no policies: only the service key
  (in Streamlit secrets + GitHub secrets, never in code) can read it.
- If a key ever leaks: Supabase → API → rotate the service key; BotFather → `/revoke`; Auth0 → rotate the client secret. Then update the three secrets boxes.
- The repo holds code only — `.streamlit/secrets.toml` and `portfolio_data/` are gitignored.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Callback URL mismatch" from Auth0 | The `redirect_uri` in secrets must exactly match an *Allowed Callback URL* in Auth0 |
| Keeps signing in as the wrong account | Sign out, then *Use a different account* (clears Auth0's remembered login) |
| "Refusing to start … database isn't configured" | `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` missing from the app's secrets |
| "isn't on the invite list" | Add the email under More → Friends (or to `ADMIN_EMAILS`) |
| No Telegram briefs | Actions tab → check the latest *desk-alerts* run log; confirm the three repo secrets |
| No market data | Yahoo throttles cloud servers at times — Refresh after a minute |

*Research and educational use only. Not investment advice.*
