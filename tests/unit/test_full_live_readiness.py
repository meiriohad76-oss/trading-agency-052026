from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import agency.api.health as health_module
import agency.runtime.full_live_readiness as readiness_module
from agency.app import create_app
from agency.runtime.full_live_readiness import load_full_live_readiness

HTTP_OK = 200
EXPECTED_TICKER_COUNT = 2


def test_full_live_readiness_ready_for_full_cycle(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    status_path = _refresh_status_path(tmp_path, state="complete")
    monkeypatch.setattr(
        readiness_module,
        "current_usage",
        lambda: {
            "enabled": False,
            "requests_made": 0,
            "requests_remaining": None,
            "requests_remaining_label": "unlimited",
            "max_requests_per_minute_label": "unpaced",
        },
    )
    monkeypatch.setenv("MASSIVE_API_KEY", "massive-test-key")

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=_data_refresh("complete"),
        data_load_status=_data_load("ready"),
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "ready_for_full_live_cycle"
    assert payload["ready"] is True
    assert payload["tradable_ready"] is True
    assert payload["review_operational_ready"] is True
    assert payload["readiness_scope"] == "full_universe"
    assert payload["active_refresh"]["batch_id"] == "refresh"
    assert payload["coverage"]["expected_ticker_count"] == EXPECTED_TICKER_COUNT
    assert payload["provider_usage"][0]["id"] == "massive_polygon"


def test_full_live_readiness_warns_when_subscription_articles_need_login(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    status_path = _refresh_status_path(tmp_path, state="complete")
    monkeypatch.setattr(
        readiness_module,
        "current_usage",
        lambda: {
            "enabled": False,
            "requests_made": 0,
            "requests_remaining": None,
            "requests_remaining_label": "unlimited",
            "max_requests_per_minute_label": "unpaced",
        },
    )
    monkeypatch.setenv("MASSIVE_API_KEY", "massive-test-key")

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=_data_refresh("complete"),
        data_load_status=_data_load("ready"),
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(
            tmp_path,
            linked_failures=0,
            login_required=1,
        ),
    )
    email_usage = {
        str(row["id"]): row
        for row in payload["provider_usage"]
    }["subscription_email"]

    assert payload["verdict"] == "ready_for_full_live_cycle"
    assert payload["ready"] is True
    assert payload["tradable_ready"] is True
    assert email_usage["status"] == "WARN"
    assert "need login confirmation" in str(email_usage["detail"])
    assert any("need login confirmation" in str(row["reason"]) for row in payload["warnings"])


def test_full_live_readiness_ready_with_partial_lanes_is_operational(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    status_path = _refresh_status_path(tmp_path, state="complete")
    monkeypatch.setattr(
        readiness_module,
        "current_usage",
        lambda: {
            "enabled": False,
            "requests_made": 0,
            "requests_remaining": None,
            "requests_remaining_label": "unlimited",
            "max_requests_per_minute_label": "unpaced",
        },
    )
    monkeypatch.setenv("MASSIVE_API_KEY", "massive-test-key")
    data_load = _data_load("attention")
    data_load["warning_count"] = 1
    data_load["warnings"] = [
        {
            "kind": "dataset",
            "item": "stock_trades",
            "reason": "latest slices are ready; full-depth repair remains queued.",
        }
    ]

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=_data_refresh("complete"),
        data_load_status=data_load,
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "ready_with_partial_lanes"
    assert payload["ready"] is False
    assert payload["tradable_ready"] is False
    assert payload["review_operational_ready"] is True
    assert payload["state"] == "attention"


def test_full_live_readiness_keeps_tradable_with_context_only_warnings(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    status_path = _refresh_status_path(tmp_path, state="complete")
    monkeypatch.setattr(
        readiness_module,
        "current_usage",
        lambda: {
            "enabled": False,
            "requests_made": 0,
            "requests_remaining": None,
            "requests_remaining_label": "unlimited",
            "max_requests_per_minute_label": "unpaced",
        },
    )
    monkeypatch.setenv("MASSIVE_API_KEY", "massive-test-key")
    data_load = _data_load("attention")
    data_load["tradable_ready"] = True
    data_load["review_operational_ready"] = True
    data_load["warning_count"] = 4
    data_load["warnings"] = [
        {
            "kind": "dataset",
            "item": "news_rss",
            "reason": "RSS/news source-health proof is old, but headline freshness is FRESH.",
        },
        {
            "kind": "dataset",
            "item": "subscription_emails",
            "reason": "Subscription thesis source-health proof is old, but thesis freshness is FRESH.",
        },
        {
            "kind": "agent_lane",
            "item": "news",
            "reason": "news has a warning because RSS/news headlines freshness is FRESH.",
        },
        {
            "kind": "agent_lane",
            "item": "subscription_thesis",
            "reason": "subscription thesis has a warning because thesis freshness is FRESH.",
        },
    ]

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=_data_refresh("complete"),
        data_load_status=data_load,
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "ready_for_full_live_cycle"
    assert payload["ready"] is True
    assert payload["tradable_ready"] is True
    assert payload["review_operational_ready"] is True
    assert payload["warning_count"] == 4


def test_full_live_readiness_keeps_tradable_with_stale_trade_progress_warning_when_market_flow_full(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    status_path = _refresh_status_path(tmp_path, state="complete")
    monkeypatch.setattr(
        readiness_module,
        "current_usage",
        lambda: {
            "enabled": False,
            "requests_made": 0,
            "requests_remaining": None,
            "requests_remaining_label": "unlimited",
            "max_requests_per_minute_label": "unpaced",
        },
    )
    monkeypatch.setenv("MASSIVE_API_KEY", "massive-test-key")
    data_refresh = _data_refresh("complete")
    data_refresh["trade_pull"] = {
        "state": "unverified",
        "pipeline_usable_count": 1,
        "pipeline_failed_count": 0,
        "pipeline_detail": "1 ticker(s) can pass forward now.",
    }
    data_load = _data_load("attention")
    data_load["tradable_ready"] = True
    data_load["review_operational_ready"] = True
    data_load["warning_count"] = 1
    data_load["warnings"] = [
        {
            "kind": "data_refresh",
            "item": "stock_trades",
            "reason": "1 ticker(s) can pass forward now.",
        }
    ]
    data_load["market_flow_summary"] = {
        "status": "ready",
        "usable_ticker_count": 2,
        "signal_ticker_count": 2,
        "expected_ticker_count": 2,
    }

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=data_refresh,
        data_load_status=data_load,
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "ready_for_full_live_cycle"
    assert payload["ready"] is True
    assert payload["tradable_ready"] is True
    assert any(warning["item"] == "stock_trades" for warning in payload["warnings"])


def test_full_live_readiness_reports_loading(tmp_path: Path) -> None:
    status_path = _refresh_status_path(tmp_path, state="running")
    data_load = _data_load("loading")
    data_load["ready"] = False
    data_load["review_operational_ready"] = False
    data_load["tradable_ready"] = False

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=_data_refresh("running"),
        data_load_status=data_load,
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "loading"
    assert payload["ready"] is False
    assert payload["active_refresh"]["running_dataset"] == "stock_trades"
    assert payload["warning_count"] >= 1


def test_full_live_readiness_data_blockers_outrank_support_refresh_loading(
    tmp_path: Path,
) -> None:
    root = tmp_path / "refresh"
    root.mkdir()
    status_path = root / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "config": {"tickers": ["AAPL", "MSFT"]},
                "progress": {"state": "running", "current_dataset": "sec_form4"},
                "jobs": [
                    {"dataset": "sec_form4", "status": "running", "reason": "running"},
                ],
            }
        ),
        encoding="utf-8",
    )
    data_refresh = _data_refresh("running")
    data_refresh["current_dataset"] = "sec_form4"
    data_load = _data_load("blocked")
    data_load["ready"] = False
    data_load["review_operational_ready"] = False
    data_load["tradable_ready"] = False
    data_load["blocker_count"] = 2
    data_load["blockers"] = [
        {
            "kind": "dataset",
            "item": "prices_daily",
            "reason": "Daily bars are stale.",
        },
        {
            "kind": "agent_lane",
            "item": "technical_analysis",
            "reason": "technical analysis is blocked by stale daily bars.",
        },
    ]

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=data_refresh,
        data_load_status=data_load,
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "blocked"
    assert payload["state"] == "blocked"
    assert payload["readiness_scope"] == "blocked"
    assert payload["review_operational_ready"] is False
    assert any(blocker["item"] == "prices_daily" for blocker in payload["blockers"])


def test_full_live_readiness_keeps_tradable_when_support_refresh_runs_after_core_ready(
    tmp_path: Path,
) -> None:
    root = tmp_path / "refresh"
    root.mkdir()
    status_path = root / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "config": {"tickers": ["AAPL", "MSFT"]},
                "progress": {"state": "running", "current_dataset": "sec_form4"},
                "jobs": [
                    {"dataset": "sec_form4", "status": "running", "reason": "running"},
                ],
            }
        ),
        encoding="utf-8",
    )
    data_refresh = _data_refresh("running")
    data_refresh["current_dataset"] = "sec_form4"
    data_load = _data_load("ready")
    data_load["tradable_ready"] = True
    data_load["review_operational_ready"] = True

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=data_refresh,
        data_load_status=data_load,
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "ready_for_full_live_cycle"
    assert payload["ready"] is True
    assert payload["tradable_ready"] is True
    assert any(warning["item"] == "sec_form4" for warning in payload["warnings"])


def test_full_live_readiness_keeps_review_operational_while_background_refresh_runs(
    tmp_path: Path,
) -> None:
    status_path = _refresh_status_path(tmp_path, state="running")
    data_load = _data_load("attention")
    data_load["review_operational_ready"] = True
    data_load["tradable_ready"] = False

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=_data_refresh("running"),
        data_load_status=data_load,
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "ready_with_partial_lanes"
    assert payload["ready"] is False
    assert payload["tradable_ready"] is False
    assert payload["review_operational_ready"] is True
    assert any(warning["kind"] == "Refresh" for warning in payload["warnings"])


def test_full_live_readiness_blocks_failed_job_even_while_refresh_running(tmp_path: Path) -> None:
    root = tmp_path / "refresh"
    root.mkdir()
    status_path = root / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "config": {"tickers": ["AAPL", "MSFT"]},
                "progress": {"state": "running", "current_dataset": "stock_trades"},
                "jobs": [
                    {"dataset": "prices_daily", "status": "failed", "reason": "failed"},
                    {"dataset": "stock_trades", "status": "running", "reason": "running"},
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=_data_refresh("running"),
        data_load_status=_data_load("ready"),
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "blocked"
    assert payload["ready"] is False
    assert any(blocker["item"] == "failed jobs" for blocker in payload["blockers"])


def test_full_live_readiness_warns_for_support_only_failed_job_when_tradable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "refresh"
    root.mkdir()
    status_path = root / "data-refresh-status.json"
    status_path.write_text(
        json.dumps(
            {
                "config": {"tickers": ["AAPL", "MSFT"]},
                "progress": {"state": "failed", "current_dataset": "sec_form4"},
                "jobs": [
                    {"dataset": "prices_daily", "status": "passed", "reason": "complete"},
                    {"dataset": "stock_trades", "status": "passed", "reason": "complete"},
                    {"dataset": "sec_form4", "status": "failed", "reason": "timeout"},
                ],
            }
        ),
        encoding="utf-8",
    )
    data_refresh = _data_refresh("failed")
    data_refresh["current_dataset"] = "sec_form4"
    data_refresh["detail"] = "SEC Form 4 refresh failed after core lanes completed."
    data_load = _data_load("ready")
    data_load["tradable_ready"] = True
    data_load["review_operational_ready"] = True

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=data_refresh,
        data_load_status=data_load,
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "ready_with_partial_lanes"
    assert payload["ready"] is False
    assert payload["review_operational_ready"] is True
    assert not payload["blockers"]
    assert any(warning["item"] == "sec_form4" for warning in payload["warnings"])


def test_full_live_readiness_blocks_failed_refresh(tmp_path: Path) -> None:
    status_path = _refresh_status_path(tmp_path, state="failed")

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=_data_refresh("failed"),
        data_load_status=_data_load("ready"),
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "blocked"
    assert payload["ready"] is False
    assert any(blocker["kind"] == "Refresh" for blocker in payload["blockers"])


def test_full_live_readiness_blocks_planned_dry_run_refresh(tmp_path: Path) -> None:
    status_path = _refresh_status_path(tmp_path, state="planned")

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=_data_refresh("planned"),
        data_load_status=_data_load("ready"),
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "blocked"
    assert payload["ready"] is False
    assert any(blocker["item"] == "planned" for blocker in payload["blockers"])


def test_full_live_readiness_blocks_partial_stock_trade_pull(tmp_path: Path) -> None:
    status_path = _refresh_status_path(tmp_path, state="complete")
    data_refresh = _data_refresh("complete")
    data_refresh["trade_pull"] = {
        "state": "partial",
        "detail": "1 ticker-day has incomplete Massive coverage.",
    }

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=data_refresh,
        data_load_status=_data_load("ready"),
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "blocked"
    assert payload["ready"] is False
    assert any(blocker["item"] == "stock_trades" for blocker in payload["blockers"])


def test_full_live_readiness_warns_when_partial_trade_pull_has_ready_tickers(
    tmp_path: Path,
) -> None:
    status_path = _refresh_status_path(tmp_path, state="complete")
    data_refresh = _data_refresh("complete")
    data_refresh["trade_pull"] = {
        "state": "partial",
        "pipeline_ready_count": 3,
        "pipeline_failed_count": 0,
        "pipeline_detail": "3 ticker(s) can pass forward now.",
    }
    data_load = _data_load("ready")
    data_load["data_refresh"] = data_refresh

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=data_refresh,
        data_load_status=data_load,
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "ready_with_partial_lanes"
    assert payload["ready"] is False
    assert payload["tradable_ready"] is False
    assert payload["review_operational_ready"] is True
    assert any(warning["item"] == "stock_trades" for warning in payload["warnings"])


def test_full_live_readiness_warns_when_unverified_trade_pull_has_usable_tickers(
    tmp_path: Path,
) -> None:
    status_path = _refresh_status_path(tmp_path, state="complete")
    data_refresh = _data_refresh("complete")
    data_refresh["trade_pull"] = {
        "state": "unverified",
        "pipeline_usable_count": 4,
        "pipeline_failed_count": 0,
        "pipeline_detail": "4 ticker(s) have usable Massive trade slices; verification is still running.",
    }
    data_load = _data_load("attention")
    data_load["review_operational_ready"] = True
    data_load["tradable_ready"] = False

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=data_refresh,
        data_load_status=data_load,
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "ready_with_partial_lanes"
    assert payload["ready"] is False
    assert payload["tradable_ready"] is False
    assert payload["review_operational_ready"] is True
    assert any(warning["item"] == "stock_trades" for warning in payload["warnings"])


def test_full_live_readiness_blocks_unverified_trade_pull_with_no_usable_tickers(
    tmp_path: Path,
) -> None:
    status_path = _refresh_status_path(tmp_path, state="complete")
    data_refresh = _data_refresh("complete")
    data_refresh["trade_pull"] = {
        "state": "unverified",
        "pipeline_usable_count": 0,
        "pipeline_ready_count": 0,
        "detail": "Massive trade slices have not been verified for any ticker.",
    }

    payload = load_full_live_readiness(
        live_config=_live_config(),
        data_refresh=data_refresh,
        data_load_status=_data_load("ready"),
        provider_readiness=_provider_readiness(),
        refresh_status_path=status_path,
        email_ingest_path=_email_ingest_path(tmp_path, linked_failures=0),
    )

    assert payload["verdict"] == "blocked"
    assert payload["ready"] is False
    assert any(blocker["item"] == "stock_trades" for blocker in payload["blockers"])


def test_full_live_readiness_endpoint_returns_payload(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        health_module,
        "load_full_live_readiness",
        lambda **_kwargs: {
            "schema_version": "0.1.0",
            "verdict": "ready_for_full_live_cycle",
            "ready": True,
        },
    )
    client = TestClient(create_app())

    response = client.get("/status/full-live-readiness")

    assert response.status_code == HTTP_OK
    assert response.json()["verdict"] == "ready_for_full_live_cycle"


def _live_config() -> dict[str, object]:
    return {
        "ready": True,
        "provider": "massive",
        "status_label": "Ready",
        "blocker_count": 0,
        "warning_count": 0,
    }


def _provider_readiness() -> dict[str, object]:
    return {
        "ready": True,
        "blocker_count": 0,
        "warning_count": 0,
    }


def _data_refresh(state: str) -> dict[str, object]:
    return {
        "state": state,
        "status_label": "Loading" if state == "running" else "Failed" if state == "failed" else "Complete",
        "status_class": "warn" if state == "running" else "block" if state == "failed" else "pass",
        "percent_complete": 50 if state == "running" else 100,
        "completed_jobs": 1 if state == "running" else 2,
        "total_jobs": 2,
        "current_dataset": "stock_trades" if state == "running" else "None",
        "eta_label": "2m" if state == "running" else "complete",
        "detail": (
            "Data refresh is loading source datasets."
            if state == "running"
            else "Latest data refresh failed."
            if state == "failed"
            else "Latest data refresh completed."
        ),
    }


def _data_load(state: str) -> dict[str, object]:
    return {
        "ready": True,
        "state": state,
        "overall_percent": 100,
        "core_dataset_percent": 100,
        "critical_lane_percent": 100,
        "expected_ticker_count": 2,
        "evidence_pack_count": 2,
        "signal_count": 12,
        "cycle_id": "cycle-1",
        "as_of": "2026-05-11",
        "blocker_count": 0,
        "warning_count": 0,
        "blockers": [],
        "warnings": [],
        "datasets": [
            {"dataset": "sec_company_facts", "status": "ready", "detail": "ready"},
            {"dataset": "sec_form4", "status": "ready", "detail": "ready"},
            {"dataset": "sec_13f", "status": "ready", "detail": "ready"},
        ],
    }


def _refresh_status_path(tmp_path: Path, *, state: str) -> Path:
    root = tmp_path / "refresh"
    root.mkdir()
    path = root / "data-refresh-status.json"
    path.write_text(
        json.dumps(
            {
                "config": {"tickers": ["AAPL", "MSFT"]},
                "progress": {
                    "state": state,
                    "current_dataset": "stock_trades" if state == "running" else None,
                },
                "jobs": [
                    {"dataset": "prices_daily", "status": "passed", "reason": "complete"},
                    {
                        "dataset": "stock_trades",
                        "status": "running"
                        if state == "running"
                        else "failed"
                        if state == "failed"
                        else "passed",
                        "reason": "refresh command running"
                        if state == "running"
                        else "refresh command failed"
                        if state == "failed"
                        else "complete",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _email_ingest_path(
    tmp_path: Path,
    *,
    linked_failures: int,
    login_required: int = 0,
    unavailable: int = 0,
) -> Path:
    path = tmp_path / "subscription-email-ingest.json"
    path.write_text(
        json.dumps(
            {
                "processed_emails": 2,
                "mode": "gmail",
                "verdict": "ready_for_research_batch",
                "linked_content": {
                    "succeeded": 1,
                    "failed": linked_failures,
                    "login_required": login_required,
                    "unavailable": unavailable,
                },
                "mailbox_sync": {"mode": "gmail"},
            }
        ),
        encoding="utf-8",
    )
    return path
