"""Turns golden_set.json into typed objects for the production engines. Used by tests and scripts/run_golden_agent.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dwn.engines.types import Candidate, ClientProfile, EventInput, Goal, Restrictions, Signal  # noqa: E402

GOLDEN = json.loads((Path(__file__).parent / "golden_set.json").read_text(encoding="utf-8"))
CONTACT = {"phone_first": "phone_first", "phone_only": "phone_only", "in_person": "in_person", "email": "email", "app": "app"}


def profile_for(key: str) -> ClientProfile:
    c = GOLDEN["clients"][key]
    r = Restrictions(untradable=c.get("untradable", []), exclusions=c.get("exclusions", []), mandate_equity_cap=c.get("mandate_equity_cap"),
                     no_new_alts=c.get("no_new_alts", False), conc_exception=c.get("conc_exception", False), crm_risk_mismatch=c.get("crm_risk_mismatch", False))
    g = c["goal"]
    return ClientProfile(client_id="c-" + key.lower(), name=key, portfolio=c["portfolio"], plan=c["plan"], weights=c["weights"], band=c["band"],
                         risk_tolerance=c["risk"], risk_capacity=c["capacity"], goal=Goal(name=g["name"], years=g["years"], earmark=g["earmark"], target=g["target"]),
                         restrictions=r, contact_mode=CONTACT[c["contact"]], consent=c["consent"])


def event_for(raw: dict) -> EventInput:
    d = dict(raw)
    sig = d.pop("signal", None)
    if sig:
        sig = dict(sig)
        if sig.get("new_goal"):
            sig["new_goal"] = Goal(name="Suggested goal", **sig["new_goal"])
        sig = Signal(**sig)
    cand = d.pop("candidate", None)
    return EventInput(signal=sig, candidate=Candidate(**cand) if cand else None, **d)


def scenarios():
    for s in GOLDEN["scenarios"]:
        yield s, profile_for(s["client"]), event_for(s["event_input"])
