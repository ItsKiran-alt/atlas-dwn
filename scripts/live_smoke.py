"""Live smoke test: fetch REAL prices and official news into a throwaway database and print the provenance.

Run:  .venv\\Scripts\\python scripts\\live_smoke.py
Uses the network (Yahoo Finance chart endpoint, Federal Reserve / SEC / BLS RSS). Writes nothing to your real database.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dwn import bootstrap, config, security                       # noqa: E402
from dwn.data.http import Fetcher                                   # noqa: E402
from dwn.data.market import MarketService                           # noqa: E402
from dwn.data.news import NewsService                               # noqa: E402
from dwn.db.session import session_scope                            # noqa: E402
from dwn.repo import Repo                                           # noqa: E402

security._ITER = 1000
tmp = tempfile.mkdtemp()
url = f"sqlite:///{Path(tmp).as_posix()}/smoke.sqlite3"
bootstrap.init(url)
print("User-Agent sent:", config.USER_AGENT)
with session_scope(url) as s:
    repo = Repo(s)
    f = Fetcher()
    m = MarketService(repo, f)
    out = m.refresh(force=True)
    print("\nPRICES  ok:", out["ok"], "failed:", out["failed"])
    for r in m.view():
        if r["available"]:
            ch = f'{r["change_pct"]:+.2f}%' if r["change_pct"] is not None else "n/a"
            print(f'  {r["symbol"]:9} {r["price"]:>10,.3f} {r["currency"]} {ch:>8}  market_time={r["market_time"]} retrieved={r["retrieved_at"]} '
                  f'age={r["age"]:>7} status={r["freshness"]:13} via {r["provider_id"]}')
        else:
            print(f'  {r["symbol"]:9} UNAVAILABLE ({r["message"]})')
    n = NewsService(repo, f)
    nout = n.refresh(force=True)
    print("\nNEWS    new:", nout["new"], "ok feeds:", nout["ok"], "failed:", nout["failed"], "quarantined:", nout["quarantined"], "problems:", nout["problems"][:3])
    for it in n.latest(8):
        print(f'  [{it.publisher[:22]:22}] {it.published_at}  {it.title[:80]}\n      {it.link}')
    print("\nSOURCE HEALTH")
    for src in repo.list_sources():
        if src["mode"] == "live":
            print(f'  {src["id"]:13} enabled={src["enabled"]!s:5} last_success={src["last_success"] or "-":18} failures={src["failures"]} err={src["last_error"][:70]}')
    print("\nHTTP network attempts:", f.calls)
