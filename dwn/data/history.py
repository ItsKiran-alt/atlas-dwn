"""Weekly price history of the market proxies, used only by the estimated-performance charts.

Same rules as the rest of the data layer: a failed or implausible fetch stores nothing and never produces a number; the last good
history stays and is labelled with its age. Refreshed at most once a day (history changes slowly)."""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta, timezone

from ..domain import utcnow
from ..engines.performance import SYMBOLS
from ..repo import Repo
from .http import FetchError, Fetcher

HISTORY_TTL = timedelta(hours=20)
MAX_WEEKLY_MOVE = 0.45            # a bigger one-week move is treated as bad data (placeholder; compliance owns real limits)


def _day(epoch: float, tz_off: int = 0):
    return datetime.fromtimestamp(epoch + tz_off, tz=timezone.utc).date()


def parse_weekly(raw: bytes | str) -> list[tuple]:
    data = json.loads(raw)
    res = data["chart"]["result"][0]
    tz_off = int(res.get("meta", {}).get("gmtoffset", 0) or 0)
    ts = res.get("timestamp") or []
    closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
    bars = [(_day(t, tz_off), float(c)) for t, c in zip(ts, closes) if c is not None and c > 0]
    if len(bars) < 20:
        raise ValueError("too few weekly bars")
    for (_, c0), (_, c1) in zip(bars, bars[1:]):
        if abs(c1 / c0 - 1.0) > MAX_WEEKLY_MOVE:
            raise ValueError("implausible weekly move in history")
    return bars


class HistoryService:
    def __init__(self, repo: Repo, fetcher: Fetcher | None = None, clock=utcnow):
        self.repo, self.fetcher, self.clock = repo, fetcher or Fetcher(), clock

    def is_stale(self) -> bool:
        last = self.repo.history_retrieved_at("SPY")
        return last is None or self.clock() - last > HISTORY_TTL

    def refresh(self, force: bool = False) -> dict:
        out = dict(ok=[], failed={}, skipped=[])
        now = self.clock()
        for sym in SYMBOLS:
            last = self.repo.history_retrieved_at(sym)
            if last and not force and now - last < HISTORY_TTL:
                out["skipped"].append(sym)
                continue
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=5y&interval=1wk"
            try:
                bars = parse_weekly(self.fetcher.get(url).body)
                self.repo.save_history(sym, bars, "yahoo", now)
                self.repo.s.commit()
                out["ok"].append(sym)
            except (FetchError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                out["failed"][sym] = f"{type(e).__name__}: {str(e)[:80]}"
        return out
