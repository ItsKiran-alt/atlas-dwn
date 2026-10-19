"""Typed, validated records for external data. Every record carries its provenance."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Freshness = Literal["fresh", "market_closed", "stale", "unavailable"]


class MarketQuote(BaseModel):
    symbol: str
    name: str
    kind: Literal["index", "etf", "yield", "fx"]
    price: float
    currency: str
    prev_close: Optional[float] = None
    change_abs: Optional[float] = None
    change_pct: Optional[float] = None
    market_time: datetime                     # when the exchange produced this price (UTC, naive)
    retrieved_at: datetime                    # when WE fetched it (UTC, naive)
    provider: str                             # provider id, e.g. yahoo
    provider_name: str
    source_url: str
    session_start: Optional[datetime] = None
    session_end: Optional[datetime] = None
    day_only_timestamp: bool = False          # provider gives a date, not a time
    transformation: str = ""                  # every calculation applied to the raw values

    @field_validator("price")
    @classmethod
    def _price_ok(cls, v):
        if not math.isfinite(v) or v <= 0:
            raise ValueError("price must be a positive finite number")
        return v

    @field_validator("source_url")
    @classmethod
    def _https(cls, v):
        if not v.startswith("https://"):
            raise ValueError("source_url must be https")
        return v

    @model_validator(mode="after")
    def _times(self):
        if self.market_time > self.retrieved_at + timedelta(minutes=5):
            raise ValueError("market_time is in the future")
        return self


class NewsItem(BaseModel):
    guid_hash: str
    source_id: str
    publisher: str
    title: str = Field(max_length=300)
    link: str
    published_at: Optional[datetime] = None
    retrieved_at: datetime
    summary: str = Field(default="", max_length=600)
    quarantined: bool = False
    quarantine_reason: str = ""

    @field_validator("link")
    @classmethod
    def _https(cls, v):
        if not v.startswith("https://"):
            raise ValueError("link must be https")
        return v
