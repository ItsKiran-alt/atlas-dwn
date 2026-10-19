"""Run the WHOLE agent (orchestrator, engines, controls, skills, persistence, audit) on every golden scenario and report pass/fail.

    .venv\\Scripts\\python scripts\\run_golden_agent.py [--llm template|groq|gemini] [--json out.json]

Uses a throwaway database. The default 'template' provider needs no key and no network (deterministic rules instead of a model).
With --llm groq/gemini the same checks run against a real model; that needs your API key in an environment variable.
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "golden"))

from dwn import auth, bootstrap, security                                    # noqa: E402
from dwn.agents.llm import make_llm                                          # noqa: E402
from dwn.agents.orchestrator import run_monitoring                           # noqa: E402
from dwn.controls.wording import prohibited_language, untraceable_figures    # noqa: E402
from dwn.db.session import session_scope                                     # noqa: E402
from dwn.engines.types import EventInput                                     # noqa: E402
from dwn.repo import Repo                                                    # noqa: E402
from loader import GOLDEN, event_for                                         # noqa: E402


def agent_event(s: dict) -> EventInput:
    """What the agent receives in production: market facts and the RAW note text. Structured signals come from the extractor."""
    ev = event_for(s["event_input"])
    raw = s["event_input"]
    if raw.get("note_text"):
        return EventInput(note_text=raw["note_text"], shocks=ev.shocks, feed_age_min=ev.feed_age_min, data_issue=ev.data_issue)
    return ev


def check(s: dict, r, repo: Repo, client_id: str) -> list[str]:
    problems = []
    e = s["expected"]
    a = r.analysis
    exp_tier = str(e["tier"])
    if r.tier != exp_tier:
        problems.append(f"tier {r.tier} != {exp_tier}")
    got_flags = sorted(a.flags) if a else []
    if got_flags != sorted(e["flags"]):
        problems.append(f"flags {got_flags} != {sorted(e['flags'])}")
    if a and a.message != e["client_message"]:
        problems.append(f"message {a.message} != {e['client_message']}")
    if a and e["goal_status_after"] and a.goal_after and a.goal_after.status != e["goal_status_after"]:
        problems.append(f"goal {a.goal_after.status} != {e['goal_status_after']}")
    mnt = s["must_not_trade_classes"]
    if mnt not in ("-", "all classes") and a and mnt not in a.must_not_trade:
        problems.append(f"{mnt} not protected")
    if r.status == "failed":
        problems.append("run failed: " + "; ".join(r.notes))
    if exp_tier == "Paused":
        if r.proposal is not None:
            problems.append("a proposal was created for a paused item")
        if not any(x.action in ("Monitoring paused",) for x in repo.list_audit(limit=30, client_ids=[client_id])):
            problems.append("no pause audit event")
    else:
        p = r.proposal
        if p is None:
            problems.append("no proposal")
        else:
            text = p.summary + " " + (p.client_message or "") + " " + " ".join(p.talking_points)
            if prohibited_language(text):
                problems.append("prohibited language in draft")
            if p.draft_provider == "":
                problems.append("draft was blocked")
            if exp_tier == "3" and not any("second approver" in u.lower() for u in p.unresolved):
                problems.append("tier 3 without second-approver requirement")
            if e["client_message"] == "none" and p.client_message:
                problems.append("client message drafted though none expected")
            if e["client_message"] in ("held", "drafted") and not p.client_message:
                problems.append("expected client message draft missing")
            if any(c.status == "fail" for c in p.checks):
                problems.append("a control failed: " + ", ".join(c.name for c in p.checks if c.status == "fail"))
            if not p.evidence_refs and not repo.get_run(r.run_id)["evidence"]:
                problems.append("no evidence recorded")
    # note extraction against the authored expectation (fields the note actually states)
    exp = s.get("expected_extraction")
    if exp and s["event_input"].get("note_text") and r.extraction is not None:
        x = r.extraction
        if x.certainty != exp["certainty"]:
            problems.append(f"extraction certainty {x.certainty} != {exp['certainty']}")
        for fld in ("inflow", "outflow"):
            want = s["event_input"].get(fld, 0)
            if want and abs(getattr(x, fld) - want) > 1:
                problems.append(f"extraction {fld} {getattr(x, fld)} != {want}")
        if exp.get("sensitive") and not x.sensitive:
            problems.append("sensitivity not detected")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default="template")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    security._ITER = 1000
    tmp = tempfile.mkdtemp()
    url = f"sqlite:///{Path(tmp).as_posix()}/golden_run.sqlite3"
    bootstrap.init(url)
    llm = make_llm(args.llm)
    results = []
    with session_scope(url) as dbs:
        repo = Repo(dbs)
        arjun, _ = auth.authenticate(repo, "arjun.mehta@atlas-demo.com", "atlas-demo", "RM")
        print(f"LLM provider: {llm.name} ({llm.model}) | scenarios: {len(GOLDEN['scenarios'])}\n")
        for s in GOLDEN["scenarios"]:
            cid = "c-" + s["client"].lower()
            ev = agent_event(s)
            rm_inputs = None
            sig = s["event_input"].get("signal") or {}
            if sig.get("new_goal"):
                rm_inputs = {"new_goal": sig["new_goal"]}
            r = run_monitoring(repo, arjun, cid, event=ev, trigger="golden_test", llm=llm, rm_inputs=rm_inputs, force=True)
            problems = check(s, r, repo, cid)
            results.append(dict(id=s["id"], title=s["title"], expected_tier=str(s["expected"]["tier"]), tier=r.tier, status=r.status, problems=problems,
                                provider=(r.proposal.draft_provider if r.proposal else ""), flags=(r.analysis.flags if r.analysis else [])))
            mark = "PASS" if not problems else "FAIL"
            print(f"{mark} {s['id']} {s['client']} tier {r.tier:>6} (exp {s['expected']['tier']}) {s['title'][:52]:52} {'; '.join(problems)}")
        # audit completeness: every run has start + finish events and steps
        runs = repo.s.execute(__import__("sqlalchemy").text("select count(*) from agent_runs")).scalar()
        audit_runs = repo.s.execute(__import__("sqlalchemy").text("select count(*) from audit_events where action like 'Agent run %' and action != 'Agent run started'")).scalar()
        started = repo.s.execute(__import__("sqlalchemy").text("select count(*) from audit_events where action = 'Agent run started'")).scalar()
        print(f"\nRuns recorded: {runs}; start events: {started}; finish events: {audit_runs}")
    failed = [r for r in results if r["problems"]]
    print(f"\nRESULT: {len(results) - len(failed)}/{len(results)} scenarios passed end to end")
    if args.json:
        Path(args.json).write_text(json.dumps(dict(provider=llm.name, results=results), indent=2), encoding="utf-8")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
