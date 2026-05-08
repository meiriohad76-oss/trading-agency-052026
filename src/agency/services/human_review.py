from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.runtime import record_candidate_lifecycle_event
from agency.services.selection_events import build_lifecycle_event

HumanReviewWriter = Callable[[AsyncSession, Mapping[str, object]], Awaitable[None]]

DECISION_STATUS = {
    "APPROVE": "PASSED",
    "DEFER": "WARN",
    "REJECT": "BLOCKED",
}

DECISION_REASONS = {
    "APPROVE": "paper review approved",
    "DEFER": "paper review deferred",
    "REJECT": "paper review rejected",
}


def build_human_review_event(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
    decision: str,
    reviewed_by: str = "local-user",
    event_time: str | None = None,
) -> dict[str, object]:
    normalized_decision = decision.upper()
    if normalized_decision not in DECISION_STATUS:
        raise ValueError("decision must be APPROVE, DEFER, or REJECT")
    event = build_lifecycle_event(
        cycle_id=cycle_id,
        ticker=ticker.upper(),
        event_type="HUMAN_REVIEW",
        event_time=event_time or _now_utc(),
        status=DECISION_STATUS[normalized_decision],
        reason=DECISION_REASONS[normalized_decision],
        payload={
            "review_decision": normalized_decision,
            "reviewed_by": reviewed_by,
            "paper_only": True,
            "as_of": as_of,
        },
    )
    validate_contract("candidate-lifecycle-event", event)
    return event


async def persist_human_review_event(
    session: AsyncSession,
    event: Mapping[str, object],
    *,
    lifecycle_writer: HumanReviewWriter = record_candidate_lifecycle_event,
) -> None:
    validate_contract("candidate-lifecycle-event", event)
    await lifecycle_writer(session, event)


async def build_and_persist_human_review_event(
    session: AsyncSession,
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
    decision: str,
    reviewed_by: str = "local-user",
    event_time: str | None = None,
    lifecycle_writer: HumanReviewWriter = record_candidate_lifecycle_event,
) -> dict[str, object]:
    event = build_human_review_event(
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
        decision=decision,
        reviewed_by=reviewed_by,
        event_time=event_time,
    )
    await persist_human_review_event(
        session,
        event,
        lifecycle_writer=lifecycle_writer,
    )
    return event


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
