"""Group the SQL statements of one page build so the N+1 patterns are obvious."""
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "golden"))
from sqlalchemy import event    # noqa: E402

from dwn import bootstrap, security    # noqa: E402
from dwn.db.session import get_engine, session_scope    # noqa: E402
from dwn.repo import Repo    # noqa: E402
from dwn.ui import controller    # noqa: E402

who, role = (sys.argv[1], sys.argv[2]) if len(sys.argv) > 2 else ("priya.sharma@atlas-demo.com", "RM")
security._ITER = 1000
url = f"sqlite:///{Path(tempfile.mkdtemp()).as_posix()}/b.sqlite3"
bootstrap.init(url)
eng = get_engine(url)
stm = []
sess = controller.new_session()
with session_scope(url) as s:
    controller.handle(Repo(s), sess, dict(id="l", action="login", payload=dict(email=who, password="atlas-demo", role=role)))


@event.listens_for(eng, "before_cursor_execute")
def _c(conn, cur, statement, *a, **k):
    stm.append(re.sub(r"\s+", " ", statement)[:110])


with session_scope(url) as s:
    controller.build(Repo(s), sess)
for k, v in Counter(stm).most_common(14):
    print(f"{v:3d} x {k}")
print("total", len(stm))
