"""Deterministic what-if scenarios. HYPOTHETICAL by construction: explicit assumptions, no forecasts, no probabilities of occurring."""
from __future__ import annotations

from . import goals, rebalance
from .types import CLASSES, ClientProfile, EventInput, Policy

FI_DURATION_YEARS = 6.0          # assumption: price change of fixed income ~ -duration x yield change

PRESETS = [
    ("Equities -10%", {"EQ": -0.10, "SS": -0.10}),
    ("Equities -20% (severe)", {"EQ": -0.20, "SS": -0.20, "AL": -0.08}),
    ("Interest rates +1 percentage point", {"FI": -0.01 * FI_DURATION_YEARS}),
]


def run(p: ClientProfile, policy: Policy | None = None) -> list[dict]:
    policy = policy or Policy()
    out = []
    for name, shocks in PRESETS:
        w1, v1, _, _ = rebalance.apply_event(p, EventInput(shocks=shocks), 0.0, 0.0)
        g = goals.project(w1, v1, p.goal, policy)
        drift = max(abs(w1[c] - p.plan[c]) for c in CLASSES)
        out.append(dict(name=name, hypothetical=True, assumptions=f"instant shock to asset-class prices: {shocks}; fixed-income duration {FI_DURATION_YEARS:g} years",
                        portfolio_change_pct=round((v1 / p.portfolio - 1) * 100, 1), max_drift_pts=round(drift * 100, 1),
                        inside_band=drift <= p.band + 1e-9, goal_status=g.status))
    return out
