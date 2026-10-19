"""Registry entries for REAL external sources (mode='live'). Salesforce and the other demo connectors stay simulated."""
from __future__ import annotations

LIVE_SOURCES = [
    dict(id="yahoo", name="Yahoo Finance chart data", label="Yahoo Finance prices (live, unofficial)", mode="live", enabled=True,
         reads="Index, ETF, Treasury-yield and FX prices with exchange timestamps. Unofficial endpoint: no key, no SLA; verify Yahoo's terms before commercial use"),
    dict(id="alphavantage", name="Alpha Vantage", label="Alpha Vantage prices (live, fallback)", mode="live", enabled=False,
         reads="Daily ETF quotes as a fallback. Needs a free API key (25 requests/day); not used until configured and enabled"),
    dict(id="fed_monetary", name="Federal Reserve: monetary policy", label="Federal Reserve monetary policy releases (live RSS)", mode="live", enabled=True,
         reads="Official FOMC and monetary policy press releases"),
    dict(id="fed_press", name="Federal Reserve: press releases", label="Federal Reserve press releases (live RSS)", mode="live", enabled=True,
         reads="Official Federal Reserve Board press releases"),
    dict(id="sec_press", name="SEC press releases", label="SEC press releases (live RSS)", mode="live", enabled=True,
         reads="Official U.S. Securities and Exchange Commission announcements"),
    dict(id="bls_latest", name="BLS latest releases", label="BLS economic releases (live RSS)", mode="live", enabled=True,
         reads="Official U.S. Bureau of Labor Statistics data releases (e.g. employment, CPI)"),
    dict(id="groq", name="Groq LLM", label="Groq language model (live, optional)", mode="live", enabled=False,
         reads="Drafts and interprets only; never calculates or approves. Needs GROQ_API_KEY and DWN_LLM_PROVIDER=groq. Not used until an Admin enables it"),
    dict(id="gemini", name="Google Gemini LLM", label="Google Gemini language model (live, optional)", mode="live", enabled=False,
         reads="Drafts and interprets only; never calculates or approves. Needs GEMINI_API_KEY and DWN_LLM_PROVIDER=gemini. Free-tier data may be used by Google to improve its products: do not use with real client data"),
]
