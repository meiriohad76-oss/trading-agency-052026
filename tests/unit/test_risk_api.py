from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from service_fixtures import selection_report

from agency.api.risk import runtime_risk_decisions
from agency.app import create_app
from agency.services import build_risk_decision

HTTP_OK = 200
RISK_DECISION_LIMIT = 5


def test_risk_decisions_endpoint_falls_back_to_empty_list() -> None:
    client = TestClient(create_app())

    response = client.get("/risk/decisions")

    assert response.status_code == HTTP_OK
    assert response.json() == []


async def test_runtime_risk_decisions_uses_repository_payloads() -> None:
    async def reader(
        session: object,
        ticker: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        assert session == "fake-session"
        assert ticker == "AAPL"
        assert limit == RISK_DECISION_LIMIT
        return [_risk_decision()]

    payloads = await runtime_risk_decisions(
        ticker="AAPL",
        limit=RISK_DECISION_LIMIT,
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["ticker"] == "AAPL"
    assert payloads[0]["decision"] == "ALLOW"


async def test_runtime_risk_decisions_falls_back_for_unavailable_db() -> None:
    payloads = await runtime_risk_decisions(session_provider=_raising_session_provider)

    assert payloads == []


@asynccontextmanager
async def _fake_session_provider() -> AsyncIterator[object]:
    yield "fake-session"


@asynccontextmanager
async def _raising_session_provider() -> AsyncIterator[object]:
    raise OSError("database unavailable")
    yield


def _risk_decision() -> dict[str, object]:
    return build_risk_decision(
        selection_report(action="BUY"),
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision
