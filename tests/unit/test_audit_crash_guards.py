from __future__ import annotations

from agency.views import _shared as shared_view
from agency.views import command as command_view


def test_is_actionable_candidate_tolerates_missing_fields() -> None:
    assert shared_view._is_actionable_candidate({}) is False


def test_source_is_degraded_tolerates_missing_fields() -> None:
    assert shared_view._source_is_degraded({}) is False


def test_human_review_summary_tolerates_partial_event() -> None:
    summary = shared_view._human_review_summary({"payload": {"review_decision": "APPROVE"}})
    assert summary["decision"] == "Approve"
    assert summary["reason"] == ""
    assert summary["event_time"] == ""


def test_list_and_mapping_helpers_return_empty_for_missing_keys() -> None:
    assert shared_view._list_field({}, "missing") == []
    assert shared_view._mapping_field({}, "missing") == {}


def test_command_summary_tolerates_partial_candidate_and_source_rows() -> None:
    summary = command_view.command_summary(
        candidates=[{}],
        data_sources=[{}],
        contracts=[],
        readiness=None,
        review_queue=[],
    )
    assert summary["candidate_count"] == 1
    assert summary["actionable_candidate_count"] == 0
    assert summary["blocked_candidate_count"] == 0
    assert summary["degraded_source_count"] == 0


def test_source_status_rows_tolerates_partial_provider_rows() -> None:
    rows = command_view.source_status_rows([{}])
    assert rows[0]["source"] == ""
    assert rows[0]["raw_status"] == "unknown"
    assert rows[0]["raw_freshness"] == "unknown"
