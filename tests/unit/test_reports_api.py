from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agency.api.reports import RuntimeSelectionReportsUnavailable, runtime_selection_reports
from agency.app import create_app
from agency.runtime.operational_filters import is_non_operational_payload

HTTP_OK = 200
EXPECTED_LIMIT = 5


def test_selection_reports_endpoint_uses_local_storage_when_postgres_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENCY_RUNTIME_ARTIFACT_FALLBACK", "false")
    client = TestClient(create_app())

    response = client.get("/reports/selection")

    assert response.status_code == HTTP_OK
    assert isinstance(response.json(), list)


def test_selection_reports_for_ticker_endpoint_uses_local_storage_when_postgres_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENCY_RUNTIME_ARTIFACT_FALLBACK", "false")
    client = TestClient(create_app())

    response = client.get("/reports/selection/AAPL")

    assert response.status_code == HTTP_OK
    assert isinstance(response.json(), list)


def test_non_operational_filter_uses_token_boundaries() -> None:
    assert is_non_operational_payload({"cycle_id": "demo-cycle-1"}) is True
    assert is_non_operational_payload({"cycle_id": "manual-smoke-cycle"}) is True
    assert (
        is_non_operational_payload(
            {
                "cycle_id": "cycle-1",
                "notes": "Model note: fundamentals are demonstrably improving.",
            }
        )
        is False
    )


async def test_runtime_selection_reports_uses_repository_payloads() -> None:
    async def reader(session: object, ticker: str | None, limit: int) -> list[dict[str, object]]:
        assert session == "fake-session"
        assert ticker == "AAPL"
        assert limit == EXPECTED_LIMIT
        return [_selection_report()]

    payloads = await runtime_selection_reports(
        ticker="AAPL",
        limit=EXPECTED_LIMIT,
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["ticker"] == "AAPL"
    assert payloads[0]["final_action"] == "WATCH"


async def test_runtime_selection_reports_can_skip_internal_validation() -> None:
    async def reader(session: object, ticker: str | None, limit: int) -> list[dict[str, object]]:
        return [{"ticker": "AAPL"}]

    payloads = await runtime_selection_reports(
        session_provider=_fake_session_provider,
        reader=reader,
        validate_payloads=False,
    )

    assert payloads == [{"ticker": "AAPL"}]


async def test_runtime_selection_reports_filters_demo_seed_payloads() -> None:
    demo = {**_selection_report(), "cycle_id": "demo-cycle-1"}

    async def reader(session: object, ticker: str | None, limit: int) -> list[dict[str, object]]:
        del session, ticker, limit
        return [demo, _selection_report()]

    payloads = await runtime_selection_reports(
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert [payload["cycle_id"] for payload in payloads] == ["cycle-1"]


async def test_runtime_selection_reports_uses_latest_artifact_when_db_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENCY_RUNTIME_ARTIFACT_FALLBACK", "true")
    artifact = tmp_path / "selection-reports.json"
    artifact.write_text(
        json.dumps([_selection_report(), {**_selection_report(), "ticker": "MSFT"}]),
        encoding="utf-8",
    )

    payloads = await runtime_selection_reports(
        ticker="AAPL",
        session_provider=_raising_session_provider,
        artifact_root=tmp_path,
    )

    assert [payload["ticker"] for payload in payloads] == ["AAPL"]
    assert payloads[0]["runtime_origin"] == "runtime_artifact_fallback"


async def test_runtime_selection_reports_does_not_use_artifact_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENCY_RUNTIME_ARTIFACT_FALLBACK", raising=False)
    artifact = tmp_path / "selection-reports.json"
    artifact.write_text(json.dumps([_selection_report()]), encoding="utf-8")

    with pytest.raises(RuntimeSelectionReportsUnavailable):
        await runtime_selection_reports(
            session_provider=_raising_session_provider,
            artifact_root=tmp_path,
        )


async def test_runtime_selection_reports_raises_for_unavailable_db() -> None:
    with pytest.raises(RuntimeSelectionReportsUnavailable):
        await runtime_selection_reports(
            session_provider=_raising_session_provider,
            artifact_root=Path("missing-runtime-artifacts"),
        )


@asynccontextmanager
async def _fake_session_provider() -> AsyncIterator[object]:
    yield "fake-session"


@asynccontextmanager
async def _raising_session_provider() -> AsyncIterator[object]:
    raise OSError("database unavailable")
    yield


def _selection_report() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "generated_at": "2026-05-07T09:31:00Z",
        "final_action": "WATCH",
        "final_conviction": 0.62,
        "deterministic": _engine_decision(),
        "llm_review": _llm_review(),
        "policy_gates": [{"name": "evidence_breadth", "status": "WARN", "reason": "one source"}],
        "risk_flags": [],
        "evidence_pack": _evidence_pack(),
        "trade_plan": {
            "entry": None,
            "stop_loss": None,
            "take_profit": None,
            "position_size": 0,
            "time_in_force": None,
        },
    }


def _evidence_pack() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "generated_at": "2026-05-07T09:31:00Z",
        "actionable_signals": [_signal_result()],
        "context_signals": [],
        "suppressed_signals": [],
        "data_quality": {
            "freshness": "FRESH",
            "source_count": 1,
            "confirmed_signal_count": 1,
            "inferred_signal_count": 0,
            "blockers": [],
        },
    }


def _signal_result() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
        "lane": "fundamentals",
        "score": 0.7,
        "direction": "BULLISH",
        "actionability": "ACTIONABLE",
        "source_tier": "OFFICIAL_FILING",
        "verification_level": "CONFIRMED",
        "freshness": "FRESH",
        "confidence": 0.9,
        "provenance": _provenance(),
        "reason_codes": ["quality_positive"],
        "suppression_reason": None,
    }


def _engine_decision() -> dict[str, object]:
    return {
        "action": "WATCH",
        "score": 0.4,
        "conviction": 0.62,
        "reason_codes": ["quality_positive"],
        "blockers": [],
    }


def _llm_review() -> dict[str, object]:
    return {
        "action": "WATCH",
        "confidence": 0.55,
        "rationale": "Constructive but incomplete.",
        "supporting_factors": ["fundamentals_positive"],
        "concerns": ["news_breadth_low"],
    }


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
