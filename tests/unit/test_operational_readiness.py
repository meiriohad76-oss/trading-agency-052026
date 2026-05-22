from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from agency.app import create_app
from agency.runtime.operational_keys import load_key_statuses
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


def test_operational_readiness_reports_enabled_paper_broker_gate() -> None:
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
                "total_count": 1,
                "reviewed_count": 1,
                "pending_count": 0,
            }
        },
        key_statuses=[
            _key("ALPACA_API_KEY", required=True, present=True),
            _key("ALPACA_SECRET_KEY", required=True, present=True),
            _key("SEC_USER_AGENT", required=True, present=True),
        ],
        broker_execution_enabled=True,
    )

    assert summary["broker_execution_enabled"] is True
    checks = cast(Sequence[Mapping[str, object]], summary["checks"])
    broker_check = next(
        check for check in checks if check["label"] == "Broker execution"
    )
    assert broker_check["status"] == "PASS"
    assert "approved READY previews can be submitted" in str(broker_check["detail"])


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
    next_actions = cast(Sequence[object], summary["next_actions"])
    assert "Add ALPACA_API_KEY to .env." in next_actions


def test_operational_readiness_blocks_stale_data_refresh() -> None:
    summary = build_operational_readiness(
        health={"status": "ok"},
        live_config={"ready": True, "blocker_count": 0, "warning_count": 0},
        data_refresh={"state": "stale", "status_label": "Stale"},
        live_readiness={
            "ready": True,
            "verdict": "ready_for_paper_validation",
            "cycle_id": "cycle-1",
        },
        paper_review={
            "progress": {
                "total_count": 1,
                "reviewed_count": 1,
                "pending_count": 0,
            }
        },
        key_statuses=[
            _key("ALPACA_API_KEY", required=True, present=True),
            _key("ALPACA_SECRET_KEY", required=True, present=True),
            _key("SEC_USER_AGENT", required=True, present=True),
        ],
    )

    assert summary["ready"] is False
    checks = cast(Sequence[Mapping[str, object]], summary["checks"])
    data_refresh = next(check for check in checks if check["label"] == "Data refresh")
    assert data_refresh["status"] == "BLOCK"


def test_operational_readiness_blocks_planned_data_refresh() -> None:
    summary = build_operational_readiness(
        health={"status": "ok"},
        live_config={"ready": True, "blocker_count": 0, "warning_count": 0},
        data_refresh={"state": "planned", "status_label": "Planned"},
        live_readiness={
            "ready": True,
            "verdict": "watch_candidates_available",
        },
        paper_review={"progress": {"total_count": 1, "reviewed_count": 0, "pending_count": 1}},
        key_statuses=[],
    )

    assert summary["ready"] is False
    checks = cast(Sequence[Mapping[str, object]], summary["checks"])
    data_refresh = next(check for check in checks if check["label"] == "Data refresh")
    assert data_refresh["status"] == "BLOCK"


def test_operational_readiness_blocks_running_data_refresh() -> None:
    summary = build_operational_readiness(
        health={"status": "ok"},
        live_config={"ready": True, "blocker_count": 0, "warning_count": 0},
        data_refresh={"state": "running", "status_label": "Loading", "eta_label": "2m"},
        live_readiness={
            "ready": True,
            "verdict": "watch_candidates_available",
        },
        paper_review={"progress": {"total_count": 1, "reviewed_count": 1, "pending_count": 0}},
        key_statuses=[],
    )

    assert summary["ready"] is False
    checks = cast(Sequence[Mapping[str, object]], summary["checks"])
    data_refresh = next(check for check in checks if check["label"] == "Data refresh")
    assert data_refresh["status"] == "BLOCK"
    assert "ETA 2m" in str(data_refresh["detail"])


def test_operational_readiness_warns_for_background_refresh_with_reviewable_data() -> None:
    summary = build_operational_readiness(
        health={"status": "ok"},
        live_config={"ready": True, "blocker_count": 0, "warning_count": 0},
        data_refresh={"state": "running", "status_label": "Loading", "eta_label": "2m"},
        data_load_status={
            "ready": True,
            "review_operational_ready": True,
            "state": "attention",
            "status_label": "Attention",
            "blocker_count": 0,
            "warning_count": 1,
            "core_dataset_percent": 78,
            "critical_lane_percent": 98,
        },
        live_readiness={
            "ready": False,
            "review_operational_ready": True,
            "verdict": "ready_with_partial_lanes",
            "readiness_scope_label": "Review Subset",
        },
        paper_review={"progress": {"total_count": 1, "reviewed_count": 1, "pending_count": 0}},
        key_statuses=[],
    )

    assert summary["ready"] is True
    assert summary["state"] == "attention"
    checks = cast(Sequence[Mapping[str, object]], summary["checks"])
    data_refresh = next(check for check in checks if check["label"] == "Data refresh")
    runtime_cycle = next(check for check in checks if check["label"] == "Runtime cycle")
    assert data_refresh["status"] == "WARN"
    assert runtime_cycle["status"] == "WARN"


def test_operational_readiness_warns_for_support_only_refresh_failure() -> None:
    summary = build_operational_readiness(
        health={"status": "ok"},
        live_config={"ready": True, "blocker_count": 0, "warning_count": 0},
        data_refresh={
            "state": "failed",
            "status_label": "Failed",
            "current_dataset": "sec_form4",
            "detail": "SEC Form 4 refresh failed after core lanes completed.",
        },
        data_load_status={
            "ready": True,
            "review_operational_ready": True,
            "tradable_ready": True,
            "state": "attention",
            "status_label": "Attention",
            "blocker_count": 0,
            "warning_count": 1,
            "overall_percent": 96,
            "core_dataset_percent": 100,
            "critical_lane_percent": 100,
        },
        live_readiness={
            "ready": False,
            "review_operational_ready": True,
            "verdict": "ready_with_partial_lanes",
            "readiness_scope_label": "Full Universe",
        },
        paper_review={"progress": {"total_count": 1, "reviewed_count": 1, "pending_count": 0}},
        key_statuses=[],
    )

    assert summary["ready"] is True
    assert summary["state"] == "attention"
    checks = cast(Sequence[Mapping[str, object]], summary["checks"])
    data_refresh = next(check for check in checks if check["label"] == "Data refresh")
    assert data_refresh["status"] == "WARN"
    assert "support refresh failed" in str(data_refresh["detail"])


def test_operational_readiness_warns_for_support_failed_dataset_without_current_dataset() -> None:
    summary = build_operational_readiness(
        health={"status": "ok"},
        live_config={"ready": True, "blocker_count": 0, "warning_count": 0},
        data_refresh={
            "state": "failed",
            "status_label": "Failed",
            "current_dataset": "None",
            "failed_datasets": ["sec_form4"],
        },
        data_load_status={
            "ready": True,
            "review_operational_ready": True,
            "tradable_ready": True,
            "state": "attention",
            "status_label": "Loaded With Gaps",
            "blocker_count": 0,
            "warning_count": 1,
            "overall_percent": 96,
            "core_dataset_percent": 100,
            "critical_lane_percent": 100,
        },
        live_readiness={
            "ready": False,
            "review_operational_ready": True,
            "verdict": "ready_with_partial_lanes",
            "readiness_scope_label": "Full Universe",
        },
        paper_review={"progress": {"total_count": 1, "reviewed_count": 0, "pending_count": 1}},
        key_statuses=[],
    )

    assert summary["ready"] is True
    checks = cast(Sequence[Mapping[str, object]], summary["checks"])
    data_refresh = next(check for check in checks if check["label"] == "Data refresh")
    assert data_refresh["status"] == "WARN"
    assert "sec_form4" in str(data_refresh["detail"])


def test_operational_readiness_blocks_loading_data_load_status() -> None:
    summary = build_operational_readiness(
        health={"status": "ok"},
        live_config={"ready": True, "blocker_count": 0, "warning_count": 0},
        data_refresh={"state": "complete", "status_label": "Complete"},
        data_load_status={
            "ready": False,
            "state": "loading",
            "status_label": "Loading",
            "overall_percent": 72,
            "blocker_count": 0,
            "warning_count": 0,
        },
        live_readiness={
            "ready": True,
            "verdict": "watch_candidates_available",
        },
        paper_review={"progress": {"total_count": 1, "reviewed_count": 1, "pending_count": 0}},
        key_statuses=[],
    )

    assert summary["ready"] is False
    checks = cast(Sequence[Mapping[str, object]], summary["checks"])
    data_load = next(check for check in checks if check["label"] == "Data loaded and analyzed")
    assert data_load["status"] == "BLOCK"


def test_operational_readiness_softens_stale_sources_when_data_load_is_complete() -> None:
    summary = build_operational_readiness(
        health={"status": "ok"},
        live_config={"ready": True, "blocker_count": 0, "warning_count": 0},
        data_refresh={"state": "complete", "status_label": "Complete"},
        data_load_status={
            "ready": True,
            "state": "ready",
            "status_label": "Loaded",
            "blocker_count": 0,
            "warning_count": 0,
            "overall_percent": 100,
            "core_dataset_percent": 100,
            "critical_lane_percent": 100,
        },
        live_readiness={
            "ready": False,
            "verdict": "context_only_source_health",
            "detail": "STALE / STALE; stale source row",
        },
        paper_review={
            "progress": {
                "total_count": 1,
                "reviewed_count": 1,
                "pending_count": 0,
            }
        },
        key_statuses=[
            _key("ALPACA_API_KEY", required=True, present=True),
            _key("ALPACA_SECRET_KEY", required=True, present=True),
            _key("SEC_USER_AGENT", required=True, present=True),
        ],
    )

    assert summary["ready"] is True
    assert summary["state"] == "attention"
    checks = cast(Sequence[Mapping[str, object]], summary["checks"])
    data_load = next(
        check for check in checks if check["label"] == "Data loaded and analyzed"
    )
    runtime = next(check for check in checks if check["label"] == "Runtime cycle")
    assert data_load["status"] == "PASS"
    assert runtime["status"] == "WARN"
    assert "data-load coverage is complete" in str(runtime["detail"])


def test_operational_readiness_softens_stale_sources_when_data_load_is_tradable() -> None:
    summary = build_operational_readiness(
        health={"status": "ok"},
        live_config={"ready": True, "blocker_count": 0, "warning_count": 0},
        data_refresh={"state": "complete", "status_label": "Complete"},
        data_load_status={
            "ready": True,
            "review_operational_ready": True,
            "tradable_ready": True,
            "state": "attention",
            "status_label": "Loaded With Gaps",
            "blocker_count": 0,
            "warning_count": 3,
            "overall_percent": 97,
            "core_dataset_percent": 100,
            "critical_lane_percent": 92,
        },
        live_readiness={
            "ready": False,
            "verdict": "context_only_source_health",
            "detail": "checked_at is stale; refresh source-health before review",
        },
        paper_review={
            "progress": {
                "total_count": 17,
                "reviewed_count": 0,
                "pending_count": 17,
            }
        },
        key_statuses=[],
    )

    assert summary["ready"] is True
    checks = cast(Sequence[Mapping[str, object]], summary["checks"])
    runtime = next(check for check in checks if check["label"] == "Runtime cycle")
    assert runtime["status"] == "WARN"
    assert "data-load coverage is complete" in str(runtime["detail"])


def test_operational_readiness_endpoint_returns_combined_status(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_reports(
        *,
        limit: int = 50,
        ticker: str | None = None,
    ) -> list[dict[str, object]]:
        del limit, ticker
        return [_report()]

    async def fake_sources() -> list[dict[str, object]]:
        return [_source()]

    async def fake_source_load_status() -> dict[str, object]:
        return {
            "data_sources": [_source()],
            "data_load_status": {**_data_load(), "live_config": _live_config()},
        }

    async def fake_risks(*, limit: int = 50, ticker: str | None = None) -> list[dict[str, object]]:
        del limit, ticker
        return [_risk()]

    async def fake_review_events(*args: object, **kwargs: object) -> list[dict[str, object]]:
        del args, kwargs
        return []

    monkeypatch.setattr("agency.views._shared.runtime_selection_reports", fake_reports)
    monkeypatch.setattr("agency.views.command.runtime_data_source_status", fake_sources)
    monkeypatch.setattr(
        "agency.views.command.runtime_data_source_status_with_load_status",
        fake_source_load_status,
    )
    monkeypatch.setattr("agency.views._shared.runtime_risk_decisions", fake_risks)
    monkeypatch.setattr(
        "agency.views.command.human_review_events_for_reports", fake_review_events
    )
    monkeypatch.setattr("agency.views.command.load_live_config_readiness", _live_config)
    monkeypatch.setattr("agency.views.command.load_data_refresh_progress", _data_refresh)
    monkeypatch.setattr("agency.views.command.load_data_load_status", _data_load)
    client = TestClient(create_app())

    response = client.get("/status/operational-readiness")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["ready"] is True
    assert payload["paper_review"]["progress"]["total_count"] == 1


def test_operational_keys_require_massive_when_active_provider(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    monkeypatch.setenv("POLYGON_API_KEY", "")

    keys = load_key_statuses(
        {
            "provider": "massive",
            "checks": [{"label": "SEC User-Agent", "status": "PASS"}],
        }
    )

    massive = next(key for key in keys if "MASSIVE_API_KEY" in str(key["name"]))
    assert massive["required"] is True
    assert massive["status"] == "BLOCK"


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


def _data_load(**_kwargs: object) -> dict[str, object]:
    return {
        "ready": True,
        "state": "ready",
        "status_label": "Loaded",
        "blocker_count": 0,
        "warning_count": 0,
        "overall_percent": 100,
        "core_dataset_percent": 100,
        "critical_lane_percent": 100,
    }


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
