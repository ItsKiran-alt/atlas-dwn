"""Job execution for saved schedules. This is the code that ACTUALLY runs the agent; `worker/run_scheduled.py` calls it.

Guarantees (all tested):
* a scheduled slot executes at most once (database unique constraint) and never twice at the same time (lock with expiry)
* permissions and client scope are re-checked at execution time, not just when the schedule was saved
* every job is recorded truthfully: started, finished, per-client outcome, data freshness, errors; failures stay visible
* cost controls: clients per job, time budget, throttled data refresh, LLM call caps (via the orchestrator)
* retries: one immediate retry per client for unexpected errors; failed/partial jobs are retried on later worker ticks (max attempts, inside the grace window)
* a missed slot (worker was not running) is recorded as 'missed' instead of silently running late
* jobs create analysis, drafts and review items only. They never approve, trade or message anyone.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .. import config, services
from ..agents.orchestrator import run_monitoring
from ..data.market import MarketService
from ..db.session import session_scope
from ..domain import Client, User, utcnow
from ..repo import Repo
from .slots import latest_slot

ALL_SCOPES = ["Portfolio drift", "Risk & scenarios", "Goal progress", "Market events", "RM draft recommendations"]


@dataclass
class JobResult:
    job_id: str = ""
    status: str = ""
    total: int = 0
    ok: int = 0
    paused: int = 0
    failed: int = 0
    not_run: int = 0
    message: str = ""
    skipped: bool = False
    items: list = field(default_factory=list)


def scope_clients(repo: Repo, owner: User, cfg: dict) -> tuple[list[Client], list[tuple[str, str]]]:
    """Clients the schedule covers, plus (client_id, reason) for anything requested but not allowed."""
    scope = cfg.get("client_scope", "All assigned clients")
    problems: list[tuple[str, str]] = []
    if scope == "Selected client only":
        allowed = {c.id: c for c in services.clients_for(repo, owner, for_scheduling=True)}
        out = []
        for cid in cfg.get("clients") or []:
            if cid in allowed:
                out.append(allowed[cid])
            else:
                problems.append((cid, "outside the scope granted to the schedule owner"))
        return out, problems
    assigned = repo.list_clients(include_all=True) if owner.role == "Admin" else repo.list_clients(rm_id=owner.rm_id)
    if scope == "Tier 1 clients only":
        assigned = [c for c in assigned if c.tier == "Tier 1"]
    elif scope == "Clients flagged for review":
        assigned = [c for c in assigned if c.kind == "review"]
    return assigned, problems


def _freshness(repo: Repo) -> dict:
    try:
        return {r["symbol"]: dict(freshness=r["freshness"], age=r.get("age", "")) for r in MarketService(repo).view(["^GSPC", "SPY", "AGG", "VNQ"])}
    except Exception as e:                                       # never let reporting break the job
        return {"error": f"{type(e).__name__}"}


def run_job(repo: Repo, owner: User, cfg: dict, *, trigger: str, slot: datetime | None = None, llm=None, resume: dict | None = None,
            clock=utcnow, refresh=True) -> JobResult:
    scopes = [s for s in (cfg.get("scopes") or []) if s in ALL_SCOPES]
    if not services.rm_can_schedule(repo, owner):
        if trigger == "manual":
            raise services.Denied("Your administrator has not enabled scheduling access.")
        job_id = uuid.uuid4().hex[:16]
        if repo.create_job(job_id, owner.email, owner.name, trigger, slot, scopes, cfg.get("client_scope", ""), 1):
            repo.update_job(job_id, status="skipped", finished_at=clock(), message="Skipped: scheduling permission was revoked by an administrator")
            repo.log("All clients", "Scheduled job skipped", "Scheduler", f"{owner.name}: scheduling permission revoked", "Review", "System")
            repo.s.commit()
        return JobResult(job_id, "skipped", message="permission revoked", skipped=True)

    key = f"schedule:{owner.email}"
    holder = uuid.uuid4().hex[:12]
    if not repo.acquire_lock(key, holder, config.JOB_TIME_BUDGET_S + 120):
        if trigger == "manual":
            raise ValueError("A run for this schedule is already in progress. Try again in a minute.")
        return JobResult(status="locked", message="another run in progress", skipped=True)
    repo.s.commit()
    try:
        if resume:
            job_id = resume["id"]
            repo.update_job(job_id, status="running", attempts=resume["attempts"] + 1, finished_at=None, message="")
            only = {i["client_id"] for i in repo.job_items(job_id) if i["status"] in ("failed", "not_run")}
            prior_ok = [i for i in repo.job_items(job_id) if i["status"] not in ("failed", "not_run")]
            repo.delete_failed_items(job_id)
        else:
            job_id = uuid.uuid4().hex[:16]
            if not repo.create_job(job_id, owner.email, owner.name, trigger, slot, scopes, cfg.get("client_scope", ""), 1):
                repo.s.rollback()
                return JobResult(status="duplicate", message="this slot already has a job", skipped=True)
            only, prior_ok = None, []
        repo.s.commit()
        repo.log("All assigned clients", "Scheduled job started" if trigger == "scheduled" else "Manual job started", "Scheduler", f"{owner.name}; job {job_id}; scopes: {', '.join(scopes) or 'none'}", "Logged", "System")

        fresh: dict = {}
        if refresh:
            try:
                msg = services.refresh_external_data(repo, owner)
                fresh["refresh"] = msg[:160]
            except Exception as e:
                fresh["refresh"] = f"refresh failed: {type(e).__name__}: {str(e)[:100]}"
            repo.s.commit()
        fresh.update(_freshness(repo))

        clients, problems = scope_clients(repo, owner, cfg)
        res = JobResult(job_id=job_id)
        deadline = time.monotonic() + config.JOB_TIME_BUDGET_S
        for cid, why in problems:
            if only is None or cid in only:
                repo.add_job_item(job_id, cid, cid, "failed", error=why); res.failed += 1
        todo = [c for c in clients if only is None or c.id in only]
        res.total = len(todo) + len(prior_ok) + len(problems if only is None else [])
        for idx, c in enumerate(todo):
            if idx >= config.JOB_MAX_CLIENTS:
                repo.add_job_item(job_id, c.id, c.name, "not_run", error="job client limit reached"); res.not_run += 1; continue
            if time.monotonic() > deadline:
                repo.add_job_item(job_id, c.id, c.name, "not_run", error="time budget used"); res.not_run += 1; continue
            outcome = _run_client(repo, owner, c, trigger, scopes, llm)
            repo.add_job_item(job_id, c.id, c.name, outcome["status"], outcome.get("run_id", ""), outcome.get("tier", ""), outcome.get("error", ""))
            res.ok += outcome["status"] in ("ok", "duplicate")
            res.paused += outcome["status"] == "paused"
            res.failed += outcome["status"] == "failed"
            repo.s.commit()                                      # progress is durable after every client
        res.ok += sum(1 for i in prior_ok if i["status"] in ("ok", "duplicate"))
        res.paused += sum(1 for i in prior_ok if i["status"] == "paused")
        good = res.ok + res.paused
        res.status = "completed" if not (res.failed or res.not_run) else ("partial" if good else "failed")
        res.message = (f"{res.total} clients: {res.ok} ok, {res.paused} paused, {res.failed} failed, {res.not_run} not run" if res.total else "No clients in scope.")
        repo.update_job(job_id, status=res.status, finished_at=clock(), total=res.total, ok=res.ok, paused=res.paused, failed=res.failed, not_run=res.not_run,
                        freshness=fresh, message=res.message)
        repo.log("All assigned clients", f"Job {res.status}", "Scheduler", f"{owner.name}; job {job_id}; {res.message}", "Logged" if res.status == "completed" else "Review", "System")
        repo.s.commit()
        res.items = repo.job_items(job_id)
        return res
    finally:
        repo.release_lock(key, holder)
        repo.s.commit()


def _run_client(repo: Repo, owner: User, c: Client, trigger: str, scopes: list, llm) -> dict:
    """One client, one immediate retry for unexpected errors. Denials and paused items are outcomes, not errors."""
    last = ""
    for attempt in range(2):
        try:
            r = run_monitoring(repo, owner, c.id, trigger="schedule" if trigger == "scheduled" else "manual", llm=llm, scopes=set(scopes))
            if r.status == "failed":
                last = "; ".join(r.notes)[:300] or "run failed"
                repo.s.commit()
                continue
            if r.status == "duplicate":                              # identical inputs were analysed moments ago: report THAT run's real outcome
                prior = repo.get_run(r.duplicate_of) or {}
                return dict(status="paused" if prior.get("status") == "paused" else "ok", run_id=r.duplicate_of, tier=prior.get("tier", ""), error="reused an identical earlier run")
            return dict(status={"completed": "ok", "paused": "paused"}[r.status], run_id=r.run_id, tier=r.tier)
        except services.Denied as e:
            repo.s.rollback()
            return dict(status="failed", error=f"not permitted: {e}")
        except Exception as e:
            repo.s.rollback()
            last = f"{type(e).__name__}: {str(e)[:200]}"
    return dict(status="failed", error=last)


def run_due(now: datetime | None = None, llm=None, url: str | None = None, refresh: bool = True) -> list[JobResult]:
    """What the worker calls on every tick. Idempotent: calling it twice in the same minute does nothing the second time."""
    now = now or utcnow()
    with session_scope(url) as s:
        schedules = Repo(s).list_schedules()
    out: list[JobResult] = []
    for sch in schedules:
        cfg = sch["cfg"]
        if not cfg.get("enabled"):
            continue
        with session_scope(url) as s:
            repo = Repo(s)
            owner = repo.get_user(sch["owner_email"])
            if owner is None or owner.role not in ("RM", "Admin"):
                continue
            slot = latest_slot(cfg, now)
            if slot is None or slot < sch["saved_at"].replace(second=0, microsecond=0):
                continue                                          # nothing due, or the schedule was created after that slot
            job = repo.job_for_slot(owner.email, slot)
            if job is None:
                if now - slot > timedelta(hours=config.JOB_GRACE_HOURS):
                    jid = uuid.uuid4().hex[:16]
                    if repo.create_job(jid, owner.email, owner.name, "scheduled", slot, cfg.get("scopes", []), cfg.get("client_scope", ""), 0):
                        repo.update_job(jid, status="missed", finished_at=now, message=f"Missed: no worker was running within {config.JOB_GRACE_HOURS}h of the scheduled time")
                        repo.log("All assigned clients", "Scheduled job missed", "Scheduler", f"{owner.name}; slot {slot:%Y-%m-%d %H:%M} UTC", "Review", "System")
                    out.append(JobResult(jid, "missed", skipped=True, message="missed slot recorded"))
                else:
                    out.append(run_job(repo, owner, cfg, trigger="scheduled", slot=slot, llm=llm, refresh=refresh))
            elif job["status"] in ("failed", "partial") and job["attempts"] < config.JOB_MAX_ATTEMPTS and now - slot <= timedelta(hours=config.JOB_GRACE_HOURS):
                out.append(run_job(repo, owner, cfg, trigger="scheduled", slot=slot, llm=llm, resume=job, refresh=refresh))
    return out
