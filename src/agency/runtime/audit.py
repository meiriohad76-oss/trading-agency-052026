from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.persistence import (
    agent_runs,
    execution_state_history,
    portfolio_snapshots,
    prompt_audits,
    risk_snapshots,
)
from agency.runtime._coerce import optional_datetime, parse_datetime, parse_float


def agent_run_row_values(payload: Mapping[str, object]) -> dict[str, object]:
    validate_contract("agent-run", payload)
    return {
        "run_id": str(payload["run_id"]),
        "cycle_id": str(payload["cycle_id"]),
        "agent_name": str(payload["agent_name"]),
        "status": str(payload["status"]),
        "trigger": str(payload["trigger"]),
        "started_at": parse_datetime(payload["started_at"]),
        "finished_at": optional_datetime(payload["finished_at"]),
        "payload": dict(payload),
    }


def build_agent_run_upsert(payload: Mapping[str, object]) -> Insert:
    values = agent_run_row_values(payload)
    statement = insert(agent_runs).values(**values)
    updates = {column: statement.excluded[column] for column in values if column != "run_id"}
    return statement.on_conflict_do_update(index_elements=["run_id"], set_=updates)


async def upsert_agent_run(session: AsyncSession, payload: Mapping[str, object]) -> None:
    await session.execute(build_agent_run_upsert(payload))


def prompt_audit_row_values(payload: Mapping[str, object]) -> dict[str, object]:
    validate_contract("prompt-audit", payload)
    return {
        "prompt_id": str(payload["prompt_id"]),
        "run_id": _optional_string(payload["run_id"]),
        "cycle_id": str(payload["cycle_id"]),
        "agent_name": str(payload["agent_name"]),
        "model": str(payload["model"]),
        "prompt_class": str(payload["prompt_class"]),
        "prompt_hash": str(payload["prompt_hash"]),
        "created_at": parse_datetime(payload["created_at"]),
        "redaction_status": str(payload["redaction_status"]),
        "payload": dict(payload),
    }


def build_prompt_audit_insert(payload: Mapping[str, object]) -> Insert:
    values = prompt_audit_row_values(payload)
    statement = insert(prompt_audits).values(**values)
    return statement.on_conflict_do_nothing(index_elements=["prompt_id"])


async def record_prompt_audit(session: AsyncSession, payload: Mapping[str, object]) -> None:
    await session.execute(build_prompt_audit_insert(payload))


def execution_state_row_values(payload: Mapping[str, object]) -> dict[str, object]:
    validate_contract("execution-state", payload)
    return {
        "state_id": str(payload["state_id"]),
        "cycle_id": str(payload["cycle_id"]),
        "ticker": _optional_upper(payload["ticker"]),
        "execution_id": str(payload["execution_id"]),
        "state": str(payload["state"]),
        "event_time": parse_datetime(payload["event_time"]),
        "reason": _optional_string(payload["reason"]),
        "payload": dict(payload),
    }


def build_execution_state_insert(payload: Mapping[str, object]) -> Insert:
    values = execution_state_row_values(payload)
    statement = insert(execution_state_history).values(**values)
    return statement.on_conflict_do_nothing(index_elements=["state_id"])


async def record_execution_state(session: AsyncSession, payload: Mapping[str, object]) -> None:
    await session.execute(build_execution_state_insert(payload))


def risk_snapshot_row_values(payload: Mapping[str, object]) -> dict[str, object]:
    validate_contract("risk-snapshot", payload)
    return {
        "snapshot_id": str(payload["snapshot_id"]),
        "cycle_id": str(payload["cycle_id"]),
        "ticker": _optional_upper(payload["ticker"]),
        "as_of": parse_datetime(payload["as_of"]),
        "generated_at": parse_datetime(payload["generated_at"]),
        "gross_exposure_pct": parse_float(payload["gross_exposure_pct"]),
        "risk_level": str(payload["risk_level"]),
        "payload": dict(payload),
    }


def portfolio_snapshot_row_values(payload: Mapping[str, object]) -> dict[str, object]:
    validate_contract("portfolio-snapshot", payload)
    return {
        "snapshot_id": str(payload["snapshot_id"]),
        "provider": str(payload["provider"]),
        "mode": str(payload["mode"]),
        "captured_at": parse_datetime(payload["captured_at"]),
        "account_status": str(payload["account_status"]),
        "equity": parse_float(payload["equity"]),
        "cash": parse_float(payload["cash"]),
        "buying_power": parse_float(payload["buying_power"]),
        "portfolio_value": parse_float(payload["portfolio_value"]),
        "position_count": _int_value(payload["position_count"]),
        "open_order_count": _int_value(payload["open_order_count"]),
        "gross_exposure_pct": parse_float(payload["gross_exposure_pct"]),
        "payload": dict(payload),
    }


def build_risk_snapshot_insert(payload: Mapping[str, object]) -> Insert:
    values = risk_snapshot_row_values(payload)
    statement = insert(risk_snapshots).values(**values)
    return statement.on_conflict_do_nothing(index_elements=["snapshot_id"])


def build_portfolio_snapshot_insert(payload: Mapping[str, object]) -> Insert:
    values = portfolio_snapshot_row_values(payload)
    statement = insert(portfolio_snapshots).values(**values)
    return statement.on_conflict_do_nothing(index_elements=["snapshot_id"])


async def record_risk_snapshot(session: AsyncSession, payload: Mapping[str, object]) -> None:
    await session.execute(build_risk_snapshot_insert(payload))


async def record_portfolio_snapshot(session: AsyncSession, payload: Mapping[str, object]) -> None:
    await session.execute(build_portfolio_snapshot_insert(payload))


async def list_agent_runs(session: AsyncSession, *, limit: int = 50) -> list[dict[str, object]]:
    return await _payloads(session, agent_run_select(limit=limit), "agent run")


async def list_prompt_audits(session: AsyncSession, *, limit: int = 50) -> list[dict[str, object]]:
    return await _payloads(session, prompt_audit_select(limit=limit), "prompt audit")


def agent_run_select(*, limit: int = 50) -> Select[tuple[object]]:
    _validate_limit(limit)
    return select(agent_runs.c.payload).order_by(agent_runs.c.started_at.desc()).limit(limit)


def prompt_audit_select(*, limit: int = 50) -> Select[tuple[object]]:
    _validate_limit(limit)
    return select(prompt_audits.c.payload).order_by(prompt_audits.c.created_at.desc()).limit(limit)


def execution_state_select(
    *,
    ticker: str | None = None,
    cycle_id: str | None = None,
    limit: int = 100,
) -> Select[tuple[object]]:
    _validate_limit(limit)
    statement = select(execution_state_history.c.payload)
    if ticker is not None:
        statement = statement.where(execution_state_history.c.ticker == ticker.upper())
    if cycle_id is not None:
        statement = statement.where(execution_state_history.c.cycle_id == cycle_id)
    return statement.order_by(execution_state_history.c.event_time.desc()).limit(limit)


def risk_snapshot_select(
    *,
    ticker: str | None = None,
    cycle_id: str | None = None,
    limit: int = 100,
) -> Select[tuple[object]]:
    _validate_limit(limit)
    statement = select(risk_snapshots.c.payload)
    if ticker is not None:
        statement = statement.where(risk_snapshots.c.ticker == ticker.upper())
    if cycle_id is not None:
        statement = statement.where(risk_snapshots.c.cycle_id == cycle_id)
    return statement.order_by(risk_snapshots.c.generated_at.desc()).limit(limit)


def portfolio_snapshot_select(*, limit: int = 100) -> Select[tuple[object]]:
    _validate_limit(limit)
    return select(portfolio_snapshots.c.payload).order_by(
        portfolio_snapshots.c.captured_at.desc()
    ).limit(limit)


async def _payloads(
    session: AsyncSession,
    statement: Select[tuple[object]],
    label: str,
) -> list[dict[str, object]]:
    result = await session.execute(statement)
    payloads: list[dict[str, object]] = []
    for payload in result.scalars().all():
        if not isinstance(payload, Mapping):
            raise TypeError(f"stored {label} payload must be a mapping")
        payloads.append(dict(cast(Mapping[str, object], payload)))
    return payloads


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_upper(value: object) -> str | None:
    return None if value is None else str(value).upper()


def _int_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected integer value")
    return value


def _validate_limit(limit: int) -> None:
    if limit < 1:
        raise ValueError("limit must be positive")
