from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from agency.contracts import ContractName, load_contract_schema, validate_contract
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import list_source_health

router = APIRouter()
SourceHealthReader = Callable[[Any], Awaitable[list[dict[str, object]]]]
SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]

CONTRACT_NAMES: tuple[ContractName, ...] = (
    "provenance",
    "signal-result",
    "evidence-pack",
    "selection-report",
    "data-source-health",
    "candidate-lifecycle-event",
)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "trading-agency-v2"}


@router.get("/contracts")
def contracts() -> list[dict[str, str]]:
    return contract_summaries()


@router.get("/contracts/{contract_name}")
def contract_schema(contract_name: str) -> dict[str, Any]:
    if contract_name not in CONTRACT_NAMES:
        raise HTTPException(status_code=404, detail="unknown contract")
    return load_contract_schema(contract_name)


@router.get("/status/data-sources")
async def data_source_status() -> list[dict[str, object]]:
    return await runtime_data_source_status()


def contract_summaries() -> list[dict[str, str]]:
    return [_contract_summary(name) for name in CONTRACT_NAMES]


def bootstrap_data_source_status() -> list[dict[str, object]]:
    payload: dict[str, object] = {
        "schema_version": "0.1.0",
        "source": "bootstrap",
        "source_tier": "MARKET_DATA",
        "status": "DEGRADED",
        "checked_at": "2026-05-07T00:00:00Z",
        "freshness": "UNAVAILABLE",
        "last_success_at": None,
        "observed_lag_seconds": None,
        "error_count": 0,
        "reliability_score": 0.0,
        "rate_limit_reset_at": None,
        "notes": ["runtime source monitors are not wired yet"],
    }
    validate_contract("data-source-health", payload)
    return [payload]


async def runtime_data_source_status(
    *,
    session_provider: SessionProvider = get_session,
    reader: SourceHealthReader = list_source_health,
) -> list[dict[str, object]]:
    try:
        async with session_provider() as session:
            payloads = await reader(session)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        return bootstrap_data_source_status()
    if not payloads:
        return bootstrap_data_source_status()
    for payload in payloads:
        validate_contract("data-source-health", payload)
    return payloads


def _contract_summary(contract: ContractName) -> dict[str, str]:
    schema = load_contract_schema(contract)
    return {
        "name": contract,
        "schema_id": str(schema["$id"]),
        "version": str(schema.get("x-version", "unversioned")),
        "title": str(schema["title"]),
    }
