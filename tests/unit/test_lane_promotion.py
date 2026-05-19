from __future__ import annotations

from fastapi.testclient import TestClient

from agency.app import create_app
from agency.runtime.lane_promotion import load_lane_promotion_status

HTTP_OK = 200


def test_lane_promotion_status_marks_provider_backlog_lanes_disabled() -> None:
    status = load_lane_promotion_status(["fundamentals", "options_flow"])

    lanes = {row["lane"]: row for row in status["lanes"]}
    assert status["ready"] is True
    assert lanes["fundamentals"]["state"] == "action_weighted"
    assert lanes["fundamentals"]["configured"] is True
    assert lanes["options_flow"]["state"] == "disabled"
    assert lanes["options_flow"]["configured"] is True
    assert lanes["buy_sell_pressure"]["state"] == "corroborating"
    assert lanes["subscription_thesis"]["state"] == "context_only"


def test_lane_promotion_endpoint_returns_matrix() -> None:
    client = TestClient(create_app())

    response = client.get("/status/lane-promotion")

    assert response.status_code == HTTP_OK
    assert response.json()["schema_version"] == "0.1.0"
    assert response.json()["lane_count"] >= 1
