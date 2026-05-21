from __future__ import annotations

import hashlib
import json
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
SELECTION_REPORT_HASH_VERSION = "0.1.0"
OPERATOR_MANUAL_ADVANCE_TYPE = "PAPER_PROMOTION_OVERRIDE"


def selection_report_hash(report: Mapping[str, object]) -> str:
    """Return a stable hash for the exact selection report a human reviewed."""
    validate_contract("selection-report", report)
    encoded = json.dumps(
        dict(report),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_human_review_event(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
    decision: str,
    reviewed_by: str = "local-user",
    review_reason: str | None = None,
    notes: str | None = None,
    event_time: str | None = None,
    selection_report_hash: str | None = None,
    caution_acknowledged: bool = False,
) -> dict[str, object]:
    normalized_decision = decision.upper()
    if normalized_decision not in DECISION_STATUS:
        raise ValueError("decision must be APPROVE, DEFER, or REJECT")
    payload: dict[str, object] = {
        "review_decision": normalized_decision,
        "reviewed_by": reviewed_by,
        "review_reason": _clean_optional(review_reason),
        "notes": _clean_optional(notes),
        "paper_only": True,
        "as_of": as_of,
    }
    cleaned_hash = _clean_optional(selection_report_hash)
    if cleaned_hash is not None:
        payload["selection_report_hash"] = cleaned_hash
        payload["selection_report_hash_version"] = SELECTION_REPORT_HASH_VERSION
    if caution_acknowledged:
        payload["caution_acknowledged"] = True
    event = build_lifecycle_event(
        cycle_id=cycle_id,
        ticker=ticker.upper(),
        event_type="HUMAN_REVIEW",
        event_time=event_time or _now_utc(),
        status=DECISION_STATUS[normalized_decision],
        reason=DECISION_REASONS[normalized_decision],
        payload=payload,
    )
    validate_contract("candidate-lifecycle-event", event)
    return event


def build_operator_manual_advance_event(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
    selection_report_hash: str,
    override_reason: str,
    blocked_reason: str | None = None,
    reviewed_by: str = "local-user",
    notes: str | None = None,
    event_time: str | None = None,
    acknowledged: bool = False,
) -> dict[str, object]:
    cleaned_reason = _clean_optional(override_reason)
    if cleaned_reason is None:
        raise ValueError("operator manual advance requires an override reason")
    if not acknowledged:
        raise ValueError("operator manual advance requires explicit acknowledgement")
    cleaned_hash = _clean_optional(selection_report_hash)
    if cleaned_hash is None:
        raise ValueError("operator manual advance requires selection_report_hash")
    payload: dict[str, object] = {
        "advance_type": OPERATOR_MANUAL_ADVANCE_TYPE,
        "scope": "paper_trade_promotion",
        "reviewed_by": reviewed_by,
        "override_reason": cleaned_reason,
        "blocked_reason": _clean_optional(blocked_reason),
        "notes": _clean_optional(notes),
        "paper_only": True,
        "acknowledged": True,
        "as_of": as_of,
        "selection_report_hash": cleaned_hash,
        "selection_report_hash_version": SELECTION_REPORT_HASH_VERSION,
    }
    event = build_lifecycle_event(
        cycle_id=cycle_id,
        ticker=ticker.upper(),
        event_type="OPERATOR_MANUAL_ADVANCE",
        event_time=event_time or _now_utc(),
        status="PASSED",
        reason="operator manual paper-promotion advance approved",
        payload=payload,
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
    review_reason: str | None = None,
    notes: str | None = None,
    event_time: str | None = None,
    selection_report_hash: str | None = None,
    caution_acknowledged: bool = False,
    lifecycle_writer: HumanReviewWriter = record_candidate_lifecycle_event,
) -> dict[str, object]:
    event = build_human_review_event(
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
        decision=decision,
        reviewed_by=reviewed_by,
        review_reason=review_reason,
        notes=notes,
        event_time=event_time,
        selection_report_hash=selection_report_hash,
        caution_acknowledged=caution_acknowledged,
    )
    await persist_human_review_event(
        session,
        event,
        lifecycle_writer=lifecycle_writer,
    )
    return event


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None
