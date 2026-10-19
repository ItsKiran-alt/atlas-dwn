"""Output controls for anything drafted for a human (concept doc s9):

* prohibited language: no guarantees, promises, risk-free claims or return forecasts
* numbers traceable: every figure in a draft must come from an engine, the client record or policy; otherwise the draft is BLOCKED
"""
from __future__ import annotations

import re

PROHIBITED = [
    r"\bguarantee[sd]?\b", r"\brisk[- ]free\b", r"\bno risk\b", r"\bpromise[sd]?\b", r"\bcan'?t lose\b", r"\bsure thing\b",
    r"\bwill (definitely |certainly )?(rise|grow|increase|outperform|recover|rebound|return|gain)\b",
    r"\b(is|are) (expected|set|bound|certain) to (rise|grow|increase|outperform|recover|rebound|return|gain)\b",
    r"\bbound to\b", r"\bdouble your money\b", r"\bforecast(s|ed)? (a |an )?(return|gain|rise|rebound|recovery)",
    r"\bexpected return of\b", r"\bwill make (you )?money\b",
]
_P = [re.compile(p, re.I) for p in PROHIBITED]

_NUM = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?\s?(?:%|M\b|k\b|million\b|thousand\b|pts\b|points\b)?", re.I)


def prohibited_language(text: str) -> list[str]:
    return [rx.pattern for rx in _P if rx.search(text or "")]


def _scale(tok: str) -> list[float]:
    """Numeric readings of a token: '$450k' -> 450000 (and 450); '3.6%' -> 3.6 and 0.036."""
    m = re.match(r"\$?([\d,]+(?:\.\d+)?)\s?(%|M|k|million|thousand|pts|points)?", tok.strip(), re.I)
    if not m:
        return []
    x = float(m.group(1).replace(",", ""))
    u = (m.group(2) or "").lower()
    vals = [x]
    if u in ("m", "million"):
        vals.append(x * 1_000_000)
    elif u in ("k", "thousand"):
        vals.append(x * 1_000)
    elif u == "%":
        vals.append(x / 100)
    return vals


def _flatten(obj, out: list[float]):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _flatten(v, out)
    elif isinstance(obj, str):
        for t in _NUM.findall(obj):
            out.extend(_scale(t))


def allowed_numbers(facts: dict) -> list[float]:
    base: list[float] = []
    _flatten(facts, base)
    ext = list(base)
    for x in base:                                           # derived readings of a fact (unit changes only; no arithmetic on facts)
        ext += [abs(x), x * 100]
    return ext


def _tol(v: float, a: float) -> float:
    m = max(abs(v), abs(a))
    return 0.0051 if m < 1 else (0.051 if m < 100 else 0.005 * m)


def untraceable_figures(text: str, facts: dict) -> list[str]:
    """Figures in `text` that match no value in `facts` (relative tolerance 0.5%, absolute 0.051 for small values)."""
    allowed = allowed_numbers(facts)
    bad = []
    for tok in _NUM.findall(text or ""):
        tok = tok.strip()
        vals = _scale(tok)
        if not vals:
            continue
        if not any(abs(v - a) <= _tol(v, a) for v in vals for a in allowed):
            bad.append(tok)
    return bad
