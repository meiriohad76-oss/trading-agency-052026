from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from agency.contracts import validate_contract
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import list_recent_risk_decisions
from agency.runtime.artifact_fallbacks import (
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
    limit: int = Query(default=50, ge=1, le=1000),
) -> list[dict[str, object]]:
    try:
        return await runtime_risk_decisions(limit=limit)
    except RuntimeRiskDecisionsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/decisions/{ticker}")
async def risk_decisions_for_ticker(
    ticker: str,
    limit: int = Query(default=50, ge=1, le=1000),
) -> list[dict[str, object]]:
    try:
        return await runtime_risk_decisions(ticker=ticker, limit=limit)
    except RuntimeRiskDecisionsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def runtime_risk_decisions(
    *,
    ticker: str | None = None,
    limit: int = 50,
    session_provider: SessionProvider = get_session,
    reader: RiskDecisionReader | None = None,
    validate_payloads: bool = True,
    artifact_root: Path | None = None,
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
        )
        if fallback:
            payloads = fallback
        else:
            raise RuntimeRiskDecisionsUnavailable(
                "runtime risk-decision storage is unavailable"
            ) from exc
    else:
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
) -> list[dict[str, object]]:
    if not artifact_fallback_enabled():
        return []
    return [
        _with_runtime_artifact_origin(payload)
        for payload in runtime_risk_decision_artifacts(
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


async def _read_risk_decisions(
    session: Any,
    ticker: str | None,
    limit: int,
) -> list[dict[str, object]]:
    return await list_recent_risk_decisions(session, ticker=ticker, limit=limit)
