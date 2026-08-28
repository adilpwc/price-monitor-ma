from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ProductConfig:
    name: str
    max_price: Decimal
    enabled: bool = True
    aliases: tuple[str, ...] = ()
    required_tokens: tuple[str, ...] = ()
    excluded_tokens: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Offer:
    query: str
    title: str
    site: str
    price: Decimal
    currency: str
    available: bool
    url: str
    image_url: str | None = None
    match_score: float = 0.0
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class HistoricalStats:
    current_price: Decimal
    previous_price: Decimal | None
    minimum_price: Decimal
    variation: Decimal | None
    last_change_at: datetime | None


@dataclass(frozen=True, slots=True)
class AlertDecision:
    should_notify: bool
    reason: str
    previous_alert_price: Decimal | None = None
