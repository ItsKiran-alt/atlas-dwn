"""Shared views of an AI recommendation: current vs target vs proposed allocation, trades and checks.

Used by AI Insights, the client hero, and the reports so the same numbers appear everywhere."""
from __future__ import annotations

from html import escape as e

from ..engines.portfolio import CLASS_LABEL
from ..engines.types import CLASS_NAME

_KEY_BY_NAME = {v: k for k, v in CLASS_NAME.items()}
KEYS = ("EQ", "FI", "AL", "CA")


def allocation_rows(c, pb: dict | None) -> list[dict]:
    """One row per asset class: current %, plan %, proposed change (points) and resulting %.

    With a stored proposal the change is the sum of its trades; without one the change is 'move to plan'."""
    change = {k: 0.0 for k in KEYS}
    if pb:
        for t in pb.get("trades", []):
            k = _KEY_BY_NAME.get(t["asset_class"])
            if k in change:
                change[k] += t["points"] if t["direction"] == "buy" else -t["points"]
        basis = "proposal"
    else:
        for k in KEYS:
            change[k] = c.plan.get(k, 0) - c.weights.get(k, 0)
        basis = "plan"
    rows = []
    for k in KEYS:
        cur, plan = c.weights.get(k, 0), c.plan.get(k, 0)
        rows.append(dict(key=k, label=CLASS_LABEL[k], current=cur, plan=plan, drift=round(cur - plan, 1), change=round(change[k], 1), new=round(cur + change[k], 1), basis=basis))
    return rows


def allocation_table(c, pb: dict | None) -> str:
    rows = allocation_rows(c, pb)
    body = ""
    for r in rows:
        ch = r["change"]
        cls = "good" if ch > 0 else ("bad" if ch < 0 else "muted")
        chtxt = "—" if ch == 0 else f"{ch:+g} pp"
        body += (f'<tr><td>{e(r["label"])}</td><td>{r["current"]:g}%</td><td>{r["plan"]:g}%</td>'
                 f'<td class="{"bad" if abs(r["drift"]) >= 5 else ""}">{r["drift"]:+g} pp</td>'
                 f'<td class="{cls}">{chtxt}</td><td><b>{r["new"]:g}%</b></td></tr>')
    note = "" if pb else '<div class="muted" style="font-size:11px;margin-top:6px">No full proposal yet: the "after" column shows a move to the client\'s target plan. Run analysis for a checked proposal.</div>'
    return (f'<div class="tablewrap"><table><thead><tr><th>Asset class</th><th>Current</th><th>Target plan</th><th>Gap</th><th>Proposed change</th><th>After adjustment</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>{note}')


def trades_list(pb: dict | None) -> str:
    if not pb or not pb.get("trades"):
        return '<p class="muted" style="margin:6px 0">No adjustment proposed: keep monitoring.</p>'
    return "<ul style='padding-left:17px;margin:6px 0'>" + "".join(
        f'<li><b>{t["direction"].capitalize()}</b> {e(t["asset_class"])} {t["points"]:g} points (about ${t["usd"]:,.0f})</li>' for t in pb["trades"]) + "</ul>"


def tier_chip(pb: dict | None) -> str:
    if not pb:
        return '<span class="chip amber">Draft</span>'
    t = pb["tier"]
    label = "Significant" if t == "3" else ("Review" if t == "2" else "Inform")
    return f'<span class="chip {"red" if t == "3" else ("amber" if t == "2" else "green")}">Tier {t} · {label}</span>'


def rec_detail(c, prop: dict | None, rec_title: str, rec_text: str, status_text: str) -> str:
    """Body of the recommendation detail (no buttons)."""
    pb = prop["body"] if prop else None
    summary = pb["summary"] if pb else rec_text
    title = pb["title"] if pb else rec_title
    out = [f'<div class="eyebrow">{e(c.name)} · {e(status_text)}</div><h3 style="margin:2px 0 8px">{e(title)}</h3>', f'<div>{tier_chip(pb)}</div>',
           f'<p style="margin:10px 0">{e(summary)}</p>',
           '<div class="charttitle" style="margin-top:12px">Current status and new adjustment</div>', allocation_table(c, pb),
           '<div class="charttitle" style="margin-top:14px">Proposed trades (nothing is executed)</div>', trades_list(pb)]
    if pb:
        if pb.get("benefits"):
            out.append("<b>Why</b><ul style='padding-left:17px;margin:4px 0 8px'>" + "".join(f"<li>{e(x)}</li>" for x in pb["benefits"]) + "</ul>")
        if pb.get("risks"):
            out.append("<b>Risks and trade-offs</b><ul style='padding-left:17px;margin:4px 0 8px'>" + "".join(f"<li>{e(x)}</li>" for x in pb["risks"] + pb.get("trade_offs", [])) + "</ul>")
        failed = [ch for ch in pb.get("checks", []) if ch["status"] == "fail"]
        ctl = "FAILED: " + e(failed[0]["name"]) if failed else "all passed"
        out.append(f'<div class="muted" style="font-size:11px">Controls: {ctl} · {e(pb["approval_path"])}</div>')
    return "".join(out)
