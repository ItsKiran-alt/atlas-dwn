"""Count SQL round trips per page build. Each one costs a network hop on a hosted database, so fewer is faster.

    .venv\\Scripts\\python scripts\\measure_queries.py
"""
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "golden"))

from sqlalchemy import event    # noqa: E402

from dwn import bootstrap, security    # noqa: E402
from dwn.db.session import get_engine, session_scope    # noqa: E402
from dwn.repo import Repo    # noqa: E402
from dwn.ui import controller    # noqa: E402

security._ITER = 1000
url = f"sqlite:///{Path(tempfile.mkdtemp()).as_posix()}/m.sqlite3"
bootstrap.init(url)
eng = get_engine(url)
count = [0]


@event.listens_for(eng, "before_cursor_execute")
def _c(*a, **k):
    count[0] += 1


def measure(label, who, role, steps=()):
    sess = controller.new_session()
    with session_scope(url) as s:
        r = Repo(s)
        controller.handle(r, sess, dict(id="l", action="login", payload=dict(email=who, password="atlas-demo", role=role)))
    for act, p in steps:
        with session_scope(url) as s:
            controller.handle(Repo(s), sess, dict(id=act, action=act, payload=p))
    count[0] = 0
    t = time.perf_counter()
    with session_scope(url) as s:
        controller.build(Repo(s), sess)
    print(f"{label:34} {count[0]:4d} queries  {1000 * (time.perf_counter() - t):6.0f} ms (local SQLite)")


measure("RM Priya, workbench", "priya.sharma@atlas-demo.com", "RM")
measure("RM Arjun (13 clients), workbench", "arjun.mehta@atlas-demo.com", "RM")
measure("Admin, settings+compliance", "admin@atlas-demo.com", "Admin")
measure("Client Ramesh, portal", "ramesh.agarwal@atlas-demo.com", "Client")
