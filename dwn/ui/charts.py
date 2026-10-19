"""Server-rendered SVG charts (no JavaScript, no external libraries, nothing to load or block). All inputs are numbers we computed;
all text is escaped. Colours match the Atlas palette used by the allocation donut."""
from __future__ import annotations

import math
from html import escape as e

COLORS = {"EQ": "#245b9d", "FI": "#8eb6ec", "AL": "#8392a6", "CA": "#c9d9ee"}
LABELS = {"EQ": "Equities", "FI": "Bonds", "AL": "Alternatives", "CA": "Cash"}
INK, MUTED, GRID, BAD, GOOD = "#10233f", "#5d6f88", "#dce5f2", "#c43b45", "#1c7a4f"


def donut(weights: dict, title: str = "Current allocation") -> str:
    total = sum(max(0.0, weights.get(k, 0)) for k in COLORS) or 1.0
    cx = cy = 80
    r, sw = 56, 26
    circ = 2 * math.pi * r
    parts, off = [], 0.0
    for k in COLORS:
        v = max(0.0, weights.get(k, 0)) / total
        if v <= 0:
            continue
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{COLORS[k]}" stroke-width="{sw}" stroke-dasharray="{v * circ:.2f} {circ:.2f}" stroke-dashoffset="{-off * circ:.2f}" transform="rotate(-90 {cx} {cy})"><title>{LABELS[k]} {weights.get(k, 0):g}%</title></circle>')
        off += v
    legend = "".join(f'<div style="display:flex;align-items:center;gap:7px;font-size:12px"><span style="width:10px;height:10px;border-radius:3px;background:{COLORS[k]}"></span>{LABELS[k]} <b style="margin-left:auto">{weights.get(k, 0):g}%</b></div>' for k in COLORS)
    return (f'<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap"><svg viewBox="0 0 160 160" width="150" height="150" role="img" aria-label="{e(title)}">{"".join(parts)}'
            f'<text x="80" y="76" text-anchor="middle" font-size="11" fill="{MUTED}">Total</text><text x="80" y="94" text-anchor="middle" font-size="15" font-weight="700" fill="{INK}">100%</text></svg>'
            f'<div style="display:grid;gap:6px;min-width:150px;flex:1">{legend}</div></div>')


def compare_bars(weights: dict, plan: dict) -> str:
    """Current (solid) vs target (marker) per class."""
    rows, y = [], 8
    for k in COLORS:
        cur, tgt = float(weights.get(k, 0)), float(plan.get(k, 0))
        w = 300
        rows.append(f'<text x="0" y="{y + 12}" font-size="12" fill="{INK}">{LABELS[k]}</text>'
                    f'<rect x="92" y="{y}" width="{w}" height="16" rx="4" fill="#eef3fb"/>'
                    f'<rect x="92" y="{y}" width="{w * min(cur, 100) / 100:.1f}" height="16" rx="4" fill="{COLORS[k]}"><title>Current {cur:g}%</title></rect>'
                    f'<line x1="{92 + w * min(tgt, 100) / 100:.1f}" x2="{92 + w * min(tgt, 100) / 100:.1f}" y1="{y - 3}" y2="{y + 19}" stroke="{INK}" stroke-width="2.5"><title>Target {tgt:g}%</title></line>'
                    f'<text x="{92 + w + 8}" y="{y + 12}" font-size="12" fill="{INK}">{cur:g}% <tspan fill="{MUTED}">/ {tgt:g}%</tspan></text>')
        y += 30
    return (f'<svg viewBox="0 0 470 {y}" width="100%" role="img" aria-label="Current allocation against target">{"".join(rows)}</svg>'
            f'<div class="muted" style="font-size:11px">Bar = current · black marker = target plan</div>')


def drift_bars(rows: list[dict], band: float) -> str:
    """Gap from target per class, centred on zero, with the allowed range shaded."""
    mx = max([abs(r["gap"]) for r in rows] + [band, 5]) * 1.15
    w, mid = 300, 92 + 150
    scale = (w / 2) / mx
    out = [f'<rect x="{mid - band * scale:.1f}" y="2" width="{band * 2 * scale:.1f}" height="{len(rows) * 30 + 4}" fill="#e8f7ef"><title>Allowed range ±{band:g} points</title></rect>',
           f'<line x1="{mid}" x2="{mid}" y1="0" y2="{len(rows) * 30 + 8}" stroke="{MUTED}" stroke-width="1"/>']
    y = 8
    for r in rows:
        g = r["gap"]
        col = BAD if r["outside"] else (GOOD if abs(g) < 0.05 else "#8392a6")
        x = mid if g >= 0 else mid + g * scale
        out.append(f'<text x="0" y="{y + 12}" font-size="12" fill="{INK}">{r["label"]}</text>'
                   f'<rect x="{x:.1f}" y="{y}" width="{max(abs(g) * scale, 1.5):.1f}" height="16" rx="3" fill="{col}"><title>{r["label"]}: {g:+g} pts vs target</title></rect>'
                   f'<text x="{92 + w + 8}" y="{y + 12}" font-size="12" font-weight="700" fill="{col}">{g:+g} pp</text>')
        y += 30
    return (f'<svg viewBox="0 0 470 {y}" width="100%" role="img" aria-label="Drift from target by asset class">{"".join(out)}</svg>'
            f'<div class="muted" style="font-size:11px">Green band = allowed range (±{band:g} points, a placeholder owned by compliance). Red = outside the range.</div>')


def line_chart(dates: list, series: list[tuple[str, list[float], str]], height: int = 190) -> str:
    """Index lines (start = 100). `series` = [(label, values, colour)]."""
    n = len(dates)
    if n < 2:
        return ""
    w, h, pl, pr, pt, pb = 560, height, 38, 12, 10, 24
    lo = min(min(v) for _, v, _ in series)
    hi = max(max(v) for _, v, _ in series)
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad

    def X(i): return pl + (w - pl - pr) * i / (n - 1)
    def Y(v): return pt + (h - pt - pb) * (1 - (v - lo) / (hi - lo))

    grid = ""
    for k in range(5):
        gv = lo + (hi - lo) * k / 4
        grid += f'<line x1="{pl}" x2="{w - pr}" y1="{Y(gv):.1f}" y2="{Y(gv):.1f}" stroke="{GRID}"/><text x="{pl - 5}" y="{Y(gv) + 4:.1f}" text-anchor="end" font-size="10" fill="{MUTED}">{gv:.0f}</text>'
    xt = ""
    for i in sorted({0, n // 4, n // 2, 3 * n // 4, n - 1}):
        anchor = "end" if i == n - 1 else ("start" if i == 0 else "middle")
        xt += f'<text x="{X(i):.1f}" y="{h - 6}" text-anchor="{anchor}" font-size="10" fill="{MUTED}">{dates[i].strftime("%b %y")}</text>'
    lines = ""
    for label, vals, col in series:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
        lines += f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.2" stroke-linejoin="round"><title>{e(label)}</title></polyline>'
    legend = "".join(f'<span style="display:inline-flex;align-items:center;gap:5px;margin-right:14px;font-size:12px"><span style="width:14px;height:3px;background:{c};display:inline-block"></span>{e(l)}</span>' for l, _, c in series)
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Estimated performance, index start 100">{grid}{xt}{lines}</svg><div>{legend}</div>'


def goal_bars(goals: list) -> str:
    if not goals:
        return '<p class="muted">No goals recorded.</p>'
    out = []
    for g in goals:
        col = GOOD if g.progress >= 80 else ("#d99a1f" if g.progress >= 60 else BAD)
        out.append(f'<div style="margin:8px 0"><div style="display:flex;justify-content:space-between;font-size:12px"><span>{e(g.name)}</span><b>{g.progress}%</b></div>'
                   f'<div style="height:10px;background:#eef3fb;border-radius:6px;overflow:hidden"><div style="height:100%;width:{min(100, max(0, g.progress))}%;background:{col}"></div></div>'
                   f'<div class="muted" style="font-size:11px">{e(g.detail)}</div></div>')
    return "".join(out)
