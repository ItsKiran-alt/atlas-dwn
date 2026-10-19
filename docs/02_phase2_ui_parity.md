# Phase 2: UI reproduction in Streamlit: parity report

Run locally: `.venv\Scripts\python -m streamlit run app.py` · tests: `.venv\Scripts\python -m pytest tests -q` (26 passed).
Demo sign-ins (demo-only, password `atlas-demo`): `admin@atlas-demo.com` · `priya.sharma@atlas-demo.com` (24 clients) · `ramesh.agarwal@atlas-demo.com` (client). Other RMs: `arjun.mehta@…` (13 clients incl. golden K01-K12 and Ramesh), `neha.kapoor@…`. Every client logs in as `first.last@atlas-demo.com`.

## How it works
- `ui_component/atlas.css` is the **original stylesheet, byte-for-byte**. Markup and copy are ported from your HTML into `dwn/ui/render.py` and filled with data the signed-in user may see.
- A small Streamlit custom component (`ui_component/index.html`) draws the HTML full-viewport and handles pure-UI behaviour (tabs, filters, modals, form toggles). **Every action that changes data goes to Python** (`controller.py` → `services.py`), which re-checks role and client ownership.
- State is held server-side in `dwn/store.py` (in-memory, shared across sessions). **It resets when the app restarts**; Phase 3 moves it to a database.

## Verified by running the app (headless-driven through the real UI)
| Area | Result |
|---|---|
| Login page, 3 role cards, bad password and wrong-role rejected | Pass |
| RM workbench: 24-client queue, filters, name search, subtabs, client switch, donut from real weights, 1Y/3Y/5Y chips | Pass |
| Review modal: note required; Tier-2 approval refused for a Tier-1 RM; decision logged | Pass |
| Draft message, adviser note, consent request, CRM record, transaction history modals | Pass |
| Clients page (24, search), global search, Home/Insights/Research/Tasks/Reports/Client View render | Pass |
| Settings & Scheduler sits in the main area beside the sidebar | Pass |
| Scheduler: frequency fields, scope, "Selected client only" picker with search + checkboxes + count, save, preview | Pass |
| Admin: only Compliance + Settings; permissions panel; add/remove sources; Salesforce shown as primary, "Connected · Simulated" | Pass |
| RM scheduling turned off by Admin → nav refused, and forged save/preview refused on the server | Pass |
| Forged events: RM opening another RM's client, RM/Client calling admin actions, Admin recording an RM decision | All refused |
| Client portal: own holdings and transactions only; existing clients never see the consent form; new client sees it once, consent stored with version + time | Pass |
| CSV / Markdown downloads (queue, audit, report) | Pass |
| Layout probe vs original at 1440×900 (rects/fonts/colours of nav, queue rows, chips, tier badge, search, buttons) | Identical where measured |

## Intentional deviations from your HTML (please approve or reject each)
1. **Currency/wording:** ₹→$, crore→million, SEBI→SEC/FINRA (approved Q1). Prototype "Cr" figures became $M one-for-one.
2. **"Client View" reachable:** your HTML's `Client View →` button toasted "not available" for every role (a bug). RM can now open it; still no tab strip.
3. **Admin-only content hidden from RM** (permissions panel, add/remove source buttons); RM sees sources read-only. Your prompt required this; the HTML showed them to everyone.
4. **No more "any password works".** Sign-in checks real demo accounts.
5. **View in CRM** now opens a read-only record from the simulated Salesforce connector (HTML only toasted).
6. **View holdings history** now shows holdings + transaction history.
7. **Reports / exports / Ask Atlas AI** do real work from stored data: files download; Ask is rule-based until Phase 5.
8. **Metrics are computed** (e.g. "Clients need attention 18", Tasks badge 5), not the HTML's static 8 and 3.
9. **Review modal** adds a "Monitoring consent on file" row; Admin sees the modal read-only.
10. **Scheduler** note says plainly that nothing runs yet.

## Not done / honest limits
- **No persistence across restarts, no real identity provider** (Phase 3). New-client onboarding creates a session without a password; Phase 3 adds account creation.
- **Consent withdrawal** exists in the backend and tests, but there is **no button for it** (your design has none). Needs your approval to add one in the client portal.
- **Market/news, goal progress, performance chart, "Passed*" policy checks are illustrative.** Real data (Phase 4) and engines/agents (Phase 5) replace them. Research page deliberately makes no market claims.
- **Not yet screenshot-compared page by page.** The preview pane is small and cropped full-page screenshots; I compared computed layout numbers and spot visuals. Pages other than the RM workbench and login were verified structurally, not pixel-by-pixel. Mobile widths use your original media queries but were not exercised.
- **Scheduler runs nothing yet; no LLM, no agents** (Phases 5-6). "Validate by running the agent" therefore starts in Phase 5; today's runnable checks are the 26 tests and the 36-scenario reference check.
- Golden set: five clients under $2M were scaled up to meet the case's $2M+ threshold (a test caught it); still 36/36.
