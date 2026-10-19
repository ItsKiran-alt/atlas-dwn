"""Scheduler worker. Run this on a timer (every ~15 minutes); it executes whatever saved schedules are due.

    python worker/run_scheduled.py --once          # one tick (what the GitHub Actions cron does)
    python worker/run_scheduled.py --loop 300      # keep ticking every 300 s (local use)

It uses the same database and the same code as the app (dwn.scheduler.jobs). It is safe to run twice at once:
each scheduled slot is executed at most once. Exit code 1 means at least one job FAILED (so CI shows red).
Secrets come from environment variables only (DATABASE_URL, optional GROQ_API_KEY / GEMINI_API_KEY ...).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dwn import bootstrap                                  # noqa: E402
from dwn.agents.llm import make_llm                         # noqa: E402
from dwn.scheduler.jobs import run_due                      # noqa: E402


def tick() -> int:
    bootstrap.init()                                         # applies migrations; seeds demo data only when DWN_SEED_DEMO=1 (never default in prod)
    results = run_due(llm=make_llm(), refresh=os.environ.get("DWN_JOB_SKIP_REFRESH", "0") != "1")
    for r in results:
        print(json.dumps(dict(job=r.job_id, status=r.status, total=r.total, ok=r.ok, paused=r.paused, failed=r.failed, not_run=r.not_run, message=r.message)))
    if not results:
        print(json.dumps(dict(status="nothing due")))
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", type=int, default=0, help="seconds between ticks")
    a = ap.parse_args()
    code = tick()
    while a.loop and not a.once:
        time.sleep(a.loop)
        code = max(code, tick())
    sys.exit(code)
