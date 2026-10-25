"""The orchestrator: one explicit, typed monitoring run (concept doc s6; build prompt s5.2).

Order: permission + consent -> client context -> data quality -> notes -> deterministic analysis -> scenarios -> news ->
draft -> output controls -> persist (run, steps, evidence, proposal, audit) -> review item for the RM. Then it STOPS:
only a human decision moves a proposal on. There is no execution code anywhere in this module.

Audit rows, run rows and step rows are written by this deterministic code in the same transaction; no model decides
whether anything is recorded. A step can fail without corrupting the run: non-critical steps degrade, critical ones fail the run.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Optional

from .. import config, services
from ..controls.gates import ABSTENTION
from ..controls.quarantine import scan_untrusted_text
from ..controls.wording import prohibited_language, untraceable_figures
from ..data.market import MarketService
from ..domain import Rec, User, utcnow
from ..engines import scenarios as scenario_engine
from ..engines.pipeline import analyse
from ..engines.types import CLASS_NAME, CLASSES, Analysis, ClientProfile, EventInput, Goal, Policy, Restrictions, Signal
from ..repo import Repo
from .llm import LLM, LLMError, TemplateLLM
from .proposal import ControlResult, Proposal, approval_path, trade_text, trades_from
from .skills import Drafter, EventInterpreter, NotesExtractor, run_skill

MAX_LLM_CALLS_PER_RUN = 4
DUP_WINDOW_S = 600
CRITICAL = {"permission_consent", "client_context", "analysis"}


@dataclass
class RunResult:
    run_id: str
    status: str                                   # completed | paused | failed | duplicate
    tier: str = ""
    paused_reason: str = ""
    proposal_id: str = ""
    analysis: Optional[Analysis] = None
    proposal: Optional[Proposal] = None
    extraction: Optional[object] = None
    notes: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    duplicate_of: str = ""


class _CallLimit:
    """Caps LLM calls per run and counts them against the provider's daily budget."""
    def __init__(self, inner: LLM, repo: Repo | None, limit: int, daily: int):
        self.inner, self.repo, self.limit, self.daily, self.n = inner, repo, limit, daily, 0
        self.name, self.model = inner.name, inner.model

    def complete_json(self, system: str, user: str, max_tokens: int = 900):
        if self.name == "template":
            return self.inner.complete_json(system, user, max_tokens)
        if self.n >= self.limit:
            raise LLMError("budget", "per-run LLM call limit reached")
        if self.repo is not None and self.repo.get_source(self.name) is not None:
            src = self.repo.get_source(self.name)
            if not src["enabled"]:
                raise LLMError("not_configured", f"{self.name} is disabled by an admin")
            if self.repo.bump_source_calls(self.name) > self.daily:
                raise LLMError("budget", "daily LLM call budget used")
        self.n += 1
        return self.inner.complete_json(system, user, max_tokens)


def load_policy(repo: Repo) -> Policy:
    return Policy(**repo.get_policy_overrides())


def build_profile(repo: Repo, client_id: str) -> tuple[Optional[ClientProfile], list[str]]:
    """Client Context agent: typed profile or (None, what is missing). Never invents a missing field."""
    d = repo.get_profile(client_id)
    if d is None:
        return None, ["structured client profile (plan, goal, band, restrictions)"]
    c = repo.list_clients(client_id=client_id)[0]
    try:
        r = d["restrictions"]
        p = ClientProfile(client_id=client_id, name=c.name, portfolio=d["portfolio_usd"], plan={k: v / 100 for k, v in d["plan5"].items()},
                          weights={k: v / 100 for k, v in d["weights5"].items()}, band=d["band_pts"] / 100, risk_tolerance=d["risk_tolerance"],
                          risk_capacity=d["risk_capacity"], goal=Goal(name=d["goal_name"], years=d["goal_years"], earmark=d["goal_earmark"], target=d["goal_target_usd"]),
                          restrictions=Restrictions(**r), contact_mode=d["contact_mode"], consent=repo.has_active_consent(client_id))
    except Exception as e:                       # pydantic validation: malformed or inconsistent stored profile
        return None, [f"profile failed validation: {str(e)[:120]}"]
    return p, []


REQUIRED_QUOTES = {"EQ": "SPY", "FI": "AGG", "AL": "VNQ"}


def build_market_event(repo: Repo, policy: Policy) -> tuple[EventInput, dict]:
    """Turn the cached real quotes into an event. Missing/stale data is passed on as such, never replaced."""
    view = {r["symbol"]: r for r in MarketService(repo).view()}
    shocks, used, worst_age = {}, [], 0.0
    issue = None
    for cls, sym in REQUIRED_QUOTES.items():
        q = view.get(sym)
        if not q or not q["available"] or q.get("change_pct") is None:
            issue = "missing_price"
            continue
        used.append(dict(symbol=sym, price=q["price"], change_pct=round(q["change_pct"], 3), market_time=q["market_time"], retrieved_at=q["retrieved_at"],
                         provider=q["provider"], source_url=q["source_url"], freshness=q["freshness"]))
        if q["freshness"] == "stale":
            age = (utcnow() - q["market_time"]).total_seconds() / 60
            worst_age = max(worst_age, age)
        elif q["freshness"] == "unavailable":
            issue = "missing_price"
        shocks[cls] = q["change_pct"] / 100
    return EventInput(shocks=shocks, feed_age_min=worst_age, data_issue=issue), dict(quotes=used)


def _hash(profile: ClientProfile, ev: EventInput, policy: Policy) -> str:
    blob = json.dumps(dict(p=profile.model_dump(), e=ev.model_dump(), pol=policy.model_dump()), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _facts(p: ClientProfile, a: Analysis, rm_name: str, trades) -> dict:
    return dict(client_first=p.name.split()[0], rm_name=rm_name, tier=a.tier, flags=a.flags, goal_name=p.goal.name, goal_years=p.goal.years, goal_months=round(p.goal.years * 12),
                goal_target=p.goal.target, goal_before=a.goal_before.status, goal_after=a.goal_after.status, goal_driver=a.goal_driver, suggested_goal_name=a.suggested_goal_name, band_pts=a.band_pts, max_drift_pts=a.max_drift_pts,
                weights_after_pct=a.weights_after, plan_pct={k: round(v * 100, 1) for k, v in p.plan.items()}, drift_pts=a.drift_pts,
                adjustment_text=trade_text(trades), trades=[t.model_dump() for t in trades], shortfall_usd=a.shortfall_usd, portfolio_usd=p.portfolio,
                contact_mode=p.contact_mode, contact_text={"phone_first": "phone call first", "phone_only": "phone only", "in_person": "in person only"}.get(p.contact_mode, p.contact_mode),
                message_routing=a.message, sensitive="sensitive" in a.flags)


class _Steps:
    def __init__(self, repo: Repo, run_id: str):
        self.repo, self.run_id, self.seq, self.log = repo, run_id, 0, []

    def run(self, name: str, fn: Callable, *, critical: bool = False, default=None):
        self.seq += 1
        t0 = utcnow()
        try:
            out = fn()
            self.repo.add_step(self.run_id, self.seq, name, "ok", t0, utcnow(), out if isinstance(out, dict) else {"result": str(out)[:500]})
            self.log.append(dict(name=name, status="ok"))
            return out
        except services.Denied:
            raise
        except Exception as e:
            self.repo.add_step(self.run_id, self.seq, name, "failed", t0, utcnow(), {}, f"{type(e).__name__}: {e}")
            self.log.append(dict(name=name, status="failed", error=f"{type(e).__name__}: {e}"))
            if critical:
                raise
            return default

    def skip(self, name: str, why: str):
        self.seq += 1
        t = utcnow()
        self.repo.add_step(self.run_id, self.seq, name, "skipped", t, t, {"reason": why})
        self.log.append(dict(name=name, status="skipped", reason=why))


def run_monitoring(repo: Repo, user: User, client_id: str, *, event: EventInput | None = None, trigger: str = "manual", llm: LLM | None = None,
                   rm_inputs: dict | None = None, force: bool = False, scopes: set | None = None) -> RunResult:
    S = set(scopes) if scopes else None                                  # None = everything (manual run); a schedule passes its workflow scope
    services.require_role(user, "RM", "Admin")
    client = services.get_client(repo, user, client_id)                        # authorisation: raises Denied before anything is recorded
    policy = load_policy(repo)
    base_llm = llm or TemplateLLM()
    limited = _CallLimit(base_llm, repo, MAX_LLM_CALLS_PER_RUN, config.LLM_DAILY_BUDGET)
    rm_name = next((r.name for r in repo.list_rms() if r.id == client.rm_id), user.name)

    profile, missing = build_profile(repo, client_id)
    market_info: dict = {}
    if event is None:
        event, market_info = build_market_event(repo, policy)
        # the RM's latest adviser note (last 90 days) is read like any other input: only for consented clients, and only when this run covers goal progress.
        # It is untrusted text: the gates below quarantine instruction-like text, and a life-event signal is a SUGGESTION the RM must confirm.
        if (S is None or "Goal progress" in S) and repo.has_active_consent(client_id):
            note = repo.latest_note_text(client_id)
            if note:
                event = event.model_copy(update=dict(note_text=note))

    # duplicate-run protection (also used by the scheduler): same inputs within the window reuse the earlier run
    ihash = _hash(profile, event, policy) if profile else hashlib.sha256(f"{client_id}|noprofile|{json.dumps(missing)}".encode()).hexdigest()
    if not force:
        prior = repo.recent_run_by_hash(client_id, ihash, DUP_WINDOW_S)
        if prior:
            return RunResult(run_id=prior, status="duplicate", duplicate_of=prior, notes=["identical inputs were analysed moments ago; reusing that run"])

    run_id = uuid.uuid4().hex[:16]
    repo.create_run(run_id, client_id, trigger, user.name, ihash, base_llm.name)
    repo.log(client.name, "Agent run started", "Orchestrator", f"trigger={trigger}; run {run_id}", "Logged", "AI", client_id=client_id)
    st = _Steps(repo, run_id)
    res = RunResult(run_id=run_id, status="running")
    status, tier, paused = "failed", "", ""
    freshness: dict = {}
    try:
        # 1 ---- permission and consent (the gate that runs first)
        def s_consent():
            return dict(consent=repo.has_active_consent(client_id), role=user.role, client=client.name)
        st.run("permission_consent", s_consent, critical=True)

        # 2 ---- client context
        def s_context():
            if profile is None:
                raise ValueError("; ".join(missing))
            stale = (utcnow() - (repo.get_profile(client_id)["updated_at"])) > timedelta(days=365)
            return dict(profile_ok=True, goal=profile.goal.name, band_pts=round(profile.band * 100, 1), warnings=(["client profile is older than 12 months"] if stale else []))
        try:
            st.run("client_context", s_context, critical=True)
        except Exception:
            paused = "incomplete_profile"
            res.analysis = Analysis(tier="Paused", paused_reason=paused, flags=[paused])

        if not paused:
            # 3 ---- data quality (market event provenance) and 4 ---- notes
            st.run("data_quality", lambda: dict(feed_age_min=round(event.feed_age_min, 1), data_issue=event.data_issue, **market_info))
            freshness = dict(feed_age_min=event.feed_age_min, issue=event.data_issue, quotes=market_info.get("quotes", []))
            extraction = None
            if event.note_text and event.signal is None:
                if scan_untrusted_text(event.note_text):
                    st.skip("notes_extraction", "instruction-like text: quarantined, not shown to any model")
                else:
                    def s_notes():
                        r = run_skill(NotesExtractor(), limited, {"note_text": event.note_text})
                        res.notes.extend(r.notes)
                        return dict(provider=r.provider, used_fallback=r.used_fallback, extraction=r.output.model_dump())
                    out = st.run("notes_extraction", s_notes)
                    if out:
                        from .skills import NotesExtraction
                        extraction = NotesExtraction(**out["extraction"])
            res.extraction = extraction
            ev = event
            needs_input: list[str] = []
            if extraction and extraction.relevant:
                ng = extraction.new_goal
                supplied = (rm_inputs or {}).get("new_goal")
                if not ng and extraction.new_goal_topic:
                    if supplied:
                        ng = Goal(name=extraction.new_goal_topic, **supplied)             # RM-entered numbers, never model-invented
                    else:
                        needs_input = list(extraction.needs_rm_input)
                sig = Signal(kind=extraction.kind, certainty=extraction.certainty, new_years=extraction.new_years, new_target=extraction.new_target,
                             new_goal=Goal(name=extraction.new_goal_topic or "Suggested goal", years=ng.years, earmark=ng.earmark, target=ng.target) if ng else None,
                             sensitive=extraction.sensitive, large_inflow=extraction.large_inflow)
                ev = event.model_copy(update=dict(signal=sig, inflow=event.inflow or extraction.inflow, outflow=event.outflow or extraction.outflow))
            elif extraction and not extraction.relevant:
                pass

            # 5 ---- deterministic analysis (gates -> engines -> flags -> tier)
            a = st.run("analysis", lambda: analyse(profile, ev, policy).model_dump(), critical=True)
            analysis = Analysis(**a)
            res.analysis = analysis
            if analysis.tier == "Paused":
                paused = analysis.paused_reason
            else:
                # 6 ---- scenarios (hypothetical)
                if analysis.tier in ("2", "3") and (S is None or "Risk & scenarios" in S):
                    scen = st.run("scenarios", lambda: {"scenarios": scenario_engine.run(profile, policy)}, default={"scenarios": []})["scenarios"]
                else:
                    scen = []
                    if S is not None and "Risk & scenarios" not in S:
                        st.skip("scenarios", "not in this schedule's workflow scope")
                # 7 ---- news interpretation
                if S is None or "Market events" in S:
                    news_ctx = st.run("news_interpretation", lambda: _news(repo, limited, profile, res), default={"items": []})["items"]
                else:
                    news_ctx = []
                    st.skip("news_interpretation", "not in this schedule's workflow scope")
                if S is not None and "RM draft recommendations" not in S:
                    # analysis only: evidence is recorded, but no draft, no proposal and no review item is created
                    st.skip("draft", "not in this schedule's workflow scope")
                    st.run("persist", lambda: (_evidence(repo, run_id, profile, analysis, market_info, news_ctx, extraction, [], policy, event), dict(proposal=None, reason="analysis only"))[1])
                    repo.log(client.name, "Analysis recorded", "Orchestrator", f"Tier {analysis.tier}; no draft recommendation (not in this schedule's scope)", "Logged", "AI", client_id=client_id)
                    tier = analysis.tier
                    status = "completed"
                    res.status, res.tier = status, tier
                    res.steps = st.log
                    return res                                  # the finally block records the run as completed
                # 8 ---- draft
                trades = trades_from(analysis.adjustment, profile.portfolio)
                facts = _facts(profile, analysis, rm_name, trades)
                draft = st.run("draft", lambda: _draft(limited, facts, res), default=None)
                # 9 ---- output controls
                checks = st.run("controls", lambda: {"checks": [c.model_dump() for c in _controls(profile, analysis, trades, facts, draft)]}, critical=False, default={"checks": []})["checks"]
                checks = [ControlResult(**c) for c in checks]
                blocked = any(c.status == "fail" and c.blocking for c in checks)
                proposal = _compose(profile, analysis, trades, facts, draft, scen, news_ctx, checks, needs_input, extraction, ev)
                res.proposal = proposal
                # 10 ---- persist proposal, evidence, review item
                pid = uuid.uuid4().hex[:16]

                def s_persist():
                    pstatus = "blocked" if blocked else ("digest" if analysis.tier == "1" else "awaiting_rm")
                    second = _pick_second_approver(repo, client.rm_id) if analysis.tier == "3" else ""
                    repo.create_proposal(pid, run_id, client_id, analysis.tier, proposal.title, proposal.model_dump(), pstatus, second)
                    _evidence(repo, run_id, profile, analysis, market_info, news_ctx, extraction, checks, policy, event)
                    _update_rec(repo, client, proposal, pstatus, analysis)
                    repo.log(client.name, "Proposal created", "Orchestrator", f"Tier {analysis.tier}: {proposal.title}; status {pstatus}; evidence {len(proposal.evidence_refs)} items", "Review" if pstatus != "digest" else "Logged", "AI", client_id=client_id)
                    if pstatus == "awaiting_rm":
                        repo.log(client.name, "Review item created", "Workflow", f"Awaiting RM decision ({approval_path(analysis.tier)})", "Pending", "RM", client_id=client_id)
                    return dict(proposal_id=pid, status=pstatus)
                st.run("persist", s_persist, critical=True)
                res.proposal_id = pid
                tier = analysis.tier

        if paused:
            tier = "Paused"
            _record_pause(repo, client, user, run_id, paused, st, res)
        status = "paused" if paused else "completed"
        res.status, res.tier, res.paused_reason = status, tier, paused
    except services.Denied:
        raise
    except Exception as e:                                           # critical step failure: the run fails, nothing half-written is presented
        status = "failed"
        res.status = "failed"
        res.notes.append(f"{type(e).__name__}: {e}")
        repo.log(client.name, "Agent run failed", "Orchestrator", f"{type(e).__name__}: {str(e)[:200]}", "Review", "AI", client_id=client_id)
    finally:
        repo.finish_run(run_id, status, tier, paused, freshness, error="; ".join(res.notes)[:400] if status == "failed" else "")
        repo.log(client.name, f"Agent run {status}", "Orchestrator", f"run {run_id}; tier {tier or '-'}" + (f"; paused: {paused}" if paused else ""), "Logged", "AI", client_id=client_id)
    res.steps = st.log
    return res


# --------------------------------------------------------------------------- helpers
def _news(repo: Repo, llm, profile: ClientProfile, res: RunResult) -> dict:
    items = [n for n in repo.list_news(limit=8) if not n.quarantined]
    if not items:
        return dict(items=[])
    heads = [dict(publisher=n.publisher, title=n.title) for n in items]
    r = run_skill(EventInterpreter(), llm, {"headlines": heads})
    res.notes.extend(r.notes)
    held = {c for c in CLASSES if profile.weights[c] > 0}
    out = []
    for it in r.output.items:
        if it.relevance in ("high", "medium") and set(it.affected_classes) & held:
            n = items[it.index]
            out.append(dict(publisher=n.publisher, title=n.title, link=n.link, published_at=str(n.published_at), classes=it.affected_classes, relevance=it.relevance,
                            fact=it.confirmed_fact, interpretation=it.interpretation, provider=r.provider))
    return dict(items=out)


def _draft(llm, facts: dict, res: RunResult):
    r = run_skill(Drafter(), llm, {"facts": facts})
    res.notes.extend(r.notes)
    d = r.output
    text = d.rm_note + " " + (d.client_message or "") + " " + " ".join(d.talking_points)
    if prohibited_language(text) or untraceable_figures(text, facts):        # defence in depth: also checks the template path
        return None
    return dict(draft=d.model_dump(), provider=r.provider, used_fallback=r.used_fallback)


def _controls(p: ClientProfile, a: Analysis, trades, facts: dict, draft: dict | None) -> list[ControlResult]:
    c: list[ControlResult] = [ControlResult(name="Monitoring consent on file", status="pass", blocking=True),
                              ControlResult(name="Market data fresh and plausible", status="pass", blocking=True, detail="feed age within the limit; prices plausible")]
    bad = [t for t in trades if t.asset_class in [CLASS_NAME[x] for x in p.restrictions.untradable]]
    nonew = [t for t in trades if p.restrictions.no_new_alts and t.asset_class == CLASS_NAME["AL"] and t.direction == "buy"]
    c.append(ControlResult(name="Restrictions and preferences respected", status="fail" if (bad or nonew) else "pass", blocking=True,
                           detail="a proposed trade touches a protected holding" if (bad or nonew) else "no trade touches a locked holding, exclusion or no-buy class"))
    cap = p.restrictions.mandate_equity_cap
    if cap is not None and a.adjustment is not None:
        eq_after = (a.weights_after["EQ"] + a.adjustment["EQ"]) / 100
        c.append(ControlResult(name="Mandate limit after proposed adjustment", status="pass" if eq_after <= cap + 1e-9 else "fail", blocking=True,
                               detail=f"equity {eq_after * 100:.1f}% vs cap {cap * 100:g}%"))
    elif cap is not None:
        c.append(ControlResult(name="Mandate limit", status="warn" if "mandate_breach" in a.flags else "pass", blocking=False,
                               detail="breach flagged and escalated to compliance; path back inside the cap is proposed" if "mandate_breach" in a.flags else "inside the cap"))
    for flag, label in (("exclusion_blocked", "Client exclusion: candidate blocked"), ("restricted_list_blocked", "Restricted list: candidate blocked"),
                        ("profile_conflict", "Profile consistency: RM must reconcile before any proposal")):
        if flag in a.flags:
            c.append(ControlResult(name=label, status="warn" if flag == "profile_conflict" else "pass", blocking=False, detail="flagged for the RM"))
    c.append(ControlResult(name="Draft wording: no promises or forecasts", status="pass" if draft else "fail", blocking=True,
                           detail="checked" if draft else "draft was blocked (prohibited language or untraceable figure)"))
    c.append(ControlResult(name="Numbers traceable to engines or records", status="pass" if draft else "fail", blocking=True))
    c.append(ControlResult(name="Human approval gate", status="pass", blocking=True, detail=approval_path(a.tier)))
    return c


def _compose(p: ClientProfile, a: Analysis, trades, facts, draft, scen, news_ctx, checks, needs_input, extraction, ev) -> Proposal:
    d = (draft or {}).get("draft") or {}
    title = {"1": "Digest: no action needed", "2": "Review proposed adjustment", "3": "Significant: client conversation and second approval"}[a.tier]
    if "goal_at_risk" in a.flags and a.tier in ("2", "3"):
        title = f"Goal '{p.goal.name}' needs attention"
    elif "mandate_breach" in a.flags:
        title = "Mandate limit breached: escalate to compliance"
    elif "drift_breach" in a.flags and a.tier == "2":
        title = "Review allocation drift"
    alts, benefits, risks, tradeoffs = [], [], [], []
    if trades:
        from ..engines.rebalance import half
        alts = [dict(name="Do nothing and keep monitoring", description=f"Leave the mix as it is; the largest gap from plan stays at {a.max_drift_pts:g} points.", trades=[]),
                dict(name="Partial adjustment (half size)", description="Move halfway toward plan now and review again at the next run.",
                     trades=[t.model_dump() for t in trades_from(half(a.adjustment), p.portfolio)])]
        benefits.append(f"Moves the mix back toward the client's plan (largest gap today {a.max_drift_pts:g} points, range {a.band_pts:g}).")
        risks.append("Selling may realise taxes and transaction costs; tax lots and costs are not connected, so these are not estimated.")
        tradeoffs.append("Acting now fixes the gap at today's prices; waiting keeps market exposure that differs from the client's plan.")
    assumptions = [f"Thresholds are placeholders owned by compliance: range {a.band_pts:g} points, concentration limit 10%, size bands 3% and 10%.",
                   "Goal status uses a planning range (lognormal approximation with flat 0.5 correlation); it is not a forecast of returns."]
    if scen:
        assumptions.append("Scenarios are hypothetical shocks, not predictions: " + scen[0]["assumptions"].split(";")[-1].strip())
    unresolved = (["Tax and transaction-cost review by the adviser.", "Suitability should be reconfirmed before anything is finalised.",
                   "Consent to receive a recommendation is not consent to execute; execution stays locked."] if a.tier != "1" else
                  ["No decision is needed; the RM can acknowledge this digest entry."])
    requires = []
    if ev.signal and ev.signal.certainty == "confirmed":
        requires.append("RM must confirm the life-event signal from the adviser note before it is used; the client profile has NOT been changed.")
    elif ev.signal and ev.signal.certainty == "possible" and extraction and extraction.relevant:
        requires.append(f'The adviser note mentions a possible life event ("{extraction.evidence_quote[:120]}"). It has NOT been used to change the analysis; confirm it with the client first.')
    if needs_input:
        requires.append("RM must supply: " + ", ".join(needs_input) + ".")
    if "profile_conflict" in a.flags:
        requires.append("RM must reconcile the CRM risk profile with the plan; no trade is proposed until then.")
    if a.tier == "3":
        requires.append("Speak to the client first; a second approver is required.")
    summary = d.get("rm_note") or "Draft blocked by output controls; RM review of the engine facts is required."
    abst = "" if draft else "Draft text was blocked; the engine facts above are still valid."
    return Proposal(title=title, tier=a.tier, flags=a.flags, summary=summary, trades=trades, alternatives=alts, benefits=benefits, risks=risks, trade_offs=tradeoffs,
                    assumptions=assumptions, unresolved=unresolved + requires, scenarios=scen, news_context=news_ctx, client_message=d.get("client_message"),
                    message_routing=a.message, talking_points=d.get("talking_points", []), checks=checks, approval_path=approval_path(a.tier),
                    draft_provider=(draft or {}).get("provider", ""), abstention=abst, requires_rm_confirmation=requires)


def _evidence(repo: Repo, run_id: str, p: ClientProfile, a: Analysis, market_info: dict, news_ctx, extraction, checks, policy: Policy, event: EventInput):
    repo.add_evidence(run_id, "client_record", p.client_id, "Client context used", dict(plan=p.plan, weights=p.weights, band=p.band, goal=p.goal.model_dump(), restrictions=p.restrictions.model_dump(), contact_mode=p.contact_mode))
    repo.add_evidence(run_id, "engine", "pipeline.analyse", "Deterministic analysis (tier, flags, drift, adjustment, goal)", a.model_dump())
    for q in market_info.get("quotes", []):
        repo.add_evidence(run_id, "market", q["symbol"], f"{q['symbol']} {q['price']} via {q['provider']}", q)
    if event.shocks and not market_info:
        repo.add_evidence(run_id, "market", "event", "Event input supplied to the run (not fetched)", dict(shocks=event.shocks, inflow=event.inflow, outflow=event.outflow))
    for n in news_ctx:
        repo.add_evidence(run_id, "news", n["link"], n["title"][:120], n)
    if extraction is not None:
        repo.add_evidence(run_id, "client_record", "adviser_note", "Signal extracted from adviser note (untrusted text; RM must confirm)", extraction.model_dump())
    repo.add_evidence(run_id, "policy", "policy_settings", "Thresholds and assumptions (placeholders)", policy.model_dump())
    for c in checks:
        repo.add_evidence(run_id, "control", c.name, f"{c.name}: {c.status}", c.model_dump())


def _pick_second_approver(repo: Repo, owner_rm_id: str) -> str:
    """Tier 3 needs a second approver: another RM with senior-adviser authority (Tier 2+). Deterministic order; '' = escalate to compliance."""
    rank = {"Tier 1": 1, "Tier 2": 2, "Tier 3": 3}
    for rm in sorted(repo.list_rms(), key=lambda r: r.id):
        if rm.id != owner_rm_id and rank[repo.get_perms(rm.id)["approval"]] >= 2:
            return rm.id
    return ""


def _update_rec(repo: Repo, client, proposal: Proposal, pstatus: str, a: Analysis):
    r = repo.get_rec(client.id, client.issue)
    r.title, r.rationale = proposal.title, proposal.summary
    r.status = "Draft" if pstatus in ("awaiting_rm", "blocked") else "Monitor"
    r.tier = {"1": "Tier 1 — RM approval", "2": "Tier 1 — RM approval", "3": "Tier 2 — Senior adviser approval"}[a.tier]
    r.decided_by, r.note = "", ""
    if proposal.message_routing != "none":
        r.client_message = "Held until RM speaks to client" if proposal.message_routing == "held" else "Draft prepared"
    repo.save_rec(r)


def _record_pause(repo: Repo, client, user: User, run_id: str, reason: str, st: _Steps, res: RunResult):
    msg = ABSTENTION.get(reason, "Processing paused.")
    repo.log(client.name, "Monitoring paused", "Control layer", f"{reason}: {msg}", "Review", "Policy", client_id=client.id)
    if reason == "no_consent":
        r = repo.get_rec(client.id, client.issue)
        r.status, r.consent_request, r.title = "Monitor", "Consent task raised", "Consent needed"
        repo.save_rec(r)
        repo.log(client.name, "Consent task raised", "Workflow", "RM must obtain monitoring consent; no analysis or draft was produced", "Pending", "Consent", client_id=client.id)
    if reason == "security_injection":
        repo.log(client.name, "Untrusted text quarantined", "Control layer", "Instruction-like text in an adviser note was quarantined; compliance alerted; no model saw it", "Review", "Policy", client_id=client.id)
    res.notes.append(msg)
    repo.add_evidence(run_id, "control", "pause", f"Paused: {reason}", dict(reason=reason, message=msg))

