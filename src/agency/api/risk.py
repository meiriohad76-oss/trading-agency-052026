from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy.exc import SQLAlchemyError

from agency.contracts import validate_contract
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import list_recent_risk_decisions

router = APIRouter(prefix="/risk", tags=["risk"])
RiskDecisionReader = Callable[[Any, str | None, int], Awaitable[list[dict[str, object]]]]
SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]


@router.get("/decisions")
async def risk_decisions(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, object]]:
    return await runtime_risk_decisions(limit=limit)


@router.get("/decisions/{ticker}")
async def risk_decisions_for_ticker(
    ticker: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, object]]:
    return await runtime_risk_decisions(ticker=ticker, limit=limit)


async def runtime_risk_decisions(
    *,
    ticker: str | None = None,
    limit: int = 50,
    session_provider: SessionProvider = get_session,
    reader: RiskDecisionReader | None = None,
) -> list[dict[str, object]]:
    decision_reader = _read_risk_decisions if reader is None else reader
    try:
        async with session_provider() as session:
            payloads = await decision_reader(session, ticker, limit)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        return []
    for payload in payloads:
        validate_contract("risk-decision", payload)
    return payloads


async def _read_risk_decisions(
    session: Any,
    ticker: str | None,
    limit: int,
) -> list[dict[str, object]]:
    return await list_recent_risk_decisions(session, ticker=ticker, limit=limit)
