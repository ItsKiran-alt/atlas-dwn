"""Diagnose: can the page scroll with the mouse wheel? Is the iframe dimmed while the server works?"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.sync_api import sync_playwright   # noqa: E402
from ui_harness import component_frame, login, running_app   # noqa: E402

with running_app(8662) as (url, tmp), sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1366, "height": 700})
    pg.goto(url)
    f = login(pg)
    info = pg.evaluate("""() => { const i = document.querySelector('iframe'); return {scrolling: i.getAttribute('scrolling'), sandbox: i.getAttribute('sandbox'), h: i.offsetHeight, w: i.offsetWidth}; }""")
    print("iframe:", info)
    f.evaluate("setView('settings')")
    pg.wait_for_timeout(800)
    dims = f.evaluate("({docH: document.documentElement.scrollHeight, winH: window.innerHeight, bodyOverflow: getComputedStyle(document.body).overflow, htmlOverflow: getComputedStyle(document.documentElement).overflow, rootH: document.getElementById('root').scrollHeight})")
    print("inside frame:", dims)
    pg.mouse.move(700, 400)
    pg.mouse.wheel(0, 900)
    pg.wait_for_timeout(500)
    print("scrollY after wheel:", f.evaluate("window.scrollY"), "| root scrollTop:", f.evaluate("document.getElementById('root').scrollTop"), "| parent scrollY:", pg.evaluate("window.scrollY"))
    # dimming while the server works: fire an action and sample opacity
    f.evaluate("act('reminders')")
    ops = []
    for _ in range(12):
        ops.append(pg.evaluate("""() => { const e = document.querySelector('[data-testid=stCustomComponentV1]') || document.querySelector('iframe'); const els = [e, e.parentElement, e.parentElement && e.parentElement.parentElement]; return els.map(x => x ? getComputedStyle(x).opacity + (x.getAttribute('data-stale') ? '(stale)' : '') : '-').join(' / '); }"""))
        pg.wait_for_timeout(150)
    print("opacity samples:", sorted(set(ops)))
    b.close()
