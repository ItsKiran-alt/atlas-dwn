"""Alembic environment. The database URL comes from DATABASE_URL (see dwn/config.py), never from this file."""
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dwn import config  # noqa: E402
from dwn.db.models import Base  # noqa: E402

cfg = context.config
target_metadata = Base.metadata


def _url() -> str:
    return cfg.attributes.get("url") or config.database_url()


def run_migrations_offline():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
