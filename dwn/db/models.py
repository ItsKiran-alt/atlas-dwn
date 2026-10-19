"""SQLAlchemy models. Schema changes go through Alembic migrations (alembic/versions)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RMRow(Base):
    __tablename__ = "rms"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    initials: Mapped[str] = mapped_column(String(4))


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(10))                      # Admin | RM | Client
    rm_id: Mapped[str] = mapped_column(String(40), default="")
    client_id: Mapped[str] = mapped_column(String(60), default="")
    initials: Mapped[str] = mapped_column(String(4), default="")
    password_hash: Mapped[str] = mapped_column(String(300))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ClientRow(Base):
    __tablename__ = "clients"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    rm_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    aum_musd: Mapped[float] = mapped_column(Float, default=0.0)
    issue: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(12), default="review")
    status_label: Mapped[str] = mapped_column(String(20), default="Review")
    status_class: Mapped[str] = mapped_column(String(10), default="")
    since: Mapped[int] = mapped_column(Integer, default=2026)
    tier: Mapped[str] = mapped_column(String(10), default="Tier 1")
    email: Mapped[str] = mapped_column(String(200), default="", index=True)
    risk_profile: Mapped[str] = mapped_column(String(40), default="Moderate")
    last_reviewed: Mapped[str] = mapped_column(String(20), default="12 Jan 2025")
    next_meeting: Mapped[str] = mapped_column(String(20), default="28 Apr 2025")
    plan_json: Mapped[str] = mapped_column(Text, default="{}")
    weights_json: Mapped[str] = mapped_column(Text, default="{}")
    contact_pref: Mapped[str] = mapped_column(String(120), default="Secure client portal")
    source: Mapped[str] = mapped_column(String(10), default="html")     # html | golden | portal
    golden_key: Mapped[str] = mapped_column(String(10), default="")
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)


class GoalRow(Base):
    __tablename__ = "goals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    detail: Mapped[str] = mapped_column(String(200))
    progress: Mapped[int] = mapped_column(Integer)
    short: Mapped[str] = mapped_column(String(40), default="")


class HoldingRow(Base):
    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    asset: Mapped[str] = mapped_column(String(120))
    asset_class: Mapped[str] = mapped_column(String(40))
    value_musd: Mapped[float] = mapped_column(Float)


class TransactionRow(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    date: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    investment: Mapped[str] = mapped_column(String(120))
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))


class ConsentRow(Base):
    """Versioned, timestamped consent linked to the client identity. Withdrawal sets withdrawn_at; rows are never deleted."""
    __tablename__ = "consents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    email: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(40))
    text_sha256: Mapped[str] = mapped_column(String(64))
    accepted_at: Mapped[datetime] = mapped_column(DateTime)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditRow(Base):
    """Append-only (database triggers reject UPDATE and DELETE; see migration 0001)."""
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    client_id: Mapped[str] = mapped_column(String(60), default="", index=True)
    client_name: Mapped[str] = mapped_column(String(120), default="")
    action: Mapped[str] = mapped_column(String(120))
    actor: Mapped[str] = mapped_column(String(120))
    details: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(12))


class RecRow(Base):
    __tablename__ = "recommendations"
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="Draft")
    rationale: Mapped[str] = mapped_column(Text, default="")
    tier: Mapped[str] = mapped_column(String(40), default="Tier 1 — RM approval")
    decided_by: Mapped[str] = mapped_column(String(120), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    consent_request: Mapped[str] = mapped_column(String(40), default="Not requested")
    client_message: Mapped[str] = mapped_column(String(40), default="Not shared")


class NoteRow(Base):
    __tablename__ = "adviser_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(120))
    ts: Mapped[datetime] = mapped_column(DateTime)


class DraftRow(Base):
    __tablename__ = "client_message_drafts"
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), primary_key=True)
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="Not shared")


class ScheduleRow(Base):
    __tablename__ = "schedules"
    owner_email: Mapped[str] = mapped_column(String(200), primary_key=True)
    cfg_json: Mapped[str] = mapped_column(Text)
    saved_at: Mapped[datetime] = mapped_column(DateTime)


class ScheduleRunRow(Base):
    __tablename__ = "schedule_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, index=True)
    by: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    scopes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40))


class RMPermissionRow(Base):
    __tablename__ = "rm_permissions"
    rm_id: Mapped[str] = mapped_column(ForeignKey("rms.id"), primary_key=True)
    schedule: Mapped[bool] = mapped_column(Boolean, default=True)
    all_clients: Mapped[bool] = mapped_column(Boolean, default=False)
    approval: Mapped[str] = mapped_column(String(10), default="Tier 1")
    override: Mapped[bool] = mapped_column(Boolean, default=False)


class DataSourceRow(Base):
    __tablename__ = "data_sources"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(160))
    reads: Mapped[str] = mapped_column(String(300))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mode: Mapped[str] = mapped_column(String(12), default="simulated")   # simulated | live (live only after a tested connection)
    last_success: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(String(300), default="")
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    calls_today: Mapped[int] = mapped_column(Integer, default=0)
    calls_day: Mapped[str] = mapped_column(String(10), default="")


Index("ix_audit_client_ts", AuditRow.client_id, AuditRow.ts)


class MarketQuoteRow(Base):
    """Cache of external prices, kept separate from client/portfolio records. Never contains fabricated values."""
    __tablename__ = "market_quotes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(10))
    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8))
    prev_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_abs: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_time: Mapped[datetime] = mapped_column(DateTime)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    provider: Mapped[str] = mapped_column(String(30))
    provider_name: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str] = mapped_column(String(300))
    session_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    session_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    day_only_timestamp: Mapped[bool] = mapped_column(Boolean, default=False)
    transformation: Mapped[str] = mapped_column(String(300), default="")


Index("ix_quotes_symbol_retrieved", MarketQuoteRow.symbol, MarketQuoteRow.retrieved_at)


class NewsItemRow(Base):
    __tablename__ = "news_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guid_hash: Mapped[str] = mapped_column(String(64), unique=True)
    source_id: Mapped[str] = mapped_column(String(30), index=True)
    publisher: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(300))
    link: Mapped[str] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime)
    summary: Mapped[str] = mapped_column(String(600), default="")
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    quarantine_reason: Mapped[str] = mapped_column(String(200), default="")


class ClientProfileRow(Base):
    """Structured Client Context Model inputs the engines need (concept doc s5). Missing row = incomplete client information."""
    __tablename__ = "client_profiles"
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), primary_key=True)
    plan5_json: Mapped[str] = mapped_column(Text)            # target weights, percent: EQ FI CA AL SS
    weights5_json: Mapped[str] = mapped_column(Text)         # current weights, percent
    portfolio_usd: Mapped[float] = mapped_column(Float)
    band_pts: Mapped[float] = mapped_column(Float)
    risk_tolerance: Mapped[str] = mapped_column(String(40), default="")
    risk_capacity: Mapped[str] = mapped_column(String(40), default="")
    goal_name: Mapped[str] = mapped_column(String(120), default="")
    goal_years: Mapped[float] = mapped_column(Float, default=0.0)
    goal_earmark: Mapped[float] = mapped_column(Float, default=1.0)
    goal_target_usd: Mapped[float] = mapped_column(Float, default=0.0)
    restrictions_json: Mapped[str] = mapped_column(Text, default="{}")
    contact_mode: Mapped[str] = mapped_column(String(20), default="portal")   # phone_first|phone_only|in_person|email|app|portal
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class PolicySettingRow(Base):
    """Thresholds are settings owned by compliance, not code (concept doc s9). Values here are PLACEHOLDERS until AWM sets them."""
    __tablename__ = "policy_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
    placeholder: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(String(120), default="seed")
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(30))                  # manual | schedule | golden_test
    requested_by: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20))                   # running | completed | paused | failed
    tier: Mapped[str] = mapped_column(String(10), default="")         # 1 | 2 | 3 | Paused
    paused_reason: Mapped[str] = mapped_column(String(60), default="")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    data_freshness_json: Mapped[str] = mapped_column(Text, default="{}")
    llm_provider: Mapped[str] = mapped_column(String(30), default="")
    error: Mapped[str] = mapped_column(String(400), default="")


class RunStepRow(Base):
    __tablename__ = "run_steps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(12))                   # ok | skipped | failed
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime] = mapped_column(DateTime)
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(String(400), default="")


class EvidenceRow(Base):
    """Every number and claim in a proposal points to one of these rows."""
    __tablename__ = "evidence_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))                     # engine | client_record | market | news | policy | control
    ref: Mapped[str] = mapped_column(String(200))                     # e.g. engine name, symbol, URL
    label: Mapped[str] = mapped_column(String(200))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class ProposalRow(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    tier: Mapped[str] = mapped_column(String(10))                     # 1 | 2 | 3
    title: Mapped[str] = mapped_column(String(200))
    body_json: Mapped[str] = mapped_column(Text)                      # full typed proposal (rationale, trades, alternatives, assumptions, drafts, checks)
    status: Mapped[str] = mapped_column(String(24), default="awaiting_rm")   # awaiting_rm | awaiting_second | approved | rejected | edited | digest | superseded
    first_approver: Mapped[str] = mapped_column(String(120), default="")
    second_approver_rm_id: Mapped[str] = mapped_column(String(40), default="")
    second_approver: Mapped[str] = mapped_column(String(120), default="")


class ApprovalRow(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"), index=True)
    stage: Mapped[str] = mapped_column(String(10))                    # first | second
    approver: Mapped[str] = mapped_column(String(120))
    approver_rm_id: Mapped[str] = mapped_column(String(40), default="")
    decision: Mapped[str] = mapped_column(String(10))                 # approve | edit | reject
    reason: Mapped[str] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime)


class JobRunRow(Base):
    """One execution of a saved schedule (scheduled or manual). Written truthfully: a failure is a failure."""
    __tablename__ = "job_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_email: Mapped[str] = mapped_column(String(200), index=True)
    owner_name: Mapped[str] = mapped_column(String(120), default="")
    trigger: Mapped[str] = mapped_column(String(12))                    # scheduled | manual
    slot: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # the scheduled time this run answers (UTC)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16))                     # running | completed | partial | failed | skipped | missed
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    client_scope: Mapped[str] = mapped_column(String(40), default="")
    clients_total: Mapped[int] = mapped_column(Integer, default=0)
    clients_ok: Mapped[int] = mapped_column(Integer, default=0)
    clients_paused: Mapped[int] = mapped_column(Integer, default=0)
    clients_failed: Mapped[int] = mapped_column(Integer, default=0)
    clients_not_run: Mapped[int] = mapped_column(Integer, default=0)
    data_freshness_json: Mapped[str] = mapped_column(Text, default="{}")
    message: Mapped[str] = mapped_column(String(400), default="")
    __table_args__ = (UniqueConstraint("owner_email", "slot", name="uq_job_owner_slot"),)


class JobRunItemRow(Base):
    __tablename__ = "job_run_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_run_id: Mapped[str] = mapped_column(ForeignKey("job_runs.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(60))
    client_name: Mapped[str] = mapped_column(String(120), default="")
    agent_run_id: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(12))                     # ok | paused | failed | not_run | duplicate
    tier: Mapped[str] = mapped_column(String(10), default="")
    error: Mapped[str] = mapped_column(String(400), default="")


class JobLockRow(Base):
    """Mutual exclusion so two workers never process the same schedule at once. Expires so a crashed worker cannot block forever."""
    __tablename__ = "job_locks"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    holder: Mapped[str] = mapped_column(String(80))
    acquired_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
