"""Pure schedule arithmetic. All times are UTC (the UI says so). No clock, no database: same inputs, same answer."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _hm(cfg: dict) -> tuple[int, int]:
    try:
        h, m = (cfg.get("time") or "08:30").split(":")[:2]
        return max(0, min(23, int(h))), max(0, min(59, int(m)))
    except (ValueError, AttributeError):
        return 8, 30


def _matches(cfg: dict, d: date) -> bool:
    f = cfg.get("frequency", "weekly")
    if f == "daily":
        return True
    if f == "weekly":
        return DOW[d.weekday()] in (cfg.get("days") or [])
    if f == "monthly":
        md = str(cfg.get("month_day", "1"))
        last = calendar.monthrange(d.year, d.month)[1]
        return d.day == last if md == "last" else d.day == min(int(md), last)
    return False


def _slots_near(cfg: dict, now: datetime, back: int, forward: int):
    h, m = _hm(cfg)
    for off in range(-back, forward + 1):
        d = (now + timedelta(days=off)).date()
        if _matches(cfg, d):
            yield datetime(d.year, d.month, d.day, h, m)


def latest_slot(cfg: dict, now: datetime) -> datetime | None:
    """The most recent scheduled instant at or before `now`."""
    past = [s for s in _slots_near(cfg, now, 62, 0) if s <= now]
    return max(past) if past else None


def next_slot(cfg: dict, now: datetime) -> datetime | None:
    fut = [s for s in _slots_near(cfg, now, 0, 62) if s > now]
    return min(fut) if fut else None


def describe(slot: datetime | None) -> str:
    return slot.strftime("%a %d %b %Y %H:%M UTC") if slot else "no upcoming run"
