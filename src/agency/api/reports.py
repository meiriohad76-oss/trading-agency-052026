from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from agency.contracts import validate_contract
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import list_recent_selection_reports
from agency.runtime.artifact_fallbacks import (
    DEFAULT_RUNTIME_ARTIFACT_ROOT,
    artifact_fallback_enabled,
    runtime_selection_report_artifacts,
)
from agency.runtime.operational_filters import is_non_operational_payload

router = APIRouter(prefix="/reports", tags=["reports"])
SelectionReportReader = Callable[[Any, str | None, int], Awaitable[list[dict[str, object]]]]
SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]
UNKNOWN_PAYLOAD_TIMESTAMP = datetime.min.replace(tzinfo=UTC)


class RuntimeSelectionReportsUnavailable(RuntimeError):
    """Raised when selection reports cannot be read from runtime storage."""


@router.get("/selection")
async def selection_reports(
    limit: int = Query(default=20, ge=1, le=1000),
) -> list[dict[str, object]]:
    try:
        return await runtime_selection_reports(
            limit=limit,
            prefer_latest_artifact=False,
        )
    except RuntimeSelectionReportsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/selection/{ticker}")
async def selection_reports_for_ticker(
    ticker: str,
    limit: int = Query(default=20, ge=1, le=1000),
) -> list[dict[str, object]]:
    try:
        return await runtime_selection_reports(
            ticker=ticker,
            limit=limit,
            prefer_latest_artifact=False,
        )
    except RuntimeSelectionReportsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def runtime_selection_reports(
    *,
    ticker: str | None = None,
    limit: int = 20,
    session_provider: SessionProvider = get_session,
    reader: SelectionReportReader | None = None,
    validate_payloads: bool = True,
    artifact_root: Path | None = None,
    prefer_latest_artifact: bool = False,
) -> list[dict[str, object]]:
    report_reader = _read_selection_reports if reader is None else reader
    try:
        async with session_provider() as session:
            payloads = await report_reader(session, ticker, limit)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        fallback = _artifact_selection_reports(
            ticker=ticker,
            limit=limit,
            artifact_root=artifact_root,
            force=prefer_latest_artifact,
        )
        if fallback:
            payloads = fallback
        else:
            raise RuntimeSelectionReportsUnavailable(
                "runtime selection-report storage is unavailable"
            ) from exc
    else:
        if prefer_latest_artifact:
            payloads = _prefer_newer_artifact_payloads(
                payloads,
                _artifact_selection_reports(
                    ticker=ticker,
                    limit=limit,
                    artifact_root=artifact_root,
                    force=True,
                    runtime_origin="runtime_artifact_selected",
                ),
            )
        if not payloads:
            payloads = _artifact_selection_reports(
                ticker=ticker,
                limit=limit,
                artifact_root=artifact_root,
            )
    payloads = [
        payload
        for payload in payloads
        if not is_non_operational_payload(payload)
    ]
    if validate_payloads:
        for payload in payloads:
            validate_contract("selection-report", payload)
    return payloads


def _artifact_selection_reports(
    *,
    ticker: str | None,
    limit: int,
    artifact_root: Path | None,
    force: bool = False,
    runtime_origin: str | None = "runtime_artifact_fallback",
    runtime_storage_superseded: bool = False,
) -> list[dict[str, object]]:
    if not force and not artifact_fallback_enabled():
        return []
    artifact_path = (artifact_root or DEFAULT_RUNTIME_ARTIFACT_ROOT) / "selection-reports.json"
    return [
        _with_runtime_artifact_origin(
            payload,
            runtime_origin=runtime_origin,
            runtime_artifact_path=artifact_path,
            runtime_storage_superseded=runtime_storage_superseded,
        )
        for payload in runtime_selection_report_artifacts(
            ticker=ticker,
            limit=limit,
            artifact_root=artifact_root,
        )
    ]


def _prefer_newer_artifact_payloads(
    storage_payloads: list[dict[str, object]],
    artifact_payloads: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not artifact_payloads:
        return storage_payloads
    if not storage_payloads:
        return artifact_payloads
    artifact_timestamp = _latest_payload_timestamp(artifact_payloads)
    storage_timestamp = _latest_payload_timestamp(storage_payloads)
    if UNKNOWN_PAYLOAD_TIMESTAMP in {artifact_timestamp, storage_timestamp}:
        return storage_payloads
    if artifact_timestamp > storage_timestamp:
        return [
            {**payload, "runtime_storage_superseded": True}
            for payload in artifact_payloads
        ]
    return storage_payloads


def _latest_payload_timestamp(payloads: list[dict[str, object]]) -> datetime:
    return max(
        (_payload_timestamp(payload) for payload in payloads),
        default=UNKNOWN_PAYLOAD_TIMESTAMP,
    )


def _payload_timestamp(payload: dict[str, object]) -> datetime:
    for key in ("generated_at", "checked_at", "as_of"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return UNKNOWN_PAYLOAD_TIMESTAMP


def _with_runtime_artifact_origin(
    payload: dict[str, object],
    *,
    runtime_origin: str | None,
    runtime_artifact_path: Path,
    runtime_storage_superseded: bool,
) -> dict[str, object]:
    if runtime_origin is None:
        return dict(payload)
    return {
        **payload,
        "runtime_origin": runtime_origin,
        "runtime_artifact_path": str(runtime_artifact_path),
        "runtime_artifact_timestamp": _payload_timestamp_label(payload),
        "runtime_storage_superseded": runtime_storage_superseded,
    }


def _payload_timestamp_label(payload: Mapping[str, object]) -> str:
    for key in ("generated_at", "checked_at", "as_of"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


async def _read_selection_reports(
    session: Any,
    ticker: str | None,
    limit: int,
) -> list[dict[str, object]]:
    return await list_recent_selection_reports(session, ticker=ticker, limit=limit)
