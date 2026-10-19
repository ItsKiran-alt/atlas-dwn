"""Do the tests have teeth? Break one safety control at a time in a COPY of the project and confirm the test suite fails.

    .venv\\Scripts\\python scripts\\mutation_check.py

Each mutation removes or weakens a real control (consent gate, stale-data gate, wording check, RBAC scoping, second-approver rule,
lock, unique slot, injection scan, approval authority, secret scrubbing, ...). A mutation that the tests do NOT catch is a gap in the tests.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# (name, file, old, new)
MUTATIONS = [
    ("consent gate removed from the engine", "dwn/controls/gates.py", "    if not p.consent:\n        return \"no_consent\"\n", "    pass\n"),
    ("stale-data gate removed", "dwn/controls/gates.py", "    if ev.feed_age_min > policy.max_feed_age_min:\n        return \"stale_data\"\n", "    pass\n"),
    ("implausible-tick gate removed", "dwn/controls/gates.py", "            return \"implausible_data\"", "            pass"),
    ("injection scan removed", "dwn/controls/gates.py", "    if scan_untrusted_text(ev.note_text):\n        return \"security_injection\"\n", "    pass\n"),
    ("prohibited-wording check disabled", "dwn/controls/wording.py", "    return [rx.pattern for rx in _P if rx.search(text or \"\")]", "    return []"),
    ("figure-traceability check disabled", "dwn/controls/wording.py", "        if not any(abs(v - a) <= _tol(v, a) for v in vals for a in allowed):\n            bad.append(tok)", "        pass"),
    ("RM scoping removed (RM sees every client)", "dwn/services.py", "        own = repo.list_clients(rm_id=user.rm_id)", "        own = repo.list_clients(include_all=True)"),
    ("client scoping removed (client sees every client)", "dwn/services.py", "        return repo.list_clients(client_id=user.client_id)", "        return repo.list_clients(include_all=True)"),
    ("consent check removed from RM decisions", "dwn/services.py", "def require_monitoring_consent(repo: Repo, client: Client):\n    if not monitoring_allowed(repo, client.id):", "def require_monitoring_consent(repo: Repo, client: Client):\n    if False:"),
    ("Tier 3 conversation requirement removed", "dwn/services.py", "    if tier == \"3\" and decision == \"approve\" and not conversation_held:", "    if False:"),
    ("second approver may equal first approver", "dwn/services.py", "        if user.rm_id == first_rm:", "        if False:"),
    ("second approver authority not checked", "dwn/services.py", "        if _rank(repo.get_perms(user.rm_id)[\"approval\"]) < 2:", "        if False:"),
    ("blocked proposals can be approved", "dwn/services.py", "    if status == \"blocked\" and decision == \"approve\":", "    if False:"),
    ("Admin permission check removed (RM can change permissions)", "dwn/services.py", "def save_rm_permissions(repo: Repo, user: User, rm_name: str, schedule: bool, all_clients: bool, approval: str, override: bool):\n    require_role(user, \"Admin\")", "def save_rm_permissions(repo: Repo, user: User, rm_name: str, schedule: bool, all_clients: bool, approval: str, override: bool):\n    pass"),
    ("scheduling permission ignored", "dwn/services.py", "    return user.role == \"Admin\" or (user.role == \"RM\" and repo.get_perms(user.rm_id)[\"schedule\"])", "    return True"),
    ("selected-client scope not validated", "dwn/services.py", "        if not set(chosen) <= allowed:\n            raise Denied(\"One or more selected clients are outside the scope granted to you.\")", "        pass"),
    ("job lock never refuses", "dwn/repo.py", "        except IntegrityError:\n            return False\n\n    def release_lock", "        except IntegrityError:\n            return True\n\n    def release_lock"),
    ("duplicate slot allowed", "dwn/repo.py", "        except IntegrityError:\n            return False\n\n    def update_job", "        except IntegrityError:\n            return True\n\n    def update_job"),
    ("scheduled job skips permission re-check", "dwn/scheduler/jobs.py", "    if not services.rm_can_schedule(repo, owner):\n        if trigger == \"manual\":", "    if False:\n        if trigger == \"manual\":"),
    ("missed slots run late", "dwn/scheduler/jobs.py", "                if now - slot > timedelta(hours=config.JOB_GRACE_HOURS):", "                if False:"),
    ("injection note sent to the model", "dwn/agents/orchestrator.py", "                if scan_untrusted_text(event.note_text):", "                if False:"),
    ("hedged language can be 'confirmed'", "dwn/agents/skills.py", "        if HEDGE.search(note) and o.certainty == \"confirmed\":", "        if False:"),
    ("hosts not allow-listed", "dwn/data/http.py", "        if (p.hostname or \"\") not in self.hosts:", "        if False:"),
    ("freshness never stale", "dwn/data/freshness.py", "        return \"fresh\" if age.total_seconds() <= max_age_s else \"stale\"", "        return \"fresh\""),
    ("failed login not counted", "dwn/repo.py", "        r.failed_attempts = (r.failed_attempts or 0) + 1", "        r.failed_attempts = 0"),
    ("audit log editable (update trigger absent)", "alembic/versions/0001_initial_schema.py", """        op.execute("CREATE TRIGGER audit_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;")""", "        pass"),
    ("HTML escaping removed from the review modal", "dwn/ui/render.py", "<textarea id=\"messageBody\">{e(draft[\"body\"])}</textarea>", "<textarea id=\"messageBody\">{draft[\"body\"]}</textarea>"),
]


def main() -> int:
    work = Path(tempfile.mkdtemp()) / "proj"
    def ignore(d, names):
        skip = {".venv", "__pycache__", ".pytest_cache", ".git", ".coverage", "node_modules"}
        return [n for n in names if n in skip or (Path(d) == ROOT and n == "data")]       # only the TOP-level ./data (local database), not the dwn.data package
    shutil.copytree(ROOT, work, ignore=ignore)
    survived, caught = [], []
    for name, rel, old, new in MUTATIONS:
        f = work / rel
        orig = f.read_text(encoding="utf-8")
        if old not in orig:
            print(f"SKIP  {name}: pattern not found in {rel} (mutation list out of date)")
            survived.append((name, "pattern not found"))
            continue
        f.write_text(orig.replace(old, new, 1), encoding="utf-8")
        r = subprocess.run([PY, "-m", "pytest", "tests", "-q", "-x", "-p", "no:cacheprovider", "--no-header"], cwd=work, capture_output=True, text=True, timeout=900)
        f.write_text(orig, encoding="utf-8")
        ok = r.returncode != 0
        failed = [ln for ln in r.stdout.splitlines() if ln.startswith("FAILED")][:1]
        print(f"{'CAUGHT ' if ok else 'SURVIVED'} {name}" + (f"  <- {failed[0][7:90]}" if failed else ""))
        (caught if ok else survived).append((name, failed[0] if failed else ""))
    print(f"\n{len(caught)}/{len(MUTATIONS)} mutations were caught by the tests")
    if survived:
        print("NOT caught:", [n for n, _ in survived])
    shutil.rmtree(work.parent, ignore_errors=True)
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
