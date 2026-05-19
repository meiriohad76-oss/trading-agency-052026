from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError

from agency.api.reports import RuntimeSelectionReportsUnavailable, runtime_selection_reports
from agency.api.risk import RuntimeRiskDecisionsUnavailable, runtime_risk_decisions
from agency.contracts import (
    ContractName,
    contract_names,
    load_contract_schema,
    validate_contract,
)
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import build_live_readiness, list_source_health, runtime_metrics_text
from agency.runtime.artifact_fallbacks import (
    artifact_fallback_enabled,
    runtime_source_health_artifacts,
)
from agency.runtime.data_load_status import load_data_load_status
from agency.runtime.data_refresh_progress import load_data_refresh_progress
from agency.runtime.full_live_readiness import load_full_live_readiness
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.runtime.operational_filters import is_non_operational_payload
from agency.runtime.provider_readiness import load_provider_readiness

router = APIRouter()
SourceHealthReader = Callable[[Any], Awaitable[list[dict[str, object]]]]
SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]
MetricsPayloadProvider = Callable[[], Awaitable[list[dict[str, object]]]]
SOURCE_HEALTH_TIMEOUT_SECONDS = 8.0
DATA_SOURCE_STATUSES = {"HEALTHY", "DEGRADED", "STALE", "UNAVAILABLE", "RATE_LIMITED"}
FRESHNESS_STATUSES = {"FRESH", "AGING", "STALE", "UNAVAILABLE"}

CONTRACT_NAMES: tuple[ContractName, ...] = contract_names()


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


@router.get("/status/data-load")
async def data_load_status() -> dict[str, object]:
    source_health = await runtime_data_source_status_with_timeout()
    return load_data_load_status(
        source_health_rows=source_health,
        source_health_origin=_source_health_origin_label(source_health),
    )


@router.get("/status/full-live-readiness")
async def full_live_readiness() -> dict[str, object]:
    source_health = await runtime_data_source_status_with_timeout()
    data_refresh = load_data_refresh_progress()
    data_load = load_data_load_status(
        source_health_rows=source_health,
        source_health_origin=_source_health_origin_label(source_health),
    )
    return load_full_live_readiness(data_refresh=data_refresh, data_load_status=data_load)


@router.get("/status/live-config")
def live_config_readiness() -> dict[str, object]:
    return load_live_config_readiness()


@router.get("/status/provider-readiness")
def provider_readiness() -> dict[str, object]:
    return load_provider_readiness()


@router.get("/metrics")
async def metrics() -> Response:
    return Response(
        content=await runtime_metrics(),
        media_type="text/plain; version=0.0.4",
    )


def contract_summaries() -> list[dict[str, str]]:
    return [_contract_summary(name) for name in CONTRACT_NAMES]


def unavailable_data_source_status(reason: str) -> list[dict[str, object]]:
    checked_at = datetime.now(UTC).isoformat()
    payload: dict[str, object] = {
        "schema_version": "0.1.0",
        "source": "source-health-monitor",
        "source_tier": "MARKET_DATA",
        "status": "UNAVAILABLE",
        "checked_at": checked_at,
        "freshness": "UNAVAILABLE",
        "last_success_at": None,
        "observed_lag_seconds": None,
        "error_count": 0,
        "reliability_score": 0.0,
        "rate_limit_reset_at": None,
        "notes": [reason, "no_live_source_health_rows"],
    }
    validate_contract("data-source-health", payload)
    return [payload]


def _source_health_origin_label(source_health: list[dict[str, object]]) -> str:
    if any(str(row.get("source") or "") == "source-health-monitor" for row in source_health):
        return "source-health monitor unavailable"
    if any(_has_artifact_fallback_note(row) for row in source_health):
        return "runtime artifact fallback"
    return "live runtime source-health reader"


async def runtime_data_source_status(
    *,
    session_provider: SessionProvider = get_session,
    reader: SourceHealthReader = list_source_health,
    artifact_root: Path | None = None,
) -> list[dict[str, object]]:
    try:
        async with session_provider() as session:
            payloads = await reader(session)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        payloads = _artifact_source_health(artifact_root=artifact_root)
        if not payloads:
            return unavailable_data_source_status(
                "live source-health reader failed or database is unavailable"
            )
    payloads = [
        payload
        for payload in payloads
        if not _non_operational_source_health_row(payload)
    ]
    if not payloads:
        payloads = _artifact_source_health(artifact_root=artifact_root)
    if not payloads:
        return unavailable_data_source_status("live source-health reader returned no rows")
    payloads = _with_unified_readiness_overlay(payloads)
    for payload in payloads:
        validate_contract("data-source-health", payload)
    return payloads


def _with_unified_readiness_overlay(
    payloads: list[dict[str, object]],
) -> list[dict[str, object]]:
    load_status = load_data_load_status(
        source_health_rows=payloads,
        source_health_origin=_source_health_origin_label(payloads),
    )
    readiness_by_source = {
        str(row.get("source") or ""): row
        for row in _mapping_rows(load_status.get("freshness_rows"))
        if str(row.get("source") or "")
    }
    output: list[dict[str, object]] = []
    for payload in payloads:
        source = str(payload.get("source") or "")
        readiness = readiness_by_source.get(source)
        if not readiness:
            output.append(payload)
            continue
        merged = dict(payload)
        status = str(readiness.get("status") or "").upper()
        if status in DATA_SOURCE_STATUSES:
            merged["status"] = status
        freshness = str(readiness.get("freshness") or "").upper()
        if freshness in FRESHNESS_STATUSES:
            merged["freshness"] = freshness
        checked_at = _valid_iso_datetime(readiness.get("checked_at"))
        if checked_at:
            merged["checked_at"] = checked_at
        last_success_at = _valid_iso_datetime(readiness.get("last_success_at"))
        if last_success_at:
            merged["last_success_at"] = last_success_at
        detail = str(readiness.get("detail") or "").strip()
        if detail:
            notes = [
                str(note)
                for note in (merged.get("notes") if isinstance(merged.get("notes"), list) else [])
                if str(note).strip()
            ]
            note = f"unified_readiness_override: {detail}"
            if note not in notes:
                notes.append(note)
            merged["notes"] = notes
        output.append(merged)
    return output


def _valid_iso_datetime(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"not checked", "not recorded"}:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _artifact_source_health(
    *,
    artifact_root: Path | None,
) -> list[dict[str, object]]:
    if not artifact_fallback_enabled():
        return []
    return [
        _with_artifact_fallback_note(payload)
        for payload in runtime_source_health_artifacts(artifact_root=artifact_root)
        if not _non_operational_source_health_row(payload)
    ]


def _with_artifact_fallback_note(payload: dict[str, object]) -> dict[str, object]:
    output = dict(payload)
    notes = output.get("notes", [])
    normalized_notes = [
        str(note)
        for note in (notes if isinstance(notes, list) else [])
        if str(note).strip()
    ]
    if "runtime_artifact_fallback" not in normalized_notes:
        normalized_notes.append("runtime_artifact_fallback")
    output["notes"] = normalized_notes
    return output


def _has_artifact_fallback_note(payload: Mapping[str, object]) -> bool:
    notes = payload.get("notes", [])
    if not isinstance(notes, list):
        return False
    return "runtime_artifact_fallback" in {str(note) for note in notes}


async def runtime_data_source_status_with_timeout(
    *,
    timeout_seconds: float = SOURCE_HEALTH_TIMEOUT_SECONDS,
) -> list[dict[str, object]]:
    try:
        return await asyncio.wait_for(
            runtime_data_source_status(),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        return unavailable_data_source_status(
            "live source-health reader timed out"
        )


def _non_operational_source_health_row(payload: dict[str, object]) -> bool:
    return is_non_operational_payload(payload)


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
    try:
        return await runtime_selection_reports(limit=200)
    except RuntimeSelectionReportsUnavailable:
        return []


async def _default_risk_decisions() -> list[dict[str, object]]:
    try:
        return await runtime_risk_decisions(limit=200)
    except RuntimeRiskDecisionsUnavailable:
        return []


def _contract_summary(contract: ContractName) -> dict[str, str]:
    schema = load_contract_schema(contract)
    return {
        "name": contract,
        "schema_id": str(schema["$id"]),
        "version": str(schema.get("x-version", "unversioned")),
        "title": str(schema["title"]),
    }
