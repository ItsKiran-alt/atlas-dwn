"""Freshness rules. Pure functions of (market time, now, session window): the same inputs always give the same label.

* session open  : fresh if the price is no older than the maximum age (golden-set placeholder: 20 minutes), else stale
* session closed: the last close is "market_closed" (honest and usable as 'as of'), unless it is older than 4 days
* day-only providers (no time of day): never 'fresh'; closed-market label if the trading day is recent, else stale
"""
from __future__ import annotations

from datetime import datetime, timedelta

CLOSED_MAX_AGE = timedelta(days=4)          # covers a weekend plus a Monday holiday


def classify(market_time: datetime, now: datetime, session_start: datetime | None, session_end: datetime | None,
             max_age_s: int, day_only: bool = False) -> str:
    age = now - market_time
    if age < timedelta(minutes=-5):
        return "unavailable"                 # timestamp in the future: implausible
    if day_only or session_start is None or session_end is None:
        return "market_closed" if age <= CLOSED_MAX_AGE else "stale"
    if session_start <= now <= session_end:
        return "fresh" if age.total_seconds() <= max_age_s else "stale"
    return "market_closed" if age <= CLOSED_MAX_AGE else "stale"


def age_label(age_s: float) -> str:
    s = int(max(age_s, 0))
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60} min"
    if s < 172800:
        return f"{s // 3600} h"
    return f"{s // 86400} days"
