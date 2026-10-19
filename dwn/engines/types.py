"""Typed inputs/outputs of the deterministic engines. Weights are FRACTIONS of the portfolio (0.45 = 45%)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

CLASSES = ("EQ", "FI", "CA", "AL", "SS")
CLASS_NAME = {"EQ": "equity", "FI": "fixed income", "CA": "cash", "AL": "alternatives", "SS": "single stock"}
Weights = dict[str, float]


class Policy(BaseModel):
    """Thresholds and market assumptions. PLACEHOLDERS: compliance owns the real values (concept doc s5, s9)."""
    exp_return: dict[str, float] = {"EQ": 0.065, "FI": 0.035, "CA": 0.020, "AL": 0.050, "SS": 0.065}
    vol: dict[str, float] = {"EQ": 0.17, "FI": 0.06, "CA": 0.01, "AL": 0.11, "SS": 0.30}
    correlation: float = 0.5
    z25: float = -0.6745
    concentration_limit: float = 0.10
    max_feed_age_min: int = 20
    bad_tick_diversified: float = 0.25
    bad_tick_single_stock: float = 0.60
    size_l2: float = 0.03
    size_l3: float = 0.10
    goal_l3_years: float = 2.0
    large_inflow_share: float = 0.10


class Goal(BaseModel):
    name: str
    years: float = Field(gt=0, le=60)
    earmark: float = Field(gt=0, le=1.0)          # share of the portfolio funding this goal
    target: float = Field(gt=0)


class Restrictions(BaseModel):
    untradable: list[str] = []
    exclusions: list[str] = []
    mandate_equity_cap: Optional[float] = None
    no_new_alts: bool = False
    conc_exception: bool = False
    crm_risk_mismatch: bool = False


ContactMode = Literal["phone_first", "phone_only", "in_person", "email", "app", "portal"]


class ClientProfile(BaseModel):
    client_id: str
    name: str
    portfolio: float = Field(gt=0)
    plan: Weights
    weights: Weights
    band: float = Field(gt=0, lt=0.5)
    risk_tolerance: str = ""
    risk_capacity: str = ""
    goal: Goal
    restrictions: Restrictions = Restrictions()
    contact_mode: ContactMode = "portal"
    consent: bool = True

    @field_validator("plan", "weights")
    @classmethod
    def _weights(cls, v):
        if set(v) != set(CLASSES) or any(x < 0 for x in v.values()) or abs(sum(v.values()) - 1.0) > 0.011:
            raise ValueError("weights must cover EQ/FI/CA/AL/SS, be >= 0 and sum to 100%")
        return v


class Signal(BaseModel):
    """A candidate signal extracted from an advisor note. It never changes the client profile until the RM confirms it."""
    kind: Literal["life_event", "client_request"]
    certainty: Literal["confirmed", "possible", "not_client"]
    new_years: Optional[float] = None
    new_target: Optional[float] = None
    new_goal: Optional[Goal] = None
    sensitive: bool = False
    large_inflow: bool = False


class Candidate(BaseModel):
    name: str
    tags: list[str] = []


class EventInput(BaseModel):
    shocks: dict[str, float] = {}
    inflow: float = 0.0
    outflow: float = 0.0
    feed_age_min: float = 0.0
    data_issue: Optional[Literal["missing_price", "sources_disagree", "currency_mismatch"]] = None
    note_text: str = ""
    signal: Optional[Signal] = None
    candidate: Optional[Candidate] = None
    liquidity_event: Optional[Literal["locked"]] = None
    irreversible: bool = False

    @model_validator(mode="after")
    def _classes(self):
        bad = set(self.shocks) - set(CLASSES)
        if bad:
            raise ValueError(f"unknown asset class in shocks: {sorted(bad)}")
        return self


class Factors(BaseModel):
    size: int
    risk_shift: int
    goal: int
    sensitivity: int
    reversibility: int


class GoalOutcome(BaseModel):
    status: Literal["on track", "at risk", "off track"]
    median: float
    p25: float
    sigma: float


class Analysis(BaseModel):
    """Everything the deterministic engines and controls decided about one event. The LLM only ever sees these facts."""
    tier: Literal["1", "2", "3", "Paused"]
    paused_reason: str = ""
    flags: list[str] = []
    message: Literal["none", "drafted", "held"] = "none"
    factors: Optional[Factors] = None
    goal_before: Optional[GoalOutcome] = None
    goal_after: Optional[GoalOutcome] = None
    goal_driver: str = "existing"                      # existing | suggested (the status comes from a suggested new goal)
    suggested_goal_name: str = ""
    max_drift_pts: Optional[float] = None
    band_pts: Optional[float] = None
    weights_after: Optional[Weights] = None
    drift_pts: Optional[Weights] = None
    adjustment: Optional[dict[str, float]] = None          # weight deltas in points (+ buy / - sell); None = no adjustment proposed
    adjustment_size_pct: float = 0.0
    adjustment_notes: list[str] = []
    must_not_trade: list[str] = []
    shortfall_usd: float = 0.0
    scenario_assumptions: dict = {}
