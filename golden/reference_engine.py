"""Independent reference implementation of the DWN tier framework (PDF section 5).

Used ONLY to check the golden data set for internal consistency. The production
engines in dwn/engines/ will be written separately and tested against the golden set.
All thresholds are illustrative placeholders (PDF s5, s12) for AWM compliance to set.
"""
from __future__ import annotations

import math
import re

CLASSES = ["EQ", "FI", "CA", "AL", "SS"]
CLASS_NAMES = {"EQ": "Equity", "FI": "Fixed income", "CA": "Cash", "AL": "Alternatives", "SS": "Single stock"}

ASSUMPTIONS = {
    "return": {"EQ": 0.065, "FI": 0.035, "CA": 0.020, "AL": 0.050, "SS": 0.065},
    "vol": {"EQ": 0.17, "FI": 0.06, "CA": 0.01, "AL": 0.11, "SS": 0.30},
    "correlation": 0.5,
    "z25": -0.6745,                 # 25th percentile of the standard normal
    "concentration_limit": 0.10,    # single holding, share of portfolio
    "max_feed_age_min": 20,
    "bad_tick": {"diversified": 0.25, "single_stock": 0.60},   # one-update move
    "size_l2": 0.03, "size_l3": 0.10,                          # PDF s5
    "goal_l3_years": 2.0,                                      # PDF s5
}

INJECTION_PATTERNS = [
    r"ignore (all|any|previous|prior) (rules|instructions)",
    r"system (note|prompt|message)\b.*\b(ai|assistant|model)",
    r"\b(assistant|ai)\s*[:,]\s*(transfer|sell|buy|approve|send|disable)",
    r"disregard .*(polic|rule|control)",
    r"you are now",
    r"override .*(approval|compliance|control)",
]


def scan_untrusted_text(text: str) -> bool:
    t = (text or "").lower()
    return any(re.search(p, t) for p in INJECTION_PATTERNS)


def goal_projection(weights: dict, value: float, years: float, earmark: float, target: float) -> dict:
    """Lognormal approximation with a flat pairwise correlation."""
    a = ASSUMPTIONS
    mu = sum(weights[c] * a["return"][c] for c in CLASSES)
    var = 0.0
    for i in CLASSES:
        for j in CLASSES:
            rho = 1.0 if i == j else a["correlation"]
            var += weights[i] * weights[j] * a["vol"][i] * a["vol"][j] * rho
    sigma = math.sqrt(var)
    funded = value * earmark
    median = funded * math.exp((mu - 0.5 * var) * years)
    p25 = median * math.exp(a["z25"] * sigma * math.sqrt(years))
    if p25 >= target:
        status = "on track"
    elif median >= target:
        status = "at risk"
    else:
        status = "off track"
    return {"status": status, "median": round(median), "p25": round(p25), "sigma": round(sigma, 4)}


def goal_level(status: str, years: float) -> int:
    if status == "on track":
        return 1
    if status == "off track":
        return 3
    return 3 if years <= ASSUMPTIONS["goal_l3_years"] else 2


def _weights_after(client: dict, event: dict):
    """Return (new_weights, new_value, size_from_event) after applying the event."""
    v0 = client["portfolio"]
    amounts = {c: client["weights"][c] * v0 for c in CLASSES}
    for c, m in (event.get("shocks") or {}).items():
        amounts[c] *= 1 + m
    inflow = event.get("inflow", 0.0)
    outflow = event.get("outflow", 0.0)
    amounts["CA"] += inflow - outflow
    # An outflow larger than cash is funded pro-rata from tradable classes, cash floor at 0.
    if amounts["CA"] < 0:
        short = -amounts["CA"]
        amounts["CA"] = 0.0
        tradable = [c for c in CLASSES if c not in client["untradable"] and c != "CA"]
        base = sum(amounts[c] for c in tradable)
        for c in tradable:
            amounts[c] -= short * amounts[c] / base
    v1 = sum(amounts.values())
    return {c: amounts[c] / v1 for c in CLASSES}, v1, (inflow + outflow) / v0, short_amount(amounts, client, event)


def short_amount(amounts, client, event):
    cash0 = client["weights"]["CA"] * client["portfolio"]
    out = event.get("outflow", 0.0) - event.get("inflow", 0.0)
    return max(0.0, out - cash0)


def propose_trades(client: dict, w: dict):
    """Restore tradable classes toward plan. Returns (trades_as_weight_deltas, notes)."""
    plan = client["plan"]
    fixed = [c for c in CLASSES if c in client["untradable"]]
    fixed_w = sum(w[c] for c in fixed)
    tradable = [c for c in CLASSES if c not in fixed]
    plan_sum = sum(plan[c] for c in tradable)
    target = {c: plan[c] * (1 - fixed_w) / plan_sum for c in tradable}
    target.update({c: w[c] for c in fixed})
    notes = []
    if client.get("no_new_alts") and "AL" in target and target["AL"] > w["AL"]:
        excess = target["AL"] - w["AL"]
        target["AL"] = w["AL"]
        others = [c for c in tradable if c != "AL"]
        s = sum(target[c] for c in others)
        for c in others:
            target[c] += excess * target[c] / s
        notes.append("alternatives buy suppressed (client preference)")
    return {c: target[c] - w[c] for c in CLASSES}, notes


def evaluate(client: dict, event: dict) -> dict:
    A = ASSUMPTIONS
    flags: set[str] = set()
    paused = None
    result: dict = {"flags": flags}

    # ---- control layer: order follows PDF s9 (consent first) ----
    if not client["consent"]:
        paused = "no_consent"
    elif event.get("feed_age_min", 0) > A["max_feed_age_min"]:
        paused = "stale_data"
    elif event.get("data_issue") in ("missing_price", "sources_disagree", "currency_mismatch"):
        paused = {"missing_price": "missing_data", "sources_disagree": "sources_disagree",
                  "currency_mismatch": "currency_mismatch"}[event["data_issue"]]
    elif any(abs(m) > (A["bad_tick"]["single_stock"] if c == "SS" else A["bad_tick"]["diversified"])
             for c, m in (event.get("shocks") or {}).items()):
        paused = "implausible_data"
    elif scan_untrusted_text(event.get("note_text", "")):
        paused = "security_injection"

    if paused:
        flags.add(paused)
        result.update(tier="Paused", message="none", trades="none", goal_before=None, goal_after=None,
                      max_drift_pts=None, band_pts=client["band"] * 100, factors=None)
        return result

    sig = event.get("signal") or {}
    certainty = sig.get("certainty")
    if certainty == "possible":
        flags.add("possible_life_event")
    elif certainty == "not_client":
        flags.add("not_attributed_to_client")
    confirmed = certainty == "confirmed"
    if confirmed:
        flags.add("client_request" if sig.get("kind") == "client_request" else "confirmed_life_event")

    # an unconfirmed or non-client signal never changes the numbers
    ev = dict(event)
    if certainty and not confirmed:                # an unconfirmed note never moves money; a known contribution does
        ev.pop("inflow", None); ev.pop("outflow", None)

    w0 = client["weights"]
    g = client["goal"]
    before = goal_projection(w0, client["portfolio"], g["years"], g["earmark"], g["target"])
    w1, v1, flow_size, shortfall = _weights_after(client, ev)

    years = g["years"]; target = g["target"]
    if confirmed and sig.get("new_years") is not None:
        years = sig["new_years"]
    if confirmed and sig.get("new_target") is not None:
        target = sig["new_target"]
    if confirmed and sig.get("new_goal"):
        flags.add("suggested_goal")
    after = goal_projection(w1, v1, years, g["earmark"], target)
    if sig.get("new_goal"):
        ng = sig["new_goal"]
        gp = goal_projection(w1, v1, ng["years"], ng["earmark"], ng["target"])
        order = ["on track", "at risk", "off track"]
        if order.index(gp["status"]) > order.index(after["status"]):
            after = {**after, "status": gp["status"], "from_new_goal": True}
    if after["status"] != "on track":
        flags.add("goal_at_risk")

    # ---- risk shift ----
    drifts = {c: (w1[c] - client["plan"][c]) for c in CLASSES}
    max_drift = max(abs(d) for d in drifts.values())
    band = client["band"]
    rs = 1 if max_drift <= band + 1e-9 else (2 if max_drift <= 2 * band + 1e-9 else 3)
    if max_drift > band + 1e-9:
        flags.add("drift_breach")
    cap = client.get("mandate_equity_cap")
    if cap is not None and w1["EQ"] > cap + 1e-9:
        flags.add("mandate_breach"); rs = 3

    # ---- concentration ----
    ss_move = (ev.get("shocks") or {}).get("SS", 0.0)
    conc_trim = False
    if w1["SS"] > A["concentration_limit"] + 1e-9 and ss_move != 0:
        flags.add("concentration")
        if client.get("conc_exception"):
            flags.add("exception_on_file")
        conc_trim = "SS" not in client["untradable"]
    if w1["SS"] > A["concentration_limit"] + 1e-9 and "SS" in client["untradable"] and ss_move != 0:
        flags.add("untradable_limit")

    # ---- candidate restrictions ----
    cand = ev.get("candidate")
    if cand:
        for tag in cand["tags"]:
            if tag in client["exclusions"]:
                flags.add("exclusion_blocked")
            if tag == "restricted_list":
                flags.add("restricted_list_blocked")

    # ---- liquidity ----
    if shortfall > 0:
        flags.add("liquidity_shortfall")
    if ev.get("liquidity_event") == "locked":
        flags.add("illiquid_locked")
    if sig.get("large_inflow") or (ev.get("inflow", 0) / client["portfolio"] > 0.10):
        flags.add("large_inflow")
    if client.get("crm_risk_mismatch"):
        flags.add("profile_conflict")

    # ---- trade proposal and size ----
    trades, notes = propose_trades(client, w1)
    need_trade = bool(
        "drift_breach" in flags or conc_trim or "large_inflow" in flags or "mandate_breach" in flags
        or "liquidity_shortfall" in flags or ("exclusion_blocked" in flags and ev.get("inflow", 0) > 0)
    )
    breached = {c for c in CLASSES if abs(drifts[c]) > band + 1e-9}
    if breached and breached <= set(client["untradable"]) and not (flags & {"mandate_breach", "large_inflow"}):
        need_trade = False                          # only locked holdings are out of range
    if flags & {"profile_conflict", "exception_on_file", "untradable_limit"} or (certainty and not confirmed):
        need_trade = False                          # flag only; RM reconciles / client exception applies
    if need_trade:
        sized = sum(max(d, 0.0) for d in trades.values())
        size_l = max(flow_size, sized)
    else:
        trades = None
        sized = 0.0
        size_l = flow_size if confirmed else 0.0
    size = 1 if size_l < A["size_l2"] else (2 if size_l <= A["size_l3"] else 3)

    # ---- sensitivity and reversibility ----
    sens = 1
    if flags & {"confirmed_life_event", "concentration", "untradable_limit", "illiquid_locked",
                "exclusion_blocked", "restricted_list_blocked", "profile_conflict"}:
        sens = 2
    if sig.get("sensitive") or "mandate_breach" in flags:
        sens = 3
        if sig.get("sensitive"):
            flags.add("sensitive")
    rev = 3 if ev.get("irreversible") else (2 if "illiquid_locked" in flags else 1)

    factors = {"size": size, "risk_shift": rs, "goal": goal_level(after["status"], years),
               "sensitivity": sens, "reversibility": rev}
    tier = max(factors.values())

    # ---- client message routing ----
    pref = client["contact"]
    if tier == 1:
        message = "none"
    elif tier == 3 or sens == 3 or pref in ("phone_first", "phone_only", "in_person"):
        message = "held"
    else:
        message = "drafted"
    if "profile_conflict" in flags and tier == 2:
        message = "none"

    result.update(
        tier=tier, message=message, factors=factors,
        goal_before=before["status"], goal_after=after["status"],
        max_drift_pts=round(max_drift * 100, 1), band_pts=round(band * 100, 1),
        trades=("none" if not trades else {c: round(d * 100, 1) for c, d in trades.items() if abs(d) >= 0.0005}),
        trade_size_pct=round(size_l * 100, 1), notes=notes,
        new_weights={c: round(w1[c] * 100, 1) for c in CLASSES},
        goal_detail={"before": before, "after": after},
    )
    return result

