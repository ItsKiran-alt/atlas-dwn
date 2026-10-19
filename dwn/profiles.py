"""Structured Client Context Model inputs (concept doc s5) for every seeded client. Synthetic; used by the engines."""
from __future__ import annotations

import re

from .domain import Client
from .repo import Repo

ORDER = ("EQ", "FI", "CA", "AL", "SS")


def _golden_profile(c: Client) -> dict:
    from scenarios import CLIENTS as G          # golden/scenarios.py (path added by dwn.seed)
    g = G[c.golden_key]
    return dict(client_id=c.id, plan5={k: round(g["plan"][k] * 100, 2) for k in ORDER}, weights5={k: round(g["weights"][k] * 100, 2) for k in ORDER},
                portfolio_usd=float(g["portfolio"]), band_pts=g["band"] * 100, risk_tolerance=g["risk"], risk_capacity=g["capacity"],
                goal_name=g["goal"]["name"], goal_years=float(g["goal"]["years"]), goal_earmark=float(g["goal"]["earmark"]), goal_target_usd=float(g["goal"]["target"]),
                restrictions=dict(untradable=g.get("untradable", []), exclusions=g.get("exclusions", []), mandate_equity_cap=g.get("mandate_equity_cap"),
                                  no_new_alts=g.get("no_new_alts", False), conc_exception=g.get("conc_exception", False), crm_risk_mismatch=g.get("crm_risk_mismatch", False)),
                contact_mode=g["contact"])


def _parse_goal(c: Client) -> tuple[str, float, float]:
    if c.goals:
        gl = c.goals[0]
        m = re.search(r"\$([\d.]+)\s*(M|k)?\s*·\s*(\d+(?:\.\d+)?)\s*years", gl.detail)
        if m:
            amt = float(m.group(1)) * (1_000_000 if (m.group(2) or "").upper() == "M" else 1_000 if m.group(2) == "k" else 1)
            return gl.name, float(m.group(3)), amt
        return gl.name, 10.0, c.aum_musd * 1_000_000 * 1.5
    return "Long-term growth", 10.0, c.aum_musd * 1_000_000 * 1.5


def build_profile(c: Client) -> dict | None:
    if c.source == "golden":
        return _golden_profile(c)
    if c.source == "portal" or c.aum_musd <= 0:
        return None                                    # new portal clients have no structured profile yet: the agent abstains
    tot = sum(c.weights.get(k, 0) for k in ("EQ", "FI", "CA", "AL")) or 100
    w5 = {k: round(c.weights.get(k, 0) / tot * 100, 2) for k in ("EQ", "FI", "CA", "AL")}
    w5["SS"] = 0.0
    ptot = sum(c.plan.get(k, 0) for k in ("EQ", "FI", "CA", "AL")) or 100
    p5 = {k: round(c.plan.get(k, 0) / ptot * 100, 2) for k in ("EQ", "FI", "CA", "AL")}
    p5["SS"] = 0.0
    name, years, target = _parse_goal(c)
    return dict(client_id=c.id, plan5=p5, weights5=w5, portfolio_usd=c.aum_musd * 1_000_000, band_pts=5.0, risk_tolerance=c.risk_profile, risk_capacity="Moderate",
                goal_name=name, goal_years=years, goal_earmark=1.0, goal_target_usd=target, restrictions={}, contact_mode="portal")


def ensure_profiles(repo: Repo) -> int:
    n = 0
    for c in repo.list_clients(include_all=True):
        if repo.get_profile(c.id) is None:
            d = build_profile(c)
            if d:
                repo.upsert_profile(d)
                n += 1
    return n
