from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from agency.api.candidates import runtime_candidate_timeline
from agency.app import create_app
from agency.runtime import make_lifecycle_event_id

HTTP_OK = 200
EXPECTED_LIMIT = 7


def test_candidate_timeline_endpoint_falls_back_to_empty_list() -> None:
    client = TestClient(create_app())

    response = client.get("/candidates/AAPL/timeline")

    assert response.status_code == HTTP_OK
    assert response.json() == []


async def test_runtime_candidate_timeline_uses_repository_payloads() -> None:
    async def reader(
        session: object,
        ticker: str,
        cycle_id: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        assert session == "fake-session"
        assert ticker == "AAPL"
        assert cycle_id == "cycle-1"
        assert limit == EXPECTED_LIMIT
        return [_lifecycle_event()]

    payloads = await runtime_candidate_timeline(
        ticker="AAPL",
        cycle_id="cycle-1",
        limit=EXPECTED_LIMIT,
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["ticker"] == "AAPL"
    assert payloads[0]["event_type"] == "FINAL_ACTION"


async def test_runtime_candidate_timeline_falls_back_for_unavailable_db() -> None:
    payloads = await runtime_candidate_timeline(
        ticker="AAPL",
        session_provider=_raising_session_provider,
    )

    assert payloads == []


@asynccontextmanager
async def _fake_session_provider() -> AsyncIterator[object]:
    yield "fake-session"


@asynccontextmanager
async def _raising_session_provider() -> AsyncIterator[object]:
    raise OSError("database unavailable")
    yield


def _lifecycle_event() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "event_id": make_lifecycle_event_id(
            cycle_id="cycle-1",
            ticker="AAPL",
            event_type="FINAL_ACTION",
            event_time="2026-05-07T09:31:00Z",
        ),
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "event_type": "FINAL_ACTION",
        "event_time": "2026-05-07T09:31:00Z",
        "status": "RECORDED",
        "reason": "selection report persisted",
        "payload": {"final_action": "WATCH"},
    }
