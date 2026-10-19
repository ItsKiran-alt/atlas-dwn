# Atlas DWN — Phase 1: Discovery, Traceability & Architecture

Status: **DRAFT for your confirmation. No application code has been written.**
Date: 19 Oct 2026

Source tags used below: **[PDF §n]** concept document · **[CASE]** Case_02 docx · **[HTML]** workbench prototype · **[PROMPT]** your build prompt · **[PROPOSED]** my own technical addition (not stated in any file).

---

## 0. What I inspected (and what I could not)

| File | Result |
|---|---|
| Concept & Product Definition (PDF, 18 pp.) | Text fully extracted and read. **The architecture diagram on p. 9 is an image and could not be read as text.** I rely on the surrounding prose ("sources, orchestrator, engines and AI skills, control layer, three views") and the HTML's "AI Orchestration & Data Flow" panel. |
| atlas_rm_workbench_updated (4).html (103 KB, 282 lines) | Read completely: all CSS, markup, and JS. |
| Case_02 docx | Read completely (it is short: problem statement + context + "MVP vs future" note). |
| `DWN_Golden_Data_Set.xlsx` (your upload) | Read in full, then **rejected by you**. Not used anywhere. Replaced by a fresh set: `golden/DWN_Golden_Data_Set_v2.xlsx` (see 8b). |

## 1. Product understanding (PDF is the source of truth)

**Problem [CASE, PDF §2].** AWM ($28B AUM, clients ≥ $2M) reviews quarterly/annually while markets and client lives are event-driven; legacy CRM/core banking cannot ingest live feeds; no unified client view; life events live in free-text notes; RMs spend ~41% of time on operations; regulation (fiduciary duty, Reg BI as benchmark, GDPR Art. 22, CCPA, SEC Marketing Rule, NIST AI RMF) forbids an opaque auto-trader.

**What DWN is [PDF §1, §7].** A *monitoring and drafting agent*, not a dashboard or chatbot. One job in v1: tell the RM **what changed for a client, what it means for their goals, and what to do — with evidence and checks attached.** Core proposition: *"which clients need me today, why, and what should I say to them?"*

**Functions [PDF §4]:** Watch · Interpret · Assess · Check · Personalise · Draft · Route.
**Eight event types [PDF §4]:** broad market move · concentration · goal near its date · life event from notes · restriction/preference conflict · no action needed · compliance limit · data/security problem.
**Significance [PDF §5]:** five factors scored 1–3 (size, risk shift, goal impact, client sensitivity, reversibility); **highest factor wins**. Tier 1 Inform (digest, no approver) · Tier 2 Review (RM approves/edits/rejects) · Tier 3 Significant (RM + second approver, after a client conversation; never automated) · plus **Paused** state (no consent / stale or implausible data / hidden instructions in notes).
**Goal status [PDF §5]:** distribution of outcomes at goal date: *On track* = 25th percentile meets target; *At risk* = only median does; *Off track* = even median misses. A planning aid, never a forecast.
**Client Context Model [PDF §5]:** Goals, Situation, Preferences (plan weights, range, exclusions), Communication (channel, tone, calls-only).
**Architecture [PDF §6]:** hybrid — deterministic engines produce every number; AI handles language; control layer sits between them and the RM; **read-only** from legacy systems; numbers flow engines → AI, never the reverse.
**Governance [PDF §9]:** consent checked before any analysis (no consent → client Paused + consent task); drafts blocked if they promise outcomes or contain untraceable figures; notes/news are untrusted (instruction-like text quarantined + compliance alerted); stale data pauses the item; full audit; pause switch for compliance; MVP has **no execution**.
**MVP vs later [PDF §10]:** MVP = monitor, interpret, tier, draft, safety checks, RM workspace/gated client view/compliance view, read-only legacy. Later = consented execution for routine Tier 1/2 only; Tier 3 never automated.
**Success metrics [PDF §10]:** event→RM time, prep time, accept/edit/reject share, % high-level items RMs agree were significant, controls-stopped counts, items with complete audit record (target: all).
**Stated assumptions [PDF §12]:** US regulation; synthetic data; asset classes = equity, bonds, cash, alternatives, single stock; **no trade proposals in alternatives**; second approver = senior advisor or compliance (AWM decides); all thresholds are placeholders.

## 2. Contradictions and gaps you need to know about

| # | Conflict | Where | My proposed resolution |
|---|---|---|---|
| C1 | **Currency/jurisdiction.** PDF/case = USD, SEC/FINRA, $2M+. HTML = ₹ crore figures, "SEBI-approved agreement" wording, Indian-style number formats. | PDF §12 vs HTML | **Needs your decision (Q1).** |
| C2 | **Meaning of "Tier".** PDF: Tier 1 = Inform (no approver), 2 = RM, 3 = RM + second approver. HTML: "Tier 1 — RM approval", "Tier 2 — Senior adviser", "Tier 3 — Investment committee", and a "Tier 1" *client service tier* badge on every client, and RM "Approval authority Tier 1/2/3". | PDF §5 vs HTML | Keep the HTML labels/layout, but implement PDF semantics underneath: *item significance tier* (PDF) and *approver authority level* are separate fields. Relabel only with your approval. |
| C3 | HTML has **no Paused state, no significance scoring, no life-event/notes signal, no quarantine UI**. PDF treats these as core. | HTML vs PDF | Add as **new content inside existing layouts** (e.g. status chip, task rows, audit rows) — not a redesign. You approve each addition. |
| C4 | HTML client directory is **24 clients, none named Ramesh Agarwal**; the client login demo user is Ramesh Agarwal (₹9.4 Cr, 6 holdings). Only Ananya/Vikram have name-mapped logins. | HTML | Seed Ramesh as a 25th client (or map him to an RM-book client). Needs confirmation (Q-default D4). |
| C5 | HTML RM "Compliance View" sidebar item is `data-access="admin"`, and Admin's allowed views are only `settings` + `compliance`. PDF also lists **Compliance and risk** and a **second approver** as users. | HTML vs PDF §3 | Keep exactly the HTML role matrix (Admin, RM, Client). Compliance = Admin's Compliance View in MVP; second approver modelled as an **RM-with-higher-authority** (approval tier) rather than a 4th login — unless you want a 4th role. |
| C6 | HTML contains **"Client View →" button and Client View page** (RM-gated preview). Your prompt says not to reintroduce the removed tab strip. The page exists in the HTML as an RM-gated preview reached by buttons, not a tab strip. | HTML vs PROMPT | Keep page `Client View` (reached by button only); no tab strip. |
| C7 | PDF **MVP: no execution**; CASE: "move from insight to automated portfolio adjustment". HTML: "Execution — Locked". | CASE vs PDF | Follow PDF + PROMPT: execution step is a permanently locked, display-only gate. |
| C8 | Your 10-agent proposal vs PDF's architecture (orchestrator + **engines** + 3 AI skills: *event interpreter, notes signal extractor, recommendation drafter* + control layer). | PROMPT §5.1 vs PDF §6 | See §5 below: fewer *LLM* agents, more deterministic engines. |
| C9 | PDF's market-evidence figures (39%→19%, 41%, 60%, 71%, 72%) have **unpinned sources**. | PDF §2 | I will not display these in the app. |
| C10 | HTML is **100% client-side demo** (fake login accepting any password, state in page memory). | HTML | Only visuals/behaviour are reused; every backend behaviour is rebuilt. |

## 3. Requirements traceability matrix

Columns: UI = page in HTML · Svc = agent/service · Validation = automated proof.

### 3A. Explicit requirements (from files)

| ID | Requirement | Source | UI | Agent / service | Data | Implementation | Validation |
|---|---|---|---|---|---|---|---|
| R1 | Monitor each portfolio vs the client's plan (weights, range) | PDF §4 | Workbench: allocation donut, drift alert | Portfolio Engine (deterministic) + Portfolio Monitoring agent | holdings, plan weights, range | Pure-Python drift calc; Decimal arithmetic | Unit tests with fixed holdings → exact drift; reproducibility test |
| R2 | Interpret market events & map to holdings | PDF §4 | Research & Market; AI Insights | Market Intel service + News/Event Interpreter (LLM) | live prices, news RSS | Provider adapters w/ cache + freshness; LLM only classifies/explains | Mocked-feed tests; stale-feed → Paused; injection-in-news fixture |
| R3 | Extract signals from advisor notes (life events), RM confirms | PDF §4, §10 | Client → Activity & Notes; "Add adviser note" modal | Notes Signal Extractor (LLM, schema-bound) + quarantine scanner | RM notes | Pydantic-validated candidate signal; RM must confirm before it affects plan | Golden items: new child, home purchase; "hidden instruction" note quarantined |
| R4 | Five-factor significance, highest wins → Tier 1/2/3 / Paused | PDF §5 | Queue status chips; Workbench | Significance Engine (deterministic) | thresholds (config, compliance-owned) | Pure function; thresholds in DB settings | Table-driven tests of every factor/level boundary |
| R5 | Goal status (on track/at risk/off track) via 25th/50th percentile | PDF §5 | Client → Goals | Goal Engine (deterministic Monte-Carlo, seeded) | goals, holdings, placeholder market assumptions | Seeded simulation, assumptions stored & displayed | Fixed-seed regression tests; boundary tests |
| R6 | Personalise by goals, situation, preferences, communication | PDF §5 | Overview; Client View; message modal | Client Context agent + Drafter | Client Context Model | Typed context object consumed by all agents | Calls-only client → message "Held" test |
| R7 | Draft RM note + client message; no return forecasts/guarantees | PDF §4, §9 | Recommendation card; "Draft client message" modal | Recommendation Drafter (LLM) + Wording/Figure check (deterministic) | engine outputs | Draft may only quote engine numbers; regex + numeric-trace check | Prohibited-wording tests; "figure not in engine output" blocks draft |
| R8 | Control layer: consent, data quality, restrictions, limits, wording | PDF §4, §9 | Compliance View: checks panel | Suitability & Compliance service (deterministic) | consent, restrictions, mandate caps | Ordinary Python rules; mandatory failure blocks progression | One test per control (PDF §11) |
| R9 | Consent checked before any analysis; no consent → Paused + consent task | PDF §9 | Queue (Neha Prakash "Consent pending"); Tasks | Consent service + Orchestrator gate | consent records (versioned) | First step of every run; creates task | Run for no-consent client produces no analysis, one task |
| R10 | RM approves/edits/rejects; Tier 3 needs 2nd approver after client conversation | PDF §5, §9 | Review & edit modal; Compliance approval workflow | Approval Workflow service | approvals | State machine; RM note mandatory; self-approval by AI impossible | State-machine tests; Tier 3 w/o second approver cannot reach "approved" |
| R11 | Client messages released only by RM | PDF §3, §9 | Client View ("Not shared" → "Ready…") | Workflow service | messages | Release is a separate RM-authorised transition; nothing sent externally | Test: no code path sends a message |
| R12 | Full audit of every event, check, edit, approval | PDF §9 | Audit Trail table + filters; export | Audit service (non-LLM) | audit_log (append-only) | Written by orchestrator in same transaction as state change | Trace test: recommendation → evidence → decision |
| R13 | Stale/implausible data pauses the item | PDF §9 | Status chips; Research page | Data-quality gate | price timestamps | Freshness threshold in config; plausibility bounds | Stale fixture → Paused, no recommendation |
| R14 | Read-only from legacy CRM/core banking | PDF §6 | Compliance KPI "Read-only Legacy CRM" | Connector layer | — | Connector interface exposes read methods only | Test: connector has no write method |
| R15 | No execution in MVP | PDF §10, CASE | "4 · Execution — Locked" | — | — | No broker integration exists; step hard-coded locked | Test greps for any order/exec endpoint; state machine has no "executed" state |
| R16 | Pause switch (client / event type / whole book) | PDF §9 | Admin settings | Settings service | pause flags | Orchestrator checks flags first | Pause tests |
| R17 | Golden data set validation (33 scenarios, 8 categories) | PDF §11 | — | Eval harness | golden set | pytest runner comparing level/flags/forbidden trades/message held | Pass/fail report |
| R18 | Metrics: accept/edit/reject, controls-stopped, items with complete audit | PDF §10 | Compliance KPIs / Reports | Metrics queries | audit + approvals | SQL views | Query tests |
| R19 | MVP vs future clearly separated | CASE | README roadmap | — | — | Roadmap doc | Doc review |
| R20 | Separate Admin / RM / Client sign-in; no tab strip; Client sees only own data | HTML | Login gate; portal | Auth + RBAC | users | Real auth, server-side checks | URL/ID tampering tests |
| R21 | Consent onboarding only for **new** clients; existing see portfolio + transactions | HTML | Onboarding; Client portal | Consent service | consent records | `needs_onboarding` derived from DB | Existing client never sees consent form test |
| R22 | RM Workbench: metrics, queue (filters/search), client detail with 6 subtabs, donut, performance chart + 1Y/3Y/5Y, events, AI recommendation card, workflow steps | HTML | Workbench | Read services | — | Render from DB | UI parity checklist (§7) |
| R23 | Clients directory (24+) with search → opens in workbench | HTML | Clients | Client service | clients | — | Count test, search test |
| R24 | AI Insights, Research & Market, Tasks, Reports, Home pages | HTML | Those pages | Insights/Tasks/Report services | — | Real data replaces demo text | Page render tests |
| R25 | Review & edit, Ask Atlas AI, Draft message, Add note dialogs all function | HTML | Modals | RM Copilot (LLM, grounded), Approval, Notes | — | `st.dialog` or component | Interaction tests |
| R26 | Settings & Scheduler in main area; daily/weekly/monthly; days; time; workflow scope (5); client scope (4) with searchable multi-select | HTML | Settings | Scheduler service | schedules | Persisted schedule rows | Scheduler tests |
| R27 | Admin controls RM permissions (schedule, all-clients, approval authority, override requests — never bypass mandatory controls) | HTML | Settings (Admin only) | Permission service | rm_permissions | Enforced in backend on every scheduler call | RM without permission is refused at service level |
| R28 | Agent data-source registry; Salesforce CRM = primary client source; add/remove | HTML | Settings → Agent data sources | Data-source registry | data_sources | Salesforce **mock** connector, labelled simulated | Registry tests; "Connected" never shown for unconfigured real source |

### 3B. Requirements from your prompt (beyond the files)

| ID | Requirement | Svc | Validation |
|---|---|---|---|
| P1 | Real market/news data with provenance (provider, URL, pub/market/retrieved timestamps, currency, freshness) | Market & News adapters | Mock + one live smoke test |
| P2 | Fallbacks, retry limits, caching, rate limiting; never silently fake data | Provider chain | Failure-injection tests |
| P3 | Pydantic contracts for every agent; reject malformed output | Agent base class | Malformed-output tests |
| P4 | Abstention phrases ("Insufficient evidence to assess" etc.) | Synthesis agent | Insufficient-evidence fixtures |
| P5 | Prompt-injection resistance for news/notes/documents | Quarantine scanner + prompt design | Injection fixtures |
| P6 | Persistent DB, migrations, indexes, transactions | DB layer (Alembic) | Restart-persistence test |
| P7 | Server-side RBAC; client & RM data isolation | Auth/RBAC | Tampering tests |
| P8 | Real durable scheduler | External trigger → secured worker | Run-record tests; overlap lock tests |
| P9 | Consent withdrawal | Consent service | Withdrawal blocks next run |
| P10 | **"Validate & verify the agent by running it"** | Eval harness + live run | See §9 |

### 3C. Proposed enhancements (mine)

Notes Signal Extractor (missing from your 10 agents but required by PDF); Significance Engine; Quarantine scanner; Pause switch; separation of *item tier* vs *approver authority*; run-lock table for overlap prevention; evidence-store table linking each number to its engine call.

## 4. Architecture

```mermaid
flowchart LR
  subgraph UI[Streamlit UI - role workspaces]
    A[Admin] --- R[RM] --- C[Client]
  end
  UI --> AUTH[Auth + RBAC + Consent gate]
  AUTH --> SVC[Application services]
  SVC --> DB[(PostgreSQL / SQLite dev)]
  SCHED[External scheduler\nGitHub Actions cron] --> WORKER[Secured worker entrypoint]
  WORKER --> ORCH
  SVC --> ORCH[Orchestrator]
  ORCH --> ENG[Deterministic engines\nPortfolio · Significance · Goal · Scenario · Rebalance]
  ORCH --> DATA[Data services\nMarket · News · CRM connector (read-only)]
  ORCH --> LLM[LLM skills\nEvent interpreter · Notes extractor · Drafter · RM Copilot]
  ENG --> CTRL
  LLM --> CTRL[Control layer\nConsent · Data quality · Restrictions · Limits · Wording/figure trace]
  CTRL --> APPROVE[Approval workflow\nRM · second approver]
  APPROVE --> DB
  ORCH --> AUDIT[Audit service - always written by code]
  AUDIT --> DB
  DATA --> EXT[(Yahoo/yfinance · FRED · RSS · official sources)]
```

## 5. Agent design: reconciling your 10 agents with the PDF

Rule: **if a task produces numbers or enforces a rule, it is a deterministic service, not an LLM agent.**

| Your agent | Becomes | LLM? |
|---|---|---|
| 1 Client Context | Client Context service (reads Client Context Model; flags missing/stale) | No |
| 2 Portfolio Monitoring | Portfolio Engine + monitoring step in orchestrator | No (LLM only explains) |
| 3 Market Intelligence | Market Data service | No |
| 4 News & Event Interpretation | **Event Interpreter skill** | **Yes** |
| 5 Risk & Scenario | Scenario Engine (+ Goal Engine) | No |
| 6 Goal Progress | Goal Engine | No |
| 7 Recommendation Synthesis | **Recommendation Drafter skill** (consumes engine output only) | **Yes** |
| 8 Suitability & Compliance | Control layer | No |
| 9 RM Copilot | **RM Copilot skill** (grounded Q&A, draft notes/messages) | **Yes** |
| 10 Audit & Workflow | Audit + Workflow services | No |
| *(new)* | **Notes Signal Extractor skill** + Quarantine scanner | **Yes** (+ regex rules) |

Result: 4 LLM skills + ~8 deterministic services, one orchestrator. Framework: **plain Python orchestrator with typed steps** (no LangGraph) unless you want it — fewer moving parts, easier to test.

## 6. External dependencies (candidates — NOT yet verified)

I have not yet checked current free-tier limits, terms or endpoints; I will do that in Phase 4 before relying on anything.
Market prices: yfinance (unofficial; terms/availability risk) with Alpha Vantage or Twelve Data as fallback · Economic: FRED (US), RBI (if India) · News: RSS from publishers whose terms allow it, plus official regulator/central-bank feeds · LLM: your choice (Q2) · Auth: Q4 · DB: Q4.

## 7. UI parity checklist (Phase 2 inventory)

Login gate (3 role cards, split brand panel, demo defaults) · Onboarding (consent) · Client portal (3 metrics, holdings, transactions) · Topbar (brand, global search, Ask Atlas AI, reminders badge, Sign out, user chip) · Sidebar (Home, RM Workbench, Clients, AI Insights, Research & Market, Tasks[3], Reports, Compliance View [admin], Settings & Scheduler, Help) · Workbench (5 metrics, queue + filter chips + name filter, client hero, 6 subtabs, allocation donut, performance chart + period chips, events, AI recommendation card, 4-step workflow) · Client View · Compliance View (5 metrics, checks, approval workflow, audit table with filters, architecture grid) · Home · Clients · AI Insights · Research · Tasks · Reports · Settings (Admin permissions, data sources, scheduler form + status) · 4 modals + toast.

**Known Streamlit limits:** Streamlit re-runs the script on every interaction, has its own chrome/layout, no true `position:fixed` modals (use `st.dialog`), no CSS-only sticky sidebar identical to the HTML. Fidelity options in Q3.

## 8. Defaults I will use unless you say otherwise

| # | Default | Why |
|---|---|---|
| D1 | Salesforce = **clearly-labelled mock connector** behind a read-only interface; status "Simulated", never "Connected (live)" | No real org; honest |
| D2 | Consent: versioned text, timestamp, linked to client ID; **withdrawal supported**; withdrawn → client Paused | PDF §9 |
| D3 | Market universe: equity, bonds, cash, alternatives, single stock; **no trade proposals in alternatives** | PDF §12 |
| D4 | Seed 24 clients from HTML + Ramesh Agarwal (25th) with 6 holdings and the 4 transactions from the HTML | C4 |
| D5 | Scheduler: schedules persisted in DB; actual execution by a **GitHub Actions cron** calling a secured worker entrypoint; Streamlit does not run jobs | Streamlit is not a scheduler |
| D6 | Thresholds (bands, range, freshness) stored as compliance-owned settings, flagged "placeholder" | PDF §5 |
| D7 | Python 3.12 for the project (you have 3.14 locally; some libraries lack 3.14 wheels and Streamlit Cloud may not offer it) | Compatibility |

## 8b. Golden data set v2 (replaces the rejected upload)

Generated fresh in `golden/`: `DWN_Golden_Data_Set_v2.xlsx` (review workbook), `golden_set.json` (machine-readable, for tests), `scenarios.py` (source), `reference_engine.py` (independent checker), `build_golden_set.py`, `check.py`.

- **36 scenarios, 8 categories** (PDF s11 categories + your prompt's data-quality cases), **12 new synthetic USD clients** (K01-K12). Tier mix: 8 x Tier 1, 14 x Tier 2, 7 x Tier 3, 7 x Paused. Nothing is copied from the rejected file.
- **Run result:** reference engine matches all 36 authored expectations (tier, flags, message routing, goal status). **That is a consistency check, not proof the framework is right.**
- **Honest calibration record:** first run matched only 16/36. Fixes: goal targets calibrated (most), shock sizes adjusted for 4 scenarios, 3 expectations revised (cash outflows move cash outside the band), 1 flag renamed. So targets and shocks were tuned, as the PDF itself admits for its own set.
- **Decisions for you to confirm:** (1) *Size factor* = share of portfolio moved by the proposed adjustment or confirmed cash flow (PDF does not define it; measuring market loss would make nearly every sell-off Tier 2). (2) Hidden instruction in a note = **Paused** (PDF s5). (3) Conflicting sources / missing price / currency mismatch = Paused with an abstention message.
- Not yet reviewed by advisors or compliance; reviewer sheet included.
- **Client seeding (C4/C11):** HTML names (24, remapped to USD) and K01-K12 can coexist; still your call.

## 9. How I will "validate & verify the agent by running it"

1. **Deterministic layer (no key needed):** pytest suite over engines and controls using **`golden/golden_set.json` (36 scenarios, v2)** (tier, flags, forbidden trades, message routing), including a pre-retiree case that is Tier 3 purely from the goal factor (S-01). I will run it and report real pass/fail.
2. **Live data smoke run:** fetch real prices/news and print the provenance record and data age.
3. **End-to-end run:** seeded client → orchestrator → recommendation → controls → approval, with audit trace printed.
4. **LLM skills:** run against your chosen provider with schema validation, injection fixtures and a "figure not traced" check. **Requires an API key you create (Q2); I will not ask you to paste it in chat.**
5. I will report failures as failures and state what was not verified.

## 10. Proposed repository structure (Phase 3+)

```
atlas-dwn/
  app.py                  # Streamlit entry only
  pages/ or ui/           # per-role workspaces, components, CSS (from HTML)
  dwn/
    config.py
    auth/  rbac.py consent.py
    db/    models.py repo.py migrations/ (Alembic)
    services/ clients portfolios tasks approvals scheduler datasources audit metrics
    engines/ portfolio.py significance.py goals.py scenarios.py rebalance.py
    data/  market/ news/ crm_connector/ (mock + interface)
    agents/ orchestrator.py event_interpreter.py notes_extractor.py drafter.py copilot.py schemas.py
    controls/ consent.py data_quality.py restrictions.py wording.py quarantine.py
  worker/run_scheduled.py # entry for the external scheduler
  tests/ unit/ integration/ golden/
  .github/workflows/ tests.yml scheduler.yml
  docs/ README.md DEPLOY.md SECURITY.md ARCHITECTURE.md
  .env.example  requirements.txt  .gitignore  .streamlit/config.toml
```

## 11. Security & financial-risk control summary

No execution code path · server-side RBAC on every service call (UI hiding is cosmetic) · consent gate first in every run · numbers only from engines + trace check on drafts · untrusted-text quarantine for notes/news · stale data → Paused · append-only audit written by code not LLM · secrets only in env/secrets store · synthetic client data only · prototype disclaimers throughout (not advice, not a regulatory-compliance claim).
