from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy.exc import SQLAlchemyError

from agency.contracts import ContractName, validate_contract
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import (
    list_agent_runs,
    list_execution_states,
    list_prompt_audits,
    list_risk_snapshots,
)

router = APIRouter(prefix="/audit", tags=["audit"])
SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]
SimpleAuditReader = Callable[[Any, int], Awaitable[list[dict[str, object]]]]
FilteredAuditReader = Callable[
    [Any, str | None, str | None, int],
    Awaitable[list[dict[str, object]]],
]


@router.get("/agent-runs")
async def agent_runs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, object]]:
    return await runtime_agent_runs(limit=limit)


@router.get("/prompts")
async def prompt_audits(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, object]]:
    return await runtime_prompt_audits(limit=limit)


@router.get("/risk-snapshots")
async def risk_snapshots(
    ticker: str | None = None,
    cycle_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, object]]:
    return await runtime_risk_snapshots(ticker=ticker, cycle_id=cycle_id, limit=limit)


@router.get("/execution-states")
async def execution_states(
    ticker: str | None = None,
    cycle_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, object]]:
    return await runtime_execution_states(ticker=ticker, cycle_id=cycle_id, limit=limit)


async def runtime_agent_runs(
    *,
    limit: int = 50,
    session_provider: SessionProvider = get_session,
    reader: SimpleAuditReader | None = None,
) -> list[dict[str, object]]:
    return await _runtime_simple(
        limit=limit,
        contract="agent-run",
        default_reader=_read_agent_runs,
        session_provider=session_provider,
        reader=reader,
    )


async def runtime_prompt_audits(
    *,
    limit: int = 50,
    session_provider: SessionProvider = get_session,
    reader: SimpleAuditReader | None = None,
) -> list[dict[str, object]]:
    return await _runtime_simple(
        limit=limit,
        contract="prompt-audit",
        default_reader=_read_prompt_audits,
        session_provider=session_provider,
        reader=reader,
    )


async def runtime_risk_snapshots(
    *,
    ticker: str | None = None,
    cycle_id: str | None = None,
    limit: int = 100,
    session_provider: SessionProvider = get_session,
    reader: FilteredAuditReader | None = None,
) -> list[dict[str, object]]:
    return await _runtime_filtered(
        ticker=ticker,
        cycle_id=cycle_id,
        limit=limit,
        contract="risk-snapshot",
        default_reader=_read_risk_snapshots,
        session_provider=session_provider,
        reader=reader,
    )


async def runtime_execution_states(
    *,
    ticker: str | None = None,
    cycle_id: str | None = None,
    limit: int = 100,
    session_provider: SessionProvider = get_session,
    reader: FilteredAuditReader | None = None,
) -> list[dict[str, object]]:
    return await _runtime_filtered(
        ticker=ticker,
        cycle_id=cycle_id,
        limit=limit,
        contract="execution-state",
        default_reader=_read_execution_states,
        session_provider=session_provider,
        reader=reader,
    )


async def _runtime_simple(
    *,
    limit: int,
    contract: ContractName,
    default_reader: SimpleAuditReader,
    session_provider: SessionProvider,
    reader: SimpleAuditReader | None,
) -> list[dict[str, object]]:
    audit_reader = default_reader if reader is None else reader
    try:
        async with session_provider() as session:
            payloads = await audit_reader(session, limit)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        return []
    return _validated(payloads, contract)


async def _runtime_filtered(
    *,
    ticker: str | None,
    cycle_id: str | None,
    limit: int,
    contract: ContractName,
    default_reader: FilteredAuditReader,
    session_provider: SessionProvider,
    reader: FilteredAuditReader | None,
) -> list[dict[str, object]]:
    audit_reader = default_reader if reader is None else reader
    try:
        async with session_provider() as session:
            payloads = await audit_reader(session, ticker, cycle_id, limit)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        return []
    return _validated(payloads, contract)


def _validated(
    payloads: list[dict[str, object]],
    contract: ContractName,
) -> list[dict[str, object]]:
    for payload in payloads:
        validate_contract(contract, payload)
    return payloads


async def _read_agent_runs(session: Any, limit: int) -> list[dict[str, object]]:
    return await list_agent_runs(session, limit=limit)


async def _read_prompt_audits(session: Any, limit: int) -> list[dict[str, object]]:
    return await list_prompt_audits(session, limit=limit)


async def _read_risk_snapshots(
    session: Any,
    ticker: str | None,
    cycle_id: str | None,
    limit: int,
) -> list[dict[str, object]]:
    return await list_risk_snapshots(session, ticker=ticker, cycle_id=cycle_id, limit=limit)


async def _read_execution_states(
    session: Any,
    ticker: str | None,
    cycle_id: str | None,
    limit: int,
) -> list[dict[str, object]]:
    return await list_execution_states(session, ticker=ticker, cycle_id=cycle_id, limit=limit)
