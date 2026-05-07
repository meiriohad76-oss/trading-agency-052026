from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from agency.contracts import ContractValidationError
from agency.runtime.source_health import build_source_health_upsert, source_health_row_values


def test_source_health_row_values_validate_and_convert_datetime_columns() -> None:
    values = source_health_row_values(_source_health(), last_error="timeout")

    assert values["source"] == "sec-edgar"
    assert values["checked_at"] == datetime(2026, 5, 7, 9, 30, tzinfo=UTC)
    assert values["last_error"] == "timeout"
    assert values["payload"] == _source_health()


def test_source_health_upsert_targets_source_primary_key() -> None:
    statement = build_source_health_upsert(_source_health())
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (source) DO UPDATE" in compiled
    assert "reliability_score" in compiled


def test_source_health_row_values_reject_invalid_contract() -> None:
    payload = _source_health()
    payload["reliability_score"] = 1.2

    with pytest.raises(ContractValidationError):
        source_health_row_values(payload)


def _source_health() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "source": "sec-edgar",
        "source_tier": "OFFICIAL_FILING",
        "status": "HEALTHY",
        "checked_at": "2026-05-07T09:30:00Z",
        "freshness": "FRESH",
        "last_success_at": "2026-05-07T09:29:00Z",
        "observed_lag_seconds": 60,
        "error_count": 0,
        "reliability_score": 1.0,
        "rate_limit_reset_at": None,
        "notes": [],
    }
