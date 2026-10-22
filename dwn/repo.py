"""Data access. All SQL lives here; services never touch the session directly.

One Repo is created per UI event on one SQLAlchemy session (see db.session.session_scope), so the writes of a
single action (e.g. RM decision + audit event) commit or roll back together.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import config
from .db import models as M
from .domain import RM, AuditEvent, Client, Goal, Rec, User, fmt_ts, utcnow


class Repo:
    def __init__(self, session: Session):
        self.s = session
        self.memo: dict = {}                     # read-phase cache (each avoided query is a network hop on a hosted DB)
        self.memoize = False                     # on ONLY while a page is being built (no writes happen then), so writes never see stale lookups

    def clear_memo(self):
        self.memo.clear()

    def cached(self, key, fn):
        if not self.memoize:
            return fn()
        if key not in self.memo:
            self.memo[key] = fn()
        return self.memo[key]

    # ---------------- users ----------------
    def get_user(self, email: str) -> User | None:
        r = self._user_row(email)
        return User(r.email, r.name, r.role, r.rm_id, r.client_id, r.initials) if r else None

    def _user_row(self, email: str):
        return self.s.scalar(select(M.UserRow).where(M.UserRow.email == (email or "").strip().lower()))

    def user_exists(self, email: str) -> bool:
        return self._user_row(email) is not None

    def password_hash(self, email: str) -> str | None:
        r = self._user_row(email)
        return r.password_hash if r else None

    def create_user(self, u: User, password_hash: str):
        self.s.add(M.UserRow(email=u.email.lower(), name=u.name, role=u.role, rm_id=u.rm_id, client_id=u.client_id,
                             initials=u.initials, password_hash=password_hash, created_at=utcnow()))
        self.s.flush()

    def lock_state(self, email: str) -> datetime | None:
        r = self._user_row(email)
        return r.locked_until if r and r.locked_until and r.locked_until > utcnow() else None

    def record_login_failure(self, email: str) -> bool:
        """Count a failure; lock the account after too many. Returns True if now locked."""
        r = self._user_row(email)
        if not r:
            return False
        r.failed_attempts = (r.failed_attempts or 0) + 1
        if r.failed_attempts >= config.MAX_FAILED_LOGINS:
            r.locked_until = utcnow() + timedelta(minutes=config.LOCKOUT_MINUTES)
            r.failed_attempts = 0
            return True
        return False

    def record_login_success(self, email: str):
        r = self._user_row(email)
        if r:
            r.failed_attempts, r.locked_until = 0, None

    # ---------------- RMs & permissions ----------------
    def list_rms(self) -> list[RM]:
        return self.cached("rms", lambda: [RM(r.id, r.name, r.email, r.initials) for r in self.s.scalars(select(M.RMRow).order_by(M.RMRow.name.desc()))])

    def add_rm(self, rm: RM):
        self.s.add(M.RMRow(id=rm.id, name=rm.name, email=rm.email, initials=rm.initials))
        self.s.flush()
        self.s.add(M.RMPermissionRow(rm_id=rm.id))
        self.s.flush()

    def all_perms(self) -> dict:
        return self.cached("perms", lambda: {r.rm_id: dict(schedule=r.schedule, all_clients=r.all_clients, approval=r.approval, override=r.override)
                                             for r in self.s.scalars(select(M.RMPermissionRow))})

    def get_perms(self, rm_id: str) -> dict:
        return dict(self.all_perms().get(rm_id) or dict(schedule=False, all_clients=False, approval="Tier 1", override=False))

    def set_perms(self, rm_id: str, schedule: bool, all_clients: bool, approval: str, override: bool):
        r = self.s.get(M.RMPermissionRow, rm_id) or M.RMPermissionRow(rm_id=rm_id)
        r.schedule, r.all_clients, r.approval, r.override = schedule, all_clients, approval, override
        self.s.add(r)
        self.s.flush()

    # ---------------- clients ----------------
    def list_clients(self, rm_id: str | None = None, client_id: str | None = None, include_all: bool = False, ids: list[str] | None = None) -> list[Client]:
        """SQL-level scoping: RM sees only rows with their rm_id; a client only their own row."""
        q = select(M.ClientRow)
        if ids is not None:
            if not ids:
                return []
            q = q.where(M.ClientRow.id.in_(ids))
        elif client_id is not None:
            q = q.where(M.ClientRow.id == client_id)
        elif rm_id is not None:
            q = q.where(M.ClientRow.rm_id == rm_id)
        elif not include_all:
            return []
        rows = list(self.s.scalars(q.order_by(M.ClientRow.position, M.ClientRow.id)))
        ids = [r.id for r in rows]
        goals = self._group(M.GoalRow, ids)
        holds = self._group(M.HoldingRow, ids)
        txs = self._group(M.TransactionRow, ids)
        out = []
        for r in rows:
            out.append(Client(
                id=r.id, name=r.name, rm_id=r.rm_id, aum_musd=r.aum_musd, issue=r.issue, kind=r.kind, status_label=r.status_label,
                status_class=r.status_class, since=r.since, tier=r.tier, email=r.email, risk_profile=r.risk_profile,
                last_reviewed=r.last_reviewed, next_meeting=r.next_meeting, plan=json.loads(r.plan_json), weights=json.loads(r.weights_json),
                goals=[Goal(g.name, g.detail, g.progress, g.short) for g in goals.get(r.id, [])],
                holdings=[(h.asset, h.asset_class, h.value_musd) for h in holds.get(r.id, [])],
                transactions=[(t.date, t.kind, t.investment, t.amount, t.status) for t in txs.get(r.id, [])],
                contact_pref=r.contact_pref, source=r.source, golden_key=r.golden_key))
        return out

    def _group(self, model, ids):
        d: dict = {}
        if ids:
            for row in self.s.scalars(select(model).where(model.client_id.in_(ids)).order_by(model.id)):
                d.setdefault(row.client_id, []).append(row)
        return d

    def add_client(self, c: Client):
        self.s.add(M.ClientRow(id=c.id, name=c.name, rm_id=c.rm_id, aum_musd=c.aum_musd, issue=c.issue, kind=c.kind,
                               status_label=c.status_label, status_class=c.status_class, since=c.since, tier=c.tier, email=c.email,
                               risk_profile=c.risk_profile, last_reviewed=c.last_reviewed, next_meeting=c.next_meeting,
                               plan_json=json.dumps(c.plan), weights_json=json.dumps(c.weights), contact_pref=c.contact_pref,
                               source=c.source, golden_key=c.golden_key, position=self.client_count()))
        self.s.flush()
        for g in c.goals:
            self.s.add(M.GoalRow(client_id=c.id, name=g.name, detail=g.detail, progress=g.progress, short=g.short))
        for a, cl, v in c.holdings:
            self.s.add(M.HoldingRow(client_id=c.id, asset=a, asset_class=cl, value_musd=v))
        for d, k, i, amt, st in c.transactions:
            self.s.add(M.TransactionRow(client_id=c.id, date=d, kind=k, investment=i, amount=amt, status=st))
        self.s.flush()

    def client_count(self) -> int:
        return self.s.scalar(select(func.count()).select_from(M.ClientRow)) or 0

    def next_portal_number(self) -> int:
        return (self.s.scalar(select(func.count()).select_from(M.ClientRow).where(M.ClientRow.source == "portal")) or 0) + 1

    def set_contact_pref(self, client_id: str, pref: str):
        r = self.s.get(M.ClientRow, client_id)
        if r:
            r.contact_pref = pref

    # ---------------- consent ----------------
    def has_active_consent(self, client_id: str) -> bool:
        return self.s.scalar(select(func.count()).select_from(M.ConsentRow).where(
            M.ConsentRow.client_id == client_id, M.ConsentRow.withdrawn_at.is_(None))) > 0

    def consent_map(self, client_ids: list[str]) -> dict[str, bool]:
        """One query for many clients (was one per client)."""
        if not client_ids:
            return {}
        active = set(self.s.scalars(select(M.ConsentRow.client_id).where(M.ConsentRow.client_id.in_(client_ids), M.ConsentRow.withdrawn_at.is_(None))))
        return {i: i in active for i in client_ids}

    def consent_info(self, client_id: str) -> dict | None:
        r = self.s.scalar(select(M.ConsentRow).where(M.ConsentRow.client_id == client_id).order_by(M.ConsentRow.id.desc()))
        if not r:
            return None
        return dict(version=r.version, accepted_at=fmt_ts(r.accepted_at), withdrawn_at=fmt_ts(r.withdrawn_at), active=r.withdrawn_at is None)

    def add_consent(self, client_id: str, email: str, version: str, text_sha256: str, accepted_at: datetime | None = None):
        self.s.add(M.ConsentRow(client_id=client_id, email=email, version=version, text_sha256=text_sha256, accepted_at=accepted_at or utcnow()))
        self.s.flush()

    def withdraw_consent(self, client_id: str):
        for r in self.s.scalars(select(M.ConsentRow).where(M.ConsentRow.client_id == client_id, M.ConsentRow.withdrawn_at.is_(None))):
            r.withdrawn_at = utcnow()
        self.s.flush()

    def count_consents(self, client_id: str | None = None) -> int:
        q = select(func.count()).select_from(M.ConsentRow)
        if client_id:
            q = q.where(M.ConsentRow.client_id == client_id)
        return self.s.scalar(q) or 0

    # ---------------- audit (append-only) ----------------
    def log(self, client: str, action: str, actor: str, details: str, status: str, kind: str, client_id: str = "", ts: datetime | None = None):
        self.s.add(M.AuditRow(ts=ts or utcnow(), client_id=client_id, client_name=client, action=action, actor=actor, details=details, status=status, kind=kind))
        self.s.flush()

    def list_audit(self, limit: int = 200, client_name: str | None = None, client_ids: list[str] | None = None) -> list[AuditEvent]:
        q = select(M.AuditRow).order_by(M.AuditRow.ts.desc(), M.AuditRow.id.desc()).limit(limit)
        if client_name:
            q = q.where(M.AuditRow.client_name == client_name)
        if client_ids is not None:
            q = q.where(M.AuditRow.client_id.in_(client_ids))
        return [AuditEvent(fmt_ts(r.ts), r.client_name, r.action, r.actor, r.details, r.status, r.kind) for r in self.s.scalars(q)]

    def last_audit_ts(self, action: str) -> datetime | None:
        return self.s.scalar(select(func.max(M.AuditRow.ts)).where(M.AuditRow.action == action))

    def audit_count(self) -> int:
        return self.s.scalar(select(func.count()).select_from(M.AuditRow)) or 0

    # ---------------- recommendations ----------------
    def _rec(self, r: M.RecRow) -> Rec:
        return Rec(r.client_id, r.title, r.status, r.rationale, r.tier, r.decided_by, fmt_ts(r.decided_at), r.note, r.consent_request, r.client_message, r.client_approval or "not_required")

    def get_rec(self, client_id: str, default_title: str = "") -> Rec:
        r = self.s.get(M.RecRow, client_id)
        if r is None:
            r = M.RecRow(client_id=client_id, title=default_title, status="Monitor")
            self.s.add(r)
            self.s.flush()
        return self._rec(r)

    def recs_for(self, client_ids: list[str]) -> dict[str, Rec]:
        if not client_ids:
            return {}
        return {r.client_id: self._rec(r) for r in self.s.scalars(select(M.RecRow).where(M.RecRow.client_id.in_(client_ids)))}

    def save_rec(self, rec: Rec, decided_at: datetime | None = None):
        r = self.s.get(M.RecRow, rec.client_id) or M.RecRow(client_id=rec.client_id, title=rec.title)
        r.title, r.status, r.rationale, r.tier, r.decided_by = rec.title, rec.status, rec.rationale, rec.tier, rec.decided_by
        r.note, r.consent_request, r.client_message = rec.note, rec.consent_request, rec.client_message
        r.client_approval = rec.client_approval
        if decided_at:
            r.decided_at = decided_at
        self.s.add(r)
        self.s.flush()

    # ---------------- notes & drafts ----------------
    def add_note(self, client_id: str, text: str, author: str):
        self.s.add(M.NoteRow(client_id=client_id, text=text, author=author, ts=utcnow()))
        self.s.flush()

    def notes_for(self, client_id: str) -> list[tuple]:
        return [(r.client_id, r.text, r.author, fmt_ts(r.ts)) for r in self.s.scalars(select(M.NoteRow).where(M.NoteRow.client_id == client_id).order_by(M.NoteRow.id))]

    def get_draft(self, client_id: str) -> dict | None:
        r = self.s.get(M.DraftRow, client_id)
        return dict(subject=r.subject, body=r.body, status=r.status) if r else None

    def save_draft(self, client_id: str, subject: str, body: str, status: str):
        r = self.s.get(M.DraftRow, client_id) or M.DraftRow(client_id=client_id, subject=subject, body=body)
        r.subject, r.body, r.status = subject, body, status
        self.s.add(r)
        self.s.flush()

    # ---------------- scheduler ----------------
    def get_schedule(self, owner_email: str) -> dict | None:
        r = self.s.get(M.ScheduleRow, owner_email)
        return json.loads(r.cfg_json) if r else None

    def save_schedule(self, owner_email: str, cfg: dict):
        r = self.s.get(M.ScheduleRow, owner_email) or M.ScheduleRow(owner_email=owner_email, cfg_json="{}", saved_at=utcnow())
        r.cfg_json, r.saved_at = json.dumps(cfg), utcnow()
        self.s.add(r)
        self.s.flush()

    def add_run(self, by: str, kind: str, scopes: int, status: str):
        self.s.add(M.ScheduleRunRow(at=utcnow(), by=by, kind=kind, scopes=scopes, status=status))
        self.s.flush()

    def last_run(self) -> dict | None:
        r = self.s.scalar(select(M.ScheduleRunRow).order_by(M.ScheduleRunRow.id.desc()))
        return dict(at=fmt_ts(r.at), by=r.by, kind=r.kind, scopes=r.scopes, status=r.status) if r else None

    # ---------------- data sources ----------------
    def list_sources(self) -> list[dict]:
        return [self._source(r) for r in self.s.scalars(select(M.DataSourceRow).order_by(M.DataSourceRow.is_primary.desc(), M.DataSourceRow.mode.desc(), M.DataSourceRow.id))]

    @staticmethod
    def _source(r) -> dict:
        return dict(id=r.id, name=r.name, label=r.label, reads=r.reads, primary=r.is_primary, enabled=r.enabled, mode=r.mode,
                    last_success=fmt_ts(r.last_success), last_success_dt=r.last_success, last_error=r.last_error, last_error_at=fmt_ts(r.last_error_at),
                    failures=r.consecutive_failures, calls_today=r.calls_today if r.calls_day == utcnow().strftime("%Y-%m-%d") else 0)

    def get_source(self, source_id: str) -> dict | None:
        r = self.s.get(M.DataSourceRow, source_id)
        return self._source(r) if r else None

    def ensure_source(self, d: dict):
        """Insert a source definition if it does not exist (idempotent; never overwrites admin choices)."""
        if self.s.get(M.DataSourceRow, d["id"]) is None:
            self.s.add(M.DataSourceRow(id=d["id"], name=d["name"], label=d["label"], reads=d["reads"], is_primary=d.get("primary", False),
                                       enabled=d.get("enabled", False), mode=d.get("mode", "simulated")))
            self.s.flush()

    def record_source_success(self, source_id: str):
        r = self.s.get(M.DataSourceRow, source_id)
        if r:
            r.last_success, r.consecutive_failures, r.last_error = utcnow(), 0, ""
            self.s.flush()

    def record_source_failure(self, source_id: str, message: str):
        r = self.s.get(M.DataSourceRow, source_id)
        if r:
            r.last_error, r.last_error_at, r.consecutive_failures = (message or "")[:300], utcnow(), (r.consecutive_failures or 0) + 1
            self.s.flush()

    def bump_source_calls(self, source_id: str) -> int:
        """Count one outbound call today (UTC day) and return the new total. Used to enforce free-tier budgets."""
        r = self.s.get(M.DataSourceRow, source_id)
        if not r:
            return 0
        day = utcnow().strftime("%Y-%m-%d")
        if r.calls_day != day:
            r.calls_day, r.calls_today = day, 0
        r.calls_today += 1
        self.s.flush()
        return r.calls_today

    def source_calls_today(self, source_id: str) -> int:
        r = self.s.get(M.DataSourceRow, source_id)
        return r.calls_today if r and r.calls_day == utcnow().strftime("%Y-%m-%d") else 0

    # ---------------- external market data cache ----------------
    def save_quote(self, q) -> None:
        self.s.add(M.MarketQuoteRow(**q.model_dump()))
        self.s.flush()

    def latest_quotes(self, symbols: list[str]) -> dict:
        """Latest stored quote per symbol in ONE query."""
        from .data.models import MarketQuote
        newest = select(func.max(M.MarketQuoteRow.id)).where(M.MarketQuoteRow.symbol.in_(symbols)).group_by(M.MarketQuoteRow.symbol)
        out = {}
        for r in self.s.scalars(select(M.MarketQuoteRow).where(M.MarketQuoteRow.id.in_(newest))):
            out[r.symbol] = MarketQuote(**{c.name: getattr(r, c.name) for c in M.MarketQuoteRow.__table__.columns if c.name != "id"})
        return out

    def latest_quote(self, symbol: str):
        from .data.models import MarketQuote
        r = self.s.scalar(select(M.MarketQuoteRow).where(M.MarketQuoteRow.symbol == symbol).order_by(M.MarketQuoteRow.retrieved_at.desc(), M.MarketQuoteRow.id.desc()))
        if not r:
            return None
        d = {c.name: getattr(r, c.name) for c in M.MarketQuoteRow.__table__.columns if c.name != "id"}
        return MarketQuote(**d)

    # ---------------- news cache ----------------
    def upsert_news(self, items) -> list:
        """Insert items not seen before (by link hash). Returns only the NEW items."""
        new = []
        for it in items:
            if self.s.scalar(select(M.NewsItemRow.id).where(M.NewsItemRow.guid_hash == it.guid_hash)) is None:
                self.s.add(M.NewsItemRow(**it.model_dump()))
                new.append(it)
        self.s.flush()
        return new

    def list_news(self, limit: int = 12, since: datetime | None = None):
        from .data.models import NewsItem
        q = select(M.NewsItemRow).order_by(M.NewsItemRow.published_at.desc().nulls_last(), M.NewsItemRow.id.desc()).limit(limit)
        if since is not None:
            q = q.where(M.NewsItemRow.published_at >= since)
        return [NewsItem(**{c.name: getattr(r, c.name) for c in M.NewsItemRow.__table__.columns if c.name != "id"}) for r in self.s.scalars(q)]


    def add_source(self, d: dict):
        self.s.add(M.DataSourceRow(id=d["id"], name=d["name"], label=d["label"], reads=d["reads"], is_primary=d["primary"], enabled=d["enabled"], mode="simulated"))
        self.s.flush()

    def set_source_enabled(self, source_id: str, enabled: bool) -> bool:
        r = self.s.get(M.DataSourceRow, source_id)
        if not r:
            return False
        r.enabled = enabled
        return True

    def source_label(self, source_id: str) -> str:
        r = self.s.get(M.DataSourceRow, source_id)
        return r.label if r else source_id

    # ---------------- client profiles (structured context for the engines) ----------------
    def get_profile(self, client_id: str) -> dict | None:
        r = self.s.get(M.ClientProfileRow, client_id)
        if not r:
            return None
        return dict(client_id=r.client_id, plan5=json.loads(r.plan5_json), weights5=json.loads(r.weights5_json), portfolio_usd=r.portfolio_usd, band_pts=r.band_pts,
                    risk_tolerance=r.risk_tolerance, risk_capacity=r.risk_capacity, goal_name=r.goal_name, goal_years=r.goal_years, goal_earmark=r.goal_earmark,
                    goal_target_usd=r.goal_target_usd, restrictions=json.loads(r.restrictions_json), contact_mode=r.contact_mode, updated_at=r.updated_at)

    def upsert_profile(self, d: dict):
        r = self.s.get(M.ClientProfileRow, d["client_id"]) or M.ClientProfileRow(client_id=d["client_id"])
        r.plan5_json, r.weights5_json = json.dumps(d["plan5"]), json.dumps(d["weights5"])
        r.portfolio_usd, r.band_pts = d["portfolio_usd"], d["band_pts"]
        r.risk_tolerance, r.risk_capacity = d.get("risk_tolerance", ""), d.get("risk_capacity", "")
        r.goal_name, r.goal_years, r.goal_earmark, r.goal_target_usd = d["goal_name"], d["goal_years"], d["goal_earmark"], d["goal_target_usd"]
        r.restrictions_json, r.contact_mode = json.dumps(d.get("restrictions", {})), d.get("contact_mode", "portal")
        r.updated_at = d.get("updated_at") or utcnow()
        self.s.add(r)
        self.s.flush()

    # ---------------- policy settings (compliance-owned thresholds) ----------------
    def get_policy_overrides(self) -> dict:
        return {r.key: json.loads(r.value_json) for r in self.s.scalars(select(M.PolicySettingRow))}

    def set_policy(self, key: str, value, by: str, placeholder: bool = False):
        r = self.s.get(M.PolicySettingRow, key) or M.PolicySettingRow(key=key, value_json="null", updated_at=utcnow())
        r.value_json, r.updated_by, r.placeholder, r.updated_at = json.dumps(value), by, placeholder, utcnow()
        self.s.add(r)
        self.s.flush()

    # ---------------- agent runs, steps, evidence ----------------
    def create_run(self, run_id: str, client_id: str, trigger: str, requested_by: str, input_hash: str, llm_provider: str):
        self.s.add(M.AgentRunRow(id=run_id, client_id=client_id, trigger=trigger, requested_by=requested_by, started_at=utcnow(), status="running",
                                 input_hash=input_hash, llm_provider=llm_provider))
        self.s.flush()

    def finish_run(self, run_id: str, status: str, tier: str = "", paused_reason: str = "", freshness: dict | None = None, error: str = ""):
        r = self.s.get(M.AgentRunRow, run_id)
        r.status, r.tier, r.paused_reason, r.finished_at, r.error = status, tier, paused_reason, utcnow(), error[:400]
        r.data_freshness_json = json.dumps(freshness or {}, default=str)
        self.s.flush()

    def add_step(self, run_id: str, seq: int, name: str, status: str, started, finished, output: dict, error: str = ""):
        self.s.add(M.RunStepRow(run_id=run_id, seq=seq, name=name, status=status, started_at=started, finished_at=finished,
                                output_json=json.dumps(output, default=str)[:20000], error=error[:400]))
        self.s.flush()

    def add_evidence(self, run_id: str, kind: str, ref: str, label: str, payload: dict):
        self.s.add(M.EvidenceRow(run_id=run_id, kind=kind, ref=ref[:200], label=label[:200], payload_json=json.dumps(payload, default=str)[:8000]))
        self.s.flush()

    def get_run(self, run_id: str) -> dict | None:
        r = self.s.get(M.AgentRunRow, run_id)
        if not r:
            return None
        steps = [dict(seq=x.seq, name=x.name, status=x.status, error=x.error, output=json.loads(x.output_json)) for x in
                 self.s.scalars(select(M.RunStepRow).where(M.RunStepRow.run_id == run_id).order_by(M.RunStepRow.seq))]
        ev = [dict(kind=x.kind, ref=x.ref, label=x.label, payload=json.loads(x.payload_json)) for x in
              self.s.scalars(select(M.EvidenceRow).where(M.EvidenceRow.run_id == run_id).order_by(M.EvidenceRow.id))]
        return dict(id=r.id, client_id=r.client_id, trigger=r.trigger, requested_by=r.requested_by, started_at=r.started_at, finished_at=r.finished_at, status=r.status,
                    tier=r.tier, paused_reason=r.paused_reason, llm_provider=r.llm_provider, error=r.error, freshness=json.loads(r.data_freshness_json), steps=steps, evidence=ev)

    def recent_run_by_hash(self, client_id: str, input_hash: str, within_s: int) -> str | None:
        since = utcnow() - timedelta(seconds=within_s)
        return self.s.scalar(select(M.AgentRunRow.id).where(M.AgentRunRow.client_id == client_id, M.AgentRunRow.input_hash == input_hash,
                                                            M.AgentRunRow.started_at >= since, M.AgentRunRow.status.in_(["completed", "paused"])).order_by(M.AgentRunRow.started_at.desc()))

    def list_runs(self, client_id: str, limit: int = 5) -> list[dict]:
        return [dict(id=r.id, status=r.status, tier=r.tier, trigger=r.trigger, started_at=fmt_ts(r.started_at), paused_reason=r.paused_reason)
                for r in self.s.scalars(select(M.AgentRunRow).where(M.AgentRunRow.client_id == client_id).order_by(M.AgentRunRow.started_at.desc()).limit(limit))]

    # ---------------- proposals and approvals ----------------
    def create_proposal(self, pid: str, run_id: str, client_id: str, tier: str, title: str, body: dict, status: str, second_rm_id: str = ""):
        for old in self.s.scalars(select(M.ProposalRow).where(M.ProposalRow.client_id == client_id, M.ProposalRow.status.in_(["awaiting_rm", "awaiting_second", "edited", "digest"]))):
            old.status = "superseded"
        self.s.add(M.ProposalRow(id=pid, run_id=run_id, client_id=client_id, created_at=utcnow(), tier=tier, title=title[:200], body_json=json.dumps(body, default=str),
                                 status=status, second_approver_rm_id=second_rm_id))
        self.s.flush()

    def _prop(self, r) -> dict:
        return dict(id=r.id, run_id=r.run_id, client_id=r.client_id, created_at=fmt_ts(r.created_at), tier=r.tier, title=r.title, body=json.loads(r.body_json), status=r.status,
                    first_approver=r.first_approver, second_approver_rm_id=r.second_approver_rm_id, second_approver=r.second_approver)

    def latest_proposal(self, client_id: str) -> dict | None:
        r = self.s.scalar(select(M.ProposalRow).where(M.ProposalRow.client_id == client_id, M.ProposalRow.status != "superseded").order_by(M.ProposalRow.created_at.desc(), M.ProposalRow.id.desc()))
        return self._prop(r) if r else None

    def latest_proposals(self, client_ids: list[str]) -> dict[str, dict | None]:
        """Latest non-superseded proposal per client, in one query."""
        out: dict[str, dict | None] = {i: None for i in client_ids}
        if not client_ids:
            return out
        q = select(M.ProposalRow).where(M.ProposalRow.client_id.in_(client_ids), M.ProposalRow.status != "superseded").order_by(M.ProposalRow.created_at.desc(), M.ProposalRow.id.desc())
        for r in self.s.scalars(q):
            if out[r.client_id] is None:
                out[r.client_id] = self._prop(r)
        return out

    def get_proposal(self, pid: str) -> dict | None:
        r = self.s.get(M.ProposalRow, pid)
        return self._prop(r) if r else None

    def update_proposal(self, pid: str, **fields):
        r = self.s.get(M.ProposalRow, pid)
        for k, v in fields.items():
            setattr(r, k, v)
        self.s.flush()

    def add_approval(self, pid: str, stage: str, approver: str, rm_id: str, decision: str, reason: str):
        self.s.add(M.ApprovalRow(proposal_id=pid, stage=stage, approver=approver, approver_rm_id=rm_id, decision=decision, reason=reason, decided_at=utcnow()))
        self.s.flush()

    def approvals_for(self, pid: str) -> list[dict]:
        return [dict(stage=a.stage, approver=a.approver, decision=a.decision, reason=a.reason, decided_at=fmt_ts(a.decided_at))
                for a in self.s.scalars(select(M.ApprovalRow).where(M.ApprovalRow.proposal_id == pid).order_by(M.ApprovalRow.id))]

    def second_approver_client_ids(self, rm_id: str) -> list[str]:
        return list(self.s.scalars(select(M.ProposalRow.client_id).where(M.ProposalRow.status == "awaiting_second", M.ProposalRow.second_approver_rm_id == rm_id)))

    def list_clients_by_ids(self, ids: list[str]):
        return self.list_clients(ids=ids)

    # ---------------- scheduler: schedules, jobs, locks ----------------
    def list_schedules(self) -> list[dict]:
        return [dict(owner_email=r.owner_email, cfg=json.loads(r.cfg_json), saved_at=r.saved_at) for r in self.s.scalars(select(M.ScheduleRow).order_by(M.ScheduleRow.owner_email))]

    def schedule_saved_at(self, owner_email: str):
        r = self.s.get(M.ScheduleRow, owner_email)
        return r.saved_at if r else None

    def acquire_lock(self, key: str, holder: str, ttl_s: int) -> bool:
        now = utcnow()
        for old in self.s.scalars(select(M.JobLockRow).where(M.JobLockRow.key == key, M.JobLockRow.expires_at < now)):
            self.s.delete(old)
        self.s.flush()
        try:
            with self.s.begin_nested():
                self.s.add(M.JobLockRow(key=key, holder=holder, acquired_at=now, expires_at=now + timedelta(seconds=ttl_s)))
                self.s.flush()
            return True
        except IntegrityError:
            return False

    def release_lock(self, key: str, holder: str):
        r = self.s.get(M.JobLockRow, key)
        if r and r.holder == holder:
            self.s.delete(r)
            self.s.flush()

    def job_for_slot(self, owner_email: str, slot):
        r = self.s.scalar(select(M.JobRunRow).where(M.JobRunRow.owner_email == owner_email, M.JobRunRow.slot == slot))
        return self._job(r) if r else None

    @staticmethod
    def _job(r) -> dict:
        return dict(id=r.id, owner_email=r.owner_email, owner_name=r.owner_name, trigger=r.trigger, slot=r.slot, started_at=r.started_at, finished_at=r.finished_at,
                    status=r.status, attempts=r.attempts, scopes=json.loads(r.scopes_json), client_scope=r.client_scope, total=r.clients_total, ok=r.clients_ok,
                    paused=r.clients_paused, failed=r.clients_failed, not_run=r.clients_not_run, freshness=json.loads(r.data_freshness_json), message=r.message)

    def create_job(self, job_id: str, owner_email: str, owner_name: str, trigger: str, slot, scopes: list, client_scope: str, attempts: int = 1) -> bool:
        """False if another job already owns (owner, slot): duplicate execution is impossible by constraint."""
        try:
            with self.s.begin_nested():
                self.s.add(M.JobRunRow(id=job_id, owner_email=owner_email, owner_name=owner_name, trigger=trigger, slot=slot, started_at=utcnow(), status="running",
                                       attempts=attempts, scopes_json=json.dumps(scopes), client_scope=client_scope))
                self.s.flush()
            return True
        except IntegrityError:
            return False

    def update_job(self, job_id: str, **f):
        r = self.s.get(M.JobRunRow, job_id)
        for k, v in f.items():
            if k == "freshness":
                r.data_freshness_json = json.dumps(v, default=str)
            else:
                setattr(r, {"total": "clients_total", "ok": "clients_ok", "paused": "clients_paused", "failed": "clients_failed", "not_run": "clients_not_run"}.get(k, k), v)
        self.s.flush()

    def add_job_item(self, job_id: str, client_id: str, client_name: str, status: str, agent_run_id: str = "", tier: str = "", error: str = ""):
        self.s.add(M.JobRunItemRow(job_run_id=job_id, client_id=client_id, client_name=client_name, agent_run_id=agent_run_id, status=status, tier=tier, error=error[:400]))
        self.s.flush()

    def job_items(self, job_id: str) -> list[dict]:
        return [dict(client_id=i.client_id, client_name=i.client_name, status=i.status, tier=i.tier, error=i.error, agent_run_id=i.agent_run_id)
                for i in self.s.scalars(select(M.JobRunItemRow).where(M.JobRunItemRow.job_run_id == job_id).order_by(M.JobRunItemRow.id))]

    def delete_failed_items(self, job_id: str):
        for i in self.s.scalars(select(M.JobRunItemRow).where(M.JobRunItemRow.job_run_id == job_id, M.JobRunItemRow.status.in_(["failed", "not_run"]))):
            self.s.delete(i)
        self.s.flush()

    def list_jobs(self, owner_email: str | None = None, limit: int = 8) -> list[dict]:
        q = select(M.JobRunRow).order_by(M.JobRunRow.started_at.desc(), M.JobRunRow.id.desc()).limit(limit)
        if owner_email:
            q = q.where(M.JobRunRow.owner_email == owner_email)
        return [self._job(r) for r in self.s.scalars(q)]

    # ---------------- price history (performance charts) ----------------
    def save_history(self, symbol: str, bars: list[tuple], provider: str, now: datetime) -> int:
        """Upsert weekly closes [(date, close)]. Returns how many rows were new or changed."""
        have = {r.day: r for r in self.s.scalars(select(M.PriceHistoryRow).where(M.PriceHistoryRow.symbol == symbol))}
        n = 0
        for day, close in bars:
            r = have.get(day)
            if r is None:
                self.s.add(M.PriceHistoryRow(symbol=symbol, day=day, close=float(close), provider=provider, retrieved_at=now)); n += 1
            elif abs(r.close - close) > 1e-9:
                r.close, r.retrieved_at = float(close), now; n += 1
        self.s.flush()
        return n

    def history(self, symbols: list[str]) -> dict[str, list[tuple]]:
        out: dict[str, list[tuple]] = {s: [] for s in symbols}
        q = select(M.PriceHistoryRow.symbol, M.PriceHistoryRow.day, M.PriceHistoryRow.close).where(M.PriceHistoryRow.symbol.in_(symbols)).order_by(M.PriceHistoryRow.day)
        for sym, day, close in self.s.execute(q):
            out[sym].append((day, close))
        return out

    def history_retrieved_at(self, symbol: str):
        return self.s.scalar(select(func.max(M.PriceHistoryRow.retrieved_at)).where(M.PriceHistoryRow.symbol == symbol))

    # ---------------- client <-> RM messages ----------------
    def add_message(self, client_id: str, rm_id: str, sender_role: str, sender_name: str, body: str, kind: str = "text"):
        self.s.add(M.MessageRow(client_id=client_id, rm_id=rm_id, sender_role=sender_role, sender_name=sender_name, body=body, kind=kind, created_at=utcnow()))
        self.s.flush()

    def messages_for(self, client_id: str, limit: int = 80) -> list[dict]:
        rows = list(self.s.scalars(select(M.MessageRow).where(M.MessageRow.client_id == client_id).order_by(M.MessageRow.id.desc()).limit(limit)))
        return [dict(id=m.id, role=m.sender_role, name=m.sender_name, body=m.body, at=m.created_at, read=m.read_at is not None, kind=m.kind or "text") for m in reversed(rows)]

    def recent_message_stats(self, client_ids: list[str]) -> dict[str, dict]:
        """Per client: unread messages FROM the client, and the latest message time. One query."""
        out: dict[str, dict] = {i: dict(unread=0, last=None, last_role="") for i in client_ids}
        if not client_ids:
            return out
        q = select(M.MessageRow.client_id, M.MessageRow.sender_role, M.MessageRow.created_at, M.MessageRow.read_at).where(M.MessageRow.client_id.in_(client_ids)).order_by(M.MessageRow.id)
        for cid, role, at, read in self.s.execute(q):
            o = out[cid]
            o["last"], o["last_role"] = at, role
            if role == "Client" and read is None:
                o["unread"] += 1
        return out

    def mark_messages_read(self, client_id: str, sender_role: str):
        """Mark messages sent BY sender_role as read (the other party opened the conversation)."""
        now = utcnow()
        for m in self.s.scalars(select(M.MessageRow).where(M.MessageRow.client_id == client_id, M.MessageRow.sender_role == sender_role, M.MessageRow.read_at.is_(None))):
            m.read_at = now
        self.s.flush()

    def count_messages_since(self, client_id: str, sender_role: str, since: datetime) -> int:
        return self.s.scalar(select(func.count()).select_from(M.MessageRow).where(M.MessageRow.client_id == client_id, M.MessageRow.sender_role == sender_role, M.MessageRow.created_at >= since)) or 0

    # ---------------- client notifications ----------------
    def add_notification(self, client_id: str, kind: str, title: str, body: str):
        self.s.add(M.NotificationRow(client_id=client_id, kind=kind, title=title[:160], body=body, created_at=utcnow()))
        self.s.flush()

    def notifications_for(self, client_id: str, limit: int = 30) -> list[dict]:
        q = select(M.NotificationRow).where(M.NotificationRow.client_id == client_id).order_by(M.NotificationRow.id.desc()).limit(limit)
        return [dict(id=n.id, kind=n.kind, title=n.title, body=n.body, at=n.created_at, read=n.read_at is not None) for n in self.s.scalars(q)]

    def mark_notifications_read(self, client_id: str):
        now = utcnow()
        for n in self.s.scalars(select(M.NotificationRow).where(M.NotificationRow.client_id == client_id, M.NotificationRow.read_at.is_(None))):
            n.read_at = now
        self.s.flush()

    # ---------------- demo upkeep ----------------
    def set_next_meeting(self, client_id: str, text: str):
        r = self.s.get(M.ClientRow, client_id)
        if r is not None:
            r.next_meeting = text
            self.s.flush()
