"""Start-up: apply migrations, then seed SYNTHETIC demo data once (idempotent). Nothing here is real client data."""
from __future__ import annotations

import threading
from datetime import datetime

from . import config, seed
from .data.sources import LIVE_SOURCES
from .db.session import run_migrations, session_scope
from .domain import CONSENT_SHA256, CONSENT_VERSION, RM, Client, User
from .repo import Repo
from .profiles import ensure_profiles
from .security import hash_password

_done: set[str] = set()
_lock = threading.Lock()


def init(url: str | None = None) -> None:
    config.validate_production()
    key = url or config.database_url()
    with _lock:
        if key in _done:
            return
        run_migrations(url)
        with session_scope(url) as s:                      # real external sources are registered in every environment
            r = Repo(s)
            for src in LIVE_SOURCES:
                r.ensure_source(src)
        if config.seed_demo_data():
            with session_scope(url) as s:
                seed_demo(Repo(s))
            with session_scope(url) as s:
                refresh_demo_upkeep(Repo(s))
            with session_scope(url) as s:
                ensure_profiles(Repo(s))
        _done.add(key)


def seed_demo(repo: Repo) -> None:
    if repo.client_count() or repo.list_rms():
        return                                           # already seeded: never overwrite existing data
    pw_hash = hash_password(config.demo_password())     # one demo password, hashed with a random salt
    for rm in seed.RMS:
        repo.add_rm(rm)
        if rm.id == "rm-arjun":
            repo.set_perms(rm.id, True, False, "Tier 2", False)      # senior adviser: eligible second approver for Tier 3 items
        repo.create_user(User(rm.email, rm.name, "RM", rm_id=rm.id, initials=rm.initials), pw_hash)
    repo.create_user(User(seed.ADMIN_EMAIL, "Atlas Administrator", "Admin", initials="AD"), pw_hash)
    for c in seed.ALL_CLIENTS:
        c.next_meeting = seed.meeting_date(c.id)
        repo.add_client(c)
        repo.create_user(User(c.email, c.name, "Client", client_id=c.id, initials="CL"), pw_hash)
        if c.has_consent:
            repo.add_consent(c.id, c.email, CONSENT_VERSION, CONSENT_SHA256, datetime(2026, 1, 5, 9, 0))
    repo.create_user(User("client@atlas-demo.com", "Ramesh Agarwal", "Client", client_id="c-ramesh.agarwal", initials="CL"), pw_hash)
    # recommendations: 12 of Priya's clients, the first 3 awaiting review (matches the prototype's counts)
    priya = [c for c in seed.ALL_CLIENTS if c.rm_id == "rm-priya"]
    from .domain import Rec
    for i, c in enumerate(priya[:12]):
        repo.save_rec(Rec(c.id, c.issue, "Draft" if i < 3 else "Monitor"))
    for c in seed.GOLDEN_CLIENTS:
        repo.save_rec(Rec(c.id, c.issue, "Monitor"))
    for src in seed.DATA_SOURCES:
        repo.add_source(dict(src, enabled=src["default"]))
    seeded = [
        (datetime(2026, 10, 19, 10, 24), "AI recommendation generated", "AI System", "Portfolio drift detected (70% equity vs 60% target)", "Logged", "AI"),
        (datetime(2026, 10, 19, 10, 25), "Policy checks evaluated", "Rules engine", "Illustrative checks passed; adviser review still required", "Review", "Policy"),
        (datetime(2026, 10, 19, 10, 28), "RM opened recommendation", "Priya Sharma", "Recommendation viewed in RM Workbench", "Logged", "RM"),
        (datetime(2026, 10, 19, 10, 30), "Client consent", "Workflow", "Consent not yet captured; execution gate remains locked", "Pending", "Consent"),
    ]
    for ts, action, actor, details, status, kind in seeded:
        repo.log("Rajesh Menon", action, actor, details, status, kind, client_id="c-rajesh.menon", ts=ts)


def refresh_demo_upkeep(repo: Repo) -> None:
    """Idempotent upkeep for demo data that may already exist in a hosted database:
    - every client's 'next meeting' must be in the future (older seeds said 2025);
    - Rajesh Menon and Sneha Patel (clients of Priya Sharma) always have a client login with the same demo password as everyone else."""
    from datetime import date
    today = date.today()
    for c in repo.list_clients(include_all=True):
        try:
            when = datetime.strptime(c.next_meeting, "%d %b %Y").date()
        except (ValueError, TypeError):
            when = None
        if when is None or when < today:
            repo.set_next_meeting(c.id, seed.meeting_date(c.id, today))
    pw_hash = None
    for name in ("Rajesh Menon", "Sneha Patel"):
        email = seed.slug(name) + "@atlas-demo.com"
        if repo.user_exists(email):
            continue
        client = next(iter(repo.list_clients(client_id="c-" + seed.slug(name))), None)
        if client is None:
            continue
        pw_hash = pw_hash or hash_password(config.demo_password())
        repo.create_user(User(email, client.name, "Client", client_id=client.id, initials="CL"), pw_hash)
