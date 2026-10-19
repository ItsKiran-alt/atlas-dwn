"""Small helper to start the app on a throwaway database and drive it with headless Chromium (used by verification scripts)."""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def running_app(port=8661, env_extra=None):
    tmp = Path(tempfile.mkdtemp())
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{(tmp / 'ui.sqlite3').as_posix()}", DWN_ENV="dev", DWN_JOB_SKIP_REFRESH="1", **(env_extra or {}))
    log = (tmp / "server.log").open("w")
    p = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port), "--server.headless", "true"], cwd=str(ROOT), env=env, stdout=log, stderr=log)
    try:
        for _ in range(180):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3)
                break
            except Exception:
                time.sleep(1)
        yield f"http://127.0.0.1:{port}/", tmp
    finally:
        p.terminate()
        log.close()


def component_frame(page, timeout_s=120):
    for _ in range(timeout_s * 2):
        f = next((f for f in page.frames if "component" in (f.url or "")), None)
        if f:
            return f
        page.wait_for_timeout(500)
    raise RuntimeError("component frame not found")


def login(page, role="RM", email="priya.sharma@atlas-demo.com", password="atlas-demo"):
    f = component_frame(page)
    f.wait_for_selector("#loginGate", timeout=120000)
    f.evaluate(f"chooseRole('{role}', document.querySelector('[data-role={role}]')); document.getElementById('loginEmail').value='{email}'; document.getElementById('loginPassword').value='{password}'; demoLogin();")
    f.wait_for_function(f"document.body.dataset.role === '{role}'", timeout=60000)
    page.wait_for_timeout(1200)
    return f
