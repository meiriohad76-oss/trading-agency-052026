from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy.exc import SQLAlchemyError

from agency.contracts import validate_contract
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import list_recent_selection_reports

router = APIRouter(prefix="/reports", tags=["reports"])
SelectionReportReader = Callable[[Any, str | None, int], Awaitable[list[dict[str, object]]]]
SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]


@router.get("/selection")
async def selection_reports(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, object]]:
    return await runtime_selection_reports(limit=limit)


@router.get("/selection/{ticker}")
async def selection_reports_for_ticker(
    ticker: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, object]]:
    return await runtime_selection_reports(ticker=ticker, limit=limit)


async def runtime_selection_reports(
    *,
    ticker: str | None = None,
    limit: int = 50,
    session_provider: SessionProvider = get_session,
    reader: SelectionReportReader | None = None,
) -> list[dict[str, object]]:
    report_reader = _read_selection_reports if reader is None else reader
    try:
        async with session_provider() as session:
            payloads = await report_reader(session, ticker, limit)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        return []
    for payload in payloads:
        validate_contract("selection-report", payload)
    return payloads


async def _read_selection_reports(
    session: Any,
    ticker: str | None,
    limit: int,
) -> list[dict[str, object]]:
    return await list_recent_selection_reports(session, ticker=ticker, limit=limit)
