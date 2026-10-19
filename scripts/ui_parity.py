"""Compare the Streamlit app with the ORIGINAL prototype HTML, page by page, in a real headless browser.

    .venv\\Scripts\\python scripts\\ui_parity.py [--out docs/parity]

For every role/page/viewport it measures the same CSS-selected components in both pages (position, size, font, colour, background,
radius, padding), compares page headings and button labels, and saves a side-by-side screenshot (original LEFT, app RIGHT).
It starts its own copies of both: a static server for reference/atlas_rm_workbench_original.html and the app on a throwaway database.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from playwright.sync_api import sync_playwright   # noqa: E402
from PIL import Image                              # noqa: E402

ORIG_PORT, APP_PORT = 8602, 8601
SELECTORS = [".topbar", ".brand", ".search", ".topbutton", ".userchip", ".avatar", ".sidebar", ".nav", ".nav.active", ".navsep", ".main", ".pagehead", ".pagehead h1", ".eyebrow", ".sub",
             ".actions", ".btn", ".btn.primary", ".btn.small", ".metrics", ".metric", ".metric strong", ".metric span", ".bubble", ".workgrid", ".card", ".cardhead", ".cardhead h2",
             ".chip", ".chip.selected", ".clientfilters", ".clientrow", ".clientrow.active", ".clientrow strong", ".clientrow small", ".status", ".clienthero h2", ".tier", ".section-tabs",
             ".section-tabs button", ".summarygrid", ".summary", ".summary strong", ".twocol", ".chartcard", ".charttitle", ".donut", ".legendrow", ".recommend", ".workflow", ".step",
             ".pill", ".riskitem", ".risklist", ".goalrow", ".progressbar", ".event", ".eventicon", ".tablewrap", "table", "th", "td", ".two-panel", ".checkrow", ".checkmark", ".notice",
             ".calloutnote", ".auditfilters", ".archgrid", ".archnode", ".scheduler-grid", ".schedule-summary", ".days", ".field", ".field label", ".field input", ".field select", ".role-tag",
             ".login-shell", ".login-brand", ".login-right", ".rolecards", ".rolecard", ".rolecard.selected", ".toast", ".footnote", ".clientpreview"]
JS_COLLECT = """(sels) => {
  const out = {};
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  for (const s of sels) {
    const all = [...document.querySelectorAll(s)].filter(vis);
    const el = all[0];
    if (!el) { out[s] = null; continue; }
    const r = el.getBoundingClientRect(), c = getComputedStyle(el);
    out[s] = {n: all.length, x: Math.round(r.x), y: Math.round(r.y + window.scrollY), w: Math.round(r.width), h: Math.round(r.height), fs: c.fontSize, fw: c.fontWeight, ff: c.fontFamily.split(',')[0].replace(/"/g, ''),
              color: c.color, bg: c.backgroundColor, br: c.borderRadius, pad: c.padding, border: c.borderTopWidth + ' ' + c.borderTopColor, shadow: c.boxShadow !== 'none'};
  }
  const txt = sel => [...document.querySelectorAll(sel)].filter(vis).map(e => e.innerText.replace(/\\s+/g, ' ').trim()).filter(Boolean);
  return {sel: out, h1: txt('h1'), h2: txt('h2'), h3: txt('h3'), eyebrow: txt('.eyebrow'), btns: txt('.btn, .topbutton, .rolecard'), nav: txt('.nav'), tabs: txt('.section-tabs button, .tab'),
          th: txt('th'), w: document.documentElement.scrollWidth, hh: document.documentElement.scrollHeight};
}"""


def wait_http(url, secs=90):
    t = time.time()
    while time.time() - t < secs:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except Exception:
            time.sleep(1)
    return False


def norm(t: str) -> str:
    t = re.sub(r"₹\s?([\d.,]+)\s?Cr", r"$\1M", t)
    return t.replace("₹", "$").replace("SEBI", "SEC/FINRA")


class Pair:
    """The original page and the app page, each driven through the same role/view."""
    def __init__(self, pw, size):
        self.b = pw.chromium.launch(args=["--hide-scrollbars"])
        self.o = self.b.new_context(viewport=size).new_page()
        self.a = self.b.new_context(viewport=size).new_page()
        self.size = size

    def app_frame(self):
        for _ in range(60):
            for f in self.a.frames:
                if f != self.a.main_frame and "component" in (f.url or ""):
                    return f
            self.a.wait_for_timeout(500)                          # (time.sleep would block Playwright's event loop)
        raise RuntimeError("component frame not found")

    def login(self, role, email, mine_email):
        self.o.goto(f"http://127.0.0.1:{ORIG_PORT}/atlas_rm_workbench_original.html")
        self.o.evaluate(f"chooseRole('{role}', document.querySelector('[data-role={role}]')); document.getElementById('loginEmail').value='{email}'; demoLogin();")
        self.o.wait_for_timeout(400)
        self.a.goto(f"http://127.0.0.1:{APP_PORT}/")
        f = self.app_frame()
        f.wait_for_selector("#loginGate")
        f.evaluate(f"chooseRole('{role}', document.querySelector('[data-role={role}]')); document.getElementById('loginEmail').value='{mine_email}'; document.getElementById('loginPassword').value='atlas-demo'; demoLogin();")
        f.wait_for_function("document.body.dataset.role === '%s'" % role, timeout=30000)
        self.a.wait_for_timeout(800)
        self.f = f

    def view(self, name, setup_o="", setup_a=""):
        # the prototype refuses to open some pages for some roles (e.g. Client View for RM); force-show them so the LAYOUT can still be compared
        self.o.evaluate(f"setView('{name}'); if (!document.getElementById('view-{name}').classList.contains('active')) {{ document.querySelectorAll('.view').forEach(v => v.classList.remove('active')); document.getElementById('view-{name}').classList.add('active'); }} {setup_o}")
        self.f.evaluate(f"setView('{name}'); {setup_a}")
        self.o.wait_for_timeout(250); self.a.wait_for_timeout(600)

    def collect(self):
        return self.o.evaluate(JS_COLLECT, SELECTORS), self.f.evaluate(JS_COLLECT, SELECTORS)

    def shot(self, path):
        po, pa = path.with_name(path.stem + "_o.png"), path.with_name(path.stem + "_a.png")
        self.o.screenshot(path=str(po)); self.a.screenshot(path=str(pa))
        a, b = Image.open(po), Image.open(pa)
        w = a.width + b.width + 12
        canvas = Image.new("RGB", (w, max(a.height, b.height)), (255, 0, 255))
        canvas.paste(a, (0, 0)); canvas.paste(b, (a.width + 12, 0))
        canvas.thumbnail((2400, 1400))
        canvas.save(path)
        po.unlink(); pa.unlink()


def compare(o, a, tol=2):
    rows, exact, total = [], 0, 0
    for s in SELECTORS:
        x, y = o["sel"].get(s), a["sel"].get(s)
        if x is None and y is None:
            continue
        if x is None or y is None:
            rows.append((s, "present only in " + ("app" if x is None else "original"), "")); total += 1
            continue
        total += 1
        diffs = []
        for k in ("fs", "fw", "ff", "color", "bg", "br", "pad", "border"):
            if x[k] != y[k]:
                diffs.append(f"{k}: {x[k]} → {y[k]}")
        for k in ("w", "h"):
            if abs(x[k] - y[k]) > tol and s not in (".main", ".card", ".workgrid", ".tablewrap", "table", ".risklist", ".sidebar", ".chartcard", ".twocol", ".two-panel", ".scheduler-grid", ".events", ".metrics"):
                diffs.append(f"{k}: {x[k]} → {y[k]}")
        if diffs:
            rows.append((s, "; ".join(diffs[:4]), f"n {x['n']}→{y['n']}"))
        else:
            exact += 1
    return exact, total, rows


def text_diff(o, a):
    out = []
    for k in ("h1", "h2", "eyebrow", "nav", "tabs", "th", "btns"):
        so, sa = [norm(t) for t in o[k]], [norm(t) for t in a[k]]
        miss, extra = [t for t in so if t not in sa], [t for t in sa if t not in so]
        if miss or extra:
            out.append((k, miss[:6], extra[:6]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "parity"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{(tmp / 'parity.sqlite3').as_posix()}", DWN_ENV="dev", DWN_JOB_SKIP_REFRESH="1")
    srv = subprocess.Popen([sys.executable, "-m", "http.server", str(ORIG_PORT), "--bind", "127.0.0.1"], cwd=str(ROOT / "reference"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    app = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(APP_PORT), "--server.headless", "true"], cwd=str(ROOT), env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report = []
    try:
        assert wait_http(f"http://127.0.0.1:{ORIG_PORT}/atlas_rm_workbench_original.html") and wait_http(f"http://127.0.0.1:{APP_PORT}/", 120), "servers did not start"
        time.sleep(4)
        plan = [("RM", "priya.sharma@atlas-demo.com", "priya.sharma@atlas-demo.com", ["workbench", "clientview", "home", "clients", "insights", "research", "tasks", "reports", "settings"]),
                ("Admin", "admin@atlas-demo.com", "admin@atlas-demo.com", ["settings", "compliance"]),
                ("Client", "ramesh.agarwal@atlas-demo.com", "ramesh.agarwal@atlas-demo.com", ["clientportal"])]
        with sync_playwright() as pw:
            for size_name, size in (("desktop", {"width": 1440, "height": 900}), ("tablet", {"width": 900, "height": 1000}), ("mobile", {"width": 390, "height": 844})):
                pair = Pair(pw, size)
                # login gate
                pair.o.goto(f"http://127.0.0.1:{ORIG_PORT}/atlas_rm_workbench_original.html"); pair.a.goto(f"http://127.0.0.1:{APP_PORT}/")
                pair.f = pair.app_frame(); pair.f.wait_for_selector("#loginGate"); pair.o.wait_for_timeout(300); pair.a.wait_for_timeout(600)
                o, a = pair.collect()
                pair.shot(out / f"{size_name}_login.png")
                ex, tot, rows = compare(o, a)
                report.append(dict(size=size_name, role="-", view="login", exact=ex, total=tot, rows=rows, text=text_diff(o, a)))
                for role, oe, ae, views in plan:
                    pair.login(role, oe, ae)
                    for v in views:
                        if size_name != "desktop" and v not in ("workbench", "settings", "clientportal", "compliance"):
                            continue
                        pair.view(v)
                        o, a = pair.collect()
                        pair.shot(out / f"{size_name}_{role.lower()}_{v}.png")
                        ex, tot, rows = compare(o, a)
                        report.append(dict(size=size_name, role=role, view=v, exact=ex, total=tot, rows=rows, text=text_diff(o, a)))
                        print(f"{size_name:8} {role:6} {v:12} {ex}/{tot} measured components identical")
                    if role == "Client" and size_name == "desktop":           # new-client onboarding (consent) page
                        pair.o.evaluate("logoutDemo(); startClientSignup();")
                        pair.f.evaluate("logoutDemo()"); pair.a.wait_for_timeout(1500)
                        pair.f = pair.app_frame(); pair.f.wait_for_selector("#loginGate"); pair.f.evaluate("startClientSignup()"); pair.f.wait_for_selector("#view-onboarding"); pair.a.wait_for_timeout(500)
                        o, a = pair.collect(); pair.shot(out / "desktop_client_onboarding.png")
                        ex, tot, rows = compare(o, a)
                        report.append(dict(size="desktop", role="Client", view="onboarding", exact=ex, total=tot, rows=rows, text=text_diff(o, a)))
                        print(f"desktop  Client onboarding  {ex}/{tot} measured components identical")
                    if role == "RM" and size_name == "desktop":              # modals
                        pair.view("workbench")
                        for mod, fn in (("reviewModal", "openReview()"), ("askModal", "openAsk()"), ("messageModal", "openClientMessage()"), ("notesModal", "openNotes()")):
                            pair.o.evaluate(fn); pair.f.evaluate(fn); pair.o.wait_for_timeout(200); pair.a.wait_for_timeout(300)
                            o, a = pair.collect()
                            pair.shot(out / f"desktop_rm_modal_{mod}.png")
                            report.append(dict(size="desktop", role="RM", view="modal:" + mod, exact=0, total=0, rows=[], text=text_diff(o, a)))
                            pair.o.evaluate(f"closeModal('{mod}')"); pair.f.evaluate(f"closeModal('{mod}')")
                pair.b.close()
    finally:
        app.terminate(); srv.terminate()
    (out / "parity_report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    tot_ex = sum(r["exact"] for r in report); tot_n = sum(r["total"] for r in report)
    print(f"\nTOTAL: {tot_ex}/{tot_n} measured component checks identical across {len(report)} page/viewport comparisons")


if __name__ == "__main__":
    main()
