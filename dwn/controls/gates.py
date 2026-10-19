"""Gate controls that run BEFORE any analysis (concept doc s9): consent, data quality, untrusted text.

A failed gate pauses the item with a stated reason. Nothing is estimated or filled in.
Order matters: consent first, so a client without consent is never analysed at all.
"""
from __future__ import annotations

from ..engines.types import ClientProfile, EventInput, Policy
from .quarantine import scan_untrusted_text

ABSTENTION = {
    "no_consent": "Client information is incomplete: monitoring consent is not on file. Processing is paused and a consent task is raised for the RM.",
    "stale_data": "Market data is stale or unavailable. No current-market statement is made.",
    "implausible_data": "A price move looks implausible (possible bad tick). Held for verification.",
    "missing_data": "Insufficient evidence to assess: a price is missing for a holding.",
    "sources_disagree": "Sources disagree. This requires relationship manager review.",
    "currency_mismatch": "Market data is unavailable in USD for a holding (currency or FX rate missing).",
    "security_injection": "Instruction-like text was found in untrusted content. It was quarantined and compliance was alerted.",
    "incomplete_profile": "Client information is incomplete. Structured goals, plan or restrictions are missing.",
}


def pause_reason(p: ClientProfile, ev: EventInput, policy: Policy) -> str:
    if not p.consent:
        return "no_consent"
    if ev.feed_age_min > policy.max_feed_age_min:
        return "stale_data"
    if ev.data_issue:
        return {"missing_price": "missing_data", "sources_disagree": "sources_disagree", "currency_mismatch": "currency_mismatch"}[ev.data_issue]
    for cls, move in ev.shocks.items():
        limit = policy.bad_tick_single_stock if cls == "SS" else policy.bad_tick_diversified
        if abs(move) > limit:
            return "implausible_data"
    if scan_untrusted_text(ev.note_text):
        return "security_injection"
    return ""
