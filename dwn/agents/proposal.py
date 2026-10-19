"""Typed recommendation proposal: the single object an RM reviews. Everything in it traces to evidence rows."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

from ..engines.types import CLASS_NAME, ClientProfile, Analysis


class Trade(BaseModel):
    asset_class: str
    direction: Literal["buy", "sell"]
    points: float
    usd: float


class ControlResult(BaseModel):
    name: str
    status: Literal["pass", "fail", "warn", "n/a"]
    blocking: bool = False
    detail: str = ""


class Proposal(BaseModel):
    title: str
    tier: Literal["1", "2", "3"]
    flags: list[str]
    summary: str                                   # RM note (from the drafter, validated)
    trades: list[Trade] = []
    alternatives: list[dict] = []                  # {name, description, trades}
    benefits: list[str] = []
    risks: list[str] = []
    trade_offs: list[str] = []
    assumptions: list[str] = []
    unresolved: list[str] = []
    scenarios: list[dict] = []
    news_context: list[dict] = []
    client_message: Optional[str] = None
    message_routing: str = "none"
    talking_points: list[str] = []
    checks: list[ControlResult] = []
    evidence_refs: list[str] = []
    approval_path: str = ""
    draft_provider: str = ""
    abstention: str = ""
    requires_rm_confirmation: list[str] = []


def trades_from(adj: dict | None, portfolio: float) -> list[Trade]:
    out = []
    for c, pts in (adj or {}).items():
        if abs(pts) >= 0.05:
            out.append(Trade(asset_class=CLASS_NAME[c], direction="buy" if pts > 0 else "sell", points=round(abs(pts), 1), usd=round(abs(pts) / 100 * portfolio, -2)))
    return sorted(out, key=lambda t: (t.direction, -t.points))


def trade_text(trades: list[Trade]) -> str:
    return "; ".join(f"{t.direction} {t.asset_class} {t.points:g} points (about ${t.usd:,.0f})" for t in trades)


def approval_path(tier: str) -> str:
    return {"1": "No approval: appears in the RM's daily digest.",
            "2": "RM approves, edits or rejects. Any client message is released only by the RM.",
            "3": "RM decision after a conversation with the client, then a second approver. Never automated."}[tier]
