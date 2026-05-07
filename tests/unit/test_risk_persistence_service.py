from __future__ import annotations

from collections.abc import Mapping

from service_fixtures import selection_report
from sqlalchemy.ext.asyncio import AsyncSession

from agency.services import build_risk_decision, persist_risk_result


async def test_persist_risk_result_writes_decision_and_lifecycle_event() -> None:
    writes: list[tuple[str, str]] = []

    async def decision_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session == "fake-session"
        writes.append(("decision", str(payload["decision"])))

    async def lifecycle_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session == "fake-session"
        writes.append(("event", str(payload["event_type"])))

    result = build_risk_decision(
        selection_report(action="BUY"),
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    )

    await persist_risk_result(
        "fake-session",  # type: ignore[arg-type]
        result,
        decision_writer=decision_writer,
        lifecycle_writer=lifecycle_writer,
    )

    assert writes == [("decision", "ALLOW"), ("event", "RISK_DECISION")]
