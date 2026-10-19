"""Synthetic demo data. Every record here is fictional (USD). Replaced by a database in Phase 3.

Client sets (both approved):
  * HTML_CLIENTS: the 24 clients in the supplied prototype, re-denominated 1 crore -> 1 million USD
    (e.g. "5.2 Cr" -> "$5.2M") so every client meets the case's $2M+ threshold.
  * GOLDEN_CLIENTS: K01-K12 from golden/scenarios.py, so the golden-set scenarios can be run against real records.
Illustrative fields (goal progress, performance, history) are labelled as such in the UI and
are replaced by engine output in Phase 5.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from .domain import RM, Client, Goal  # noqa: F401  (re-exported for callers)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "golden"))

CLASSES = ["EQ", "FI", "CA", "AL"]



RMS = [
    RM("rm-priya", "Priya Sharma", "priya.sharma@atlas-demo.com", "PS"),
    RM("rm-arjun", "Arjun Mehta", "arjun.mehta@atlas-demo.com", "AM"),
    RM("rm-neha", "Neha Kapoor", "neha.kapoor@atlas-demo.com", "NK"),
]

# name, AUM (millions USD, from the prototype's crore figure), issue, kind
_HTML_RAW = [
    ("Rajesh Menon", 5.2, "Portfolio drift detected", "review"), ("Ananya Singh", 12.4, "Market event impact", "review"),
    ("Vikram Kapoor", 3.8, "Goal tracking update", "approval"), ("Sneha Patel", 8.6, "Rebalance opportunity", "review"),
    ("Daniel Gonsalves", 2.1, "Risk level increased", "review"), ("Neha Prakash", 4.7, "Consent pending", "approval"),
    ("Abhishek Rao", 6.3, "Quarterly review due", "review"), ("Kavita Iyer", 9.1, "Tax planning opportunity", "review"),
    ("Meera Shah", 7.4, "Quarterly review due", "review"), ("Arjun Malhotra", 11.2, "Goal projection refresh", "approval"),
    ("Pooja Nair", 3.4, "Risk profile check", "review"), ("Rohan Desai", 6.8, "Market event impact", "review"),
    ("Ishita Verma", 4.2, "Consent follow-up", "approval"), ("Sanjay Kulkarni", 14.6, "Tax planning opportunity", "review"),
    ("Nandita Bose", 2.9, "Portfolio review due", "review"), ("Rahul Khanna", 8.2, "Allocation drift detected", "review"),
    ("Aditi Menon", 5.7, "Goal tracking update", "approval"), ("Devika Reddy", 10.3, "Risk scenario review", "review"),
    ("Karan Mehta", 3.1, "Quarterly review due", "review"), ("Simran Gill", 7.9, "Market event impact", "review"),
    ("Aman Joshi", 4.5, "Portfolio concentration check", "approval"), ("Tara Srinivasan", 12.1, "Goal projection refresh", "review"),
    ("Nikhil Bhat", 6.1, "Rebalance opportunity", "review"), ("Farah Khan", 9.8, "Annual review due", "review"),
]
# The first eight keep the exact status chips from the prototype.
_FIRST_STATUS = {
    "Rajesh Menon": ("Review", "high"), "Ananya Singh": ("Action", ""), "Vikram Kapoor": ("Info", "info"),
    "Sneha Patel": ("Review", "high"), "Daniel Gonsalves": ("Review", "high"), "Neha Prakash": ("Consent", ""),
    "Abhishek Rao": ("Info", "info"), "Kavita Iyer": ("Review", "high"),
}
_GOLDEN_NAMES = {
    "K01": "Helen Brooks", "K02": "Marcus Chen", "K03": "Walter Hayes", "K04": "Olivia Grant", "K05": "Samuel Okafor",
    "K06": "Eleanor Whitcombe", "K07": "Lukas Berger", "K08": "Margaret Ellison", "K09": "Tyler Ross",
    "K10": "Diane Fischer", "K11": "Carlos Mendes", "K12": "Naomi Katz",
}


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest(), 16)


def slug(name: str) -> str:
    return name.lower().replace(" ", ".")


def _split(name, aum, weights):
    """Holdings from class weights (percent) and total AUM in millions."""
    out = []
    eq, fi, ca, al = (weights[c] for c in CLASSES)
    if eq:
        out += [("Atlas Large Cap Fund", "Equity", aum * eq / 100 * 0.6), ("Global Equity Fund", "International equity", aum * eq / 100 * 0.4)]
    if fi:
        out.append(("Government & corporate bonds", "Fixed income", aum * fi / 100))
    if al:
        out.append(("Atlas Real Assets Fund", "Alternatives", aum * al / 100))
    if ca:
        out.append(("Cash & liquid funds", "Cash", aum * ca / 100))
    return out


def _transactions(name, holdings):
    days = [(12, "Oct"), (28, "Sep"), (3, "Sep"), (19, "Aug")]
    kinds = [("Purchase", "Completed", 0.5), ("Dividend", "Credited", 0.012), ("Redemption", "Completed", 0.3), ("Purchase", "Completed", 0.4)]
    rows = []
    for i, ((d, m), (kind, status, f)) in enumerate(zip(days, kinds)):
        inv = holdings[_h(name, i) % len(holdings)][0]
        base = holdings[_h(name, i) % len(holdings)][2] * 1_000_000
        amount = int(round(base * f / 1000.0) * 1000) if kind != "Dividend" else int(round(base * f / 100.0) * 100)
        rows.append((f"{d:02d} {m} 2026", kind, inv, max(amount, 5000), status))
    return rows


def _goals(name, plan_goal_names):
    return [Goal(n, d, 40 + _h(name, n) % 56) for n, d in plan_goal_names]


def _build_html_clients():
    clients = []
    for name, aum, issue, kind in _HTML_RAW:
        label, cls = _FIRST_STATUS.get(name, ("Review", "high") if kind == "review" else ("Action", "info"))
        if name == "Rajesh Menon":
            plan = {"EQ": 60, "FI": 40, "CA": 0, "AL": 0}; weights = {"EQ": 70, "FI": 20, "CA": 5, "AL": 5}
        else:
            eq = 50 + 5 * (_h(name, "eq") % 4)
            plan = {"EQ": eq, "FI": 100 - eq - 5, "CA": 5, "AL": 0}
            drift = (_h(name, "d") % 9) - 3           # -3..+5 points of equity
            weights = {"EQ": eq + drift, "FI": plan["FI"] - drift - 2, "CA": 5, "AL": 2}
        c = Client(id="c-" + slug(name), name=name, rm_id="rm-priya", aum_musd=aum, issue=issue, kind=kind, status_label=label,
                   status_class=cls, since=(2018 if name == "Rajesh Menon" else 2012 + _h(name, "since") % 12), email=slug(name) + "@atlas-demo.com", plan=plan, weights=weights,
                   has_consent=(name not in ("Neha Prakash", "Ishita Verma")))
        c.holdings = _split(name, aum, weights)
        c.transactions = _transactions(name, c.holdings)
        if name == "Rajesh Menon":
            c.goals = [Goal("Retirement at age 60", "Target $8M · 14 years", 76, "Retirement"), Goal("Child education", "Target $800k · 8 years", 85, "Education"),
                       Goal("Wealth transfer", "Estate planning review", 45, "Legacy")]
        else:
            c.goals = _goals(name, [("Retirement", f"Target ${aum * 1.6:.1f}M · {10 + _h(name, 'y') % 12} years"),
                                    ("Education fund", f"Target ${aum * 0.12:.1f}M · {5 + _h(name, 'e') % 8} years")])
        clients.append(c)
    return clients


def _build_golden_clients():
    from scenarios import CLIENTS as G
    out = []
    for key, g in G.items():
        name = _GOLDEN_NAMES[key]
        aum = g["portfolio"] / 1_000_000
        plan = {k: round(g["plan"][k] * 100) for k in CLASSES}
        plan["EQ"] += round(g["plan"]["SS"] * 100)            # single stock is shown inside equity in the UI
        w = dict(plan)
        c = Client(id="c-" + key.lower(), name=name, rm_id="rm-arjun", aum_musd=aum, issue=g["persona"], kind="review",
                   status_label="Review", status_class="high", since=2015 + _h(key) % 9, email=slug(name) + "@atlas-demo.com",
                   risk_profile=g["risk"], plan=plan, weights=w, has_consent=g["consent"], source="golden", golden_key=key,
                   contact_pref=g["contact_text"])
        c.goals = [Goal(g["goal"]["name"], f"Target ${g['goal']['target']:,} · {g['goal']['years']:g} years", 50 + _h(key, "p") % 40)]
        c.holdings = _split(name, aum, w)
        c.transactions = _transactions(name, c.holdings)
        if not g["consent"]:
            c.status_label, c.status_class, c.issue = "Consent", "", "Consent pending"
        out.append(c)
    return out


def _ramesh():
    c = Client(id="c-ramesh.agarwal", name="Ramesh Agarwal", rm_id="rm-arjun", aum_musd=9.4, issue="Annual review", kind="review",
               status_label="Info", status_class="info", since=2016, email="ramesh.agarwal@atlas-demo.com",
               plan={"EQ": 48, "FI": 24, "CA": 8, "AL": 20}, weights={"EQ": 48, "FI": 22, "CA": 9, "AL": 21}, source="html")
    c.holdings = [("Atlas Large Cap Fund", "Equity", 2.8), ("Government & corporate bonds", "Fixed income", 2.1),
                  ("Global Equity Fund", "International equity", 1.5), ("Balanced Advantage Fund", "Hybrid", 1.2),
                  ("Listed shares", "Equity", 1.0), ("Cash & liquid funds", "Cash", 0.8)]
    c.transactions = [("12 Oct 2026", "Purchase", "Atlas Large Cap Fund", 500_000, "Completed"),
                      ("28 Sep 2026", "Dividend", "Government & corporate bonds", 82_500, "Credited"),
                      ("03 Sep 2026", "Redemption", "Balanced Advantage Fund", 200_000, "Completed"),
                      ("19 Aug 2026", "Purchase", "Global Equity Fund", 350_000, "Completed")]
    c.goals = [Goal("Retirement", "Target $15M · 12 years", 62)]
    return c


HTML_CLIENTS = _build_html_clients()
GOLDEN_CLIENTS = _build_golden_clients()
RAMESH = _ramesh()
ALL_CLIENTS = HTML_CLIENTS + GOLDEN_CLIENTS + [RAMESH]

DATA_SOURCES = [
    dict(id="salesforce", name="Salesforce CRM", label="Salesforce CRM (demo)", primary=True,
         reads="Client identity, contact details, relationship profile and account-to-client mapping", default=True),
    dict(id="portfolio", name="Portfolio records", label="Portfolio records (demo)", primary=False, reads="Holdings, balances and transactions", default=True),
    dict(id="market", name="Market & event feed", label="Market & event feed (demo)", primary=False, reads="Prices, market headlines and event signals", default=True),
    dict(id="crm", name="Legacy CRM", label="Legacy CRM (demo)", primary=False, reads="Client profile and relationship context", default=True),
    dict(id="notes", name="RM notes", label="RM notes (demo)", primary=False, reads="Adviser notes and review signals", default=True),
    dict(id="policy", name="Policy & suitability rules", label="Policy & suitability rules (demo)", primary=False, reads="Eligibility and mandatory control checks", default=True),
    dict(id="custody", name="Custodian / account feed", label="Custodian / account feed (demo)", primary=False, reads="Account balances and custody records", default=False),
    dict(id="goals", name="Client goals & risk profile", label="Client goals & risk profile (demo)", primary=False, reads="Goals, horizon and risk preferences", default=False),
    dict(id="research", name="Approved research feed", label="Approved research feed (demo)", primary=False, reads="Approved research notes and market commentary", default=False),
    dict(id="tax", name="Tax lots & transaction costs", label="Tax lots & transaction costs (demo)", primary=False, reads="Tax lots, estimated tax and transaction-cost inputs", default=False),
]

# Demo-only accounts. Passwords are verified against PBKDF2 hashes (dwn/auth.py); real auth arrives in Phase 3.
DEMO_PASSWORD = "atlas-demo"
ADMIN_EMAIL = "admin@atlas-demo.com"
