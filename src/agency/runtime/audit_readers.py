from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from agency.runtime.audit import execution_state_select, risk_snapshot_select


async def list_execution_states(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    cycle_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    result = await session.execute(
        execution_state_select(ticker=ticker, cycle_id=cycle_id, limit=limit)
    )
    return _payloads(result.scalars().all(), "execution state")


async def list_risk_snapshots(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    cycle_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    result = await session.execute(
        risk_snapshot_select(ticker=ticker, cycle_id=cycle_id, limit=limit)
    )
    return _payloads(result.scalars().all(), "risk snapshot")


def _payloads(rows: Sequence[object], label: str) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for payload in rows:
        if not isinstance(payload, Mapping):
            raise TypeError(f"stored {label} payload must be a mapping")
        payloads.append(dict(cast(Mapping[str, object], payload)))
    return payloads
