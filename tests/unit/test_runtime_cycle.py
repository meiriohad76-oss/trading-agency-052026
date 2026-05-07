from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from service_fixtures import provenance, source_health
from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import validate_contract
from agency.services import (
    RuntimeCycleResult,
    build_runtime_cycle,
    build_runtime_cycle_from_payload,
    build_signal_result,
    persist_runtime_cycle,
)

CYCLE_ID = "cycle-2026-05-07T143000Z"
AS_OF = "2026-05-07T14:30:00Z"
GENERATED_AT = "2026-05-07T14:31:00Z"
PROJECTED_EXPOSURE_PCT = 15.0


def test_runtime_cycle_builds_contract_valid_artifacts() -> None:
    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[_signal("AAPL", 0.7), _signal("MSFT", -0.8)],
    )

    assert [pack["ticker"] for pack in cycle.evidence_packs] == ["AAPL", "MSFT"]
    assert [report["final_action"] for report in cycle.selection_reports] == [
        "WATCH",
        "NO_TRADE",
    ]
    assert {preview["preview_state"] for preview in cycle.execution_previews} == {
        "BLOCKED",
        "DISABLED",
    }
    _assert_contracts(cycle)


def test_runtime_cycle_records_requested_tickers_without_signals() -> None:
    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[],
        tickers=["AAPL"],
    )

    assert cycle.evidence_packs[0]["ticker"] == "AAPL"
    assert cycle.selection_reports[0]["final_action"] == "NO_TRADE"
    assert cycle.risk_decisions[0]["decision"] == "BLOCK"
    assert cycle.execution_previews[0]["preview_state"] == "BLOCKED"


def test_runtime_cycle_from_payload_accepts_json_compatible_inputs() -> None:
    cycle = build_runtime_cycle_from_payload(
        {
            "cycle_id": CYCLE_ID,
            "as_of": AS_OF,
            "generated_at": GENERATED_AT,
            "tickers": ["aapl"],
            "source_health": [source_health()],
            "signals": [_signal("AAPL", 0.7)],
            "current_gross_exposure_pct": 5.0,
        }
    )

    assert cycle.selection_reports[0]["ticker"] == "AAPL"
    assert cycle.risk_decisions[0]["projected_gross_exposure_pct"] == PROJECTED_EXPOSURE_PCT


async def test_persist_runtime_cycle_writes_persistent_artifacts_and_audit_events() -> None:
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

    cycle = build_runtime_cycle(
        cycle_id=CYCLE_ID,
        as_of=AS_OF,
        generated_at=GENERATED_AT,
        source_health=[source_health()],
        signals=[_signal("AAPL", 0.7)],
    )

    persisted = await persist_runtime_cycle(
        _session(),
        cycle,
        source_writer=source_writer,
        report_writer=report_writer,
        risk_writer=risk_writer,
        lifecycle_writer=lifecycle_writer,
    )

    assert persisted is cycle
    assert len([kind for kind, _value in writes if kind == "source"]) == 1
    assert len([kind for kind, _value in writes if kind == "report"]) == 1
    assert len([kind for kind, _value in writes if kind == "risk"]) == 1
    assert len([kind for kind, _value in writes if kind == "event"]) == len(
        cycle.all_lifecycle_events
    )


def _signal(ticker: str, score: float) -> dict[str, object]:
    return build_signal_result(
        cycle_id=CYCLE_ID,
        ticker=ticker,
        as_of=AS_OF,
        lane="fundamentals",
        score=score,
        provenance=provenance(),
        confidence=0.9,
    )


def _assert_contracts(cycle: RuntimeCycleResult) -> None:
    for source in cycle.source_health:
        validate_contract("data-source-health", source)
    for pack in cycle.evidence_packs:
        validate_contract("evidence-pack", pack)
    for report in cycle.selection_reports:
        validate_contract("selection-report", report)
    for decision in cycle.risk_decisions:
        validate_contract("risk-decision", decision)
    for preview in cycle.execution_previews:
        validate_contract("execution-preview", preview)
    for event in cycle.all_lifecycle_events:
        validate_contract("candidate-lifecycle-event", event)


def _session() -> AsyncSession:
    return cast(AsyncSession, _SESSION)


_SESSION = object()
