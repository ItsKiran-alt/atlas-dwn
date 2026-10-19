"""Application services. EVERY function re-checks permissions server-side; hiding a button is cosmetic.

There is deliberately no function here that places an order, moves money or sends a message.
"""
from __future__ import annotations

import csv
import io

from . import config, seed
from .domain import CONSENT_SHA256, CONSENT_TEXT, CONSENT_VERSION, Client, Rec, User, utcnow
from .data.http import Fetcher
from .data.market import MarketService
from .data.news import NewsService
from .engines.portfolio import CLASS_LABEL, headline_drift
from .repo import Repo
from .security import hash_password

TIER_RANK = {"Tier 1": 1, "Tier 2": 2, "Tier 3": 3}


class Denied(PermissionError):
    pass


# ---------------- authorisation ----------------
def clients_for(repo: Repo, user: User, for_scheduling: bool = False) -> list[Client]:
    """Scoping happens in SQL: an RM never loads another RM's rows, a client never loads another client's row."""
    if user.role == "Admin":
        return repo.list_clients(include_all=True)
    if user.role == "RM":
        if for_scheduling and repo.get_perms(user.rm_id)["all_clients"]:
            return repo.list_clients(include_all=True)
        own = repo.list_clients(rm_id=user.rm_id)
        extra = [i for i in repo.second_approver_client_ids(user.rm_id) if i not in {c.id for c in own}]
        return own + repo.list_clients_by_ids(extra)                     # Tier 3 cases routed to this RM as second approver
    if user.role == "Client":
        return repo.list_clients(client_id=user.client_id)
    return []


def get_client(repo: Repo, user: User, client_id: str) -> Client:
    for c in clients_for(repo, user):
        if c.id == client_id:
            return c
    raise Denied("You are not authorised to access this client record.")


def require_role(user: User | None, *roles: str) -> User:
    if user is None or user.role not in roles:
        raise Denied("This action is not available for your role.")
    return user


def rm_can_schedule(repo: Repo, user: User) -> bool:
    return user.role == "Admin" or (user.role == "RM" and repo.get_perms(user.rm_id)["schedule"])


def monitoring_allowed(repo: Repo, client_id: str) -> bool:
    """Policy gate used by every workflow: no active monitoring consent means no analysis, recommendation or approval."""
    return repo.has_active_consent(client_id)


def require_monitoring_consent(repo: Repo, client: Client):
    if not monitoring_allowed(repo, client.id):
        raise Denied(f"Monitoring consent is not on file for {client.name}. Processing is paused until the client consents.")


# ---------------- consent & accounts ----------------
def accept_onboarding_consent(repo: Repo, email: str, password: str, terms: bool, ai: bool) -> User:
    """New-client onboarding: creates the account (hashed password) and records versioned consent once."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise ValueError("Enter your email to complete onboarding.")
    if len(email) > 150:
        raise ValueError("That email address is too long.")
    if not (terms and ai):
        raise ValueError("Please accept both Terms & Conditions and AI monitoring consent to continue.")
    if len(password or "") < config.MIN_PASSWORD_LEN:
        raise ValueError(f"Choose a password of at least {config.MIN_PASSWORD_LEN} characters.")
    if repo.user_exists(email):
        raise ValueError("An account already exists for this email. Please sign in instead.")
    n = repo.next_portal_number()
    cid = f"c-portal-{n}"
    name = " ".join(w.capitalize() for w in email.split("@")[0].replace("_", ".").replace("-", ".").split("."))[:100]
    repo.add_client(Client(id=cid, name=name, rm_id="", aum_musd=0.0, issue="Awaiting account linkage", kind="approval", status_label="Action",
                           status_class="", since=utcnow().year, email=email, source="portal"))
    user = User(email, name, "Client", client_id=cid, initials="CL")
    repo.create_user(user, hash_password(password))
    repo.add_consent(cid, email, CONSENT_VERSION, CONSENT_SHA256)
    repo.log(name, "New client onboarding consent accepted", "Client", f"Consent version {CONSENT_VERSION}; AI monitoring only, no trading authority", "Logged", "Consent", client_id=cid)
    return user


def withdraw_consent(repo: Repo, user: User, client_id: str):
    c = get_client(repo, user, client_id)
    if user.role != "Client" or user.client_id != c.id:
        raise Denied("Only the client can withdraw their own consent.")
    if not repo.has_active_consent(c.id):
        raise ValueError("Monitoring consent is already withdrawn.")
    repo.withdraw_consent(c.id)
    repo.log(c.name, "Consent withdrawn", user.name, "Monitoring and recommendations paused for this client; no data deleted", "Logged", "Consent", client_id=c.id)


def regrant_consent(repo: Repo, user: User, client_id: str, terms: bool, ai: bool):
    c = get_client(repo, user, client_id)
    if user.role != "Client" or user.client_id != c.id:
        raise Denied("Only the client can give their own consent.")
    if not (terms and ai):
        raise ValueError("Please accept both Terms & Conditions and AI monitoring consent to continue.")
    if repo.has_active_consent(c.id):
        raise ValueError("Monitoring consent is already active.")
    repo.add_consent(c.id, user.email, CONSENT_VERSION, CONSENT_SHA256)
    repo.log(c.name, "Consent given", user.name, f"Consent version {CONSENT_VERSION}", "Logged", "Consent", client_id=c.id)


# ---------------- RM workflow ----------------
def recommendation(repo: Repo, client_id: str, title: str = "") -> Rec:
    return repo.get_rec(client_id, title)


def rationale_for(client: Client) -> tuple[str, str]:
    """Deterministic, data-grounded rationale text (no LLM)."""
    k, d = headline_drift(client.weights, client.plan)
    name = CLASS_LABEL[k]
    if abs(d) < 0.5:
        return (f"Review {client.issue.lower()}",
                f"No allocation drift above 0.5 points versus plan. Current review reason: {client.issue.lower()}. Confirm goals, liquidity and suitability.")
    direction = "above" if d > 0 else "below"
    return ("Review allocation drift",
            f"Current {name.lower()} exposure is {client.weights[k]}%, {abs(d):g} points {direction} the {client.plan[k]}% target. "
            "Consider whether rebalancing remains suitable given the client's goals, taxes, liquidity needs and market conditions.")


def save_rm_decision(repo: Repo, user: User, client_id: str, note: str, decision: str, tier: str, target_equity: int | None, rationale: str,
                     conversation_held: bool = False) -> Rec:
    require_role(user, "RM")
    c = get_client(repo, user, client_id)
    require_monitoring_consent(repo, c)
    prop = repo.latest_proposal(client_id)
    if prop and prop["status"] in ("awaiting_rm", "awaiting_second", "edited", "blocked", "digest"):
        decide_proposal(repo, user, client_id, decision, note, conversation_held, rationale)
        return repo.get_rec(client_id, c.issue)
    note = (note or "").strip()
    if not note:
        raise ValueError("Please add an RM review note before recording the decision.")
    if decision not in ("approve", "edit", "reject"):
        raise ValueError("Unknown decision.")
    need = " ".join(tier.split(" ")[:2])
    if need not in TIER_RANK:
        raise ValueError("Unknown approval tier.")
    have = repo.get_perms(user.rm_id)["approval"]
    if decision == "approve" and TIER_RANK[need] > TIER_RANK[have]:
        raise Denied(f"Your approval authority is {have}. A {need} item needs a higher-level approver.")
    if target_equity is not None and not (0 <= int(target_equity) <= 100):
        raise ValueError("Target equity must be between 0 and 100.")
    r = recommendation(repo, c.id, c.issue)
    r.status = {"approve": "RM reviewed", "edit": "Edited", "reject": "Rejected"}[decision]
    r.note, r.tier, r.decided_by = note, tier, user.name
    if rationale.strip():
        r.rationale = rationale.strip()
    repo.save_rec(r, decided_at=utcnow())
    repo.log(c.name, f"RM decision: {decision}", user.name, note, "Rejected" if decision == "reject" else "Logged", "RM", client_id=c.id)
    return repo.get_rec(c.id)


def request_consent(repo: Repo, user: User, client_id: str):
    require_role(user, "RM")
    c = get_client(repo, user, client_id)
    r = recommendation(repo, c.id, c.issue)
    r.consent_request, r.client_message = "Request drafted", "Draft prepared"
    repo.save_rec(r)
    repo.log(c.name, "Consent request drafted", user.name, "Draft request prepared; no consent received and no trade authority granted", "Awaiting client", "Consent", client_id=c.id)


def add_note(repo: Repo, user: User, client_id: str, text: str):
    require_role(user, "RM")
    c = get_client(repo, user, client_id)
    text = (text or "").strip()
    if not text:
        raise ValueError("Please enter a note.")
    if len(text) > 4000:
        raise ValueError("Notes are limited to 4,000 characters.")
    repo.add_note(c.id, text, user.name)
    repo.log(c.name, "Adviser note added", user.name, text, "Logged", "RM", client_id=c.id)


def get_draft(repo: Repo, client: Client) -> dict:
    d = repo.get_draft(client.id)
    if d:
        return d
    first = client.name.split(" ")[0]
    k, dv = headline_drift(client.weights, client.plan)
    why = (f"your {CLASS_LABEL[k].lower()} allocation is {'above' if dv > 0 else 'below'} your current target" if abs(dv) >= 0.5
           else f"we would like to review {client.issue.lower()}")
    rm = next((r.name for r in repo.list_rms() if r.id == client.rm_id), "Your Relationship Manager")
    return dict(subject="Your portfolio review — suggested discussion", status="Not shared",
                body=(f"Hello {first},\n\nWe have reviewed your portfolio and noticed that {why}. We would like to discuss whether an adjustment "
                      "remains appropriate in light of your goals, risk profile, liquidity needs and any tax or transaction-cost considerations.\n\n"
                      f"No action has been taken. We can review the options together at your next meeting.\n\nRegards,\n{rm}"))


def mark_draft_ready(repo: Repo, user: User, client_id: str, subject: str, body: str):
    require_role(user, "RM")
    c = get_client(repo, user, client_id)
    require_monitoring_consent(repo, c)
    repo.save_draft(c.id, subject[:200], body[:8000], "Ready for RM review")
    r = recommendation(repo, c.id, c.issue)
    r.client_message = "Ready for RM review"
    repo.save_rec(r)
    repo.log(c.name, "Client message marked ready for RM review", user.name, "Draft only; nothing sent", "Logged", "RM", client_id=c.id)


def save_contact_pref(repo: Repo, user: User, client_id: str, pref: str):
    require_role(user, "RM")
    c = get_client(repo, user, client_id)
    repo.set_contact_pref(c.id, (pref or "")[:120])
    repo.log(c.name, "Communication preference saved", user.name, pref, "Logged", "RM", client_id=c.id)


def answer_question(repo: Repo, user: User, client_id: str | None, question: str) -> str:
    """RM Copilot: answers ONLY from the authorised records below and cites them. Uses the configured LLM if any, else deterministic rules."""
    q0 = (question or "").strip()
    if not q0:
        raise ValueError("Enter a question or choose a suggested prompt.")
    if len(q0) > 1000:
        raise ValueError("Questions are limited to 1,000 characters.")
    if not client_id:
        return "Select a client first so the answer can be grounded in that client's authorised records."
    from .agents.llm import make_llm
    from .agents.skills import Copilot, run_skill
    c = get_client(repo, user, client_id)
    if not repo.has_active_consent(c.id):                                  # no consent = no analysis, including conversational analysis
        return f"Monitoring consent is not on file for {c.name}. Processing is paused, so no analysis or summary is provided."
    recs: dict[str, str] = {}
    k, d = headline_drift(c.weights, c.plan)
    recs["allocation"] = (f"{c.name}'s {CLASS_LABEL[k].lower()} weight is {c.weights[k]}% against a {c.plan[k]}% plan ({d:+g} points)." if abs(d) >= 0.5
                          else f"No allocation class differs from plan by 0.5 points or more for {c.name}.")
    for i, g in enumerate(c.goals):
        recs[f"goal{i + 1}"] = f"Goal {g.name}: {g.detail}; about {g.progress}% on track (illustrative)."
    recs["consent"] = "Monitoring consent is on file." if repo.has_active_consent(c.id) else "Monitoring consent is NOT on file; processing is paused."
    prop = repo.latest_proposal(c.id)
    if prop:
        b = prop["body"]
        recs["proposal"] = f"Latest proposal: Tier {prop['tier']}, status {prop['status'].replace('_', ' ')}. {b['summary']}"
    for qq in repo.latest_quote("^GSPC") and [repo.latest_quote("^GSPC")] or []:
        recs["market"] = f"S&P 500 {qq.price:,.2f} ({qq.change_pct:+.2f}% vs previous close) as of {qq.market_time} UTC via {qq.provider_name}." if qq.change_pct is not None else f"S&P 500 {qq.price:,.2f} as of {qq.market_time} UTC."
    r = run_skill(Copilot(), make_llm(), {"question": q0, "records": recs})
    out = r.output
    if out.abstain:
        return "Insufficient evidence to assess. The authorised records for this client do not answer that question."
    return out.answer + "  [Sources: " + ", ".join(out.citations) + (" · template, no AI" if r.used_fallback else f" · {r.provider}") + "]"


def _answer_question_rules(repo: Repo, user: User, client_id: str | None, question: str) -> str:
    """Previous rule-based implementation (kept for reference and as a last resort)."""
    q = (question or "").lower().strip()
    if not q:
        raise ValueError("Enter a question or choose a suggested prompt.")
    if not client_id:
        return "Select a client first so the answer can be grounded in that client's authorised records."
    c = get_client(repo, user, client_id)
    r = recommendation(repo, c.id, c.issue)
    k, d = headline_drift(c.weights, c.plan)
    if "goal" in q:
        gl = "; ".join(f"{g.name} ({g.detail}, about {g.progress}% on track, illustrative)" for g in c.goals)
        return f"{c.name} has {len(c.goals)} recorded goal(s): {gl}. Confirm dates, assumptions and latest circumstances before relying on a projection."
    if "pending" in q or "check" in q:
        consent = "recorded" if repo.has_active_consent(c.id) else "NOT on file (processing paused)"
        return (f"Monitoring consent is {consent}. RM review status: {r.status}. Consent request: {r.consent_request}. "
                "Execution remains locked; RM review and client consent are separate steps and tax/transaction-cost review may also be required.")
    if abs(d) < 0.5:
        return f"No allocation class differs from plan by 0.5 points or more for {c.name}. Review reason on record: {c.issue}."
    return (f"{c.name}'s {CLASS_LABEL[k].lower()} weight is {c.weights[k]}% against a {c.plan[k]}% plan ({d:+g} points). "
            "A deterministic calculation from the stored holdings; the adviser should review goals, liquidity, taxes and costs before deciding.")


# ---------------- admin ----------------
def save_rm_permissions(repo: Repo, user: User, rm_name: str, schedule: bool, all_clients: bool, approval: str, override: bool):
    require_role(user, "Admin")
    rm = next((r for r in repo.list_rms() if r.name == rm_name), None)
    if rm is None or approval not in TIER_RANK:
        raise ValueError("Unknown relationship manager or approval tier.")
    repo.set_perms(rm.id, schedule, all_clients, approval, override)
    repo.log("All assigned clients", "RM permissions changed", user.name,
             f"{rm.name}: scheduling {'on' if schedule else 'off'}, {'all clients' if all_clients else 'assigned clients'}, {approval}, override requests {'permitted' if override else 'off'}", "Logged", "System")


def set_source(repo: Repo, user: User, source_id: str, enabled: bool):
    require_role(user, "Admin")
    if not repo.set_source_enabled(source_id, enabled):
        raise ValueError("Unknown data source.")
    repo.log("All clients", "Data source " + ("added" if enabled else "removed"), user.name, repo.source_label(source_id), "Logged", "System")


# ---------------- scheduler ----------------
SCOPES = ["Portfolio drift", "Risk & scenarios", "Goal progress", "Market events", "RM draft recommendations"]


def _validated_cfg(repo: Repo, user: User, cfg: dict) -> dict:
    """Server-side validation shared by Save and Run now. Permission and client scope are enforced here, not in the UI."""
    if not rm_can_schedule(repo, user):
        raise Denied("Your administrator has not enabled scheduling access.")
    if cfg.get("frequency") not in ("daily", "weekly", "monthly"):
        raise ValueError("Unknown frequency.")
    if cfg.get("frequency") == "weekly" and not cfg.get("days"):
        raise ValueError("Select at least one day for a weekly schedule.")
    if not set(cfg.get("scopes") or []) <= set(SCOPES):
        raise ValueError("Unknown workflow scope.")
    if cfg.get("client_scope") not in ("All assigned clients", "Tier 1 clients only", "Clients flagged for review", "Selected client only"):
        raise ValueError("Unknown client scope.")
    if cfg.get("client_scope") == "Selected client only":
        allowed = {c.id for c in clients_for(repo, user, for_scheduling=True)}
        chosen = cfg.get("clients") or []
        if not chosen:
            raise ValueError("Select at least one client for this schedule.")
        if not set(chosen) <= allowed:
            raise Denied("One or more selected clients are outside the scope granted to you.")
    clean = {k: cfg.get(k) for k in ("name", "frequency", "time", "days", "month_day", "scopes", "client_scope", "enabled", "clients")}
    clean["name"] = (clean["name"] or "")[:120]
    return clean


def save_schedule(repo: Repo, user: User, cfg: dict):
    clean = _validated_cfg(repo, user, cfg)
    repo.save_schedule(user.email, clean)
    repo.log("All assigned clients" if cfg.get("client_scope") != "Selected client only" else f"{len(cfg['clients'])} selected clients",
             "Schedule configuration saved", user.name, describe_schedule(cfg) + " (UTC)", "Logged", "System")


def describe_schedule(cfg: dict) -> str:
    f, t = cfg.get("frequency", "weekly"), cfg.get("time") or "08:30"
    if f == "daily":
        return f"Daily at {t}"
    if f == "monthly":
        return f"Monthly on day {cfg.get('month_day', '1')} at {t}"
    return "Weekly · " + (", ".join(cfg.get("days", [])) or "no days selected") + " · " + t


def run_preview(repo: Repo, user: User, cfg: dict) -> str:
    """DRY RUN: shows what a run would cover. Nothing is executed or written except an audit line."""
    clean = _validated_cfg(repo, user, cfg)
    from .scheduler.jobs import scope_clients
    clients, problems = scope_clients(repo, user, clean)
    no_consent = sum(1 for c in clients if not repo.has_active_consent(c.id))
    repo.add_run(user.name, "preview", len(clean.get("scopes", [])), "Preview only")
    repo.log("All assigned clients", "Scheduler preview", user.name, f"{len(clients)} clients in scope; {no_consent} would pause (no consent); {len(problems)} outside scope", "Logged", "System")
    return (f"Preview: {len(clients)} clients in scope, {no_consent} would be paused for missing consent, {len(problems)} outside your granted scope. "
            "No agents were executed and nothing was written. Use Run now to execute.")


def run_now(repo: Repo, user: User, cfg: dict) -> str:
    """Execute the schedule immediately (analysis, drafts and review items only). Recorded in the job history like any other run."""
    clean = _validated_cfg(repo, user, cfg)
    from .agents.llm import make_llm
    from .scheduler.jobs import run_job
    repo.s.commit()
    r = run_job(repo, user, clean, trigger="manual", llm=make_llm())
    return f"Run {r.status}: {r.message}. Drafts are waiting in the RM queue; nothing was approved, traded or sent."


def scheduler_view(repo: Repo, user: User, cfg: dict | None) -> dict:
    from .scheduler.slots import describe, next_slot
    jobs = repo.list_jobs(None if user.role == "Admin" else user.email, 6)
    nxt = describe(next_slot(cfg, utcnow())) if cfg and cfg.get("enabled") else "schedule paused"
    return dict(jobs=jobs, next=nxt)


# ---------------- exports (real files, built from stored data) ----------------
def export_queue_csv(repo: Repo, user: User) -> str:
    require_role(user, "RM")
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["Client", "AUM (USD millions)", "Review reason", "Status", "Recommendation status"])
    clients = clients_for(repo, user)
    recs = repo.recs_for([c.id for c in clients])
    for c in clients:
        w.writerow([_csv_safe(c.name), c.aum_musd, _csv_safe(c.issue), c.status_label, recs[c.id].status if c.id in recs else "Monitor"])
    return buf.getvalue()


def _csv_safe(v: str) -> str:
    """Neutralise spreadsheet formula injection."""
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def export_audit_csv(repo: Repo, user: User) -> str:
    require_role(user, "Admin")
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["Date & time (UTC)", "Client", "Action", "Actor", "Details", "Status"])
    for e in repo.list_audit(limit=100000):
        w.writerow([e.ts, _csv_safe(e.client), e.action, e.actor, _csv_safe(e.details), e.status])
    return buf.getvalue()


def review_report(repo: Repo, user: User, client_id: str, template: str) -> str:
    require_role(user, "RM")
    c = get_client(repo, user, client_id)
    require_monitoring_consent(repo, c)
    r = recommendation(repo, c.id, c.issue)
    lines = [f"# {template}: {c.name}", f"Prepared by {user.name}. Fictional demo data. Decision support, not advice.", "",
             f"Portfolio value: ${c.aum_musd:.1f}M · Risk profile: {c.risk_profile}", "", "## Allocation vs plan"]
    for k in CLASS_LABEL:
        lines.append(f"- {CLASS_LABEL[k]}: {c.weights.get(k, 0)}% (plan {c.plan.get(k, 0)}%, {c.weights.get(k, 0) - c.plan.get(k, 0):+g} pts)")
    lines += ["", "## Recommendation", f"Status: {r.status}. {r.rationale or rationale_for(c)[1]}", "", "## Approvals and audit"]
    lines += [f"- {e.ts} UTC · {e.action} · {e.actor} · {e.status}" for e in repo.list_audit(limit=10, client_name=c.name)]
    lines += ["", "Execution is locked in this prototype. No trade or message has been sent."]
    return "\n".join(lines)


# ---------------- external market and news data ----------------
def _fetcher_factory() -> Fetcher:           # tests replace this with a mock transport
    return Fetcher()


def refresh_external_data(repo: Repo, user: User, force: bool = False) -> str:
    """Fetch real prices and official news into the cache. RM/Admin only, throttled, audited. Never invents data."""
    require_role(user, "RM", "Admin")
    now = utcnow()
    last = repo.last_audit_ts("External data refresh")
    if last and (now - last).total_seconds() < config.MANUAL_REFRESH_MIN_GAP_S:
        return f"Data was refreshed {int((now - last).total_seconds())}s ago. Showing the cached values (minimum gap {config.MANUAL_REFRESH_MIN_GAP_S}s)."
    fetcher = _fetcher_factory()
    m = MarketService(repo, fetcher).refresh(force=force)
    n = NewsService(repo, fetcher).refresh(force=force)
    parts = [f"prices ok {len(m['ok'])}/{len(m['ok']) + len(m['failed'])}", f"new headlines {n['new']}"]
    if m["failed"]:
        parts.append("price failures: " + "; ".join(f"{k} ({v[:60]})" for k, v in list(m["failed"].items())[:3]))
    if n["failed"]:
        parts.append("feed failures: " + ", ".join(n["failed"]))
    if n["quarantined"]:
        parts.append(f"{n['quarantined']} item(s) quarantined")
    problems = bool(m["failed"] or n["failed"])
    repo.log("—", "External data refresh", user.name, " · ".join(parts), "Review" if problems else "Logged", "System")
    if problems:
        return "Refresh finished with problems: " + " · ".join(parts[2:]) + ". Last successful data is shown with its age."
    return "Market data and headlines refreshed from the live sources."


def external_data_is_stale(repo: Repo) -> bool:
    q = repo.latest_quote("^GSPC")
    return q is None or (utcnow() - q.retrieved_at).total_seconds() > config.MARKET_CACHE_TTL_S * 5


# ---------------- agent runs and the human approval workflow ----------------
def _rank(a: str) -> int:
    return TIER_RANK.get(a, 0)


def run_agent(repo: Repo, user: User, client_id: str) -> str:
    """RM triggers a monitoring run for one client. Real cached market data is used; a stale cache is refreshed first (throttled)."""
    require_role(user, "RM")
    from .agents.llm import make_llm
    from .agents.orchestrator import run_monitoring
    c = get_client(repo, user, client_id)
    note = ""
    if external_data_is_stale(repo):
        repo.s.commit()
        note = " " + refresh_external_data(repo, user)
    r = run_monitoring(repo, user, c.id, trigger="manual", llm=make_llm())
    if r.status == "duplicate":
        return "Identical inputs were analysed moments ago; showing that result." + note
    if r.status == "failed":
        return "The run failed and nothing was proposed: " + "; ".join(r.notes)[:160]
    if r.status == "paused":
        from .controls.gates import ABSTENTION
        return "Paused: " + ABSTENTION.get(r.paused_reason, r.paused_reason) + note
    return f"Monitoring check complete: Tier {r.tier}. {'A proposal is awaiting your decision.' if r.tier in ('2', '3') else 'Recorded in your digest; no decision needed.'}" + note


def decide_proposal(repo: Repo, user: User, client_id: str, decision: str, note: str, conversation_held: bool = False, rationale: str = ""):
    """Human decisions only. Tier 1: acknowledge. Tier 2: RM decides. Tier 3: RM after a client conversation, then a DIFFERENT second approver."""
    require_role(user, "RM")
    c = get_client(repo, user, client_id)
    require_monitoring_consent(repo, c)
    prop = repo.latest_proposal(client_id)
    if not prop or prop["status"] not in ("awaiting_rm", "awaiting_second", "edited", "blocked", "digest"):
        raise ValueError("There is no open proposal to decide.")
    note = (note or "").strip()
    if not note:
        raise ValueError("Please add an RM review note before recording the decision.")
    if decision not in ("approve", "edit", "reject"):
        raise ValueError("Unknown decision.")
    pid, tier, status = prop["id"], prop["tier"], prop["status"]
    if status == "blocked" and decision == "approve":
        raise Denied("An output control blocked this proposal, so it cannot be approved. Review the failed check or reject it.")
    rec = repo.get_rec(client_id, c.issue)
    if status == "awaiting_second":
        firsts = [a for a in repo.approvals_for(pid) if a["stage"] == "first"]
        first_rm = next((r.id for r in repo.list_rms() if firsts and r.name == firsts[-1]["approver"]), "")
        if user.rm_id == first_rm:
            raise Denied("The second approver must be a different person from the first approver.")
        if _rank(repo.get_perms(user.rm_id)["approval"]) < 2:
            raise Denied("A second approver needs senior-adviser authority (Tier 2 or higher).")
        if prop["second_approver_rm_id"] and prop["second_approver_rm_id"] != user.rm_id:
            raise Denied("This case is routed to a different second approver.")
        if decision == "edit":
            raise ValueError("The second approver can approve or reject; edits go back to the first approver by rejecting.")
        repo.add_approval(pid, "second", user.name, user.rm_id, decision, note)
        new = "approved" if decision == "approve" else "rejected"
        repo.update_proposal(pid, status=new, second_approver=user.name)
        rec.status = "RM reviewed" if decision == "approve" else "Rejected"
        rec.decided_by, rec.note = user.name, note
        repo.save_rec(rec, decided_at=utcnow())
        repo.log(c.name, f"Second approval: {decision}", user.name, note, "Rejected" if decision == "reject" else "Logged", "RM", client_id=client_id)
        return
    if user.rm_id != c.rm_id:
        raise Denied("Only the client's relationship manager records the first decision.")
    if tier == "3" and decision == "approve" and not conversation_held:
        raise ValueError("Tier 3: confirm that you have spoken with the client before approving.")
    repo.add_approval(pid, "first", user.name, user.rm_id, decision, note)
    if decision == "reject":
        new = "rejected"
    elif decision == "edit":
        new = "edited"
        if rationale.strip():
            body = prop["body"]; body["summary"] = rationale.strip()[:1500]
            repo.s.execute(__import__("sqlalchemy").text("update proposals set body_json=:b where id=:i"), dict(b=__import__("json").dumps(body), i=pid))
    elif tier == "3":
        new = "awaiting_second"
    else:
        new = "approved"
    fields = dict(status=new, first_approver=user.name)
    if new == "awaiting_second" and not prop["second_approver_rm_id"]:
        from .agents.orchestrator import _pick_second_approver
        fields["second_approver_rm_id"] = _pick_second_approver(repo, c.rm_id)
    repo.update_proposal(pid, **fields)
    rec.status = {"approved": "RM reviewed", "awaiting_second": "RM reviewed", "edited": "Edited", "rejected": "Rejected"}[new]
    rec.decided_by, rec.note = user.name, note
    if rationale.strip():
        rec.rationale = rationale.strip()
    repo.save_rec(rec, decided_at=utcnow())
    repo.log(c.name, f"RM decision: {decision}", user.name, note + (" (routed to second approver)" if new == "awaiting_second" else ""),
             "Rejected" if decision == "reject" else ("Pending" if new == "awaiting_second" else "Logged"), "RM", client_id=client_id)
    if new == "awaiting_second":
        repo.log(c.name, "Second approval required", "Workflow", "Tier 3: a different senior approver must decide after the client conversation", "Pending", "RM", client_id=client_id)
