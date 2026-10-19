"""Market data: providers, fallback chain, validation, caching and freshness.

Rules enforced here (financial-services reliability):
* every stored price carries provider, source URL, market time, retrieval time, currency and the calculation applied
* a failed or implausible fetch NEVER produces a number; we keep the last good record and label its age
* free-tier budgets are counted per day and respected
"""
from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .. import config
from ..domain import utcnow
from ..repo import Repo
from .freshness import age_label, classify
from .http import FetchError, Fetcher
from .models import MarketQuote

# symbol -> (display name, kind). The smallest set that covers the asset classes in client portfolios.
WATCHLIST = {
    "^GSPC": ("S&P 500", "index"),
    "SPY": ("SPDR S&P 500 ETF (equity proxy)", "etf"),
    "AGG": ("iShares Core US Aggregate Bond ETF (bond proxy)", "etf"),
    "^TNX": ("US 10-year Treasury yield (%)", "yield"),
    "VNQ": ("Vanguard Real Estate ETF (alternatives proxy)", "etf"),
    "GLD": ("SPDR Gold Shares (gold proxy)", "etf"),
    "EURUSD=X": ("EUR/USD exchange rate", "fx"),
}
# a move bigger than this in one update is treated as a bad tick (golden-set placeholder, compliance owns the real limit)
BAD_TICK = {"index": 0.25, "etf": 0.25, "fx": 0.25, "yield": 1.0}


class ProviderError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _utc(epoch: float | int) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None, microsecond=0)


@dataclass
class YahooChartProvider:
    """Yahoo Finance public chart endpoint. UNOFFICIAL: no key, no SLA, terms restrict use (research/personal;
    verify Yahoo's terms before any commercial use). Chosen as the smallest working primary; a documented fallback exists."""
    id: str = "yahoo"
    label: str = "Yahoo Finance chart data (unofficial)"
    host: str = "query1.finance.yahoo.com"

    def configured(self) -> bool:
        return True

    def supports(self, symbol: str) -> bool:
        return symbol in WATCHLIST

    def url(self, symbol: str) -> str:
        return f"https://{self.host}/v8/finance/chart/{urllib.parse.quote(symbol)}?range=5d&interval=1d"

    def fetch(self, symbol: str, fetcher: Fetcher, now: datetime) -> MarketQuote:
        name, kind = WATCHLIST[symbol]
        url = self.url(symbol)
        raw = fetcher.get(url).body
        try:
            data = json.loads(raw)
            res = data["chart"]["result"][0]
            meta = res["meta"]
            price = float(meta["regularMarketPrice"])
            mtime = _utc(meta["regularMarketTime"])
            tz_off = int(meta.get("gmtoffset", meta.get("currentTradingPeriod", {}).get("regular", {}).get("gmtoffset", 0)) or 0)
            reg = meta.get("currentTradingPeriod", {}).get("regular", {})
            s_start = _utc(reg["start"]) if "start" in reg else None
            s_end = _utc(reg["end"]) if "end" in reg else None
            ts = res.get("timestamp") or []
            closes = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
            bars = [(t, c) for t, c in zip(ts, closes) if c is not None]
            prev = None
            note = "change = price - previous session close"
            if len(bars) >= 2:
                last_day = _utc(bars[-1][0] + tz_off).date()
                same_day = last_day == _utc(meta["regularMarketTime"] + tz_off).date()
                prev = float(bars[-2][1] if same_day else bars[-1][1])
            cur = str(meta.get("currency") or "")
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as e:
            raise ProviderError("parse", f"unexpected response shape ({type(e).__name__})") from e
        if len(cur) != 3:
            raise ProviderError("parse", "currency missing")
        change_abs = change_pct = None
        if prev and prev > 0:
            change_abs = price - prev
            change_pct = (price / prev - 1.0) * 100.0
        return MarketQuote(symbol=symbol, name=name, kind=kind, price=price, currency=cur, prev_close=prev, change_abs=change_abs,
                           change_pct=change_pct, market_time=mtime, retrieved_at=now, provider=self.id, provider_name=self.label,
                           source_url=url, session_start=s_start, session_end=s_end,
                           transformation=(note if prev else "no previous close available; change not computed"))


@dataclass
class AlphaVantageProvider:
    """Optional fallback. Needs a free API key (ALPHAVANTAGE_API_KEY); the free tier allows 25 requests per day
    (alphavantage.co/premium), so we budget 20. Daily bars only: no time of day, so a price is never labelled 'fresh'.
    Covers ETFs only (no indices / yields / FX)."""
    id: str = "alphavantage"
    label: str = "Alpha Vantage GLOBAL_QUOTE (fallback, daily)"
    host: str = "www.alphavantage.co"

    def configured(self) -> bool:
        return bool(config.ALPHAVANTAGE_API_KEY)

    def supports(self, symbol: str) -> bool:
        return WATCHLIST.get(symbol, ("", ""))[1] == "etf"

    def fetch(self, symbol: str, fetcher: Fetcher, now: datetime) -> MarketQuote:
        name, kind = WATCHLIST[symbol]
        url = f"https://{self.host}/query?function=GLOBAL_QUOTE&symbol={urllib.parse.quote(symbol)}"
        # the key is appended only for the request and never stored or logged
        raw = fetcher.get(url + "&apikey=" + urllib.parse.quote(config.ALPHAVANTAGE_API_KEY)).body
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError("parse", "not JSON") from e
        if "Note" in data or "Information" in data:
            raise ProviderError("rate_limited", (data.get("Note") or data.get("Information") or "limit")[:120])
        try:
            q = data["Global Quote"]
            price = float(q["05. price"])
            day = datetime.strptime(q["07. latest trading day"], "%Y-%m-%d")
            prev = float(q["08. previous close"])
        except (KeyError, ValueError, TypeError) as e:
            raise ProviderError("parse", "unexpected response shape") from e
        mtime = day.replace(hour=21)                           # date only: assume ~US close; labelled as such
        return MarketQuote(symbol=symbol, name=name, kind=kind, price=price, currency="USD", prev_close=prev, change_abs=price - prev,
                           change_pct=(price / prev - 1.0) * 100.0, market_time=min(mtime, now), retrieved_at=now, provider=self.id,
                           provider_name=self.label, source_url=url, day_only_timestamp=True,
                           transformation="provider gives a trading date only; market time assumed 21:00 UTC; change = price - previous close")


def plausible(q: MarketQuote) -> bool:
    if q.change_pct is None:
        return True
    limit = BAD_TICK[q.kind] * 100
    if q.kind == "yield":                           # yield index quoted in percent: judge the absolute move in points
        return abs(q.change_abs or 0) <= 1.5
    return abs(q.change_pct) <= limit


class MarketService:
    def __init__(self, repo: Repo, fetcher: Fetcher | None = None, providers=None, clock=utcnow):
        self.repo = repo
        self.fetcher = fetcher or Fetcher()
        self.providers = providers if providers is not None else [YahooChartProvider(), AlphaVantageProvider()]
        self.clock = clock

    # ---- write side (network) ----
    def refresh(self, symbols=None, force: bool = False) -> dict:
        """Fetch each symbol through the provider chain. Returns a summary; never invents values."""
        now = self.clock()
        out = dict(ok=[], failed={}, skipped=[], providers_used={})
        for sym in symbols or list(WATCHLIST):
            last = self.repo.latest_quote(sym)
            if last and not force and (now - last.retrieved_at).total_seconds() < config.MARKET_CACHE_TTL_S:
                out["skipped"].append(sym)
                continue
            errors = []
            for prov in self.providers:
                src = self.repo.get_source(prov.id)
                if src is not None and not src["enabled"]:
                    errors.append(f"{prov.id}: disabled by admin"); continue
                if not prov.supports(sym):
                    continue
                if not prov.configured():
                    errors.append(f"{prov.id}: not configured"); continue
                if prov.id == "alphavantage" and self.repo.source_calls_today(prov.id) >= config.ALPHAVANTAGE_DAILY_BUDGET:
                    errors.append(f"{prov.id}: daily budget used"); continue
                try:
                    if prov.id == "alphavantage":
                        self.repo.bump_source_calls(prov.id)
                    q = prov.fetch(sym, self.fetcher, now)
                    if not plausible(q):
                        raise ProviderError("implausible", f"implausible move for {sym}: {q.change_pct:+.1f}% in one update (held for verification)")
                    self.repo.save_quote(q)
                    self.repo.record_source_success(prov.id)
                    out["ok"].append(sym); out["providers_used"][sym] = prov.id
                    self.repo.s.commit()                  # release the write lock between network calls
                    break
                except (FetchError, ProviderError, ValueError) as e:
                    msg = f"{type(e).__name__}: {e}"
                    self.repo.record_source_failure(prov.id, f"{sym}: {msg}")
                    errors.append(f"{prov.id}: {msg}")
                    self.repo.s.commit()
            else:
                if not any(s == sym for s in out["ok"]):
                    out["failed"][sym] = "; ".join(errors) or "no provider supports this symbol"
        return out

    # ---- read side (no network) ----
    def view(self, symbols=None) -> list[dict]:
        """Latest stored quotes with freshness recomputed NOW. Missing data is reported as unavailable, never filled in."""
        now = self.clock()
        rows = []
        syms = symbols or list(WATCHLIST)
        stored = self.repo.latest_quotes(syms)
        for sym in syms:
            name, kind = WATCHLIST[sym]
            q = stored.get(sym)
            if q is None:
                rows.append(dict(symbol=sym, name=name, kind=kind, available=False, freshness="unavailable", message="No data retrieved yet."))
                continue
            fresh = classify(q.market_time, now, q.session_start, q.session_end, config.MARKET_MAX_AGE_MIN * 60, q.day_only_timestamp)
            rows.append(dict(symbol=sym, name=q.name, kind=kind, available=True, price=q.price, currency=q.currency, change_abs=q.change_abs,
                             change_pct=q.change_pct, market_time=q.market_time, retrieved_at=q.retrieved_at, provider=q.provider_name,
                             provider_id=q.provider, source_url=q.source_url, freshness=fresh, age=age_label((now - q.market_time).total_seconds()),
                             transformation=q.transformation, day_only=q.day_only_timestamp))
        return rows
