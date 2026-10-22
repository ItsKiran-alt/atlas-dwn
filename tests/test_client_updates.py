"""Client portal header, notifications, RM <-> client messages, tier rules for client approval, demo logins and meeting dates."""
from datetime import date, datetime

import pytest

from dwn import bootstrap, services
from dwn.domain import utcnow
from dwn.ui import controller

PRIYA, RAJESH, SNEHA = "priya.sharma@atlas-demo.com", "rajesh.menon@atlas-demo.com", "sneha.patel@atlas-demo.com"


def sess_for(repo, email, role="RM"):
    s = controller.new_session()
    controller.handle(repo, s, dict(id="login-" + email, action="login", payload=dict(email=email, password="atlas-demo", role=role)))
    assert s["email"] == email
    return s


def ev(repo, sess, action, **payload):
    controller.handle(repo, sess, dict(id=f"{action}-{utcnow().timestamp()}", action=action, payload=payload))
    repo.s.commit()
    return sess["effect"] or {}


def page(repo, sess):
    return controller.build(repo, sess)["html"]


def decide_legacy(repo, rm_email, client_id, tier, decision="approve"):
    rm = repo.get_user(rm_email)
    services.save_rm_decision(repo, rm, client_id, "Reviewed the AI report.", decision, tier, 60, "", conversation_held=True)


# ------------------------------------------------------------------ 1. client header
def test_client_page_has_company_header_ask_ai_notifications_and_messages(repo):
    html = page(repo, sess_for(repo, RAJESH, "Client"))
    head = html[html.index('<header class="topbar clientbar">'):html.index("</header>")]
    assert "ATLAS" in head and "WEALTH MANAGEMENT" in head
    assert "Ask Atlas AI" in head and "Notifications" in head and "Messages" in head and "Sign out" in head
    assert 'id="askModal"' in html and "Ask about your own portfolio" in html


def test_client_ask_ai_answers_only_from_own_records(repo):
    c = repo.get_user(RAJESH)
    out = services.answer_client_question(repo, c, "Explain my allocation")
    assert "equit" in out.lower() or "plan" in out.lower()
    with pytest.raises(ValueError):
        services.answer_client_question(repo, c, "  ")
    with pytest.raises(services.Denied):
        services.answer_client_question(repo, repo.get_user(PRIYA), "hi")
    s = sess_for(repo, RAJESH, "Client")
    assert "Sources" in ev(repo, s, "ask", question="Summarise my goals")["ask_answer"] or "your own records" in ev(repo, s, "ask", question="Summarise my goals")["ask_answer"]


def test_rm_text_reaches_the_client_and_shows_in_the_header_count(repo):
    r = sess_for(repo, PRIYA)
    ev(repo, r, "select_client", id="c-rajesh.menon")
    ev(repo, r, "send_message", body="Hello Rajesh, a quick note from me.")
    c = sess_for(repo, RAJESH, "Client")
    html = page(repo, c)
    assert "a quick note from me" in html
    assert controller.build(repo, c)["chat_unread"] == 1
    ev(repo, c, "chat_seen")
    assert controller.build(repo, c)["chat_unread"] == 0


# ------------------------------------------------------------------ 2. logins linked to Priya
def test_rajesh_and_sneha_have_logins_linked_to_priya_and_see_the_same_data(repo):
    for email, cid in ((RAJESH, "c-rajesh.menon"), (SNEHA, "c-sneha.patel")):
        u = repo.get_user(email)
        assert u.role == "Client" and u.client_id == cid
        mine = services.get_client(repo, u, cid)
        assert mine.rm_id == "rm-priya"
        theirs = services.get_client(repo, repo.get_user(PRIYA), cid)
        assert (mine.weights, mine.plan, mine.aum_musd, [g.name for g in mine.goals]) == (theirs.weights, theirs.plan, theirs.aum_musd, [g.name for g in theirs.goals])
        html = page(repo, sess_for(repo, email, "Client"))
        assert mine.name in html and f"${mine.aum_musd:.1f}M" in html
    # a client can never open the other one
    with pytest.raises(services.Denied):
        services.get_client(repo, repo.get_user(RAJESH), "c-sneha.patel")


def test_upkeep_creates_missing_logins_with_the_demo_password(repo):
    repo.s.execute(__import__("sqlalchemy").text("delete from users where email in (:a, :b)"), dict(a=RAJESH, b=SNEHA))
    repo.s.commit()
    assert repo.get_user(SNEHA) is None
    bootstrap.refresh_demo_upkeep(repo)
    repo.s.commit()
    assert repo.get_user(SNEHA).client_id == "c-sneha.patel"
    assert sess_for(repo, SNEHA, "Client")["email"] == SNEHA            # same demo password as the RM and Admin accounts
    bootstrap.refresh_demo_upkeep(repo)                                  # idempotent


# ------------------------------------------------------------------ 3. Tier 1 and 2: notification only
@pytest.mark.parametrize("tier", ["Tier 1 — RM approval"])
def test_tier1_decision_notifies_the_client_and_needs_no_consent(repo, tier):
    decide_legacy(repo, PRIYA, "c-rajesh.menon", tier)
    rec = repo.get_rec("c-rajesh.menon")
    assert rec.client_approval == "not_required"
    notes = repo.notifications_for("c-rajesh.menon")
    assert len(notes) == 1 and "approved" in notes[0]["title"].lower() and "No action is needed" in notes[0]["body"]
    assert not any(m["kind"] == "consent_request" for m in repo.messages_for("c-rajesh.menon"))
    r = sess_for(repo, PRIYA)
    ev(repo, r, "select_client", id="c-rajesh.menon")
    html = page(repo, r)
    assert 'id="step3status">Not required' in html


def test_tier2_decision_notifies_only(repo):
    admin = repo.get_user("admin@atlas-demo.com")
    services.save_rm_permissions(repo, admin, "Priya Sharma", True, False, "Tier 2", False)
    decide_legacy(repo, PRIYA, "c-sneha.patel", "Tier 2 — Senior adviser approval")
    assert repo.get_rec("c-sneha.patel").client_approval == "not_required"
    assert len(repo.notifications_for("c-sneha.patel")) == 1
    assert repo.messages_for("c-sneha.patel") == []


def test_reject_and_edit_also_notify_without_asking_anything(repo):
    decide_legacy(repo, PRIYA, "c-rajesh.menon", "Tier 1 — RM approval", "reject")
    decide_legacy(repo, PRIYA, "c-sneha.patel", "Tier 1 — RM approval", "edit")
    assert "not going ahead" in repo.notifications_for("c-rajesh.menon")[0]["title"].lower()
    assert "refined" in repo.notifications_for("c-sneha.patel")[0]["title"].lower()


# ------------------------------------------------------------------ 4. Tier 3: client approval through the chat
def tier3_decision(repo):
    admin = repo.get_user("admin@atlas-demo.com")
    services.save_rm_permissions(repo, admin, "Priya Sharma", True, False, "Tier 3", False)
    decide_legacy(repo, PRIYA, "c-rajesh.menon", "Tier 3 — Investment committee")


def test_tier3_decision_sends_the_client_a_chat_request_with_two_choices(repo):
    tier3_decision(repo)
    assert repo.get_rec("c-rajesh.menon").client_approval == "pending"
    msg = [m for m in repo.messages_for("c-rajesh.menon") if m["kind"] == "consent_request"]
    assert len(msg) == 1 and msg[0]["role"] == "RM" and "I need your consent" in msg[0]["body"]
    assert any(n["kind"] == "consent_request" for n in repo.notifications_for("c-rajesh.menon"))
    c = sess_for(repo, RAJESH, "Client")
    html = page(repo, c)
    assert "I need your consent" in html and ">Approve<" in html and "Request a meeting" in html
    assert controller.build(repo, c)["notif_unread"] == 1 and controller.build(repo, c)["chat_unread"] == 1
    r = sess_for(repo, PRIYA)
    ev(repo, r, "select_client", id="c-rajesh.menon", goto="messages")
    assert "Waiting for the client" in page(repo, r) and 'id="step3status"' in page(repo, r)


def test_client_can_approve(repo):
    tier3_decision(repo)
    c = sess_for(repo, RAJESH, "Client")
    assert "answer has been sent" in ev(repo, c, "client_approval", decision="approve")["toast"]
    assert repo.get_rec("c-rajesh.menon").client_approval == "approved"
    last = repo.messages_for("c-rajesh.menon")[-1]
    assert last["role"] == "Client" and last["kind"] == "client_response" and "approve" in last["body"].lower()
    assert ">Approve<" not in page(repo, c)                                           # buttons disappear once answered
    r = sess_for(repo, PRIYA)
    ev(repo, r, "select_client", id="c-rajesh.menon", goto="messages")
    assert "I approve this recommendation" in page(repo, r) and "Approved by the client" in page(repo, r)


def test_client_can_request_a_meeting_and_still_approve_later(repo):
    tier3_decision(repo)
    c = sess_for(repo, RAJESH, "Client")
    ev(repo, c, "client_approval", decision="meeting")
    assert repo.get_rec("c-rajesh.menon").client_approval == "meeting_requested"
    assert "meet to discuss" in repo.messages_for("c-rajesh.menon")[-1]["body"]
    assert "already asked" in ev(repo, c, "client_approval", decision="meeting")["toast"]
    html = page(repo, c)
    assert ">Approve<" in html and "Request a meeting</button>" not in html
    ev(repo, c, "client_approval", decision="approve")
    assert repo.get_rec("c-rajesh.menon").client_approval == "approved"


def test_nothing_to_answer_and_only_the_client_can_answer(repo):
    c = repo.get_user(RAJESH)
    with pytest.raises(ValueError, match="nothing waiting"):
        services.respond_to_approval_request(repo, c, "approve")
    tier3_decision(repo)
    with pytest.raises(services.Denied):
        services.respond_to_approval_request(repo, repo.get_user(PRIYA), "approve")
    with pytest.raises(ValueError):
        services.respond_to_approval_request(repo, c, "maybe")
    # another client cannot answer for Rajesh: the answer always applies to the signed-in client's own record
    with pytest.raises(ValueError, match="nothing waiting"):
        services.respond_to_approval_request(repo, repo.get_user(SNEHA), "approve")


def test_marking_notifications_read(repo):
    decide_legacy(repo, PRIYA, "c-rajesh.menon", "Tier 1 — RM approval")
    c = sess_for(repo, RAJESH, "Client")
    assert controller.build(repo, c)["notif_unread"] == 1
    ev(repo, c, "notifications_seen")
    assert controller.build(repo, c)["notif_unread"] == 0 and repo.notifications_for("c-rajesh.menon")[0]["read"]


def test_clients_only_see_their_own_notifications(repo):
    decide_legacy(repo, PRIYA, "c-rajesh.menon", "Tier 1 — RM approval")
    html = page(repo, sess_for(repo, SNEHA, "Client"))
    assert "Recommendation approved" not in html and "No notifications yet" in html


def test_notification_text_is_escaped(repo):
    repo.add_notification("c-rajesh.menon", "decision", "<script>x</script>", "<img src=x onerror=1>")
    html = page(repo, sess_for(repo, RAJESH, "Client"))
    assert "<script>x" not in html and "&lt;script&gt;" in html and "<img src=x" not in html


# ------------------------------------------------------------------ 5. meeting dates
def test_next_meetings_are_in_the_future_and_varied(repo):
    today = date.today()
    dates = [datetime.strptime(c.next_meeting, "%d %b %Y").date() for c in repo.list_clients(include_all=True)]
    assert all(d > today for d in dates) and not any(d.year == 2025 for d in dates)
    assert len(set(dates)) > 10


def test_old_2025_meeting_dates_are_rolled_forward(repo):
    repo.set_next_meeting("c-rajesh.menon", "28 Apr 2025")
    repo.s.commit()
    bootstrap.refresh_demo_upkeep(repo)
    got = datetime.strptime(repo.list_clients(client_id="c-rajesh.menon")[0].next_meeting, "%d %b %Y").date()
    assert got > date.today()
    page_html = page(repo, sess_for(repo, PRIYA))
    assert "28 Apr 2025" not in page_html
