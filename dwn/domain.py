"""Plain domain objects used by services and rendering (independent of the database)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

CONSENT_VERSION = "2026-10-v1"
CONSENT_TEXT = (
    "I consent to AI-assisted continuous portfolio monitoring, analysis and recommendation drafting, with Relationship Manager "
    "review and approval required for proposed adjustments. The AI will not independently execute trades. I can withdraw consent at any time."
)
CONSENT_SHA256 = hashlib.sha256((CONSENT_VERSION + "|" + CONSENT_TEXT).encode()).hexdigest()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def fmt_ts(dt: datetime | None) -> str:
    return dt.strftime("%d %b %Y, %H:%M") if dt else ""


@dataclass
class Goal:
    name: str
    detail: str
    progress: int          # illustrative until the goal engine exists
    short: str = ""


@dataclass
class Client:
    id: str
    name: str
    rm_id: str
    aum_musd: float
    issue: str
    kind: str                       # review | approval
    status_label: str
    status_class: str               # "" | high | info
    since: int
    tier: str = "Tier 1"
    email: str = ""
    risk_profile: str = "Moderate"
    last_reviewed: str = "12 Jan 2025"
    next_meeting: str = "28 Apr 2025"
    plan: dict = field(default_factory=dict)
    weights: dict = field(default_factory=dict)
    goals: list = field(default_factory=list)
    holdings: list = field(default_factory=list)        # (asset, asset_class, value_musd)
    transactions: list = field(default_factory=list)    # (date, type, investment, amount_usd, status)
    contact_pref: str = "Secure client portal"
    has_consent: bool = True                            # seed hint only; the consents table is authoritative
    source: str = "html"                                # html | golden | portal
    golden_key: str = ""


@dataclass
class RM:
    id: str
    name: str
    email: str
    initials: str


@dataclass
class User:
    email: str
    name: str
    role: str                 # Admin | RM | Client
    rm_id: str = ""
    client_id: str = ""
    initials: str = ""


@dataclass
class AuditEvent:
    ts: str
    client: str
    action: str
    actor: str
    details: str
    status: str               # Logged | Review | Pending | Rejected | Awaiting client
    kind: str                 # AI | RM | Consent | Policy | System


@dataclass
class Rec:
    client_id: str
    title: str
    status: str = "Draft"     # Draft | RM reviewed | Edited | Rejected | Monitor
    rationale: str = ""
    tier: str = "Tier 1 — RM approval"
    decided_by: str = ""
    decided_at: str = ""
    note: str = ""
    consent_request: str = "Not requested"
    client_message: str = "Not shared"
