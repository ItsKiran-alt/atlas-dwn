# Phase 8: final repository and what was verified before you deploy

## Verified here (2026-10-20)
| Check | Result |
|---|---|
| Full test suite, SQLite, **Python 3.14** | 345 passed, 95% coverage of `dwn/` |
| Full test suite, SQLite, **Python 3.12** (Streamlit Community Cloud's default) in a **fresh clone** built from `requirements-dev.txt` | 345 passed |
| Full test suite on a **real PostgreSQL 17.2** (portable EDB build, run locally, then deleted): migrations 0001-0004 applied, append-only audit triggers, locks, unique slots, all agent/approval/scheduler tests | **343 passed, 2 skipped** (the two that read SQLite files directly) |
| **Deployment-style smoke test** (`scripts/deploy_smoke.py`): app started with `DWN_ENV=prod`, PostgreSQL `DATABASE_URL`, custom demo password; headless browser | 8/8: login page shows no demo password; wrong password refused; RM signs in; 24 clients; agent run with live data creates a proposal; Research page renders; sign-out. Rows landed in Postgres (37 clients, 42 users, runs, proposals, audit). No server errors. |
| Offline PostgreSQL DDL generation from the migrations | OK |
| `pip-audit` on the pinned `requirements.txt` | No known vulnerabilities |
| Clean-clone check: 125 tracked files, no `.env`/secrets/database/venv tracked, secret-pattern scan clean | OK |
| Provider instructions (Streamlit Community Cloud deploy + secrets, Supabase connection modes, GitHub schedule behaviour and free minutes, Groq/Gemini/Alpha Vantage key pages) | Read from their official docs on 2026-10-20 |

## Bugs found by these checks (fixed)
1. **`.gitignore` pattern `data/` also ignored the code package `dwn/data/`.** A GitHub push would have **silently omitted the market/news code** and the deployed app would crash on start. Now `/data/`. Found only because I tested a fresh clone.
2. **A test depended on the time of day** (the market-session window); it passed on SQLite in the evening and failed on Postgres run at night. Rewritten to use relative times.
3. Added a 150-character cap on onboarding emails (Postgres enforces column lengths; SQLite does not).
4. Login page no longer pre-fills a custom demo password; Postgres connection pool tuned for hosted free tiers.

## NOT verified (you will meet these)
- **Supabase itself** (free-tier pausing/limits, pooler host naming) and **Streamlit Community Cloud** (build, secrets bridge, IPv4/IPv6 reachability of the database from their servers) and **GitHub Actions** (the scheduler workflow has never run).
- **Every LLM call** (Groq, Gemini) and Alpha Vantage: adapters tested with fake transports only.
- Safari/Firefox rendering; real-world load; Yahoo Finance terms.
- The deployment steps follow the documentation, but I could not click through your accounts. If a step fails, see section 8 of `docs/DEPLOYMENT.md`.
