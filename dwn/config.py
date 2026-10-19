"""Configuration from environment variables (never from code). Dev, test and production are separate via DWN_ENV."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ENV = os.environ.get("DWN_ENV", "dev").lower()                 # dev | test | prod
IS_PROD = ENV == "prod"


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        if IS_PROD:
            raise RuntimeError("DATABASE_URL must be set when DWN_ENV=prod (a hosted Postgres, e.g. Supabase).")
        data = ROOT / "data"
        data.mkdir(exist_ok=True)
        return f"sqlite:///{(data / 'dwn.sqlite3').as_posix()}"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def seed_demo_data() -> bool:
    """Synthetic demo users and clients are seeded unless explicitly disabled. Never default-on in prod."""
    default = "0" if IS_PROD else "1"
    return os.environ.get("DWN_SEED_DEMO", default) == "1"


def demo_password() -> str:
    pw = os.environ.get("DWN_DEMO_PASSWORD", "")
    if IS_PROD and not pw:
        raise RuntimeError("Set DWN_DEMO_PASSWORD if you really want demo accounts in production.")
    return pw or "atlas-demo"


SESSION_IDLE_MINUTES = int(os.environ.get("DWN_SESSION_IDLE_MINUTES", "30"))
MAX_FAILED_LOGINS = int(os.environ.get("DWN_MAX_FAILED_LOGINS", "5"))
LOCKOUT_MINUTES = int(os.environ.get("DWN_LOCKOUT_MINUTES", "15"))
MIN_PASSWORD_LEN = 10


# ---- external data (Phase 4) ----
CONTACT = os.environ.get("DWN_CONTACT", "")                     # optional contact string added to the User-Agent (SEC asks for one)
USER_AGENT = "AtlasDWN-prototype/0.1 (research prototype" + (f"; {CONTACT}" if CONTACT else "") + ")"
HTTP_TIMEOUT_S = float(os.environ.get("DWN_HTTP_TIMEOUT_S", "8"))
HTTP_RETRIES = int(os.environ.get("DWN_HTTP_RETRIES", "2"))      # retries AFTER the first attempt, per provider
HTTP_MAX_BYTES = 2_000_000
MARKET_MAX_AGE_MIN = int(os.environ.get("DWN_MARKET_MAX_AGE_MIN", "20"))   # golden-set placeholder (compliance owns the real value)
MARKET_CACHE_TTL_S = int(os.environ.get("DWN_MARKET_CACHE_TTL_S", "60"))
NEWS_CACHE_TTL_S = int(os.environ.get("DWN_NEWS_CACHE_TTL_S", "900"))
MANUAL_REFRESH_MIN_GAP_S = int(os.environ.get("DWN_REFRESH_MIN_GAP_S", "30"))
ALPHAVANTAGE_API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "")
ALPHAVANTAGE_DAILY_BUDGET = int(os.environ.get("ALPHAVANTAGE_DAILY_BUDGET", "20"))   # free tier is 25/day; keep headroom


# ---- LLM (Phase 5): provider chosen by DWN_LLM_PROVIDER = template | groq | gemini (default: template, no AI) ----
LLM_DAILY_BUDGET = int(os.environ.get("DWN_LLM_DAILY_BUDGET", "100"))        # calls per provider per UTC day, shared by all runs


# ---- scheduler (Phase 6) ----
JOB_MAX_CLIENTS = int(os.environ.get("DWN_JOB_MAX_CLIENTS", "50"))              # cost control: clients per job
JOB_TIME_BUDGET_S = int(os.environ.get("DWN_JOB_TIME_BUDGET_S", "240"))         # remaining clients are recorded as not_run
JOB_GRACE_HOURS = int(os.environ.get("DWN_JOB_GRACE_HOURS", "6"))               # a missed slot older than this is recorded as missed, not run late
JOB_MAX_ATTEMPTS = int(os.environ.get("DWN_JOB_MAX_ATTEMPTS", "3"))


def async_jobs() -> bool:
    """Run Now / agent runs execute in a background thread so the page never freezes (default on). Tests set DWN_ASYNC_JOBS=0 to run inline."""
    return os.environ.get("DWN_ASYNC_JOBS", "1") != "0"


def validate_production() -> None:
    """Refuse to start in production with unsafe settings (called from bootstrap.init)."""
    if not IS_PROD:
        return
    url = database_url()                                   # raises if DATABASE_URL is missing
    if url.startswith("sqlite"):
        raise RuntimeError("DWN_ENV=prod requires a hosted database (Postgres), not SQLite.")
    if seed_demo_data() and os.environ.get("DWN_DEMO_PASSWORD", "") in ("", "atlas-demo"):
        raise RuntimeError("Demo accounts are enabled in production with the default password. Disable DWN_SEED_DEMO or set a strong DWN_DEMO_PASSWORD.")
