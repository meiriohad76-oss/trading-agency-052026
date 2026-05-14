from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from agency.contracts import validate_contract
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import list_recent_risk_decisions
from agency.services.risk import PortfolioPolicy, load_policy_from_db, save_policy_to_db

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
    try:
        async with session_provider() as session:
            db_policy = await load_policy_from_db(session)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        db_policy = None
    policy = db_policy if db_policy is not None else PortfolioPolicy.from_env()
    return policy.as_dict()


@policy_router.post("/policy")
async def update_policy(
    body: PolicyUpdate,
    session_provider: SessionProvider = get_session,
) -> dict[str, object]:
    """Persist editable policy fields to DB; broker_submit_enabled is not editable here."""
    try:
        async with session_provider() as session:
            current = await load_policy_from_db(session)
            if current is None:
                current = PortfolioPolicy.from_env()
            updated = PortfolioPolicy(
                min_final_conviction=(
                    body.min_final_conviction
                    if body.min_final_conviction is not None
                    else current.min_final_conviction
                ),
                max_new_positions_per_cycle=(
                    body.max_new_positions_per_cycle
                    if body.max_new_positions_per_cycle is not None
                    else current.max_new_positions_per_cycle
                ),
                max_gross_exposure_pct=(
                    body.max_gross_exposure_pct
                    if body.max_gross_exposure_pct is not None
                    else current.max_gross_exposure_pct
                ),
                default_position_pct=(
                    body.default_position_pct
                    if body.default_position_pct is not None
                    else current.default_position_pct
                ),
                take_profit_pct=(
                    body.take_profit_pct
                    if body.take_profit_pct is not None
                    else current.take_profit_pct
                ),
                stop_loss_pct=(
                    body.stop_loss_pct
                    if body.stop_loss_pct is not None
                    else current.stop_loss_pct
                ),
                trailing_stop_pct=(
                    body.trailing_stop_pct
                    if body.trailing_stop_pct is not None
                    else current.trailing_stop_pct
                ),
                hourly_loss_alert_pct=(
                    body.hourly_loss_alert_pct
                    if body.hourly_loss_alert_pct is not None
                    else current.hourly_loss_alert_pct
                ),
                # broker_submit_enabled is preserved from current — not UI-editable
                broker_submit_enabled=current.broker_submit_enabled,
            )
            await save_policy_to_db(session, updated)
            await session.commit()
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        raise HTTPException(status_code=503, detail="policy persistence unavailable") from exc
    return updated.as_dict()


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
) -> list[dict[str, object]]:
    decision_reader = _read_risk_decisions if reader is None else reader
    try:
        async with session_provider() as session:
            payloads = await decision_reader(session, ticker, limit)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        raise RuntimeRiskDecisionsUnavailable(
            "runtime risk-decision storage is unavailable"
        ) from exc
    if validate_payloads:
        for payload in payloads:
            validate_contract("risk-decision", payload)
    return payloads


async def _read_risk_decisions(
    session: Any,
    ticker: str | None,
    limit: int,
) -> list[dict[str, object]]:
    return await list_recent_risk_decisions(session, ticker=ticker, limit=limit)
