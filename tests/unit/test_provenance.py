from __future__ import annotations

import json
import pickle
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError

from agency.provenance.freshness import FreshnessDomain, compute_freshness
from agency.provenance.instrumented_call import instrumented_call
from agency.provenance.types import (
    FreshnessStatus,
    Provenance,
    Provenanced,
    SourceTier,
    VerificationLevel,
)

NOW = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
HISTORICAL_CALL_VALUE = 10


class Payload(BaseModel):
    ticker: str
    score: int


def make_provenance(
    *,
    source_tier: SourceTier = SourceTier.MARKET_DATA,
    verification_level: VerificationLevel = VerificationLevel.CONFIRMED,
    freshness: FreshnessStatus = FreshnessStatus.FRESH,
    timestamp_observed: datetime = NOW,
    timestamp_as_of: datetime = NOW,
) -> Provenance:
    return Provenance(
        source="unit-test",
        source_tier=source_tier,
        source_id="fixture-1",
        source_url=None,
        timestamp_observed=timestamp_observed,
        timestamp_as_of=timestamp_as_of,
        freshness=freshness,
        confidence=0.9,
        verification_level=verification_level,
    )


def test_enum_values_round_trip_through_json() -> None:
    enum_types = [SourceTier, VerificationLevel, FreshnessStatus]
    for enum_type in enum_types:
        for member in enum_type:
            payload = json.loads(json.dumps({"value": member.value}))
            assert enum_type(payload["value"]) is member


@pytest.mark.parametrize(
    ("domain", "age", "expected"),
    [
        (FreshnessDomain.PRICING, timedelta(seconds=1), FreshnessStatus.FRESH),
        (FreshnessDomain.PRICING, timedelta(days=1), FreshnessStatus.STALE),
        (FreshnessDomain.PRICING, timedelta(days=30), FreshnessStatus.STALE),
        (FreshnessDomain.NEWS, timedelta(seconds=1), FreshnessStatus.FRESH),
        (FreshnessDomain.NEWS, timedelta(days=1), FreshnessStatus.STALE),
        (FreshnessDomain.NEWS, timedelta(days=30), FreshnessStatus.STALE),
        (FreshnessDomain.SEC_FUNDAMENTALS, timedelta(seconds=1), FreshnessStatus.FRESH),
        (FreshnessDomain.SEC_FUNDAMENTALS, timedelta(days=1), FreshnessStatus.FRESH),
        (FreshnessDomain.SEC_FUNDAMENTALS, timedelta(days=30), FreshnessStatus.FRESH),
        (FreshnessDomain.SEC_FORM4, timedelta(seconds=1), FreshnessStatus.FRESH),
        (FreshnessDomain.SEC_FORM4, timedelta(days=1), FreshnessStatus.FRESH),
        (FreshnessDomain.SEC_FORM4, timedelta(days=30), FreshnessStatus.STALE),
        (FreshnessDomain.SEC_13F, timedelta(seconds=1), FreshnessStatus.FRESH),
        (FreshnessDomain.SEC_13F, timedelta(days=1), FreshnessStatus.FRESH),
        (FreshnessDomain.SEC_13F, timedelta(days=30), FreshnessStatus.FRESH),
        (FreshnessDomain.BROKER, timedelta(seconds=1), FreshnessStatus.FRESH),
        (FreshnessDomain.BROKER, timedelta(days=1), FreshnessStatus.STALE),
        (FreshnessDomain.BROKER, timedelta(days=30), FreshnessStatus.STALE),
        (FreshnessDomain.LEARNING, timedelta(seconds=1), FreshnessStatus.FRESH),
        (FreshnessDomain.LEARNING, timedelta(days=1), FreshnessStatus.FRESH),
        (FreshnessDomain.LEARNING, timedelta(days=30), FreshnessStatus.STALE),
    ],
)
def test_compute_freshness_boundary_cases(
    domain: FreshnessDomain,
    age: timedelta,
    expected: FreshnessStatus,
) -> None:
    assert compute_freshness(NOW - age, domain, now=NOW) is expected


def test_compute_freshness_reports_unavailable_and_rejects_naive_datetimes() -> None:
    assert compute_freshness(None, FreshnessDomain.PRICING, now=NOW) is FreshnessStatus.UNAVAILABLE

    with pytest.raises(ValueError, match="timezone"):
        compute_freshness(datetime(2026, 5, 6, 12, 0), FreshnessDomain.PRICING, now=NOW)


async def test_instrumented_call_records_timestamp_after_call_returns() -> None:
    call_completed = False

    async def fake_call() -> dict[str, str]:
        nonlocal call_completed
        call_completed = True
        return {"ok": "yes"}

    def clock() -> datetime:
        assert call_completed
        return NOW

    wrapped = await instrumented_call(
        fake_call,
        source="yfinance",
        source_tier=SourceTier.MARKET_DATA,
        source_id="AAPL-2026-05-06",
        verification_level=VerificationLevel.CONFIRMED,
        freshness_domain=FreshnessDomain.PRICING,
        confidence=0.8,
        clock=clock,
    )

    assert wrapped.value == {"ok": "yes"}
    assert wrapped.provenance.timestamp_observed == NOW
    assert wrapped.provenance.timestamp_as_of == NOW


async def test_instrumented_call_accepts_historical_timestamp_as_of() -> None:
    filed_at = datetime(2022, 6, 30, tzinfo=UTC)

    async def fake_call() -> int:
        return HISTORICAL_CALL_VALUE

    wrapped = await instrumented_call(
        fake_call,
        source="SEC",
        source_tier=SourceTier.OFFICIAL_FILING,
        source_id="0000320193-22-000070",
        verification_level=VerificationLevel.CONFIRMED,
        freshness_domain=FreshnessDomain.SEC_FUNDAMENTALS,
        timestamp_as_of=filed_at,
        confidence=1.0,
        clock=lambda: NOW,
    )

    assert wrapped.value == HISTORICAL_CALL_VALUE
    assert wrapped.provenance.timestamp_observed == NOW
    assert wrapped.provenance.timestamp_as_of == filed_at
    assert wrapped.provenance.freshness is FreshnessStatus.STALE


def test_provenanced_round_trips_json_for_int_value() -> None:
    wrapped = Provenanced[int](value=7, provenance=make_provenance())

    dumped = wrapped.model_dump()
    encoded = json.dumps(dumped)
    restored = Provenanced[int].model_validate(json.loads(encoded))

    assert restored == wrapped


def test_provenanced_round_trips_json_for_dict_value() -> None:
    wrapped = Provenanced[dict[str, int]](value={"score": 7}, provenance=make_provenance())

    dumped = wrapped.model_dump()
    encoded = json.dumps(dumped)
    restored = Provenanced[dict[str, int]].model_validate(json.loads(encoded))

    assert restored == wrapped


def test_provenanced_round_trips_json_for_pydantic_value() -> None:
    wrapped = Provenanced[Payload](
        value=Payload(ticker="AAPL", score=7),
        provenance=make_provenance(),
    )

    restored = Provenanced[Payload].model_validate(json.loads(json.dumps(wrapped.model_dump())))

    assert restored == wrapped
    assert restored.value.ticker == "AAPL"


def test_provenanced_is_pickle_safe() -> None:
    wrapped = Provenanced[int](value=7, provenance=make_provenance())

    restored = pickle.loads(pickle.dumps(wrapped))

    assert restored == wrapped


@pytest.mark.parametrize(
    ("source_tier", "verification_level"),
    [
        (SourceTier.OFFICIAL_FILING, VerificationLevel.INFERRED),
        (SourceTier.CONFIRMED_TRADE_PRINT, VerificationLevel.INFERRED),
        (SourceTier.MARKET_DATA, VerificationLevel.INFERRED),
        (SourceTier.INFERRED_FROM_BARS, VerificationLevel.CONFIRMED),
        (SourceTier.SOCIAL_CROWD, VerificationLevel.CONFIRMED),
    ],
)
def test_rejects_invalid_source_tier_verification_pairs(
    source_tier: SourceTier,
    verification_level: VerificationLevel,
) -> None:
    with pytest.raises(ValidationError):
        make_provenance(source_tier=source_tier, verification_level=verification_level)


@pytest.mark.parametrize(
    ("source_tier", "verification_level"),
    [
        (SourceTier.PROVIDER_NEWS, VerificationLevel.CONFIRMED),
        (SourceTier.PROVIDER_NEWS, VerificationLevel.INFERRED),
        (SourceTier.PAID_SUB_EMAIL, VerificationLevel.CONFIRMED),
        (SourceTier.RSS_HEADLINE, VerificationLevel.INFERRED),
    ],
)
def test_accepts_flexible_news_and_email_source_pairs(
    source_tier: SourceTier,
    verification_level: VerificationLevel,
) -> None:
    provenance = make_provenance(source_tier=source_tier, verification_level=verification_level)

    assert provenance.source_tier is source_tier
    assert provenance.verification_level is verification_level


def test_json_schema_validates_serialized_provenanced_dict() -> None:
    schema = json.loads(Path("schemas/provenance.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    wrapped = Provenanced[dict[str, int]](value={"score": 7}, provenance=make_provenance())

    validator.validate(wrapped.model_dump())
