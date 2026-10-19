import sys
sys.path.insert(0, __file__.rsplit("\\", 1)[0] if "\\" in __file__ else ".")
from reference_engine import evaluate
from scenarios import CLIENTS, S

bad = 0
for s in S:
    r = evaluate(CLIENTS[s["client"]], s["event"])
    e = s["expected"]
    problems = []
    if r["tier"] != e["tier"]: problems.append(f"tier {r['tier']} != {e['tier']}")
    if r["flags"] != e["flags"]: problems.append(f"flags {sorted(r['flags'])} != {sorted(e['flags'])}")
    if r["message"] != e["message"]: problems.append(f"msg {r['message']} != {e['message']}")
    if e["goal_after"] and r.get("goal_after") != e["goal_after"]: problems.append(f"goal {r.get('goal_before')}->{r.get('goal_after')} != {e['goal_after']}")
    mark = "OK  " if not problems else "FAIL"
    bad += bool(problems)
    print(mark, s["id"], s["client"], r["tier"], f"drift={r.get('max_drift_pts')}/{r.get('band_pts')}", f"goal={r.get('goal_before')}->{r.get('goal_after')}",
          f"trade={r.get('trade_size_pct')}", r.get("factors"), "; ".join(problems))
print("mismatches:", bad, "of", len(S))
