from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import cast

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.persistence import candidate_lifecycle_events
from agency.runtime._coerce import parse_datetime


def make_lifecycle_event_id(
    *,
    cycle_id: str,
    ticker: str,
    event_type: str,
    event_time: str,
) -> str:
    identity = "|".join([cycle_id, ticker.upper(), event_type, event_time])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def candidate_lifecycle_row_values(payload: Mapping[str, object]) -> dict[str, object]:
    """Convert a schema-valid lifecycle event into table values."""
    validate_contract("candidate-lifecycle-event", payload)
    return {
        "event_id": str(payload["event_id"]),
        "cycle_id": str(payload["cycle_id"]),
        "ticker": str(payload["ticker"]),
        "event_type": str(payload["event_type"]),
        "event_time": parse_datetime(payload["event_time"]),
        "status": str(payload["status"]),
        "reason": payload["reason"],
        "payload": dict(payload),
    }


def build_candidate_lifecycle_insert(payload: Mapping[str, object]) -> Insert:
    """Build an idempotent append-only insert for lifecycle events."""
    values = candidate_lifecycle_row_values(payload)
    statement = insert(candidate_lifecycle_events).values(**values)
    return statement.on_conflict_do_nothing(index_elements=["event_id"])


async def record_candidate_lifecycle_event(
    session: AsyncSession,
    payload: Mapping[str, object],
) -> None:
    await session.execute(build_candidate_lifecycle_insert(payload))


async def list_candidate_lifecycle_events(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    cycle_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    result = await session.execute(
        candidate_lifecycle_select(ticker=ticker, cycle_id=cycle_id, limit=limit)
    )
    payloads: list[dict[str, object]] = []
    for payload in result.scalars().all():
        if not isinstance(payload, Mapping):
            raise TypeError("stored lifecycle event payload must be a mapping")
        payloads.append(dict(cast(Mapping[str, object], payload)))
    return payloads


def candidate_lifecycle_select(
    *,
    ticker: str | None = None,
    cycle_id: str | None = None,
    limit: int = 100,
) -> Select[tuple[object]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    statement = select(candidate_lifecycle_events.c.payload)
    if ticker is not None:
        statement = statement.where(candidate_lifecycle_events.c.ticker == ticker.upper())
    if cycle_id is not None:
        statement = statement.where(candidate_lifecycle_events.c.cycle_id == cycle_id)
    return statement.order_by(candidate_lifecycle_events.c.event_time.desc()).limit(limit)
