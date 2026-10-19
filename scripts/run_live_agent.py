"""Run the agent on seeded clients using REAL prices and REAL official news fetched right now (throwaway database).

    .venv\\Scripts\\python scripts\\run_live_agent.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dwn import auth, bootstrap, security                      # noqa: E402
from dwn.agents.llm import make_llm                             # noqa: E402
from dwn.agents.orchestrator import run_monitoring              # noqa: E402
from dwn.data.http import Fetcher                               # noqa: E402
from dwn.data.market import MarketService                       # noqa: E402
from dwn.data.news import NewsService                           # noqa: E402
from dwn.db.session import session_scope                        # noqa: E402
from dwn.repo import Repo                                       # noqa: E402

security._ITER = 1000
url = f"sqlite:///{Path(tempfile.mkdtemp()).as_posix()}/live.sqlite3"
bootstrap.init(url)
with session_scope(url) as s:
    repo = Repo(s)
    f = Fetcher()
    m = MarketService(repo, f).refresh(force=True)
    n = NewsService(repo, f).refresh(force=True)
    repo.s.commit()
    print("fetched prices:", m["ok"], "failed:", m["failed"], "| headlines new:", n["new"], "failed feeds:", n["failed"])
    for q in MarketService(repo).view(["^GSPC", "SPY", "AGG", "VNQ"]):
        print(f"  {q['symbol']:6} {q['price']:>9,.2f} {q['change_pct']:+.2f}%  as of {q['market_time']} UTC  [{q['freshness']}]  via {q['provider_id']}")
    priya, _ = auth.authenticate(repo, "priya.sharma@atlas-demo.com", "atlas-demo", "RM")
    arjun, _ = auth.authenticate(repo, "arjun.mehta@atlas-demo.com", "atlas-demo", "RM")
    llm = make_llm()
    print(f"\nLLM provider: {llm.name}\n")
    for who, cids in ((priya, ["c-rajesh.menon", "c-ananya.singh", "c-neha.prakash"]), (arjun, ["c-k02", "c-k07", "c-ramesh.agarwal"])):
        for cid in cids:
            r = run_monitoring(repo, who, cid, llm=llm)
            print(f"{cid:18} status={r.status:9} tier={r.tier or '-':6} {('paused: ' + r.paused_reason) if r.paused_reason else ''}")
            if r.proposal:
                p = r.proposal
                print("   title:", p.title)
                print("   note :", p.summary[:230])
                print("   trades:", [f"{t.direction} {t.asset_class} {t.points:g}pts" for t in p.trades][:4], "| news items:", len(p.news_context), "| checks:", [c.status for c in p.checks])
                for nws in p.news_context[:2]:
                    print("   news :", nws["publisher"], "-", nws["title"][:80], nws["link"])
            run = repo.get_run(r.run_id)
            print("   steps:", [(x["name"], x["status"]) for x in run["steps"]], "| evidence rows:", len(run["evidence"]))
