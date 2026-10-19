"""Event application and rebalance proposals. Pure arithmetic; no LLM, no order is ever created."""
from __future__ import annotations

from .types import CLASSES, ClientProfile, EventInput, Weights


def apply_event(p: ClientProfile, ev: EventInput, inflow: float, outflow: float) -> tuple[Weights, float, float, float]:
    """Return (weights after, value after, cash-flow size as share of portfolio, cash shortfall in USD)."""
    amounts = {c: p.weights[c] * p.portfolio for c in CLASSES}
    for c, move in ev.shocks.items():
        amounts[c] *= 1 + move
    cash_before = amounts["CA"]
    amounts["CA"] += inflow - outflow
    shortfall = max(0.0, (outflow - inflow) - p.weights["CA"] * p.portfolio)
    if amounts["CA"] < 0:                         # outflow larger than cash: fund the rest pro-rata from tradable classes
        short = -amounts["CA"]
        amounts["CA"] = 0.0
        tradable = [c for c in CLASSES if c not in p.restrictions.untradable and c != "CA"]
        base = sum(amounts[c] for c in tradable)
        for c in tradable:
            amounts[c] -= short * amounts[c] / base
    value = sum(amounts.values())
    return {c: amounts[c] / value for c in CLASSES}, value, (inflow + outflow) / p.portfolio, shortfall


def propose(p: ClientProfile, w: Weights) -> tuple[dict[str, float], list[str]]:
    """Move tradable classes back toward plan. Locked holdings stay put; 'no new alternatives' suppresses buys of AL."""
    fixed = [c for c in CLASSES if c in p.restrictions.untradable]
    fixed_w = sum(w[c] for c in fixed)
    tradable = [c for c in CLASSES if c not in fixed]
    plan_sum = sum(p.plan[c] for c in tradable)
    target = {c: p.plan[c] * (1 - fixed_w) / plan_sum for c in tradable}
    target.update({c: w[c] for c in fixed})
    notes: list[str] = []
    if p.restrictions.no_new_alts and target["AL"] > w["AL"]:
        excess = target["AL"] - w["AL"]
        target["AL"] = w["AL"]
        others = [c for c in tradable if c != "AL"]
        s = sum(target[c] for c in others)
        for c in others:
            target[c] += excess * target[c] / s
        notes.append("alternatives buy suppressed (client preference: no new alternatives)")
    if fixed:
        notes.append("locked/untradable holdings left unchanged: " + ", ".join(fixed))
    return {c: round((target[c] - w[c]) * 100, 2) for c in CLASSES}, notes


def half(adj: dict[str, float]) -> dict[str, float]:
    return {c: round(v / 2, 2) for c, v in adj.items()}
