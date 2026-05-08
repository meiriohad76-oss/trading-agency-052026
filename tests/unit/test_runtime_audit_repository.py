from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from agency.contracts import ContractValidationError
from agency.runtime.audit import (
    agent_run_row_values,
    build_agent_run_upsert,
    build_execution_state_insert,
    build_prompt_audit_insert,
    build_risk_snapshot_insert,
    execution_state_row_values,
    execution_state_select,
    prompt_audit_row_values,
    risk_snapshot_row_values,
    risk_snapshot_select,
)

GROSS_EXPOSURE_PCT = 40.0


def test_agent_run_row_values_validate_and_convert_datetimes() -> None:
    values = agent_run_row_values(_agent_run())

    assert values["run_id"] == "run-1"
    assert values["started_at"] == datetime(2026, 5, 8, 9, 30, tzinfo=UTC)
    assert values["finished_at"] == datetime(2026, 5, 8, 9, 31, tzinfo=UTC)
    assert values["payload"] == _agent_run()


def test_agent_run_upsert_targets_run_identity() -> None:
    statement = build_agent_run_upsert(_agent_run())
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (run_id) DO UPDATE" in compiled
    assert "status" in compiled


def test_prompt_audit_insert_is_idempotent_by_prompt_id() -> None:
    values = prompt_audit_row_values(_prompt_audit())
    statement = build_prompt_audit_insert(_prompt_audit())
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert values["prompt_hash"] == "a" * 64
    assert "ON CONFLICT (prompt_id) DO NOTHING" in compiled


def test_execution_state_insert_and_select_are_append_only() -> None:
    values = execution_state_row_values(_execution_state())
    statement = build_execution_state_insert(_execution_state())
    select_statement = execution_state_select(ticker="aapl", cycle_id="cycle-1", limit=5)
    compiled_insert = str(statement.compile(dialect=postgresql.dialect()))
    compiled_select = str(select_statement.compile(dialect=postgresql.dialect()))

    assert values["ticker"] == "AAPL"
    assert "ON CONFLICT (state_id) DO NOTHING" in compiled_insert
    assert "execution_state_history.ticker" in compiled_select
    assert "ORDER BY execution_state_history.event_time DESC" in compiled_select


def test_risk_snapshot_insert_and_select_are_append_only() -> None:
    values = risk_snapshot_row_values(_risk_snapshot())
    statement = build_risk_snapshot_insert(_risk_snapshot())
    select_statement = risk_snapshot_select(ticker="aapl", cycle_id="cycle-1", limit=5)
    compiled_insert = str(statement.compile(dialect=postgresql.dialect()))
    compiled_select = str(select_statement.compile(dialect=postgresql.dialect()))

    assert values["ticker"] == "AAPL"
    assert values["gross_exposure_pct"] == GROSS_EXPOSURE_PCT
    assert "ON CONFLICT (snapshot_id) DO NOTHING" in compiled_insert
    assert "risk_snapshots.cycle_id" in compiled_select
    assert "ORDER BY risk_snapshots.generated_at DESC" in compiled_select


def test_runtime_audit_row_values_reject_invalid_contract() -> None:
    payload = _agent_run()
    payload["status"] = "BROKEN"

    with pytest.raises(ContractValidationError):
        agent_run_row_values(payload)


def _agent_run() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "run_id": "run-1",
        "cycle_id": "cycle-1",
        "agent_name": "runtime-cycle",
        "status": "SUCCEEDED",
        "trigger": "MANUAL",
        "started_at": "2026-05-08T09:30:00Z",
        "finished_at": "2026-05-08T09:31:00Z",
        "payload": {"candidate_count": 1},
    }


def _prompt_audit() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "prompt_id": "prompt-1",
        "run_id": "run-1",
        "cycle_id": "cycle-1",
        "agent_name": "llm-review",
        "model": "gpt-test",
        "prompt_class": "candidate-review",
        "prompt_hash": "a" * 64,
        "created_at": "2026-05-08T09:31:00Z",
        "redaction_status": "NO_SECRETS",
        "payload": {"template": "candidate-review-v1"},
    }


def _execution_state(ticker: str | None = "AAPL") -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "state_id": "state-1",
        "cycle_id": "cycle-1",
        "ticker": ticker,
        "execution_id": "exec-1",
        "state": "READY",
        "event_time": "2026-05-08T09:33:00Z",
        "reason": "paper preview ready",
        "payload": {"submit_enabled": False},
    }


def _risk_snapshot(ticker: str | None = "AAPL") -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "snapshot_id": "snap-1",
        "cycle_id": "cycle-1",
        "ticker": ticker,
        "as_of": "2026-05-08T09:30:00Z",
        "generated_at": "2026-05-08T09:32:00Z",
        "gross_exposure_pct": GROSS_EXPOSURE_PCT,
        "risk_level": "LOW",
        "payload": {"degraded_source_count": 0},
    }
