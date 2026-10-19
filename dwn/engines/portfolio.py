"""Deterministic portfolio calculations used by the UI (Phase 2). Plain arithmetic, no LLM."""
from __future__ import annotations

CLASS_LABEL = {"EQ": "Equities", "FI": "Bonds", "AL": "Alternatives", "CA": "Cash"}


def drift_points(weights: dict, plan: dict) -> dict:
    """Current minus plan weight, in percentage points, per class."""
    return {c: weights.get(c, 0) - plan.get(c, 0) for c in CLASS_LABEL}


def largest_drift(weights: dict, plan: dict) -> tuple[str, float]:
    d = drift_points(weights, plan)
    k = max(d, key=lambda c: abs(d[c]))
    return k, d[k]


def headline_drift(weights: dict, plan: dict, equity_first_pts: float = 5.0) -> tuple[str, float]:
    """The class to headline in a recommendation: equity when it is off plan by >= 5 pts (the firm's framing is equity risk), else the largest."""
    d = drift_points(weights, plan)
    if abs(d["EQ"]) >= equity_first_pts:
        return "EQ", d["EQ"]
    return largest_drift(weights, plan)


def holding_shares(holdings: list) -> list:
    """[(asset, asset_class, value_musd, share_pct)] with shares summing to 100 (rounded to 0.1)."""
    total = sum(h[2] for h in holdings) or 1.0
    return [(a, cl, v, round(v / total * 100, 1)) for a, cl, v in holdings]


def money_m(v: float) -> str:
    return f"${v:.1f}M"


def money(v: float) -> str:
    return f"${v:,.0f}"
