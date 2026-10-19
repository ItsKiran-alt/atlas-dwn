# Phase 5: the agent (orchestrator, engines, skills, approvals) and how I ran it

Tests: `.venv\Scripts\python -m pytest tests -q` → **187 passed**.
Run the agent yourself:
- `.venv\Scripts\python scripts\run_golden_agent.py` (all 36 golden scenarios through the real orchestrator; no key or network needed)
- `.venv\Scripts\python scripts\run_live_agent.py` (real prices + real Fed/SEC/BLS news, then runs the agent on 6 clients)
- `... run_golden_agent.py --llm groq|gemini` once you set the key (see below)

## Architecture (your 10 agents → what exists)
| Your agent | Implemented as | Uses an LLM? |
|---|---|---|
| 1 Client Context | `orchestrator.build_profile`: typed profile from `client_profiles`; missing/invalid → abstain | no |
| 2 Portfolio Monitoring | `engines/pipeline.analyse` (drift, bands, concentration, tier) | no |
| 3 Market Intelligence | Phase 4 `MarketService` + `build_market_event` | no |
| 4 News & Event Interpretation | `skills.EventInterpreter` | **yes** (rules fallback) |
| 5 Risk & Scenario | `engines/scenarios.py` (hypothetical, labelled) | no |
| 6 Goal Progress | `engines/goals.py` | no |
| 7 Recommendation Synthesis | `orchestrator._compose` + `skills.Drafter` for the wording | wording only |
| 8 Suitability & Compliance | `controls/` (gates, policy flags, wording, figure traceability) + `_controls` | no |
| 9 RM Copilot | `skills.Copilot` (cited answers, abstains) wired to *Ask Atlas AI* | **yes** (rules fallback) |
| 10 Audit & Workflow | orchestrator writes run/step/evidence/audit rows itself; approvals in `services.decide_proposal` | never |
| (new) Notes Signal Extractor | `skills.NotesExtractor` + quarantine scan | **yes** (rules fallback) |

Run order (each step recorded): permission+consent → client context → data quality → notes extraction → deterministic analysis → scenarios → news → draft → output controls → persist proposal + evidence + review item → **stop**. The orchestrator contains no approval, no execution and no message sending (a test inspects its code for that).

Safeguards implemented: consent gate first; stale / implausible / missing / conflicting / wrong-currency data **pauses** the item with the exact abstention message; instruction-like note text is quarantined and **never sent to a model**; every draft is blocked if it contains promises/forecasts or a number that doesn't trace to an engine or the client record; per-run LLM call cap (4) and daily budget; duplicate runs within 10 minutes are reused; a failing non-critical step degrades the run, a failing critical step fails it cleanly (both tested).

**Human workflow:** Tier 1 = digest (no decision). Tier 2 = the client's RM decides. Tier 3 = the RM after confirming a client conversation, then a **different** second approver with senior-adviser authority (Tier 2+), who can open only that case. Admin and the agent cannot approve. A proposal blocked by a control cannot be approved.

## What I ran, and the honest results
| Run | Result |
|---|---|
| Golden set, whole agent, rules mode (36 scenarios) | **36/36** (tier, flags, message routing, goal status, protected holdings, note extraction, pause + audit events, drafts pass wording/figure checks) |
| Same, with Groq selected but **no key** | **36/36**: every LLM call failed with `not_configured` and the system degraded to the rules path, as designed |
| Live: real prices + 12 real headlines → 6 clients | Completed/paused correctly (no-consent clients paused; others Tier 1-3 with 14 evidence rows each, links to real Fed/BLS items) |
| Real browser UI: Run check → refresh live data → Tier 3 proposal → first approval refused without conversation tick → accepted → second approver (different RM) approves | Worked |

**What 36/36 does and does not mean.** The expectations were authored by me from the PDF framework and the production engine was ported from my reference engine, so this proves the pipeline is *consistent with the golden set*, not that the framework or thresholds are right. Advisors/compliance still have to review them.

**Bugs the testing found (fixed):** (1) the reference engine silently ignored a known $150k contribution (S-20), (2) my first figure-traceability check let "99%" pass because of a rounding rule, (3) a draft attributed a *suggested* goal's "at risk" status to the client's existing goal, (4) the note extractor would have invented an education-goal amount; it now returns "RM must supply" instead.

## NOT verified: the LLM paths
- **No LLM call has been made.** I had no API key. The Groq (OpenAI-compatible `chat/completions`) and Gemini (`generateContent`) adapters follow the providers' docs as fetched today and are tested only against a fake transport. Gemini's default model id (`gemini-2.5-flash`) is **unverified**: set `GEMINI_MODEL` from AI Studio. Groq's default `openai/gpt-oss-20b` was listed on Groq's page. Free-tier limits could not be confirmed (Google no longer publishes them on the docs page; Groq's table didn't include the free plan).
- **Privacy:** third-party sources say Gemini's *free* tier may use your inputs to improve Google's products. Use only synthetic data (as here), never real client data.
- To try a real model: create a key (Groq: console.groq.com; Gemini: aistudio.google.com), put it in an environment variable (never in chat or git), then `set DWN_LLM_PROVIDER=groq` + `GROQ_API_KEY=...`, enable the source in Settings, and run `run_golden_agent.py --llm groq`. Tell me the pass/fail output and I'll fix what it exposes.

## Changes to your UI (same classes/layout) for approval
1. AI Recommendation card: tier chip + approval path, real proposal block (trades, alternatives, "Needs the RM", relevant official headlines with links), **Run monitoring check** button, workflow step 2 now reflects the real checks.
2. Review dialog: evidence & checks list, open points, approval history, **"I have spoken with the client"** checkbox (needed for Tier 3).
3. Compliance view: step 2 is now "Second approver" (named when Tier 3).
4. Ask Atlas AI answers with citations or "Insufficient evidence to assess."
5. Seed change: **Arjun Mehta = Tier 2 (senior adviser)** so Tier 3 cases have a second approver.

## Limitations
- Goal numbers for the 24 prototype clients are **generated placeholders** parsed from the prototype's text (that is why many show "at risk"). Golden clients K01-K12 use the authored data.
- Real runs use the *day's move* of three proxy ETFs (SPY, AGG, VNQ); the fictional funds are not mapped to tickers; cash/single stock get no move.
- The keyword news fallback is crude (it only matches a few terms); an LLM would interpret better but must pass the same grounding checks.
- Tier thresholds, bands, size definition, concentration limit and assumptions are placeholders; there is no UI yet for compliance to edit them (table `policy_settings` exists).
- Scheduling, run history screen and background execution are Phase 6.
