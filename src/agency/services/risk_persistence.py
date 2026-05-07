from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.runtime import record_candidate_lifecycle_event, upsert_risk_decision
from agency.services.risk import RiskDecisionResult

RiskPayloadWriter = Callable[[AsyncSession, Mapping[str, object]], Awaitable[None]]


async def persist_risk_result(
    session: AsyncSession,
    result: RiskDecisionResult,
    *,
    decision_writer: RiskPayloadWriter = upsert_risk_decision,
    lifecycle_writer: RiskPayloadWriter = record_candidate_lifecycle_event,
) -> None:
    """Validate and persist a risk decision plus its audit event."""
    validate_contract("risk-decision", result.risk_decision)
    validate_contract("candidate-lifecycle-event", result.lifecycle_event)
    await decision_writer(session, result.risk_decision)
    await lifecycle_writer(session, result.lifecycle_event)
