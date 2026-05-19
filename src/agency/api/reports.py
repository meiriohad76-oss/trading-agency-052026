from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError

from agency.contracts import validate_contract
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime.artifact_fallbacks import (
    artifact_fallback_enabled,
    runtime_selection_report_artifacts,
)
from agency.runtime.operational_filters import is_non_operational_payload
from agency.runtime import list_recent_selection_reports

router = APIRouter(prefix="/reports", tags=["reports"])
SelectionReportReader = Callable[[Any, str | None, int], Awaitable[list[dict[str, object]]]]
SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]


class RuntimeSelectionReportsUnavailable(RuntimeError):
    """Raised when selection reports cannot be read from runtime storage."""


@router.get("/selection")
async def selection_reports(
    limit: int = Query(default=50, ge=1, le=1000),
) -> list[dict[str, object]]:
    try:
        return await runtime_selection_reports(limit=limit)
    except RuntimeSelectionReportsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/selection/{ticker}")
async def selection_reports_for_ticker(
    ticker: str,
    limit: int = Query(default=50, ge=1, le=1000),
) -> list[dict[str, object]]:
    try:
        return await runtime_selection_reports(ticker=ticker, limit=limit)
    except RuntimeSelectionReportsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def runtime_selection_reports(
    *,
    ticker: str | None = None,
    limit: int = 50,
    session_provider: SessionProvider = get_session,
    reader: SelectionReportReader | None = None,
    validate_payloads: bool = True,
    artifact_root: Path | None = None,
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
        )
        if fallback:
            payloads = fallback
        else:
            raise RuntimeSelectionReportsUnavailable(
                "runtime selection-report storage is unavailable"
            ) from exc
    else:
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
) -> list[dict[str, object]]:
    if not artifact_fallback_enabled():
        return []
    return [
        _with_runtime_artifact_origin(payload)
        for payload in runtime_selection_report_artifacts(
            ticker=ticker,
            limit=limit,
            artifact_root=artifact_root,
        )
    ]


def _with_runtime_artifact_origin(payload: dict[str, object]) -> dict[str, object]:
    return {
        **payload,
        "runtime_origin": "runtime_artifact_fallback",
    }


async def _read_selection_reports(
    session: Any,
    ticker: str | None,
    limit: int,
) -> list[dict[str, object]]:
    return await list_recent_selection_reports(session, ticker=ticker, limit=limit)
