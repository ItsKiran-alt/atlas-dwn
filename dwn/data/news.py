"""News ingestion from official RSS feeds (no scraping, no paywalls).

Feeds: Federal Reserve Board (monetary policy, all press releases), SEC press releases, US Bureau of Labor Statistics.
Every item keeps publisher, link, publication time and retrieval time. Feed text is UNTRUSTED: it is parsed with
defusedxml, stripped of markup, length-capped, scanned for instruction-like text (quarantined if found) and its
links must be https on an allow-listed host. A summary written by an LLM is never evidence that an event occurred.
"""
from __future__ import annotations

import hashlib
import html
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from .. import config
from ..controls.quarantine import scan_untrusted_text
from ..domain import utcnow
from ..repo import Repo
from .http import ALLOWED_HOSTS, FetchError, Fetcher
from .models import NewsItem


@dataclass(frozen=True)
class Feed:
    id: str
    label: str
    publisher: str
    url: str


FEEDS = [
    Feed("fed_monetary", "Federal Reserve Board: monetary policy releases", "Federal Reserve Board", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    Feed("fed_press", "Federal Reserve Board: all press releases", "Federal Reserve Board", "https://www.federalreserve.gov/feeds/press_all.xml"),
    Feed("sec_press", "SEC press releases", "U.S. Securities and Exchange Commission", "https://www.sec.gov/news/pressreleases.rss"),
    Feed("bls_latest", "BLS latest releases", "U.S. Bureau of Labor Statistics", "https://www.bls.gov/feed/bls_latest.rss"),
]
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
MAX_AGE = timedelta(days=14)


def clean_text(raw: str, limit: int) -> str:
    t = html.unescape(_TAG.sub(" ", raw or ""))
    t = _WS.sub(" ", t).strip()
    return t[:limit]


def parse_pubdate(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s.strip())
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        return d
    return d.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def parse_feed(xml_bytes: bytes, feed: Feed, now: datetime) -> tuple[list[NewsItem], list[str]]:
    """Return (valid items, problems). Malformed or suspicious entries are dropped and reported, never repaired."""
    problems: list[str] = []
    try:
        root = ET.fromstring(xml_bytes.lstrip(b"\xef\xbb\xbf"))
    except (ET.ParseError, DefusedXmlException) as e:
        return [], [f"feed is not valid XML: {type(e).__name__}"]
    items: list[NewsItem] = []
    for el in root.iter("item"):
        title = clean_text((el.findtext("title") or ""), 300)
        link = (el.findtext("link") or "").strip()
        p = urllib.parse.urlsplit(link)
        if not title or p.scheme != "https" or (p.hostname or "") not in ALLOWED_HOSTS:
            problems.append(f"dropped item with unusable title/link: {link[:80]}"); continue
        published = parse_pubdate(el.findtext("pubDate"))
        if published and published > now + timedelta(hours=1):
            problems.append(f"dropped item dated in the future: {title[:60]}"); continue
        if published and now - published > MAX_AGE:
            continue                                        # old news is not 'current'; skip silently
        summary = clean_text(el.findtext("description") or "", 600)
        reason = scan_untrusted_text(title + " " + summary)
        items.append(NewsItem(guid_hash=hashlib.sha256(link.encode()).hexdigest(), source_id=feed.id, publisher=feed.publisher, title=title,
                              link=link, published_at=published, retrieved_at=now, summary="" if reason else summary,
                              quarantined=bool(reason), quarantine_reason=reason))
    return items, problems


class NewsService:
    def __init__(self, repo: Repo, fetcher: Fetcher | None = None, feeds=None, clock=utcnow):
        self.repo, self.fetcher, self.feeds, self.clock = repo, fetcher or Fetcher(), feeds or FEEDS, clock

    def refresh(self, force: bool = False) -> dict:
        now = self.clock()
        out = dict(new=0, ok=[], failed={}, skipped=[], quarantined=0, problems=[])
        for feed in self.feeds:
            src = self.repo.get_source(feed.id)
            if src is not None and not src["enabled"]:
                out["skipped"].append(feed.id); continue
            last = src["last_success_dt"] if src else None
            if last and not force and (now - last).total_seconds() < config.NEWS_CACHE_TTL_S:
                out["skipped"].append(feed.id); continue          # TTL: the cache is the answer between refreshes
            try:
                resp = self.fetcher.get(feed.url, respect_robots=True)
                items, problems = parse_feed(resp.body, feed, now)
                out["problems"] += [f"{feed.id}: {p}" for p in problems]
                fresh = self.repo.upsert_news(items)
                for it in fresh:
                    if it.quarantined:
                        out["quarantined"] += 1
                        self.repo.log("—", "Untrusted text quarantined", "Control layer", f"{feed.publisher}: instruction-like text in a news item ({it.quarantine_reason[:60]}); link {it.link}", "Review", "Policy")
                out["new"] += len(fresh)
                self.repo.record_source_success(feed.id)
                out["ok"].append(feed.id)
                self.repo.s.commit()                              # do not hold a write lock across the next network call
            except (FetchError, ValueError) as e:
                self.repo.record_source_failure(feed.id, f"{type(e).__name__}: {e}")
                out["failed"][feed.id] = str(e)
                self.repo.s.commit()
        return out

    def latest(self, limit: int = 10) -> list[NewsItem]:
        return self.repo.list_news(limit=limit, since=self.clock() - MAX_AGE)
