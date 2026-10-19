"""Goal projection: lognormal approximation with a flat pairwise correlation (concept doc s5).

On track: the 25th-percentile outcome at the goal date meets the target. At risk: only the median does.
Off track: even the median falls short. A planning range, never a forecast.
"""
from __future__ import annotations

import math

from .types import CLASSES, GoalOutcome, Goal, Policy, Weights


def project(weights: Weights, portfolio: float, goal: Goal, policy: Policy, years: float | None = None, target: float | None = None) -> GoalOutcome:
    yrs = goal.years if years is None else years
    tgt = goal.target if target is None else target
    mu = sum(weights[c] * policy.exp_return[c] for c in CLASSES)
    var = 0.0
    for i in CLASSES:
        for j in CLASSES:
            rho = 1.0 if i == j else policy.correlation
            var += weights[i] * weights[j] * policy.vol[i] * policy.vol[j] * rho
    sigma = math.sqrt(var)
    median = portfolio * goal.earmark * math.exp((mu - 0.5 * var) * yrs)
    p25 = median * math.exp(policy.z25 * sigma * math.sqrt(yrs))
    status = "on track" if p25 >= tgt else ("at risk" if median >= tgt else "off track")
    return GoalOutcome(status=status, median=round(median), p25=round(p25), sigma=round(sigma, 4))


_ORDER = ["on track", "at risk", "off track"]


def worse(a: GoalOutcome, b: GoalOutcome) -> GoalOutcome:
    return b if _ORDER.index(b.status) > _ORDER.index(a.status) else a


def goal_level(status: str, years: float, policy: Policy) -> int:
    if status == "on track":
        return 1
    if status == "off track":
        return 3
    return 3 if years <= policy.goal_l3_years else 2
