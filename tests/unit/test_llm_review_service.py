from __future__ import annotations

import pytest

from agency.contracts import ContractValidationError, validate_contract
from agency.services import (
    build_context_only_llm_review,
    build_deterministic_selection,
    build_evidence_pack,
    build_llm_review_stub,
    build_signal_result,
)


def test_llm_review_stub_returns_context_only_review_and_lifecycle_event() -> None:
    selection = build_deterministic_selection(_evidence_pack())

    result = build_llm_review_stub(
        _evidence_pack(),
        selection.selection_report["deterministic"],
    )

    validate_contract("candidate-lifecycle-event", result.lifecycle_event)
    assert result.review == build_context_only_llm_review()
    assert result.lifecycle_event["event_type"] == "LLM_ACTION"
    assert result.lifecycle_event["status"] == "CONTEXT_ONLY"


def test_context_only_review_is_selection_report_compatible() -> None:
    selection = build_deterministic_selection(_evidence_pack())

    assert selection.selection_report["llm_review"] == build_context_only_llm_review()
    validate_contract("selection-report", selection.selection_report)


def test_llm_review_stub_rejects_invalid_evidence_pack() -> None:
    evidence_pack = _evidence_pack()
    evidence_pack["ticker"] = "bad ticker"

    with pytest.raises(ContractValidationError):
        build_llm_review_stub(evidence_pack, {"action": "WATCH"})


def _evidence_pack() -> dict[str, object]:
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
                score=0.7,
                provenance=_provenance(),
                confidence=0.9,
            )
        ],
    )


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
