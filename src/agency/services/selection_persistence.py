from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.runtime import record_candidate_lifecycle_event, upsert_selection_report
from agency.services.deterministic_selection import (
    DeterministicSelectionResult,
    build_deterministic_selection,
)


class SelectionPayloadWriter(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        payload: Mapping[str, object],
    ) -> None: ...


async def persist_selection_result(
    session: AsyncSession,
    result: DeterministicSelectionResult,
    *,
    report_writer: SelectionPayloadWriter = upsert_selection_report,
    lifecycle_writer: SelectionPayloadWriter = record_candidate_lifecycle_event,
) -> None:
    """Persist a selection report and its matching lifecycle event."""
    validate_contract("selection-report", result.selection_report)
    validate_contract("candidate-lifecycle-event", result.lifecycle_event)
    await report_writer(session, result.selection_report)
    await lifecycle_writer(session, result.lifecycle_event)


async def build_and_persist_deterministic_selection(
    session: AsyncSession,
    evidence_pack: Mapping[str, object],
    *,
    generated_at: str | None = None,
    report_writer: SelectionPayloadWriter = upsert_selection_report,
    lifecycle_writer: SelectionPayloadWriter = record_candidate_lifecycle_event,
) -> DeterministicSelectionResult:
    """Build deterministic selection artifacts and persist them."""
    result = build_deterministic_selection(evidence_pack, generated_at=generated_at)
    await persist_selection_result(
        session,
        result,
        report_writer=report_writer,
        lifecycle_writer=lifecycle_writer,
    )
    return result
