# Architecture

## 1. Layers
Principle from the concept document: **AI drafts and explains, engines calculate, authorised people decide.**

| Layer | Code | Rule |
|---|---|---|
| UI | `ui_component/`, `dwn/ui/` | Renders HTML for the signed-in role only; sends actions to the server. No auth, no client data logic in the browser. |
| Authorisation + consent | `dwn/services.py`, `dwn/auth.py` | Every action re-checks role, client ownership, consent, scheduling permission. |
| Orchestration | `dwn/agents/orchestrator.py` | One explicit typed run; stops at "awaiting human". No approval or execution code. |
| Deterministic engines | `dwn/engines/` | Same input → same output. All numbers come from here. |
| Controls | `dwn/controls/`, `orchestrator._controls` | Gates (consent, data quality, injection), policy flags, wording, figure traceability. |
| Data ingestion | `dwn/data/` | Hardened HTTP, provenance, freshness, quarantine of untrusted text. |
| LLM skills | `dwn/agents/skills.py`, `llm.py` | Interpret and draft only; validated, grounded, replaceable by deterministic fallbacks. |
| Persistence + audit | `dwn/repo.py`, `dwn/db/` | One transaction per event; audit is append-only (DB triggers). |
| Scheduling | `dwn/scheduler/`, `worker/` | At-most-once per slot, locks, permission re-check at run time. |

## 2. One monitoring run
```mermaid
flowchart TD
  S([Trigger: RM click, schedule, golden test]) --> P{Permission +<br/>client ownership}
  P -- denied --> X1([Refused, audited, nothing recorded])
  P --> CN{Monitoring consent?}
  CN -- no --> PA1([PAUSED: consent task raised, no analysis])
  CN --> CC[Client context: typed profile]
  CC -- missing/invalid --> PA2([PAUSED: incomplete profile])
  CC --> DQ{Data quality:<br/>fresh, plausible, complete,<br/>agreeing, USD}
  DQ -- fails --> PA3([PAUSED with exact reason])
  DQ --> NT{Note text?}
  NT -- instruction-like --> PA4([PAUSED: quarantined,<br/>never sent to a model])
  NT --> EX[Extract candidate signal<br/>RM must confirm]
  EX --> AN[Deterministic analysis:<br/>drift · five-factor tier · goal · adjustment]
  AN --> SC[Scenarios - hypothetical]
  SC --> NW[News interpretation]
  NW --> DR[Draft RM note + client message]
  DR --> OC{Output controls:<br/>restrictions · mandate ·<br/>wording · figures traceable}
  OC -- blocking failure --> BL([Proposal BLOCKED: cannot be approved])
  OC --> PR[Persist run, steps, evidence,<br/>proposal, audit]
  PR --> RV([Review item for the RM - STOP])
```

## 3. Approval state machine (humans only)
```mermaid
stateDiagram-v2
  [*] --> digest: Tier 1
  [*] --> awaiting_rm: Tier 2 / Tier 3
  [*] --> blocked: control failed
  awaiting_rm --> approved: Tier 2, RM approves
  awaiting_rm --> awaiting_second: Tier 3, RM approves after client conversation
  awaiting_rm --> edited: RM edits
  awaiting_rm --> rejected: RM rejects
  edited --> awaiting_rm: new run supersedes
  awaiting_second --> approved: DIFFERENT senior approver
  awaiting_second --> rejected: second approver rejects
  blocked --> rejected: reject only
  approved --> [*]: nothing is executed. Execution stays locked
```

## 4. Scheduler
```mermaid
sequenceDiagram
  participant Cron as GitHub Actions / Task Scheduler
  participant W as worker/run_scheduled.py
  participant DB as Database
  participant O as Orchestrator
  Cron->>W: tick
  W->>DB: list enabled schedules
  loop each schedule
    W->>W: latest slot <= now (UTC)
    W->>DB: job for (owner, slot)? unique constraint
    alt none and within grace
      W->>DB: acquire lock (expires)
      W->>W: re-check permission + client scope
      W->>O: run each client (retry once)
      W->>DB: job + per-client outcome + data freshness
    else none and older than grace
      W->>DB: record MISSED
    else failed/partial and attempts < 3
      W->>O: retry only failed clients
    end
  end
```

## 5. Data model (main tables)
`users · rms · rm_permissions · clients · client_profiles · goals · holdings · transactions · consents · audit_events (append-only) · recommendations · proposals · approvals · agent_runs · run_steps · evidence_items · adviser_notes · client_message_drafts · schedules · schedule_runs · job_runs · job_run_items · job_locks · data_sources · market_quotes · news_items · policy_settings`. Migrations: `alembic/versions/0001…0004`.

## 6. Mapping to the 10 agents in the build prompt
See the table in [docs/05_phase5_agent.md](05_phase5_agent.md): most "agents" are deterministic services on purpose; only four skills use a language model.
