"""Which interpreted market events matter for ONE client, and a cache key for the AI-drafted outlook.
Pure functions over data the caller is already allowed to see (the client's own record and the shared interpretations)."""
from __future__ import annotations

import hashlib
import json

LABELS = {"rates_monetary": "Interest rates / monetary policy", "labour_inflation_data": "Jobs and inflation data",
          "regulatory_enforcement": "Regulation / enforcement", "market_structure": "Market structure", "other": "Other"}
NAMES = {"EQ": "Equities", "FI": "Bonds", "AL": "Alternatives", "CA": "Cash", "SS": "Single stock"}
HELD = ("EQ", "FI", "AL", "CA")
_RANK = {"high": 0, "medium": 1}


def relevant_events(client, news: list, interp: dict) -> list[dict]:
    """High/medium-relevance headlines whose asset classes this client actually holds, most relevant and most exposed first."""
    out = []
    for n in news:
        it = interp.get(n.guid_hash)
        if not it or it["relevance"] not in _RANK:
            continue
        classes = [k for k in it["classes"] if k in NAMES]
        exposure = sum(client.weights.get(k, 0) for k in classes if k in HELD)
        if exposure <= 0:
            continue
        out.append(dict(guid=n.guid_hash, title=n.title, link=n.link, publisher=n.publisher, event_type=it["event_type"], label=LABELS.get(it["event_type"], "Other"),
                        classes=classes, class_names=[NAMES[k] for k in classes], relevance=it["relevance"], fact=it["fact"],
                        interpretation=it["interpretation"], provider=it["provider"], exposure=exposure))
    out.sort(key=lambda e: (_RANK[e["relevance"]], -e["exposure"], e["title"]))
    return out


def impact_key(client, events: list[dict]) -> str:
    """Changes when the relevant events or the client's mix change, so the outlook is redrafted only when needed."""
    basis = json.dumps([[e["guid"] for e in events], {k: client.weights.get(k, 0) for k in HELD}], sort_keys=True)
    return hashlib.sha1(basis.encode()).hexdigest()
