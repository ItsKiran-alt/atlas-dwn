# Security notes and limitations

This is a **case-study prototype with synthetic data**. It runs, and it has real controls, but it is **not enterprise-production-ready** and must not hold real client data without a proper security and compliance review.

## Controls that exist (each has automated tests)
| Area | What is implemented |
|---|---|
| Authorisation | Enforced on the server in `dwn/services.py` for every action; scoping is done in SQL (an RM never loads another RM's rows). A matrix test calls **every client-scoped service with every wrong user** and expects a denial. Forged browser events (other client ids, admin actions by an RM) are refused and audited. |
| Authentication | Salted PBKDF2-SHA256 hashes (200k iterations), generic error messages, lockout after 5 failures (15 min), idle session expiry (30 min), sign-out clears the server session. Minimum 10-character passwords for new clients. |
| Consent | Versioned text hash and timestamps; withdrawal pauses the agent, RM decisions, drafts, the copilot and reports for that client. Existing clients are never asked again. |
| Human approval | The agent has no approval or execution code (checked by a test that parses its source). Tier 3 needs a client conversation and a *different* senior second approver. |
| Output escaping | All dynamic values are HTML-escaped; tests inject script/image/attribute-breakout payloads through client names, notes, drafts, news and LLM output and parse the page like a browser. |
| Untrusted text | News and notes are stripped, length-capped, scanned for instruction-like text (quarantined, never sent to a model) and passed to models only inside delimited data blocks. |
| Model output | Parsed, schema-validated, grounded (quotes and amounts must appear in the source), checked for prohibited wording and untraceable figures; otherwise rejected and replaced by a deterministic fallback. |
| Network | Outbound requests: https only, host allow-list, redirects only inside the list, size and time caps, rate limits, robots.txt for feeds, XML parsed with defusedxml. |
| Secrets | Read from environment variables only; never stored in the database, audit log or error text (tested). `.env.example` holds placeholders. |
| Errors | Unexpected errors show only a reference number; details stay in the server log. |
| Audit | Append-only (database triggers block UPDATE/DELETE); written by code in the same transaction as the action. |
| Production guards | `DWN_ENV=prod` refuses to start on SQLite, or with demo accounts on the default password; the login page shows no demo credentials outside demo mode. |
| Dependencies | `pip-audit` reported **no known vulnerabilities** in the installed packages (checked 2026-10-20); versions are pinned. |

## Known limitations (read before any real use)
1. **No real identity provider.** Own password auth only: no MFA, no email verification, no password reset, no SSO. New-client onboarding creates an account from any email without verifying it.
2. **Account lockout can be abused** to lock a known user out (denial of service). There is no per-IP throttling because Streamlit does not expose client IPs reliably.
3. **Streamlit session model:** state lives in the server process per browser session. There is no CSRF token of our own; we rely on Streamlit's session binding. Cookie flags and security headers are controlled by the host, not by this code.
4. **Demo accounts share one password** (`DWN_DEMO_PASSWORD`, one salt) and exist only in demo mode.
5. **Postgres/Supabase, GitHub Actions and Python 3.12 are untested** (this machine has Python 3.14 and SQLite).
6. **Yahoo Finance data is unofficial** and its terms were not verified; do not treat it as licensed market data.
7. **LLM paths never run live** (no key). Free tiers of some providers may use inputs to improve their products: use only synthetic data.
8. Thresholds, assumptions and wording rules are **placeholders**, not legal or compliance advice; nothing here is a regulatory-compliance claim.
9. No encryption of data at rest beyond what the database host provides; no backup automation (see the deployment guide for the manual process).
10. Logs include user names and client names (synthetic here). Real deployments need a data-protection review (GDPR/CCPA retention and subject-access processes are not implemented).
