"""Phase 7 security tests: output escaping, a full authorisation matrix, secret hygiene, error handling, production guards."""
import json
import logging
from datetime import timedelta

import pytest

from dwn import auth, bootstrap, config, services
from dwn.agents.llm import ScriptedLLM, TemplateLLM
from dwn.agents.orchestrator import run_monitoring
from dwn.data.http import Fetcher, Response
from dwn.data.market import AlphaVantageProvider, MarketService, YahooChartProvider
from dwn.data.models import MarketQuote
from dwn.data.news import FEEDS, parse_feed
from dwn.domain import utcnow
from dwn.ui import controller


def login(repo, email, role="RM"):
    u, err = auth.authenticate(repo, email, "atlas-demo", role)
    assert u, err
    return u


def sess_for(repo, email, role="RM"):
    s = controller.new_session()
    controller.handle(repo, s, dict(id="login-" + email, action="login", payload=dict(email=email, password="atlas-demo", role=role)))
    assert s["email"] == email
    return s


def event(repo, sess, action, **payload):
    controller.handle(repo, sess, dict(id=f"{action}-{utcnow().timestamp()}", action=action, payload=payload))
    repo.s.commit()
    return sess["effect"] or {}


def put_quotes(repo):
    now = utcnow()
    for sym, kind, chg in (("SPY", "etf", 0.004), ("AGG", "etf", -0.002), ("VNQ", "etf", 0.001), ("^GSPC", "index", 0.004)):
        repo.save_quote(MarketQuote(symbol=sym, name=sym, kind=kind, price=100 * (1 + chg), currency="USD", prev_close=100.0, change_abs=100 * chg, change_pct=chg * 100,
                                    market_time=now - timedelta(seconds=20), retrieved_at=now, provider="yahoo", provider_name="Yahoo Finance chart data (unofficial)",
                                    source_url="https://query1.finance.yahoo.com/v8/finance/chart/" + sym, session_start=now - timedelta(hours=2), session_end=now + timedelta(hours=4)))
    repo.s.commit()


# =============================================================== output escaping (XSS)
PAYLOADS = ['<img src=x onerror=alert(1)>', '<script>alert(1)</script>', '"><svg onload=alert(1)>', "' onmouseover='alert(1)", "</textarea><script>alert(2)</script>"]


def assert_clean(html: str):
    """Parse the page like a browser: no injected script/img/iframe tags and no injected event-handler attributes.
    (Escaped text such as '&lt;img onerror=...&gt;' parses as plain text, which is exactly what we want.)"""
    from html.parser import HTMLParser

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.bad = []

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "img", "iframe", "object", "embed", "link", "meta", "base"):
                self.bad.append(f"<{tag}>")
            for name, _ in attrs:
                if name in ("onerror", "onload", "onmouseover", "onfocus", "onmouseenter", "onmouseout", "onanimationstart", "formaction", "srcdoc"):
                    self.bad.append(f"{tag}[{name}]")
    p = P()
    p.feed(html)
    assert not p.bad, p.bad


@pytest.mark.parametrize("payload", PAYLOADS)
def test_malicious_client_name_is_escaped_everywhere(repo, payload):
    u = services.accept_onboarding_consent(repo, f"{payload}.x@example.com", "a-long-password-1", True, True)
    repo.s.commit()
    for email, role in ((u.email, "Client"), ("admin@atlas-demo.com", "Admin")):
        s = controller.new_session()
        controller.handle(repo, s, dict(id="l" + email, action="login", payload=dict(email=email, password="a-long-password-1" if role == "Client" else "atlas-demo", role=role)))
        assert s["email"] == email
        assert_clean(controller.build(repo, s)["html"])


@pytest.mark.parametrize("payload", PAYLOADS)
def test_malicious_adviser_note_and_draft_are_escaped(repo, payload):
    s = sess_for(repo, "priya.sharma@atlas-demo.com")
    event(repo, s, "select_client", id="c-rajesh.menon")
    event(repo, s, "save_note", text=payload)
    event(repo, s, "mark_draft_ready", subject=payload, body=payload)
    event(repo, s, "save_review", note=payload, decision="edit", tier="Tier 1 — RM approval", target="60", rationale=payload)
    html = controller.build(repo, s)["html"]
    assert_clean(html)
    admin_html = controller.build(repo, sess_for(repo, "admin@atlas-demo.com", "Admin"))["html"]
    assert_clean(admin_html)                                                                  # audit table shows the note text


def test_malicious_news_and_llm_output_are_escaped(repo):
    from dwn.data.news import NewsService
    body = ("<?xml version='1.0'?><rss version='2.0'><channel><item><title>&lt;script&gt;alert(1)&lt;/script&gt;Rates held</title>"
            "<link>https://www.federalreserve.gov/x1</link><pubDate>Mon, 19 Oct 2026 14:00:00 GMT</pubDate>"
            "<description>&lt;img src=x onerror=alert(1)&gt;details</description></item></channel></rss>").encode()
    items, _ = parse_feed(body, FEEDS[0], utcnow())
    assert "<" not in items[0].title and "<" not in items[0].summary                         # tags are stripped at ingestion
    repo.upsert_news(items); put_quotes(repo)
    llm = ScriptedLLM([{"rm_note": "<script>alert(1)</script>Tier 3. The gap is 20.1 points.", "client_message": "<img src=x onerror=alert(1)>Hello Rajesh", "talking_points": []}] * 3)
    run_monitoring(repo, login(repo, "priya.sharma@atlas-demo.com"), "c-rajesh.menon", llm=llm, force=True)
    repo.s.commit()
    s = sess_for(repo, "priya.sharma@atlas-demo.com")
    event(repo, s, "select_client", id="c-rajesh.menon")
    assert_clean(controller.build(repo, s)["html"])


# =============================================================== authorisation matrix: every client-scoped service, every wrong user
UNAUTHORISED = [("priya.sharma@atlas-demo.com", "RM", "c-k01"), ("priya.sharma@atlas-demo.com", "RM", "c-ramesh.agarwal"), ("arjun.mehta@atlas-demo.com", "RM", "c-rajesh.menon"),
                ("neha.kapoor@atlas-demo.com", "RM", "c-rajesh.menon"), ("neha.kapoor@atlas-demo.com", "RM", "c-k01"),
                ("ramesh.agarwal@atlas-demo.com", "Client", "c-rajesh.menon"), ("ramesh.agarwal@atlas-demo.com", "Client", "c-ananya.singh"),
                ("ananya.singh@atlas-demo.com", "Client", "c-ramesh.agarwal")]

CALLS = {
    "get_client": lambda r, u, c: services.get_client(r, u, c),
    "save_rm_decision": lambda r, u, c: services.save_rm_decision(r, u, c, "n", "approve", "Tier 1 — RM approval", 60, ""),
    "decide_proposal": lambda r, u, c: services.decide_proposal(r, u, c, "approve", "n", True),
    "request_consent": lambda r, u, c: services.request_consent(r, u, c),
    "add_note": lambda r, u, c: services.add_note(r, u, c, "note"),
    "mark_draft_ready": lambda r, u, c: services.mark_draft_ready(r, u, c, "s", "b"),
    "save_contact_pref": lambda r, u, c: services.save_contact_pref(r, u, c, "Email"),
    "answer_question": lambda r, u, c: services.answer_question(r, u, c, "summarise goals"),
    "review_report": lambda r, u, c: services.review_report(r, u, c, "Quarterly portfolio review"),
    "withdraw_consent": lambda r, u, c: services.withdraw_consent(r, u, c),
    "regrant_consent": lambda r, u, c: services.regrant_consent(r, u, c, True, True),
    "run_monitoring": lambda r, u, c: run_monitoring(r, u, c, llm=TemplateLLM()),
}


@pytest.mark.parametrize("email,role,cid", UNAUTHORISED, ids=[f"{e.split('@')[0]}->{c}" for e, _, c in UNAUTHORISED])
@pytest.mark.parametrize("fn", list(CALLS))
def test_every_client_scoped_service_refuses_the_wrong_user(repo, email, role, cid, fn):
    put_quotes(repo)
    u = login(repo, email, role)
    with pytest.raises(services.Denied):
        CALLS[fn](repo, u, cid)
    assert repo.list_runs(cid) == []                                                          # a denied run leaves no trace of analysis


def test_admin_and_clients_cannot_use_rm_actions_on_any_client(repo):
    admin = login(repo, "admin@atlas-demo.com", "Admin")
    for fn in ("save_rm_decision", "decide_proposal", "request_consent", "add_note", "mark_draft_ready", "save_contact_pref", "review_report"):
        with pytest.raises(services.Denied):
            CALLS[fn](repo, admin, "c-rajesh.menon")
    ramesh = login(repo, "ramesh.agarwal@atlas-demo.com", "Client")
    for fn in ("save_rm_decision", "decide_proposal", "add_note", "mark_draft_ready", "review_report", "run_monitoring"):
        with pytest.raises(services.Denied):
            CALLS[fn](repo, ramesh, "c-ramesh.agarwal")                                      # even their OWN client: these are RM-only actions


def test_injection_strings_in_identifiers_are_just_unknown_ids(repo):
    priya = login(repo, "priya.sharma@atlas-demo.com")
    for bad in ("' OR '1'='1", "c-rajesh.menon' --", "1; DROP TABLE clients;--", "../../etc/passwd"):
        with pytest.raises(services.Denied):
            services.get_client(repo, priya, bad)
    assert auth.authenticate(repo, "' OR '1'='1' --", "x", "RM")[0] is None
    assert repo.client_count() == 37


def test_second_approver_access_is_limited_to_the_routed_case(repo):
    put_quotes(repo)
    priya = login(repo, "priya.sharma@atlas-demo.com")
    run_monitoring(repo, priya, "c-rajesh.menon", llm=TemplateLLM())
    arjun = login(repo, "arjun.mehta@atlas-demo.com")
    assert "c-rajesh.menon" not in {c.id for c in services.clients_for(repo, arjun)}                  # not yet: only after the first approval routes it
    services.decide_proposal(repo, priya, "c-rajesh.menon", "approve", "Spoke with client.", True)
    repo.s.commit()
    ids = {c.id for c in services.clients_for(repo, arjun)}
    assert "c-rajesh.menon" in ids and "c-ananya.singh" not in ids and "c-ramesh.agarwal" in ids      # only the routed case plus his own book
    neha = login(repo, "neha.kapoor@atlas-demo.com")
    assert services.clients_for(repo, neha) == []


# =============================================================== consent gates beyond the agent
def test_no_consent_blocks_copilot_and_reports(repo):
    priya = login(repo, "priya.sharma@atlas-demo.com")
    assert "consent is not on file" in services.answer_question(repo, priya, "c-neha.prakash", "summarise goals")
    with pytest.raises(services.Denied):
        services.review_report(repo, priya, "c-neha.prakash", "Quarterly portfolio review")
    assert "Sources:" in services.answer_question(repo, priya, "c-rajesh.menon", "why is it flagged for drift")


# =============================================================== secrets never leak
def test_api_keys_never_reach_logs_audit_or_source_errors(repo, monkeypatch, caplog):
    secret = "SUPERSECRETKEY-123456"
    monkeypatch.setattr(config, "ALPHAVANTAGE_API_KEY", secret)
    repo.set_source_enabled("alphavantage", True)
    calls = []

    def net(url, headers, timeout, **k):
        calls.append(url)
        return Response(500, b"", url)
    with caplog.at_level(logging.DEBUG):
        MarketService(repo, Fetcher(transport=net, sleep=lambda s: None, min_interval_s=0, retries=1), providers=[YahooChartProvider(), AlphaVantageProvider()]).refresh(["SPY"], force=True)
    repo.s.commit()
    blob = json.dumps([e.__dict__ for e in repo.list_audit(limit=50)], default=str) + json.dumps(repo.list_sources(), default=str) + caplog.text
    assert any("apikey" in c for c in calls) and secret not in blob                           # the key was used on the wire, and only there


def test_passwords_never_reach_audit_or_logs(repo, caplog):
    with caplog.at_level(logging.DEBUG):
        auth.authenticate(repo, "priya.sharma@atlas-demo.com", "my-very-secret-pw-9", "RM")
    repo.s.commit()
    assert "my-very-secret-pw-9" not in json.dumps([e.__dict__ for e in repo.list_audit(limit=20)]) + caplog.text


def test_unexpected_errors_show_a_reference_not_internals(repo, monkeypatch, caplog):
    monkeypatch.setattr(services, "add_note", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(r"secret path C:\internal\db password=hunter2")))
    s = sess_for(repo, "priya.sharma@atlas-demo.com")
    with caplog.at_level(logging.ERROR, logger="dwn"):
        eff = event(repo, s, "save_note", text="hello")
    assert "Reference" in eff["toast"] and "secret" not in eff["toast"] and "hunter2" not in eff["toast"]
    assert "hunter2" in caplog.text                                                           # details are kept SERVER-side for debugging
    actions = [e for e in repo.list_audit(limit=10) if e.action == "Internal error"]
    assert actions and "hunter2" not in actions[0].details


# =============================================================== production guards and input limits
def test_production_start_is_refused_when_unsafe(monkeypatch):
    import importlib
    monkeypatch.setenv("DWN_ENV", "prod"); monkeypatch.setenv("DATABASE_URL", "sqlite:///x.db"); monkeypatch.setenv("DWN_SEED_DEMO", "0")
    cfg = importlib.reload(config)
    try:
        with pytest.raises(RuntimeError):
            cfg.validate_production()                                                         # SQLite is not allowed in production
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com:5432/x"); monkeypatch.setenv("DWN_SEED_DEMO", "1"); monkeypatch.delenv("DWN_DEMO_PASSWORD", raising=False)
        with pytest.raises(RuntimeError):
            cfg.validate_production()                                                         # demo accounts with the default password
        monkeypatch.setenv("DWN_SEED_DEMO", "0")
        cfg.validate_production()                                                             # safe configuration passes
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_login_page_has_no_demo_credentials_outside_demo_mode(repo, monkeypatch):
    monkeypatch.setattr(config, "seed_demo_data", lambda: False)
    p = controller.build(repo, controller.new_session())
    assert "atlas-demo" not in p["html"] and p["demo_defaults"] is False and "Prototype sign-in" not in p["html"]
    monkeypatch.setattr(config, "seed_demo_data", lambda: True)
    assert controller.build(repo, controller.new_session())["demo_defaults"] is True


def test_oversized_inputs_are_rejected(repo):
    priya = login(repo, "priya.sharma@atlas-demo.com")
    with pytest.raises(ValueError):
        services.add_note(repo, priya, "c-rajesh.menon", "x" * 4001)
    with pytest.raises(ValueError):
        services.answer_question(repo, priya, "c-rajesh.menon", "q" * 1001)
    with pytest.raises(ValueError):
        services.accept_onboarding_consent(repo, "ok@example.com", "short", True, True)


def test_no_demo_password_in_tracked_config_files():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for name in (".env.example", "requirements.txt", ".github/workflows/scheduler.yml"):
        txt = (root / name).read_text(encoding="utf-8")
        assert "sk-" not in txt and "AIza" not in txt and "gsk_" not in txt and "postgresql://" not in txt.replace("DATABASE_URL=postgresql://USER:PASSWORD@HOST", "")
