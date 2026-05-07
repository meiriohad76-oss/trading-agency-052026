from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from agency.api.reports import runtime_selection_reports
from agency.app import create_app

HTTP_OK = 200
EXPECTED_LIMIT = 5


def test_selection_reports_endpoint_falls_back_to_empty_list() -> None:
    client = TestClient(create_app())

    response = client.get("/reports/selection")

    assert response.status_code == HTTP_OK
    assert response.json() == []


def test_selection_reports_for_ticker_endpoint_falls_back_to_empty_list() -> None:
    client = TestClient(create_app())

    response = client.get("/reports/selection/AAPL")

    assert response.status_code == HTTP_OK
    assert response.json() == []


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


async def test_runtime_selection_reports_falls_back_for_unavailable_db() -> None:
    payloads = await runtime_selection_reports(session_provider=_raising_session_provider)

    assert payloads == []


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
