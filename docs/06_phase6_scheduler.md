# Phase 6: persistent scheduler, permissions, run history, real job execution

Tests: `.venv\Scripts\python -m pytest tests -q` → **221 passed** (34 new in `tests/test_phase6.py`, including a real worker subprocess).

## How it works
Streamlit cannot run background jobs, so the clock is a separate **worker**:

```
GitHub Actions cron (every 15 min)  ──►  python worker/run_scheduled.py --once
   or Windows Task Scheduler / cron                │
                                                   ▼
                       dwn.scheduler.jobs.run_due()  ──►  orchestrator (the same agent as the app)
                                                   │
                                         same database as the app
```
- Schedules are saved in the database (Settings & Scheduler). Time is **UTC** (labelled everywhere).
- Each tick finds the latest scheduled slot for every enabled schedule and runs it if it has not run yet.
- A job runs the agent for the clients in scope, as the schedule's owner, and creates **analysis, drafts and review items only**. It never approves, trades or messages (tested).

## Guarantees, each tested
| Concern | What happens |
|---|---|
| Runs twice? | Impossible: a unique constraint on (schedule owner, slot). A second tick, or two workers at once, does nothing. |
| Overlap | A lock with an expiry. A scheduled tick that finds the lock leaves the slot untouched for the next tick; "Run now" says a run is in progress. A crashed worker's lock expires. |
| Schedule saved after the slot | No back-fill. |
| Worker was down | A slot older than 6 h is recorded as **missed** (visible, red), not silently run late. |
| Permission revoked after saving | Checked again **at run time**: job recorded as *skipped: permission revoked*, nothing analysed, audited. |
| Client scope shrinks after saving | Re-checked at run time: out-of-scope clients are recorded as failed ("outside the scope granted"), others still run (job = *partial*); the other RM's client is never touched. |
| Failures | Never hidden. Per-client outcome (ok / paused / failed / not run) and error text stored. One immediate retry per client; failed or partial jobs are retried on later ticks up to **3 attempts**, only for the failed clients; then they stay visibly failed. |
| Paused ≠ failed | A client without consent is *paused* (by design). A reused identical run reports its real earlier outcome. |
| Cost controls | Max 50 clients per job, 240 s time budget (the rest recorded as *not run*), market-data refresh throttled to once per 30 s, LLM call caps and daily budget. |
| Data problems | If the live refresh fails, the job continues; agents abstain on missing/stale data; the job records what the data freshness was. |
| Workflow scope boxes | *Risk & scenarios*, *Market events*, *RM draft recommendations* really switch those steps off (skipped steps are recorded). Without "RM draft recommendations" a run records analysis and evidence but creates no proposal or review item. *Portfolio drift* and *Goal progress* are one engine pass and always run. |
| Durable | Schedules, jobs and history survive restarts (tested). |

## What I ran for real
1. Saved a schedule **through the UI** (daily, selected clients Rajesh, Ananya, Neha, Vikram).
2. Ran `python worker/run_scheduled.py --once` as a separate process against the app's database (I backdated the schedule's `saved_at` by 2 days, because the no-back-fill rule correctly refused to run a slot earlier than the save time): **job completed, 4 clients: 3 ok, 1 paused (no consent), 0 failed**, with live price refresh. Ananya's Tier 2 review item then appeared in the RM workbench without anyone clicking Run.
3. A second tick said "nothing due". **Run now** in the UI recorded a *manual* job; Run history shows both; *Run preview now* is a dry run.
4. Failure, retry, overlap, missed slot, revoked permission, scope shrink, budgets: **verified by automated tests with simulated failures, not by breaking the live system.**

## Setup (simple English)
**Locally (Windows):** Task Scheduler → Create Task → trigger every 15 minutes → action: `C:\path\to\.venv\Scripts\python.exe worker\run_scheduled.py --once`, start in the project folder.
**Hosted (GitHub):** the workflow `.github/workflows/scheduler.yml` is written but **has never run**. It needs: repository secret `DATABASE_URL` (the Postgres URL; the same one the Streamlit app uses), optional `GROQ_API_KEY` / `GEMINI_API_KEY`, optional variable `DWN_LLM_PROVIDER`. **It cannot work with SQLite**: the runner and Streamlit Cloud do not share a file, so the hosted scheduler requires the hosted Postgres (Supabase), which is untested here.

## Changes to your UI for approval
1. **Run now** button beside *Run preview now* (preview is now a real dry run: counts clients in scope and clients that would pause).
2. **Next scheduled run** line and a **Run history** list (time, manual/scheduled, outcome counts, data freshness, attempt number, status chip) inside the Scheduler status card. Admin sees all owners; an RM sees their own.
3. Times are labelled **UTC**.

## Limits
- 15-minute granularity (cron). GitHub cron can lag by minutes; never exact.
- One schedule per user. No per-schedule timezone. No email/Slack notification of failures (the red status and audit log are the alert for now; the workflow goes red on a failed job).
- Not verified: Postgres, GitHub Actions, Python 3.12 (this machine has 3.14).
- Jobs run clients one after another; 50 clients ≈ a few minutes.
