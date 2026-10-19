# Deployment guide (simple English, step by step)

You will: **(1)** run it on your computer, **(2)** put the code on GitHub, **(3)** create a free hosted database, **(4)** deploy the app on Streamlit Community Cloud, **(5)** start the scheduler, **(6)** check everything works.

I cannot create accounts or enter passwords for you, so every account step below is yours. **Never paste a key or password into a chat, an issue, or a file that is committed to GitHub.**

Time needed: about 60-90 minutes the first time. Cost: free tiers only.

> **Honest status.** Verified here: SQLite on Python 3.14 and 3.12, all 345 tests, a local PostgreSQL (see `docs/08_phase8_verification.md`), the instructions below against the providers' documentation as fetched on 2026-10-20. **Not verified here:** Supabase, Streamlit Community Cloud and GitHub Actions themselves, and every LLM. If a step fails, use section 8.

---
## 1. Run it on your computer
1. **Install Python 3.12 or newer** from python.org (tick "Add python.exe to PATH"). Check: open PowerShell, type `python --version`.
2. **Install Git** from git-scm.com. Check: `git --version`.
3. Open PowerShell in the project folder, then:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m pytest tests -q
python -m streamlit run app.py
```
If PowerShell refuses to run `Activate.ps1`, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then retry.
4. Browser opens at `http://localhost:8501`. Sign in as `priya.sharma@atlas-demo.com` / `atlas-demo` (local demo only).
5. Open **Research & Market**. After a few seconds you should see real prices with "Fresh" or "Market closed · last close" and real headlines with links. That proves the data connections work.

## 2. Put the code on GitHub
1. Create a GitHub account at github.com if you have none.
2. Click **+ → New repository**. Name: `atlas-dwn`. Choose **Public** (see the note on cost in section 5) or Private. **Do NOT tick** "Add a README" or ".gitignore" (we already have them). Click **Create repository**.
3. In PowerShell, in the project folder:
```powershell
git init -b main
git add .
git status          # CHECK: you must NOT see .env, .streamlit/secrets.toml, data/, or .venv in this list
git commit -m "Atlas DWN prototype"
git remote add origin https://github.com/YOUR-USER/atlas-dwn.git
git push -u origin main
```
GitHub may open a browser window to sign you in the first time.
4. Refresh the repository page: you should see `app.py`, `dwn/`, `README.md`.
5. **Safety check:** use the repository search box for `password`, `api_key`, `postgresql://`. Only placeholders (like `YOUR-DB-PASSWORD`) may appear.

## 3. Create the hosted database (Supabase, free)
Why: Streamlit Community Cloud forgets local files, so data must live in a database. Required for hosting.
1. Go to supabase.com → **Start your project** → sign in (GitHub login is fine).
2. **New project**. Name `atlas-dwn`. **Database password:** choose a long one and save it in your password manager. Choose the region closest to you. Plan: **Free**.
3. Wait until the project says it is ready.
4. Click **Connect** (top of the page). Choose **Session pooler**. (Reason: the direct connection is IPv6-only on the free plan; the session pooler works over IPv4 and suits an always-on app.) Copy the connection string. It looks like `postgresql://postgres.PROJECTREF:[YOUR-PASSWORD]@aws-0-REGION.pooler.supabase.com:5432/postgres`.
5. Replace `[YOUR-PASSWORD]` with your database password. If the password contains `& # ? @ /` or a space, **percent-encode** it (e.g. `@` → `%40`) or pick a simpler password.
6. Keep this string private. It is your `DATABASE_URL`.
**We use Supabase only as a PostgreSQL host.** No Supabase API key is needed. Free-tier limits (project pausing after inactivity, storage) were not verified: check Supabase's pricing page.

## 4. Deploy on Streamlit Community Cloud
1. Go to **share.streamlit.io** and sign in with GitHub. Allow it to access your `atlas-dwn` repository.
2. Click **Create app** (top right) → **Yup, I have an app**.
3. Fill in: **Repository** `YOUR-USER/atlas-dwn`, **Branch** `main`, **Main file path** `app.py`.
4. Click **Advanced settings**:
   - **Python version:** 3.12 (it is the default; this project was tested on 3.12).
   - **Secrets:** paste the text below, with your own values (this is TOML):
```toml
DWN_ENV = "prod"
DATABASE_URL = "postgresql://postgres.PROJECTREF:YOUR-PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres"
DWN_SEED_DEMO = "1"
DWN_DEMO_PASSWORD = "choose-a-long-unique-demo-password"
```
   (`DWN_SEED_DEMO=1` creates the synthetic demo clients and accounts on the first start. `prod` mode refuses to start with the default demo password, which is why you must set your own.)
   - Click **Save**.
5. Click **Deploy**. The first start takes a few minutes: it installs packages, creates the tables (migrations) and the demo data.
6. Open the app URL. Sign in with `priya.sharma@atlas-demo.com` and your `DWN_DEMO_PASSWORD`.
Later changes: edit **Secrets** in the app's settings; pushing to GitHub redeploys automatically.

## 5. Start the scheduler (needed only if you use schedules)
Streamlit cannot run background jobs, so a GitHub Action is the clock.
1. Repository → **Settings → Secrets and variables → Actions → New repository secret**:
   - `DATABASE_URL` = the same string as in step 4.
   - Optional: `GROQ_API_KEY`, `GEMINI_API_KEY`.
   Optional **Variables** tab: `DWN_LLM_PROVIDER` = `groq` or `gemini`.
2. Repository → **Actions** tab → enable workflows if asked → open **scheduler** → **Run workflow** (this is a manual test run). It should finish green; the log shows `{"status": "nothing due"}` until a schedule is due.
3. It then runs automatically at minutes 7 and 37 of every hour (`.github/workflows/scheduler.yml`).
**Things to know (from GitHub's documentation):** scheduled runs can be delayed or dropped under heavy load; they run only on the default branch; in a **public** repo they switch off after **60 days with no repository activity** (push anything to wake them); standard runners are **free for public repos**, but a **private** repo gets only **2,000 free minutes/month** (every 30 minutes can exceed that: change the cron to hourly `7 * * * *`).
**Local alternative:** Windows Task Scheduler → Create Task → trigger every 15 minutes → action `C:\path\to\.venv\Scripts\python.exe worker\run_scheduled.py --once`, start in the project folder, with the environment variable `DATABASE_URL` set.

## 6. API keys and accounts
| Credential | Why | Required? | Where to get it | Plan | Steps | Permissions | Store locally | Store on hosting | Test | Limits (verified 2026-10-20) |
|---|---|---|---|---|---|---|---|---|---|---|
| **Supabase database** | Persistent hosted data | Yes, to host | supabase.com | Free | Section 3 | project owner; we need only the connection string | `DATABASE_URL` in `.env` / `.streamlit/secrets.toml` | Streamlit **Secrets**; GitHub **Secrets** | App starts and Admin → Settings shows sources | Not verified: check Supabase pricing (pausing, storage) |
| **GitHub** | Code, CI, scheduler | Yes | github.com | Free | Section 2 | repo write | none | n/a | Actions tab goes green | Public repos: free runner minutes; private: 2,000 min/month; scheduled runs can lag |
| **Streamlit Community Cloud** | Hosting | Optional (or run locally) | share.streamlit.io | Free | Section 4 | read access to your repo | n/a | n/a | App URL loads | Not verified |
| **Groq API key** | Optional LLM drafting | Optional | console.groq.com → **API Keys** (link `/keys`) | Free tier if offered | Create key, copy once | key only | environment variable `GROQ_API_KEY` | Streamlit Secrets + GitHub Secrets | Set `DWN_LLM_PROVIDER=groq`, enable "Groq language model" in Settings, run `python scripts\run_golden_agent.py --llm groq` | Free-plan numbers not shown in Groq's docs; check your console |
| **Google Gemini key** | Optional LLM | Optional | aistudio.google.com/apikey | Free tier | **Create API key**; belongs to a Google Cloud project | key only | `GEMINI_API_KEY`; also set `GEMINI_MODEL` to the model id shown in AI Studio | Secrets | same as above with `--llm gemini` | Google no longer publishes per-model free limits in its docs; **free-tier inputs may be used to improve Google products: synthetic data only** |
| **Alpha Vantage key** | Optional fallback prices | Optional | alphavantage.co/support/#api-key | Free | Fill the claim form (organisation, email) | key only | `ALPHAVANTAGE_API_KEY` | Secrets | Set the key, enable the source in Settings, refresh data while Yahoo is blocked | **25 requests/day**; the app budgets 20 |
No key is needed for Yahoo Finance, Federal Reserve, SEC or BLS data.
**Where "locally" means:** copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (git-ignored) or set environment variables. To enable a model in the app: sign in as Admin → Settings & Scheduler → Agent data sources → add the Groq or Gemini source.

## 7. Check that it works (10-minute checklist)
1. **Real data:** Research & Market shows prices with a source link, a time and a status; headlines link to federalreserve.gov / sec.gov / bls.gov.
2. **Roles:** (a) RM: Priya sees 24 clients, no Admin panel. (b) Admin: sees only Compliance View and Settings. (c) Client: `ramesh.agarwal@atlas-demo.com` sees only his own portfolio. (d) As Priya, try opening Ramesh: impossible; there is no way to reach him.
3. **Agent:** as Priya, open Rajesh Menon → **Run monitoring check**. A Tier 3 proposal appears with evidence. Approve it **without** ticking "I have spoken with the client": refused. Tick it: now "Awaiting second approver: Arjun Mehta". Sign in as Arjun, open Rajesh, approve.
4. **Consent:** as Ramesh, **Withdraw consent**; as his RM (Arjun) try to approve anything for him: refused. Give consent again in the portal.
5. **Persistence:** note something, redeploy/restart the app: it is still there.
6. **Scheduler:** Settings → create a schedule 10 minutes ahead (UTC) → wait for the GitHub Action → **Run history** shows a *scheduled* job.
7. **Tests:** `python -m pytest tests -q` → all pass.

## 8. Troubleshooting
| Symptom | Likely cause and fix |
|---|---|
| `pip install` fails on a package | Use Python 3.12 (`python --version`); upgrade pip: `python -m pip install -U pip`. |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| App shows "The service could not start… reference abc123" | Open the app's **Manage app → Logs**; search the reference. Usually a wrong `DATABASE_URL` (typo, un-encoded special character, wrong region host) or `DWN_ENV=prod` with `DWN_SEED_DEMO=1` and no `DWN_DEMO_PASSWORD`. |
| `RuntimeError: DWN_ENV=prod requires a hosted database` | `DATABASE_URL` missing or it starts with `sqlite`. |
| `connection refused` / `Network is unreachable` to Supabase | You used the **direct** connection (IPv6). Use the **Session pooler** string. |
| `password authentication failed` | Wrong or un-encoded password; reset it in Supabase → Project Settings → Database. |
| Too many connections | The app keeps a small pool (3+2); close other tools using the database or restart the app. |
| Research page says "Unavailable" or "Stale" | The provider is down or blocked from your host. Admin → Settings → data sources shows the real error. Not a bug: the app refuses to show unverified prices. |
| Login says "Too many failed attempts" | Account locked for 15 minutes after 5 bad passwords. |
| GitHub Action red: `DATABASE_URL` empty | Secret not set in **Actions** secrets (Streamlit secrets are separate). |
| GitHub Action never runs | Workflows disabled, not on the default branch, or a public repo idle for 60 days. |
| Scheduled job status "missed" | No worker ran within 6 hours of the slot; by design it is recorded, not run late. |
| LLM calls "not configured" | Key or `DWN_LLM_PROVIDER` missing, or the source is disabled in Settings. The agent then uses templates (still works). |
| Page is blank after deploy | Hard-refresh; check the browser console; the app needs the component folder `ui_component/` in the repo. |

## 9. Backup and recovery (manual)
- Supabase: Dashboard → **Database → Backups** (availability depends on plan; not verified). Manual: `pg_dump "$DATABASE_URL" > backup.sql`, restore with `psql "$DATABASE_URL" < backup.sql` (needs PostgreSQL client tools).
- Local SQLite: copy `data/dwn.sqlite3` while the app is stopped.
- Schema changes are migrations in `alembic/versions`; they run automatically at start (`bootstrap.init`).

## 10. Before real use
Read `docs/SECURITY.md`. Replace the placeholder thresholds with compliance-owned values, add a real identity provider (MFA, verification), licensed market data, and a data-protection review.
