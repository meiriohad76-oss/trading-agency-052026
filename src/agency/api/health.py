from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError

from agency.api.reports import runtime_selection_reports
from agency.api.risk import runtime_risk_decisions
from agency.contracts import ContractName, load_contract_schema, validate_contract
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import build_live_readiness, list_source_health, runtime_metrics_text
from agency.runtime.data_refresh_progress import load_data_refresh_progress

router = APIRouter()
SourceHealthReader = Callable[[Any], Awaitable[list[dict[str, object]]]]
SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]
MetricsPayloadProvider = Callable[[], Awaitable[list[dict[str, object]]]]

CONTRACT_NAMES: tuple[ContractName, ...] = (
    "provenance",
    "signal-result",
    "evidence-pack",
    "selection-report",
    "data-source-health",
    "candidate-lifecycle-event",
    "risk-decision",
    "execution-preview",
    "portfolio-monitor",
    "learning-outcome",
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


@router.get("/status/live-readiness")
async def live_readiness_status() -> dict[str, object]:
    return await runtime_live_readiness()


@router.get("/status/data-refresh")
def data_refresh_progress() -> dict[str, object]:
    return load_data_refresh_progress()


@router.get("/metrics")
async def metrics() -> Response:
    return Response(
        content=await runtime_metrics(),
        media_type="text/plain; version=0.0.4",
    )


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


async def runtime_metrics(
    *,
    source_status_provider: MetricsPayloadProvider | None = None,
    selection_report_provider: MetricsPayloadProvider | None = None,
    risk_decision_provider: MetricsPayloadProvider | None = None,
) -> str:
    source_provider = (
        _default_source_status if source_status_provider is None else source_status_provider
    )
    selection_provider = (
        _default_selection_reports
        if selection_report_provider is None
        else selection_report_provider
    )
    risk_provider = (
        _default_risk_decisions
        if risk_decision_provider is None
        else risk_decision_provider
    )
    return runtime_metrics_text(
        source_health=await source_provider(),
        selection_reports=await selection_provider(),
        risk_decisions=await risk_provider(),
    )


async def runtime_live_readiness(
    *,
    source_status_provider: MetricsPayloadProvider | None = None,
    selection_report_provider: MetricsPayloadProvider | None = None,
    risk_decision_provider: MetricsPayloadProvider | None = None,
) -> dict[str, object]:
    source_provider = (
        _default_source_status if source_status_provider is None else source_status_provider
    )
    selection_provider = (
        _default_selection_reports
        if selection_report_provider is None
        else selection_report_provider
    )
    risk_provider = (
        _default_risk_decisions
        if risk_decision_provider is None
        else risk_decision_provider
    )
    return build_live_readiness(
        source_health=await source_provider(),
        selection_reports=await selection_provider(),
        risk_decisions=await risk_provider(),
    )


async def _default_source_status() -> list[dict[str, object]]:
    return await runtime_data_source_status()


async def _default_selection_reports() -> list[dict[str, object]]:
    return await runtime_selection_reports()


async def _default_risk_decisions() -> list[dict[str, object]]:
    return await runtime_risk_decisions()


def _contract_summary(contract: ContractName) -> dict[str, str]:
    schema = load_contract_schema(contract)
    return {
        "name": contract,
        "schema_id": str(schema["$id"]),
        "version": str(schema.get("x-version", "unversioned")),
        "title": str(schema["title"]),
    }
