from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.services import build_demo_runtime_seed, persist_demo_runtime_seed


async def test_persist_demo_runtime_seed_writes_runtime_artifacts() -> None:
    writes: list[tuple[str, str]] = []

    async def source_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("source", str(payload["source"])))

    async def report_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("report", str(payload["ticker"])))

    async def risk_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("risk", str(payload["decision"])))

    async def lifecycle_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("event", str(payload["event_type"])))

    async def agent_run_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        validate_contract("agent-run", payload)
        writes.append(("agent-run", str(payload["run_id"])))

    async def risk_snapshot_writer(
        session: AsyncSession,
        payload: Mapping[str, object],
    ) -> None:
        assert session is _session()
        validate_contract("risk-snapshot", payload)
        writes.append(("risk-snapshot", str(payload["snapshot_id"])))

    async def execution_state_writer(
        session: AsyncSession,
        payload: Mapping[str, object],
    ) -> None:
        assert session is _session()
        validate_contract("execution-state", payload)
        writes.append(("execution-state", str(payload["state_id"])))

    seed = await persist_demo_runtime_seed(
        _session(),
        source_writer=source_writer,
        report_writer=report_writer,
        risk_writer=risk_writer,
        lifecycle_writer=lifecycle_writer,
        agent_run_writer=agent_run_writer,
        risk_snapshot_writer=risk_snapshot_writer,
        execution_state_writer=execution_state_writer,
    )

    assert len([kind for kind, _value in writes if kind == "agent-run"]) == 1
    assert len([kind for kind, _value in writes if kind == "source"]) == len(seed.source_health)
    assert len([kind for kind, _value in writes if kind == "report"]) == len(seed.selection_reports)
    assert len([kind for kind, _value in writes if kind == "risk"]) == len(seed.risk_decisions)
    assert len([kind for kind, _value in writes if kind == "event"]) == len(
        seed.all_lifecycle_events
    )
    assert len([kind for kind, _value in writes if kind == "risk-snapshot"]) == len(
        seed.risk_decisions
    )
    assert len([kind for kind, _value in writes if kind == "execution-state"]) == len(
        seed.execution_previews
    )


def test_demo_runtime_seed_exercises_dashboard_states() -> None:
    seed = build_demo_runtime_seed()

    assert {report["ticker"] for report in seed.selection_reports} == {"NVDA", "HD", "UNH"}
    assert {decision["decision"] for decision in seed.risk_decisions} == {
        "ALLOW",
        "BLOCK",
        "WARN",
    }
    assert {preview["preview_state"] for preview in seed.execution_previews} == {
        "READY",
        "BLOCKED",
        "DISABLED",
    }


def test_demo_runtime_seed_artifacts_validate_contracts() -> None:
    seed = build_demo_runtime_seed()

    for source in seed.source_health:
        validate_contract("data-source-health", source)
    for pack in seed.evidence_packs:
        validate_contract("evidence-pack", pack)
    for report in seed.selection_reports:
        validate_contract("selection-report", report)
    for decision in seed.risk_decisions:
        validate_contract("risk-decision", decision)
    for preview in seed.execution_previews:
        validate_contract("execution-preview", preview)
    for event in seed.all_lifecycle_events:
        validate_contract("candidate-lifecycle-event", event)


def _session() -> AsyncSession:
    return cast(AsyncSession, _SESSION)


_SESSION = object()
