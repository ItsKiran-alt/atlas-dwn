"""Fix batch: overview/queue alignment, AI Insights, reports, Run now, performance charts, secure messages, Groq drafting, query batching."""
import re
import time
from datetime import date, timedelta

import pytest

from dwn import reports, services
from dwn.agents import llm as llmmod
from dwn.agents.llm import LLMResult, ScriptedLLM
from dwn.data.history import parse_weekly
from dwn.domain import utcnow
from dwn.engines import performance
from dwn.ui import controller, render

PRIYA, ARJUN, RAJESH = "priya.sharma@atlas-demo.com", "arjun.mehta@atlas-demo.com", "rajesh.menon@atlas-demo.com"


def sess_for(repo, email, role="RM"):
    s = controller.new_session()
    controller.handle(repo, s, dict(id="login-" + email, action="login", payload=dict(email=email, password="atlas-demo", role=role)))
    assert s["email"] == email
    return s


def ev(repo, sess, action, **payload):
    controller.handle(repo, sess, dict(id=f"{action}-{utcnow().timestamp()}", action=action, payload=payload))
    repo.s.commit()
    return sess["effect"] or {}


def page(repo, sess) -> str:
    return controller.build(repo, sess)["html"]


# ------------------------------------------------------------------ item 4: overview numbers = queue numbers
def test_overview_cards_match_queue_chips_and_rows(repo):
    for email in (PRIYA, ARJUN):
        s = sess_for(repo, email)
        html = page(repo, s)
        cards = re.findall(r'<strong[^>]*>(\d+)</strong><span>(Clients need attention|Awaiting your approval|Consent pending)</span>', html)
        card = {name: int(n) for n, name in cards}
        chips = dict((k, int(n)) for k, n in re.findall(r"filterQueue\('(\w+)',this\)\">[^<(]*\((\d+)\)", html))
        assert card["Clients need attention"] == chips["review"]
        assert card["Awaiting your approval"] == chips["approval"]
        assert card["Consent pending"] == chips["consent"]
        rows = re.findall(r'class="clientrow[^"]*" data-id="[^"]+" data-name="[^"]*" data-kind="(\w+)" data-consent="(\d)"', html)
        assert sum(1 for k, _ in rows if k == "approval") == chips["approval"]
        assert sum(1 for k, _ in rows if k in ("review", "approval")) == chips["review"]
        assert sum(1 for _, c in rows if c == "0") == chips["consent"]


def test_overview_cards_are_clickable(repo):
    html = page(repo, sess_for(repo, PRIYA))
    assert html.count('class="metric clickable"') >= 4 and "jumpQueue('approval')" in html and "setView('insights')" in html


# ------------------------------------------------------------------ items 5/6: AI Insights
def test_insights_lists_every_pending_recommendation_with_current_and_new_allocation(repo):
    s = sess_for(repo, PRIYA)
    html = page(repo, s)
    sec = html[html.index('id="view-insights"'):html.index('id="view-research"')]
    n = int(re.search(r"Recommendations awaiting your approval \((\d+)\)", sec).group(1))
    assert n >= 1 and sec.count("data-client=") == n
    assert "After adjustment" in sec and "Target plan" in sec and "Review &amp; decide" in sec
    assert "showRec(" in sec
    assert "onclick=\"setView('workbench')\">Review recommendations" not in sec          # the old redirect is gone


def test_insights_review_opens_review_modal_without_leaving_insights(repo):
    s = sess_for(repo, PRIYA)
    e = ev(repo, s, "select_client", id="c-rajesh.menon", review=True, goto="insights")
    assert e["view"] == "insights" and e["open_modal"] == "reviewModal"


def test_allocation_table_uses_the_proposal_trades(repo):
    from dwn.ui.recview import allocation_rows
    s = sess_for(repo, PRIYA)
    ev(repo, s, "select_client", id="c-rajesh.menon")
    c = services.get_client(repo, repo.get_user(PRIYA), "c-rajesh.menon")
    plain = {r["key"]: r for r in allocation_rows(c, None)}
    assert plain["EQ"]["new"] == c.plan["EQ"]                       # no proposal: move to plan
    pb = dict(trades=[dict(asset_class="equity", direction="sell", points=4.0, usd=100000), dict(asset_class="fixed income", direction="buy", points=4.0, usd=100000)])
    rows = {r["key"]: r for r in allocation_rows(c, pb)}
    assert rows["EQ"]["new"] == pytest.approx(c.weights["EQ"] - 4) and rows["FI"]["new"] == pytest.approx(c.weights["FI"] + 4)


# ------------------------------------------------------------------ items 2/7: reports
def test_every_report_builds_and_has_content(repo):
    u = repo.get_user(PRIYA)
    for kind in reports.BUILDERS:
        rep = services.build_report(repo, u, kind)
        assert rep["title"] and len(rep["body_html"]) > 100
        doc = reports.document(rep["title"], rep["body_html"], u.name)
        assert doc.startswith("<!doctype html>") and "<script" not in doc


def test_report_for_client_without_consent_is_a_paused_page_not_an_error(repo):
    u = repo.get_user(PRIYA)
    rep = services.build_report(repo, u, "client_review", "c-neha.prakash")
    assert "Paused" in rep["body_html"] and "consent" in rep["body_html"].lower()
    full = services.build_report(repo, u, "portfolio_review")
    assert "Neha Prakash" in full["body_html"] and "Paused" in full["body_html"]


def test_report_rbac(repo):
    priya = repo.get_user(PRIYA)
    with pytest.raises(services.Denied):
        services.build_report(repo, priya, "client_review", "c-someone.elses")
    with pytest.raises(services.Denied):
        services.build_report(repo, repo.get_user(RAJESH), "portfolio_review")        # clients cannot build reports
    with pytest.raises(ValueError):
        services.build_report(repo, priya, "nope")
    other = next(c for c in repo.list_clients(include_all=True) if c.rm_id != "rm-priya")
    with pytest.raises(services.Denied):
        services.build_report(repo, priya, "client_review", other.id)


def test_report_actions_view_and_download(repo):
    s = sess_for(repo, PRIYA)
    v = ev(repo, s, "report_view", kind="portfolio_review")
    assert v["open_modal"] == "reportModal" and v["report"]["has_csv"] and "Rajesh Menon" in v["report"]["html"]
    d = ev(repo, s, "report_download", kind="consent_status", fmt="csv")["download"]
    assert d["filename"].endswith(".csv") and "Neha Prakash" in d["content"]
    h = ev(repo, s, "report_download", kind="client_review", client_id="c-rajesh.menon", fmt="html")["download"]
    assert h["filename"].endswith(".html") and "Rajesh Menon" in h["content"]
    n = ev(repo, s, "report_view", kind="client_review", client_id="c-neha.prakash")
    assert "report" in n and "Paused" in n["report"]["html"]                           # no consent: shown as paused, no error toast


def test_report_csv_neutralises_formulas():
    assert reports._csv([["=cmd()", "ok"]]).startswith("'=cmd()")


def test_reports_are_audited(repo):
    s = sess_for(repo, PRIYA)
    ev(repo, s, "report_view", kind="consent_status")
    assert any(a.action == "Report viewed" for a in repo.list_audit(limit=20))


# ------------------------------------------------------------------ item 8: Run now (inline here; thread test below)
def test_scheduler_run_now_inline_runs_and_records_a_job(repo, monkeypatch):
    monkeypatch.setattr(services, "refresh_external_data", lambda *a, **k: "stub")
    monkeypatch.setattr(services, "external_data_is_stale", lambda r: False)
    s = sess_for(repo, ARJUN)
    cfg = dict(name="x", frequency="daily", time="08:30", days=[], month_day="1", scopes=["Portfolio drift"], client_scope="Selected client only", enabled=True, clients=[])
    first = next(c for c in services.clients_for(repo, repo.get_user(ARJUN), for_scheduling=True))
    cfg["clients"] = [first.id]
    t = ev(repo, s, "run_now", cfg=cfg)["toast"]
    assert t.startswith("Run ") and repo.list_jobs(ARJUN, 3)[0]["trigger"] == "manual"


def test_run_now_rejects_bad_scope_before_starting(repo):
    s = sess_for(repo, ARJUN)
    t = ev(repo, s, "run_now", cfg=dict(name="x", frequency="daily", time="08:30", days=[], month_day="1", scopes=["Portfolio drift"], client_scope="Selected client only", enabled=True, clients=["c-not-mine"]))["toast"]
    assert "outside the scope" in t and not (s.get("bg") or {}).get("running")


def test_hero_run_now_and_run_all(repo, monkeypatch):
    monkeypatch.setattr(services, "refresh_external_data", lambda *a, **k: "stub")
    monkeypatch.setattr(services, "external_data_is_stale", lambda r: False)
    s = sess_for(repo, PRIYA)
    ev(repo, s, "select_client", id="c-rajesh.menon")
    assert ev(repo, s, "run_agent")["toast"]
    t = ev(repo, s, "run_all")["toast"]
    assert t.startswith("Analysis finished for")
    assert "▶ Run now" in page(repo, s) and "viewReport('client_review'" in page(repo, s)


def test_background_run_finishes_and_announces(repo, monkeypatch):
    monkeypatch.setenv("DWN_ASYNC_JOBS", "1")
    monkeypatch.setattr(services, "refresh_external_data", lambda *a, **k: "stub")
    monkeypatch.setattr(services, "external_data_is_stale", lambda r: False)
    s = sess_for(repo, PRIYA)
    ev(repo, s, "select_client", id="c-rajesh.menon")
    repo.s.commit()
    t = ev(repo, s, "run_agent")["toast"]
    assert "Running" in t
    for _ in range(100):
        if not s["bg"]["running"]:
            break
        time.sleep(0.1)
    assert not s["bg"]["running"] and s["bg"]["message"]
    msg = ev(repo, s, "refresh_view")["toast"]
    assert msg == s["bg"]["message"]
    assert "toast" not in ev(repo, s, "refresh_view")                                  # announced once
    assert controller.build(repo, s)["bg_running"] is False


def test_second_background_run_is_refused_while_one_runs(repo, monkeypatch):
    monkeypatch.setenv("DWN_ASYNC_JOBS", "1")
    s = sess_for(repo, PRIYA)
    s["bg"] = dict(running=True, label="The run", message="", announced=False, started=time.time())
    t = ev(repo, s, "run_all")["toast"]
    assert "still running" in t


# ------------------------------------------------------------------ item 3: fewer queries
def test_page_build_query_count_does_not_grow_with_clients(repo):
    from sqlalchemy import event
    eng = repo.s.get_bind()
    s = sess_for(repo, PRIYA)
    n = [0]

    def count(*a, **k):
        n[0] += 1
    event.listen(eng, "before_cursor_execute", count)
    try:
        controller.build(repo, s)
    finally:
        event.remove(eng, "before_cursor_execute", count)
    assert n[0] < 45, f"{n[0]} queries per page build"


def test_batched_lookups_match_the_per_client_ones(repo):
    ids = [c.id for c in repo.list_clients(include_all=True)]
    assert repo.consent_map(ids) == {i: repo.has_active_consent(i) for i in ids}
    assert repo.latest_proposals(ids) == {i: repo.latest_proposal(i) for i in ids}
    assert [c.id for c in repo.list_clients(ids=ids[:3])] == ids[:3]
    assert repo.list_clients(ids=[]) == []


def test_memo_is_off_outside_page_builds(repo):
    assert repo.memoize is False
    u = repo.get_user("admin@atlas-demo.com")
    services.save_rm_permissions(repo, u, "Priya Sharma", True, True, "Tier 1", False)
    assert repo.get_perms("rm-priya")["all_clients"] is True


# ------------------------------------------------------------------ item 9: performance + charts
def _hist(weeks=270, drift=0.002):
    start = date(2021, 1, 4)
    out = {}
    for sym, mult in (("SPY", 1.0), ("AGG", 0.3), ("VNQ", 0.8)):
        v, bars = 100.0, []
        for i in range(weeks):
            v *= 1 + drift * mult + (0.01 if i % 2 else -0.01) * mult
            bars.append((start + timedelta(weeks=i), v))
        out[sym] = bars
    return out


def test_performance_estimate_is_deterministic_and_labelled_by_window():
    h = _hist()
    p = performance.estimate({"EQ": 60, "FI": 30, "AL": 5, "CA": 5}, h)
    assert p.available and p.portfolio[0] == 100.0 and set(p.returns) == {"1Y", "3Y", "5Y"}
    assert performance.estimate({"EQ": 60, "FI": 30, "AL": 5, "CA": 5}, h).returns == p.returns
    allcash = performance.estimate({"EQ": 0, "FI": 0, "AL": 0, "CA": 100}, h)
    assert allcash.returns["1Y"] == 0.0                                                 # cash earns nothing in this estimate


def test_performance_never_invents_numbers_without_history():
    p = performance.estimate({"EQ": 60, "FI": 40}, {"SPY": [], "AGG": [], "VNQ": []})
    assert not p.available and p.reason and not p.returns


def test_history_parser_rejects_bad_data():
    import json
    def payload(closes):
        return json.dumps({"chart": {"result": [{"meta": {"gmtoffset": 0}, "timestamp": [1600000000 + 604800 * i for i in range(len(closes))], "indicators": {"quote": [{"close": closes}]}}]}})
    assert len(parse_weekly(payload([100 + i for i in range(30)]))) == 30
    with pytest.raises(ValueError):
        parse_weekly(payload([100 + i for i in range(5)]))                               # too short
    with pytest.raises(ValueError):
        parse_weekly(payload([100] * 15 + [300] + [100] * 15))                           # implausible jump


def test_history_roundtrip_and_upsert(repo):
    bars = [(date(2026, 1, 5) + timedelta(weeks=i), 100.0 + i) for i in range(5)]
    assert repo.save_history("SPY", bars, "yahoo", utcnow()) == 5
    assert repo.save_history("SPY", bars, "yahoo", utcnow()) == 0                         # idempotent
    assert repo.history(["SPY"])["SPY"] == bars


def test_client_portal_shows_dashboard_charts_and_honest_labels(repo):
    s = sess_for(repo, RAJESH, "Client")
    html = page(repo, s)
    assert html.count("<svg") >= 3 and "Portfolio drift" in html and "Current vs target" in html and "Goal outlook" in html
    assert "market history has not been loaded" in html.lower()                           # no history in the test DB: no invented return
    for sym, bars in _hist().items():
        repo.save_history(sym, [(d, c) for d, c in bars], "yahoo", utcnow())
    repo.s.commit()
    html = page(repo, s)
    assert html.count("<svg") >= 4 and "NOT your account" in html and "60/40 benchmark" in html and 'class="perfblock"' in html


def test_charts_escape_text():
    from dwn.ui import charts

    class G:
        name, detail, progress = "<script>x</script>", "<b>d</b>", 50
    out = charts.goal_bars([G()])
    assert "<script>" not in out and "&lt;script&gt;" in out


# ------------------------------------------------------------------ item 9: secure messages
def test_client_messages_their_own_rm_and_rm_replies(repo):
    c = sess_for(repo, RAJESH, "Client")
    assert ev(repo, c, "send_message", body="Hello, can we talk about my equity weight?")["toast"] == "Message sent."
    r = sess_for(repo, PRIYA)
    html = page(repo, r)
    assert "view-messages" in html and "1 new" in html
    ev(repo, r, "select_client", id="c-rajesh.menon", goto="messages")
    assert "equity weight" in page(repo, r) and repo.recent_message_stats(["c-rajesh.menon"])["c-rajesh.menon"]["unread"] == 0
    ev(repo, r, "send_message", body="Of course. Thursday?")
    assert "Thursday" in page(repo, c)
    assert [m["role"] for m in repo.messages_for("c-rajesh.menon")] == ["Client", "RM"]


def test_messages_are_scoped_validated_and_not_logged(repo):
    priya = repo.get_user(PRIYA)
    other = next(c for c in repo.list_clients(include_all=True) if c.rm_id != "rm-priya")
    with pytest.raises(services.Denied):
        services.send_message(repo, priya, "hi", other.id)
    with pytest.raises(services.Denied):
        services.send_message(repo, repo.get_user("admin@atlas-demo.com"), "hi", "c-rajesh.menon")
    client = repo.get_user(RAJESH)
    with pytest.raises(ValueError):
        services.send_message(repo, client, "   ")
    with pytest.raises(ValueError):
        services.send_message(repo, client, "x" * (services.MSG_MAX_CHARS + 1))
    services.send_message(repo, client, "secret-account-number-12345")
    assert not any("secret-account-number" in a.details for a in repo.list_audit(limit=50))
    assert any(a.action == "Secure message sent" for a in repo.list_audit(limit=50))


def test_message_rate_limit(repo):
    client = repo.get_user(RAJESH)
    for i in range(services.MSG_PER_HOUR):
        services.send_message(repo, client, f"m{i}")
    with pytest.raises(ValueError, match="very quickly"):
        services.send_message(repo, client, "one more")


def test_message_html_is_escaped_everywhere(repo):
    services.send_message(repo, repo.get_user(RAJESH), '<img src=x onerror=alert(1)> <script>alert(2)</script>')
    repo.s.commit()
    for email, role in ((RAJESH, "Client"), (PRIYA, "RM")):
        s = sess_for(repo, email, role)
        if role == "RM":
            ev(repo, s, "select_client", id="c-rajesh.menon", goto="messages")
        html = page(repo, s)
        assert "<img src=x" not in html and "<script>alert" not in html and "&lt;img" in html


def test_client_with_withdrawn_consent_can_still_message(repo):
    services.withdraw_consent(repo, repo.get_user(RAJESH), "c-rajesh.menon")
    services.send_message(repo, repo.get_user(RAJESH), "I withdrew consent; please call me.")
    assert len(repo.messages_for("c-rajesh.menon")) == 1


# ------------------------------------------------------------------ item 10: Groq
def test_provider_is_inferred_from_the_key(monkeypatch):
    for k in ("DWN_LLM_PROVIDER", "GROQ_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert llmmod.chosen_provider() == "template" and llmmod.llm_status()["live"] is False
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert llmmod.chosen_provider() == "groq" and llmmod.llm_status()["live"] is True
    monkeypatch.setenv("DWN_LLM_PROVIDER", "template")
    assert llmmod.chosen_provider() == "template"                                         # explicit choice wins
    monkeypatch.setenv("DWN_LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY")
    assert llmmod.llm_status()["live"] is False and "missing" in llmmod.llm_status()["text"]
    monkeypatch.setenv("GROQ_API_KEY", "sekret-key-123")
    assert "sekret" not in str(llmmod.llm_status())                                       # the key is never exposed to the UI


def test_reply_draft_template_when_no_ai(repo, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("DWN_LLM_PROVIDER", raising=False)
    services.send_message(repo, repo.get_user(RAJESH), "How is my portfolio doing?")
    text, how = services.draft_reply(repo, repo.get_user(PRIYA), "c-rajesh.menon")
    assert "Hello Rajesh" in text and "template" in how and "guarantee" not in text.lower()


def test_reply_draft_uses_the_model_but_rejects_ungrounded_numbers(repo, monkeypatch):
    services.send_message(repo, repo.get_user(RAJESH), "How is my portfolio doing?")
    good = ScriptedLLM([dict(reply="Hello Rajesh, thanks for asking. I will review your portfolio and come back to you.")], name="groq", model="m")
    monkeypatch.setattr(llmmod, "make_llm", lambda *a, **k: good)
    text, how = services.draft_reply(repo, repo.get_user(PRIYA), "c-rajesh.menon")
    assert text.startswith("Hello Rajesh, thanks") and "groq" in how
    bad = ScriptedLLM([dict(reply="Your portfolio will grow 37.5% next year, guaranteed.")] * 2, name="groq", model="m")
    monkeypatch.setattr(llmmod, "make_llm", lambda *a, **k: bad)
    text, how = services.draft_reply(repo, repo.get_user(PRIYA), "c-rajesh.menon")
    assert "37.5" not in text and "guaranteed" not in text and "template" in how and text.startswith("Hello Rajesh")


def test_reply_draft_is_consent_gated_and_needs_a_client_message(repo):
    with pytest.raises(ValueError, match="no client message"):
        services.draft_reply(repo, repo.get_user(PRIYA), "c-rajesh.menon")
    with pytest.raises(services.Denied):
        services.draft_reply(repo, repo.get_user(PRIYA), "c-neha.prakash")               # no consent: no AI processing


def test_draft_reply_action_fills_the_box_and_sends_nothing(repo):
    services.send_message(repo, repo.get_user(RAJESH), "Question about my bonds")
    r = sess_for(repo, PRIYA)
    ev(repo, r, "select_client", id="c-rajesh.menon", goto="messages")
    e = ev(repo, r, "draft_reply")
    assert e["fill"]["id"] == "replyBody" and e["fill"]["text"] and len(repo.messages_for("c-rajesh.menon")) == 1


def test_ask_modal_reports_ai_status(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("DWN_LLM_PROVIDER", raising=False)
    assert "no external AI service" in render._ask_modal()
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert "AI-assisted (groq)" in render._ask_modal()
