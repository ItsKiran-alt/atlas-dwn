# Phase 7: testing, hardening, security review, final UI parity

**Tests:** `.venv\Scripts\python -m pytest tests -q` → **345 passed**. **Coverage 92%** of `dwn/` (weakest: `ui/controller.py` before the new UI-action tests, `services.py` 82%; the worker script is covered only by a subprocess test). Security detail: `docs/SECURITY.md`.

## What I did and found
| Check | Result |
|---|---|
| **Security review** of authorisation, output escaping, secrets, errors, production config | 4 real gaps found and **fixed** (below). No XSS hole: all injected payloads were escaped. |
| **Authorisation matrix**: 12 client-scoped services × 8 wrong user/client pairs, plus role checks | All refused; a denied run leaves no trace. |
| **XSS tests** with script/image/attribute-breakout payloads via client name, notes, drafts, news and LLM output, parsed with a real HTML parser | Clean. (My first version of the test had false alarms; I fixed the test, not the app, after confirming the output was escaped.) |
| **Dependency audit** (`pip-audit`) | No known vulnerabilities in the installed packages (2026-10-20). |
| **Mutation check** (`scripts/mutation_check.py`): break 27 real controls one at a time in a copy of the project | **27/27 caught.** The first complete run caught 25: two survivors exposed genuine test gaps ("second approver may equal first approver" was only blocked by a different rule; the audit-trigger mutation was badly written). Both fixed. |
| **Every UI action** exercised per role (5 new tests incl. malformed events) | All work; dead or crashing actions: none found. |
| **UI parity** (`scripts/ui_parity.py`, headless Chromium): 30 page/viewport comparisons (desktop 1440, tablet 900, mobile 390) against your original HTML; screenshots in `docs/parity/` (original LEFT, app RIGHT) | **750 of 986 measured component checks identical.** RM Workbench: 54/55 (only a toast). Clients/Insights: 100%. The rest are listed below. |

## Fixed in this phase
1. **Unexpected errors** would have shown a stack trace to the user. Now: a reference number to the user, details only in the server log + an audit line (tested that internals never reach the UI).
2. **Production login page** pre-filled demo credentials. Now only in demo mode; `DWN_ENV=prod` refuses to start on SQLite or with demo accounts on the default password.
3. **Consent gap:** the copilot and report export still worked for a client who had no consent. Both now refuse (tested).
4. **Input limits** on questions (1,000 chars).
5. **Client portal layout** was 44 px narrower than your design (an extra wrapper added padding). Fixed; now matches.
6. Two weak tests strengthened (see mutation check).

## Remaining UI differences (all intentional or data-driven; please approve)
- **Currency/wording** (₹→$, SEBI→SEC/FINRA) and live data: counts, names, AUM, "Tasks 3→5", "Needs attention 8→18" come from the database.
- **Additions:** Run monitoring check, Run now, Run history, Next run, UTC labels, consent card in the portal, password fields on onboarding, Research & Market (real tables, links), evidence section and "I have spoken with the client" in the review dialog, tier chip and proposal block.
- **Removed/changed:** "Remove" source buttons and "View controls" hidden from RM (Admin only); Reports "Preview" became "Generate" (downloads a file); Ask AI button reads "Get answer".
- Alternatives/Cash legend rows now also show a ↑ when 5 points over plan (the prototype only marked equities).
- Prototype bugs not reproduced: Client View blocked for RM; Compliance nav not highlighted for Admin.

## Not verified
- Parity was measured in Chromium only; Safari/Firefox untested. The pixel-level check is layout/style metrics plus your eyes on the side-by-side images, not an automated pixel diff (data differs).
- Postgres/Supabase, GitHub Actions, Python 3.12 and every LLM path remain untested (see `docs/SECURITY.md`).
