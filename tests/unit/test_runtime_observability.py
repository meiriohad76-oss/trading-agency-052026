from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from agency.api.health import runtime_metrics
from agency.app import create_app
from agency.runtime import runtime_metrics_text, structured_log

HTTP_OK = 200


def test_metrics_endpoint_returns_prometheus_text() -> None:
    client = TestClient(create_app())

    response = client.get("/metrics")

    assert response.status_code == HTTP_OK
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert "agency_source_health_total 1" in response.text
    assert "agency_source_degraded_total 1" in response.text
    assert "agency_live_readiness_ready 0" in response.text


async def test_runtime_metrics_uses_payload_providers() -> None:
    text = await runtime_metrics(
        source_status_provider=_source_status_provider,
        selection_report_provider=_selection_report_provider,
        risk_decision_provider=_risk_decision_provider,
    )

    assert "agency_source_health_total 2" in text
    assert "agency_source_degraded_total 1" in text
    assert 'agency_final_action_total{value="WATCH"} 1' in text
    assert 'agency_risk_decision_total{value="ALLOW"} 1' in text
    assert "agency_live_readiness_ready 0" in text
    assert "agency_live_readiness_blockers_total 1" in text


def test_runtime_metrics_text_escapes_labels() -> None:
    text = runtime_metrics_text(
        source_health=[],
        selection_reports=[{"final_action": 'WATCH "A"'}],
        risk_decisions=[],
    )

    assert 'agency_final_action_total{value="WATCH \\"A\\""} 1' in text
    assert 'agency_risk_decision_total{value="none"} 0' in text


def test_structured_log_renders_compact_json_line() -> None:
    timestamp = datetime(2026, 5, 8, 10, 30, tzinfo=UTC)

    payload = json.loads(structured_log("agency_cycle_completed", timestamp=timestamp, rows=3))

    assert payload == {
        "event": "agency_cycle_completed",
        "level": "INFO",
        "rows": 3,
        "timestamp": "2026-05-08T10:30:00+00:00",
    }


async def _source_status_provider() -> list[dict[str, object]]:
    return [{"status": "HEALTHY", "freshness": "FRESH"}, {"status": "STALE", "freshness": "STALE"}]


async def _selection_report_provider() -> list[dict[str, object]]:
    return [{"cycle_id": "cycle-1", "final_action": "WATCH"}]


async def _risk_decision_provider() -> list[dict[str, object]]:
    return [{"cycle_id": "cycle-1", "decision": "ALLOW"}]
