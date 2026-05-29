from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from agency.contracts import validate_contract
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import list_recent_risk_decisions
from agency.runtime.artifact_fallbacks import (
    DEFAULT_RUNTIME_ARTIFACT_ROOT,
    artifact_fallback_enabled,
    runtime_risk_decision_artifacts,
)
from agency.runtime.operational_filters import is_non_operational_payload
from agency.services.risk import (
    PortfolioPolicy,
    load_active_portfolio_policy,
    load_policy_from_db,
    save_policy_to_db,
)

router = APIRouter(prefix="/risk", tags=["risk"])
policy_router = APIRouter(prefix="/api", tags=["policy"])
RiskDecisionReader = Callable[[Any, str | None, int], Awaitable[list[dict[str, object]]]]
SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]
UNKNOWN_PAYLOAD_TIMESTAMP = datetime.min.replace(tzinfo=UTC)


class RuntimeRiskDecisionsUnavailable(RuntimeError):
    """Raised when risk decisions cannot be read from runtime storage."""


class PolicyUpdate(BaseModel):
    min_final_conviction: float | None = None
    max_new_positions_per_cycle: int | None = None
    max_gross_exposure_pct: float | None = None
    default_position_pct: float | None = None
    take_profit_pct: float | None = None
    stop_loss_pct: float | None = None
    trailing_stop_pct: float | None = None
    hourly_loss_alert_pct: float | None = None


@policy_router.get("/policy")
async def get_policy(
    session_provider: SessionProvider = get_session,
) -> dict[str, object]:
    """Return the active policy (DB override if present, else env defaults)."""
    policy = await load_active_portfolio_policy(session_provider=session_provider)
    return policy.as_dict()


@policy_router.post("/policy")
async def update_policy(
    body: PolicyUpdate,
    session_provider: SessionProvider = get_session,
) -> dict[str, object]:
    """Persist editable policy fields to DB; broker submit remains env-controlled."""
    try:
        async with session_provider() as session:
            current = await load_policy_from_db(session)
            if current is None:
                current = PortfolioPolicy.from_env()
            runtime_controls = PortfolioPolicy.from_env()
            updated = _updated_policy(
                current,
                body,
                broker_submit_enabled=runtime_controls.broker_submit_enabled,
                allow_short_trades=runtime_controls.allow_short_trades,
            )
            await save_policy_to_db(session, updated)
            await session.commit()
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail="policy persistence unavailable") from exc
    return updated.as_dict()


def _updated_policy(
    current: PortfolioPolicy,
    body: PolicyUpdate,
    *,
    broker_submit_enabled: bool,
    allow_short_trades: bool,
) -> PortfolioPolicy:
    return replace(
        current,
        min_final_conviction=_bounded_float(
            body.min_final_conviction,
            current.min_final_conviction,
            field="min_final_conviction",
            minimum=0.0,
            maximum=1.0,
        ),
        max_new_positions_per_cycle=_bounded_int(
            body.max_new_positions_per_cycle,
            current.max_new_positions_per_cycle,
            field="max_new_positions_per_cycle",
            minimum=0,
            maximum=100,
        ),
        max_gross_exposure_pct=_bounded_float(
            body.max_gross_exposure_pct,
            current.max_gross_exposure_pct,
            field="max_gross_exposure_pct",
            minimum=0.0,
            maximum=300.0,
        ),
        default_position_pct=_bounded_float(
            body.default_position_pct,
            current.default_position_pct,
            field="default_position_pct",
            minimum=0.0,
            maximum=100.0,
        ),
        take_profit_pct=_bounded_float(
            body.take_profit_pct,
            current.take_profit_pct,
            field="take_profit_pct",
            minimum=0.0,
            maximum=300.0,
        ),
        stop_loss_pct=_bounded_float(
            body.stop_loss_pct,
            current.stop_loss_pct,
            field="stop_loss_pct",
            minimum=0.0,
            maximum=100.0,
        ),
        trailing_stop_pct=_bounded_float(
            body.trailing_stop_pct,
            current.trailing_stop_pct,
            field="trailing_stop_pct",
            minimum=0.0,
            maximum=100.0,
        ),
        hourly_loss_alert_pct=_bounded_float(
            body.hourly_loss_alert_pct,
            current.hourly_loss_alert_pct,
            field="hourly_loss_alert_pct",
            minimum=0.0,
            maximum=100.0,
        ),
        broker_submit_enabled=broker_submit_enabled,
        allow_short_trades=allow_short_trades,
    )


def _bounded_float(
    value: float | None,
    current: float,
    *,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    if value is None:
        return current
    if value < minimum or value > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be between {minimum:g} and {maximum:g}",
        )
    return float(value)


def _bounded_int(
    value: int | None,
    current: int,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        return current
    if value < minimum or value > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be between {minimum} and {maximum}",
        )
    return int(value)


@router.get("/decisions")
async def risk_decisions(
    limit: int = Query(default=20, ge=1, le=1000),
) -> list[dict[str, object]]:
    try:
        return await runtime_risk_decisions(
            limit=limit,
            prefer_latest_artifact=False,
        )
    except RuntimeRiskDecisionsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/decisions/{ticker}")
async def risk_decisions_for_ticker(
    ticker: str,
    limit: int = Query(default=20, ge=1, le=1000),
) -> list[dict[str, object]]:
    try:
        return await runtime_risk_decisions(
            ticker=ticker,
            limit=limit,
            prefer_latest_artifact=False,
        )
    except RuntimeRiskDecisionsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def runtime_risk_decisions(
    *,
    ticker: str | None = None,
    limit: int = 20,
    session_provider: SessionProvider = get_session,
    reader: RiskDecisionReader | None = None,
    validate_payloads: bool = True,
    artifact_root: Path | None = None,
    prefer_latest_artifact: bool = False,
) -> list[dict[str, object]]:
    decision_reader = _read_risk_decisions if reader is None else reader
    try:
        async with session_provider() as session:
            payloads = await decision_reader(session, ticker, limit)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        fallback = _artifact_risk_decisions(
            ticker=ticker,
            limit=limit,
            artifact_root=artifact_root,
            force=prefer_latest_artifact,
        )
        if fallback:
            payloads = fallback
        else:
            raise RuntimeRiskDecisionsUnavailable(
                "runtime risk-decision storage is unavailable"
            ) from exc
    else:
        if prefer_latest_artifact:
            payloads = _prefer_newer_artifact_payloads(
                payloads,
                _artifact_risk_decisions(
                    ticker=ticker,
                    limit=limit,
                    artifact_root=artifact_root,
                    force=True,
                    runtime_origin="runtime_artifact_selected",
                ),
            )
        if not payloads:
            payloads = _artifact_risk_decisions(
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
            validate_contract("risk-decision", payload)
    return payloads


def _artifact_risk_decisions(
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
    artifact_path = (artifact_root or DEFAULT_RUNTIME_ARTIFACT_ROOT) / "risk-decisions.json"
    return [
        _with_runtime_artifact_origin(
            payload,
            runtime_origin=runtime_origin,
            runtime_artifact_path=artifact_path,
            runtime_storage_superseded=runtime_storage_superseded,
        )
        for payload in runtime_risk_decision_artifacts(
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


async def _read_risk_decisions(
    session: Any,
    ticker: str | None,
    limit: int,
) -> list[dict[str, object]]:
    return await list_recent_risk_decisions(session, ticker=ticker, limit=limit)
