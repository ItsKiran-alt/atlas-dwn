# Phase 4: real market and news data

Tests: `.venv\Scripts\python -m pytest tests -q` → **76 passed** (42 new, all offline with a fake network).
Live check: `.venv\Scripts\python scripts\live_smoke.py` (real network, throwaway database).

## Sources chosen (smallest set that works)
| Source | Used for | Key? | Status I verified |
|---|---|---|---|
| Yahoo Finance chart endpoint (`query1.finance.yahoo.com`) | S&P 500, SPY, AGG, 10-yr yield, VNQ, GLD, EUR/USD | none | **Live run OK** (7/7, timestamps 6-60 s old; yield index 15 min, its normal delay) |
| Federal Reserve RSS (monetary policy, all releases) | official news | none | Live run OK |
| SEC press-release RSS | official news | none | Live run OK |
| BLS latest-releases RSS | economic releases | none | Live run OK |
| Alpha Vantage `GLOBAL_QUOTE` | **optional fallback**, ETFs only, daily data | free key | **Code + tests only; never run live (no key)**. Free tier is 25 requests/day per [alphavantage.co/premium](https://www.alphavantage.co/premium); we budget 20 |
| FRED | **not used.** Its official API needs a key; I did not rely on the unofficial CSV download | key | skipped |

**Caveats you should know**
- **Yahoo is unofficial.** No key or SLA; the yfinance project says it is for personal/research use and I could not retrieve Yahoo's own terms text. Fine for this case-study prototype; **do not treat it as licensed market data** for production. Swapping in a licensed vendor means writing one provider class.
- The Fed feed page states no terms or rate rules; we fetch at most every 15 minutes per feed with a plain User-Agent.
- Stooq (404) and the Treasury XML (timeout) did not work from here, ECB failed certificate checks on this machine; none are used.
- **Disclosure:** during my first connectivity probe I put your Gmail address in the User-Agent header sent to Yahoo, the Fed, SEC, BLS, ECB, Stooq and FRED. It was a one-off diagnostic and I should not have done it. The app now sends no personal data; set `DWN_CONTACT` yourself if you want a contact string (the SEC asks for one).

## What each external record carries
Prices: provider, source URL, **market time** (exchange), **retrieval time**, currency, previous close, change and the calculation used, session window, freshness. News: publisher, link, publication time, retrieval time, summary, quarantine flag. Stored in separate cache tables (`market_quotes`, `news_items`) from client records.

## Rules enforced (and tested)
- **Fresh / stale / closed:** open session: fresh if ≤ 20 min old (the golden-set placeholder), else **stale**. Closed session: "market closed · last close" until 4 days old, then stale. Day-only data is never "fresh". Future timestamps are rejected. Freshness is **recomputed every time it is shown**, so an old good price turns stale on screen.
- **No fake data:** a failed or implausible fetch (e.g. −40% in one update) stores nothing; the page says "Unavailable" and shows no number. Last good data stays, labelled with its age.
- **Retries/fallback:** ≤2 retries on timeout/5xx/429 only; 4xx not retried; then the next provider; failures and last success recorded per source and visible to Admin (Settings) and RM (Research page).
- **Hardening:** https only, host allow-list, redirects only inside the list, 2 MB cap, 8 s timeout, 1 s per-host gap, robots.txt honoured for feeds (RFC 9309), XML parsed with defusedxml (entity bombs rejected), HTML stripped, links must be https on allowed hosts, 14-day window.
- **Untrusted text:** instruction-like news text is **quarantined** (not displayed, not summarised), the source is linked, compliance is alerted through an audit event.
- **Cost/abuse control:** 60 s price cache, 15 min news cache, 30 s minimum gap between refreshes (audited), Alpha Vantage daily budget, only RM/Admin can refresh, **Clients get no market data page at all**.
- Admin can disable any live source; Alpha Vantage shows "Not configured" until a key is set.

## UI changes (same layout classes as your design)
- **Research & Market** now has: Market snapshot table (price, change, "as of" and "retrieved" UTC, status chip, source link), official headlines with publisher/time/link, live-source status, and a **Refresh data** button. Opening the page refreshes automatically if data is stale.
- **Settings → Agent data sources:** live sources listed with real status (OK time or the actual error). Salesforce stays *simulated* and primary.
- **Workbench → "Market update"** line shows the real S&P 500 move with time and source, or says data is stale/unavailable.

## Not done yet
- Client holdings are fictional funds, not mapped to tickers; relevance of news/prices to a specific client comes with the agents (Phase 5).
- Refresh is on demand (button / page open), sequential (~12 s). Scheduled refresh arrives with the scheduler (Phase 6).
- Postgres, Alpha Vantage live and FRED are untested here.
