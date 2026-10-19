"""Phase 6 tests: schedule arithmetic, real job execution, permissions at run time, locks, retries, budgets, history, worker."""
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from dwn import auth, config, services
from dwn.agents.llm import TemplateLLM
from dwn.data.models import MarketQuote
from dwn.db import session as dbsession
from dwn.domain import utcnow
from dwn.repo import Repo
from dwn.scheduler import jobs
from dwn.scheduler.jobs import run_due, run_job
from dwn.scheduler.slots import latest_slot, next_slot
from dwn.ui import controller

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 20, 8, 35)          # a Tuesday, five minutes after the 08:30 slot
SLOT = datetime(2026, 10, 20, 8, 30)


def cfg(**kw):
    c = dict(name="t", frequency="daily", time="08:30", days=[], month_day="1", scopes=list(jobs.ALL_SCOPES), client_scope="Selected client only",
             enabled=True, clients=["c-rajesh.menon", "c-ananya.singh", "c-neha.prakash"])
    c.update(kw)
    return c


def login(repo, email, role="RM"):
    u, err = auth.authenticate(repo, email, "atlas-demo", role)
    assert u, err
    return u


def put_quotes(repo):
    now = utcnow()
    for sym, kind, chg in (("SPY", "etf", 0.004), ("AGG", "etf", -0.002), ("VNQ", "etf", 0.001), ("^GSPC", "index", 0.004)):
        repo.save_quote(MarketQuote(symbol=sym, name=sym, kind=kind, price=100 * (1 + chg), currency="USD", prev_close=100.0, change_abs=100 * chg, change_pct=chg * 100,
                                    market_time=now - timedelta(seconds=20), retrieved_at=now, provider="yahoo", provider_name="Yahoo Finance chart data (unofficial)",
                                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/" + sym, session_start=now - timedelta(hours=2), session_end=now + timedelta(hours=4),
                                    transformation="change = price - previous session close"))
    repo.s.commit()


def schedule(repo, who="priya.sharma@atlas-demo.com", saved_days_ago=3, **kw):
    u = login(repo, who, "Admin" if who.startswith("admin") else "RM")
    services.save_schedule(repo, u, cfg(**kw))
    repo.s.execute(text("update schedules set saved_at=:t where owner_email=:e"), dict(t=NOW - timedelta(days=saved_days_ago), e=who))
    repo.s.commit()
    return u


@pytest.fixture()
def ready(repo, db_url, monkeypatch):
    """A seeded DB with fresh cached quotes and the network refresh stubbed out (jobs must not touch the internet in tests)."""
    put_quotes(repo)
    monkeypatch.setattr(services, "refresh_external_data", lambda *a, **k: "refresh skipped in test")
    return repo


def due(db_url, repo, now=NOW, **kw):
    repo.s.commit()
    return run_due(now=now, llm=TemplateLLM(), url=db_url, **kw)


# =============================================================== slot arithmetic
CASES = [
    (dict(frequency="daily", time="08:30"), datetime(2026, 10, 20, 8, 35), datetime(2026, 10, 20, 8, 30), datetime(2026, 10, 21, 8, 30)),
    (dict(frequency="daily", time="08:30"), datetime(2026, 10, 20, 8, 29), datetime(2026, 10, 19, 8, 30), datetime(2026, 10, 20, 8, 30)),
    (dict(frequency="weekly", time="08:30", days=["Mon", "Wed", "Fri"]), datetime(2026, 10, 20, 9, 0), datetime(2026, 10, 19, 8, 30), datetime(2026, 10, 21, 8, 30)),
    (dict(frequency="weekly", time="23:59", days=["Sun"]), datetime(2026, 10, 20, 0, 0), datetime(2026, 10, 18, 23, 59), datetime(2026, 10, 25, 23, 59)),
    (dict(frequency="monthly", time="06:00", month_day="1"), datetime(2026, 10, 20, 7, 0), datetime(2026, 10, 1, 6, 0), datetime(2026, 11, 1, 6, 0)),
    (dict(frequency="monthly", time="06:00", month_day="last"), datetime(2026, 2, 28, 5, 0), datetime(2026, 1, 31, 6, 0), datetime(2026, 2, 28, 6, 0)),
    (dict(frequency="monthly", time="06:00", month_day="28"), datetime(2026, 12, 31, 12, 0), datetime(2026, 12, 28, 6, 0), datetime(2027, 1, 28, 6, 0)),
]


@pytest.mark.parametrize("c,now,prev,nxt", CASES)
def test_slot_arithmetic(c, now, prev, nxt):
    assert latest_slot(c, now) == prev and next_slot(c, now) == nxt


def test_slot_edge_cases():
    assert latest_slot(dict(frequency="weekly", time="08:30", days=[]), NOW) is None
    assert latest_slot(dict(frequency="daily", time="garbage"), NOW) == datetime(2026, 10, 20, 8, 30)          # bad time falls back, never crashes
    assert latest_slot(dict(frequency="daily", time="08:30"), NOW) == latest_slot(dict(frequency="daily", time="08:30"), NOW)


# =============================================================== real execution
def test_due_schedule_runs_the_agent_once_and_records_it(ready, db_url):
    schedule(ready)
    out = due(db_url, ready)
    assert len(out) == 1 and out[0].status == "completed" and (out[0].ok, out[0].paused, out[0].failed) == (2, 1, 0)
    with dbsession.session_scope(db_url) as s:
        r = Repo(s)
        j = r.list_jobs("priya.sharma@atlas-demo.com")[0]
        assert j["slot"] == SLOT and j["trigger"] == "scheduled" and j["total"] == 3 and j["finished_at"] and j["freshness"]
        items = {i["client_id"]: i for i in r.job_items(j["id"])}
        assert items["c-rajesh.menon"]["status"] == "ok" and items["c-neha.prakash"]["status"] == "paused"            # no consent: paused, not failed
        assert r.latest_proposal("c-rajesh.menon")["status"] == "awaiting_rm"                                       # a review item exists
        assert r.get_run(items["c-rajesh.menon"]["agent_run_id"])["trigger"] == "schedule"
        actions = [e.action for e in r.list_audit(limit=60)]
        assert "Scheduled job started" in actions and "Job completed" in actions


def test_same_slot_is_never_executed_twice(ready, db_url):
    schedule(ready)
    assert len(due(db_url, ready)) == 1
    assert due(db_url, ready) == [] and due(db_url, ready, now=NOW + timedelta(minutes=10)) == []
    with dbsession.session_scope(db_url) as s:
        assert len(Repo(s).list_jobs()) == 1


def test_not_before_the_schedule_was_saved_and_not_when_disabled(ready, db_url):
    schedule(ready, saved_days_ago=0)
    ready.s.execute(text("update schedules set saved_at=:t"), dict(t=NOW))                  # saved after the 08:30 slot
    ready.s.commit()
    assert due(db_url, ready) == []
    schedule(ready, enabled=False)
    assert due(db_url, ready) == []


def test_missed_slot_is_recorded_not_run_late(ready, db_url):
    schedule(ready)
    out = due(db_url, ready, now=SLOT + timedelta(hours=config.JOB_GRACE_HOURS, minutes=5))
    assert out[0].status == "missed"
    assert due(db_url, ready, now=SLOT + timedelta(hours=8)) == []                            # no duplicate 'missed' row
    with dbsession.session_scope(db_url) as s:
        r = Repo(s)
        j = r.list_jobs()[0]
        assert j["status"] == "missed" and "Missed" in j["message"] and r.job_items(j["id"]) == []
        assert r.list_runs("c-rajesh.menon") == []                                           # nothing was analysed


def test_scopes_control_what_a_job_produces(ready, db_url):
    schedule(ready, scopes=["Portfolio drift", "Goal progress"], clients=["c-rajesh.menon"])
    assert due(db_url, ready)[0].status == "completed"
    with dbsession.session_scope(db_url) as s:
        r = Repo(s)
        assert r.latest_proposal("c-rajesh.menon") is None                                    # analysis only: no draft recommendation
        run = r.get_run(r.list_runs("c-rajesh.menon")[0]["id"])
        assert [x["status"] for x in run["steps"] if x["name"] in ("scenarios", "news_interpretation", "draft")] == ["skipped"] * 3
        assert any(e["kind"] == "engine" for e in run["evidence"])
    schedule(ready, scopes=list(jobs.ALL_SCOPES), clients=["c-ananya.singh"])
    ready.s.commit()
    run_due(now=NOW + timedelta(days=1), llm=TemplateLLM(), url=db_url)
    with dbsession.session_scope(db_url) as s:
        assert Repo(s).latest_proposal("c-ananya.singh") is not None


@pytest.mark.parametrize("scope,expected", [("All assigned clients", 24), ("Clients flagged for review", 18), ("Tier 1 clients only", 24)])
def test_client_scope_filters(ready, scope, expected):
    priya = login(ready, "priya.sharma@atlas-demo.com")
    clients, problems = jobs.scope_clients(ready, priya, cfg(client_scope=scope))
    assert len(clients) == expected and not problems


def test_jobs_never_approve_trade_or_send(ready, db_url):
    schedule(ready)
    due(db_url, ready)
    with dbsession.session_scope(db_url) as s:
        r = Repo(s)
        for cid in ("c-rajesh.menon", "c-ananya.singh"):
            p = r.latest_proposal(cid)
            assert p["status"] in ("awaiting_rm", "digest") and r.approvals_for(p["id"]) == []
            assert r.get_draft(cid) is None or r.get_draft(cid)["status"] != "Sent"


# =============================================================== permissions and scope at EXECUTION time
def test_revoked_permission_skips_the_job_visibly(ready, db_url):
    schedule(ready)
    admin = login(ready, "admin@atlas-demo.com", "Admin")
    services.save_rm_permissions(ready, admin, "Priya Sharma", False, False, "Tier 1", False)
    ready.s.commit()
    out = run_due(now=NOW, llm=TemplateLLM(), url=db_url)
    assert out[0].status == "skipped"
    with dbsession.session_scope(db_url) as s:
        r = Repo(s)
        j = r.list_jobs()[0]
        assert j["status"] == "skipped" and "revoked" in j["message"] and r.list_runs("c-rajesh.menon") == []
        assert any(e.action == "Scheduled job skipped" for e in r.list_audit(limit=20))


def test_client_scope_is_rechecked_when_the_job_runs(ready, db_url):
    admin = login(ready, "admin@atlas-demo.com", "Admin")
    services.save_rm_permissions(ready, admin, "Priya Sharma", True, True, "Tier 1", False)         # all-clients granted at save time
    schedule(ready, clients=["c-rajesh.menon", "c-ramesh.agarwal"])
    services.save_rm_permissions(ready, admin, "Priya Sharma", True, False, "Tier 1", False)        # ...then revoked before the run
    ready.s.commit()
    out = run_due(now=NOW, llm=TemplateLLM(), url=db_url)
    assert out[0].status == "partial" and (out[0].ok, out[0].failed) == (1, 1)
    with dbsession.session_scope(db_url) as s:
        bad = [i for i in Repo(s).job_items(out[0].job_id) if i["status"] == "failed"][0]
        assert bad["client_id"] == "c-ramesh.agarwal" and "outside the scope" in bad["error"]
        assert Repo(s).list_runs("c-ramesh.agarwal") == []                                       # the other RM's client was never touched


def test_rm_cannot_run_or_save_without_permission(ready):
    admin = login(ready, "admin@atlas-demo.com", "Admin")
    services.save_rm_permissions(ready, admin, "Priya Sharma", False, False, "Tier 1", False)
    priya = login(ready, "priya.sharma@atlas-demo.com")
    with pytest.raises(services.Denied):
        services.run_now(ready, priya, cfg())
    with pytest.raises(services.Denied):
        services.save_schedule(ready, priya, cfg())
    client = login(ready, "ramesh.agarwal@atlas-demo.com", "Client")
    with pytest.raises(services.Denied):
        services.run_now(ready, client, cfg())


# =============================================================== locks, duplicates, budgets, failure and retry
def test_overlapping_run_is_refused(ready, db_url):
    schedule(ready)
    assert ready.acquire_lock("schedule:priya.sharma@atlas-demo.com", "other-worker", 600)
    ready.s.commit()
    out = run_due(now=NOW, llm=TemplateLLM(), url=db_url)
    assert out[0].status == "locked" and out[0].skipped
    with dbsession.session_scope(db_url) as s:
        assert Repo(s).list_jobs() == []                                                         # slot not consumed: a later tick will run it
    priya = login(ready, "priya.sharma@atlas-demo.com")
    with pytest.raises(ValueError):
        services.run_now(ready, priya, cfg())


def test_expired_lock_does_not_block_forever(ready):
    assert ready.acquire_lock("k", "a", 600)
    assert not ready.acquire_lock("k", "b", 600)
    ready.s.execute(text("update job_locks set expires_at=:t"), dict(t=utcnow() - timedelta(seconds=1)))
    assert ready.acquire_lock("k", "b", 600)


def test_duplicate_slot_is_blocked_by_the_database(ready):
    assert ready.create_job("j1", "a@x.com", "A", "scheduled", SLOT, [], "", 1)
    assert not ready.create_job("j2", "a@x.com", "A", "scheduled", SLOT, [], "", 1)
    assert ready.create_job("j3", "a@x.com", "A", "manual", None, [], "", 1) and ready.create_job("j4", "a@x.com", "A", "manual", None, [], "", 1)   # manual runs may repeat


def test_failure_is_recorded_retried_in_call_and_on_later_ticks(ready, db_url, monkeypatch):
    schedule(ready)
    real = jobs.run_monitoring
    calls = {"n": 0}

    def flaky(repo, user, cid, **kw):
        if cid == "c-ananya.singh":
            calls["n"] += 1
            raise RuntimeError("provider exploded")
        return real(repo, user, cid, **kw)
    monkeypatch.setattr(jobs, "run_monitoring", flaky)
    out = due(db_url, ready)
    assert out[0].status == "partial" and out[0].failed == 1 and calls["n"] == 2                 # one immediate retry inside the job
    with dbsession.session_scope(db_url) as s:
        j = Repo(s).list_jobs()[0]
        bad = [i for i in Repo(s).job_items(j["id"]) if i["status"] == "failed"][0]
        assert "provider exploded" in bad["error"] and j["attempts"] == 1
    # next tick: still broken -> attempt 2 (only the failed client is retried; the others are not re-run)
    out2 = due(db_url, ready, now=NOW + timedelta(minutes=15))
    assert out2[0].status == "partial" and calls["n"] == 4
    # fixed: attempt 3 succeeds and the job becomes completed
    monkeypatch.setattr(jobs, "run_monitoring", real)
    out3 = due(db_url, ready, now=NOW + timedelta(minutes=30))
    assert out3[0].status == "completed" and out3[0].failed == 0
    with dbsession.session_scope(db_url) as s:
        j = Repo(s).list_jobs()[0]
        assert j["attempts"] == 3 and j["status"] == "completed" and j["ok"] == 2
    assert due(db_url, ready, now=NOW + timedelta(minutes=45)) == []                              # finished: no more retries


def test_retries_stop_at_the_attempt_limit(ready, db_url, monkeypatch):
    schedule(ready, clients=["c-ananya.singh"])
    monkeypatch.setattr(jobs, "run_monitoring", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("always down")))
    for i in range(config.JOB_MAX_ATTEMPTS + 2):
        due(db_url, ready, now=NOW + timedelta(minutes=15 * i))
    with dbsession.session_scope(db_url) as s:
        j = Repo(s).list_jobs()[0]
        assert j["status"] == "failed" and j["attempts"] == config.JOB_MAX_ATTEMPTS               # visible failure, bounded retries


def test_time_budget_and_client_cap_are_enforced(ready, db_url, monkeypatch):
    schedule(ready, client_scope="All assigned clients")
    monkeypatch.setattr(config, "JOB_MAX_CLIENTS", 3)
    out = due(db_url, ready)
    assert out[0].status == "partial" and out[0].ok + out[0].paused == 3 and out[0].not_run == 21
    schedule(ready, client_scope="All assigned clients")
    monkeypatch.setattr(config, "JOB_MAX_CLIENTS", 50); monkeypatch.setattr(config, "JOB_TIME_BUDGET_S", -1)
    out2 = run_due(now=NOW + timedelta(days=1), llm=TemplateLLM(), url=db_url)
    assert out2[0].status == "failed" and out2[0].not_run == 24


def test_data_refresh_failure_is_survived_and_reported(repo, db_url, monkeypatch):
    schedule(repo)                                                                                  # no cached quotes at all
    monkeypatch.setattr(services, "refresh_external_data", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network down")))
    out = due(db_url, repo)
    assert out[0].status == "completed"
    with dbsession.session_scope(db_url) as s:
        r = Repo(s)
        j = r.list_jobs()[0]
        assert "refresh failed" in j["freshness"]["refresh"]
        assert {i["status"] for i in r.job_items(j["id"])} == {"paused"}                          # missing data: agents abstained, nothing invented


def test_schedules_and_history_survive_a_restart(ready, db_url):
    schedule(ready)
    due(db_url, ready)
    dbsession._engines.pop(db_url).dispose()
    with dbsession.session_scope(db_url) as s:
        r = Repo(s)
        assert r.get_schedule("priya.sharma@atlas-demo.com")["name"] == "t" and r.list_jobs()[0]["status"] == "completed"


def test_reused_runs_report_their_real_outcome(ready):
    """A repeated 'Run now' reuses identical earlier runs; a paused client must still be counted as paused, not ok."""
    priya = login(ready, "priya.sharma@atlas-demo.com")
    c = cfg(clients=["c-rajesh.menon", "c-neha.prakash"])
    first = run_job(ready, priya, c, trigger="manual", llm=TemplateLLM(), refresh=False)
    second = run_job(ready, priya, c, trigger="manual", llm=TemplateLLM(), refresh=False)
    assert (first.ok, first.paused) == (1, 1) and (second.ok, second.paused) == (1, 1)
    assert any("reused" in i["error"] for i in second.items)


# =============================================================== admin schedule, manual run, UI
def test_admin_schedule_runs_for_all_clients(ready, db_url):
    schedule(ready, who="admin@atlas-demo.com", client_scope="Selected client only", clients=["c-rajesh.menon", "c-k01"])
    out = due(db_url, ready)
    assert out[0].ok == 2


def test_manual_run_now_is_recorded_and_visible_in_the_ui(ready):
    s = controller.new_session()
    controller.handle(ready, s, dict(id="1", action="login", payload=dict(email="priya.sharma@atlas-demo.com", password="atlas-demo", role="RM")))
    ready.s.commit()
    html = controller.build(ready, s)["html"]
    assert "Run now" in html and "Run preview now" in html and "No job runs recorded yet" in html
    controller.handle(ready, s, dict(id="2", action="run_now", payload=dict(cfg=cfg(clients=["c-rajesh.menon"]))))
    ready.s.commit()
    assert "Run completed" in s["effect"]["toast"] and "nothing was approved" in s["effect"]["toast"]
    html = controller.build(ready, s)["html"]
    assert "manual" in html and "completed" in html and "1 clients: 1 ok" in html and "Next scheduled run" in html


def test_preview_is_a_dry_run(ready):
    priya = login(ready, "priya.sharma@atlas-demo.com")
    msg = services.run_preview(ready, priya, cfg(client_scope="All assigned clients"))
    assert "24 clients in scope" in msg and "2 would be paused" in msg and "No agents were executed" in msg
    assert ready.list_jobs() == [] and ready.list_runs("c-rajesh.menon") == []


def test_job_history_visibility(ready, db_url):
    schedule(ready)
    due(db_url, ready)
    arjun = login(ready, "arjun.mehta@atlas-demo.com")
    assert services.scheduler_view(ready, arjun, None)["jobs"] == []                             # another RM sees nothing of Priya's jobs
    admin = login(ready, "admin@atlas-demo.com", "Admin")
    assert len(services.scheduler_view(ready, admin, None)["jobs"]) == 1


# =============================================================== the worker process, for real
from conftest import sqlite_only  # noqa: E402


@sqlite_only
def test_worker_process_executes_due_schedules(tmp_path, template_db):
    import shutil
    db = tmp_path / "worker.sqlite3"
    shutil.copy(template_db, db)
    url = f"sqlite:///{db.as_posix()}"
    with dbsession.session_scope(url) as s:
        r = Repo(s)
        put_quotes(r)
        u = login(r, "priya.sharma@atlas-demo.com")
        services.save_schedule(r, u, cfg(time=(utcnow() - timedelta(minutes=5)).strftime("%H:%M"), clients=["c-rajesh.menon"]))   # a slot 5 minutes ago, in real time
        r.s.execute(text("update schedules set saved_at=:t"), dict(t=datetime(2020, 1, 1)))
    env = dict(os.environ, DATABASE_URL=url, DWN_ENV="dev", DWN_SEED_DEMO="0", DWN_JOB_SKIP_REFRESH="1", DWN_LLM_PROVIDER="template")
    p = subprocess.run([sys.executable, str(ROOT / "worker" / "run_scheduled.py"), "--once"], capture_output=True, text=True, env=env, timeout=120, cwd=str(ROOT))
    assert p.returncode == 0, p.stderr[-500:]
    assert '"status": "completed"' in p.stdout
    p2 = subprocess.run([sys.executable, str(ROOT / "worker" / "run_scheduled.py"), "--once"], capture_output=True, text=True, env=env, timeout=120, cwd=str(ROOT))
    assert '"status": "nothing due"' in p2.stdout                                                  # second tick: slot already done
    with dbsession.session_scope(url) as s:
        assert len(Repo(s).list_jobs()) == 1
    dbsession._engines.pop(url, None)
