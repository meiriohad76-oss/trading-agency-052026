from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql

from agency.contracts import ContractValidationError
from agency.runtime.selection_reports import (
    build_selection_report_upsert,
    selection_report_row_values,
)


def test_selection_report_row_values_validate_and_convert_keys() -> None:
    values = selection_report_row_values(_selection_report())

    assert values["cycle_id"] == "cycle-1"
    assert values["ticker"] == "AAPL"
    assert values["as_of"] == datetime(2026, 5, 7, 9, 30, tzinfo=UTC)
    assert values["payload"] == _selection_report()


def test_selection_report_upsert_targets_report_identity() -> None:
    statement = build_selection_report_upsert(_selection_report())
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (cycle_id, ticker, as_of) DO UPDATE" in compiled
    assert "final_conviction" in compiled


def test_selection_report_row_values_reject_invalid_contract() -> None:
    payload = _selection_report()
    payload["final_conviction"] = 1.2

    with pytest.raises(ContractValidationError):
        selection_report_row_values(payload)


def _selection_report() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "generated_at": "2026-05-07T09:31:00Z",
        "final_action": "WATCH",
        "final_conviction": 0.62,
        "deterministic": _engine_decision(),
        "llm_review": _llm_review(),
        "policy_gates": [{"name": "evidence_breadth", "status": "WARN", "reason": "one source"}],
        "risk_flags": [],
        "evidence_pack": _evidence_pack(),
        "trade_plan": {
            "entry": None,
            "stop_loss": None,
            "take_profit": None,
            "position_size": 0,
            "time_in_force": None,
        },
    }


def _evidence_pack() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "generated_at": "2026-05-07T09:31:00Z",
        "actionable_signals": [_signal_result()],
        "context_signals": [],
        "suppressed_signals": [],
        "data_quality": {
            "freshness": "FRESH",
            "source_count": 1,
            "confirmed_signal_count": 1,
            "inferred_signal_count": 0,
            "blockers": [],
        },
    }


def _signal_result() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "lane": "fundamentals",
        "score": 0.7,
        "direction": "BULLISH",
        "actionability": "ACTIONABLE",
        "source_tier": "OFFICIAL_FILING",
        "verification_level": "CONFIRMED",
        "freshness": "FRESH",
        "confidence": 0.9,
        "provenance": _provenance(),
        "reason_codes": ["quality_positive"],
        "suppression_reason": None,
    }


def _engine_decision() -> dict[str, object]:
    return {
        "action": "WATCH",
        "score": 0.4,
        "conviction": 0.62,
        "reason_codes": ["quality_positive"],
        "blockers": [],
    }


def _llm_review() -> dict[str, object]:
    return {
        "action": "WATCH",
        "confidence": 0.55,
        "rationale": "Constructive but incomplete.",
        "supporting_factors": ["fundamentals_positive"],
        "concerns": ["news_breadth_low"],
    }


def _provenance() -> dict[str, object]:
    return {
        "source": "sec-edgar",
        "source_tier": "OFFICIAL_FILING",
        "source_id": "CIK0000320193",
        "source_url": None,
        "timestamp_observed": "2026-05-07T09:00:00Z",
        "timestamp_as_of": "2026-05-07T08:59:00Z",
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }
