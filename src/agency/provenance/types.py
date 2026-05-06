from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from pydantic.functional_validators import model_validator


class SourceTier(StrEnum):
    OFFICIAL_FILING = "OFFICIAL_FILING"
    CONFIRMED_TRADE_PRINT = "CONFIRMED_TRADE_PRINT"
    MARKET_DATA = "MARKET_DATA"
    PROVIDER_NEWS = "PROVIDER_NEWS"
    PAID_SUB_EMAIL = "PAID_SUB_EMAIL"
    RSS_HEADLINE = "RSS_HEADLINE"
    INFERRED_FROM_BARS = "INFERRED_FROM_BARS"
    SOCIAL_CROWD = "SOCIAL_CROWD"


class VerificationLevel(StrEnum):
    CONFIRMED = "CONFIRMED"
    INFERRED = "INFERRED"


class FreshnessStatus(StrEnum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


_MUST_BE_CONFIRMED = {
    SourceTier.OFFICIAL_FILING,
    SourceTier.CONFIRMED_TRADE_PRINT,
    SourceTier.MARKET_DATA,
}

_MUST_BE_INFERRED = {
    SourceTier.INFERRED_FROM_BARS,
    SourceTier.SOCIAL_CROWD,
}


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "datetime values must include timezone information"
        raise ValueError(msg)
    return value.astimezone(UTC)


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str = Field(min_length=1)
    source_tier: SourceTier
    source_id: str = Field(min_length=1)
    source_url: str | None = Field(default=None, min_length=1)
    timestamp_observed: datetime
    timestamp_as_of: datetime
    freshness: FreshnessStatus
    confidence: float = Field(ge=0.0, le=1.0)
    verification_level: VerificationLevel

    @field_validator("timestamp_observed", "timestamp_as_of")
    @classmethod
    def validate_datetime_is_utc(cls, value: datetime) -> datetime:
        return _ensure_utc(value)

    @field_serializer("timestamp_observed", "timestamp_as_of")
    def serialize_datetime(self, value: datetime) -> str:
        return value.isoformat()

    @model_validator(mode="after")
    def validate_source_verification_compatibility(self) -> Provenance:
        if self.source_tier in _MUST_BE_CONFIRMED:
            _expect_verification(
                self.source_tier,
                self.verification_level,
                VerificationLevel.CONFIRMED,
            )
        if self.source_tier in _MUST_BE_INFERRED:
            _expect_verification(
                self.source_tier,
                self.verification_level,
                VerificationLevel.INFERRED,
            )
        if self.timestamp_as_of > self.timestamp_observed:
            msg = "timestamp_as_of cannot be later than timestamp_observed"
            raise ValueError(msg)
        return self


def _expect_verification(
    source_tier: SourceTier,
    actual: VerificationLevel,
    expected: VerificationLevel,
) -> None:
    if actual != expected:
        msg = f"{source_tier.value} must use verification_level={expected.value}"
        raise ValueError(msg)


class Provenanced[T](BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    value: T
    provenance: Provenance

    def __reduce__(self) -> tuple[object, tuple[dict[str, Any]]]:
        return (_restore_provenanced, (self.model_dump(),))

    def __repr__(self) -> str:
        summary = (
            f"{self.provenance.source}"
            f"/{self.provenance.source_tier.value}"
            f"/{self.provenance.verification_level.value}"
        )
        return f"Provenanced(value={self.value!r}, provenance={summary})"


ProvenancedDict = Provenanced[dict[str, Any]]


def _restore_provenanced(data: dict[str, Any]) -> Provenanced[Any]:
    return Provenanced.model_validate(data)
