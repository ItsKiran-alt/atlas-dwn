"""Phase 3 tests: database persistence, migrations, authentication, RBAC isolation, consent, audit. No network, no LLM."""
import importlib
import inspect
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dwn import auth, bootstrap, config, security, services
from dwn.db import session as dbsession
from dwn.domain import CONSENT_VERSION
from dwn.repo import Repo
from dwn.ui import controller

PW = "atlas-demo"


def login(repo, email, role):
    u, err = auth.authenticate(repo, email, PW, role)
    assert u, err
    return u


def sess_for(repo, email, role):
    s = controller.new_session()
    controller.handle(repo, s, dict(id="t", action="login", payload=dict(email=email, password=PW, role=role)))
    assert s["email"] == email, s["effect"]
    return s


def event(repo, sess, action, **payload):
    controller.handle(repo, sess, dict(id=str(time.time()), action=action, payload=payload))
    repo.s.commit()                     # in the app each event is its own transaction (session_scope)
    return sess["effect"] or {}


# ---------------- migrations & persistence ----------------
from conftest import sqlite_only  # noqa: E402


@sqlite_only
def test_migration_creates_schema_and_round_trips(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.sqlite3').as_posix()}"
    dbsession.run_migrations(url)
    eng = dbsession.get_engine(url)
    with eng.connect() as c:
        tables = {r[0] for r in c.execute(text("select name from sqlite_master where type='table'"))}
    assert {"users", "clients", "consents", "audit_events", "recommendations", "schedules", "rm_permissions", "data_sources"} <= tables
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(config.ROOT / "alembic.ini")); cfg.set_main_option("script_location", str(config.ROOT / "alembic")); cfg.attributes["url"] = url
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng.dispose()


def test_seed_is_idempotent_and_complete(repo):
    n = repo.client_count()
    assert n == 37                                              # 24 prototype + 12 golden + Ramesh
    bootstrap.seed_demo(repo)                                   # second run must not duplicate or overwrite
    assert repo.client_count() == n and len(repo.list_rms()) == 3
    assert all(c.aum_musd >= 2.0 for c in repo.list_clients(include_all=True))


def test_state_survives_restart(db_url):
    with dbsession.session_scope(db_url) as s:
        r = Repo(s)
        priya = login(r, "priya.sharma@atlas-demo.com", "RM")
        services.save_rm_decision(r, priya, "c-rajesh.menon", "persist me", "approve", "Tier 1 — RM approval", 60, "")
        services.save_schedule(r, priya, dict(name="persisted", frequency="daily", time="07:00", days=[], month_day="1", scopes=["Portfolio drift"],
                                              client_scope="All assigned clients", enabled=True, clients=[]))
    dbsession._engines.pop(db_url).dispose()                   # simulate an app restart: drop engine and connections
    with dbsession.session_scope(db_url) as s:
        r = Repo(s)
        assert r.get_rec("c-rajesh.menon").status == "RM reviewed" and r.get_rec("c-rajesh.menon").decided_by == "Priya Sharma"
        assert r.get_schedule("priya.sharma@atlas-demo.com")["name"] == "persisted"
        assert any(e.action == "RM decision: approve" for e in r.list_audit())


def test_audit_log_is_append_only(repo):
    repo.log("X", "test event", "tester", "d", "Logged", "System")
    repo.s.commit()
    with pytest.raises(DBAPIError):
        repo.s.execute(text("UPDATE audit_events SET action='tampered'"))
    repo.s.rollback()
    with pytest.raises(DBAPIError):
        repo.s.execute(text("DELETE FROM audit_events"))
    repo.s.rollback()


# ---------------- configuration ----------------
def test_prod_requires_database_url_and_does_not_seed_by_default(monkeypatch):
    monkeypatch.setenv("DWN_ENV", "prod"); monkeypatch.delenv("DATABASE_URL", raising=False); monkeypatch.delenv("DWN_SEED_DEMO", raising=False)
    monkeypatch.delenv("DWN_DEMO_PASSWORD", raising=False)
    cfg = importlib.reload(config)
    try:
        with pytest.raises(RuntimeError):
            cfg.database_url()
        assert cfg.seed_demo_data() is False
        with pytest.raises(RuntimeError):
            cfg.demo_password()
    finally:
        monkeypatch.delenv("DWN_ENV")
        importlib.reload(config)


# ---------------- authentication ----------------
def test_passwords_are_hashed_not_stored(repo):
    stored = repo.password_hash("priya.sharma@atlas-demo.com")
    assert stored.startswith("pbkdf2_sha256$") and PW not in stored
    assert security.verify_password(PW, stored) and not security.verify_password("wrong", stored)
    assert security.hash_password("x") != security.hash_password("x")      # random salt


def test_wrong_password_role_and_unknown_user(repo):
    assert auth.authenticate(repo, "priya.sharma@atlas-demo.com", "nope", "RM")[0] is None
    assert auth.authenticate(repo, "priya.sharma@atlas-demo.com", PW, "Admin")[0] is None
    assert auth.authenticate(repo, "ghost@x.com", PW, "RM")[0] is None
    assert all(e.status == "Rejected" for e in repo.list_audit(limit=3))


def test_lockout_after_repeated_failures(repo):
    for _ in range(config.MAX_FAILED_LOGINS):
        assert auth.authenticate(repo, "arjun.mehta@atlas-demo.com", "bad", "RM")[0] is None
    u, err = auth.authenticate(repo, "arjun.mehta@atlas-demo.com", PW, "RM")      # correct password, but locked
    assert u is None and "Too many failed attempts" in err
    assert any("locked" in e.details.lower() for e in repo.list_audit(limit=10))


def test_success_resets_failure_counter(repo):
    for _ in range(config.MAX_FAILED_LOGINS - 1):
        auth.authenticate(repo, "neha.kapoor@atlas-demo.com", "bad", "RM")
    assert auth.authenticate(repo, "neha.kapoor@atlas-demo.com", PW, "RM")[0]
    for _ in range(config.MAX_FAILED_LOGINS - 1):
        auth.authenticate(repo, "neha.kapoor@atlas-demo.com", "bad", "RM")
    assert auth.authenticate(repo, "neha.kapoor@atlas-demo.com", PW, "RM")[0]     # still not locked


def test_logout_clears_session_and_audits(repo):
    s = sess_for(repo, "priya.sharma@atlas-demo.com", "RM")
    event(repo, s, "logout")
    assert s["email"] is None and controller.user_of(repo, s) is None
    html = controller.build(repo, s)["html"]
    assert "loginGate" in html and "Rajesh" not in html
    assert any(e.action == "Sign-out" for e in repo.list_audit(limit=5))


def test_idle_session_expires(repo, monkeypatch):
    s = sess_for(repo, "priya.sharma@atlas-demo.com", "RM")
    s["last_active"] -= config.SESSION_IDLE_MINUTES * 60 + 5
    eff = event(repo, s, "select_client", id="c-rajesh.menon")
    assert s["email"] is None and "expired" in eff["toast"]


# ---------------- isolation (enforced in SQL and services) ----------------
def test_rm_sees_only_own_clients_at_query_level(repo):
    priya = login(repo, "priya.sharma@atlas-demo.com", "RM")
    arjun = login(repo, "arjun.mehta@atlas-demo.com", "RM")
    neha = login(repo, "neha.kapoor@atlas-demo.com", "RM")
    assert len(services.clients_for(repo, priya)) == 24
    assert len(services.clients_for(repo, arjun)) == 13
    assert services.clients_for(repo, neha) == []
    assert not {c.id for c in services.clients_for(repo, priya)} & {c.id for c in services.clients_for(repo, arjun)}
    with pytest.raises(services.Denied):
        services.get_client(repo, priya, "c-ramesh.agarwal")
    with pytest.raises(services.Denied):
        services.get_client(repo, neha, "c-rajesh.menon")


def test_client_cannot_read_other_clients(repo):
    ramesh = login(repo, "ramesh.agarwal@atlas-demo.com", "Client")
    with pytest.raises(services.Denied):
        services.get_client(repo, ramesh, "c-rajesh.menon")
    html = controller.build(repo, sess_for(repo, "ramesh.agarwal@atlas-demo.com", "Client"))["html"]
    assert "Ramesh Agarwal" in html and "Rajesh Menon" not in html and "Ananya" not in html


def test_forged_events_denied_and_audited(repo):
    s = sess_for(repo, "priya.sharma@atlas-demo.com", "RM")
    assert "not authorised" in event(repo, s, "select_client", id="c-ramesh.agarwal")["toast"]
    assert s["client_id"] != "c-ramesh.agarwal"
    assert "not available for your role" in event(repo, s, "save_perms", rm="Priya Sharma", schedule=True, all_clients=True, approval="Tier 3", override=True)["toast"]
    assert "not available for your role" in event(repo, s, "source", id="salesforce", on=False)["toast"]
    repo.s.commit()
    assert sum(1 for e in repo.list_audit(limit=20) if e.action == "Access denied") >= 3
    assert repo.get_perms("rm-priya")["approval"] == "Tier 1"               # nothing changed


def test_rm_html_contains_only_own_clients(repo):
    html = controller.build(repo, sess_for(repo, "priya.sharma@atlas-demo.com", "RM"))["html"]
    assert "Rajesh Menon" in html and "Helen Brooks" not in html and "Ramesh Agarwal" not in html


def test_role_workspaces_are_separate(repo):
    admin = controller.build(repo, sess_for(repo, "admin@atlas-demo.com", "Admin"))
    rm = controller.build(repo, sess_for(repo, "priya.sharma@atlas-demo.com", "RM"))
    client = controller.build(repo, sess_for(repo, "ramesh.agarwal@atlas-demo.com", "Client"))
    assert admin["allowed"] == ["compliance", "settings"] and "view-workbench" not in admin["html"]
    assert "view-workbench" in rm["html"] and "view-compliance" not in rm["html"] and "adminPermissions" not in rm["html"]
    assert client["allowed"] == ["clientportal"] and 'class="sidebar"' not in client["html"] and "<aside" not in client["html"]


def test_settings_is_in_main_content_beside_sidebar(repo):
    html = controller.build(repo, sess_for(repo, "priya.sharma@atlas-demo.com", "RM"))["html"]
    assert 'id="view-settings"' in html.split('<main class="main">')[1] and html.index("<aside") < html.index('<main class="main">')


def test_salesforce_primary_and_simulated(repo):
    html = controller.build(repo, sess_for(repo, "admin@atlas-demo.com", "Admin"))["html"]
    assert "Primary client source" in html and "Salesforce CRM (demo)" in html and "Connected · Simulated" in html and "Connected · Live" not in html


# ---------------- consent ----------------
def test_existing_client_never_sees_onboarding(repo):
    for email in ("ramesh.agarwal@atlas-demo.com", "ananya.singh@atlas-demo.com"):
        assert "view-onboarding" not in controller.build(repo, sess_for(repo, email, "Client"))["html"]


def test_new_client_onboarding_creates_account_and_versioned_consent_once(repo):
    with pytest.raises(ValueError):
        services.accept_onboarding_consent(repo, "n@example.com", "longenoughpw1", True, False)
    with pytest.raises(ValueError):
        services.accept_onboarding_consent(repo, "n@example.com", "short", True, True)
    u = services.accept_onboarding_consent(repo, "n@example.com", "longenoughpw1", True, True)
    info = repo.consent_info(u.client_id)
    assert info["active"] and info["version"] == CONSENT_VERSION and info["accepted_at"]
    assert repo.password_hash("n@example.com").startswith("pbkdf2_sha256$")
    with pytest.raises(ValueError):                                          # returning client is told to sign in, not re-consent
        services.accept_onboarding_consent(repo, "n@example.com", "longenoughpw1", True, True)
    assert repo.count_consents(u.client_id) == 1
    assert auth.authenticate(repo, "n@example.com", "longenoughpw1", "Client")[0]
    assert "view-onboarding" not in controller.build(repo, sess_for_pw(repo, "n@example.com", "longenoughpw1"))["html"]


def sess_for_pw(repo, email, pw):
    s = controller.new_session()
    controller.handle(repo, s, dict(id="p", action="login", payload=dict(email=email, password=pw, role="Client")))
    return s


def test_consent_withdrawal_pauses_monitoring_and_keeps_data(repo):
    ramesh = login(repo, "ramesh.agarwal@atlas-demo.com", "Client")
    priya = login(repo, "priya.sharma@atlas-demo.com", "RM")
    arjun = login(repo, "arjun.mehta@atlas-demo.com", "RM")
    with pytest.raises(services.Denied):
        services.withdraw_consent(repo, arjun, "c-ramesh.agarwal")           # RM cannot withdraw for a client
    services.withdraw_consent(repo, ramesh, ramesh.client_id)
    info = repo.consent_info(ramesh.client_id)
    assert not info["active"] and info["withdrawn_at"]
    assert repo.count_consents(ramesh.client_id) == 1                       # history retained, nothing deleted
    assert len(services.get_client(repo, ramesh, ramesh.client_id).holdings) == 6
    with pytest.raises(services.Denied):                                    # RM decisions blocked while paused
        services.save_rm_decision(repo, arjun, "c-ramesh.agarwal", "n", "approve", "Tier 1 — RM approval", 60, "")
    with pytest.raises(services.Denied):
        services.mark_draft_ready(repo, arjun, "c-ramesh.agarwal", "s", "b")
    services.regrant_consent(repo, ramesh, ramesh.client_id, True, True)
    assert repo.consent_info(ramesh.client_id)["active"] and repo.count_consents(ramesh.client_id) == 2
    services.save_rm_decision(repo, arjun, "c-ramesh.agarwal", "ok", "approve", "Tier 1 — RM approval", 60, "")


def test_clients_without_consent_cannot_be_approved(repo):
    priya = login(repo, "priya.sharma@atlas-demo.com", "RM")
    with pytest.raises(services.Denied):
        services.save_rm_decision(repo, priya, "c-neha.prakash", "n", "approve", "Tier 1 — RM approval", 60, "")


def test_client_portal_shows_consent_controls(repo):
    html = controller.build(repo, sess_for(repo, "ramesh.agarwal@atlas-demo.com", "Client"))["html"]
    assert "Withdraw consent" in html and "withdrawModal" in html
    s = sess_for(repo, "ramesh.agarwal@atlas-demo.com", "Client")
    event(repo, s, "withdraw_consent")
    html = controller.build(repo, s)["html"]
    assert "Give consent again" in html and "Withdrawn" in html


# ---------------- RM approvals ----------------
def test_rm_decision_needs_note_and_authority(repo):
    priya = login(repo, "priya.sharma@atlas-demo.com", "RM")
    with pytest.raises(ValueError):
        services.save_rm_decision(repo, priya, "c-rajesh.menon", "  ", "approve", "Tier 1 — RM approval", 60, "")
    with pytest.raises(services.Denied):
        services.save_rm_decision(repo, priya, "c-rajesh.menon", "ok", "approve", "Tier 3 — Investment committee", 60, "")
    r = services.save_rm_decision(repo, priya, "c-rajesh.menon", "ok", "approve", "Tier 1 — RM approval", 60, "")
    assert r.status == "RM reviewed" and r.decided_by == "Priya Sharma" and r.decided_at
    assert any(e.action == "RM decision: approve" for e in repo.list_audit())


def test_admin_cannot_record_rm_decision(repo):
    admin = login(repo, "admin@atlas-demo.com", "Admin")
    with pytest.raises(services.Denied):
        services.save_rm_decision(repo, admin, "c-rajesh.menon", "ok", "approve", "Tier 1 — RM approval", 60, "")


def test_no_execution_or_messaging_code_path():
    names = [n for n, _ in inspect.getmembers(services, inspect.isfunction)]
    assert not [n for n in names if any(w in n for w in ("execute", "trade", "order", "send", "transfer"))]


# ---------------- scheduler & admin ----------------
CFG = dict(name="x", frequency="weekly", time="08:30", days=["Mon"], month_day="1", scopes=["Portfolio drift"],
           client_scope="All assigned clients", enabled=True, clients=[])


def test_scheduler_permission_enforced_on_backend(repo):
    admin = login(repo, "admin@atlas-demo.com", "Admin")
    priya = login(repo, "priya.sharma@atlas-demo.com", "RM")
    services.save_schedule(repo, priya, CFG)
    assert repo.get_schedule(priya.email)["name"] == "x"
    services.save_rm_permissions(repo, admin, "Priya Sharma", False, False, "Tier 1", False)
    with pytest.raises(services.Denied):
        services.save_schedule(repo, priya, CFG)
    with pytest.raises(services.Denied):
        services.run_preview(repo, priya, CFG)
    assert "view-settings" not in controller.build(repo, sess_for(repo, "priya.sharma@atlas-demo.com", "RM"))["html"]


def test_rm_cannot_change_permissions_or_sources(repo):
    priya = login(repo, "priya.sharma@atlas-demo.com", "RM")
    with pytest.raises(services.Denied):
        services.save_rm_permissions(repo, priya, "Priya Sharma", True, True, "Tier 3", True)
    with pytest.raises(services.Denied):
        services.set_source(repo, priya, "salesforce", False)


def test_schedule_client_scope_is_enforced(repo):
    priya = login(repo, "priya.sharma@atlas-demo.com", "RM")
    with pytest.raises(services.Denied):
        services.save_schedule(repo, priya, dict(CFG, client_scope="Selected client only", clients=["c-ramesh.agarwal"]))
    with pytest.raises(ValueError):
        services.save_schedule(repo, priya, dict(CFG, client_scope="Selected client only", clients=[]))
    admin = login(repo, "admin@atlas-demo.com", "Admin")
    services.save_rm_permissions(repo, admin, "Priya Sharma", True, True, "Tier 1", False)
    services.save_schedule(repo, priya, dict(CFG, client_scope="Selected client only", clients=["c-ramesh.agarwal"]))


def test_schedule_validation(repo):
    priya = login(repo, "priya.sharma@atlas-demo.com", "RM")
    with pytest.raises(ValueError):
        services.save_schedule(repo, priya, dict(CFG, days=[]))
    with pytest.raises(ValueError):
        services.save_schedule(repo, priya, dict(CFG, frequency="hourly"))
    with pytest.raises(ValueError):
        services.save_schedule(repo, priya, dict(CFG, scopes=["Execute trades"]))


def test_preview_run_is_labelled_not_a_job(repo):
    priya = login(repo, "priya.sharma@atlas-demo.com", "RM")
    assert "No agents were executed" in services.run_preview(repo, priya, CFG)
    assert repo.last_run()["status"] == "Preview only"


def test_removing_salesforce_shows_warning(repo):
    admin = login(repo, "admin@atlas-demo.com", "Admin")
    services.set_source(repo, admin, "salesforce", False)
    assert "Salesforce CRM is not connected" in controller.build(repo, sess_for(repo, "admin@atlas-demo.com", "Admin"))["html"]


# ---------------- exports ----------------
def test_exports_are_scoped_and_formula_safe(repo):
    priya = login(repo, "priya.sharma@atlas-demo.com", "RM")
    csv_text = services.export_queue_csv(repo, priya)
    assert "Rajesh Menon" in csv_text and "Helen Brooks" not in csv_text
    with pytest.raises(services.Denied):
        services.export_audit_csv(repo, priya)
    assert services._csv_safe("=HYPERLINK(1)") == "'=HYPERLINK(1)"


# ---------------- golden set stays consistent ----------------
def test_golden_reference_engine_matches_authored_expectations():
    from reference_engine import evaluate
    from scenarios import CLIENTS, S
    bad = [s["id"] for s in S if evaluate(CLIENTS[s["client"]], s["event"])["tier"] != s["expected"]["tier"]]
    assert not bad
