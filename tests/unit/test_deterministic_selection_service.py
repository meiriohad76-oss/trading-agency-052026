from __future__ import annotations

import pytest

from agency.contracts import ContractValidationError, validate_contract
from agency.services import build_deterministic_selection
from agency.services import deterministic_selection as deterministic_selection_module

EXPECTED_CONVICTION = 0.7


def test_deterministic_selection_builds_watch_report_and_lifecycle_event() -> None:
    result = build_deterministic_selection(_evidence_pack())

    validate_contract("selection-report", result.selection_report)
    validate_contract("candidate-lifecycle-event", result.lifecycle_event)
    assert result.selection_report["final_action"] == "WATCH"
    assert result.selection_report["final_conviction"] == EXPECTED_CONVICTION
    assert result.lifecycle_event["event_type"] == "DETERMINISTIC_ACTION"
    assert result.lifecycle_event["status"] == "ACTIONABLE"


def test_deterministic_selection_blocks_when_data_quality_has_blockers() -> None:
    evidence_pack = _evidence_pack()
    data_quality = evidence_pack["data_quality"]
    assert isinstance(data_quality, dict)
    data_quality["blockers"] = ["stale official filing data"]

    result = build_deterministic_selection(evidence_pack)

    assert result.selection_report["final_action"] == "NO_TRADE"
    assert result.selection_report["final_conviction"] == 0.0
    assert result.lifecycle_event["status"] == "BLOCKED"


def test_deterministic_selection_uses_no_trade_without_actionable_signals() -> None:
    evidence_pack = _evidence_pack()
    evidence_pack["actionable_signals"] = []

    result = build_deterministic_selection(evidence_pack)

    deterministic = result.selection_report["deterministic"]
    assert isinstance(deterministic, dict)
    assert result.selection_report["final_action"] == "NO_TRADE"
    assert deterministic["reason_codes"] == ["no_actionable_signals"]


def test_deterministic_selection_rejects_invalid_evidence_pack() -> None:
    evidence_pack = _evidence_pack()
    evidence_pack["ticker"] = "not-valid"

    with pytest.raises(ContractValidationError):
        build_deterministic_selection(evidence_pack)


def test_deterministic_selection_is_repeatable_for_same_inputs() -> None:
    first = build_deterministic_selection(_evidence_pack())
    second = build_deterministic_selection(_evidence_pack())

    assert first.selection_report == second.selection_report
    assert first.lifecycle_event["event_id"] == second.lifecycle_event["event_id"]


def test_deterministic_lifecycle_event_uses_action_status_policy() -> None:
    report = {
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "generated_at": "2026-05-07T09:31:00Z",
        "final_action": "CLOSE_REVIEW",
        "final_conviction": 0.4,
        "deterministic": {"reason_codes": ["exit_review"], "blockers": []},
    }

    event = deterministic_selection_module._deterministic_lifecycle_event(report)

    assert event["status"] == "WARN"


def _evidence_pack() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "generated_at": "2026-05-07T09:31:00Z",
        "actionable_signals": [_signal_result("fundamentals"), _signal_result("insider")],
        "context_signals": [],
        "suppressed_signals": [],
        "data_quality": {
            "freshness": "FRESH",
            "source_count": 2,
            "confirmed_signal_count": 2,
            "inferred_signal_count": 0,
            "blockers": [],
        },
    }


def _signal_result(lane: str) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "lane": lane,
        "score": 0.7,
        "direction": "BULLISH",
        "actionability": "ACTIONABLE",
        "source_tier": "OFFICIAL_FILING",
        "verification_level": "CONFIRMED",
        "freshness": "FRESH",
        "confidence": 0.9,
        "provenance": _provenance(lane),
        "reason_codes": [f"{lane}_positive"],
        "suppression_reason": None,
    }


def _provenance(source_id: str) -> dict[str, object]:
    return {
        "source": "sec-edgar",
        "source_tier": "OFFICIAL_FILING",
        "source_id": source_id,
        "source_url": None,
        "timestamp_observed": "2026-05-07T09:00:00Z",
        "timestamp_as_of": "2026-05-07T08:59:00Z",
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }
