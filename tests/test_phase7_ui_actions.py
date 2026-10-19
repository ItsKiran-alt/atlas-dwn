"""Every UI action goes through the controller at least once, per role, with the effects checked. Catches dead buttons and server-side errors."""
import pytest

from dwn import services
from dwn.domain import utcnow
from dwn.ui import controller


def sess_for(repo, email, role="RM"):
    s = controller.new_session()
    controller.handle(repo, s, dict(id="login-" + email, action="login", payload=dict(email=email, password="atlas-demo", role=role)))
    assert s["email"] == email
    return s


def ev(repo, sess, action, **payload):
    controller.handle(repo, sess, dict(id=f"{action}-{utcnow().timestamp()}", action=action, payload=payload))
    repo.s.commit()
    return sess["effect"] or {}


CFG = dict(name="x", frequency="weekly", time="08:30", days=["Mon"], month_day="1", scopes=["Portfolio drift"], client_scope="All assigned clients", enabled=True, clients=[])


def test_rm_actions(repo, monkeypatch):
    monkeypatch.setattr(services, "external_data_is_stale", lambda r: False)
    monkeypatch.setattr(services, "refresh_external_data", lambda *a, **k: "refreshed (stub)")
    s = sess_for(repo, "priya.sharma@atlas-demo.com")
    assert "Selected" in ev(repo, s, "select_client", id="c-ananya.singh")["toast"]
    assert ev(repo, s, "select_client", id="c-rajesh.menon", review=True)["open_modal"] == "reviewModal"
    assert ev(repo, s, "select_client", id="c-rajesh.menon", goto="clientview")["view"] == "clientview"
    assert "consent request" in ev(repo, s, "request_consent")["toast"].lower()
    assert "saved" in ev(repo, s, "save_note", text="n")["toast"].lower()
    assert "ready" in ev(repo, s, "mark_draft_ready", subject="s", body="b")["toast"]
    assert "saved" in ev(repo, s, "save_pref", pref="Email (approved channel)")["toast"].lower()
    assert "Sources:" in ev(repo, s, "ask", question="why flagged for drift")["ask_answer"]
    assert "ask_answer" in ev(repo, s, "detail", what="goal") and "not connected" in ev(repo, s, "detail", what="market")["toast"]
    assert "awaiting review" in ev(repo, s, "reminders")["toast"]
    d = ev(repo, s, "export_queue")["download"]
    assert d["filename"] == "client-queue.csv" and "Rajesh Menon" in d["content"]
    r = ev(repo, s, "report", template="Quarterly portfolio review")["download"]
    assert r["filename"].endswith(".md") and "Rajesh Menon" in r["content"]
    assert "Unknown report template" in ev(repo, s, "report", template="../../etc/passwd")["toast"]
    assert "Tier" in ev(repo, s, "run_agent")["toast"] or "Paused" in s["effect"]["toast"]
    assert "refreshed" in ev(repo, s, "market_refresh")["toast"] and set(ev(repo, s, "market_refresh_if_stale")) <= {"id"}
    assert "Preview" in ev(repo, s, "run_preview", cfg=CFG)["toast"]
    assert "Schedule saved" in ev(repo, s, "save_schedule", cfg=CFG)["toast"]
    assert "Run " in ev(repo, s, "run_now", cfg=dict(CFG, client_scope="Selected client only", clients=["c-ananya.singh"]))["toast"]
    assert "view" not in ev(repo, s, "nav", view="home")                                # unknown actions are harmless
    for forbidden in ("export_audit", "save_perms", "load_perms"):
        assert "not available for your role" in ev(repo, s, forbidden, rm="Priya Sharma", schedule=True, approval="Tier 3")["toast"]
    assert "not available for your role" in ev(repo, s, "source", id="salesforce", on=False)["toast"]
    assert ev(repo, s, "logout") is not None and s["email"] is None


def test_admin_actions(repo):
    s = sess_for(repo, "admin@atlas-demo.com", "Admin")
    assert "Preview" in ev(repo, s, "run_preview", cfg=CFG)["toast"]
    assert ev(repo, s, "load_perms", rm="Arjun Mehta") is not None and s["perm_rm"] == "rm-arjun"
    assert "saved" in ev(repo, s, "save_perms", rm="Neha Kapoor", schedule=True, all_clients=True, approval="Tier 2", override=False)["toast"]
    assert "Data source" in ev(repo, s, "source", id="salesforce", on=False)["toast"] and "Data source" in ev(repo, s, "source", id="salesforce", on=True)["toast"]
    assert "Unknown data source" in ev(repo, s, "source", id="nope", on=True)["toast"]
    d = ev(repo, s, "export_audit")["download"]
    assert d["filename"] == "audit-log.csv" and "Sign-in" in d["content"]
    assert "not available for your role" in ev(repo, s, "save_note", text="x")["toast"]
    assert "not available for your role" in ev(repo, s, "request_consent")["toast"]


def test_client_actions_and_onboarding(repo):
    s = sess_for(repo, "ramesh.agarwal@atlas-demo.com", "Client")
    assert "withdrawn" in ev(repo, s, "withdraw_consent")["toast"]
    assert "already withdrawn" in ev(repo, s, "withdraw_consent")["toast"]
    assert "accept" in ev(repo, s, "regrant_consent", terms=False, ai=True)["toast"].lower()
    assert "Thank you" in ev(repo, s, "regrant_consent", terms=True, ai=True)["toast"]
    assert "already active" in ev(repo, s, "regrant_consent", terms=True, ai=True)["toast"]
    for rm_only in ("run_agent", "save_review", "request_consent", "export_queue", "run_now"):
        toast = ev(repo, s, rm_only, cfg=CFG, note="n", decision="approve", tier="Tier 1 — RM approval", target="60", rationale="")["toast"]
        assert any(p in toast for p in ("not available for your role", "has not enabled scheduling", "not authorised")), (rm_only, toast)
    # onboarding: mismatch, missing ticks, success
    o = controller.new_session()
    controller.handle(repo, o, dict(id="o1", action="start_signup", payload={}))
    assert o["onboarding"] is True
    assert "do not match" in ev(repo, o, "accept_consent", email="z@example.com", password="a-long-password-1", password2="different-pw-123", terms=True, ai=True)["toast"]
    assert "accept both" in ev(repo, o, "accept_consent", email="z@example.com", password="a-long-password-1", password2="a-long-password-1", terms=True, ai=False)["toast"].lower()
    assert "Account created" in ev(repo, o, "accept_consent", email="z@example.com", password="a-long-password-1", password2="a-long-password-1", terms=True, ai=True)["toast"]
    assert o["email"] == "z@example.com" and o["onboarding"] is False


def test_unknown_and_unauthenticated_actions_do_nothing(repo):
    anon = controller.new_session()
    for act in ("save_review", "run_agent", "export_queue", "save_perms", "source", "run_now", "withdraw_consent", "select_client"):
        controller.handle(repo, anon, dict(id="a-" + act, action=act, payload={"id": "c-rajesh.menon", "rm": "Priya Sharma"}))
        assert anon["email"] is None and (anon["effect"] is None or "download" not in anon["effect"])
    s = sess_for(repo, "priya.sharma@atlas-demo.com")
    assert set(ev(repo, s, "definitely_not_an_action")) <= {"id"}
    controller.handle(repo, s, dict(id="garbage", action=None, payload=None, ui=None))
    controller.handle(repo, s, dict(id="garbage2", action="select_client", payload={"id": ["not", "a", "string"]}))
    assert s["email"] == "priya.sharma@atlas-demo.com"                                      # malformed events never crash or log the user out


def test_login_failures_and_role_mismatch_via_controller(repo):
    s = controller.new_session()
    assert "Incorrect email or password" in ev(repo, s, "login", email="priya.sharma@atlas-demo.com", password="nope", role="RM")["toast"]
    assert "not a Admin account" in ev(repo, s, "login", email="priya.sharma@atlas-demo.com", password="atlas-demo", role="Admin")["toast"]
    assert s["email"] is None
