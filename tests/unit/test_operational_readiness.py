from __future__ import annotations

from fastapi.testclient import TestClient

from agency.app import create_app
from agency.runtime.operational_readiness import build_operational_readiness

HTTP_OK = 200
EXPECTED_ATTENTION_WARNINGS = 2
EXPECTED_BLOCKERS = 5


def test_operational_readiness_is_ready_with_pending_review_attention() -> None:
    summary = build_operational_readiness(
        health={"status": "ok"},
        live_config={"ready": True, "blocker_count": 0, "warning_count": 0},
        data_refresh={"state": "complete", "status_label": "Complete"},
        live_readiness={
            "ready": True,
            "verdict": "ready_for_paper_validation",
            "cycle_id": "cycle-1",
        },
        paper_review={
            "progress": {
                "total_count": 2,
                "reviewed_count": 1,
                "pending_count": 1,
            }
        },
        key_statuses=[
            _key("ALPACA_API_KEY", required=True, present=True),
            _key("ALPACA_SECRET_KEY", required=True, present=True),
            _key("SEC_USER_AGENT", required=True, present=True),
            _key("OPENAI_API_KEY", required=False, present=False),
        ],
    )

    assert summary["ready"] is True
    assert summary["state"] == "attention"
    assert summary["broker_execution_enabled"] is False
    assert summary["blocker_count"] == 0
    assert summary["warning_count"] == EXPECTED_ATTENTION_WARNINGS


def test_operational_readiness_blocks_missing_runtime_cycle_and_keys() -> None:
    summary = build_operational_readiness(
        health={"status": "ok"},
        live_config={"ready": False, "blocker_count": 1, "warning_count": 0},
        data_refresh={"state": "failed", "status_label": "Failed"},
        live_readiness={"ready": False, "detail": "No runtime cycle found."},
        paper_review={"progress": {"total_count": 0, "reviewed_count": 0, "pending_count": 0}},
        key_statuses=[_key("ALPACA_API_KEY", required=True, present=False)],
    )

    assert summary["ready"] is False
    assert summary["state"] == "blocked"
    assert summary["blocker_count"] == EXPECTED_BLOCKERS
    assert "Add ALPACA_API_KEY to .env." in summary["next_actions"]


def test_operational_readiness_endpoint_returns_combined_status(monkeypatch) -> None:
    async def fake_reports(
        *,
        limit: int = 50,
        ticker: str | None = None,
    ) -> list[dict[str, object]]:
        del limit, ticker
        return [_report()]

    async def fake_sources() -> list[dict[str, object]]:
        return [_source()]

    async def fake_risks(*, limit: int = 50, ticker: str | None = None) -> list[dict[str, object]]:
        del limit, ticker
        return [_risk()]

    async def fake_review_events(*args: object, **kwargs: object) -> list[dict[str, object]]:
        del args, kwargs
        return []

    monkeypatch.setattr("agency.dashboard.runtime_selection_reports", fake_reports)
    monkeypatch.setattr("agency.dashboard.runtime_data_source_status", fake_sources)
    monkeypatch.setattr("agency.dashboard.runtime_risk_decisions", fake_risks)
    monkeypatch.setattr("agency.dashboard.human_review_events_for_reports", fake_review_events)
    monkeypatch.setattr("agency.dashboard.load_live_config_readiness", _live_config)
    monkeypatch.setattr("agency.dashboard.load_data_refresh_progress", _data_refresh)
    client = TestClient(create_app())

    response = client.get("/status/operational-readiness")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["ready"] is True
    assert payload["paper_review"]["progress"]["total_count"] == 1


def _key(name: str, *, required: bool, present: bool) -> dict[str, object]:
    return {
        "name": name,
        "required": required,
        "present": present,
        "status": "PASS" if present else "WARN",
        "file": ".env",
        "purpose": "test",
    }


def _live_config() -> dict[str, object]:
    return {
        "ready": True,
        "provider": "yfinance",
        "blocker_count": 0,
        "warning_count": 0,
        "checks": [{"label": "SEC User-Agent", "status": "PASS"}],
    }


def _data_refresh() -> dict[str, object]:
    return {"state": "complete", "status_label": "Complete"}


def _source() -> dict[str, object]:
    return {
        "source": "sec-edgar",
        "status": "HEALTHY",
        "freshness": "FRESH",
        "notes": ["ready"],
    }


def _report() -> dict[str, object]:
    return {
        "cycle_id": "live-pit-2026-05-08",
        "ticker": "AAPL",
        "as_of": "2026-05-08T00:00:00Z",
        "final_action": "WATCH",
        "final_conviction": 0.62,
        "policy_gates": [{"name": "gate", "status": "PASS", "reason": "ok"}],
        "risk_flags": [],
        "evidence_pack": {
            "actionable_signals": [
                {"ticker": "AAPL", "provenance": {"source": "sec-edgar"}}
            ],
            "context_signals": [],
            "suppressed_signals": [],
            "data_quality": {"source_count": 1, "confirmed_signal_count": 1},
        },
    }


def _risk() -> dict[str, object]:
    return {
        "cycle_id": "live-pit-2026-05-08",
        "ticker": "AAPL",
        "as_of": "2026-05-08T00:00:00Z",
        "decision": "WARN",
        "reasons": ["paper review required"],
    }
