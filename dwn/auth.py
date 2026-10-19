"""Authentication against the users table (salted PBKDF2 hashes) with lockout and audit.

Provider-independent on purpose: a hosted identity provider (e.g. Supabase Auth) can replace `authenticate`
without touching the rest of the app. Not connected yet: see docs/03_phase3_backend.md.
"""
from __future__ import annotations

from . import config
from .domain import User, utcnow
from .repo import Repo
from .security import hash_password, verify_password

_DUMMY = hash_password("not-a-real-password")      # makes unknown-email timing look like a wrong password


def authenticate(repo: Repo, email: str, password: str, role: str) -> tuple[User | None, str]:
    """Return (user, error). Failures are counted, locked after repeated failure, and audited. Never logs the password."""
    email = (email or "").strip().lower()
    stored = repo.password_hash(email)
    locked = repo.lock_state(email) if stored else None
    if locked:
        mins = max(1, int((locked - utcnow()).total_seconds() // 60) + 1)
        repo.log("—", "Sign-in blocked", email, f"Account locked after repeated failures ({mins} min left)", "Rejected", "System")
        return None, f"Too many failed attempts. Try again in about {mins} minutes."
    ok = verify_password(password or "", stored or _DUMMY) and stored is not None
    if not ok:
        now_locked = repo.record_login_failure(email)
        repo.log("—", "Sign-in failed", email or "unknown", "Incorrect email or password" + ("; account locked" if now_locked else ""), "Rejected", "System")
        return None, "Incorrect email or password."
    user = repo.get_user(email)
    if user.role != role:
        repo.log("—", "Sign-in refused", email, f"Account is {user.role}, not {role}", "Rejected", "System")
        return None, f"This account is not a {role} account. Choose the correct role card."
    repo.record_login_success(email)
    return user, ""
