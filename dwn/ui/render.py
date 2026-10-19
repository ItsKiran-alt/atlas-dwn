"""Server-side HTML rendering of the Atlas workspace.

Markup, class names and copy are ported from the supplied prototype (atlas_rm_workbench_updated (4).html);
dynamic values come from the store and ONLY for records the signed-in user is authorised to see.
Currency is USD (1 crore in the prototype = $1M here).
"""
from __future__ import annotations

from html import escape as e

from .. import seed, services
from ..engines.portfolio import CLASS_LABEL, headline_drift, holding_shares, money, money_m
from ..domain import CONSENT_VERSION, User

Store = object          # the renderers receive a controller.ViewData snapshot

TODAY_ISO = "19 Oct 2026"


def _h(*parts) -> int:
    return seed._h(*parts)


def initials(name: str) -> str:
    return "".join(w[0] for w in name.split()[:2]).upper()


# ------------------------------------------------------------------ login & onboarding
def login_gate(role: str = "RM", error: str = "", demo: bool = True, demo_pw_known: bool = True) -> str:
    defaults = {"Admin": ("admin@atlas-demo.com", "atlas-demo"), "RM": ("priya.sharma@atlas-demo.com", "atlas-demo"),
                "Client": ("ramesh.agarwal@atlas-demo.com", "atlas-demo")}
    em, pw = defaults[role] if demo else ("", "")
    if not demo_pw_known:
        pw = ""                                        # a custom demo password is never pre-filled
    note = ("Prototype sign-in. Demo accounts only, with a shared demo-only password; no real client data. Real identity management is added in the next phase." if demo
            else "Sign in with your Atlas account. Access is limited to your role and your clients.")
    sel = lambda r: " selected" if r == role else ""
    err = f'<div class="notice" style="background:var(--redbg);color:#75424a">{e(error)}</div>' if error else ""
    return f'''<div class="login-gate" id="loginGate"><div class="login-shell">
  <div class="login-brand"><div><div style="letter-spacing:4px;font:24px Georgia,serif">ATLAS</div><div style="letter-spacing:2px;font-size:10px;margin-top:4px">WEALTH MANAGEMENT</div><h1>Clarity for every financial decision.</h1><p>A secure workspace for relationship teams, clients and compliance professionals.</p></div><div style="font-size:11px;color:#c5d8eb">PRIVATE WEALTH · AI-ASSISTED · HUMAN-LED</div></div>
  <div class="login-right"><div class="eyebrow">Welcome back</div><h2>Sign in to Atlas</h2><p class="sub">Sign in to your dedicated Atlas workspace.</p>
   <div class="rolecards"><button class="rolecard{sel("Admin")}" data-role="Admin" onclick="chooseRole('Admin',this)"><span>⚙</span>Admin</button><button class="rolecard{sel("RM")}" data-role="RM" onclick="chooseRole('RM',this)"><span>♙</span>Relationship<br>Manager</button><button class="rolecard{sel("Client")}" data-role="Client" onclick="chooseRole('Client',this)"><span>▣</span>Client</button></div>
   {err}<div class="field"><label for="loginEmail">Work email</label><input id="loginEmail" type="email" value="{e(em)}" placeholder="name@company.com" style="width:100%" autocomplete="off"></div>
   <div class="field"><label for="loginPassword">Password</label><input id="loginPassword" type="password" value="{e(pw)}" placeholder="Enter password" style="width:100%" autocomplete="off"></div>
   <button class="btn primary" style="width:100%;padding:12px" onclick="demoLogin()">Sign in securely →</button><button class="btn" style="width:100%;margin-top:8px" onclick="startClientSignup()">New client? Start onboarding</button>
   <div class="login-note">{e(note)}</div>
  </div></div></div>'''


def onboarding() -> str:
    return f'''<section class="view active" id="view-onboarding" style="max-width:900px;margin:30px auto;padding:24px"><div class="pagehead"><div><div class="eyebrow">Client onboarding · Atlas Wealth Management</div><h1>Consent & authorisation</h1><div class="sub">Review the terms before activating AI-assisted portfolio monitoring.</div></div></div><div class="card" style="padding:18px;margin-bottom:14px"><div class="field"><label for="onboardingClientEmail">New client email / account ID</label><input id="onboardingClientEmail" type="email" placeholder="you@example.com" style="width:100%" required></div><div class="field"><label for="onboardingPassword">Create a password (at least 10 characters)</label><input id="onboardingPassword" type="password" style="width:100%" autocomplete="new-password"></div><div class="field"><label for="onboardingPassword2">Confirm password</label><input id="onboardingPassword2" type="password" style="width:100%" autocomplete="new-password"></div><div class="footnote">New clients complete consent once during onboarding. Existing clients sign in directly and are not asked to consent again.</div></div><div class="card" style="padding:24px"><div class="notice" style="border-left:4px solid #4b8f77;background:#edf7f2;padding:18px;font-size:16px;color:#173e32"><strong>IMPORTANT: To help optimise your portfolio against your financial goals, your consent is needed for Atlas Wealth Management’s agentic AI to continuously monitor your portfolio, analyse market developments and prepare adjustment recommendations. Every proposed portfolio adjustment remains subject to review and approval by your Relationship Manager. The AI will not independently execute trades.</strong></div><h2>What you are consenting to</h2><ul><li>Analysis of portfolio holdings and relevant financial information you have authorised Atlas to use.</li><li>Continuous or scheduled monitoring of allocation, risk, goal progress and relevant market events.</li><li>AI-assisted recommendations and explanations for your Relationship Manager.</li><li>Recording of consent, reviews, approvals and related actions for governance and audit purposes.</li></ul><h3>Important terms and safeguards</h3><p class="muted">This prototype wording is illustrative, not legal advice or an approved agreement. Production wording must be reviewed by Atlas compliance and legal teams and aligned with applicable SEC and FINRA requirements, GDPR and CCPA privacy obligations, client mandate, risk profiling, suitability and approved terms. Consent does not guarantee returns or authorise the AI to trade independently. You can withdraw consent at any time.</p><div class="field"><label><input type="checkbox" id="consentTerms"> I have read and agree to the applicable Terms & Conditions and privacy notice.</label></div><div class="field"><label><input type="checkbox" id="consentAI"> I consent to AI-assisted continuous portfolio monitoring, analysis and recommendation drafting, with Relationship Manager review and approval required for proposed adjustments.</label></div><div class="actions"><button class="btn" onclick="logoutDemo()">Cancel / sign out</button><button class="btn primary" onclick="acceptOnboardingConsent()">Accept and continue →</button></div><div class="footnote">Your acceptance is stored with a timestamp and the consent text version ({CONSENT_VERSION}). Prototype record only; not a legally valid consent.</div></div></section>'''


# ------------------------------------------------------------------ client portal
def client_portal(store: Store, user: User) -> str:
    c = store.client(user.client_id)
    rows = holding_shares(c.holdings)
    hold = "".join(f"<tr><td>{e(a)}</td><td>{e(cl)}</td><td>{money_m(v)}</td><td>{s:.1f}%</td></tr>" for a, cl, v, s in rows) or \
        '<tr><td>Portfolio records</td><td>—</td><td>Awaiting account linkage</td><td>—</td></tr>'
    tx = "".join(f'<tr><td>{d}</td><td>{k}</td><td>{e(i)}</td><td>{money(a)}</td><td><span class="pill">{s}</span></td></tr>' for d, k, i, a, s in c.transactions) or \
        '<tr><td colspan="5">No transactions available until the client account is linked.</td></tr>'
    aum = money_m(c.aum_musd) if c.aum_musd else "—"
    ret = "+7.8%" if c.aum_musd else "—"
    return f'''<section class="view active" id="view-clientportal" style="max-width:1100px;margin:30px auto;padding:24px"><div class="pagehead"><div><div class="eyebrow">Secure client portal</div><h1 id="portalGreeting">Welcome, {e(c.name)}</h1><div class="sub">Your portfolio and transaction history, linked to the account you signed in with.</div></div><button class="btn" onclick="logoutDemo()">Sign out</button></div><div class="metrics"><div class="metric"><div class="bubble">$</div><div><strong id="portalAum">{aum}</strong><span>Total portfolio value</span></div></div><div class="metric"><div class="bubble">↗</div><div><strong>{ret}</strong><span>Illustrative 1-year return</span></div></div><div class="metric"><div class="bubble">▤</div><div><strong>{len(c.holdings)}</strong><span>Investment holdings</span></div></div></div><div class="card" style="margin-top:16px"><div class="cardhead"><div><h2>Your portfolio</h2><div class="sub">Illustrative holdings linked to this demo client account</div></div><span class="pill">Read-only</span></div><div class="tablewrap"><table><thead><tr><th>Asset / investment</th><th>Asset class</th><th>Current value</th><th>Portfolio share</th></tr></thead><tbody id="portalHoldings">{hold}</tbody></table></div></div><div class="card" style="margin-top:16px"><div class="cardhead"><div><h2>Previous transactions</h2><div class="sub">Transaction history for the signed-in account</div></div></div><div class="tablewrap"><table><thead><tr><th>Date</th><th>Transaction</th><th>Investment</th><th>Amount</th><th>Status</th></tr></thead><tbody id="portalTransactions">{tx}</tbody></table></div><div class="footnote">All holdings and transactions shown here are fictional demo data. Records are retrieved only after a server-side identity and account-ownership check.</div></div>{_consent_card(store)}</section>{_consent_modals()}'''


def _consent_card(store) -> str:
    ci = store.consent_info
    if ci and ci["active"]:
        return (f'''<div class="card" style="margin-top:16px"><div class="cardhead"><div><h2>Your consent</h2><div class="sub">AI-assisted portfolio monitoring · consent version {e(ci["version"])}</div></div><span class="pill">Active</span></div><p class="muted">You agreed on {e(ci["accepted_at"])} UTC to AI-assisted monitoring and recommendation drafting. Every proposed change is reviewed by your Relationship Manager; the AI never trades on its own. You can withdraw consent at any time: monitoring and recommendations for your account then pause. Your data is not deleted.</p><button class="btn danger" onclick="openModal('withdrawModal')">Withdraw consent</button></div>''')
    when = f" on {e(ci['withdrawn_at'])} UTC" if ci and ci["withdrawn_at"] else ""
    return (f'''<div class="card" style="margin-top:16px"><div class="cardhead"><div><h2>Your consent</h2><div class="sub">AI-assisted portfolio monitoring</div></div><span class="pill pending">Withdrawn</span></div><p class="muted">Consent was withdrawn{when}. Monitoring and recommendations for your account are paused. You can give consent again at any time.</p><button class="btn primary" onclick="openModal('regrantModal')">Give consent again</button></div>''')


def _consent_modals() -> str:
    return '''<div class="modalback" id="withdrawModal" role="dialog" aria-modal="true"><div class="modal"><div class="modalhead"><h2>Withdraw consent?</h2><button class="close" onclick="closeModal('withdrawModal')">×</button></div><div class="modalbody"><div class="notice">Withdrawing consent pauses AI-assisted monitoring and recommendations for your account. Your portfolio and transaction history stay visible to you, and nothing is deleted.</div></div><div class="modalfoot"><button class="btn" onclick="closeModal('withdrawModal')">Keep consent</button><button class="btn danger" onclick="act('withdraw_consent')">Withdraw consent</button></div></div></div>
<div class="modalback" id="regrantModal" role="dialog" aria-modal="true"><div class="modal"><div class="modalhead"><h2>Give consent again</h2><button class="close" onclick="closeModal('regrantModal')">×</button></div><div class="modalbody"><div class="field"><label><input type="checkbox" id="regrantTerms"> I have read and agree to the applicable Terms & Conditions and privacy notice.</label></div><div class="field"><label><input type="checkbox" id="regrantAI"> I consent to AI-assisted continuous portfolio monitoring, analysis and recommendation drafting, with Relationship Manager review and approval required for proposed adjustments.</label></div></div><div class="modalfoot"><button class="btn" onclick="closeModal('regrantModal')">Cancel</button><button class="btn primary" onclick="act('regrant_consent',{terms:document.getElementById('regrantTerms').checked,ai:document.getElementById('regrantAI').checked})">Give consent</button></div></div></div>'''


# ------------------------------------------------------------------ shell
def _nav(store: Store, user: User, n_tasks: int) -> str:
    return f'''<aside class="sidebar">
  <button class="nav" data-access="rm" data-view="home" onclick="setMain('home',this)"><span class="ico">⌂</span>Home</button>
  <button class="nav" data-access="rm" data-view="workbench" onclick="setMain('workbench',this)"><span class="ico">▦</span>RM Workbench</button>
  <button class="nav" data-access="rm" data-view="clients" onclick="setMain('clients',this)"><span class="ico">♙</span>Clients</button>
  <button class="nav" data-access="rm" data-view="insights" onclick="setMain('insights',this)"><span class="ico">✧</span>AI Insights</button>
  <button class="nav" data-access="rm" data-view="research" onclick="setMain('research',this)"><span class="ico">◎</span>Research & Market</button>
  <button class="nav" data-access="rm" data-view="tasks" onclick="setMain('tasks',this)"><span class="ico">☷</span>Tasks <span class="chip red">{n_tasks}</span></button>
  <button class="nav" data-access="rm" data-view="reports" onclick="setMain('reports',this)"><span class="ico">▤</span>Reports</button>
  <div class="navsep"></div>
  <button class="nav" data-access="admin" data-view="compliance" onclick="setView('compliance')"><span class="ico">♧</span>Compliance View</button>
  <div class="sidefoot"><div class="navsep"></div><button class="nav" data-access="settings" data-view="settings" onclick="setView('settings',this)"><span class="ico">⚙</span>Settings & Scheduler</button><button class="nav" onclick="toast('Help: use the sidebar to move between pages. AI output is decision support for review, never an instruction to trade.')">? Help</button></div>
</aside>'''


def _topbar(user: User, store: Store, n_alerts: int) -> str:
    sub = {"Admin": "Administrator", "RM": "Relationship Manager", "Client": "Client Portal"}[user.role]
    return f'''<header class="topbar">
  <div class="brand">ATLAS<small>WEALTH MANAGEMENT</small></div>
  <input class="search" id="globalSearch" placeholder="⌕  Search clients, portfolios, or ask a question..." aria-label="Search clients">
  <div class="topright">
    <button class="topbutton" onclick="openAsk()">✦ Ask Atlas AI</button>
    <button class="topbutton" onclick="act('reminders')">♧ <span style="color:#c43b45">{n_alerts}</span></button><button class="topbutton" onclick="logoutDemo()">Sign out</button>
    <div class="userchip"><div class="avatar">{e(user.initials)}</div><span><b>{e(user.name)}</b><br><span style="opacity:.7">{sub}</span></span></div>
  </div>
</header>'''


# ------------------------------------------------------------------ workbench
def _queue_rows(clients, selected_id) -> str:
    out = []
    for c in clients:
        act = " active" if c.id == selected_id else ""
        out.append(f'<div class="clientrow{act}" data-id="{c.id}" data-name="{e(c.name.lower())}" data-kind="{c.kind}" onclick="selectClient(\'{c.id}\')"><div class="avatar">{initials(c.name)}</div><div><strong>{e(c.name)}</strong><small>{money_m(c.aum_musd)} · {e(c.issue)}</small></div><span class="status {c.status_class}">{c.status_label}</span></div>')
    return "".join(out)


def _alloc_text(c) -> str:
    parts = [f"{c.plan[k]}% {n}" for k, n in (("EQ", "Equity"), ("FI", "Bonds"), ("AL", "Alternatives"), ("CA", "Cash")) if c.plan.get(k)]
    return "Target: " + " / ".join(parts)


def _donut_style(c) -> str:
    w = c.weights
    total = sum(w.get(k, 0) for k in ("EQ", "FI", "AL", "CA")) or 1
    cols = [("EQ", "#245b9d"), ("FI", "#8eb6ec"), ("AL", "#8392a6"), ("CA", "#d9e7fa")]
    acc, stops = 0.0, []
    for k, col in cols:
        p = w.get(k, 0) / total * 100
        stops.append(f"{col} {acc:.1f}% {acc + p:.1f}%")
        acc += p
    return "background:conic-gradient(" + ",".join(stops) + ")"


def _perf(c) -> dict:
    if c.name == "Rajesh Menon":                      # figures shown in the supplied prototype
        return {"1Y": "+8.2%", "3Y": "+21.4%", "5Y": "+34.6%"}
    base = 4 + _h(c.id, "1y") % 70 / 10
    return {"1Y": f"+{base:.1f}%", "3Y": f"+{base * 2.6:.1f}%", "5Y": f"+{base * 4.2:.1f}%"}


def workbench(store: Store, user: User, clients, client, view_state: dict) -> str:
    if not clients:
        return '<section class="view active" id="view-workbench"><div class="card"><h2>No clients assigned</h2></div></section>'
    c = client
    rec = store.rec(c.id)
    title, rat = services.rationale_for(c)
    if not rec.rationale:
        rec_text = rat
    else:
        rec_text = rec.rationale
    drift_key, drift_val = headline_drift(c.weights, c.plan)
    n_attn = sum(1 for x in clients if x.kind == "review")
    n_appr = sum(1 for x in clients if x.kind == "approval")
    n_draft = sum(1 for x in clients if store.recs.get(x.id) and store.recs[x.id].status == "Draft")
    n_recs = sum(1 for x in clients if x.id in store.recs)
    n_consent = sum(1 for x in clients if not store.has_active_consent(x.id))
    st = rec.status
    step1 = {"Draft": ("Pending", "warn"), "RM reviewed": ("Reviewed", "good"), "Edited": ("Edits saved", "good"), "Rejected": ("Rejected", "bad"), "Monitor": ("Pending", "warn")}[st]
    pill = {"Draft": "Draft", "RM reviewed": "RM reviewed", "Edited": "Edited", "Rejected": "Rejected", "Monitor": "Draft"}[st]
    consent_req = rec.consent_request
    prop = store.proposals.get(c.id)
    pb = prop["body"] if prop else None
    if pb:
        title, rec_text = pb["title"], pb["summary"]
        ps = prop["status"]
        second = next((r.name for r in store.rms if r.id == prop["second_approver_rm_id"]), "compliance (no eligible senior adviser)")
        step1 = {"awaiting_rm": ("Pending", "warn"), "awaiting_second": (f"Awaiting second approver: {second}", "warn"), "approved": ("Approved", "good"),
                 "rejected": ("Rejected", "bad"), "edited": ("Edits saved", "good"), "digest": ("No decision needed", "muted"), "blocked": ("Blocked by a control", "bad")}.get(ps, step1)
        pill = {"awaiting_rm": "Awaiting RM", "awaiting_second": "Awaiting 2nd approver", "approved": "Approved", "rejected": "Rejected", "edited": "Edited", "digest": "Digest", "blocked": "Blocked"}.get(ps, pill)
    ai_chips, ai_block, step2 = "", "", '<span class="good">Passed* </span>'
    foot = "*Illustrative checks only. No real trade is placed. Execution remains disabled in this prototype."
    last_run = store.runs[0] if store.runs else None
    if pb:
        tn = {"1": "Tier 1 · Inform", "2": "Tier 2 · Review", "3": "Tier 3 · Significant"}[pb["tier"]]
        ai_chips = f'<div style="margin-top:9px"><span class="chip {"red" if pb["tier"] == "3" else ("amber" if pb["tier"] == "2" else "green")}">{tn}</span> <span class="muted" style="font-size:11px">{e(pb["approval_path"])}</span></div>'
        trades = "".join(f'<li>{t["direction"].capitalize()} {e(t["asset_class"])} {t["points"]:g} points (about ${t["usd"]:,.0f})</li>' for t in pb["trades"]) or "<li>No adjustment proposed</li>"
        alts = "".join(f'<li>Alternative: {e(a["name"])}</li>' for a in pb["alternatives"])
        news = "".join(f'<li><a href="{e(n["link"])}" target="_blank" rel="noopener noreferrer">{e(n["title"][:80])}</a> <span class="muted">({e(n["publisher"])})</span></li>' for n in pb["news_context"][:2])
        need = "".join(f"<li>{e(x)}</li>" for x in pb["requires_rm_confirmation"])
        ai_block = (f'<div style="background:#edf8f2;padding:11px;border-radius:8px;margin:12px 0;color:#23664c;font-size:11px"><b>Proposed adjustment (for RM review; nothing is executed)</b>'
                    f'<ul style="padding-left:17px;margin:6px 0 0">{trades}{alts}</ul></div>'
                    + (f'<div style="background:#fff3dc;padding:11px;border-radius:8px;margin:0 0 12px;color:#79520e;font-size:11px"><b>Needs the RM</b><ul style="padding-left:17px;margin:6px 0 0">{need}</ul></div>' if need else "")
                    + (f'<div class="muted" style="font-size:11px;margin-bottom:8px"><b>Relevant official headlines</b><ul style="padding-left:17px;margin:4px 0 0">{news}</ul></div>' if news else ""))
        failed = [ch for ch in pb["checks"] if ch["status"] == "fail"]
        step2 = f'<span class="{"bad" if failed else "good"}">{"Failed: " + e(failed[0]["name"]) if failed else "Passed"}</span>'
        foot = "Checks ran in the deterministic control layer. No real trade is placed or sent; execution remains disabled."
    elif last_run and last_run["status"] == "paused":
        from ..controls.gates import ABSTENTION
        title, rec_text = "Monitoring paused", ABSTENTION.get(last_run["paused_reason"], "Processing paused.")
        ai_chips = '<div style="margin-top:9px"><span class="chip red">Paused</span></div>'
        ai_block = f'<div style="background:#fff0f0;padding:11px;border-radius:8px;margin:12px 0;color:#75424a;font-size:11px"><b>{e(ABSTENTION.get(last_run["paused_reason"], "Processing paused."))}</b></div>'
        step2 = '<span class="warn">Paused</span>'
    elif last_run:
        ai_chips = f'<div style="margin-top:9px"><span class="muted" style="font-size:11px">Last run {e(last_run["started_at"])} UTC: {e(last_run["status"])}</span></div>'
    goals = "".join(f'<div class="goalrow"><div><strong>{e(g.name)}</strong><small>{e(g.detail)}</small></div><div class="progressbar"><span style="width:{g.progress}%"></span></div><b>{g.progress}%</b></div>' for g in c.goals)
    shares = holding_shares(c.holdings)
    hold_rows = "".join(f"<tr><td>{e(a)}</td><td>{e(cl)}</td><td>{money_m(v)}</td><td>{s:.1f}%</td></tr>" for a, cl, v, s in shares)
    alloc_rows = "".join(
        f'<div class="riskitem"><strong>{CLASS_LABEL[k]}</strong><span>{c.weights.get(k, 0)}%' +
        (f' <span class="{"bad" if c.weights.get(k, 0) - c.plan.get(k, 0) > 0 else "warn"}">({c.weights.get(k, 0) - c.plan.get(k, 0):+g} pp)</span>' if c.weights.get(k, 0) != c.plan.get(k, 0) else "") + "</span></div>"
        for k in ("EQ", "FI", "AL", "CA"))
    legend = ""
    for k, cls in (("EQ", ""), ("FI", "bonds"), ("AL", "alt"), ("CA", "cash")):
        dv = c.weights.get(k, 0) - c.plan.get(k, 0)
        arrow = ' <span class="bad">↑</span>' if dv >= 5 else ""
        legend += f'<div class="legendrow"><span class="dot {cls}"></span><span>{CLASS_LABEL[k]}</span><b>{c.weights.get(k, 0)}%{arrow}</b></div>'
    notes = [n for n in store.notes if n[0] == c.id]
    events_audit = [x for x in store.audit if x.client == c.name][:3]
    act_events = "".join(f'<div class="event"><div class="eventicon">✦</div><div><strong>{e(x.action)}</strong><p>{e(x.details)}</p></div><time>{e(x.ts.split(",")[0])}</time></div>' for x in events_audit)
    act_events += "".join(f'<div class="event"><div class="eventicon">▤</div><div><strong>Adviser note</strong><p>{e(n[1])}</p></div><time>{e(n[3].split(",")[0])}</time></div>' for n in notes[-3:])
    consent_ok = store.has_active_consent(c.id)
    perf = _perf(c)
    g0 = c.goals[0] if c.goals else None
    recs_tab = f'''<div class="risklist" style="margin-top:13px"><div class="riskitem"><div><strong>{e(title if abs(drift_val) >= .5 else "Review " + c.issue.lower())}</strong><small>{e(CLASS_LABEL[drift_key])} {c.weights.get(drift_key, 0)}% vs target {c.plan.get(drift_key, 0)}% · {e(st if st != "Monitor" else "Monitor")}</small></div><button class="btn small primary" onclick="openReview()">Review</button></div><div class="riskitem"><div><strong>Market event impact review</strong><small>Market and event feeds are not connected yet; this item will use live data in a later phase</small></div><button class="btn small" onclick="act('detail',{{what:'market'}})">Details</button></div><div class="riskitem"><div><strong>{e(g0.name if g0 else "Goal")} check-in</strong><small>Goal is approximately {g0.progress if g0 else 0}% on track (illustrative)</small></div><button class="btn small" onclick="act('detail',{{what:'goal'}})">Details</button></div></div>'''
    sub = view_state.get("subtab", "overview")
    def S(n): return " active" if sub == n else ""
    def T(n, label): return f'<button class="{"active" if sub == n else ""}" onclick="setSubtab(\'{n}\',this)">{label}</button>'
    queue = _queue_rows(clients, c.id)
    kinds_all = len(clients)
    return f'''<section class="view active" id="view-workbench">
  <div class="pagehead"><div><div class="eyebrow">Relationship Manager Workspace</div><h1>Good afternoon, {e(user.name.split()[0])}</h1><div class="sub">Your client priorities, AI-assisted recommendations and approvals in one place.</div></div><div class="actions"><button class="btn" onclick="act('export_queue')">↓ Export queue</button><button class="btn primary" onclick="openAsk()">✦ Ask Atlas AI</button></div></div>
  <div class="metrics">
    <div class="metric"><div class="bubble" style="background:#fff0f0">♧</div><div><strong>{n_attn}</strong><span>Clients need attention</span></div></div>
    <div class="metric"><div class="bubble" style="background:#fff3dc">◷</div><div><strong id="approvalCount">{n_draft}</strong><span>Awaiting your approval</span></div></div>
    <div class="metric"><div class="bubble">✦</div><div><strong>{n_recs}</strong><span>AI recommendations</span></div></div>
    <div class="metric"><div class="bubble" style="background:#e8f7ef">▤</div><div><strong id="consentCount">{n_consent}</strong><span>Consent pending</span></div></div>
    <div class="metric"><div class="bubble" style="background:#e8f7ef">✓</div><div><strong>0</strong><span>Open compliance issues</span></div></div>
  </div>
  <div class="workgrid">
    <section class="card">
      <div class="cardhead"><h2>Client Queue</h2><button class="btn small" onclick="toggleFilters()">⚑ Filters</button></div>
      <div class="clientfilters" id="queueFilters"><button class="chip selected" onclick="filterQueue('all',this)">All ({kinds_all})</button><button class="chip" onclick="filterQueue('review',this)">Needs attention ({n_attn})</button><button class="chip" onclick="filterQueue('approval',this)">Awaiting approval ({n_appr})</button></div>
      <div class="field hidden" id="filterSearch"><input id="queueSearch" placeholder="Filter by client name…" oninput="searchQueue()"></div>
      <div class="queue" id="queue">{queue}</div>
      <div class="footnote">Demo queue · fictional client data · prioritisation is illustrative.</div>
    </section>
    <section class="detail">
      <div class="card">
        <div class="cardhead" style="margin-bottom:14px"><div class="clienthero"><div class="avatar" id="heroAvatar">{initials(c.name)}</div><div><h2 id="heroName">{e(c.name)} <span class="tier">{c.tier}</span></h2><div class="meta">Client since {c.since} &nbsp; | &nbsp; AUM <b id="heroAum">{money_m(c.aum_musd)}</b></div></div></div><div class="actions"><button class="btn small" onclick="openCrm()">View in CRM ↗</button><button class="btn primary small" data-access="rm" onclick="setView('clientview')">Client View →</button></div></div>
        <div class="section-tabs">{T("overview","Overview")}{T("recommendations","AI Recommendations (3)")}{T("portfolio","Portfolio")}{T("goals","Goals")}{T("risk","Risk & Suitability")}{T("activity","Activity & Notes")}</div>
        <div class="subview{S("overview")}" id="sub-overview"><div class="summarygrid" style="margin-top:13px">
          <div class="summary"><div class="label">Portfolio value</div><strong id="summaryAum">{money_m(c.aum_musd)}</strong><small class="good">↑ {6.3 if c.name == "Rajesh Menon" else 3 + _h(c.id, "q") % 70 / 10:.1f}% vs. 3 months ago</small></div>
          <div class="summary"><div class="label">Risk profile</div><strong>{e(c.risk_profile)}</strong><small>Last reviewed {c.last_reviewed}</small></div>
          <div class="summary"><div class="label">Key goals</div><strong>{len(c.goals)} active</strong><small>{e(", ".join(g.short or g.name.split(" ")[0] for g in c.goals)[:44])}</small></div>
          <div class="summary"><div class="label">Next meeting</div><strong>{c.next_meeting}</strong><small>Quarterly portfolio review</small></div></div></div>
        <div class="subview{S("recommendations")}" id="sub-recommendations">{recs_tab}</div>
        <div class="subview{S("portfolio")}" id="sub-portfolio"><div class="twocol" style="margin-top:13px"><div class="chartcard"><div class="charttitle">Current vs target allocation</div><div class="risklist">{alloc_rows}</div></div><div class="chartcard"><div class="charttitle">Holdings & history</div><div class="tablewrap"><table><thead><tr><th>Asset</th><th>Class</th><th>Value</th><th>Share</th></tr></thead><tbody>{hold_rows}</tbody></table></div><button class="btn small" style="margin-top:10px" onclick="openHistory()">View transaction history</button></div></div></div>
        <div class="subview{S("goals")}" id="sub-goals"><div style="margin-top:13px">{goals}</div></div>
        <div class="subview{S("risk")}" id="sub-risk"><div class="risklist" style="margin-top:13px"><div class="riskitem"><div><strong>Risk profile fit</strong><small>{e(c.risk_profile)} risk profile · long-term horizon</small></div><span class="pill">Pass</span></div><div class="riskitem"><div><strong>Concentration check</strong><small>Single issuer and sector exposure checks</small></div><span class="pill">Pass</span></div><div class="riskitem"><div><strong>Suitability assessment</strong><small>Reconfirm profile before recommendation is finalised</small></div><span class="pill pending">Review required</span></div><div class="riskitem"><div><strong>Client consent</strong><small>{"Monitoring consent on file (version " + CONSENT_VERSION + "). Consent for execution is separate." if consent_ok else "No active monitoring consent: processing paused until consent is captured"}</small></div><span class="pill {"" if consent_ok else "pending"}">{"On file" if consent_ok else "Pending"}</span></div></div></div>
        <div class="subview{S("activity")}" id="sub-activity"><div class="events" style="margin-top:10px">{act_events or '<div class="muted" style="padding:10px 0">No activity recorded yet.</div>'}</div><button class="btn small" style="margin-top:10px" onclick="openNotes()">＋ Add adviser note</button></div>
      </div>
      <div class="twocol">
        <div class="chartcard">
          <div class="charttitle">Portfolio Allocation <span class="muted" style="font-size:11px;font-weight:500">{e(_alloc_text(c))}</span></div>
          <div class="allocation"><div class="donut" style="{_donut_style(c)}"><div class="donutlabel" id="donutValue">{money_m(c.aum_musd)}<small>Total portfolio</small></div></div><div class="legend">{legend}</div></div>
        </div>
        <div class="chartcard">
          <div class="charttitle">Performance (illustrative) <div class="actions"><button class="chip selected" onclick="setPeriod('1Y',this)">1Y</button><button class="chip" onclick="setPeriod('3Y',this)">3Y</button><button class="chip" onclick="setPeriod('5Y',this)">5Y</button></div></div>
          <div style="display:flex;gap:15px;font-size:11px;margin-bottom:8px"><span>● Portfolio <b class="good" id="performanceValue" data-perf='{e(str(perf).replace("'", '"'))}'>{perf["1Y"]}</b></span><span style="color:#8eb6ec">● Benchmark +6.1%</span></div>
          <svg viewBox="0 0 440 125" width="100%" role="img" aria-label="Illustrative portfolio performance line chart"><g stroke="#e7edf4" stroke-width="1"><path d="M25 20H430 M25 50H430 M25 80H430 M25 110H430"/></g><g fill="#73839a" font-size="9"><text x="1" y="23">20%</text><text x="1" y="53">10%</text><text x="8" y="83">0%</text><text x="1" y="113">-10%</text></g><path d="M25 93 L42 92 L58 95 L75 85 L91 88 L107 81 L124 80 L140 74 L157 78 L173 66 L190 70 L206 61 L223 67 L239 55 L256 60 L272 51 L289 54 L305 42 L322 48 L338 38 L355 44 L371 33 L388 39 L405 28 L430 31" fill="none" stroke="#174f96" stroke-width="2.6" stroke-linecap="round"/><path d="M25 99 L42 98 L58 96 L75 94 L91 93 L107 91 L124 90 L140 87 L157 88 L173 82 L190 84 L206 80 L223 82 L239 76 L256 77 L272 72 L289 74 L305 69 L322 70 L338 65 L355 66 L371 62 L388 61 L405 58 L430 56" fill="none" stroke="#9fc2f2" stroke-width="2" stroke-linecap="round"/><text x="25" y="123" fill="#73839a" font-size="9">Apr</text><text x="220" y="123" fill="#73839a" font-size="9">Oct</text><text x="405" y="123" fill="#73839a" font-size="9">Apr</text></svg>
        </div>
      </div>
      <div class="twocol">
        <div class="chartcard"><div class="charttitle">Recent Events & Insights <button class="btn small" onclick="setSubtab('activity',document.querySelectorAll('.section-tabs button')[5])">See all</button></div><div class="events">
          <div class="event"><div class="eventicon" style="background:#fff0f0">♙</div><div><strong>Portfolio drift</strong><p>{e(CLASS_LABEL[drift_key])} allocation is {c.weights.get(drift_key, 0)}% vs. {c.plan.get(drift_key, 0)}% target.</p></div><time>2 days ago</time></div>
          <div class="event"><div class="eventicon">▥</div><div><strong>Market update</strong><p>{_market_line(store)}</p></div><time>{_market_time(store)}</time></div>
          <div class="event"><div class="eventicon" style="background:#e8f7ef">⌂</div><div><strong>Goal milestone</strong><p>{e(g0.name if g0 else "Goal")} is approximately {g0.progress if g0 else 0}% on track (illustrative).</p></div><time>5 days ago</time></div></div></div>
        <div class="chartcard">
          <div class="recommendhead"><span class="chip selected">✦ AI Recommendation</span><span class="pill pending" id="draftStatus">{pill}</span></div>
          <h3 style="margin:11px 0 5px">{e(title)}</h3>
          <p class="muted" style="font-size:12px;margin:0">{e(rec_text)}</p>
          {ai_chips}
          {ai_block or '<div style="background:#edf8f2;padding:11px;border-radius:8px;margin:12px 0;color:#23664c;font-size:11px"><b>Potential outcome (illustrative)</b><ul style="padding-left:17px;margin:6px 0 0"><li>Move closer to target allocation</li><li>Reduce unintended concentration in equity risk</li><li>Keep the long-term plan under review</li></ul><br>No monitoring run yet: press Run monitoring check for an evidence-based proposal.</div>'}
          <div class="actions"><button class="btn primary" onclick="openReview()">✎ Review & edit</button><button class="btn" onclick="openClientMessage()">▢ Draft client message</button><button class="btn" onclick="runAgent()">↻ Run monitoring check</button></div>
          <div class="workflow"><div class="step current"><b>1 · RM review</b><span class="{step1[1]}" id="step1status">{step1[0]}</span></div><div class="step"><b>2 · Policy checks</b>{step2}</div><div class="step"><b>3 · Client consent</b><span class="warn" id="step3status">{e(consent_req if consent_req != "Not requested" else "Pending")}</span></div><div class="step"><b>4 · Execution</b><span class="muted">Locked</span></div></div>
          <div class="footnote">{foot}</div>
        </div>
      </div>
    </section>
  </div>
</section>'''


def clientview(store: Store, user: User, c) -> str:
    rec = store.rec(c.id)
    cs = rec.consent_request if rec.consent_request != "Not requested" else "Not requested"
    pref = c.contact_pref
    opts = "".join(f'<option{" selected" if o == pref else ""}>{o}</option>' for o in ("Secure client portal", "Email (approved channel)", "Discuss in next meeting"))
    if pref not in ("Secure client portal", "Email (approved channel)", "Discuss in next meeting"):
        opts = f"<option selected>{e(pref)}</option>" + opts
    first = c.name.split()[0]
    return f'''<section class="view" id="view-clientview">
  <div class="pagehead"><div><div class="eyebrow">RM-gated client experience</div><h1>Client View</h1><div class="sub">Preview the information a client would see after the RM reviews and authorises sharing.</div></div><div class="actions"><button class="btn" onclick="setView('workbench')">← Back to Workbench</button><button class="btn primary" onclick="openClientMessage()">Prepare client update</button></div></div>
  <div class="two-panel">
    <div class="card"><div class="cardhead"><div><h2>Client preview · {e(c.name)}</h2><div class="sub">Illustrative client-facing summary</div></div><span class="pill pending" id="clientShareStatus">{e(rec.client_message)}</span></div>
      <div class="clientpreview"><div class="brandmini">ATLAS <span style="font-family:system-ui;font-size:9px;letter-spacing:1px">WEALTH MANAGEMENT</span></div><h3>Your portfolio, clearly explained.</h3><p>Hello {e(first)}, here's a summary of your portfolio and a recommendation for your review.</p><div class="summarygrid"><div class="summary"><div class="label">Portfolio value</div><strong>{money_m(c.aum_musd)}</strong><small class="good">Illustrative</small></div><div class="summary"><div class="label">Risk profile</div><strong>{e(c.risk_profile)}</strong><small>As last recorded</small></div></div><div class="callout"><b>Recommended review: portfolio allocation</b><p>Your allocation differs from your target. Your adviser would like to discuss whether an adjustment is appropriate for your financial goals.</p><button class="btn small blue" onclick="openClientMessage()">View recommendation details →</button></div><p>Any investment action would be discussed with you first and would require the applicable consent and approvals.</p></div>
      <div class="actions" style="margin-top:14px"><button class="btn" onclick="openClientMessage()">Edit client message</button><button class="btn primary" onclick="act('request_consent')">Record consent request</button></div>
    </div>
    <div class="card"><div class="cardhead"><h2>Consent & preferences</h2><span class="chip amber">RM-gated</span></div><div class="checkrow"><span class="checkmark">✓</span><span>Client identity and profile available</span><span class="right pass">Available</span></div><div class="checkrow"><span class="checkmark">✓</span><span>Communication preference</span><span class="right">{e(pref[:28])}</span></div><div class="checkrow"><span class="checkmark pending">!</span><span>Consent for proposed portfolio action</span><span class="right pending" id="consentStatus">{e(cs)}</span></div><div class="notice">Consent to receive a recommendation is not the same as consent or authority to execute a trade.</div><div class="field"><label>Preferred communication</label><select id="commPreference">{opts}</select></div><button class="btn" onclick="act('save_pref',{{pref:document.getElementById('commPreference').value}})">Save preference</button></div>
  </div>
</section>'''


def audit_table(rows) -> str:
    return "".join(
        f'<tr data-action="{x.kind}"><td>{e(x.ts)}</td><td>{e(x.client)}</td><td>{e(x.action)}</td><td>{e(x.actor)}</td><td class="details">{e(x.details)}</td><td><span class="pill {"pending" if x.status in ("Review", "Pending", "Awaiting client") else ("red" if x.status == "Rejected" else "")}">{e(x.status)}</span></td></tr>'
        for x in rows)


def compliance(store: Store, user: User, c) -> str:
    rec = store.rec(c.id)
    pending_actions = sum(1 for r in store.recs.values() if r.status == "Draft")
    appr = {"Draft": ("Pending", "pending"), "Monitor": ("Pending", "pending"), "RM reviewed": ("Reviewed", "pass"), "Edited": ("Edits saved", "pending"), "Rejected": ("Rejected", "bad")}[rec.status]
    consent_state = rec.consent_request if rec.consent_request != "Not requested" else "Pending"
    rm = next((r.name for r in store.rms if r.id == c.rm_id), "—")
    prop = store.proposals.get(c.id)
    second_txt = '<span class="muted">Not required in this illustrative Tier 1 flow; policy-dependent</span>'
    if prop and prop["tier"] == "3":
        sname = next((r.name for r in store.rms if r.id == prop["second_approver_rm_id"]), "compliance (no eligible senior adviser)")
        second_txt = f'<span class="warn">Required (Tier 3): second approver {e(sname)}</span>' if prop["status"] in ("awaiting_rm", "awaiting_second") else f'<span class="good">{e(prop["status"].replace("_", " ").capitalize())}{" by " + e(prop["second_approver"]) if prop["second_approver"] else ""}</span>'
    return f'''<section class="view" id="view-compliance">
  <div class="pagehead"><div><div class="eyebrow">Oversight & controls</div><h1>Compliance View</h1><div class="sub">Review the policy checks, consent state, approvals and audit history behind each AI-assisted action.</div></div><div class="actions"><button class="btn" onclick="act('export_audit')">↓ Export audit log</button><button class="btn primary" onclick="openReview()">Review active recommendation</button></div></div>
  <div class="metrics"><div class="metric"><div class="bubble" style="background:#e8f7ef">✓</div><div><strong>0</strong><span>Open control exceptions</span></div></div><div class="metric"><div class="bubble" style="background:#fff3dc">◷</div><div><strong id="compPending">{pending_actions}</strong><span>Pending actions</span></div></div><div class="metric"><div class="bubble">▤</div><div><strong id="auditCount">{store.audit_total}</strong><span>Audit events</span></div></div><div class="metric"><div class="bubble">♧</div><div><strong>Tier 1</strong><span>Client service tier</span></div></div><div class="metric"><div class="bubble">🔒</div><div><strong>Read-only</strong><span>Legacy CRM connection</span></div></div></div>
  <div class="two-panel">
    <div class="card"><div class="cardhead"><h2>Policy, Suitability & Consent Checks</h2><span class="chip green">Illustrative</span></div>
      <div class="checkrow"><span class="checkmark">✓</span><span>Recommendation within recorded risk profile</span><span class="right pass">Pass*</span></div><div class="checkrow"><span class="checkmark">✓</span><span>Investment objective alignment reviewed</span><span class="right pass">Pass*</span></div><div class="checkrow"><span class="checkmark">✓</span><span>Product eligibility and tier rules checked</span><span class="right pass">Pass*</span></div><div class="checkrow"><span class="checkmark">✓</span><span>Concentration and exposure limits checked</span><span class="right pass">Pass*</span></div><div class="checkrow"><span class="checkmark pending">!</span><span>Tax and transaction-cost review</span><span class="right pending">Adviser review</span></div><div class="checkrow"><span class="checkmark pending">!</span><span>Client consent for execution</span><span class="right pending" id="complianceConsent">{e(consent_state)}</span></div><div class="checkrow"><span class="checkmark pending">!</span><span>RM review / approval</span><span class="right {appr[1]}" id="complianceApproval">{appr[0]}</span></div><div class="notice">*Statuses are not a real suitability determination. Production checks must be implemented, tested and approved by the firm's control functions. Active item: {e(c.name)}.</div>
    </div>
    <div class="card"><div class="cardhead"><h2>Approval Workflow</h2><span class="tier">Tier 1</span></div><div class="step current" style="margin-bottom:8px"><b>1 · RM review</b><span id="workflowRm" class="{"bad" if rec.status == "Rejected" else ("good" if rec.status != "Draft" else "warn")}">{e(rec.status + " — " + rm if rec.status != "Draft" else "Pending — " + rm)}</span></div><div class="step" style="margin-bottom:8px"><b>2 · Second approver</b>{second_txt}</div><div class="step" style="margin-bottom:8px"><b>3 · Client consent</b><span id="workflowConsent" class="warn">{e(consent_state)}</span></div><div class="step"><b>4 · Execution gate</b><span class="muted">Locked; no trading integration</span></div><div class="calloutnote">Any override should require a reason, authorised role, timestamp and audit record. This prototype does not execute orders.</div></div>
  </div>
  <div class="card" style="margin-top:15px"><div class="cardhead"><h2>Audit Trail</h2><span class="muted" style="font-size:11px">Fictional events · append-only</span></div><div class="auditfilters"><input id="auditSearch" placeholder="Search client or action…" oninput="filterAudit()"><select id="auditAction" onchange="filterAudit()"><option value="all">All actions</option><option value="AI">AI recommendation</option><option value="RM">RM action</option><option value="Consent">Consent</option><option value="Policy">Policy</option><option value="System">System</option></select><button class="btn small" onclick="filterAudit()">Apply filters</button></div><div class="tablewrap"><table id="auditTable"><thead><tr><th>Date & time</th><th>Client</th><th>Action</th><th>Actor</th><th>Details</th><th>Status</th></tr></thead><tbody id="auditBody">{audit_table(store.audit[:200])}</tbody></table></div><div class="footnote">Times are UTC. The audit log is append-only in the database and is not connected to a production compliance system.</div></div>
  <div class="card" style="margin-top:15px"><div class="cardhead"><h2>AI Orchestration & Data Flow</h2><span class="chip selected">Architecture overview</span></div><div class="archgrid"><div class="archnode"><h3>01 · SOURCES</h3><ul><li>Legacy CRM · read-only</li><li>Portfolio records</li><li>Market & event feeds</li><li>Compliance rules</li><li>Adviser notes</li></ul></div><div class="archnode"><h3>02 · DATA FOUNDATION</h3><ul><li>Client context model</li><li>Holdings & history</li><li>Market/event data</li><li>Consent & preferences</li></ul></div><div class="archnode"><h3>03 · AI LAYER</h3><ul><li>Orchestrator</li><li>Event interpreter</li><li>Notes signal extractor</li><li>Recommendation drafter</li></ul></div><div class="archnode"><h3>04 · DETERMINISTIC ENGINES</h3><ul><li>Portfolio analytics</li><li>Risk & scenario engine</li><li>Goal projection</li><li>Rebalance proposal</li></ul></div><div class="archnode"><h3>05 · RM WORKBENCH</h3><ul><li>Client queue</li><li>Review & edit</li><li>Approval workflow</li><li>Client view (gated)</li></ul></div></div><div class="calloutnote">Control layer spans all stages: policy and suitability checks · consent verification · tiered approvals · output guardrails · audit logging. AI drafts and explains; deterministic engines calculate; authorised humans and workflows govern action.</div></div>
</section>'''


# ------------------------------------------------------------------ simple pages
def home(store, user, clients) -> str:
    n_attn = sum(1 for c in clients if c.kind == "review")
    n_draft = sum(1 for c in clients if store.recs.get(c.id) and store.recs[c.id].status == "Draft")
    first = next((c for c in clients if store.recs.get(c.id) and store.recs[c.id].status == "Draft"), clients[0] if clients else None)
    line = f"{e(first.name)} · {e(first.issue)} · RM review required." if first else "No clients assigned."
    return f'''<section class="view" id="view-home"><div class="pagehead"><div><div class="eyebrow">Overview</div><h1>Relationship Manager Home</h1><div class="sub">A prioritised summary of your workday.</div></div><button class="btn primary" onclick="setView('workbench')">Open RM Workbench →</button></div><div class="metrics"><div class="metric"><div class="bubble">♙</div><div><strong>{len(clients)}</strong><span>Assigned clients</span></div></div><div class="metric"><div class="bubble" style="background:#fff0f0">♧</div><div><strong>{n_attn}</strong><span>Need attention</span></div></div><div class="metric"><div class="bubble" style="background:#fff3dc">◷</div><div><strong>{n_draft}</strong><span>Pending approvals</span></div></div></div><div class="card"><h2>Start with your highest-priority client</h2><p class="muted">{line}</p><button class="btn primary" onclick="setView('workbench')">Open client queue</button></div></section>'''


def clients_page(clients) -> str:
    rows = "".join(f'<div class="riskitem"><div><strong>{e(c.name)}</strong><small>{money_m(c.aum_musd)} · {e(c.issue)}</small></div><button class="btn small primary" onclick="openClientFromBook(\'{c.id}\')">Open portfolio →</button></div>' for c in clients)
    return f'''<section class="view" id="view-clients"><div class="pagehead"><div><div class="eyebrow">Client book</div><h1>Clients</h1><div class="sub">Choose a client to open their portfolio overview in the RM Workbench. These are fictional demo records.</div></div><button class="btn" onclick="setView('workbench')">Open RM Workbench</button></div><div class="card"><div class="actions" style="margin-bottom:14px"><input id="clientBookSearch" placeholder="Search client name…" oninput="filterClientBook()" style="max-width:360px;width:100%"><span class="pill">{len(clients)} demo clients</span></div><div id="clientBookList" class="risklist">{rows}</div><p class="muted" id="clientBookEmpty" style="display:none">No clients match your search.</p></div></section>'''


def insights(store, clients) -> str:
    items = [(c, store.recs[c.id]) for c in clients if c.id in store.recs and store.recs[c.id].status in ("Draft", "Edited", "RM reviewed")][:6]
    rows = "".join(f'<div class="riskitem"><div><strong>{e(r.title)}</strong><small>{e(c.name)} · {e(services.rationale_for(c)[1][:86])}…</small></div><span class="pill {"pending" if r.status == "Draft" else ""}">{"Review" if r.status == "Draft" else e(r.status)}</span></div>' for c, r in items)
    return f'''<section class="view" id="view-insights"><div class="pagehead"><div><div class="eyebrow">AI intelligence</div><h1>AI Insights</h1><div class="sub">Signals are prioritised for adviser review, not automatic execution.</div></div><button class="btn primary" onclick="setView('workbench')">Review recommendations</button></div><div class="card">{rows or '<p class="muted">No open signals.</p>'}</div></section>'''


def _fmt_dt(dt) -> str:
    return dt.strftime("%d %b %H:%M") + " UTC" if dt else "—"


_FRESH = {"fresh": ("Fresh", ""), "market_closed": ("Market closed · last close", ""), "stale": ("Stale · not current", "pending"),
          "unavailable": ("Unavailable", "red")}


def _market_line(store) -> str:
    q = store.market_by_symbol.get("^GSPC")
    if not q or not q["available"]:
        return "Market data has not been retrieved yet; no market statement is made."
    if q["freshness"] == "stale":
        return f"Market data is stale ({e(q['age'])} old); not used for current-market statements."
    if q["freshness"] == "unavailable" or q["change_pct"] is None:
        return "Market data is unavailable."
    state = "last close" if q["freshness"] == "market_closed" else "latest"
    return f"S&P 500 {q['change_pct']:+.2f}% ({state}, {_fmt_dt(q['market_time'])}, source: {e(q['provider'].split(' (')[0])})."


def _market_time(store) -> str:
    q = store.market_by_symbol.get("^GSPC")
    return q["age"] + " ago" if q and q["available"] else "—"


def _quote_row(q: dict) -> str:
    if not q["available"]:
        return f'<tr><td><b>{e(q["name"])}</b><br><span class="muted">{e(q["symbol"])}</span></td><td colspan="3">No data retrieved yet.</td><td><span class="pill red">Unavailable</span></td><td>—</td></tr>'
    label, cls = _FRESH[q["freshness"]]
    unit = "%" if q["kind"] == "yield" else ""
    price = f'{q["price"]:,.3f}{unit}' if q["kind"] in ("yield", "fx") else f'{q["price"]:,.2f}'
    if q["change_pct"] is None:
        ch = "—"
    elif q["kind"] == "yield":
        ch = f'<span class="{"good" if q["change_abs"] >= 0 else "bad"}">{q["change_abs"]:+.3f} pts</span>'
    else:
        ch = f'<span class="{"good" if q["change_pct"] >= 0 else "bad"}">{q["change_pct"]:+.2f}%</span>'
    stale_note = f' <span class="muted">({e(q["age"])} old)</span>' if q["freshness"] == "stale" else ""
    day = " · daily data" if q["day_only"] else ""
    return (f'<tr><td><b>{e(q["name"])}</b><br><span class="muted">{e(q["symbol"])} · {"percent" if q["kind"] == "yield" else q["currency"]}</span></td><td>{price}</td><td>{ch}</td>'
            f'<td>{_fmt_dt(q["market_time"])}<br><span class="muted">retrieved {_fmt_dt(q["retrieved_at"])}</span></td>'
            f'<td><span class="pill {cls}">{label}</span>{stale_note}</td><td><a href="{e(q["source_url"])}" target="_blank" rel="noopener noreferrer">{e(q["provider"])}</a><span class="muted">{day}</span></td></tr>')


def _news_row(n) -> str:
    when = _fmt_dt(n.published_at) if n.published_at else "date not given"
    if n.quarantined:
        return (f'<div class="riskitem"><div><strong>Item quarantined</strong><small>{e(n.publisher)} · {when} · the text contained instruction-like content and was not displayed or sent to any model. '
                f'Compliance has been alerted. <a href="{e(n.link)}" target="_blank" rel="noopener noreferrer">Open the source</a></small></div><span class="pill red">Quarantined</span></div>')
    return (f'<div class="riskitem"><div><strong><a href="{e(n.link)}" target="_blank" rel="noopener noreferrer">{e(n.title)}</a></strong>'
            f'<small>{e(n.publisher)} · published {when} · retrieved {_fmt_dt(n.retrieved_at)}</small></div><span class="pill">Official source</span></div>')


def research(store) -> str:
    rows = "".join(_quote_row(q) for q in store.market)
    news = "".join(_news_row(n) for n in store.news) or '<p class="muted">No headlines retrieved yet. Use Refresh data.</p>'
    live = [s for s in store.sources.values() if s["mode"] == "live"]
    srcs = "".join(f'<div class="riskitem"><div><strong>{e(s["name"])}</strong><small>{e(_source_state(s)[1])}</small></div>{_source_state(s)[0]}</div>' for s in live)
    return f'''<section class="view" id="view-research"><div class="pagehead"><div><div class="eyebrow">Market context</div><h1>Research & Market</h1><div class="sub">Market feeds are a data input, not an instruction to trade.</div></div><button class="btn primary" onclick="act('market_refresh')">↻ Refresh data</button></div>
<div class="card" style="margin-bottom:15px"><div class="cardhead"><div><h2>Market snapshot</h2><div class="sub">Real prices with exchange timestamps. Nothing is shown as current unless it passed the freshness check.</div></div><span class="pill">Live data</span></div><div class="tablewrap"><table><thead><tr><th>Instrument</th><th>Last</th><th>Change</th><th>As of (UTC)</th><th>Status</th><th>Source</th></tr></thead><tbody>{rows}</tbody></table></div><div class="footnote">Change = price minus the previous session close, computed by the platform. Prices marked stale or unavailable are never used for current-market statements. Yahoo Finance is an unofficial source; see Data sources below.</div></div>
<div class="twocol"><div class="card"><div class="cardhead"><h2>Headlines from official sources</h2><span class="pill">Fed · SEC · BLS</span></div><div class="risklist">{news}</div><div class="footnote">Headlines are information, not instructions. Each item links to its publisher; a publication time is shown where the feed gives one.</div></div>
<div class="card"><div class="cardhead"><h2>Data sources status</h2><span class="pill">Live</span></div><div class="risklist">{srcs}</div></div></div>
<div class="card" style="margin-top:15px"><h2>Market event interpreter</h2><p class="muted">When a market or news event is relevant to a client, the system will link it to the client's holdings, run deterministic scenarios and draft an explanation for adviser review.</p><div class="calloutnote">Interpretation and scenarios are added in the next build phase. Until then this page only reports retrieved facts with their sources and ages; it makes no forecasts and no recommendations.</div></div></section>'''


def _source_detail(s: dict) -> str:
    d = _source_state(s)[1]
    return f'<div class="muted" style="font-size:11px;margin-top:3px;max-width:260px;white-space:normal">{e(d)}</div>' if d and s["mode"] == "live" else ""


def _source_state(s: dict):
    """(pill html, detail text) for a registry row."""
    from .. import config
    if s["mode"] != "live":
        return '<span class="pill">Connected · Simulated</span>', ""
    if s["id"] == "alphavantage" and not config.ALPHAVANTAGE_API_KEY:
        return '<span class="pill pending">Not configured</span>', "Needs a free API key (ALPHAVANTAGE_API_KEY). Not used until configured."
    if s["failures"] and s["last_error"]:
        ok = f" Last success {s['last_success']} UTC." if s["last_success"] else " No successful retrieval yet."
        return '<span class="pill red">Error</span>', f"{s['last_error'][:120]}.{ok}"
    if s["last_success"]:
        return f'<span class="pill">Live · last OK {e(s["last_success"])} UTC</span>', f"Last successful retrieval {s['last_success']} UTC."
    return '<span class="pill pending">Live · not yet retrieved</span>', "No retrieval yet. Open Research & Market and press Refresh."


def tasks(store, clients) -> str:
    rows = ""
    for c in clients:
        r = store.recs.get(c.id)
        if r and r.status == "Draft":
            rows += f'<div class="riskitem"><div><strong>Review {e(c.name)} recommendation</strong><small>{e(r.title)} · Tier 1 · Draft</small></div><button class="btn small primary" onclick="selectClient(\'{c.id}\',true)">Review</button></div>'
    for c in clients:
        if not store.has_active_consent(c.id):
            rows += f'<div class="riskitem"><div><strong>Confirm consent status: {e(c.name)}</strong><small>Monitoring is paused until consent is on file</small></div><button class="btn small" data-access="rm" onclick="selectClient(\'{c.id}\',false,\'clientview\')">Open Client View</button></div>'
    return f'''<section class="view" id="view-tasks"><div class="pagehead"><div><div class="eyebrow">Tasks & approvals</div><h1>Tasks</h1><div class="sub">Actions awaiting adviser attention.</div></div></div><div class="card">{rows or '<p class="muted">No open tasks.</p>'}</div></section>'''


def reports() -> str:
    return '''<section class="view" id="view-reports"><div class="pagehead"><div><div class="eyebrow">Reporting</div><h1>Reports</h1><div class="sub">Prepare review summaries with source links and an audit trail.</div></div><button class="btn primary" onclick="act('report',{template:'Portfolio review report'})">Generate review report</button></div><div class="card"><h2>Available report templates</h2><div class="riskitem"><div><strong>Quarterly portfolio review</strong><small>Holdings, performance, allocation drift, goals and adviser commentary</small></div><button class="btn small" onclick="act('report',{template:'Quarterly portfolio review'})">Generate</button></div><div class="riskitem"><div><strong>AI recommendation rationale</strong><small>Signals, calculations, assumptions, checks and approval history</small></div><button class="btn small" onclick="act('report',{template:'AI recommendation rationale'})">Generate</button></div><div class="footnote">Reports download as Markdown for the client currently selected in the RM Workbench.</div></div></section>'''


# ------------------------------------------------------------------ settings & scheduler
def settings(store: Store, user: User, pick_clients, saved: dict | None, perm_rm_id: str = "") -> str:
    is_admin = user.role == "Admin"
    cfg = saved or dict(name="Portfolio monitoring & review", frequency="weekly", time="08:30", days=["Mon", "Wed", "Fri"], month_day="1",
                        scopes=list(services.SCOPES), client_scope="All assigned clients", enabled=True, clients=[])
    role_tag = "ADMIN CONFIGURATION" if is_admin else "RM SCHEDULING SETTINGS"
    perm_rm = next((r for r in store.rms if r.id == perm_rm_id), store.rms[0])
    admin_panel = ""
    if is_admin:
        p = store.perms[perm_rm.id]
        opts = "".join(f"<option{' selected' if r.id == perm_rm.id else ''}>{r.name}</option>" for r in store.rms)
        tiers = "".join(f"<option{' selected' if t == p['approval'] else ''}>{t}</option>" for t in ("Tier 1", "Tier 2", "Tier 3"))
        admin_panel = f'''<div class="card" id="adminPermissions" style="margin-bottom:15px"><div class="cardhead"><h2>Admin controls · RM permissions</h2><span class="pill">Admin only</span></div><p class="muted">Choose which relationship managers may schedule agent workflows and configure approval limits.</p><div class="field"><label for="permissionRM">Relationship Manager</label><select id="permissionRM" style="width:100%" onchange="act('load_perms',{{rm:this.value}})">{opts}</select></div><div class="field"><label><input type="checkbox" id="permSchedule" {"checked" if p["schedule"] else ""}> Allow this RM to create and edit workflow schedules</label></div><div class="field"><label><input type="checkbox" id="permAllClients" {"checked" if p["all_clients"] else ""}> Allow scheduling for all clients (otherwise assigned clients only)</label></div><div class="field"><label for="permApproval">Approval authority</label><select id="permApproval" style="width:100%">{tiers}</select></div><div class="field"><label><input type="checkbox" id="permOverride" {"checked" if p["override"] else ""}> Allow policy override requests (mandatory controls cannot be bypassed)</label></div><button class="btn primary" onclick="saveRMAccess()">Save RM permissions</button><div class="calloutnote" id="permissionSummary">{perm_rm.name} · Scheduling {"enabled" if p["schedule"] else "disabled"} · {"All clients" if p["all_clients"] else "Assigned clients only"} · {p["approval"]} routing.</div></div>'''
    # data sources
    rows = ""
    for s in store.sources.values():
        if not s["enabled"]:
            continue
        prim = ' <span class="pill" style="margin-left:6px">Primary client source</span>' if s["primary"] else ""
        btn = f'<button class="btn small" onclick="act(\'source\',{{id:\'{s["id"]}\',on:false}})">Remove</button>' if is_admin else '<span class="muted">View only</span>'
        rows += f'<tr data-source="{s["id"]}"><td><b>{e(s["label"])}</b>{prim}</td><td>{e(s["reads"])}</td><td>{_source_state(s)[0]}{_source_detail(s)}</td><td>{btn}</td></tr>'
    add = ""
    if is_admin:
        off = [s for s in store.sources.values() if not s["enabled"]]
        opts = "".join(f'<option value="{s["id"]}">{e(s["label"])}{" · primary client data source" if s["primary"] else ""}</option>' for s in off)
        add = f'<div class="actions" style="margin-top:12px">{"<select id=newDataSource style=max-width:300px>" + opts + "</select><button class=\"btn primary\" onclick=\"addDataSource()\">＋ Add data source</button>" if off else "<span class=muted>All available sources are connected.</span>"}</div>'
    n_on = sum(1 for s in store.sources.values() if s["enabled"])
    n_live = sum(1 for s in store.sources.values() if s["enabled"] and s["mode"] == "live")
    sf = "Salesforce CRM is marked as the primary client-data source." if store.sources["salesforce"]["enabled"] else "Warning: Salesforce CRM is not connected in this list."
    ds = f'''<div class="card" id="dataSourceSettings" style="margin-bottom:15px"><div class="cardhead"><div><h2>Agent data sources</h2><div class="sub">Review and manage the demo sources used by agents for analysis.</div></div><span class="pill">Demo connectors</span></div><p class="muted">Demo connectors are simulated; market and news sources are live and show their real status. {"Add or remove sources to control which inputs an agent is allowed to use." if is_admin else "Only an Admin can add or remove sources."}</p><div class="tablewrap"><table><thead><tr><th>Data source</th><th>What the agent reads</th><th>Status</th><th>Action</th></tr></thead><tbody id="dataSourceRows">{rows}</tbody></table></div>{add}<div class="calloutnote" id="dataSourceStatus">{n_on} sources enabled ({n_live} live, {n_on - n_live} simulated). {sf} Salesforce and the other demo connectors are simulated; live sources show their last successful retrieval.</div></div>'''
    d = lambda x: " checked" if x in cfg["days"] else ""
    freq = lambda v: " selected" if cfg["frequency"] == v else ""
    mdays = "".join(f'<option value="{i}"{" selected" if str(i) == str(cfg["month_day"]) else ""}>{i}{"st" if i == 1 else "nd" if i == 2 else "rd" if i == 3 else "th"}</option>' for i in range(1, 29)) + f'<option value="last"{" selected" if cfg["month_day"] == "last" else ""}>Last day of month</option>'
    sc = lambda i, name: f'<label><input type="checkbox" id="{i}"{" checked" if name in cfg["scopes"] else ""}>{name}</label>'
    scope_opts = "".join(f'<option{" selected" if cfg["client_scope"] == o else ""}>{o}</option>' for o in ("All assigned clients", "Tier 1 clients only", "Clients flagged for review", "Selected client only"))
    chosen = set(cfg.get("clients", []))
    picker_clients = "".join(f'<label style="display:flex;align-items:center;gap:8px;padding:7px;border:1px solid var(--line);border-radius:8px;font-weight:500" data-client-name="{e(c.name.lower())}"><input type="checkbox" class="schedule-client-check" value="{c.id}"{" checked" if c.id in chosen else ""}> <span>{e(c.name)}</span></label>' for c in pick_clients)
    desc = (services.describe_schedule(cfg) + " UTC") if cfg["enabled"] else "Schedule paused"
    store_is_admin = is_admin
    last = store.schedule_runs[0] if store.schedule_runs else None
    jobs = store.sched["jobs"]
    j0 = jobs[0] if jobs else None
    last_txt = (f"Last run: {j0['trigger']} at {_fmt_dt(j0['started_at'])} by {j0['owner_name']} · {j0['status']}. {j0['message']}" if j0
                else "No runs yet. A saved schedule is executed by the scheduler worker (see docs); Run now executes immediately.")
    hist = "".join(
        f'''<div class="riskitem"><div><strong>{_fmt_dt(j["started_at"])} · {e(j["trigger"])}{" · " + e(j["owner_name"]) if store_is_admin else ""}</strong><small>{e(j["message"] or "running")}{" · attempt " + str(j["attempts"]) if j["attempts"] > 1 else ""}{" · data: " + e(", ".join(f"{k} {v['freshness']}" for k, v in list(j["freshness"].items())[:3] if isinstance(v, dict))) if j["freshness"] else ""}</small></div><span class="pill {"" if j["status"] == "completed" else ("red" if j["status"] in ("failed", "missed") else "pending")}">{e(j["status"])}</span></div>'''
        for j in jobs) or '<p class="muted">No job runs recorded yet.</p>'
    return f'''<section class="view" id="view-settings">
 <div class="pagehead"><div><div class="eyebrow">Workspace settings</div><h1>Agent settings & workflow scheduler</h1><div class="sub">Configure when Atlas prepares monitoring alerts, portfolio reviews and recommendation drafts.</div></div><span class="role-tag" id="settingsRole">{role_tag}</span></div>
 {admin_panel}{ds}
 <div class="notice">Scheduled runs create analysis and drafts only. They never place trades, send client messages or bypass suitability, consent, or approval gates.</div>
 <div class="scheduler-grid"><div class="card"><div class="cardhead"><h2>Schedule configuration</h2><span class="pill">Customisable</span></div>
 <div class="field"><label for="scheduleName">Schedule name</label><input id="scheduleName" value="{e(cfg["name"])}" style="width:100%"></div>
 <div class="field"><label for="scheduleFrequency">Frequency</label><select id="scheduleFrequency" onchange="updateScheduleFields()" style="width:100%"><option value="daily"{freq("daily")}>Daily</option><option value="weekly"{freq("weekly")}>Weekly</option><option value="monthly"{freq("monthly")}>Monthly</option></select></div>
 <div class="field"><label for="scheduleTime">Run time</label><input id="scheduleTime" type="time" value="{e(cfg["time"])}" style="width:100%"></div>
 <div class="field{" hidden" if cfg["frequency"] != "weekly" else ""}" id="weeklyField"><label>Run on</label><div class="days">{"".join(f'<label><input type="checkbox" name="scheduleDay" value="{x}"{d(x)}>{x}</label>' for x in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"))}</div></div>
 <div class="field{" hidden" if cfg["frequency"] != "monthly" else ""}" id="monthlyField"><label for="monthDay">Day of month</label><select id="monthDay" style="width:100%">{mdays}</select></div>
 <div class="field"><label>Workflow scope</label><div class="days">{sc("scopeMonitor", "Portfolio drift")}{sc("scopeRisk", "Risk & scenarios")}{sc("scopeGoals", "Goal progress")}{sc("scopeEvents", "Market events")}{sc("scopeDrafts", "RM draft recommendations")}</div></div>
 <div class="field"><label for="scheduleClients">Client scope</label><select id="scheduleClients" style="width:100%">{scope_opts}</select></div>
 <div class="field{" hidden" if cfg["client_scope"] != "Selected client only" else ""}" id="selectedClientPicker"><label style="display:flex;align-items:center;gap:9px"><input type="checkbox" id="enableClientSelection"{" checked" if chosen else ""}> Choose specific clients for this schedule</label><div id="clientSelectionPanel" class="{"" if chosen else "hidden"}" style="margin-top:10px;border:1px solid var(--line);border-radius:12px;padding:12px"><input id="scheduleClientSearch" placeholder="Search clients by name…" style="width:100%;margin-bottom:10px" oninput="filterScheduleClients()"><div id="scheduleClientList" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;max-height:220px;overflow:auto">{picker_clients}</div><div class="footnote" id="selectedClientCount">{len(chosen)} clients selected</div></div></div>
 <div class="actions"><button class="btn primary" onclick="saveSchedule()">Save schedule</button><button class="btn" onclick="runScheduleNow()">Run preview now</button><button class="btn blue" onclick="runNow()">Run now</button></div><div class="footnote">Preview is a dry run (nothing executes). Run now executes the agent for the clients in scope: analysis, drafts and review items only. Times are UTC.</div></div>
 <div class="card"><div class="cardhead"><h2>Scheduler status</h2><label style="display:flex;align-items:center;gap:8px;font-size:12px;font-weight:750"><input id="scheduleEnabled" type="checkbox"{" checked" if cfg["enabled"] else ""} onchange="updateScheduleSummary()"> Enabled</label></div>
 <div class="schedule-summary"><div class="eyebrow">Schedule preview</div><h2 id="nextRunLabel" style="margin:6px 0 4px">{e(desc)}</h2><div class="sub" id="scheduleSummaryText">{"Enabled" if cfg["enabled"] else "Paused"} · {e(cfg["client_scope"])}</div><div class="sub" style="margin-top:6px">Next scheduled run: <b>{e(store.sched["next"])}</b></div></div>
 <div class="risklist" style="margin-top:15px"><div class="riskitem"><div><strong>1. Gather & validate data</strong><small>Holdings, client context and market/event inputs</small></div><span class="pill">Read-only</span></div><div class="riskitem"><div><strong>2. Run deterministic engines</strong><small>Portfolio drift, risk scenarios and goal projections</small></div><span class="pill">Calculated</span></div><div class="riskitem"><div><strong>3. Generate RM work items</strong><small>Prioritised alerts and recommendation drafts</small></div><span class="pill pending">Human review</span></div><div class="riskitem"><div><strong>4. Record run event</strong><small>Schedule settings and run records in the audit log</small></div><span class="pill">Auditable</span></div></div>
 <div class="calloutnote" id="schedulerRunNote">{e(last_txt)}</div>
 <h3 style="margin:16px 0 8px;font-size:14px">Run history</h3><div class="risklist" id="runHistory">{hist}</div></div></div>
</section>'''


# ------------------------------------------------------------------ modals
def modals(store: Store, user: User, c, readonly: bool) -> str:
    if c is None:
        return '<div class="toast" id="toast"></div>' + _ask_modal()
    rec = store.rec(c.id)
    title, rat = services.rationale_for(c)
    draft = store.draft(c)
    ro = " readonly" if readonly else ""
    eq_plan = c.plan.get("EQ", 0)
    tier_opts = "".join(f'<option{" selected" if rec.tier == t else ""}>{t}</option>' for t in ("Tier 1 — RM approval", "Tier 2 — Senior adviser approval", "Tier 3 — Investment committee"))
    foot = '<button class="btn" onclick="closeModal(\'reviewModal\')">Close</button>' if readonly else '<button class="btn" onclick="closeModal(\'reviewModal\')">Cancel</button><button class="btn primary" onclick="saveReview()">Save RM decision</button>'
    consent_ok = store.has_active_consent(c.id)
    rm_name = next((r.name for r in store.rms if r.id == c.rm_id), "—")
    prop = store.proposals.get(c.id)
    evid = ""
    if prop:
        pb = prop["body"]
        chk = "".join(f'<div class="checkrow"><span class="checkmark {"" if ch["status"] in ("pass", "n/a") else "pending"}">{"✓" if ch["status"] in ("pass", "n/a") else "!"}</span><span>{e(ch["name"])}</span><span class="right {"pass" if ch["status"] == "pass" else "pending"}">{e(ch["status"].upper())}</span></div>' for ch in pb["checks"])
        unres = "".join(f"<li>{e(x)}</li>" for x in pb["unresolved"])
        apprs = "".join(f'<li>{e(a["stage"].capitalize())} approval: {e(a["approver"])} · {e(a["decision"])} · {e(a["decided_at"])} UTC: {e(a["reason"][:120])}</li>' for a in store.approvals)
        evid = (f'<div class="field"><label>Proposal {e(prop["status"].replace("_", " "))} · Tier {prop["tier"]} · evidence items recorded: {store.evidence_count}</label>{chk}'
                f'<div class="muted" style="font-size:11px;margin-top:8px"><b>Open points</b><ul style="padding-left:17px;margin:4px 0 0">{unres}</ul></div>'
                + (f'<div class="muted" style="font-size:11px;margin-top:8px"><b>Approval history</b><ul style="padding-left:17px;margin:4px 0 0">{apprs}</ul></div>' if apprs else "") + "</div>")
    tx = "".join(f'<tr><td>{d}</td><td>{k}</td><td>{e(i)}</td><td>{money(a)}</td><td><span class="pill">{s}</span></td></tr>' for d, k, i, a, s in c.transactions)
    return f'''<div class="modalback" id="reviewModal" role="dialog" aria-modal="true" aria-labelledby="reviewTitle"><div class="modal"><div class="modalhead"><div><div class="eyebrow">AI recommendation · {e(rec.status)}</div><h2 id="reviewTitle">Review & edit recommendation</h2></div><button class="close" onclick="closeModal('reviewModal')" aria-label="Close">×</button></div><div class="modalbody"><div class="notice">This is a fictional scenario. No order will be placed. A recommendation must pass applicable policy, suitability, consent and approval checks before any authorised action.{" Read-only: only a Relationship Manager can record a decision." if readonly else ""}</div><div class="twocol"><div class="field"><label>Client</label><input value="{e(c.name)}" readonly></div><div class="field"><label>Approval tier</label><select id="approvalTier"{" disabled" if readonly else ""}>{tier_opts}</select></div></div><div class="twocol"><div class="field"><label>Current equity allocation</label><input value="{c.weights.get("EQ", 0)}%" readonly></div><div class="field"><label>Target equity allocation</label><input id="targetEquity" type="number" min="0" max="100" value="{eq_plan}"{ro}></div></div><div class="field"><label>AI rationale (editable)</label><textarea id="rationale"{ro}>{e(rec.rationale or rat)}</textarea></div><div class="field"><label>RM review note (required to record decision)</label><textarea id="rmNote" placeholder="Add rationale for approval, edit or rejection…"{ro}>{e(rec.note)}</textarea></div>{evid}<div class="field"><label>Decision</label><select id="decision"{" disabled" if readonly else ""}><option value="approve">Approve draft for next workflow step</option><option value="edit">Save edits for further review</option><option value="reject">Reject recommendation</option></select></div>{"" if readonly else '<div class="field"><label><input type="checkbox" id="convoHeld"> I have spoken with the client (required to approve a Tier 3 item)</label></div>'}<div class="checkrow"><span class="checkmark">✓</span><span>AI output labelled as draft</span><span class="right pass">Yes</span></div><div class="checkrow"><span class="checkmark {"" if consent_ok else "pending"}">{"✓" if consent_ok else "!"}</span><span>Monitoring consent on file</span><span class="right {"pass" if consent_ok else "pending"}">{"Yes" if consent_ok else "No — required"}</span></div><div class="checkrow"><span class="checkmark pending">!</span><span>Client consent for execution</span><span class="right pending">No — still required</span></div></div><div class="modalfoot">{foot}</div></div></div>
{_ask_modal()}
<div class="modalback" id="messageModal" role="dialog" aria-modal="true" aria-labelledby="messageTitle"><div class="modal"><div class="modalhead"><div><div class="eyebrow">Client View · RM-gated</div><h2 id="messageTitle">Draft client message</h2></div><button class="close" onclick="closeModal('messageModal')">×</button></div><div class="modalbody"><div class="notice">This creates a draft only. It will not be sent from this prototype.</div><div class="field"><label>Subject</label><input id="messageSubject" value="{e(draft["subject"])}"></div><div class="field"><label>Message</label><textarea id="messageBody">{e(draft["body"])}</textarea></div></div><div class="modalfoot"><button class="btn" onclick="closeModal('messageModal')">Close draft</button><button class="btn primary" onclick="markDraftReady()">Mark ready for RM review</button></div></div></div>
<div class="modalback" id="notesModal" role="dialog" aria-modal="true" aria-labelledby="notesTitle"><div class="modal"><div class="modalhead"><h2 id="notesTitle">Add adviser note</h2><button class="close" onclick="closeModal('notesModal')">×</button></div><div class="modalbody"><div class="field"><label>Note</label><textarea id="noteText" placeholder="Enter a factual client note…"></textarea></div><div class="footnote">Notes are treated as untrusted text: instruction-like content is quarantined by the control layer (added with the agents).</div></div><div class="modalfoot"><button class="btn" onclick="closeModal('notesModal')">Cancel</button><button class="btn primary" onclick="saveNote()">Save note</button></div></div></div>
<div class="modalback" id="crmModal" role="dialog" aria-modal="true"><div class="modal"><div class="modalhead"><div><div class="eyebrow">Salesforce CRM · simulated · read-only</div><h2>CRM record · {e(c.name)}</h2></div><button class="close" onclick="closeModal('crmModal')">×</button></div><div class="modalbody"><div class="tablewrap"><table><tbody><tr><th>Client ID</th><td>{e(c.id)}</td></tr><tr><th>Email</th><td>{e(c.email)}</td></tr><tr><th>Relationship manager</th><td>{e(rm_name)}</td></tr><tr><th>Service tier</th><td>{c.tier}</td></tr><tr><th>Client since</th><td>{c.since}</td></tr><tr><th>Risk profile (CRM)</th><td>{e(c.risk_profile)}</td></tr><tr><th>Communication preference</th><td>{e(c.contact_pref)}</td></tr></tbody></table></div><div class="calloutnote">Data comes from the simulated Salesforce connector. Atlas reads CRM data and never writes back to it.</div></div><div class="modalfoot"><button class="btn" onclick="closeModal('crmModal')">Close</button></div></div></div>
<div class="modalback" id="historyModal" role="dialog" aria-modal="true"><div class="modal"><div class="modalhead"><div><div class="eyebrow">Portfolio records · simulated</div><h2>Transaction history · {e(c.name)}</h2></div><button class="close" onclick="closeModal('historyModal')">×</button></div><div class="modalbody"><div class="tablewrap"><table><thead><tr><th>Date</th><th>Transaction</th><th>Investment</th><th>Amount</th><th>Status</th></tr></thead><tbody>{tx}</tbody></table></div></div><div class="modalfoot"><button class="btn" onclick="closeModal('historyModal')">Close</button></div></div></div>
<div class="toast" id="toast"></div>'''


def _ask_modal() -> str:
    return '''<div class="modalback" id="askModal" role="dialog" aria-modal="true" aria-labelledby="askTitle"><div class="modal"><div class="modalhead"><div><div class="eyebrow">Internal assistant</div><h2 id="askTitle">Ask Atlas AI</h2></div><button class="close" onclick="closeModal('askModal')">×</button></div><div class="modalbody"><p class="muted">Ask about the selected client, portfolio signal, goal or recommendation. Answers are rule-based from stored records until the AI copilot is connected, and should not be treated as financial advice.</p><div class="field"><label>Your question</label><textarea id="askQuestion" placeholder="e.g., Why is this portfolio flagged for review?"></textarea></div><div id="askAnswer" class="calloutnote hidden"></div><div class="actions"><button class="btn" onclick="askPrompt('Explain the allocation drift')">Explain allocation drift</button><button class="btn" onclick="askPrompt('Summarise client goals')">Summarise goals</button><button class="btn" onclick="askPrompt('What checks are pending?')">Pending checks</button></div></div><div class="modalfoot"><span class="footnote">Rule-based · no external AI service is connected yet.</span><button class="btn primary" onclick="answerAsk()">Get answer</button></div></div></div>'''
