from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.persistence import risk_decisions
from agency.runtime._coerce import parse_datetime, parse_float


def risk_decision_row_values(payload: Mapping[str, object]) -> dict[str, object]:
    """Convert a schema-valid risk decision into table values."""
    validate_contract("risk-decision", payload)
    return {
        "cycle_id": str(payload["cycle_id"]),
        "ticker": str(payload["ticker"]),
        "as_of": parse_datetime(payload["as_of"]),
        "generated_at": parse_datetime(payload["generated_at"]),
        "decision": str(payload["decision"]),
        "final_action": str(payload.get("final_action", "UNKNOWN")),
        "final_conviction": parse_float(payload.get("final_conviction", 0.0)),
        "payload": dict(payload),
    }


def build_risk_decision_upsert(payload: Mapping[str, object]) -> Insert:
    """Build the Postgres upsert used by risk decision persistence."""
    values = risk_decision_row_values(payload)
    statement = insert(risk_decisions).values(**values)
    updates = {
        column: statement.excluded[column]
        for column in values
        if column not in {"cycle_id", "ticker", "as_of"}
    }
    return statement.on_conflict_do_update(
        index_elements=["cycle_id", "ticker", "as_of"],
        set_=updates,
    )


async def upsert_risk_decision(
    session: AsyncSession,
    payload: Mapping[str, object],
) -> None:
    await session.execute(build_risk_decision_upsert(payload))


async def list_recent_risk_decisions(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    result = await session.execute(risk_decision_select(ticker=ticker, limit=limit))
    payloads: list[dict[str, object]] = []
    for payload in result.scalars().all():
        if not isinstance(payload, Mapping):
            raise TypeError("stored risk decision payload must be a mapping")
        payloads.append(dict(cast(Mapping[str, object], payload)))
    return payloads


def risk_decision_select(
    *,
    ticker: str | None = None,
    limit: int = 50,
) -> Select[tuple[object]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    statement = select(risk_decisions.c.payload)
    if ticker is not None:
        statement = statement.where(risk_decisions.c.ticker == ticker.upper())
    return statement.order_by(risk_decisions.c.generated_at.desc()).limit(limit)
