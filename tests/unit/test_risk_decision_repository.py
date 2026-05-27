from __future__ import annotations

from datetime import UTC, datetime

import pytest
from service_fixtures import selection_report
from sqlalchemy.dialects import postgresql

from agency.contracts import ContractValidationError
from agency.runtime.risk_decisions import (
    build_risk_decision_upsert,
    risk_decision_row_values,
    risk_decision_select,
)
from agency.services import build_risk_decision


def test_risk_decision_row_values_validate_and_convert_keys() -> None:
    values = risk_decision_row_values(_risk_decision())

    assert values["cycle_id"] == "cycle-1"
    assert values["ticker"] == "AAPL"
    assert values["as_of"] == datetime(2026, 5, 7, 9, 30, tzinfo=UTC)
    assert values["final_action"] == "BUY"
    assert values["final_conviction"] == 0.7
    assert values["payload"] == _risk_decision()


def test_risk_decision_upsert_targets_decision_identity() -> None:
    statement = build_risk_decision_upsert(_risk_decision())
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (cycle_id, ticker, as_of) DO UPDATE" in compiled
    assert "decision" in compiled
    assert "final_action" in compiled
    assert "final_conviction" in compiled


def test_risk_decision_select_filters_by_uppercase_ticker() -> None:
    statement = risk_decision_select(ticker="aapl", limit=5)
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "risk_decisions.ticker" in compiled
    assert "ORDER BY risk_decisions.generated_at DESC" in compiled


def test_risk_decision_row_values_reject_invalid_contract() -> None:
    payload = _risk_decision()
    payload["decision"] = "MAYBE"

    with pytest.raises(ContractValidationError):
        risk_decision_row_values(payload)


def _risk_decision() -> dict[str, object]:
    return build_risk_decision(
        selection_report(action="BUY"),
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision
