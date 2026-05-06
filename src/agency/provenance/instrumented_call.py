from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from agency.provenance.freshness import FreshnessDomain, compute_freshness
from agency.provenance.types import Provenance, Provenanced, SourceTier, VerificationLevel


async def instrumented_call[T](
    call: Callable[[], Awaitable[T]],
    *,
    source: str,
    source_tier: SourceTier,
    source_id: str,
    verification_level: VerificationLevel,
    freshness_domain: FreshnessDomain | str,
    confidence: float,
    clock: Callable[[], datetime] | None = None,
    timestamp_as_of: datetime | None = None,
    source_url: str | None = None,
) -> Provenanced[T]:
    get_now = _utc_now if clock is None else clock
    value = await call()
    timestamp_observed = _ensure_utc(get_now())
    effective_as_of = (
        timestamp_observed
        if timestamp_as_of is None
        else _ensure_utc(timestamp_as_of)
    )
    provenance = Provenance(
        source=source,
        source_tier=source_tier,
        source_id=source_id,
        source_url=source_url,
        timestamp_observed=timestamp_observed,
        timestamp_as_of=effective_as_of,
        freshness=compute_freshness(
            effective_as_of,
            freshness_domain,
            now=timestamp_observed,
        ),
        confidence=confidence,
        verification_level=verification_level,
    )
    return Provenanced[T](value=value, provenance=provenance)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "datetime values must include timezone information"
        raise ValueError(msg)
    return value.astimezone(UTC)
