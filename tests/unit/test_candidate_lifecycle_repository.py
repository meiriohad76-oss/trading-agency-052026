from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from agency.contracts import ContractValidationError
from agency.runtime.candidate_lifecycle import (
    build_candidate_lifecycle_insert,
    candidate_lifecycle_row_values,
    candidate_lifecycle_select,
    make_lifecycle_event_id,
)

EVENT_ID_LENGTH = 64


def test_make_lifecycle_event_id_is_deterministic_and_uses_upper_ticker() -> None:
    first = make_lifecycle_event_id(
        cycle_id="cycle-1",
        ticker="aapl",
        event_type="FINAL_ACTION",
        event_time="2026-05-07T09:31:00Z",
    )
    second = make_lifecycle_event_id(
        cycle_id="cycle-1",
        ticker="AAPL",
        event_type="FINAL_ACTION",
        event_time="2026-05-07T09:31:00Z",
    )

    assert first == second
    assert len(first) == EVENT_ID_LENGTH


def test_candidate_lifecycle_row_values_validate_and_convert_event_time() -> None:
    values = candidate_lifecycle_row_values(_lifecycle_event())

    assert values["event_id"] == _event_id()
    assert values["ticker"] == "AAPL"
    assert values["event_time"] == datetime(2026, 5, 7, 9, 31, tzinfo=UTC)
    assert values["payload"] == _lifecycle_event()


def test_candidate_lifecycle_insert_is_idempotent_by_event_id() -> None:
    statement = build_candidate_lifecycle_insert(_lifecycle_event())
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (event_id) DO NOTHING" in compiled


def test_candidate_lifecycle_select_filters_and_orders() -> None:
    statement = candidate_lifecycle_select(ticker="aapl", cycle_id="cycle-1", limit=5)
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "candidate_lifecycle_events.ticker" in compiled
    assert "candidate_lifecycle_events.cycle_id" in compiled
    assert "ORDER BY candidate_lifecycle_events.event_time DESC" in compiled


def test_candidate_lifecycle_row_values_reject_invalid_contract() -> None:
    payload = _lifecycle_event()
    payload["status"] = "UNKNOWN"

    with pytest.raises(ContractValidationError):
        candidate_lifecycle_row_values(payload)


def _lifecycle_event() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "event_id": _event_id(),
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "event_type": "FINAL_ACTION",
        "event_time": "2026-05-07T09:31:00Z",
        "status": "RECORDED",
        "reason": "selection report persisted",
        "payload": {"final_action": "WATCH"},
    }


def _event_id() -> str:
    return make_lifecycle_event_id(
        cycle_id="cycle-1",
        ticker="AAPL",
        event_type="FINAL_ACTION",
        event_time="2026-05-07T09:31:00Z",
    )
