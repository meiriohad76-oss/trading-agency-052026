from __future__ import annotations

from agency.contracts import validate_contract
from agency.services import (
    build_evidence_pack,
    build_final_selection,
    build_signal_result,
)


def test_final_selection_builds_valid_report_and_audit_events() -> None:
    result = build_final_selection(_evidence_pack(score=0.7))

    validate_contract("selection-report", result.selection_report)
    for event in result.lifecycle_events:
        validate_contract("candidate-lifecycle-event", event)
    assert result.selection_report["final_action"] == "WATCH"
    assert [event["event_type"] for event in result.lifecycle_events] == [
        "DETERMINISTIC_ACTION",
        "LLM_ACTION",
        "FINAL_ACTION",
    ]


def test_final_selection_blocks_when_policy_gate_blocks() -> None:
    result = build_final_selection(_empty_evidence_pack())

    assert result.selection_report["final_action"] == "NO_TRADE"
    assert result.selection_report["final_conviction"] == 0.0
    assert result.selection_report["risk_flags"] == ["policy_gate_blocked"]
    assert result.lifecycle_events[-1]["status"] == "BLOCKED"


def test_final_selection_does_not_let_llm_promote_no_trade() -> None:
    result = build_final_selection(
        _evidence_pack(score=0.2, actionability="ACTIONABLE"),
        llm_review=_llm_review("WATCH"),
    )

    assert result.selection_report["final_action"] == "NO_TRADE"
    assert result.selection_report["risk_flags"] == ["llm_promotion_blocked"]


def test_final_selection_allows_llm_to_demote_watch_to_close_review() -> None:
    result = build_final_selection(
        _evidence_pack(score=0.7),
        llm_review=_llm_review("NO_TRADE"),
    )

    assert result.selection_report["final_action"] == "CLOSE_REVIEW"
    assert result.lifecycle_events[-1]["status"] == "WARN"


def _evidence_pack(score: float, actionability: str | None = None) -> dict[str, object]:
    return build_evidence_pack(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        generated_at="2026-05-07T09:31:00Z",
        signals=[
            build_signal_result(
                cycle_id="cycle-1",
                ticker="AAPL",
                as_of="2026-05-07T09:30:00Z",
                lane="fundamentals",
                score=score,
                provenance=_provenance("fundamentals"),
                confidence=0.9,
                actionability=actionability,
            ),
            build_signal_result(
                cycle_id="cycle-1",
                ticker="AAPL",
                as_of="2026-05-07T09:30:00Z",
                lane="insider",
                score=score,
                provenance=_provenance("insider"),
                confidence=0.9,
                actionability=actionability,
            )
        ],
    )


def _empty_evidence_pack() -> dict[str, object]:
    return build_evidence_pack(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        generated_at="2026-05-07T09:31:00Z",
        signals=[],
    )


def _llm_review(action: str) -> dict[str, object]:
    return {
        "action": action,
        "confidence": 0.6,
        "rationale": "Stubbed reviewer fixture.",
        "supporting_factors": ["factor"],
        "concerns": ["concern"],
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
