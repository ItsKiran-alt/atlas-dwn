"""Engine, per-event session (transaction boundary) and migration runner."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .. import config

_lock = threading.Lock()
_engines: dict[str, Engine] = {}


def get_engine(url: str | None = None) -> Engine:
    url = url or config.database_url()
    with _lock:
        if url not in _engines:
            kw = {}
            if url.startswith("sqlite"):
                kw["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if url.startswith("postgresql"):
                # small pool (hosted free tiers allow few connections); no server-side prepared statements so poolers in transaction mode also work
                kw["pool_size"], kw["max_overflow"], kw["pool_recycle"] = 3, 2, 1800
                kw["connect_args"] = {"prepare_threshold": None}
            eng = create_engine(url, pool_pre_ping=True, **kw)
            if url.startswith("sqlite"):
                @event.listens_for(eng, "connect")
                def _pragmas(dbapi, _):          # noqa: ANN001
                    cur = dbapi.cursor()
                    cur.execute("PRAGMA foreign_keys=ON")
                    cur.execute("PRAGMA journal_mode=WAL")
                    cur.close()
            _engines[url] = eng
        return _engines[url]


def run_migrations(url: str | None = None) -> None:
    """Apply Alembic migrations up to head. Safe to call on every start."""
    from alembic import command
    from alembic.config import Config
    root = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.attributes["url"] = url or config.database_url()
    command.upgrade(cfg, "head")


@contextmanager
def session_scope(url: str | None = None):
    """One transaction per UI event: commit on success, roll back on any exception."""
    s: Session = sessionmaker(bind=get_engine(url), expire_on_commit=False)()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
