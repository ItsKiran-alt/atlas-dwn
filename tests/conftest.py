"""Test fixtures. By default tests run on SQLite. Set DWN_TEST_PG_ADMIN_URL to run the SAME suite on PostgreSQL, e.g.

    set DWN_TEST_PG_ADMIN_URL=postgresql+psycopg://postgres@127.0.0.1:55432/postgres

(a superuser connection to the maintenance database; the fixtures create and drop throwaway databases from a migrated, seeded template).
"""
import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "golden"))

from sqlalchemy import create_engine, text      # noqa: E402
from sqlalchemy.engine import make_url           # noqa: E402

from dwn import bootstrap, security              # noqa: E402
from dwn.db import session as dbsession          # noqa: E402
from dwn.repo import Repo                        # noqa: E402

PG_ADMIN = os.environ.get("DWN_TEST_PG_ADMIN_URL", "")
IS_PG = bool(PG_ADMIN)
sqlite_only = pytest.mark.skipif(IS_PG, reason="uses SQLite files directly")


def _pg_url(dbname: str) -> str:
    return make_url(PG_ADMIN).set(database=dbname).render_as_string(hide_password=False)


def _pg_admin(sql: str):
    eng = create_engine(PG_ADMIN, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text(sql))
    eng.dispose()


@pytest.fixture(scope="session")
def template_db(tmp_path_factory):
    """One migrated + seeded database, built once (fast hashing), cloned for every test."""
    security._ITER = 1000
    if IS_PG:
        name = "dwn_tpl_" + uuid.uuid4().hex[:8]
        _pg_admin(f'CREATE DATABASE "{name}"')
        url = _pg_url(name)
        bootstrap.init(url)
        dbsession.get_engine(url).dispose()
        dbsession._engines.pop(url, None)
        yield name
        _pg_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        return
    path = tmp_path_factory.mktemp("tpl") / "template.sqlite3"
    url = f"sqlite:///{path.as_posix()}"
    bootstrap.init(url)
    dbsession.get_engine(url).dispose()
    dbsession._engines.pop(url, None)
    yield path


@pytest.fixture()
def db_url(template_db, tmp_path):
    if IS_PG:
        name = "dwn_t_" + uuid.uuid4().hex[:10]
        _pg_admin(f'CREATE DATABASE "{name}" TEMPLATE "{template_db}"')
        url = _pg_url(name)
        yield url
        eng = dbsession._engines.pop(url, None)
        if eng:
            eng.dispose()
        _pg_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        return
    p = tmp_path / "test.sqlite3"
    shutil.copy(template_db, p)
    url = f"sqlite:///{p.as_posix()}"
    yield url
    eng = dbsession._engines.pop(url, None)
    if eng:
        eng.dispose()


@pytest.fixture()
def repo(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)         # so config.database_url() points at this database
    with dbsession.session_scope(db_url) as s:
        yield Repo(s)
