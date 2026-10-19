"""Smoke-test the app the way a hosted deployment runs it: DWN_ENV=prod, a PostgreSQL DATABASE_URL, a custom demo password.

    set DATABASE_URL=postgresql+psycopg://...   (an EMPTY database)
    set DWN_DEMO_PASSWORD=some-long-password
    .venv\\Scripts\\python scripts\\deploy_smoke.py

Starts Streamlit on a free port, drives it with a headless browser (login, workbench, agent run, research page) and prints PASS/FAIL per check.
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from playwright.sync_api import sync_playwright   # noqa: E402

PORT = 8651
PW = os.environ["DWN_DEMO_PASSWORD"]
env = dict(os.environ, DWN_ENV="prod", DWN_SEED_DEMO="1", DWN_JOB_SKIP_REFRESH="1")
log = (ROOT / "smoke_server.log").open("w")
srv = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(PORT), "--server.headless", "true"], cwd=str(ROOT), env=env, stdout=log, stderr=log)
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


try:
    for _ in range(180):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=3)
            break
        except Exception:
            time.sleep(1)
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--hide-scrollbars"])
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(f"http://127.0.0.1:{PORT}/")
        fr = None
        for _ in range(240):
            fr = next((f for f in pg.frames if "component" in (f.url or "")), None)
            if fr:
                try:
                    fr.wait_for_selector("#loginGate", timeout=1000)
                    break
                except Exception:
                    pass
            pg.wait_for_timeout(500)
        check("app started in prod mode against the configured database and shows the login page", fr is not None)
        pw_prefill = fr.evaluate("document.getElementById('loginPassword').value")
        check("custom demo password is NOT pre-filled on the login page", pw_prefill == "", repr(pw_prefill))
        fr.evaluate("document.getElementById('loginEmail').value='priya.sharma@atlas-demo.com'; document.getElementById('loginPassword').value='wrong-password'; demoLogin()")
        pg.wait_for_timeout(2500)
        check("wrong password is refused", fr.evaluate("!!document.getElementById('loginGate')"))
        fr.evaluate(f"document.getElementById('loginPassword').value={PW!r}; demoLogin()")
        fr.wait_for_function("document.body.dataset.role === 'RM'", timeout=30000)
        pg.wait_for_timeout(1500)
        check("RM signs in with the custom password", True)
        check("RM queue shows her 24 clients", fr.evaluate("document.querySelectorAll('.clientrow').length") == 24)
        fr.evaluate("selectClient('c-ananya.singh')"); pg.wait_for_timeout(2500)
        fr.evaluate("runAgent()")
        for _ in range(60):
            t = fr.evaluate("document.getElementById('toast') ? document.getElementById('toast').textContent : ''")
            if "Monitoring check complete" in t or "Paused" in t or "failed" in t:
                break
            pg.wait_for_timeout(1000)
        check("agent run completes and records a proposal or an explained pause", ("complete" in t or "Paused" in t), t[:90])
        fr.evaluate("setView('research')"); pg.wait_for_timeout(1500)
        check("Research & Market page renders", fr.evaluate("!!document.querySelector('#view-research table')"))
        fr.evaluate("logoutDemo()"); pg.wait_for_timeout(2000)
        check("sign-out returns to the login page", fr.evaluate("!!document.getElementById('loginGate')"))
        b.close()
finally:
    srv.terminate()
    log.close()
    text = (ROOT / "smoke_server.log").read_text(errors="replace")
    bad = [ln for ln in text.splitlines() if "Traceback" in ln or "Error" in ln and "DeprecationWarning" not in ln]
    print("server log errors:", bad[:3] if bad else "none")
print(f"\n{sum(results)}/{len(results)} smoke checks passed")
sys.exit(0 if all(results) else 1)
