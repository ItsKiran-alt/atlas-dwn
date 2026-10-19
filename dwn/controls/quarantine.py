"""Untrusted-text scan (concept document s4/s9): notes and news are DATA, never instructions.

Text that looks like a command to the AI is quarantined (not shown, not passed to any model) and compliance is alerted.
The pattern list is deliberately simple and conservative; it is one layer, not the only defence (agents also receive
untrusted text only inside clearly delimited data blocks, added in Phase 5).
"""
from __future__ import annotations

import re

INJECTION_PATTERNS = [
    r"ignore (all|any|previous|prior) (rules|instructions)",
    r"system (note|prompt|message)\b.*\b(ai|assistant|model)",
    r"\b(assistant|ai)\s*[:,]\s*(transfer|sell|buy|approve|send|disable)",
    r"disregard .*(polic|rule|control)",
    r"you are now",
    r"override .*(approval|compliance|control)",
    r"(reveal|print|show) .*(system prompt|api key|password|secret)",
    r"<\s*(system|assistant)\s*>",
]
_COMPILED = [re.compile(p) for p in INJECTION_PATTERNS]


def scan_untrusted_text(text: str) -> str:
    """Return the first matching pattern (a reason) or '' if the text looks like ordinary content."""
    t = (text or "").lower()
    for rx in _COMPILED:
        if rx.search(t):
            return rx.pattern
    return ""
