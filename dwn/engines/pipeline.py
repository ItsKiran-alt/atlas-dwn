"""The deterministic analysis pipeline: gates -> engines -> policy flags -> five-factor tier -> message routing.

`analyse` is the single place that decides tier, flags and trade proposals. Same input, same output, always.
"""
from __future__ import annotations

from ..controls.gates import pause_reason
from . import goals, rebalance
from .types import CLASSES, Analysis, ClientProfile, EventInput, Factors, Policy

SENSITIVITY_2 = {"confirmed_life_event", "concentration", "untradable_limit", "illiquid_locked", "exclusion_blocked", "restricted_list_blocked", "profile_conflict"}


def analyse(p: ClientProfile, ev: EventInput, policy: Policy | None = None) -> Analysis:
    policy = policy or Policy()
    reason = pause_reason(p, ev, policy)
    if reason:
        return Analysis(tier="Paused", paused_reason=reason, flags=[reason], band_pts=round(p.band * 100, 1),
                        must_not_trade=(["all"] if reason in ("no_consent", "security_injection") else []))

    flags: set[str] = set()
    sig = ev.signal
    certainty = sig.certainty if sig else None
    confirmed = certainty == "confirmed"
    if certainty == "possible":
        flags.add("possible_life_event")
    elif certainty == "not_client":
        flags.add("not_attributed_to_client")
    if confirmed:
        flags.add("client_request" if sig.kind == "client_request" else "confirmed_life_event")

    inflow, outflow = (ev.inflow, ev.outflow) if confirmed or sig is None else (0.0, 0.0)
    before = goals.project(p.weights, p.portfolio, p.goal, policy)
    w1, v1, flow_size, shortfall = rebalance.apply_event(p, ev, inflow, outflow)

    years, target = p.goal.years, p.goal.target
    if confirmed and sig.new_years is not None:
        years = sig.new_years
    if confirmed and sig.new_target is not None:
        target = sig.new_target
    after = goals.project(w1, v1, p.goal, policy, years=years, target=target)
    driver, suggested_name = "existing", ""
    if confirmed and sig.new_goal:
        flags.add("suggested_goal")
        new = goals.project(w1, v1, sig.new_goal, policy)
        if goals.worse(after, new) is new and new.status != after.status:
            driver, suggested_name = "suggested", sig.new_goal.name
        after = goals.worse(after, new)
    if after.status != "on track":
        flags.add("goal_at_risk")

    drifts = {c: w1[c] - p.plan[c] for c in CLASSES}
    max_drift = max(abs(d) for d in drifts.values())
    risk = 1 if max_drift <= p.band + 1e-9 else (2 if max_drift <= 2 * p.band + 1e-9 else 3)
    if max_drift > p.band + 1e-9:
        flags.add("drift_breach")
    cap = p.restrictions.mandate_equity_cap
    if cap is not None and w1["EQ"] > cap + 1e-9:
        flags.add("mandate_breach")
        risk = 3

    ss_move = ev.shocks.get("SS", 0.0)
    conc_trim = False
    if w1["SS"] > policy.concentration_limit + 1e-9 and ss_move != 0:
        flags.add("concentration")
        if p.restrictions.conc_exception:
            flags.add("exception_on_file")
        if "SS" in p.restrictions.untradable:
            flags.add("untradable_limit")
        else:
            conc_trim = True

    if ev.candidate:
        for tag in ev.candidate.tags:
            if tag in p.restrictions.exclusions:
                flags.add("exclusion_blocked")
            if tag == "restricted_list":
                flags.add("restricted_list_blocked")

    if shortfall > 0:
        flags.add("liquidity_shortfall")
    if ev.liquidity_event == "locked":
        flags.add("illiquid_locked")
    if (sig and sig.large_inflow) or (ev.inflow / p.portfolio > policy.large_inflow_share):
        flags.add("large_inflow")
    if p.restrictions.crm_risk_mismatch:
        flags.add("profile_conflict")

    adjustment, notes = rebalance.propose(p, w1)
    need = bool(flags & {"drift_breach", "large_inflow", "mandate_breach", "liquidity_shortfall"} or conc_trim
                or ("exclusion_blocked" in flags and ev.inflow > 0))
    breached = {c for c in CLASSES if abs(drifts[c]) > p.band + 1e-9}
    if breached and breached <= set(p.restrictions.untradable) and not (flags & {"mandate_breach", "large_inflow"}):
        need = False                                         # only locked holdings are out of range
    if flags & {"profile_conflict", "exception_on_file", "untradable_limit"} or (certainty and not confirmed):
        need = False                                         # flag only; RM reconciles / client exception applies
    if need:
        size_share = max(flow_size, sum(max(v, 0.0) for v in adjustment.values()) / 100)
    else:
        adjustment, notes = None, []
        size_share = flow_size if confirmed else 0.0

    size = 1 if size_share < policy.size_l2 else (2 if size_share <= policy.size_l3 else 3)
    sens = 2 if flags & SENSITIVITY_2 else 1
    if (sig and sig.sensitive) or "mandate_breach" in flags:
        sens = 3
        if sig and sig.sensitive:
            flags.add("sensitive")
    rev = 3 if ev.irreversible else (2 if "illiquid_locked" in flags else 1)
    f = Factors(size=size, risk_shift=risk, goal=goals.goal_level(after.status, years, policy), sensitivity=sens, reversibility=rev)
    tier = max(f.size, f.risk_shift, f.goal, f.sensitivity, f.reversibility)

    if tier == 1:
        message = "none"
    elif tier == 3 or sens == 3 or p.contact_mode in ("phone_first", "phone_only", "in_person"):
        message = "held"
    else:
        message = "drafted"
    if "profile_conflict" in flags and tier == 2:
        message = "none"

    blocked = [c for c in CLASSES if c in p.restrictions.untradable]
    if p.restrictions.no_new_alts and "AL" not in blocked:
        blocked.append("AL")
    return Analysis(tier=str(tier), flags=sorted(flags), message=message, factors=f, goal_before=before, goal_after=after, goal_driver=driver, suggested_goal_name=suggested_name,
                    max_drift_pts=round(max_drift * 100, 1), band_pts=round(p.band * 100, 1),
                    weights_after={c: round(w1[c] * 100, 1) for c in CLASSES}, drift_pts={c: round(drifts[c] * 100, 1) for c in CLASSES},
                    adjustment=adjustment, adjustment_size_pct=round(size_share * 100, 1), adjustment_notes=notes,
                    must_not_trade=blocked, shortfall_usd=round(shortfall))
