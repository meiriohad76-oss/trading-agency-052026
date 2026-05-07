from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.persistence import data_source_health


def source_health_row_values(
    payload: Mapping[str, object],
    last_error: str | None = None,
) -> dict[str, object]:
    """Convert a schema-valid source-health payload into table values."""
    validate_contract("data-source-health", payload)
    return {
        "source": str(payload["source"]),
        "source_tier": str(payload["source_tier"]),
        "status": str(payload["status"]),
        "checked_at": _parse_datetime(payload["checked_at"]),
        "freshness": str(payload["freshness"]),
        "last_success_at": _optional_datetime(payload["last_success_at"]),
        "observed_lag_seconds": _optional_float(payload["observed_lag_seconds"]),
        "error_count": _parse_int(payload["error_count"]),
        "reliability_score": _parse_float(payload["reliability_score"]),
        "rate_limit_reset_at": _optional_datetime(payload["rate_limit_reset_at"]),
        "notes": payload["notes"],
        "payload": dict(payload),
        "last_error": last_error,
    }


def build_source_health_upsert(
    payload: Mapping[str, object],
    last_error: str | None = None,
) -> Insert:
    """Build the Postgres upsert used by runtime source monitors."""
    values = source_health_row_values(payload, last_error)
    statement = insert(data_source_health).values(**values)
    updates = {
        column: statement.excluded[column]
        for column in values
        if column not in {"source"}
    }
    return statement.on_conflict_do_update(index_elements=["source"], set_=updates)


async def upsert_source_health(
    session: AsyncSession,
    payload: Mapping[str, object],
    *,
    last_error: str | None = None,
) -> None:
    await session.execute(build_source_health_upsert(payload, last_error))


async def list_source_health(session: AsyncSession) -> list[dict[str, object]]:
    result = await session.execute(source_health_select())
    payloads: list[dict[str, object]] = []
    for payload in result.scalars().all():
        if not isinstance(payload, Mapping):
            raise TypeError("stored source health payload must be a mapping")
        payloads.append(dict(cast(Mapping[str, object], payload)))
    return payloads


def source_health_select() -> Select[tuple[object]]:
    return select(data_source_health.c.payload).order_by(data_source_health.c.source)


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("datetime values must be strings")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return _parse_float(value)


def _parse_int(value: object) -> int:
    if isinstance(value, bool):
        raise TypeError("integer values cannot be booleans")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise TypeError("integer values must be strings or integers")


def _parse_float(value: object) -> float:
    if isinstance(value, bool):
        raise TypeError("float values cannot be booleans")
    if isinstance(value, int | float | str):
        return float(value)
    raise TypeError("float values must be strings or numbers")
