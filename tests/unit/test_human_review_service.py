from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest
from service_fixtures import selection_report
from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import ContractValidationError, validate_contract
from agency.services import (
    build_and_persist_human_review_event,
    build_human_review_event,
    build_operator_manual_advance_event,
    persist_human_review_event,
    selection_report_hash,
)


def test_build_human_review_event_is_contract_valid() -> None:
    event = build_human_review_event(
        cycle_id="cycle-1",
        ticker="aapl",
        as_of="2026-05-07T09:30:00Z",
        decision="APPROVE",
        review_reason=" two confirmed lanes ",
        notes="  Looks clean after risk review. ",
        event_time="2026-05-07T10:00:00Z",
    )

    validate_contract("candidate-lifecycle-event", event)
    assert event["ticker"] == "AAPL"
    assert event["event_type"] == "HUMAN_REVIEW"
    assert event["status"] == "PASSED"
    assert event["reason"] == "paper review approved"
    assert event["payload"]["review_decision"] == "APPROVE"
    assert event["payload"]["review_reason"] == "two confirmed lanes"
    assert event["payload"]["notes"] == "Looks clean after risk review."
    assert event["payload"]["paper_only"] is True


def test_selection_report_hash_is_stable() -> None:
    report = selection_report()

    assert selection_report_hash(report) == selection_report_hash(dict(report))


def test_build_human_review_event_rejects_unknown_decision() -> None:
    with pytest.raises(ValueError, match="APPROVE"):
        build_human_review_event(
            cycle_id="cycle-1",
            ticker="AAPL",
            as_of="2026-05-07T09:30:00Z",
            decision="MAYBE",
        )


def test_build_human_review_event_records_caution_acknowledgement() -> None:
    event = build_human_review_event(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        decision="APPROVE",
        event_time="2026-05-07T10:00:00Z",
        caution_acknowledged=True,
    )

    validate_contract("candidate-lifecycle-event", event)
    assert event["payload"]["caution_acknowledged"] is True


def test_build_operator_manual_advance_event_is_report_hash_bound() -> None:
    report = selection_report(policy_status="BLOCK", policy_reason="operator accepted risk")
    report_hash = selection_report_hash(report)

    event = build_operator_manual_advance_event(
        cycle_id=str(report["cycle_id"]),
        ticker=str(report["ticker"]),
        as_of=str(report["as_of"]),
        selection_report_hash=report_hash,
        override_reason="Operator accepts the policy block for a paper rehearsal.",
        blocked_reason="selection policy gate blocked: evidence_breadth",
        acknowledged=True,
        event_time="2026-05-07T10:02:00Z",
    )

    validate_contract("candidate-lifecycle-event", event)
    assert event["event_type"] == "OPERATOR_MANUAL_ADVANCE"
    assert event["status"] == "PASSED"
    assert event["payload"]["advance_type"] == "PAPER_PROMOTION_OVERRIDE"
    assert event["payload"]["paper_only"] is True
    assert event["payload"]["acknowledged"] is True
    assert event["payload"]["selection_report_hash"] == report_hash
    assert event["payload"]["blocked_reason"] == "selection policy gate blocked: evidence_breadth"


def test_build_operator_manual_advance_event_requires_reason_and_acknowledgement() -> None:
    report = selection_report()
    report_hash = selection_report_hash(report)

    with pytest.raises(ValueError, match="reason"):
        build_operator_manual_advance_event(
            cycle_id=str(report["cycle_id"]),
            ticker=str(report["ticker"]),
            as_of=str(report["as_of"]),
            selection_report_hash=report_hash,
            override_reason=" ",
            acknowledged=True,
        )
    with pytest.raises(ValueError, match="acknowledgement"):
        build_operator_manual_advance_event(
            cycle_id=str(report["cycle_id"]),
            ticker=str(report["ticker"]),
            as_of=str(report["as_of"]),
            selection_report_hash=report_hash,
            override_reason="Paper rehearsal override.",
            acknowledged=False,
        )


async def test_build_and_persist_human_review_event_writes_lifecycle() -> None:
    writes: list[tuple[str, str]] = []

    async def lifecycle_writer(
        session: AsyncSession,
        payload: Mapping[str, object],
    ) -> None:
        assert session is _session()
        writes.append((str(payload["event_type"]), str(payload["status"])))

    event = await build_and_persist_human_review_event(
        _session(),
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        decision="REJECT",
        event_time="2026-05-07T10:00:00Z",
        lifecycle_writer=lifecycle_writer,
    )

    assert event["status"] == "BLOCKED"
    assert writes == [("HUMAN_REVIEW", "BLOCKED")]


async def test_persist_human_review_event_validates_before_writing() -> None:
    writes: list[str] = []
    event = build_human_review_event(
        cycle_id="cycle-1",
        ticker="AAPL",
        as_of="2026-05-07T09:30:00Z",
        decision="DEFER",
        event_time="2026-05-07T10:00:00Z",
    )
    event["status"] = "UNKNOWN"

    async def lifecycle_writer(
        _session_arg: AsyncSession,
        payload: Mapping[str, object],
    ) -> None:
        writes.append(str(payload["event_type"]))

    with pytest.raises(ContractValidationError):
        await persist_human_review_event(
            _session(),
            event,
            lifecycle_writer=lifecycle_writer,
        )

    assert writes == []


def _session() -> AsyncSession:
    return cast(AsyncSession, _SESSION)


_SESSION = object()
