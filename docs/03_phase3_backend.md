# Phase 3: persistent backend, authentication, consent, isolation

Run: `.venv\Scripts\python -m streamlit run app.py` (first start migrates and seeds `data/dwn.sqlite3`).
Tests: `.venv\Scripts\python -m pytest tests -q` → **34 passed**.

## What changed
| Piece | Where |
|---|---|
| Config from env vars (`DWN_ENV`, `DATABASE_URL`, lockout/idle limits) | `dwn/config.py`, `.env.example` |
| Schema + **Alembic migration 0001** (upgrade and downgrade tested) | `dwn/db/models.py`, `alembic/` |
| Data access (all SQL in one place, scoping done in SQL) | `dwn/repo.py` |
| Salted PBKDF2 password hashes, constant-time compare | `dwn/security.py` |
| Login with failure counting, 15-minute lockout, audit of every failure | `dwn/auth.py` |
| Server-side idle session expiry (30 min) | `dwn/ui/controller.py` |
| One DB transaction per UI event; denied requests roll back and are audited | `app.py`, `controller.py` |
| Synthetic seed (37 clients, 3 RMs, admin, consents, sources), idempotent | `dwn/bootstrap.py` |
| Consent: versioned + SHA-256 of consent text + timestamps, withdrawal, re-consent | `dwn/services.py` |
| Consent-withdrawal card and dialogs in the client portal (approved) | `dwn/ui/render.py` |

## Verified
- **Persistence:** wrote an RM decision and note through the UI, restarted the server, both still there (also a unit test that drops the engine and re-reads).
- **Audit log append-only:** database triggers reject UPDATE and DELETE (tested).
- **Passwords** never stored in plain text; random salt per hash; wrong password / wrong role / unknown user rejected; **5 failures lock the account** (seen in the UI too); success resets the counter.
- **Isolation:** RM queries return only their `rm_id` rows (Priya 24, Arjun 13, Neha 0); a client loads only their own row; forged events (other RM's client, admin actions by RM/Client, RM decision by Admin) are refused **and audited as "Access denied"**.
- **Consent:** new client gets an account + one consent record; existing clients never see the consent form; returning email is told to sign in; withdrawal by the client pauses the RM's ability to approve or draft for that client (RM cannot withdraw for them); data is kept; re-consent works; history rows are kept.
- **Prod guard:** `DWN_ENV=prod` refuses to start without `DATABASE_URL`, and never seeds demo data unless explicitly told to.

## Deviations / decisions to confirm
1. **New: password fields on the onboarding form** (needed for real accounts; min 10 characters). Not in your HTML.
2. **Supabase:** I used **Postgres-compatible SQLAlchemy + Alembic**, so a Supabase Postgres URL should work, but **I could not test Postgres here** (no server/credentials) and the `psycopg` driver is not installed. **Supabase Auth is NOT integrated**; sign-in uses the app's own hashed passwords. `auth.authenticate` is the single swap point. I'd integrate Supabase Auth in Phase 8 once you have an account, or keep own auth if you prefer fewer vendors. Your call.
3. All demo users share one hash (same demo password, one salt) to keep first-run seeding fast. New clients get their own salted hash.
4. Audit times are UTC; RM-facing "Last reviewed" / "Next meeting" fields are still static seed text.

## Still not done (by phase)
- Real market/news data, goal/risk numbers: Phase 4/5 (UI still shows illustrative values, labelled).
- No Postgres test run, no Supabase connection, no email verification or password reset.
- Rate limiting is per-account lockout only (no per-IP limit; Streamlit does not expose client IPs reliably).
- The scheduler still only saves settings; nothing runs (Phase 6).
