"""Report builders. Every report is built only from stored records the signed-in user may see (RBAC is applied by the caller
through services.clients_for). Reports never call an LLM, never invent figures and never send anything.

A report is {title, filename, body_html, csv?}. `body_html` is what the app shows in the View dialog; `document()` wraps it
into a standalone, print-ready HTML file for download."""
from __future__ import annotations

import csv
import io
from html import escape as e

from .domain import utcnow
from .engines.portfolio import CLASS_LABEL, headline_drift, money_m
from .ui.recview import allocation_table, rec_detail, trades_list

DISCLAIMER = "Fictional demo data. Decision support, not advice. Execution is locked: no trade or message has been placed or sent."

KINDS = {
    "portfolio_review": ("Quarterly portfolio review", "Every client: value, allocation drift, goal status and recommendation state"),
    "recommendations": ("AI recommendation rationale", "Each AI proposal: tier, status, current vs proposed allocation, trades and checks"),
    "approvals_audit": ("Approvals and audit summary", "Who decided what, and the latest audit entries for your clients"),
    "consent_status": ("Consent status", "Monitoring consent on file, withdrawn or pending for each client"),
    "data_freshness": ("Market and data freshness", "Latest stored prices and headlines with their age and source"),
}


def _csv(rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    for r in rows:
        w.writerow(["'" + str(x) if isinstance(x, str) and x[:1] in ("=", "+", "-", "@") else x for x in r])
    return buf.getvalue()


def _table(head: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{e(h)}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tablewrap"><table><thead><tr>{th}</tr></thead><tbody>{tr or "<tr><td colspan=%d>Nothing to show.</td></tr>" % len(head)}</tbody></table></div>'


def document(title: str, body_html: str, who: str) -> str:
    """Standalone HTML file for download. Self-contained; no scripts."""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{e(title)}</title>'
            '<style>body{font:14px/1.5 system-ui,Segoe UI,Arial,sans-serif;color:#10233f;max-width:960px;margin:28px auto;padding:0 18px}'
            'h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin-top:26px;border-bottom:1px solid #dce5f2;padding-bottom:4px}'
            'table{border-collapse:collapse;width:100%;margin:8px 0}th,td{border:1px solid #dce5f2;padding:6px 9px;text-align:left;font-size:13px}'
            'th{background:#f2f6fc}.muted,.footer{color:#5d6f88;font-size:12px}.good{color:#1c7a4f}.bad{color:#b4333d}.warn{color:#9a6a12}'
            '.chip{display:inline-block;padding:1px 8px;border-radius:99px;background:#eef3fb;font-size:12px}.charttitle{font-weight:700;margin-top:12px}.eyebrow{text-transform:uppercase;font-size:11px;letter-spacing:.06em;color:#2b61a8}</style></head><body>'
            f'<div class="eyebrow">Atlas Wealth Management</div><h1>{e(title)}</h1>'
            f'<div class="muted">Prepared for {e(who)} · {utcnow().strftime("%d %b %Y %H:%M")} UTC</div>{body_html}'
            f'<p class="footer">{e(DISCLAIMER)}</p></body></html>')


# ----------------------------------------------------------------------------- data gathering
class Ctx:
    """One batch of reads shared by all report builders (a handful of queries, however many clients)."""

    def __init__(self, repo, clients):
        self.repo, self.clients = repo, clients
        ids = [c.id for c in clients]
        self.consent = repo.consent_map(ids)
        self.props = repo.latest_proposals(ids)
        self.recs = repo.recs_for(ids)
        self.rms = {r.id: r.name for r in repo.list_rms()}


def _status(ctx: Ctx, c) -> str:
    if not ctx.consent.get(c.id):
        return "Paused: no monitoring consent"
    p = ctx.props.get(c.id)
    if p:
        return p["status"].replace("_", " ").capitalize()
    r = ctx.recs.get(c.id)
    return r.status if r else "Monitoring"


# ----------------------------------------------------------------------------- portfolio-wide reports
def portfolio_review(ctx: Ctx) -> dict:
    rows, csv_rows = [], [["Client", "AUM (USD m)", "Risk profile", "Largest gap", "Equity now", "Equity target", "Status"]]
    for c in ctx.clients:
        k, v = headline_drift(c.weights, c.plan)
        paused = not ctx.consent.get(c.id)
        gap = "—" if paused else f"{CLASS_LABEL[k]} {v:+g} pp"
        goal = "; ".join(f"{g.name} {g.progress}%" for g in c.goals) or "—"
        rows.append([e(c.name), money_m(c.aum_musd), e(c.risk_profile), e(gap), f'{c.weights.get("EQ", 0):g}% / {c.plan.get("EQ", 0):g}%', e(goal), e(_status(ctx, c))])
        csv_rows.append([c.name, c.aum_musd, c.risk_profile, gap, c.weights.get("EQ", 0), c.plan.get("EQ", 0), _status(ctx, c)])
    total = sum(c.aum_musd for c in ctx.clients)
    paused_n = sum(1 for c in ctx.clients if not ctx.consent.get(c.id))
    body = (f'<p>{len(ctx.clients)} clients · total assets {money_m(total)} · {paused_n} paused for missing consent (no analysis is shown for them).</p>'
            + _table(["Client", "AUM", "Risk profile", "Largest gap vs plan", "Equity now / target", "Goals", "Status"], rows))
    return dict(title="Quarterly portfolio review", filename="portfolio-review", body_html=body, csv=_csv(csv_rows))


def recommendations(ctx: Ctx) -> dict:
    parts, csv_rows = [], [["Client", "Tier", "Status", "Title", "Trades"]]
    open_n = 0
    for c in ctx.clients:
        p = ctx.props.get(c.id)
        if not ctx.consent.get(c.id):
            parts.append(f'<h2>{e(c.name)}</h2><p class="muted">Paused: monitoring consent is not on file, so no recommendation is produced.</p>')
            csv_rows.append([c.name, "", "paused (no consent)", "", ""])
            continue
        if not p:
            continue
        pb = p["body"]
        open_n += p["status"] in ("awaiting_rm", "awaiting_second")
        parts.append(f'<h2>{e(c.name)}</h2>' + rec_detail(c, p, pb["title"], pb["summary"], p["status"].replace("_", " ")))
        csv_rows.append([c.name, pb["tier"], p["status"], pb["title"], "; ".join(f'{t["direction"]} {t["asset_class"]} {t["points"]:g}pts (${t["usd"]:,.0f})' for t in pb["trades"])])
    body = f'<p>{len(csv_rows) - 1} proposals · {open_n} awaiting a human decision.</p>' + ("".join(parts) or '<p class="muted">No proposals yet. Run analysis to create them.</p>')
    return dict(title="AI recommendation rationale", filename="ai-recommendations", body_html=body, csv=_csv(csv_rows))


def approvals_audit(ctx: Ctx) -> dict:
    rows, csv_rows = [], [["Client", "Stage", "Approver", "Decision", "Time (UTC)", "Reason"]]
    for c in ctx.clients:
        p = ctx.props.get(c.id)
        if not p:
            continue
        for a in ctx.repo.approvals_for(p["id"]):
            rows.append([e(c.name), e(a["stage"]), e(a["approver"]), e(a["decision"]), e(str(a["decided_at"])), e(a["reason"][:160])])
            csv_rows.append([c.name, a["stage"], a["approver"], a["decision"], str(a["decided_at"]), a["reason"]])
    audit = ctx.repo.list_audit(limit=25, client_ids=[c.id for c in ctx.clients])
    arows = [[e(x.ts), e(x.client), e(x.action), e(x.actor), e(x.status)] for x in audit]
    body = ("<h2>Decisions recorded</h2>" + _table(["Client", "Stage", "Approver", "Decision", "Time (UTC)", "Reason"], rows)
            + "<h2>Latest audit entries</h2>" + _table(["Time (UTC)", "Client", "Action", "Actor", "Status"], arows))
    return dict(title="Approvals and audit summary", filename="approvals-audit", body_html=body, csv=_csv(csv_rows))


def consent_status(ctx: Ctx) -> dict:
    rows, csv_rows = [], [["Client", "Monitoring consent"]]
    for c in ctx.clients:
        ok = ctx.consent.get(c.id)
        rows.append([e(c.name), '<span class="good">On file</span>' if ok else '<span class="bad">Not on file: processing paused</span>', e(ctx.rms.get(c.rm_id, "—"))])
        csv_rows.append([c.name, "on file" if ok else "not on file"])
    n = sum(1 for c in ctx.clients if not ctx.consent.get(c.id))
    body = f'<p>{len(ctx.clients) - n} of {len(ctx.clients)} clients have monitoring consent on file. Without consent, Atlas does not analyse, draft or report on a client.</p>' + _table(["Client", "Monitoring consent", "Relationship manager"], rows)
    return dict(title="Consent status", filename="consent-status", body_html=body, csv=_csv(csv_rows))


def data_freshness(ctx: Ctx) -> dict:
    from .data.market import MarketService
    rows, csv_rows = [], [["Symbol", "Name", "Price", "Change %", "Freshness", "Source"]]
    for q in MarketService(ctx.repo).view():
        price = f'{q["price"]:,.2f}' if q.get("price") is not None else "—"
        chg = f'{q["change_pct"]:+.2f}%' if q.get("change_pct") is not None else "—"
        rows.append([e(q["symbol"]), e(q["name"]), price, chg, e(q["freshness"].replace("_", " ")), e(str(q.get("provider", "")).split(" (")[0])])
        csv_rows.append([q["symbol"], q["name"], price, chg, q["freshness"], q.get("provider", "")])
    news = ctx.repo.list_news(8)
    nrows = [[e(getattr(n, "title", "")[:110]), e(getattr(n, "publisher", ""))] for n in news]
    body = ("<h2>Prices</h2>" + _table(["Symbol", "Name", "Price", "Change", "Freshness", "Source"], rows)
            + "<h2>Latest official headlines</h2>" + _table(["Headline", "Publisher"], nrows))
    return dict(title="Market and data freshness", filename="data-freshness", body_html=body, csv=_csv(csv_rows))


# ----------------------------------------------------------------------------- one client
def client_review(ctx: Ctx, c) -> dict:
    """The final analysis, recommendation and adjustment for ONE client."""
    if not ctx.consent.get(c.id):
        body = (f'<h2>{e(c.name)}</h2><p class="bad"><b>Paused.</b> Monitoring consent is not on file for this client, so Atlas has not analysed the portfolio '
                'and no recommendation or adjustment is shown. Ask the client to give consent in their portal.</p>')
        return dict(title=f"Client review: {c.name}", filename=f"client-review-{c.id}", body_html=body, csv=None)
    p = ctx.props.get(c.id)
    pb = p["body"] if p else None
    rec = ctx.recs.get(c.id)
    k, v = headline_drift(c.weights, c.plan)
    goals = _table(["Goal", "Detail", "Progress"], [[e(g.name), e(g.detail), f"{g.progress}%"] for g in c.goals])
    status = p["status"].replace("_", " ") if p else (rec.status if rec else "Monitoring")
    head = (f'<p>{e(c.name)} · {money_m(c.aum_musd)} · {e(c.risk_profile)} risk profile · client since {e(str(c.since))}</p>'
            f'<h2>Final analysis</h2><p>Largest gap from plan: <b>{e(CLASS_LABEL[k])} {v:+g} points</b>. Recommendation status: <b>{e(status)}</b>.</p>')
    if pb:
        rec_html = rec_detail(c, p, pb["title"], pb["summary"], status)
        client_msg = f'<h2>Draft client message (RM-gated, not sent)</h2><p>{e(pb["client_message"])}</p>' if pb.get("client_message") else ""
        talking = "<h2>Talking points</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in pb.get("talking_points", [])) + "</ul>" if pb.get("talking_points") else ""
        chk = _table(["Control", "Result", "Detail"], [[e(x["name"]), e(x["status"].upper()), e(x.get("detail", ""))] for x in pb["checks"]])
        appr = _table(["Stage", "Approver", "Decision", "Time (UTC)", "Reason"], [[e(a["stage"]), e(a["approver"]), e(a["decision"]), e(str(a["decided_at"])), e(a["reason"][:160])] for a in ctx.repo.approvals_for(p["id"])])
        body = head + "<h2>Recommendation and adjustment</h2>" + rec_html + client_msg + talking + "<h2>Controls</h2>" + chk + "<h2>Approvals</h2>" + appr + "<h2>Goals</h2>" + goals
    else:
        body = (head + "<h2>Recommendation and adjustment</h2><p class='muted'>No AI proposal exists yet for this client. Use Run now to create one. "
                "Until then the table shows the move that would bring the portfolio to its target plan.</p>" + allocation_table(c, None) + trades_list(None) + "<h2>Goals</h2>" + goals)
    return dict(title=f"Client review: {c.name}", filename=f"client-review-{c.id}", body_html=body, csv=None)


BUILDERS = dict(portfolio_review=portfolio_review, recommendations=recommendations, approvals_audit=approvals_audit,
                consent_status=consent_status, data_freshness=data_freshness)
