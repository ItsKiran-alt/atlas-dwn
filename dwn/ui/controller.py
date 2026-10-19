"""Turns UI events into service calls and session state into a rendered page payload."""
from __future__ import annotations

import hashlib
import logging
import time
import uuid

from .. import auth, config, services
from ..data.market import MarketService
from ..data.news import NewsService
from ..domain import Client, Rec, User
from ..repo import Repo
from . import render as R


class ViewData:
    """Read-only snapshot handed to the renderers: only data the signed-in user is allowed to see."""

    def __init__(self, repo: Repo, user: User, clients: list[Client], selected: Client | None):
        ids = [c.id for c in clients]
        self.rms = repo.list_rms()
        self.recs = repo.recs_for(ids)
        self._consent = {i: repo.has_active_consent(i) for i in ids}
        scope = None if user.role == "Admin" else ids
        self.audit = repo.list_audit(limit=200, client_ids=scope)
        self.notes = repo.notes_for(selected.id) if selected else []
        self.sources = {s["id"]: s for s in repo.list_sources()}
        self.perms = {r.id: repo.get_perms(r.id) for r in self.rms}
        last = repo.last_run()
        self.schedule_runs = [last] if last else []
        self.audit_total = repo.audit_count() if user.role == "Admin" else len(self.audit)
        self.clients_by_id = {c.id: c for c in clients}
        self._repo = repo
        self.consent_info = repo.consent_info(user.client_id) if user.role == "Client" else None
        self._selected = selected
        self.proposals = {c.id: repo.latest_proposal(c.id) for c in clients}
        self.sched = services.scheduler_view(repo, user, repo.get_schedule(user.email)) if user.role in ("RM", "Admin") else dict(jobs=[], next="")
        self.approvals = repo.approvals_for(self.proposals[selected.id]["id"]) if selected and self.proposals.get(selected.id) else []
        self.runs = repo.list_runs(selected.id, 3) if selected else []
        _p = self.proposals.get(selected.id) if selected else None
        self.evidence_count = len(repo.get_run(_p["run_id"])["evidence"]) if _p else 0
        self.second_cases = {c.id for c in clients if c.rm_id != user.rm_id} if user.role == "RM" else set()
        self.market = MarketService(repo).view() if user.role in ("RM", "Admin") else []
        self.market_by_symbol = {r["symbol"]: r for r in self.market}
        self.news = NewsService(repo).latest(10) if user.role in ("RM", "Admin") else []

    def has_active_consent(self, client_id: str) -> bool:
        return self._consent.get(client_id, False)

    def rec(self, client_id: str) -> Rec:
        return self.recs.get(client_id) or Rec(client_id, self.clients_by_id[client_id].issue if client_id in self.clients_by_id else "", "Monitor")

    def draft(self, client: Client) -> dict:
        return services.get_draft(self._repo, client)

    def client(self, client_id: str) -> Client:
        return self.clients_by_id[client_id]


def _demo_pw_known() -> bool:
    """True only when demo accounts use the well-known default password (safe to pre-fill in local demos)."""
    try:
        return config.seed_demo_data() and config.demo_password() == "atlas-demo"
    except RuntimeError:
        return False


def new_session() -> dict:
    return dict(email=None, onboarding=False, role_hint="RM", client_id=None, perm_rm="rm-priya", error="",
                last_event=None, effect=None, view=None, subtab="overview", fresh=[], last_active=time.time())


def user_of(repo: Repo, sess: dict) -> User | None:
    return repo.get_user(sess["email"]) if sess["email"] else None


def _effect(sess, **kw):
    kw["id"] = uuid.uuid4().hex
    sess["effect"] = kw


FRESH_CLIENT_FIELDS = ["rmNote", "rationale", "targetEquity", "decision", "approvalTier", "messageSubject", "messageBody", "noteText"]


def _active_client(repo: Repo, user: User, sess: dict):
    clients = services.clients_for(repo, user)
    if not clients:
        return None, []
    cur = next((c for c in clients if c.id == sess["client_id"]), None)
    if cur is None:
        recs = repo.recs_for([c.id for c in clients])
        pref = [c for c in clients if c.id in recs and recs[c.id].status == "Draft"]
        cur = (pref or clients)[0]
        sess["client_id"] = cur.id
    return cur, clients


def expire_if_idle(repo: Repo, sess: dict) -> bool:
    """Server-side idle timeout. A stale session is cleared before any event is processed."""
    if sess["email"] and time.time() - sess.get("last_active", 0) > config.SESSION_IDLE_MINUTES * 60:
        u = repo.get_user(sess["email"])
        repo.log("—", "Session expired", u.name if u else sess["email"], "Signed out after inactivity", "Logged", "System")
        sess.update(email=None, onboarding=False, client_id=None, view=None, role_hint="RM", error="")
        _effect(sess, toast="Your session expired after inactivity. Please sign in again.", reset_modals=True)
        return True
    return False


def handle(repo: Repo, sess: dict, ev: dict) -> None:
    """Process one UI event. Every branch re-derives the user from the database; nothing the browser sends is trusted."""
    sess["effect"] = None
    sess["fresh"] = []
    if expire_if_idle(repo, sess):
        return
    sess["last_active"] = time.time()
    act, p = ev.get("action"), ev.get("payload") or {}
    ui = ev.get("ui") or {}
    sess["view"], sess["subtab"] = ui.get("view") or sess["view"], ui.get("subtab") or sess["subtab"]
    user = user_of(repo, sess)
    try:
        if act == "login":
            u, err = auth.authenticate(repo, p.get("email", ""), p.get("password", ""), p.get("role", ""))
            if u is None:
                sess["role_hint"] = p.get("role", "RM"); _effect(sess, toast=err, select_role=p.get("role", "RM")); return
            sess.update(email=u.email, error="", client_id=None, view=None, subtab="overview", onboarding=False, last_active=time.time())
            repo.log("—", "Sign-in", u.name, f"{u.role} workspace opened", "Logged", "System")
            _effect(sess, toast=f"{u.role} workspace opened. Demo data only.", reset_modals=True, view="__default__")
        elif act == "logout":
            if user:
                repo.log("—", "Sign-out", user.name, "Session ended", "Logged", "System")
            sess.update(email=None, onboarding=False, client_id=None, view=None, role_hint="RM", error="")
            _effect(sess, reset_modals=True)
        elif act == "start_signup":
            sess.update(onboarding=True, email=None)
            _effect(sess, toast="New client onboarding opened. Consent is required only for new client sign-up.")
        elif act == "accept_consent":
            if p.get("password") != p.get("password2"):
                raise ValueError("The two passwords do not match.")
            u = services.accept_onboarding_consent(repo, p.get("email", ""), p.get("password", ""), bool(p.get("terms")), bool(p.get("ai")))
            sess.update(email=u.email, onboarding=False, last_active=time.time())
            _effect(sess, toast="Account created and consent recorded. No trades are enabled.", reset_modals=True)
        elif user is None:
            return
        elif act == "select_client":
            c = services.get_client(repo, user, p.get("id", ""))
            sess["client_id"] = c.id
            sess["fresh"] = FRESH_CLIENT_FIELDS
            eff = dict(toast=f"Selected {c.name}.")
            if p.get("goto"):
                eff["view"] = p["goto"]
            elif p.get("review"):
                eff["view"] = "workbench"
            if p.get("review"):
                eff["open_modal"] = "reviewModal"
            _effect(sess, **eff)
        elif act == "save_review":
            c, _ = _active_client(repo, user, sess)
            services.save_rm_decision(repo, user, c.id, p.get("note", ""), p.get("decision", ""), p.get("tier", ""),
                                      int(p["target"]) if str(p.get("target", "")).strip() != "" else None, p.get("rationale", ""), bool(p.get("convo")))
            _effect(sess, close_modal="reviewModal", toast="RM decision recorded in the audit log. Consent and execution gates remain separate.")
        elif act == "run_agent":
            c, _ = _active_client(repo, user, sess)
            repo.s.commit()                                           # release the write lock before any network call
            _effect(sess, toast=services.run_agent(repo, user, c.id))
        elif act == "request_consent":
            c, _ = _active_client(repo, user, sess)
            services.request_consent(repo, user, c.id)
            _effect(sess, toast="Consent request draft recorded. No message was sent and no consent was received.")
        elif act == "save_note":
            c, _ = _active_client(repo, user, sess)
            services.add_note(repo, user, c.id, p.get("text", ""))
            sess["fresh"] = ["noteText"]
            _effect(sess, close_modal="notesModal", toast="Note saved to the audit trail.", subtab="activity")
        elif act == "mark_draft_ready":
            c, _ = _active_client(repo, user, sess)
            services.mark_draft_ready(repo, user, c.id, p.get("subject", ""), p.get("body", ""))
            _effect(sess, close_modal="messageModal", toast="Client message marked ready for RM review; not sent.")
        elif act == "save_pref":
            c, _ = _active_client(repo, user, sess)
            services.save_contact_pref(repo, user, c.id, p.get("pref", ""))
            _effect(sess, toast="Preference saved.")
        elif act == "ask":
            c, _ = _active_client(repo, user, sess)
            _effect(sess, ask_answer=services.answer_question(repo, user, c.id if c else None, p.get("question", "")))
        elif act == "detail":
            c, _ = _active_client(repo, user, sess)
            if p.get("what") == "market":
                _effect(sess, toast="Market and event feeds are not connected yet; no market claims are shown until real, timestamped data is available.")
            else:
                _effect(sess, ask_answer=services.answer_question(repo, user, c.id, "goal"), open_modal="askModal")
        elif act == "reminders":
            clients = services.clients_for(repo, user)
            recs = repo.recs_for([c.id for c in clients])
            n_draft = sum(1 for c in clients if c.id in recs and recs[c.id].status == "Draft")
            n_cons = sum(1 for c in clients if not repo.has_active_consent(c.id))
            _effect(sess, toast=f"You have {n_draft} recommendation(s) awaiting review and {n_cons} consent item(s) pending.")
        elif act == "export_queue":
            _effect(sess, download=dict(filename="client-queue.csv", mime="text/csv", content=services.export_queue_csv(repo, user)), toast="Queue exported.")
        elif act == "export_audit":
            content = services.export_audit_csv(repo, user)
            repo.log("—", "Audit log exported", user.name, "CSV download", "Logged", "System")
            _effect(sess, download=dict(filename="audit-log.csv", mime="text/csv", content=content), toast="Audit log exported.")
        elif act == "report":
            c, _ = _active_client(repo, user, sess)
            tpl = p.get("template", "Portfolio review report")
            if tpl not in ("Portfolio review report", "Quarterly portfolio review", "AI recommendation rationale"):
                raise ValueError("Unknown report template.")
            body = services.review_report(repo, user, c.id, tpl)
            repo.log(c.name, "Report generated", user.name, tpl, "Logged", "RM", client_id=c.id)
            _effect(sess, download=dict(filename=f"{c.id}-report.md", mime="text/markdown", content=body), toast=f"{tpl} generated for {c.name}.")
        elif act == "load_perms":
            services.require_role(user, "Admin")
            rm = next((r for r in repo.list_rms() if r.name == p.get("rm")), None)
            if rm:
                sess["perm_rm"] = rm.id
            _effect(sess)
        elif act == "save_perms":
            services.save_rm_permissions(repo, user, p.get("rm", ""), bool(p.get("schedule")), bool(p.get("all_clients")), p.get("approval", ""), bool(p.get("override")))
            rm = next((r for r in repo.list_rms() if r.name == p.get("rm")), None)
            if rm:
                sess["perm_rm"] = rm.id
            _effect(sess, toast="RM permissions saved.")
        elif act == "source":
            services.set_source(repo, user, p.get("id", ""), bool(p.get("on")))
            _effect(sess, toast="Data source list updated. No external connection was made.")
        elif act == "save_schedule":
            services.save_schedule(repo, user, p.get("cfg") or {})
            _effect(sess, toast="Schedule saved. The scheduler worker runs it at the scheduled time (UTC). Use Run now to execute immediately.")
        elif act == "run_preview":
            _effect(sess, toast=services.run_preview(repo, user, p.get("cfg") or {}))
        elif act == "run_now":
            repo.s.commit()                                           # release the write lock before network and agent work
            _effect(sess, toast=services.run_now(repo, user, p.get("cfg") or {}))
        elif act in ("market_refresh", "market_refresh_if_stale"):
            services.require_role(user, "RM", "Admin")
            if act == "market_refresh_if_stale" and not services.external_data_is_stale(repo):
                _effect(sess)
            else:
                repo.s.commit()                                   # release the write lock before network calls
                _effect(sess, toast=services.refresh_external_data(repo, user, force=(act == "market_refresh")))
        elif act == "withdraw_consent":
            services.withdraw_consent(repo, user, user.client_id)
            _effect(sess, close_modal="withdrawModal", toast="Consent withdrawn. Monitoring and recommendations for your account are paused.")
        elif act == "regrant_consent":
            services.regrant_consent(repo, user, user.client_id, bool(p.get("terms")), bool(p.get("ai")))
            _effect(sess, close_modal="regrantModal", toast="Thank you. Consent recorded.")
    except services.Denied as ex:
        repo.s.rollback()
        repo.log("—", "Access denied", user.name if user else "anonymous", f"{act}: {ex}"[:300], "Rejected", "System")
        _effect(sess, toast=str(ex))
    except ValueError as ex:
        repo.s.rollback()
        _effect(sess, toast=str(ex))
    except Exception:                                              # unexpected: log details SERVER-side only, show a reference to the user
        ref = uuid.uuid4().hex[:8]
        logging.getLogger("dwn").exception("UI event %s failed (ref %s)", act, ref)
        repo.s.rollback()
        try:
            repo.log("—", "Internal error", user.name if user else "anonymous", f"{act}; reference {ref}", "Rejected", "System")
        except Exception:
            pass
        _effect(sess, toast=f"Something went wrong and nothing was changed. Reference {ref}.")


def build(repo: Repo, sess: dict) -> dict:
    user = user_of(repo, sess)
    effect = sess.get("effect")
    if not user:
        html = (('<div class="app" id="appShell"><div class="layout">' + R.onboarding() + '</div></div>') if sess["onboarding"] else R.login_gate(sess["role_hint"], "", demo=config.seed_demo_data(), demo_pw_known=_demo_pw_known())) + '<div class="toast" id="toast"></div>'
        payload = dict(html=html, role="Client" if sess["onboarding"] else "", allowed=["onboarding"] if sess["onboarding"] else [], default_view="onboarding",
                       demo_defaults=config.seed_demo_data(), demo_pw_known=_demo_pw_known())
        payload.update(_finish(html, effect, sess))
        return payload
    c, clients = _active_client(repo, user, sess)
    vd = ViewData(repo, user, clients, c)
    if user.role == "Client":
        html = ('<div class="app" id="appShell"><div class="layout">' + R.client_portal(vd, user) + '</div></div>'
                '<div class="toast" id="toast"></div>')
        payload = dict(html=html, role="Client", allowed=["clientportal"], default_view="clientportal")
        payload.update(_finish(html, effect, sess))
        return payload
    pick = services.clients_for(repo, user, for_scheduling=True)
    saved = repo.get_schedule(user.email)
    n_draft = sum(1 for x in clients if vd.rec(x.id).status == "Draft")
    n_tasks = sum(1 for x in clients if vd.rec(x.id).status == "Draft" or not vd.has_active_consent(x.id))
    can_sched = services.rm_can_schedule(repo, user)
    if user.role == "Admin":
        main = R.compliance(vd, user, c) + R.settings(vd, user, pick, saved, sess["perm_rm"])
        allowed, default = ["compliance", "settings"], "settings"
    else:
        main = (R.workbench(vd, user, clients, c, sess) + R.clientview(vd, user, c) + R.home(vd, user, clients) + R.clients_page(clients) +
                R.insights(vd, clients) + R.research(vd) + R.tasks(vd, clients) + R.reports() +
                (R.settings(vd, user, pick, saved, sess["perm_rm"]) if can_sched else ""))
        allowed = ["home", "workbench", "clientview", "clients", "insights", "research", "tasks", "reports"] + (["settings"] if can_sched else [])
        default = "workbench"
    html = ('<div class="app" id="appShell">' + R._topbar(user, vd, n_draft) + '<div class="layout">' + R._nav(vd, user, n_tasks) +
            '<main class="main">' + main + '</main></div></div>' + R.modals(vd, user, c, readonly=(user.role == "Admin")))
    payload = dict(html=html, role=user.role, allowed=allowed, default_view=default, settings_denied=(user.role == "RM" and not can_sched))
    payload.update(_finish(html, effect, sess))
    return payload


def _finish(html, effect, sess) -> dict:
    out = dict(render_key=hashlib.sha1(html.encode()).hexdigest(), fresh_fields=sess.get("fresh", []))
    if effect:
        eff = dict(effect)
        if eff.get("view") == "__default__":
            eff.pop("view")
        out["effect"] = eff
    return out
