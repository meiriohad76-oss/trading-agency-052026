from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agency.contracts import ContractValidationError
from agency.services import (
    build_and_persist_deterministic_selection,
    build_deterministic_selection,
    build_evidence_pack,
    build_signal_result,
    persist_selection_result,
)


async def test_persist_selection_result_writes_report_then_lifecycle() -> None:
    writes: list[tuple[str, str]] = []

    async def report_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("report", str(payload["ticker"])))

    async def lifecycle_writer(session: AsyncSession, payload: Mapping[str, object]) -> None:
        assert session is _session()
        writes.append(("lifecycle", str(payload["event_type"])))

    await persist_selection_result(
        _session(),
        build_deterministic_selection(_evidence_pack()),
        report_writer=report_writer,
        lifecycle_writer=lifecycle_writer,
    )

    assert writes == [("report", "AAPL"), ("lifecycle", "DETERMINISTIC_ACTION")]


async def test_persist_selection_result_validates_before_writing() -> None:
    writes: list[str] = []

    async def writer(_session_arg: AsyncSession, payload: Mapping[str, object]) -> None:
        writes.append(str(payload["ticker"]))

    result = build_deterministic_selection(_evidence_pack())
    result.selection_report["ticker"] = "bad ticker"

    with pytest.raises(ContractValidationError):
        await persist_selection_result(
            _session(),
            result,
            report_writer=writer,
            lifecycle_writer=writer,
        )

    assert writes == []


async def test_build_and_persist_deterministic_selection_returns_persisted_result() -> None:
    writes: list[str] = []

    async def report_writer(_session_arg: AsyncSession, payload: Mapping[str, object]) -> None:
        writes.append(str(payload["final_action"]))

    async def lifecycle_writer(_session_arg: AsyncSession, payload: Mapping[str, object]) -> None:
        writes.append(str(payload["status"]))

    result = await build_and_persist_deterministic_selection(
        _session(),
        _evidence_pack(),
        report_writer=report_writer,
        lifecycle_writer=lifecycle_writer,
    )

    assert result.selection_report["final_action"] == "WATCH"
    assert writes == ["WATCH", "ACTIONABLE"]


def _session() -> AsyncSession:
    return cast(AsyncSession, _SESSION)


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


_SESSION = object()
