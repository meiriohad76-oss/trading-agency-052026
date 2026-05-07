from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from agency.contracts import validate_contract
from agency.runtime import make_lifecycle_event_id


class LlmReviewProvider(Protocol):
    async def review(
        self,
        evidence_pack: Mapping[str, object],
        deterministic_decision: Mapping[str, object],
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True)
class LlmReviewResult:
    """Context-only LLM review artifact and audit event."""

    review: dict[str, object]
    lifecycle_event: dict[str, object]


def build_context_only_llm_review() -> dict[str, object]:
    """Return the no-live-LLM review shape used until providers are enabled."""
    return {
        "action": "NO_REVIEW",
        "confidence": 0.0,
        "rationale": "LLM review is not enabled for this run.",
        "supporting_factors": [],
        "concerns": [],
    }


def build_llm_review_stub(
    evidence_pack: Mapping[str, object],
    deterministic_decision: Mapping[str, object],
    *,
    generated_at: str | None = None,
) -> LlmReviewResult:
    """Build a contract-compatible, context-only LLM review and lifecycle event."""
    validate_contract("evidence-pack", evidence_pack)
    pack = dict(evidence_pack)
    event_time = generated_at or str(pack["generated_at"])
    review = build_context_only_llm_review()
    lifecycle_event = _lifecycle_event(
        pack,
        deterministic_decision,
        review,
        event_time=event_time,
    )
    validate_contract("candidate-lifecycle-event", lifecycle_event)
    return LlmReviewResult(review=review, lifecycle_event=lifecycle_event)


def _lifecycle_event(
    evidence_pack: Mapping[str, object],
    deterministic_decision: Mapping[str, object],
    review: Mapping[str, object],
    *,
    event_time: str,
) -> dict[str, object]:
    cycle_id = str(evidence_pack["cycle_id"])
    ticker = str(evidence_pack["ticker"])
    event_type = "LLM_ACTION"
    return {
        "schema_version": "0.1.0",
        "event_id": make_lifecycle_event_id(
            cycle_id=cycle_id,
            ticker=ticker,
            event_type=event_type,
            event_time=event_time,
        ),
        "cycle_id": cycle_id,
        "ticker": ticker,
        "event_type": event_type,
        "event_time": event_time,
        "status": "CONTEXT_ONLY",
        "reason": "llm review disabled",
        "payload": {
            "llm_review": dict(review),
            "deterministic_action": deterministic_decision.get("action", "UNKNOWN"),
        },
    }
