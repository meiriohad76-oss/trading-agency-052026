from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy.exc import SQLAlchemyError

from agency.contracts import validate_contract
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import list_candidate_lifecycle_events

router = APIRouter(prefix="/candidates", tags=["candidates"])
LifecycleReader = Callable[[Any, str, str | None, int], Awaitable[list[dict[str, object]]]]
SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]


@router.get("/{ticker}/timeline")
async def candidate_timeline(
    ticker: str,
    cycle_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, object]]:
    return await runtime_candidate_timeline(ticker=ticker, cycle_id=cycle_id, limit=limit)


async def runtime_candidate_timeline(
    *,
    ticker: str,
    cycle_id: str | None = None,
    limit: int = 100,
    session_provider: SessionProvider = get_session,
    reader: LifecycleReader | None = None,
) -> list[dict[str, object]]:
    timeline_reader = _read_candidate_timeline if reader is None else reader
    try:
        async with session_provider() as session:
            payloads = await timeline_reader(session, ticker, cycle_id, limit)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        return []
    for payload in payloads:
        validate_contract("candidate-lifecycle-event", payload)
    return payloads


async def _read_candidate_timeline(
    session: Any,
    ticker: str,
    cycle_id: str | None,
    limit: int,
) -> list[dict[str, object]]:
    return await list_candidate_lifecycle_events(
        session,
        ticker=ticker,
        cycle_id=cycle_id,
        limit=limit,
    )
