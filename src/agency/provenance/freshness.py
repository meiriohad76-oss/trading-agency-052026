from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from agency.provenance.types import FreshnessStatus


class FreshnessDomain(StrEnum):
    PRICING = "pricing"
    TRADE_PRINTS = "trade_prints"
    NEWS = "news"
    SEC_FUNDAMENTALS = "sec_fundamentals"
    SEC_FORM4 = "sec_form4"
    SEC_13F = "sec_13f"
    BROKER = "broker"
    LEARNING = "learning"


FRESH_WINDOWS: dict[FreshnessDomain, timedelta] = {
    FreshnessDomain.PRICING: timedelta(minutes=5),
    FreshnessDomain.TRADE_PRINTS: timedelta(minutes=20),
    FreshnessDomain.NEWS: timedelta(hours=4),
    FreshnessDomain.SEC_FUNDAMENTALS: timedelta(days=120),
    FreshnessDomain.SEC_FORM4: timedelta(days=14),
    FreshnessDomain.SEC_13F: timedelta(days=120),
    FreshnessDomain.BROKER: timedelta(seconds=30),
    FreshnessDomain.LEARNING: timedelta(days=7),
}

STALE_MULTIPLIER = 2


def compute_freshness(
    timestamp_as_of: datetime | None,
    domain: FreshnessDomain | str,
    *,
    now: datetime,
    windows: dict[FreshnessDomain, timedelta] | None = None,
) -> FreshnessStatus:
    if timestamp_as_of is None:
        return FreshnessStatus.UNAVAILABLE

    observed_at = _ensure_utc(timestamp_as_of)
    measured_at = _ensure_utc(now)
    age = measured_at - observed_at
    if age < timedelta(0):
        msg = "timestamp_as_of cannot be in the future"
        raise ValueError(msg)

    freshness_domain = FreshnessDomain(domain)
    active_windows = FRESH_WINDOWS if windows is None else windows
    fresh_window = active_windows[freshness_domain]

    if age <= fresh_window:
        return FreshnessStatus.FRESH
    if age <= fresh_window * STALE_MULTIPLIER:
        return FreshnessStatus.AGING
    return FreshnessStatus.STALE


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "datetime values must include timezone information"
        raise ValueError(msg)
    return value.astimezone(UTC)
