from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.persistence import selection_reports
from agency.runtime._coerce import parse_datetime, parse_float


def selection_report_row_values(payload: Mapping[str, object]) -> dict[str, object]:
    """Convert a schema-valid selection report into table values."""
    validate_contract("selection-report", payload)
    return {
        "cycle_id": str(payload["cycle_id"]),
        "ticker": str(payload["ticker"]),
        "as_of": parse_datetime(payload["as_of"]),
        "generated_at": parse_datetime(payload["generated_at"]),
        "final_action": str(payload["final_action"]),
        "final_conviction": parse_float(payload["final_conviction"]),
        "payload": dict(payload),
    }


def build_selection_report_upsert(payload: Mapping[str, object]) -> Insert:
    """Build the Postgres upsert used by final selection persistence."""
    values = selection_report_row_values(payload)
    statement = insert(selection_reports).values(**values)
    updates = {
        column: statement.excluded[column]
        for column in values
        if column not in {"cycle_id", "ticker", "as_of"}
    }
    return statement.on_conflict_do_update(
        index_elements=["cycle_id", "ticker", "as_of"],
        set_=updates,
    )


async def upsert_selection_report(
    session: AsyncSession,
    payload: Mapping[str, object],
) -> None:
    await session.execute(build_selection_report_upsert(payload))


async def list_recent_selection_reports(
    session: AsyncSession,
    *,
    limit: int = 50,
) -> list[dict[str, object]]:
    result = await session.execute(selection_report_select(limit=limit))
    payloads: list[dict[str, object]] = []
    for payload in result.scalars().all():
        if not isinstance(payload, Mapping):
            raise TypeError("stored selection report payload must be a mapping")
        payloads.append(dict(cast(Mapping[str, object], payload)))
    return payloads


def selection_report_select(*, limit: int = 50) -> Select[tuple[object]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    return (
        select(selection_reports.c.payload)
        .order_by(selection_reports.c.generated_at.desc())
        .limit(limit)
    )
