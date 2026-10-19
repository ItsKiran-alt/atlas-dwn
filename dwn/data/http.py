"""Hardened HTTP client for external data.

* https only, host allow-list (no SSRF), redirects only within the allow-list, response size cap, timeout
* bounded retries with backoff (timeouts, 5xx, 429 only), per-host minimum interval (rate limit)
* optional robots.txt check (RFC 9309: 4xx = allowed, unreachable/5xx = NOT allowed)
* injectable transport and clock so tests never touch the network
"""
from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from urllib.robotparser import RobotFileParser

from .. import config

ALLOWED_HOSTS = {
    "query1.finance.yahoo.com", "www.alphavantage.co",
    "www.federalreserve.gov", "www.sec.gov", "www.bls.gov",
}


class FetchError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind            # blocked | robots | timeout | network | http | too_large | rate_limited


@dataclass
class Response:
    status: int
    body: bytes
    url: str
    headers: dict = field(default_factory=dict)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def urllib_transport(url: str, headers: dict, timeout: float) -> Response:
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        r = opener.open(urllib.request.Request(url, headers=headers), timeout=timeout)
        return Response(r.status, r.read(config.HTTP_MAX_BYTES + 1), url, dict(r.headers))
    except urllib.error.HTTPError as e:
        return Response(e.code, b"", url, dict(e.headers or {}))
    except TimeoutError as e:
        raise FetchError("timeout", f"timed out after {timeout}s") from e
    except (urllib.error.URLError, OSError) as e:
        raise FetchError("network", f"{type(e).__name__}: {str(e)[:100]}") from e


class Fetcher:
    def __init__(self, transport=urllib_transport, sleep=time.sleep, clock=time.monotonic,
                 retries: int | None = None, timeout: float | None = None, min_interval_s: float = 0.4, hosts=None):
        self.transport, self.sleep, self.clock = transport, sleep, clock
        self.retries = config.HTTP_RETRIES if retries is None else retries
        self.timeout = config.HTTP_TIMEOUT_S if timeout is None else timeout
        self.min_interval = min_interval_s
        self.hosts = set(hosts or ALLOWED_HOSTS)
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._robots: dict[str, tuple[float, RobotFileParser | None]] = {}
        self.calls = 0                                     # network attempts made (for tests and budgets)

    def _check(self, url: str) -> urllib.parse.SplitResult:
        p = urllib.parse.urlsplit(url)
        if p.scheme != "https":
            raise FetchError("blocked", "only https URLs are allowed")
        if (p.hostname or "") not in self.hosts:
            raise FetchError("blocked", f"host not on the allow-list: {p.hostname}")
        return p

    def _throttle(self, host: str):
        with self._lock:
            wait = self._last.get(host, -1e9) + self.min_interval - self.clock()
            if wait > 0:
                self.sleep(wait)
            self._last[host] = self.clock()

    def _attempt(self, url: str, headers: dict) -> Response:
        host = self._check(url).hostname
        self._throttle(host)
        self.calls += 1
        return self.transport(url, headers, self.timeout)

    def robots_allows(self, url: str) -> bool:
        p = self._check(url)
        host = p.hostname
        now = self.clock()
        cached = self._robots.get(host)
        if cached and now - cached[0] < 86400:
            rp = cached[1]
        else:
            try:
                r = self._attempt(f"https://{host}/robots.txt", {"User-Agent": config.USER_AGENT})
            except FetchError:
                r = None
            if r is None or r.status >= 500 or r.status == 429:
                rp = None                                   # unreachable: treat as disallowed
                self._robots[host] = (now, None)
                return False
            if 400 <= r.status < 500:
                rp = RobotFileParser(); rp.parse([])          # no robots file: everything allowed
            else:
                rp = RobotFileParser(); rp.parse(r.body.decode("utf-8", "replace").splitlines())
            self._robots[host] = (now, rp)
        return bool(rp and rp.can_fetch("AtlasDWN-prototype", url))

    def get(self, url: str, *, headers: dict | None = None, respect_robots: bool = False) -> Response:
        self._check(url)
        if respect_robots and not self.robots_allows(url):
            raise FetchError("robots", "fetching is disallowed by robots.txt")
        hdr = {"User-Agent": config.USER_AGENT, "Accept": "*/*", **(headers or {})}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            cur = url
            try:
                for _hop in range(3):                      # follow redirects only inside the allow-list
                    r = self._attempt(cur, hdr)
                    if r.status in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                        cur = urllib.parse.urljoin(cur, r.headers["Location"])
                        self._check(cur)
                        continue
                    break
                if len(r.body) > config.HTTP_MAX_BYTES:
                    raise FetchError("too_large", "response larger than the size cap")
                if r.status == 429 or r.status >= 500:
                    raise FetchError("rate_limited" if r.status == 429 else "http", f"HTTP {r.status}")
                if r.status >= 400:
                    raise FetchError("http", f"HTTP {r.status}")
                return r
            except FetchError as e:
                last = e
                if e.kind in ("blocked", "robots", "too_large") or (e.kind == "http" and "HTTP 4" in str(e)):
                    raise                                   # not retryable
                if attempt < self.retries:
                    self.sleep(0.5 * (2 ** attempt))
        assert last is not None
        raise last
