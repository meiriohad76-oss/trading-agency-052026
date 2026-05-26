from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import agency.api.health as health_module
import agency.dashboard as dashboard_module
import agency.services.leveraged_alternatives as leveraged_module
import agency.views._shared as shared_module
import agency.views.candidates as candidates_module
import agency.views.command as command_module
import agency.views.execution as execution_module
import agency.views.final_selection as final_selection_module
import agency.views.market_regime as market_regime_module
import agency.views.portfolio as portfolio_module
import agency.views.signals as signals_module
from agency.api.health import runtime_data_source_status
from agency.app import create_app
from agency.dashboard import (
    broker_status_view,
    candidate_decision_brief,
    candidate_detail_report_rows,
    candidate_detail_summary,
    candidate_email_evidence,
    candidate_email_evidence_with_judgement,
    candidate_news_evidence,
    candidate_review_summary,
    candidate_rows,
    command_status_overview,
    command_summary,
    data_load_status_view,
    data_refresh_progress_view,
    execution_preview_rows,
    final_selection_context,
    final_selection_rows,
    final_selection_summary,
    human_review_events_for_reports,
    learning_summary,
    live_config_view,
    paper_review_progress,
    paper_review_queue,
    paper_review_status_from_runtime,
    policy_sections,
    portfolio_monitor_summary,
    provider_readiness_view,
    readiness_view,
    risk_decision_rows,
    risk_summary,
    signal_dashboard_rows,
    signal_dashboard_summary,
    signal_lane_rows,
    source_status_rows,
    timeline_rows,
)
from agency.runtime import artifact_fallbacks
from agency.services import (
    LlmReviewResult,
    PortfolioPolicy,
    build_evidence_pack,
    build_execution_preview,
    build_final_selection,
    build_learning_outcome,
    build_order_approval_event,
    build_portfolio_monitor,
    build_risk_decision,
    build_signal_result,
    selection_report_hash,
)
from agency.services.selection_events import build_llm_lifecycle_event

HTTP_OK = 200
HTTP_ACCEPTED = 202
HTTP_NOT_FOUND = 404
HTTP_SEE_OTHER = 303
EXPECTED_SOURCE_COUNT = 2
EXPECTED_CONFIRMED_SIGNAL_COUNT = 2
FULL_RELIABILITY_PERCENT = 100
EXPECTED_TIMELINE_LIMIT = 50
EXPECTED_REVIEW_QUEUE_COUNT = 4
EXPECTED_REVIEWED_COUNT = 3
EXPECTED_EMAIL_EVENT_COUNT = 2
EXPECTED_BRIEF_POINT_COUNT = 4
EXPECTED_FINAL_SELECTION_REPORT_LIMIT = 1000


@pytest.fixture(autouse=True)
def _disable_runtime_artifact_fallback_by_default(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("AGENCY_RUNTIME_ARTIFACT_FALLBACK", "false")


async def test_shared_live_source_health_empty_reader_returns_unavailable_monitor() -> None:
    async def empty_reader() -> list[dict[str, object]]:
        return []

    rows = await shared_module.live_runtime_source_health_rows(reader=empty_reader)

    assert rows[0]["source"] == "source-health-monitor"
    assert rows[0]["status"] == "UNAVAILABLE"
    assert "returned no monitored provider rows" in str(rows[0]["notes"][0])


def test_runtime_artifact_fallback_is_disabled_by_default(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENCY_RUNTIME_ARTIFACT_FALLBACK", raising=False)

    assert artifact_fallbacks.artifact_fallback_enabled() is False


def test_shared_dashboard_data_health_bounds_progress_and_coverage() -> None:
    health = shared_module.dashboard_data_health(
        "Signals dashboard",
        data_load_status={
            "overall_percent": 133,
            "cycle_id": "live-ready-20260516",
            "health_monitor": {
                "status_label": "Live",
                "status_class": "pass",
                "live": True,
                "reliable": True,
                "row_count": 1,
                "latest_checked_at": "2026-05-16T12:00:00+00:00",
            },
            "datasets": [
                {
                    "dataset": "prices_daily",
                    "label": "Daily bars",
                    "status_label": "Fresh",
                    "status_class": "pass",
                    "coverage_pct": 140,
                    "loaded_ticker_count": 2,
                    "expected_ticker_count": 2,
                }
            ],
            "lanes": [],
        },
        datasets=("prices_daily",),
    )

    dataset_row = next(row for row in health["rows"] if row["kind"] == "Dataset")
    assert health["overall_percent"] == 100
    assert health["progress_style"] == "width: 100%"
    assert dataset_row["coverage_label"] == "100% / 2/2 tickers loaded"


def test_shared_dashboard_data_health_humanizes_monitor_seconds() -> None:
    health = shared_module.dashboard_data_health(
        "Command dashboard",
        data_load_status={
            "overall_percent": 97,
            "cycle_id": "live-ready-20260516",
            "health_monitor": {
                "status_label": "Health Monitor Needs Refresh",
                "status_class": "block",
                "live": False,
                "reliable": False,
                "row_count": 7,
                "latest_checked_at": "2026-05-16T09:43:59+00:00",
                "max_age_seconds": 27837,
                "detail": (
                    "subscription-email-thesis source-health is older than its SLA "
                    "(27837s > 1800s)."
                ),
            },
            "datasets": [],
            "lanes": [],
        },
    )

    monitor_row = next(row for row in health["rows"] if row["kind"] == "Health monitor")
    assert monitor_row["freshness_label"] == "7h 43m max age"
    assert "27837s" not in monitor_row["detail"]
    assert "7h 43m" in monitor_row["detail"]
    assert "30m" in monitor_row["detail"]


def test_shared_dashboard_data_health_formats_timestamp_labels() -> None:
    health = shared_module.dashboard_data_health(
        "Signals dashboard",
        data_load_status={
            "overall_percent": 100,
            "as_of": "2026-05-16T12:34:56+00:00",
            "cycle_id": "live-ready-20260516",
            "health_monitor": {
                "status_label": "Live",
                "status_class": "pass",
                "live": True,
                "reliable": True,
                "row_count": 1,
                "latest_checked_at": "2026-05-16T12:35:01+00:00",
            },
            "datasets": [
                {
                    "dataset": "prices_daily",
                    "label": "Daily bars",
                    "status_label": "Fresh",
                    "status_class": "pass",
                    "source_freshness": "FRESH",
                    "coverage_pct": 100,
                    "loaded_ticker_count": 2,
                    "expected_ticker_count": 2,
                    "source_last_success_at": "2026-05-16T12:33:00+00:00",
                    "coverage_as_of": "2026-05-16T00:00:00+00:00",
                    "detail": (
                        "Daily bars fetched at 2026-05-16T12:33:00+00:00 "
                        "and checked at 2026-05-16T12:35:01+00:00."
                    ),
                }
            ],
            "lanes": [],
        },
        datasets=("prices_daily",),
    )

    summary = {item["label"]: item["value"] for item in health["summary_items"]}
    dataset_row = next(row for row in health["rows"] if row["kind"] == "Dataset")
    assert summary["As of"] == "2026-05-16 12:34 UTC"
    assert summary["Last verified"] == "2026-05-16 12:35 UTC"
    assert dataset_row["last_update"] == "2026-05-16 12:33 UTC"
    assert dataset_row["freshness_label"] == "FRESH; coverage 2026-05-16 00:00 UTC"
    assert "2026-05-16 12:33 UTC" in dataset_row["detail"]
    assert "T12:" not in str(summary)
    assert "+00:00" not in str(dataset_row)


def test_shared_dashboard_data_health_labels_old_monitor_as_health_proof_refresh() -> None:
    health = shared_module.dashboard_data_health(
        "Command dashboard",
        data_load_status={
            "overall_percent": 97,
            "cycle_id": "live-ready-20260516",
            "status_label": "Loaded With Gaps",
            "mode_label": "Full-Universe Tradable",
            "health_monitor": {
                "status_label": "Health Monitor Needs Refresh",
                "status_class": "block",
                "live": False,
                "reliable": False,
                "row_count": 7,
                "latest_checked_at": "2026-05-16T09:43:59+00:00",
                "max_age_seconds": 27837,
                "detail": (
                    "daily-market-bars source-health is older than its SLA "
                    "(27837s > 1800s)."
                ),
            },
            "datasets": [
                {
                    "dataset": "prices_daily",
                    "label": "Daily OHLCV bars",
                    "status_label": "Ready",
                    "status_class": "pass",
                    "source_freshness": "FRESH",
                    "coverage_pct": 100,
                    "loaded_ticker_count": 168,
                    "expected_ticker_count": 168,
                    "detail": "Daily bars are current.",
                }
            ],
            "lanes": [],
        },
        datasets=("prices_daily",),
    )

    assert health["status_label"] == "Health proof needs refresh"
    assert "health proof needs refresh" in str(health["headline"]).lower()
    assert "stale" not in str(health).lower()
    assert "Last verified" in {item["label"] for item in health["summary_items"]}
    assert "tooltip" in health

def test_shared_dashboard_data_health_treats_context_monitor_age_as_proof_refresh() -> None:
    health = shared_module.dashboard_data_health(
        "Portfolio monitor dashboard",
        data_load_status={
            "overall_percent": 97,
            "cycle_id": "live-ready-20260516",
            "status_label": "Loaded With Gaps",
            "health_monitor": {
                "status": "context_stale",
                "status_label": "Context Health Check Needs Refresh",
                "status_class": "warn",
                "live": True,
                "reliable": True,
                "row_count": 7,
                "latest_checked_at": "2026-05-16T09:43:59+00:00",
                "max_age_seconds": 1800,
                "detail": "Context source-health proof needs refresh.",
            },
            "datasets": [],
            "lanes": [],
        },
    )

    assert health["status_label"] == "Health proof needs refresh"
    assert health["monitor_label"] == "Health proof needs refresh"


def test_shared_dashboard_data_health_exposes_lane_state_rows() -> None:
    health = shared_module.dashboard_data_health(
        "Portfolio monitor dashboard",
        data_load_status={
            "overall_percent": 88,
            "cycle_id": "live-ready-20260516",
            "health_monitor": {
                "status_label": "Live",
                "status_class": "pass",
                "live": True,
                "reliable": True,
                "row_count": 7,
                "latest_checked_at": "2026-05-16T09:43:59+00:00",
            },
            "datasets": [],
            "lanes": [],
            "lane_states": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "status_label": "Data is still loading",
                    "status_class": "warn",
                    "progress_label": "6/29 ticker-days",
                    "latest_as_of": "2026-05-22T13:25:29+00:00",
                    "detail": "Live trade slices are running for APP.",
                    "recommended_action": "Wait for the lane to finish.",
                }
            ],
        },
    )

    assert health["lane_state_rows"][0]["lane_id"] == "massive_live_trade_slices"
    assert health["lane_state_rows"][0]["progress_label"] == "6/29 ticker-days"
    assert health["lane_state_rows"][0]["latest_as_of"] == "2026-05-22 13:25 UTC"


def test_shared_dashboard_data_health_offers_trade_lane_refresh_for_old_massive_monitor() -> None:
    health = shared_module.dashboard_data_health(
        "Final selection dashboard",
        data_load_status={
            "overall_percent": 56,
            "cycle_id": "live-pit-current",
            "health_monitor": {
                "status_label": "Health Monitor Needs Refresh",
                "status_class": "block",
                "live": False,
                "reliable": False,
                "row_count": 21,
                "latest_checked_at": "2026-05-20T20:00:00+00:00",
                "max_age_seconds": 900,
                "detail": (
                    "massive-stock-trades source-health is older than its SLA "
                    "(900s > 600s)."
                ),
            },
            "datasets": [],
            "lanes": [],
        },
    )

    assert health["status_label"] == "Health proof needs refresh"
    assert "stale" not in str(health).lower()
    assert health["action_buttons"][0] == {
        "label": "Refresh Live Trade Slices",
        "action": "/scheduler/massive-lanes/massive_live_trade_slices/refresh",
        "method": "post",
        "detail": (
            "Runs the trade-aware Massive live trade slice refresh, then updates "
            "runtime health proof."
        ),
    }
    assert health["action_buttons"][1]["label"] == "Open Refresh Queue"


def test_shared_dashboard_data_health_recommends_refresh_for_analyzed_old_data() -> None:
    health = shared_module.dashboard_data_health(
        "Signals dashboard",
        data_load_status={
            "overall_percent": 82,
            "cycle_id": "live-pit-current",
            "health_monitor": {
                "status_label": "Live Health Monitor",
                "status_class": "pass",
                "live": True,
                "reliable": True,
                "row_count": 21,
                "latest_checked_at": "2026-05-20T20:00:00+00:00",
            },
            "datasets": [
                {
                    "dataset": "massive_live_trade_slices",
                    "label": "Live Trade Slices",
                    "status_label": "Analyzed but out of policy",
                    "status_class": "warn",
                    "source_freshness": "STALE",
                    "coverage_pct": 95,
                    "loaded_ticker_count": 160,
                    "expected_ticker_count": 168,
                    "source_last_success_at": "2026-05-20T19:40:00+00:00",
                    "detail": "Live trade data was analyzed, but the result is STALE.",
                }
            ],
            "lanes": [],
        },
        datasets=("massive_live_trade_slices",),
    )

    assert health["status_label"] == "Refresh recommended"
    assert "analyzed data" in str(health["meaning"]).lower()
    assert health["action_buttons"][0]["label"] == "Refresh Live Trade Slices"
    assert "stale" not in str(health).lower()


def test_shared_dashboard_data_health_identifies_available_data_waiting_for_analysis() -> None:
    health = shared_module.dashboard_data_health(
        "Technical analysis dashboard",
        data_load_status={
            "overall_percent": 76,
            "cycle_id": "live-pit-current",
            "health_monitor": {
                "status_label": "Live Health Monitor",
                "status_class": "pass",
                "live": True,
                "reliable": True,
                "row_count": 21,
                "latest_checked_at": "2026-05-20T20:00:00+00:00",
            },
            "datasets": [],
            "lanes": [
                {
                    "lane": "technical_analysis",
                    "label": "Technical Analysis",
                    "status_label": "No analysis rows",
                    "status_class": "block",
                    "source_freshness": "FRESH",
                    "coverage_pct": 0,
                    "produced_count": 0,
                    "expected_count": 168,
                    "source_last_success_at": "2026-05-20T19:58:00+00:00",
                    "detail": "Source data is available, but the agent has produced 0 rows.",
                }
            ],
        },
        lanes=("technical_analysis",),
    )

    assert health["status_label"] == "Waiting for analysis"
    assert "agent has not produced analysis" in str(health["meaning"]).lower()
    assert "Run the Technical Analysis lane" in str(health["recommended_action"])
    assert "stale" not in str(health).lower()


def test_shared_dashboard_data_health_identifies_unavailable_data_plainly() -> None:
    health = shared_module.dashboard_data_health(
        "Candidate dashboard",
        data_load_status={
            "overall_percent": 50,
            "cycle_id": "live-pit-current",
            "health_monitor": {
                "status_label": "Live Health Monitor",
                "status_class": "pass",
                "live": True,
                "reliable": True,
                "row_count": 21,
                "latest_checked_at": "2026-05-20T20:00:00+00:00",
            },
            "datasets": [
                {
                    "dataset": "subscription_emails",
                    "label": "Subscription Email Thesis",
                    "status_label": "Unavailable",
                    "status_class": "block",
                    "source_freshness": "UNAVAILABLE",
                    "coverage_pct": 0,
                    "detail": "The email article source is unavailable because login is required.",
                }
            ],
            "lanes": [],
        },
        datasets=("subscription_emails",),
    )

    assert health["status_label"] == "Data unavailable"
    assert "problem reaching or loading" in str(health["meaning"]).lower()
    assert "login" in str(health["primary_blocker_detail"]).lower()
    assert "stale" not in str(health).lower()


def test_shared_human_review_index_ignores_order_approval_events() -> None:
    research_review = {
        "cycle_id": "cycle-live",
        "ticker": "AMZN",
        "event_type": "HUMAN_REVIEW",
        "status": "PASSED",
        "reason": "paper review approved",
        "event_time": "2026-05-22T16:13:22Z",
        "payload": {
            "as_of": "2026-05-22T00:00:00+00:00",
            "review_decision": "APPROVE",
        },
    }
    order_approval = {
        "cycle_id": "cycle-live",
        "ticker": "AMZN",
        "event_type": "ORDER_APPROVAL",
        "status": "PASSED",
        "reason": "paper order intent approved",
        "event_time": "2026-05-22T16:15:00Z",
        "payload": {
            "as_of": "2026-05-22T00:00:00+00:00",
            "approval_type": "ORDER_APPROVAL",
            "order_intent_hash": "a" * 64,
        },
    }

    indexed = shared_module._human_review_index([order_approval, research_review])
    summary = shared_module._human_review_summary(
        indexed[("cycle-live", "AMZN", "2026-05-22T00:00:00+00:00")]
    )

    assert summary["decision"] == "Approve"
    assert summary["reason"] == "paper review approved"


def test_shared_dashboard_data_health_treats_partial_live_trades_as_usable() -> None:
    health = shared_module.dashboard_data_health(
        "AMZN candidate brief",
        data_load_status={
            "overall_percent": 65,
            "cycle_id": "live-pit-current",
            "health_monitor": {
                "status_label": "Live Health Monitor",
                "status_class": "pass",
                "live": True,
                "reliable": True,
                "row_count": 7,
                "latest_checked_at": "2026-05-22T16:06:00+00:00",
            },
            "datasets": [
                {
                    "dataset": "stock_trades",
                    "label": "Massive trade prints",
                    "status_label": "Attention",
                    "status_class": "warn",
                    "source_freshness": "PARTIAL",
                    "coverage_pct": 18,
                    "usable_ticker_count": 28,
                    "expected_ticker_count": 168,
                    "row_count": 224245,
                    "detail": (
                        "massive_live_trade_slices lane is DEGRADED / PARTIAL; "
                        "manifest checked 3m 58s ago; 28/30 ticker(s) usable, "
                        "2 missing/partial, 28 partial slices, 0 failed."
                    ),
                }
            ],
            "lanes": [],
        },
        datasets=("stock_trades",),
    )

    assert health["status_label"] == "Usable With Gaps"
    assert health["primary_blocker"] == "Massive trade prints - Attention"
    assert "problem reaching or loading" not in str(health["meaning"]).lower()
    assert "Data unavailable" not in str(health)


def test_shared_dashboard_data_health_offers_refresh_queue_for_warning_issue() -> None:
    health = shared_module.dashboard_data_health(
        "Candidate brief",
        data_load_status={
            "overall_percent": 88,
            "cycle_id": "live-pit-current",
            "health_monitor": {
                "status_label": "Live Health Monitor",
                "status_class": "pass",
                "live": True,
                "reliable": True,
                "row_count": 21,
                "latest_checked_at": "2026-05-20T20:00:00+00:00",
            },
            "datasets": [
                {
                    "dataset": "subscription_emails",
                    "label": "Subscription Emails",
                    "status_label": "Context Health Needs Refresh",
                    "status_class": "warn",
                    "source_freshness": "AGING",
                    "coverage_pct": 70,
                    "detail": "subscription-email-thesis source-health is older than its SLA.",
                }
            ],
            "lanes": [],
        },
        datasets=("subscription_emails",),
    )

    assert health["status_label"] == "Refresh recommended"
    assert "stale" not in str(health).lower()
    assert health["action_buttons"] == [
        {
            "label": "Open Refresh Queue",
            "href": "/#scheduler-heading",
            "method": "get",
            "detail": "Opens Command at the scheduler and lane refresh controls.",
        }
    ]


def test_shared_dashboard_data_health_explains_blocked_lanes_actionably() -> None:
    health = shared_module.dashboard_data_health(
        "CPRT candidate brief",
        data_load_status={
            "overall_percent": 90,
            "as_of": "2026-05-18T13:55:00+00:00",
            "cycle_id": "live-cycle-20260518",
            "status_label": "Loaded With Gaps",
            "health_monitor": {
                "status_label": "Live",
                "status_class": "pass",
                "live": True,
                "reliable": True,
                "row_count": 11,
                "latest_checked_at": "2026-05-18T13:56:00+00:00",
                "max_age_seconds": 60,
            },
            "datasets": [
                {
                    "dataset": "massive_daily_bars",
                    "label": "Massive Daily Bars",
                    "status_label": "Partial",
                    "status_class": "warn",
                    "source_freshness": "FRESH",
                    "coverage_pct": 60,
                    "loaded_ticker_count": 100,
                    "expected_ticker_count": 168,
                    "detail": "Daily bars verified coverage 100/168 active tickers.",
                }
            ],
            "lanes": [
                {
                    "lane": "abnormal_volume",
                    "label": "Abnormal Volume",
                    "status_label": "Blocked",
                    "status_class": "block",
                    "source_freshness": "FRESH",
                    "coverage_pct": 100,
                    "produced_count": 168,
                    "expected_count": 168,
                    "source_dataset": "massive_daily_bars",
                    "detail": (
                        "Blocked because Massive Daily Bars only verified 100/168 "
                        "active tickers."
                    ),
                }
            ],
        },
        datasets=("massive_daily_bars",),
        lanes=("abnormal_volume",),
    )

    summary = {item["label"]: item["value"] for item in health["summary_items"]}
    lane_row = next(row for row in health["rows"] if row["kind"] == "Agent lane")

    assert health["meaning"].startswith("This dashboard is not execution-ready")
    assert "Refresh" in health["recommended_action"]
    assert "Abnormal Volume" in health["primary_blocker"]
    assert "Provider/cache" not in health["detail"]
    assert "Runtime mode" not in health["detail"]
    assert "Cycle:" not in health["detail"]
    assert summary["Decision status"] == "Blocked"
    assert "Abnormal Volume" in summary["Blocking reason"]
    assert summary["Last verified"] == "2026-05-18 13:56 UTC"
    assert "refresh" in summary["Next action"].lower()
    assert lane_row["blocking_reason"].startswith("Blocked because")
    assert "Refresh" in lane_row["recommended_action"]
    assert "why_it_matters" in lane_row
    assert "diagnostic_detail" in lane_row


EXPECTED_SIGNALS_REPORT_LIMIT = 300
EXPECTED_SIGNALS_RENDER_LIMIT = 30
EXPECTED_LATEST_CYCLE_REPORT_COUNT = 2
EXPECTED_ALL_SELECTION_REPORT_COUNT = 3
EXPECTED_HISTORICAL_SELECTION_REPORT_COUNT = 1
EXPECTED_SUMMARY_HISTORICAL_COUNT = 2
EXPECTED_SIGNAL_DASHBOARD_ROW_COUNT = 3
EXPECTED_SIGNAL_CONTEXT_REPORT_COUNT = 60


def test_health_endpoint_reports_service_status() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == HTTP_OK
    assert response.json() == {"status": "ok", "service": "trading-agency-v3"}


def test_dashboard_renders_status_overview(monkeypatch: MonkeyPatch) -> None:
    async def fake_reports(*, limit: int = 50) -> list[dict[str, object]]:
        del limit
        return []

    async def fake_sources() -> list[dict[str, object]]:
        checked_at = datetime.now(UTC).isoformat()
        return [
            {
                "schema_version": "0.1.0",
                "source": source,
                "source_tier": "MARKET_DATA",
                "status": "HEALTHY",
                "checked_at": checked_at,
                "freshness": "FRESH",
                "last_success_at": checked_at,
                "observed_lag_seconds": 1,
                "error_count": 0,
                "reliability_score": 1.0,
                "rate_limit_reset_at": None,
                "notes": [],
            }
            for source in ("daily-market-bars", "massive-stock-trades")
        ]

    async def fake_risks(*, limit: int = 50) -> list[dict[str, object]]:
        del limit
        return []

    monkeypatch.setattr(command_module, "_dashboard_selection_reports", fake_reports)
    monkeypatch.setattr(command_module, "runtime_data_source_status", fake_sources)
    monkeypatch.setattr(command_module, "_dashboard_risk_decisions", fake_risks)

    client = TestClient(create_app())

    root_response = client.get("/")
    response = client.get("/command")

    assert root_response.status_code == HTTP_OK
    assert "Pre-Flight Cockpit" in root_response.text
    assert response.status_code == HTTP_OK
    assert "Command" in response.text
    assert "Paper trading" in response.text
    assert "Candidates" in response.text
    assert "Agency Readiness Mode" in response.text
    assert "Live Config" in response.text
    assert "Provider Readiness" in response.text
    assert "Agency Data Readiness" in response.text
    assert "Automation &amp; Refresh Queue" in response.text
    assert "Massive Data Lanes" in response.text
    assert "Execution-Critical Ready" in response.text
    assert "Execution-Critical Needs Refresh" in response.text
    assert "Support / Context Due" in response.text
    assert "Research / Disabled / Not Entitled" in response.text
    assert "Trading Freshness Gate" in response.text
    assert "Live-Critical Due" in response.text
    assert "Support Due" in response.text
    assert "Repair Due" in response.text
    assert "Review Operational" in response.text
    assert "Tradable Ready" in response.text
    assert "Live Trade Slice Coverage" in response.text
    assert "operator-briefing" in response.text
    assert "Trade eligibility" in response.text
    assert "What to do now" in response.text
    assert "Provider Connections" in response.text
    assert "Credential readiness" in response.text
    assert "not a freshness or connectivity proof" in response.text
    assert "Next Action" in response.text
    assert "Secrets" in response.text
    assert "Latest Cycle Review Readiness" in response.text
    assert "persisted selection reports, risk decisions, and source-health proof" in response.text
    assert "Broker Config" not in response.text
    assert "Review Queue" in response.text
    assert "System status" in response.text
    assert "Data readiness" in response.text
    assert "Scheduler" in response.text
    assert "Lane Refresh" in response.text
    assert "Configuration readiness" in response.text
    assert "Runtime Signals" in response.text
    assert "Next Action" in response.text
    assert "Agency Process Health" in response.text
    assert "Agency Readiness Mode" in response.text
    assert "Review data sources" in response.text
    assert "Source Health" in response.text
    assert "No reviewable paper candidates" in response.text
    assert "No candidates yet" in response.text
    assert "SelectionReport" in response.text


def test_final_selection_page_renders_empty_state() -> None:
    client = TestClient(create_app())

    response = client.get("/final-selection")

    assert response.status_code == HTTP_OK
    assert "Final Selection" in response.text
    assert "No final selection reports yet" in response.text
    assert "Read-only" in response.text


def test_final_selection_route_preserves_requested_focus(
    monkeypatch: MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    async def fake_final_selection_context(
        *,
        focus_ticker: str | None = None,
    ) -> dict[str, object]:
        seen["focus_ticker"] = focus_ticker
        return {
            "data_health": None,
            "final_rows": [],
            "actionable_rows": [],
            "watch_rows": [],
            "no_trade_rows": [],
            "blocked_rows": [],
            "trace_rows": [],
            "focused_ticker": focus_ticker or "",
            "summary": final_selection_summary([], all_report_count=0, cycle_id="cycle-test"),
        }

    monkeypatch.setattr(dashboard_module, "final_selection_context", fake_final_selection_context)

    response = TestClient(create_app()).get("/final-selection?ticker=pltr")

    assert response.status_code == HTTP_OK
    assert seen["focus_ticker"] == "PLTR"
    assert "PLTR candidate is not in the latest final-selection cycle" in response.text
    assert "Show full candidate queue" in response.text

def test_candidate_return_context_preserves_execution_review_origin() -> None:
    context = candidates_module._candidate_return_context("pltr", "execution-preview")

    assert context == {
        "label": "Back to execution review",
        "href": "/execution-preview?ticker=PLTR#focused-preview-PLTR",
    }


def test_final_selection_review_actions_return_to_focused_queue() -> None:
    action = candidates_module._review_action_url(
        ticker="PLTR",
        cycle_id="cycle-1",
        as_of="2026-05-07T09:30:00Z",
        decision="DEFER",
        return_to="final-selection",
    )
    redirect = candidates_module._candidate_review_redirect_url(
        ticker="pltr",
        decision="DEFER",
        return_to="final-selection",
    )

    assert "return_to=final-selection" in action
    assert redirect == "/final-selection?ticker=PLTR#candidate-PLTR"


async def test_final_selection_focused_routes_do_not_reuse_other_ticker_cache(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str | None] = []

    async def fake_final_selection_context(
        *,
        focus_ticker: str | None = None,
    ) -> dict[str, object]:
        calls.append(focus_ticker)
        ticker = str(focus_ticker or "FULL").upper()
        return {
            "final_rows": [
                {
                    "ticker": ticker,
                    "action": "WATCH",
                    "gate_status": "PASS",
                    "human_review_decision": "Pending",
                    "review_next_step": f"Review {ticker}.",
                    "action_class": "pass",
                }
            ],
            "focused_ticker": ticker if focus_ticker else "",
            "focused_final_selection": {},
        }

    monkeypatch.setattr(dashboard_module, "final_selection_context", fake_final_selection_context)
    dashboard_module._clear_final_selection_route_cache()

    first = await dashboard_module._final_selection_route_context(focus_ticker="AAPL")
    second = await dashboard_module._final_selection_route_context(focus_ticker="MSFT")

    assert calls == ["AAPL", "MSFT"]
    assert first["focused_final_selection"]["ticker"] == "AAPL"
    assert first["focused_final_selection"]["found"] is True
    assert second["focused_final_selection"]["ticker"] == "MSFT"
    assert second["focused_final_selection"]["found"] is True


async def test_command_dashboard_route_context_shares_inflight_build(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = 0

    async def fake_dashboard_context() -> dict[str, object]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return {"call": calls}

    monkeypatch.setattr(dashboard_module, "dashboard_context", fake_dashboard_context)
    dashboard_module._clear_command_dashboard_route_cache()

    first, second = await asyncio.gather(
        dashboard_module._command_dashboard_route_context(),
        dashboard_module._command_dashboard_route_context(),
    )

    assert calls == 1
    assert first == {"call": 1}
    assert second == {"call": 1}


def test_execution_status_row_uses_operator_refresh_language() -> None:
    row = dashboard_module._execution_preview_status_row(
        {
            "cycle_id": "cycle-1",
            "ticker": "PLTR",
            "as_of": "2026-05-07T09:30:00Z",
            "preview_state": "DISABLED",
            "side": "NONE",
            "risk_decision": "WARN",
            "submit_enabled": False,
            "order_approval_available": False,
            "submit_blocker": "critical evidence freshness is STALE",
            "paper_promotion_status_label": "Stale Evidence",
            "paper_promotion_reasons": ["critical evidence freshness is STALE."],
            "order_intent_hash_label": "",
            "order_value_label": "No paper order",
            "approval_label": "Research approved",
            "execution_state": "NONE",
            "execution_status_label": "No broker action",
            "execution_status_class": "neutral",
            "execution_reason": "",
            "execution_event_time": "",
            "execution_event_time_label": "",
            "client_order_id": "",
            "filled_qty": None,
            "filled_avg_price": None,
            "submission_confirmation_label": "",
            "next_step": "Wait until stale evidence is refreshed.",
        }
    )

    assert "stale" not in json.dumps(row).lower()
    assert "needs refresh" in json.dumps(row).lower()


def test_signals_page_renders_empty_state() -> None:
    client = TestClient(create_app())

    response = client.get("/signals")

    assert response.status_code == HTTP_OK
    assert "Signals" in response.text
    assert "Lane Health" in response.text
    assert "Signal Rows" in response.text
    assert "Inspect" in response.text
    assert "No signal rows are available for the latest cycle" in response.text


def test_market_regime_page_renders_snapshot(monkeypatch: MonkeyPatch) -> None:
    def fake_snapshot() -> dict[str, object]:
        return _market_regime_snapshot()

    monkeypatch.setattr(market_regime_module, "load_market_regime_snapshot", fake_snapshot)
    client = TestClient(create_app())

    response = client.get("/market-regime")

    assert response.status_code == HTTP_OK
    assert "Universe &amp; Market Regime" in response.text
    assert "Market Map" in response.text
    assert "Sector Leadership" in response.text
    assert "How to use this" in response.text


def test_universe_route_redirects_to_market_regime() -> None:
    client = TestClient(create_app())

    response = client.get("/universe", follow_redirects=False)

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"] == "/market-regime"


def test_risk_and_execution_pages_render_runtime_states() -> None:
    client = TestClient(create_app())

    risk_response = client.get("/risk")
    execution_response = client.get("/execution-preview")

    assert risk_response.status_code == HTTP_OK
    assert "Risk Decisions" in risk_response.text
    assert "No risk decisions yet" in risk_response.text
    assert execution_response.status_code == HTTP_OK
    assert "No execution previews yet" in execution_response.text
    assert "Paper broker" in execution_response.text
    assert "Leveraged Alternative Advisor" in execution_response.text


def test_execution_preview_status_endpoint_summarizes_orderability(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_execution_preview_context() -> dict[str, object]:
        return {
            "summary": {
                "preview_count": 2,
                "ready_count": 1,
                "blocked_count": 0,
                "disabled_count": 1,
                "submit_ready_count": 1,
                "submit_gate_open": True,
                "submit_gate_label": "Open",
                "headline": "1 orderable paper previews are ready.",
                "detail": "Paper submit gate is open.",
            },
            "preview_rows": [
                {
                    "cycle_id": "cycle-1",
                    "ticker": "AAPL",
                    "as_of": "2026-05-19T00:00:00+00:00",
                    "preview_state": "READY",
                    "side": "BUY",
                    "risk_decision": "ALLOW",
                    "submit_enabled": True,
                    "order_approval_available": False,
                    "submit_blocker": "",
                    "paper_promotion_status_label": "Promoted",
                    "paper_promotion_reasons": [],
                    "order_intent_hash_label": "abc123",
                    "order_value_label": "$1,000.00",
                    "approval_label": "Approved",
                    "next_step": "Submit the approved paper order.",
                },
                {
                    "cycle_id": "cycle-1",
                    "ticker": "MSFT",
                    "as_of": "2026-05-19T00:00:00+00:00",
                    "preview_state": "DISABLED",
                    "side": "NONE",
                    "risk_decision": "WARN",
                    "submit_enabled": False,
                    "order_approval_available": False,
                    "submit_blocker": "review-only action",
                    "paper_promotion_status_label": "Blocked checks",
                    "paper_promotion_reasons": ["confirmed signal count 1 is below required 2."],
                    "order_intent_hash_label": "def456",
                    "order_value_label": "No paper order",
                    "approval_label": "Needs research review",
                    "next_step": "Wait for blocked checks to clear.",
                },
            ],
            "execution_freshness_gate": {
                "ready": True,
                "status_label": "Ready",
                "status_class": "pass",
                "detail": "Broker and critical source freshness passed.",
            },
        }

    monkeypatch.setattr(
        dashboard_module,
        "execution_preview_context",
        fake_execution_preview_context,
    )
    client = TestClient(create_app())

    response = client.get("/status/execution-preview")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["ready"] is True
    assert payload["cycle_id"] == "cycle-1"
    assert payload["ready_count"] == 1
    assert payload["submit_ready_count"] == 1
    assert payload["order_approval_available_count"] == 0
    assert payload["rows"][0]["ticker"] == "AAPL"
    assert payload["blockers"][0]["ticker"] == "MSFT"


def test_portfolio_and_learning_pages_render_empty_states() -> None:
    client = TestClient(create_app())

    portfolio_response = client.get("/portfolio-monitor")
    learning_response = client.get("/learning")

    assert portfolio_response.status_code == HTTP_OK
    assert "Portfolio Monitor" in portfolio_response.text
    assert "Portfolio Rules" in portfolio_response.text
    assert "Exit Signal" in portfolio_response.text
    assert learning_response.status_code == HTTP_OK
    assert "Learning Requirements" in learning_response.text
    assert "No auto-tuning" in learning_response.text


def test_policy_page_shows_loaded_controls() -> None:
    client = TestClient(create_app())

    response = client.get("/policy")

    assert response.status_code == HTTP_OK
    assert "Portfolio policy is loaded from local controls" in response.text
    assert "Policy source" in response.text
    assert "Audit Log" in response.text


def test_static_styles_are_served() -> None:
    client = TestClient(create_app())

    response = client.get("/static/styles.css")

    assert response.status_code == HTTP_OK
    assert "summary-band" in response.text
    assert "action-ribbon" in response.text


def test_static_progress_script_is_served() -> None:
    client = TestClient(create_app())

    response = client.get("/static/data-refresh-progress.js")

    assert response.status_code == HTTP_OK
    assert "data-progress-panel" in response.text
    assert "data-load-panel" in response.text
    assert "data-scheduler-panel" in response.text
    assert "payload.status_label || \"Broker offline\"" in response.text


def test_static_responsive_tables_script_is_served() -> None:
    client = TestClient(create_app())

    response = client.get("/static/responsive-tables.js")

    assert response.status_code == HTTP_OK
    assert "applyResponsiveTableLabels" in response.text


def test_static_signal_table_script_is_served() -> None:
    client = TestClient(create_app())

    response = client.get("/static/signal-table.js")

    assert response.status_code == HTTP_OK
    assert "inspect-signal-button" in response.text
    assert "table-sort-button" in response.text


def test_broker_status_defaults_to_disabled(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "false")
    client = TestClient(create_app())

    response = client.get("/status/broker")

    assert response.status_code == HTTP_OK
    assert response.json()["status_label"] == "Broker Disabled"


async def test_broker_status_context_bounds_dashboard_broker_reads(
    monkeypatch: MonkeyPatch,
) -> None:
    async def slow_broker_snapshot(*, config: object) -> dict[str, object]:
        await asyncio.sleep(0.05)
        return {
            "provider": "alpaca",
            "mode": "paper",
            "connected": True,
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {},
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
            "status_label": "Broker Connected",
            "status_class": "pass",
            "detail": "slow broker response",
        }

    await _reset_broker_test_state()
    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setattr(market_regime_module, "broker_snapshot", slow_broker_snapshot)
    monkeypatch.setattr(
        market_regime_module,
        "DASHBOARD_BROKER_STATUS_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )

    started = datetime.now(UTC)
    context = await market_regime_module.broker_status_context(use_cache=True)

    assert context["connected"] is False
    assert context["status_label"] == "Broker Check Delayed"
    assert context["status_class"] == "warn"
    assert "did not finish within 0.01s" in str(context["detail"])
    assert datetime.fromisoformat(str(context["checked_at"])) >= started
    await _wait_for_broker_inflight(allow_errors=True)


async def test_broker_status_context_caches_completed_delayed_broker_reads(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = 0

    async def delayed_broker_snapshot(*, config: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {
            "provider": "alpaca",
            "mode": "paper",
            "connected": True,
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {"status": "ACTIVE"},
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
            "status_label": "Broker Connected",
            "status_class": "pass",
            "detail": "broker response",
        }

    await _reset_broker_test_state()
    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setattr(market_regime_module, "broker_snapshot", delayed_broker_snapshot)
    monkeypatch.setattr(
        market_regime_module,
        "DASHBOARD_BROKER_STATUS_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )

    delayed = await market_regime_module.broker_status_context(use_cache=True)
    await _wait_for_broker_inflight()
    recovered = await market_regime_module.broker_status_context(use_cache=True)

    assert delayed["status_label"] == "Broker Check Delayed"
    assert recovered["status_label"] == "Broker Connected"
    assert recovered["connected"] is True
    assert calls == 1


async def test_broker_status_context_caches_failed_delayed_broker_reads(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = 0

    async def delayed_failure_broker_snapshot(*, config: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        raise market_regime_module.AlpacaBrokerError("paper broker network unavailable")

    await _reset_broker_test_state()
    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setattr(market_regime_module, "broker_snapshot", delayed_failure_broker_snapshot)
    monkeypatch.setattr(
        market_regime_module,
        "DASHBOARD_BROKER_STATUS_TIMEOUT_SECONDS",
        0.01,
        raising=False,
    )

    delayed = await market_regime_module.broker_status_context(use_cache=True)
    repeated = await market_regime_module.broker_status_context(use_cache=True)
    await _wait_for_broker_inflight(allow_errors=True)
    offline = await market_regime_module.broker_status_context(use_cache=True)

    assert delayed["status_label"] == "Broker Check Delayed"
    assert repeated["status_label"] == "Broker Check Delayed"
    assert offline["status_label"] == "Broker Offline"
    assert offline["status_class"] == "warn"
    assert "paper broker network unavailable" in str(offline["detail"])
    assert calls == 1


async def _wait_for_broker_inflight(*, allow_errors: bool = False) -> None:
    tasks = list(market_regime_module._broker_status_inflight.values())
    if not tasks:
        return
    await _await_broker_tasks(tasks, allow_errors=allow_errors)


async def _await_broker_tasks(
    tasks: list[asyncio.Future[object]],
    *,
    allow_errors: bool,
) -> None:
    current_loop = asyncio.get_running_loop()
    current_loop_tasks: list[asyncio.Future[object]] = []
    for task in tasks:
        task_loop = task.get_loop()
        if task_loop is not current_loop:
            if not task.done():
                task.cancel()
            continue
        current_loop_tasks.append(task)
    if current_loop_tasks:
        await asyncio.wait(current_loop_tasks)
        for task in current_loop_tasks:
            if task.cancelled():
                continue
            error = task.exception()
            if error is not None and not allow_errors:
                raise error
    await asyncio.sleep(0)


async def _reset_broker_test_state() -> None:
    tasks = list(market_regime_module._broker_status_inflight.values())
    market_regime_module._broker_status_inflight.clear()
    for task in tasks:
        if not task.done():
            task.cancel()
    await _await_broker_tasks(tasks, allow_errors=False)
    market_regime_module._broker_status_context_cache.clear()


async def test_broker_status_context_does_not_reuse_foreign_loop_inflight_task(
    monkeypatch: MonkeyPatch,
) -> None:
    calls = 0

    async def connected_broker_snapshot(*, config: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "provider": "alpaca",
            "mode": "paper",
            "connected": True,
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {},
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
            "status_label": "Broker Connected",
            "status_class": "pass",
            "detail": "broker response",
        }

    await _reset_broker_test_state()
    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setattr(market_regime_module, "broker_snapshot", connected_broker_snapshot)

    foreign_loop = asyncio.new_event_loop()
    foreign_task = foreign_loop.create_future()
    market_regime_module._broker_status_inflight[
        market_regime_module._broker_status_inflight_key(
            market_regime_module._broker_status_cache_key(),
            foreign_loop,
        )
    ] = foreign_task  # type: ignore[assignment]
    try:
        context = await market_regime_module.broker_status_context(use_cache=True)
    finally:
        foreign_task.cancel()
        foreign_loop.close()

    assert context["status_label"] == "Broker Connected"
    assert calls == 1


async def test_broker_status_context_can_return_nonblocking_pending_status(
    monkeypatch: MonkeyPatch,
) -> None:
    async def failing_broker_snapshot(*, config: object) -> dict[str, object]:
        raise AssertionError("dashboard shell should not call live broker")

    await _reset_broker_test_state()
    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setattr(market_regime_module, "broker_snapshot", failing_broker_snapshot)

    context = await market_regime_module.broker_status_context(allow_live_read=False)

    assert context["connected"] is False
    assert context["status_label"] == "Broker Check Pending"
    assert "strict fresh Alpaca checks" in str(context["detail"])


async def test_execution_preview_uses_bounded_broker_read_for_page_render(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_broker_status_context(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
        }

    async def fake_policy() -> PortfolioPolicy:
        return PortfolioPolicy()

    async def fake_review_events(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    def fake_scheduler_context(**_kwargs: object) -> dict[str, object]:
        return {"tradability": {"state": "tradable", "status_label": "Tradable"}}

    monkeypatch.setattr(market_regime_module, "broker_status_context", fake_broker_status_context)
    monkeypatch.setattr(execution_module, "load_active_portfolio_policy", fake_policy)
    monkeypatch.setattr(command_module, "human_review_events_for_reports", fake_review_events)
    monkeypatch.setattr(execution_module, "scheduler_work_queue_context", fake_scheduler_context)

    await execution_module.execution_preview_context(raw_reports=[], data_sources=[])

    assert captured["use_cache"] is True


async def test_execution_preview_recovers_from_delayed_cached_broker_read(
    monkeypatch: MonkeyPatch,
) -> None:
    broker_calls: list[object] = []

    async def fake_broker_status_context(**kwargs: object) -> dict[str, object]:
        broker_calls.append(kwargs.get("use_cache"))
        if kwargs.get("use_cache") is True:
            return {
                "connected": False,
                "mode": "paper",
                "checked_at": datetime.now(UTC).isoformat(),
                "account": None,
                "positions": [],
                "orders": [],
                "gross_exposure_pct": 0.0,
                "status_label": "Broker Check Delayed",
                "status_class": "warn",
                "detail": "delayed",
            }
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
            "status_label": "Broker Connected",
            "status_class": "pass",
            "detail": "connected",
        }

    async def fake_policy() -> PortfolioPolicy:
        return PortfolioPolicy()

    async def fake_review_events(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    def fake_scheduler_context(**_kwargs: object) -> dict[str, object]:
        return {"tradability": {"state": "tradable", "status_label": "Tradable"}}

    monkeypatch.setattr(market_regime_module, "broker_status_context", fake_broker_status_context)
    monkeypatch.setattr(execution_module, "load_active_portfolio_policy", fake_policy)
    monkeypatch.setattr(command_module, "human_review_events_for_reports", fake_review_events)
    monkeypatch.setattr(execution_module, "scheduler_work_queue_context", fake_scheduler_context)

    context = await execution_module.execution_preview_context(raw_reports=[], data_sources=[])

    assert broker_calls == [True, False]
    assert context["broker"]["status_label"] == "Broker Connected"


async def test_execution_preview_refreshes_stale_connected_broker_cache() -> None:
    broker_calls: list[object] = []
    current_time = datetime.now(UTC)
    stale_checked_at = (current_time - timedelta(seconds=75)).isoformat()
    fresh_checked_at = current_time.isoformat()

    async def fake_broker_status_context(**kwargs: object) -> dict[str, object]:
        broker_calls.append(kwargs.get("use_cache"))
        checked_at = stale_checked_at if kwargs.get("use_cache") is True else fresh_checked_at
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": checked_at,
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
            "status_label": "Broker Connected",
            "status_class": "pass",
            "detail": "connected",
        }

    context = await execution_module._execution_preview_broker_status_context(
        fake_broker_status_context
    )

    assert broker_calls == [True, False]
    assert context["checked_at"] == fresh_checked_at


async def test_execution_preview_passes_market_phase_to_freshness_gate(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    classified: dict[str, object] = {}

    async def fake_policy() -> PortfolioPolicy:
        return PortfolioPolicy()

    async def fake_review_events(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    def fake_scheduler_context(**_kwargs: object) -> dict[str, object]:
        return {"tradability": {"state": "tradable", "status_label": "Tradable"}}

    def fake_freshness_gate(
        broker: Mapping[str, object],
        source_health: Sequence[Mapping[str, object]],
        **kwargs: object,
    ) -> dict[str, object]:
        captured["broker"] = broker
        captured["source_health"] = source_health
        captured.update(kwargs)
        return {
            "ready": True,
            "state": "pass",
            "status_label": "Ready",
            "status_class": "pass",
            "checks": [],
            "blocker_count": 0,
            "detail": "Broker and critical source freshness passed.",
        }

    def fake_classify_market_session(now: datetime) -> SimpleNamespace:
        classified["now"] = now
        return SimpleNamespace(phase="overnight_after_hours")

    monkeypatch.setattr(execution_module, "load_active_portfolio_policy", fake_policy)
    monkeypatch.setattr(command_module, "human_review_events_for_reports", fake_review_events)
    monkeypatch.setattr(execution_module, "scheduler_work_queue_context", fake_scheduler_context)
    monkeypatch.setattr(execution_module, "execution_freshness_gate", fake_freshness_gate)
    monkeypatch.setattr(
        execution_module,
        "classify_market_session",
        fake_classify_market_session,
    )

    await execution_module.execution_preview_context(
        raw_reports=[],
        data_sources=[],
        broker={
            "connected": True,
            "mode": "paper",
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
        },
    )

    assert captured["market_phase"] == "overnight_after_hours"
    assert captured["now"] == classified["now"]


async def test_execution_preview_reuses_leveraged_policy_for_render(
    monkeypatch: MonkeyPatch,
) -> None:
    from_env_count = 0

    def fake_from_env(
        cls: type[leveraged_module.LeveragedAlternativePolicy],
        env: object | None = None,
    ) -> leveraged_module.LeveragedAlternativePolicy:
        nonlocal from_env_count
        from_env_count += 1
        return cls()

    async def fake_policy() -> PortfolioPolicy:
        return PortfolioPolicy()

    async def fake_review_events(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    def fake_scheduler_context(**_kwargs: object) -> dict[str, object]:
        return {"tradability": {"state": "tradable", "status_label": "Tradable"}}

    monkeypatch.setattr(
        leveraged_module.LeveragedAlternativePolicy,
        "from_env",
        classmethod(fake_from_env),
    )
    monkeypatch.setattr(execution_module, "load_active_portfolio_policy", fake_policy)
    monkeypatch.setattr(command_module, "human_review_events_for_reports", fake_review_events)
    monkeypatch.setattr(execution_module, "scheduler_work_queue_context", fake_scheduler_context)

    reports = [
        _selection_report_for_cycle("cycle-1", "AAPL", "2026-05-07T09:31:00Z"),
        _selection_report_for_cycle("cycle-1", "MSFT", "2026-05-07T09:31:00Z"),
    ]
    broker = {
        "connected": True,
        "mode": "paper",
        "checked_at": datetime.now(UTC).isoformat(),
        "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
        "positions": [],
        "orders": [],
        "gross_exposure_pct": 0.0,
    }

    await execution_module.execution_preview_context(
        raw_reports=reports,
        data_sources=[],
        broker=broker,
    )

    assert from_env_count == 1


async def test_execution_preview_page_render_uses_fast_contract_builders(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_policy() -> PortfolioPolicy:
        return PortfolioPolicy()

    async def fake_review_events(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    def fake_risk_decisions(*_args: object, **kwargs: object) -> list[object]:
        captured["risk_validate_contracts"] = kwargs.get("validate_contracts")
        return []

    def fake_execution_previews(*_args: object, **kwargs: object) -> list[object]:
        captured["preview_validate_contracts"] = kwargs.get("validate_contracts")
        return []

    def fake_scheduler_context(**_kwargs: object) -> dict[str, object]:
        return {"tradability": {"state": "tradable", "status_label": "Tradable"}}

    monkeypatch.setattr(execution_module, "load_active_portfolio_policy", fake_policy)
    monkeypatch.setattr(command_module, "human_review_events_for_reports", fake_review_events)
    monkeypatch.setattr(execution_module, "build_risk_decisions", fake_risk_decisions)
    monkeypatch.setattr(execution_module, "build_execution_previews", fake_execution_previews)
    monkeypatch.setattr(execution_module, "scheduler_work_queue_context", fake_scheduler_context)

    await execution_module.execution_preview_context(
        raw_reports=[],
        data_sources=[],
        broker={
            "connected": True,
            "mode": "paper",
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
        },
    )

    assert captured == {
        "risk_validate_contracts": False,
        "preview_validate_contracts": False,
    }


async def test_dashboard_readiness_inputs_load_blocking_artifacts_concurrently(
    monkeypatch: MonkeyPatch,
) -> None:
    def slow_live_config() -> dict[str, object]:
        time.sleep(0.05)
        return {"runtime_signals": []}

    def slow_data_refresh() -> dict[str, object]:
        time.sleep(0.05)
        return {"state": "complete"}

    def slow_data_load_status(**_: object) -> dict[str, object]:
        time.sleep(0.05)
        return {"state": "ready"}

    async def slow_active_policy() -> PortfolioPolicy:
        await asyncio.sleep(0.05)
        return PortfolioPolicy()

    monkeypatch.setattr(
        command_module,
        "load_live_config_readiness",
        slow_live_config,
    )
    monkeypatch.setattr(command_module, "load_data_refresh_progress", slow_data_refresh)
    monkeypatch.setattr(command_module, "load_data_load_status", slow_data_load_status)
    monkeypatch.setattr(command_module, "load_active_portfolio_policy", slow_active_policy)

    started = time.perf_counter()
    inputs = await command_module._dashboard_readiness_inputs(data_sources=[])
    elapsed = time.perf_counter() - started

    assert elapsed < 0.13
    assert inputs["live_config"] == {"runtime_signals": []}
    assert inputs["data_refresh"] == {"state": "complete"}
    assert inputs["data_load_status"] == {"state": "ready"}
    assert isinstance(inputs["active_policy"], PortfolioPolicy)


async def test_dashboard_context_reuses_source_health_load_status(
    monkeypatch: MonkeyPatch,
) -> None:
    checked_at = datetime.now(UTC).isoformat()
    data_sources = [
        {
            "schema_version": "0.1.0",
            "source": "daily-market-bars",
            "source_tier": "MARKET_DATA",
            "status": "HEALTHY",
            "checked_at": checked_at,
            "freshness": "FRESH",
            "last_success_at": checked_at,
            "observed_lag_seconds": 1,
            "error_count": 0,
            "reliability_score": 1.0,
            "rate_limit_reset_at": None,
            "notes": [],
        }
    ]
    data_load_status = {
        "state": "ready",
        "status_label": "Ready",
        "status_class": "pass",
        "overall_percent": 100,
        "core_dataset_percent": 100,
        "critical_lane_percent": 100,
        "expected_ticker_count": 1,
        "market_flow_summary": {
            "status": "ready",
            "usable_ticker_count": 1,
            "expected_ticker_count": 1,
        },
        "dataset_summary": {},
        "agent_summary": {},
        "freshness_rows": [],
        "datasets": [],
        "lanes": [],
        "blockers": [],
        "warnings": [],
        "data_refresh": {},
        "health_monitor": {},
        "source_summary": {},
        "live_config": {"runtime_signals": [], "checks": []},
    }

    async def empty_reports(_limit: int) -> list[dict[str, object]]:
        return []

    async def source_status_with_load_status() -> dict[str, object]:
        return {
            "data_sources": data_sources,
            "data_load_status": data_load_status,
        }

    def fail_duplicate_load_status(**_: object) -> dict[str, object]:
        raise AssertionError("dashboard should reuse source-health load status")

    def fail_duplicate_live_config() -> dict[str, object]:
        raise AssertionError("dashboard should reuse load-status live config")

    def fake_scheduler_context(**_: object) -> dict[str, object]:
        return {"tradability": {"state": "tradable", "status_label": "Tradable"}}

    def fake_scheduler_view(status: dict[str, object]) -> dict[str, object]:
        return {
            "tradability": dict(status.get("tradability", {})),
            "refresh_workload": {},
        }

    monkeypatch.setattr(command_module, "_dashboard_selection_reports_live", empty_reports)
    monkeypatch.setattr(command_module, "_dashboard_risk_decisions_live", empty_reports)
    monkeypatch.setattr(
        command_module,
        "_runtime_data_source_status_with_load_status_live",
        source_status_with_load_status,
        raising=False,
    )
    monkeypatch.setattr(command_module, "load_data_load_status", fail_duplicate_load_status)
    monkeypatch.setattr(command_module, "load_live_config_readiness", fail_duplicate_live_config)
    monkeypatch.setattr(
        command_module,
        "load_data_refresh_progress",
        lambda: {
            "state": "complete",
            "status_label": "Complete",
            "percent_complete": 100,
            "updated_at": checked_at,
        },
    )
    monkeypatch.setattr(command_module, "scheduler_work_queue_context", fake_scheduler_context)
    monkeypatch.setattr(command_module, "scheduler_work_queue_view", fake_scheduler_view)

    context = await command_module.dashboard_context()

    assert context["data_sources"][0]["source"] == "daily-market-bars"
    assert context["data_load_status"]["status_label"] == "Ready"


async def test_dashboard_context_uses_full_cycle_for_review_queue(
    monkeypatch: MonkeyPatch,
) -> None:
    checked_at = datetime.now(UTC).isoformat()
    cycle_id = "auto-lane-refresh-20260522T173901Z"
    tickers = [f"N{i:03d}" for i in range(148)] + [f"W{i:02d}" for i in range(20)]
    reports = [
        {
            "cycle_id": cycle_id,
            "ticker": ticker,
            "as_of": checked_at,
            "generated_at": checked_at,
            "final_action": "WATCH" if ticker.startswith("W") else "NO_TRADE",
            "final_conviction": 0.7 if ticker.startswith("W") else 0.1,
            "policy_gates": [
                {"name": "selection_policy", "status": "PASS", "reason": "within policy"}
            ],
            "risk_flags": [],
            "evidence_pack": {
                "data_quality": {
                    "source_count": 5,
                    "confirmed_signal_count": 2,
                }
            },
        }
        for ticker in tickers
    ]
    risk_decisions = [
        {
            "cycle_id": report["cycle_id"],
            "ticker": report["ticker"],
            "as_of": report["as_of"],
            "decision": "WARN" if report["final_action"] == "WATCH" else "ALLOW",
            "reasons": ["Caution: review-only candidate"]
            if report["final_action"] == "WATCH"
            else ["risk decision recorded"],
            "final_action": report["final_action"],
            "final_conviction": report["final_conviction"],
        }
        for report in reports
    ]
    data_load_status = {
        "state": "ready",
        "status_label": "Ready",
        "status_class": "pass",
        "overall_percent": 100,
        "core_dataset_percent": 100,
        "critical_lane_percent": 100,
        "expected_ticker_count": len(tickers),
        "market_flow_summary": {
            "status": "ready",
            "usable_ticker_count": len(tickers),
            "expected_ticker_count": len(tickers),
        },
        "dataset_summary": {},
        "agent_summary": {},
        "freshness_rows": [],
        "datasets": [],
        "lanes": [],
        "blockers": [],
        "warnings": [],
        "data_refresh": {},
        "health_monitor": {},
        "source_summary": {},
        "live_config": {"runtime_signals": [], "checks": []},
    }
    seen_report_limits: list[int] = []

    async def fake_reports(limit: int) -> list[dict[str, object]]:
        seen_report_limits.append(limit)
        return reports[:limit]

    async def fake_risks(limit: int) -> list[dict[str, object]]:
        return risk_decisions[:limit]

    async def source_status_with_load_status() -> dict[str, object]:
        return {
            "data_sources": [],
            "data_load_status": data_load_status,
        }

    def fake_scheduler_context(**_: object) -> dict[str, object]:
        return {"tradability": {"state": "tradable", "status_label": "Tradable"}}

    def fake_scheduler_view(status: dict[str, object]) -> dict[str, object]:
        return {
            "headline": "Scheduler ready",
            "tradability": dict(status.get("tradability", {})),
            "refresh_workload": {},
        }

    async def no_review_events(
        reports: Sequence[Mapping[str, object]],
        readiness: Mapping[str, object],
    ) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(command_module, "_dashboard_selection_reports_live", fake_reports)
    monkeypatch.setattr(command_module, "_dashboard_risk_decisions_live", fake_risks)
    monkeypatch.setattr(
        command_module,
        "_runtime_data_source_status_with_load_status_live",
        source_status_with_load_status,
        raising=False,
    )
    monkeypatch.setattr(command_module, "human_review_events_for_reports", no_review_events)
    monkeypatch.setattr(
        command_module,
        "load_data_refresh_progress",
        lambda: {
            "state": "complete",
            "status_label": "Complete",
            "percent_complete": 100,
            "updated_at": checked_at,
        },
    )
    monkeypatch.setattr(command_module, "scheduler_work_queue_context", fake_scheduler_context)
    monkeypatch.setattr(command_module, "scheduler_work_queue_view", fake_scheduler_view)

    context = await command_module.dashboard_context()

    assert seen_report_limits == [command_module.FINAL_SELECTION_REPORT_LIMIT]
    assert context["review_progress"]["total_count"] == 20
    assert len(context["review_queue"]) == 20


def test_command_dashboard_runtime_timeout_budget_covers_live_selection_reads() -> None:
    assert command_module.DASHBOARD_RUNTIME_QUERY_TIMEOUT_SECONDS >= 15.0


async def test_operational_readiness_context_reuses_source_health_load_status(
    monkeypatch: MonkeyPatch,
) -> None:
    data_load_status = {
        "ready": True,
        "state": "ready",
        "status_label": "Ready",
        "blocker_count": 0,
        "warning_count": 0,
        "overall_percent": 100,
        "core_dataset_percent": 100,
        "critical_lane_percent": 100,
        "live_config": {"runtime_signals": [], "checks": []},
    }

    async def empty_reports(_limit: int) -> list[dict[str, object]]:
        return []

    async def source_status_with_load_status() -> dict[str, object]:
        return {
            "data_sources": [],
            "data_load_status": data_load_status,
        }

    def fail_duplicate_load_status(**_: object) -> dict[str, object]:
        raise AssertionError("operational readiness should reuse source-health load status")

    def fail_duplicate_live_config() -> dict[str, object]:
        raise AssertionError("operational readiness should reuse load-status live config")

    monkeypatch.setattr(command_module, "_dashboard_selection_reports_live", empty_reports)
    monkeypatch.setattr(command_module, "_dashboard_risk_decisions_live", empty_reports)
    monkeypatch.setattr(
        command_module,
        "_runtime_data_source_status_with_load_status_live",
        source_status_with_load_status,
    )
    monkeypatch.setattr(command_module, "load_data_load_status", fail_duplicate_load_status)
    monkeypatch.setattr(command_module, "load_live_config_readiness", fail_duplicate_live_config)
    monkeypatch.setattr(
        command_module,
        "load_data_refresh_progress",
        lambda: {"state": "complete", "status_label": "Complete"},
    )

    context = await command_module.operational_readiness_context()

    assert context["data_load_status"]["status_label"] == "Ready"
    assert context["live_config"] == {"runtime_signals": [], "checks": []}


async def test_operational_readiness_context_reports_runtime_fetch_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    checked_at = datetime.now(UTC).isoformat()

    async def failing_reports(*, limit: int = EXPECTED_FINAL_SELECTION_REPORT_LIMIT) -> list[dict[str, object]]:
        del limit
        raise RuntimeError("selection repository timed out")

    async def failing_risks(*, limit: int = EXPECTED_FINAL_SELECTION_REPORT_LIMIT) -> list[dict[str, object]]:
        del limit
        raise RuntimeError("risk repository timed out")

    async def source_status_with_load_status() -> dict[str, object]:
        return {
            "data_sources": [
                {
                    **_source_health(source),
                    "source_tier": "MARKET_DATA",
                    "checked_at": checked_at,
                    "last_success_at": checked_at,
                }
                for source in ("daily-market-bars", "massive-stock-trades")
            ],
            "data_load_status": {
                "ready": True,
                "state": "ready",
                "status_label": "Ready",
                "blocker_count": 0,
                "warning_count": 0,
                "overall_percent": 100,
                "core_dataset_percent": 100,
                "critical_lane_percent": 100,
                "live_config": {"runtime_signals": [], "checks": []},
            },
        }

    monkeypatch.setattr(command_module, "_dashboard_selection_reports", failing_reports)
    monkeypatch.setattr(command_module, "_dashboard_risk_decisions", failing_risks)
    monkeypatch.setattr(
        command_module,
        "_runtime_data_source_status_with_load_status_live",
        source_status_with_load_status,
    )
    monkeypatch.setattr(
        command_module,
        "load_data_refresh_progress",
        lambda: {"state": "complete", "status_label": "Complete"},
    )

    context = await command_module.operational_readiness_context()

    live_readiness = context["live_readiness"]
    assert live_readiness["verdict"] == "runtime_reader_unavailable"
    assert "runtime repository is unavailable" in str(live_readiness["detail"]).lower()
    assert "No runtime cycle found" not in str(context)


async def test_operational_readiness_context_filters_to_active_cycle(
    monkeypatch: MonkeyPatch,
) -> None:
    older = _selection_report_for_cycle(
        "live-pit-older",
        "MSFT",
        "2026-05-06T09:31:00Z",
    )
    current = _selection_report_for_cycle(
        "live-pit-current",
        "AAPL",
        "2026-05-07T09:31:00Z",
    )
    current_risk = build_risk_decision(
        current,
        {"source_count": 2, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision
    older_risk = build_risk_decision(
        older,
        {"source_count": 2, "degraded_source_count": 0},
        generated_at="2026-05-06T09:32:00Z",
    ).risk_decision
    checked_at = datetime.now(UTC).isoformat()

    async def reports(*, limit: int = EXPECTED_FINAL_SELECTION_REPORT_LIMIT) -> list[dict[str, object]]:
        del limit
        return [older, current]

    async def risks(*, limit: int = EXPECTED_FINAL_SELECTION_REPORT_LIMIT) -> list[dict[str, object]]:
        del limit
        return [older_risk, current_risk]

    async def source_status_with_load_status() -> dict[str, object]:
        return {
            "data_sources": [
                {
                    **_source_health(source),
                    "source_tier": "MARKET_DATA",
                    "checked_at": checked_at,
                    "last_success_at": checked_at,
                }
                for source in ("daily-market-bars", "massive-stock-trades")
            ],
            "data_load_status": {
                "ready": True,
                "state": "ready",
                "status_label": "Ready",
                "blocker_count": 0,
                "warning_count": 0,
                "overall_percent": 100,
                "core_dataset_percent": 100,
                "critical_lane_percent": 100,
                "live_config": {"runtime_signals": [], "checks": []},
            },
        }

    async def fake_review_events(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(command_module, "_dashboard_selection_reports", reports)
    monkeypatch.setattr(command_module, "_dashboard_risk_decisions", risks)
    monkeypatch.setattr(
        command_module,
        "_runtime_data_source_status_with_load_status_live",
        source_status_with_load_status,
    )
    monkeypatch.setattr(command_module, "human_review_events_for_reports", fake_review_events)
    monkeypatch.setattr(
        command_module,
        "load_data_refresh_progress",
        lambda: {"state": "complete", "status_label": "Complete"},
    )

    context = await command_module.operational_readiness_context()

    assert context["live_readiness"]["cycle_id"] == "live-pit-current"
    assert context["paper_review"]["cycle_id"] == "live-pit-current"


def test_paper_review_status_endpoint_renders_empty_state(monkeypatch: MonkeyPatch) -> None:
    async def fake_reports(*, limit: int = 50) -> list[dict[str, object]]:
        del limit
        return []

    async def fake_sources() -> list[dict[str, object]]:
        checked_at = datetime.now(UTC).isoformat()
        return [
            {
                "schema_version": "0.1.0",
                "source": source,
                "source_tier": "MARKET_DATA",
                "status": "HEALTHY",
                "checked_at": checked_at,
                "freshness": "FRESH",
                "last_success_at": checked_at,
                "observed_lag_seconds": 1,
                "error_count": 0,
                "reliability_score": 1.0,
                "rate_limit_reset_at": None,
                "notes": [],
            }
            for source in ("daily-market-bars", "massive-stock-trades")
        ]

    async def fake_risks(*, limit: int = 50) -> list[dict[str, object]]:
        del limit
        return []

    monkeypatch.setattr(command_module, "_dashboard_selection_reports", fake_reports)
    monkeypatch.setattr(command_module, "runtime_data_source_status", fake_sources)
    monkeypatch.setattr(command_module, "_dashboard_risk_decisions", fake_risks)

    client = TestClient(create_app())

    response = client.get("/status/paper-review")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["schema_version"] == "0.1.0"
    assert payload["progress"]["total_count"] == 0
    assert payload["queue"] == []


def test_scheduler_work_queue_endpoint_returns_payload() -> None:
    client = TestClient(create_app())

    response = client.get("/status/scheduler-work-queue")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload["schema_version"] == "0.1.0"
    assert "jobs" in payload
    assert "tradability" in payload
    assert payload["automation_status"]["label"] == "Automation Status"
    assert payload["trading_freshness_gate"]["label"] == "Trading Freshness Gate"
    assert payload["refresh_workload"]["label"] == "Refresh Workload"
    assert "lane_summary" in payload["massive_orchestrator"]
    assert "display_status_label" in payload["massive_orchestrator"]["lanes"][0]


async def test_scheduler_work_queue_endpoint_filters_to_active_cycle(
    monkeypatch: MonkeyPatch,
) -> None:
    current = _selection_report_for_cycle(
        "live-pit-current",
        "AAPL",
        "2026-05-07T09:31:00Z",
    )
    current["final_conviction"] = 0.40
    older = _selection_report_for_cycle(
        "live-pit-older",
        "MSFT",
        "2026-05-06T09:31:00Z",
    )
    older["final_conviction"] = 0.95

    async def fake_reports(
        *,
        limit: int = EXPECTED_FINAL_SELECTION_REPORT_LIMIT,
    ) -> list[dict[str, object]]:
        assert limit == EXPECTED_FINAL_SELECTION_REPORT_LIMIT
        return [current, older]

    monkeypatch.setattr(shared_module, "runtime_selection_reports", fake_reports)

    payload = await command_module.scheduler_work_queue_status_context()
    tier_payload = payload["ticker_tiers"]
    assert isinstance(tier_payload, dict)
    tiers = tier_payload["tiers"]
    assert isinstance(tiers, dict)
    t1 = tiers["T1"]
    assert isinstance(t1, dict)

    assert "MSFT" not in t1["sample"]


def test_candidate_review_post_records_human_review(monkeypatch: MonkeyPatch) -> None:
    writes: list[dict[str, object]] = []
    session = _FakeSession()

    @asynccontextmanager
    async def fake_session_provider() -> AsyncIterator[_FakeSession]:
        yield session

    async def fake_persist(session_arg: object, **kwargs: object) -> dict[str, object]:
        assert session_arg is session
        writes.append(dict(kwargs))
        return {"event_type": "HUMAN_REVIEW"}

    async def fake_report_hash(**_kwargs: object) -> str:
        return "review-hash"

    monkeypatch.setattr(dashboard_module, "get_session", fake_session_provider)
    monkeypatch.setattr(
        dashboard_module,
        "build_and_persist_human_review_event",
        fake_persist,
    )
    monkeypatch.setattr(dashboard_module, "_selection_report_hash_for_review", fake_report_hash)
    client = TestClient(create_app())

    response = client.post(
        "/candidates/aapl/reviews"
        "?cycle_id=cycle-1&as_of=2026-05-07T09%3A30%3A00Z&decision=APPROVE"
        "&review_reason=confirmed&notes=paper%20only",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"] == "/execution-preview?ticker=AAPL#focused-preview-AAPL"
    assert session.committed is True
    assert writes == [
        {
            "cycle_id": "cycle-1",
            "ticker": "aapl",
            "as_of": "2026-05-07T09:30:00Z",
            "decision": "APPROVE",
            "review_reason": "confirmed",
            "notes": "paper only",
            "selection_report_hash": "review-hash",
        }
    ]


def test_candidate_review_post_writes_local_event_when_db_unavailable(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "human-review-events.jsonl"

    @asynccontextmanager
    async def unavailable_session_provider() -> AsyncIterator[_FakeSession]:
        raise OSError("database unavailable")
        yield _FakeSession()

    async def fake_report_hash(**_kwargs: object) -> str:
        return "review-hash"

    monkeypatch.setenv("AGENCY_RUNTIME_LIFECYCLE_EVENTS_PATH", str(events_path))
    monkeypatch.setattr(dashboard_module, "get_session", unavailable_session_provider)
    monkeypatch.setattr(dashboard_module, "_selection_report_hash_for_review", fake_report_hash)
    client = TestClient(create_app())

    response = client.post(
        "/candidates/aapl/reviews"
        "?cycle_id=cycle-1&as_of=2026-05-07T09%3A30%3A00Z&decision=APPROVE",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["event_type"] == "HUMAN_REVIEW"
    assert event["ticker"] == "AAPL"
    assert event["payload"]["selection_report_hash"] == "review-hash"


def test_candidate_review_post_rejects_hashless_review(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_report_hash(**_kwargs: object) -> None:
        return None

    monkeypatch.setattr(dashboard_module, "_selection_report_hash_for_review", fake_report_hash)

    response = TestClient(create_app()).post(
        "/candidates/aapl/reviews"
        "?cycle_id=cycle-1&as_of=2026-05-07T09%3A30%3A00Z&decision=APPROVE",
        follow_redirects=False,
    )

    assert response.status_code == 409
    assert "hash-bound review" in response.json()["detail"]


def test_candidate_review_post_rejects_missing_required_caution_ack(
    monkeypatch: MonkeyPatch,
) -> None:
    writes: list[dict[str, object]] = []

    async def fake_report_hash(**_kwargs: object) -> str:
        return "review-hash"

    async def fake_caution_required(**_kwargs: object) -> bool:
        return True

    async def fake_persist(_session_arg: object, **kwargs: object) -> dict[str, object]:
        writes.append(dict(kwargs))
        return {"event_type": "HUMAN_REVIEW"}

    monkeypatch.setattr(dashboard_module, "_selection_report_hash_for_review", fake_report_hash)
    monkeypatch.setattr(
        dashboard_module,
        "_caution_acknowledgement_required_for_review",
        fake_caution_required,
    )
    monkeypatch.setattr(
        dashboard_module,
        "build_and_persist_human_review_event",
        fake_persist,
    )

    response = TestClient(create_app()).post(
        "/candidates/aapl/reviews"
        "?cycle_id=cycle-1&as_of=2026-05-07T09%3A30%3A00Z&decision=APPROVE",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "caution acknowledgement" in response.json()["detail"]
    assert writes == []


def test_candidate_review_post_accepts_form_caution_acknowledgement(
    monkeypatch: MonkeyPatch,
) -> None:
    writes: list[dict[str, object]] = []
    session = _FakeSession()

    @asynccontextmanager
    async def fake_session_provider() -> AsyncIterator[_FakeSession]:
        yield session

    async def fake_report_hash(**_kwargs: object) -> str:
        return "review-hash"

    async def fake_caution_required(**_kwargs: object) -> bool:
        return True

    async def fake_persist(session_arg: object, **kwargs: object) -> dict[str, object]:
        assert session_arg is session
        writes.append(dict(kwargs))
        return {"event_type": "HUMAN_REVIEW"}

    monkeypatch.setattr(dashboard_module, "get_session", fake_session_provider)
    monkeypatch.setattr(dashboard_module, "_selection_report_hash_for_review", fake_report_hash)
    monkeypatch.setattr(
        dashboard_module,
        "_caution_acknowledgement_required_for_review",
        fake_caution_required,
    )
    monkeypatch.setattr(
        dashboard_module,
        "build_and_persist_human_review_event",
        fake_persist,
    )

    response = TestClient(create_app()).post(
        "/candidates/aapl/reviews"
        "?cycle_id=cycle-1&as_of=2026-05-07T09%3A30%3A00Z&decision=APPROVE",
        data={"caution_acknowledged": "true"},
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert writes[0]["caution_acknowledged"] is True


def test_candidate_manual_llm_review_runs_for_selected_ticker(
    monkeypatch: MonkeyPatch,
) -> None:
    report = build_final_selection(_evidence_pack()).selection_report
    writes: dict[str, object] = {}
    session = _FakeSession()

    @asynccontextmanager
    async def fake_session_provider() -> AsyncIterator[_FakeSession]:
        yield session

    async def fake_reports(**kwargs: object) -> list[dict[str, object]]:
        assert kwargs["ticker"] == "AAPL"
        return [report]

    class FakeProvider:
        async def review(
            self,
            evidence_pack: Mapping[str, object],
            deterministic_decision: Mapping[str, object],
        ) -> LlmReviewResult:
            review = {
                "action": "AGREE",
                "confidence": 0.81,
                "rationale": "Manual review agrees with the ranked evidence.",
                "supporting_factors": ["two confirmed signals"],
                "concerns": [],
            }
            return LlmReviewResult(
                review=review,
                lifecycle_event=build_llm_lifecycle_event(
                    evidence_pack,
                    deterministic_decision,
                    review,
                    event_time=str(evidence_pack["generated_at"]),
                ),
                prompt_audit=None,
            )

    async def fake_upsert(_session_arg: object, payload: Mapping[str, object]) -> None:
        writes["report"] = dict(payload)

    async def fake_record(_session_arg: object, payload: Mapping[str, object]) -> None:
        writes["event"] = dict(payload)

    def fake_provider_from_env(*, enabled: bool) -> FakeProvider:
        return FakeProvider()

    monkeypatch.setattr(dashboard_module, "_dashboard_selection_reports", fake_reports)
    monkeypatch.setattr(dashboard_module, "get_session", fake_session_provider)
    monkeypatch.setattr(dashboard_module, "upsert_selection_report", fake_upsert)
    monkeypatch.setattr(dashboard_module, "record_candidate_lifecycle_event", fake_record)
    monkeypatch.setattr(
        dashboard_module.OpenAILlmReviewProvider,
        "from_env",
        fake_provider_from_env,
    )

    response = TestClient(create_app()).post(
        "/candidates/aapl/llm-review",
        data={
            "cycle_id": "cycle-1",
            "as_of": "2026-05-07T09:30:00Z",
        },
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"] == "/candidates/AAPL?llm_review=completed"
    assert session.committed is True
    persisted_report = writes["report"]
    assert isinstance(persisted_report, dict)
    assert persisted_report["llm_review"]["action"] == "AGREE"  # type: ignore[index]
    persisted_event = writes["event"]
    assert isinstance(persisted_event, dict)
    assert persisted_event["event_type"] == "LLM_ACTION"
    assert persisted_event["payload"]["manual_trigger"] is True  # type: ignore[index]


def test_operator_manual_advance_post_records_hash_bound_event(
    monkeypatch: MonkeyPatch,
) -> None:
    writes: list[dict[str, object]] = []
    session = _FakeSession()

    @asynccontextmanager
    async def fake_session_provider() -> AsyncIterator[_FakeSession]:
        yield session

    async def fake_report_hash(**_kwargs: object) -> str:
        return "b" * 64

    async def fake_record(_session_arg: object, event: dict[str, object]) -> None:
        writes.append(event)

    monkeypatch.setattr(dashboard_module, "get_session", fake_session_provider)
    monkeypatch.setattr(dashboard_module, "_selection_report_hash_for_review", fake_report_hash)
    monkeypatch.setattr(dashboard_module, "record_candidate_lifecycle_event", fake_record)

    response = TestClient(create_app()).post(
        "/execution-preview/operator-advance"
        "?cycle_id=cycle-1&ticker=aapl&as_of=2026-05-07T09%3A30%3A00Z",
        data={
            "override_reason": "Operator accepts this block for a paper rehearsal.",
            "blocked_reason": "selection policy gate blocked",
            "acknowledged": "true",
        },
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"] == "/execution-preview?ticker=AAPL#focused-preview-AAPL"
    assert session.committed is True
    assert writes[0]["event_type"] == "OPERATOR_MANUAL_ADVANCE"
    assert writes[0]["payload"]["selection_report_hash"] == "b" * 64
    assert writes[0]["payload"]["override_reason"] == (
        "Operator accepts this block for a paper rehearsal."
    )


def test_candidate_defer_redirects_back_to_candidate(monkeypatch: MonkeyPatch) -> None:
    session = _FakeSession()

    @asynccontextmanager
    async def fake_session_provider() -> AsyncIterator[_FakeSession]:
        yield session

    async def fake_persist(_session_arg: object, **_kwargs: object) -> dict[str, object]:
        return {"event_type": "HUMAN_REVIEW"}

    async def fake_report_hash(**_kwargs: object) -> str:
        return "review-hash"

    monkeypatch.setattr(dashboard_module, "get_session", fake_session_provider)
    monkeypatch.setattr(
        dashboard_module,
        "build_and_persist_human_review_event",
        fake_persist,
    )
    monkeypatch.setattr(dashboard_module, "_selection_report_hash_for_review", fake_report_hash)
    client = TestClient(create_app())

    response = client.post(
        "/candidates/aapl/reviews"
        "?cycle_id=cycle-1&as_of=2026-05-07T09%3A30%3A00Z&decision=DEFER",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"] == "/candidates/AAPL"


def test_candidate_detail_renders_audit_empty_state() -> None:
    client = TestClient(create_app())

    response = client.get("/candidates/AAPL")

    assert response.status_code == HTTP_OK
    assert "Candidate Brief" in response.text
    assert "AAPL" in response.text
    assert "Human Review" in response.text
    assert "Leveraged Alternative Advisor" in response.text
    assert "Mailbox Alert" in response.text
    assert "Agency Interpretation" in response.text
    assert "No selection report available for review" in response.text
    assert "No lifecycle events yet" in response.text


def test_candidate_detail_light_audit_shell_renders_without_rich_reconstruction(
    monkeypatch: MonkeyPatch,
) -> None:
    report = _selection_report_for_cycle(
        "live-pit-current",
        "PLTR",
        "2026-05-07T09:31:00Z",
    )

    async def fake_reports(*, ticker: str | None = None, limit: int = 1) -> list[dict[str, object]]:
        assert ticker == "PLTR"
        assert limit == 1
        return [report]

    async def empty_timeline(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    async def empty_risk(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    async def fake_broker() -> dict[str, object]:
        raise AssertionError("audit light candidate shell should not call broker status")

    async def fake_data_load_status() -> dict[str, object]:
        return {"datasets": [], "lane_states": [], "summary": {}}

    def forbidden_enrichment(_rows: object) -> list[dict[str, object]]:
        raise AssertionError("audit shell should not rebuild rich signal evidence")

    monkeypatch.setattr(candidates_module, "_dashboard_selection_reports", fake_reports)
    monkeypatch.setattr(candidates_module, "_dashboard_candidate_timeline", empty_timeline)
    monkeypatch.setattr(candidates_module, "_dashboard_risk_decisions", empty_risk)
    monkeypatch.setattr(market_regime_module, "broker_status_context", fake_broker)
    monkeypatch.setattr(candidates_module, "live_dashboard_data_load_status", fake_data_load_status)
    monkeypatch.setattr(
        candidates_module,
        "enrich_signal_rows_with_evidence",
        forbidden_enrichment,
    )

    response = TestClient(create_app()).get("/candidates/PLTR?audit=light")

    assert response.status_code == HTTP_OK
    assert "PLTR is ready for evidence review" in response.text
    assert "Rich article/email evidence was skipped for the audit shell." in response.text
    assert "RSS/news ticker evidence" in response.text
    assert "Email/article evidence" in response.text
    assert "data-health-panel" in response.text


def test_candidate_rows_summarize_selection_reports() -> None:
    rows = candidate_rows([_selection_report()])

    assert rows == [
        {
            "ticker": "AAPL",
            "action": "WATCH",
            "conviction_pct": 62,
            "gate_status": "WARN",
            "as_of": "2026-05-07T09:30:00Z",
            "as_of_label": "2026-05-07 09:30 UTC",
            "risk_flag_count": 1,
        }
    ]


def test_command_summary_counts_runtime_rows() -> None:
    summary = command_summary(
        candidates=candidate_rows([_selection_report()]),
        data_sources=[_source_health("sec-edgar"), _degraded_source_health()],
        contracts=[{"name": "selection-report"}],
    )

    assert summary["candidate_count"] == 1
    assert summary["actionable_candidate_count"] == 1
    assert summary["degraded_source_count"] == 1
    assert summary["source_count"] == EXPECTED_SOURCE_COUNT
    assert summary["contract_count"] == 1
    assert summary["headline"] == "Runtime online. 1 actionable candidate across 1 report."


def test_command_actions_target_visible_dashboard_anchors() -> None:
    actions = command_module.command_actions()
    hrefs = {action["label"]: action["href"] for action in actions}

    assert hrefs["Data readiness"] == "#status-data-readiness"
    assert hrefs["Trade pull"] == "#trade-pull-status-heading"
    assert hrefs["Scheduler"] == "#status-scheduler"
    assert "#data-load-heading" not in hrefs.values()
    assert "#scheduler-heading" not in hrefs.values()


def test_command_status_overview_exposes_visible_runtime_gates() -> None:
    overview = command_status_overview(
        broker=broker_status_view(
            {
                "status_label": "Broker Disabled",
                "status_class": "neutral",
                "mode": "paper",
                "detail": "Broker reads are disabled.",
            }
        ),
        data_load_status={
            "status_label": "Review Ready",
            "status_class": "warn",
            "overall_percent": 80,
            "blocker_count": 0,
            "warning_count": 2,
        },
        data_refresh={
            "status_label": "Loading",
            "eta_label": "3m",
            "trade_pull": {
                "state": "ready",
                "status_label": "Trades Ready",
                "status_class": "pass",
                "percent_complete": 100,
                "latest_as_of": "2026-05-14 00:00 UTC",
                "updated_at": "2026-05-14T12:00:00Z",
                "coverage_scope_label": "168 stored tickers; latest batch 24/24 usable",
                "ticker_progress_label": "24/24 ticker-days",
                "row_count_label": "12,345",
            },
        },
        full_live_readiness={
            "status_label": "Ready With Partial Lanes",
            "status_class": "warn",
            "review_operational_ready": True,
            "tradable_ready": False,
            "detail": "Review-operational, trading gated.",
        },
        operational_readiness={"status_class": "pass", "detail": "Review loop is operational."},
        provider_readiness={
            "status_label": "Provider Keys Ready",
            "status_class": "pass",
            "configured_count": 3,
            "provider_count": 4,
        },
        scheduler={
            "status_label": "Review Operational",
            "status_class": "warn",
            "tradability_detail": "Scheduler is current; execution freshness is gated.",
        },
    )

    rows = {row["id"]: row for row in overview["rows"]}
    assert rows["status-broker"]["label"] == "Broker"
    assert rows["status-provider-config"]["label"] == "Provider Connections"
    assert rows["status-review-operational"]["value"] == "Ready"
    assert rows["status-tradable-ready"]["value"] == "Gated"
    assert overview["trade_pull"]["eta_label"] == "not running"
    assert overview["trade_pull"]["freshness_label"] == "2026-05-14 00:00 UTC"
    assert overview["trade_pull"]["progress_style"] == "width: 100%"
    assert overview["trade_pull"]["status_label"] == "Usable for live review"
    assert overview["issue_summary"]["blocker_count"] == 0
    assert overview["issue_summary"]["warning_count"] == 2
    assert overview["issue_summary"]["refresh_label"] == "Loading: 3m ETA"
    assert "tooltip" in overview["trade_pull"]


def test_command_status_overview_humanizes_seconds_in_details() -> None:
    overview = command_status_overview(
        broker=broker_status_view(
            {
                "status_label": "Broker Connected",
                "status_class": "pass",
                "mode": "paper",
                "detail": "Broker reads are live.",
            }
        ),
        data_load_status={
            "status_label": "Loaded With Gaps",
            "status_class": "warn",
            "overall_percent": 97,
            "blocker_count": 0,
            "warning_count": 17,
        },
        data_refresh={
            "state": "running",
            "status_label": "Loading",
            "status_class": "warn",
            "eta_label": "7m",
            "trade_pull": {
                "status_label": "Trades Ready",
                "status_class": "pass",
                "percent_complete": 100,
                "latest_as_of": "2026-05-16T09:36:31Z",
                "updated_at": "2026-05-16T09:36:31Z",
                "coverage_scope_label": "168 stored tickers; latest batch 24/24 usable",
                "ticker_progress_label": "24/24 ticker-days",
                "row_count_label": "1,239,948",
            },
        },
        full_live_readiness={
            "status_label": "Ready With Partial Lanes",
            "status_class": "warn",
            "review_operational_ready": True,
            "tradable_ready": False,
            "detail": "manifest checked 27040s ago; SLA is 1800s.",
        },
        operational_readiness={"status_class": "pass", "detail": "Review loop is operational."},
        provider_readiness={
            "status_label": "Provider Keys Ready",
            "status_class": "pass",
            "configured_count": 6,
            "provider_count": 11,
            "required_ready_count": 4,
            "active_required_count": 4,
            "required_label": "4/4 required ready",
        },
        scheduler={
            "status_label": "Review Operational",
            "status_class": "warn",
            "tradability_detail": "Scheduler is current.",
        },
    )

    rows = {row["id"]: row for row in overview["rows"]}
    assert "27040s" not in rows["status-live-runtime"]["detail"]
    assert "7h 30m ago" in rows["status-live-runtime"]["detail"]
    assert overview["trade_pull"]["ticker_progress_label"] == (
        "168 stored tickers; latest batch 24/24 usable"
    )


def test_full_live_readiness_view_humanizes_embedded_seconds() -> None:
    view = command_module.full_live_readiness_view(
        {
            "status_label": "Ready With Partial Lanes",
            "status_class": "warn",
            "detail": "manifest checked 28476s ago",
            "coverage": {"overall_percent": 97},
            "active_refresh": {"dataset_rows": []},
            "provider_usage": [
                {
                    "label": "SEC EDGAR",
                    "status": "WARN",
                    "status_class": "warn",
                    "detail": "source-health row is 28028s old",
                }
            ],
            "next_actions": ["Refresh source-health row checked 28027s ago"],
            "blockers": [],
            "warnings": [],
        }
    )

    assert "28476s" not in str(view["detail"])
    assert "7h 54m ago" in str(view["detail"])
    assert "28028s" not in str(view["provider_usage_rows"][0]["detail"])
    assert "7h 47m old" in str(view["provider_usage_rows"][0]["detail"])
    assert "28027s" not in str(view["next_action_rows"][0])

    issue_view = command_module.data_load_status_view(
        {
            "overall_percent": 97,
            "detail": "manifest checked 28676s ago",
            "datasets": [],
            "lanes": [],
            "freshness_rows": [
                {
                    "label": "Massive Stock Trades",
                    "detail": "manifest checked 28914s ago",
                }
            ],
            "blockers": [],
            "warnings": [
                {
                    "kind": "data",
                    "item": "stock_trades",
                    "reason": "manifest checked 28676s ago",
                }
            ],
        }
    )
    assert "28676s" not in str(issue_view["detail"])
    assert "28676s" not in str(issue_view["issue_rows"][0]["reason"])
    assert "28914s" not in str(issue_view["freshness_rows"][0]["detail"])

    row_view = command_module.data_load_status_view(
        {
            "overall_percent": 97,
            "datasets": [
                {
                    "dataset": "sec_company_facts",
                    "coverage_pct": 99,
                    "detail": "source-health row is 28331s old",
                }
            ],
            "lanes": [],
            "freshness_rows": [],
            "blockers": [],
            "warnings": [],
        }
    )
    assert "28331s" not in str(row_view["dataset_rows"][0]["detail"])

    scheduler_view = command_module.scheduler_work_queue_view(
        {
            "summary": {
                "headline": "Scheduler is context-only: source-health row is 28598s old",
                "counts": {"due_now": 0, "running": 0},
            },
            "ticker_tiers": {"tiers": {}},
            "tradability": {
                "status_label": "Context Only",
                "status_class": "warn",
                "detail": "checked 28598s ago",
            },
            "repair_plan": {"jobs": []},
            "execution_freshness_gate": {"checks": []},
            "scheduler_runtime": {
                "status_label": "Running",
                "detail": "latest heartbeat 28598s ago",
            },
            "massive_orchestrator": {
                "lanes": [],
                "derived_signal_lanes": [],
                "detail": "manifest checked 28914s ago",
            },
            "jobs": [],
            "next_jobs": [],
            "stale_datasets": [],
            "market_phase": "closed_weekend",
        }
    )
    assert "28598s" not in str(scheduler_view["headline"])
    assert "28598s" not in str(scheduler_view["tradability_detail"])
    assert "28598s" not in str(scheduler_view["runtime"]["detail"])
    assert "28914s" not in str(scheduler_view["massive_orchestrator"]["detail"])


def test_scheduler_work_queue_view_translates_refresh_needed_rows_for_users() -> None:
    view = command_module.scheduler_work_queue_view(
        {
            "summary": {
                "headline": "Some datasets are stale or warning.",
                "counts": {"due_now": 0, "running": 0},
            },
            "ticker_tiers": {"tiers": {}},
            "tradability": {
                "status_label": "Context Only",
                "status_class": "warn",
                "detail": "Some datasets are stale or warning.",
            },
            "repair_plan": {"jobs": []},
            "execution_freshness_gate": {"checks": []},
            "scheduler_runtime": {"status_label": "Idle", "detail": "No job running."},
            "massive_orchestrator": {"lanes": [], "derived_signal_lanes": []},
            "jobs": [],
            "next_jobs": [],
            "stale_datasets": [
                {
                    "dataset": "prices_daily",
                    "status": "STALE",
                    "status_class": "warn",
                    "reason": "Daily bars are stale.",
                }
            ],
            "market_phase": "closed_weekend",
        }
    )

    assert "stale" not in str(view["headline"]).lower()
    assert "stale" not in str(view["tradability_detail"]).lower()
    assert "stale" not in str(view["stale_rows"]).lower()
    assert view["stale_rows"][0]["status"] == "needs refresh"
    assert view["stale_rows"][0]["reason"] == "Daily bars need refresh."


def test_scheduler_work_queue_view_exposes_context_refresh_actions() -> None:
    view = command_module.scheduler_work_queue_view(
        {
            "summary": {
                "headline": "Context data needs attention.",
                "counts": {"due_now": 0, "running": 0},
            },
            "ticker_tiers": {"tiers": {}},
            "tradability": {
                "status_label": "Tradable",
                "status_class": "pass",
                "detail": "Core execution lanes are ready.",
            },
            "repair_plan": {"jobs": []},
            "execution_freshness_gate": {"checks": []},
            "scheduler_runtime": {"status_label": "Idle", "detail": "No job running."},
            "massive_orchestrator": {"lanes": [], "derived_signal_lanes": []},
            "jobs": [],
            "next_jobs": [],
            "stale_datasets": [
                {
                    "dataset": "news_rss",
                    "status": "WARNING",
                    "status_class": "warn",
                    "reason": "RSS/news source needs attention.",
                },
                {
                    "dataset": "subscription_emails",
                    "status": "WARNING",
                    "status_class": "warn",
                    "reason": "Subscription email thesis needs login confirmation.",
                },
            ],
            "market_phase": "regular_market",
        }
    )

    news, email = view["stale_rows"]
    assert news["refresh_action_url"] == "/scheduler/datasets/news_rss/refresh"
    assert news["refresh_button_label"] == "Refresh RSS/news"
    assert email["refresh_action_url"] == "/scheduler/subscription-emails/login-refresh"
    assert email["refresh_button_label"] == "Open email login refresh"


def test_scheduler_work_queue_view_splits_automation_gate_and_workload() -> None:
    view = command_module.scheduler_work_queue_view(
        {
            "summary": {
                "headline": "Scheduler is context-only: source-health row is 28598s old",
                "counts": {"due_now": 2, "running": 1},
            },
            "ticker_tiers": {"tiers": {}},
            "tradability": {
                "status_label": "Context Only",
                "status_class": "warn",
                "detail": "critical evidence needs refresh",
            },
            "repair_plan": {
                "status_label": "Ready Off-Hours",
                "jobs": [
                    {
                        "job_id": "repair:stock_trades",
                        "dataset": "stock_trades",
                        "status": "DUE_NOW",
                        "eta_label": "9m",
                    }
                ],
            },
            "execution_freshness_gate": {"checks": []},
            "scheduler_runtime": {
                "status_label": "Running",
                "status_class": "pass",
                "detail": "Automatic lane refresh is running sec_form4.",
            },
            "massive_orchestrator": {
                "lanes": [
                    {
                        "lane_id": "massive_live_trade_slices",
                        "label": "Massive Live Trade Slices",
                        "status": "DUE_NOW",
                        "status_class": "warn",
                        "blocks_execution": True,
                        "eta_label": "5m",
                    }
                ],
                "derived_signal_lanes": [],
                "detail": "Run due Massive raw acquisition lane.",
            },
            "jobs": [
                {
                    "job_id": "signal:news",
                    "kind": "signal_lane",
                    "name": "news",
                    "dataset": "news_rss",
                    "signal_lane": "news",
                    "status": "DUE_NOW",
                    "eta_label": "2m",
                },
                {
                    "job_id": "signal:technical_analysis",
                    "kind": "signal_lane",
                    "name": "technical_analysis",
                    "dataset": "prices_daily",
                    "signal_lane": "technical_analysis",
                    "status": "DUE_NOW",
                    "eta_label": "3m",
                },
                {
                    "job_id": "dataset:sec_form4",
                    "kind": "dataset",
                    "name": "sec_form4",
                    "dataset": "sec_form4",
                    "status": "RUNNING",
                    "eta_label": "6m",
                },
            ],
            "next_jobs": [],
            "stale_datasets": [],
            "market_phase": "closed_weekend",
        }
    )

    assert view["automation_status"]["label"] == "Automation Status"
    assert view["automation_status"]["status_label"] == "Running"
    assert "scheduler heartbeat" in view["automation_status"]["tooltip"]
    assert view["trading_freshness_gate"]["label"] == "Trading Freshness Gate"
    assert view["trading_freshness_gate"]["status_label"] == "Context Only"
    workload = view["refresh_workload"]
    assert workload["label"] == "Refresh Workload"
    assert workload["live_critical_due_count"] == 2
    assert workload["support_due_count"] == 1
    assert workload["repair_due_count"] == 1
    assert workload["running_count"] == 1
    assert workload["next_live_eta_label"] == "3m"
    assert "support and repair jobs" in workload["tooltip"]


def test_scheduler_work_queue_view_translates_massive_lanes_for_users() -> None:
    view = command_module.scheduler_work_queue_view(
        {
            "summary": {
                "headline": "Scheduler queue is clear enough for paper trading.",
                "counts": {"due_now": 0, "running": 0},
            },
            "ticker_tiers": {"tiers": {}},
            "tradability": {
                "status_label": "Tradable",
                "status_class": "pass",
                "detail": "Broker and critical evidence are fresh.",
            },
            "repair_plan": {"jobs": []},
            "execution_freshness_gate": {"checks": []},
            "scheduler_runtime": {
                "status_label": "Running",
                "status_class": "pass",
                "detail": "Automatic lane refresh is running.",
            },
            "massive_orchestrator": {
                "status_label": "Due Now",
                "status_class": "warn",
                "detail": "Run due Massive raw acquisition lane.",
                "lanes": [
                    {
                        "lane_id": "massive_daily_bars",
                        "label": "Massive Daily Bars",
                        "status": "SKIPPED",
                        "status_class": "neutral",
                        "blocks_execution": True,
                        "raw_source_dataset": "prices_daily",
                        "acquisition_mode": "massive_api",
                        "manifest_status": "complete",
                        "manifest_coverage_pct": 100,
                        "health_status": "COMPLETE",
                        "health_freshness": "UNKNOWN",
                        "health_status_class": "warn",
                        "ticker_count": 168,
                        "fresh_ticker_count": 0,
                        "pending_ticker_count": 168,
                        "request_budget_label": "1 grouped-daily request per market date",
                        "reason": "Daily bars already loaded.",
                    },
                    {
                        "lane_id": "massive_premarket_trade_slices",
                        "label": "Massive Pre-Market Trade Slices",
                        "status": "DUE_NOW",
                        "status_class": "warn",
                        "blocks_execution": True,
                        "raw_source_dataset": "stock_trades",
                        "acquisition_mode": "massive_api",
                        "manifest_status": "partial_usable",
                        "manifest_coverage_pct": 100,
                        "health_status": "PARTIAL_USABLE",
                        "health_freshness": "PARTIAL",
                        "health_status_class": "warn",
                        "ticker_count": 36,
                        "fresh_ticker_count": 13,
                        "pending_ticker_count": 23,
                        "batch_ticker_count": 23,
                        "eta_label": "6m",
                        "request_budget_label": "bounded latest-print pages",
                        "command": ["python", "pull-premarket.py", "--ticker", "AAPL"],
                        "reason": "Pre-market activity needs refresh.",
                    },
                    {
                        "lane_id": "massive_options_flow",
                        "label": "Massive Options Flow",
                        "status": "DISABLED",
                        "status_class": "neutral",
                        "blocks_execution": False,
                        "raw_source_dataset": "options_chains",
                        "acquisition_mode": "massive_api",
                        "manifest_status": "missing",
                        "manifest_coverage_pct": 0,
                        "health_status": "UNAVAILABLE",
                        "health_freshness": "UNAVAILABLE",
                        "health_status_class": "warn",
                        "ticker_count": 36,
                        "request_budget_label": "options endpoint budget",
                        "reason": "Options endpoint not enabled.",
                    },
                ],
                "derived_signal_lanes": [
                    {
                        "label": "Pre Market Unusual Activity",
                        "signal_lane": "pre_market_unusual_activity",
                        "status": "WAITING",
                        "status_class": "neutral",
                        "requires_raw_lanes": ["massive_premarket_trade_slices"],
                        "reason": "Waiting for Massive raw lane.",
                    }
                ],
            },
            "jobs": [],
            "next_jobs": [],
            "stale_datasets": [],
            "market_phase": "closed_weekend",
        }
    )

    massive = view["massive_orchestrator"]
    summary = massive["lane_summary"]
    assert summary["execution_ready_count"] == 1
    assert summary["execution_needs_refresh_count"] == 1
    assert summary["research_disabled_count"] == 1

    daily, premarket, options = view["massive_lane_rows"]
    assert daily["display_status_label"] == "Loaded / No Pull Needed"
    assert daily["display_health_label"] == "Health Check Needed"
    assert daily["coverage_label"] == "Manifest complete / 100% coverage"
    assert daily["show_live_ticker_progress"] is False
    assert daily["impact_label"] == "Execution-critical"
    assert daily["refresh_enabled"] is False
    assert daily["refresh_button_label"] == "Refresh Daily Bars"
    assert "policy" in daily["refresh_tooltip"].lower()

    assert premarket["display_status_label"] == "Refresh Due"
    assert premarket["display_health_label"] == "Usable With Gaps"
    assert premarket["coverage_label"] == "13 fresh / 23 pending"
    assert premarket["show_live_ticker_progress"] is True
    assert premarket["action_label"] == "Run lane refresh"
    assert premarket["refresh_enabled"] is True
    assert (
        premarket["refresh_action_url"]
        == "/scheduler/massive-lanes/massive_premarket_trade_slices/refresh"
    )
    assert premarket["refresh_button_label"] == "Refresh Premarket Trade Slices"
    assert "23 ticker" in premarket["refresh_scope_label"]

    assert options["display_status_label"] == "Disabled / Entitlement Not Verified"
    assert options["impact_label"] == "Optional / entitlement"
    assert options["bucket_label"] == "Research / Disabled / Not Entitled"
    assert options["refresh_enabled"] is False
    assert options["refresh_button_label"] == "Refresh Options Flow"

    signal = view["massive_signal_rows"][0]
    assert signal["impact_label"] == "Execution-critical signal"
    assert "blocks or weakens paper-trading evidence" in signal["impact_detail"]


def test_manual_massive_lane_refresh_endpoint_schedules_background_task(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_queue_context() -> dict[str, object]:
        raise AssertionError("refresh route should not block on scheduler queue rendering")

    def fake_refresh(lane_id: str, **kwargs: object) -> dict[str, object]:
        calls.append((lane_id, kwargs))
        return {"state": "completed", "lane_id": lane_id}

    monkeypatch.setattr(dashboard_module, "run_manual_massive_lane_refresh", fake_refresh)
    monkeypatch.setattr(
        dashboard_module,
        "scheduler_work_queue_raw_context",
        fake_queue_context,
    )

    response = TestClient(create_app()).post(
        "/scheduler/massive-lanes/massive_live_trade_slices/refresh",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"] == "/#scheduler-heading"
    assert calls == [("massive_live_trade_slices", {})]


def test_manual_dataset_refresh_endpoint_schedules_background_task(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_refresh(dataset: str, **kwargs: object) -> dict[str, object]:
        calls.append(dataset)
        return {"state": "completed", "dataset": dataset}

    monkeypatch.setattr(dashboard_module, "run_manual_dataset_refresh", fake_refresh)

    response = TestClient(create_app()).post(
        "/scheduler/datasets/news_rss/refresh",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"] == "/#scheduler-heading"
    assert calls == ["news_rss"]


def test_subscription_email_login_refresh_endpoint_opens_interactive_flow(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_launch(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"state": "started"}

    monkeypatch.setattr(
        dashboard_module,
        "launch_subscription_email_login_refresh",
        fake_launch,
    )

    response = TestClient(create_app()).post(
        "/scheduler/subscription-emails/login-refresh",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"] == "/#scheduler-heading"
    assert calls == [{}]


def test_execution_preview_page_exposes_daily_bars_refresh_when_gate_blocks(
    monkeypatch: MonkeyPatch,
) -> None:
    execution_gate = {
        "ready": False,
        "status_label": "Blocked",
        "status_class": "block",
        "detail": "daily-market-bars source-health row is old; refresh critical evidence.",
        "checks": [],
    }
    broker = {
        "connected": True,
        "mode": "paper",
        "checked_at": datetime.now(UTC).isoformat(),
        "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
        "positions": [],
        "orders": [],
        "gross_exposure_pct": 0.0,
        "status_class": "pass",
        "detail": "paper broker connected",
    }

    async def fake_execution_preview_context() -> dict[str, object]:
        return {
            "summary": execution_module.execution_preview_summary(
                [],
                broker=broker,
                policy=PortfolioPolicy(broker_submit_enabled=True),
                execution_gate=execution_gate,
            ),
            "broker": broker,
            "preview_rows": [],
            "orderable_rows": [],
            "review_only_rows": [],
            "approved_review_only_rows": [],
            "blocked_rows": [],
            "data_health": None,
            "execution_freshness_gate": execution_gate,
            "leveraged_alternatives": execution_module.leveraged_alternative_panel([]),
        }

    monkeypatch.setattr(
        dashboard_module,
        "execution_preview_context",
        fake_execution_preview_context,
    )

    response = TestClient(create_app()).get("/execution-preview")

    assert response.status_code == HTTP_OK
    assert (
        'method="post" action="/scheduler/massive-lanes/massive_daily_bars/refresh"'
        in response.text
    )
    assert ">Refresh Daily Bars</button>" in response.text


def test_full_live_readiness_view_uses_plain_readiness_and_tooltip_labels() -> None:
    view = command_module.full_live_readiness_view(
        {
            "status_label": "Ready With Partial Lanes",
            "status_class": "warn",
            "review_operational_ready": True,
            "tradable_ready": False,
            "detail": "Core data is usable, but paper trading is gated.",
            "verdict": "ready_with_partial_lanes",
            "coverage": {
                "overall_percent": 97,
                "core_dataset_percent": 100,
                "critical_lane_percent": 92,
                "expected_ticker_count": 168,
                "signal_count": 1430,
                "market_flow_status_label": "Live Market Flow Ready",
                "critical_source_blocker_count": 1,
                "source_warning_count": 6,
                "source_headline": "Critical source needs refresh: Daily Market Bars",
                "fresh_source_count": 0,
                "source_count": 7,
                "stale_source_count": 1,
                "agent_ready_count": 0,
                "agent_warning_count": 11,
                "agent_blocked_count": 2,
                "agent_total_count": 13,
                "critical_agent_ready_label": "0/7 critical lanes",
            },
            "active_refresh": {
                "state": "running",
                "status_label": "Loading",
                "status_class": "warn",
                "running_dataset": "sec_form4",
                "eta_label": "10m",
                "dataset_rows": [
                    {
                        "dataset": "sec_form4",
                        "status": "running",
                        "reason": "refresh command running",
                        "extraction_action": "baseline",
                    }
                ],
            },
            "provider_usage": [],
            "next_actions": [],
            "blockers": [],
            "warnings": [],
        }
    )

    assert view["mode_label"] == "Review Ready"
    assert view["trading_gate_label"] == "Paper Trading Gated"
    assert view["mode_summary"] == "Review Ready · Paper Trading Gated"
    assert view["command_map"]["system"]["label"] == "Agency Mode"
    assert view["command_map"]["system"]["value"] == "Review Ready · Paper Trading Gated"
    assert view["command_map"]["freshness"]["label"] == "Freshness Proof"
    assert view["command_map"]["freshness"]["value"] == "Health proof needs refresh"
    assert view["command_map"]["agents"]["label"] == "Signal Worker Readiness"
    assert view["command_map"]["agents"]["value"] == "0/7 fully ready · 5/7 usable with warnings"
    assert view["command_map"]["loading"]["label"] == "Active Refresh"
    assert view["command_map"]["loading"]["value"] == "Support refresh running"
    assert "tooltip" in view["command_map"]["freshness"]
    assert "review can continue" in str(view["command_map"]["loading"]["detail"]).lower()


def test_full_live_readiness_view_never_marks_gated_review_ready() -> None:
    view = command_module.full_live_readiness_view(
        {
            "status_label": "Loading",
            "status_class": "warn",
            "review_operational_ready": False,
            "tradable_ready": False,
            "detail": "Daily bars are stale.",
            "verdict": "loading",
            "readiness_scope": "loading",
            "coverage": {
                "overall_percent": 97,
                "core_dataset_percent": 100,
                "critical_lane_percent": 92,
                "expected_ticker_count": 168,
                "signal_count": 1430,
                "market_flow_status_label": "Live Market Flow Ready",
                "critical_source_blocker_count": 1,
                "source_warning_count": 6,
                "source_headline": "Critical source needs refresh: Daily Market Bars",
                "fresh_source_count": 0,
                "source_count": 7,
                "stale_source_count": 1,
                "agent_ready_count": 0,
                "agent_warning_count": 11,
                "agent_blocked_count": 2,
                "agent_total_count": 13,
                "critical_agent_ready_label": "0/7 critical lanes",
            },
            "active_refresh": {
                "state": "running",
                "status_label": "Loading",
                "status_class": "warn",
                "running_dataset": "sec_form4",
                "eta_label": "10m",
                "dataset_rows": [
                    {
                        "dataset": "sec_form4",
                        "status": "running",
                        "reason": "refresh command running",
                    }
                ],
            },
            "provider_usage": [],
            "next_actions": ["Fix prices_daily before review."],
            "blockers": [
                {
                    "kind": "Data",
                    "item": "prices_daily",
                    "reason": "Daily bars are stale.",
                }
            ],
            "warnings": [],
        }
    )

    assert view["mode_label"] == "Review Gated"
    assert view["trading_gate_label"] == "Paper Trading Gated"
    assert view["mode_summary"] == "Review Gated · Paper Trading Gated"
    assert view["command_map"]["system"]["value"] == "Review Gated · Paper Trading Gated"
    assert "Daily bars need refresh" in view["blocking_reason_label"]


def test_source_status_rows_add_status_classes() -> None:
    rows = source_status_rows([_source_health("sec-edgar"), _degraded_source_health()])

    assert rows[0]["status_class"] == "pass"
    assert rows[0]["reliability_pct"] == FULL_RELIABILITY_PERCENT
    assert rows[1]["status_class"] == "warn"
    assert rows[1]["reliability_pct"] == 0


def test_source_status_rows_do_not_pass_old_health_snapshots() -> None:
    old_source = _source_health("daily-market-bars")
    old_source["checked_at"] = "2000-01-01T00:00:00Z"

    rows = source_status_rows([old_source])

    assert rows[0]["status_class"] == "block"


def test_source_status_rows_explain_refresh_needed_without_raw_stale_label() -> None:
    source = _source_health("rss-news")
    source["status"] = "STALE"
    source["freshness"] = "STALE"

    rows = source_status_rows([source])

    assert rows[0]["status"] == "Needs refresh"
    assert rows[0]["freshness"] == "Needs refresh"
    assert rows[0]["raw_status"] == "STALE"
    assert rows[0]["raw_freshness"] == "STALE"


def test_active_refresh_value_explains_stale_monitor_as_needing_attention() -> None:
    active_refresh = {
        "state": "stale",
        "current_dataset": "stock_trades",
        "eta_label": "not available",
    }

    assert command_module._active_refresh_value(active_refresh) == "Refresh needs attention"
    assert "needs attention" in command_module._active_refresh_detail(active_refresh, "stale")
    assert "state stale" not in command_module._active_refresh_detail(active_refresh, "stale")


def test_massive_lane_refresh_scope_keeps_lane_scope_separate_from_next_batch() -> None:
    label = command_module._massive_lane_refresh_scope_label(
        {"ticker_count": 168, "command_ticker_count": 2}
    )

    assert label == "168 planned ticker(s); next safe batch 2 ticker(s)"


def test_source_health_kpi_distinguishes_unavailable_from_health_proof_refresh() -> None:
    view = command_module.data_load_status_view(
        {
            "overall_percent": 100,
            "expected_ticker_count": 1,
            "signal_count": 0,
            "datasets": [],
            "lanes": [],
            "blockers": [],
            "warnings": [],
            "freshness_rows": [
                {
                    "source": "massive-stock-trades",
                    "label": "Massive Stock Trades",
                    "status": "UNAVAILABLE",
                    "freshness": "UNAVAILABLE",
                    "status_class": "block",
                    "detail": "massive_live_trade_slices lane manifest is missing.",
                    "critical": True,
                    "checked_at": "not checked",
                }
            ]
        }
    )

    assert view["source_health_kpi"]["short_detail"] == "data source unavailable"
    assert "health proof needs refresh" not in str(view["source_health_kpi"]).lower()


def test_readiness_view_adds_status_classes() -> None:
    view = readiness_view(
        {
            "ready": False,
            "verdict": "context_only_source_health",
            "blockers": [
                {
                    "kind": "source_health",
                    "item": "activity-alerts",
                    "reason": "UNAVAILABLE",
                }
            ],
        }
    )

    assert view["verdict_label"] == "Context Only Source Health"
    assert view["status_class"] == "warn"
    assert view["blocker_rows"] == [
        {
            "kind": "Source Health",
            "item": "activity-alerts",
            "reason": "UNAVAILABLE",
            "status_class": "warn",
        }
    ]


def test_data_refresh_progress_view_adds_width_style() -> None:
    view = data_refresh_progress_view(
        {
            "percent_complete": 42,
            "state": "running",
            "status_label": "Loading",
            "status_class": "warn",
        }
    )

    assert view["progress_style"] == "width: 42%"


def test_data_refresh_progress_view_explains_failed_support_refresh() -> None:
    view = data_refresh_progress_view(
        {
            "state": "failed",
            "status_label": "Failed",
            "status_class": "block",
            "percent_complete": 100,
            "completed_jobs": 1,
            "total_jobs": 1,
            "current_dataset": "sec_company_facts",
            "eta_label": "not available",
            "detail": "Latest data refresh failed before all datasets loaded.",
            "has_failures": True,
            "failed_datasets": ["sec_company_facts"],
        }
    )

    assert view["display_status_label"] == "Failed - Support"
    assert view["display_status_class"] == "warn"
    assert view["display_progress_label"] == "Failed after 1/1 jobs"
    assert view["refresh_impact"]["label"] == "Support/context failed"
    assert "does not automatically block paper orders" in view["refresh_impact"]["detail"]
    assert "rerun the support refresh" in view["next_action_label"]


def test_data_refresh_progress_view_explains_running_support_refresh() -> None:
    view = data_refresh_progress_view(
        {
            "state": "running",
            "status_label": "Loading",
            "status_class": "warn",
            "percent_complete": 0,
            "completed_jobs": 0,
            "total_jobs": 1,
            "current_dataset": "sec_form4",
            "eta_label": "10m",
        }
    )

    assert view["display_status_label"] == "Refreshing"
    assert view["refresh_impact"]["label"] == "Support refresh running"
    assert view["refresh_impact"]["status_class"] == "neutral"
    assert "does not block paper orders" in view["refresh_impact"]["detail"]


def test_data_refresh_progress_view_hides_raw_stale_state_from_dom() -> None:
    view = data_refresh_progress_view(
        {
            "state": "stale",
            "status_label": "Stale",
            "status_class": "block",
            "percent_complete": 25,
            "current_dataset": "prices_daily",
        }
    )

    assert view["display_status_label"] == "Refresh monitor needs restart"
    assert view["display_state"] == "needs_refresh"
    assert "stale" not in str(view["display_state"]).lower()


def test_data_refresh_progress_view_translates_massive_lane_progress() -> None:
    view = data_refresh_progress_view(
        {
            "state": "idle",
            "status_label": "Idle",
            "status_class": "neutral",
            "percent_complete": 0,
            "massive_lanes": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "label": "Massive Live Trade Slices",
                    "state": "partial_usable",
                    "status_label": "Usable Partial",
                    "status_class": "warn",
                    "percent_complete": 100,
                    "progress_label": "24/24 usable",
                    "row_count_label": "1,239,948",
                    "updated_at": "2026-05-16T19:06:39+00:00",
                    "window_label": "latest session",
                    "manifest_status": "partial_usable",
                    "manifest_coverage_pct": 100,
                    "detail": "Manifest reports partial_usable.",
                },
                {
                    "lane_id": "massive_options_flow",
                    "label": "Massive Options Flow",
                    "state": "missing_manifest",
                    "status_label": "Manifest Missing",
                    "status_class": "warn",
                    "percent_complete": 0,
                    "progress_label": "not tracked",
                    "row_count_label": "0",
                    "updated_at": "not recorded",
                    "window_label": "not recorded",
                    "manifest_status": "missing",
                    "manifest_coverage_pct": 0,
                    "detail": "No manifest yet.",
                },
            ],
        }
    )

    live_lane, options_lane = view["massive_lanes"]

    assert live_lane["display_status_label"] == "Usable With Gaps"
    assert live_lane["display_status_class"] == "warn"
    assert live_lane["impact_label"] == "Execution-critical"
    assert "paper-order readiness" in live_lane["tooltip"]
    assert options_lane["display_status_label"] == "Disabled / Entitlement Not Verified"
    assert options_lane["impact_label"] == "Optional / entitlement"


def test_command_progress_widths_are_bounded() -> None:
    progress = data_refresh_progress_view(
        {
            "percent_complete": 142,
            "state": "running",
            "status_label": "Loading",
            "status_class": "warn",
            "trade_pull": {"percent_complete": -12},
        }
    )
    load_status = data_load_status_view(
        {
            "overall_percent": 125,
            "datasets": [
                {
                    "label": "Daily bars",
                    "dataset": "prices_daily",
                    "group": "core",
                    "coverage_pct": -5,
                    "loaded_ticker_count": 0,
                    "expected_ticker_count": 2,
                }
            ],
            "lanes": [],
            "blockers": [],
            "warnings": [],
        }
    )

    assert progress["progress_style"] == "width: 100%"
    assert progress["trade_pull"]["progress_style"] == "width: 0%"
    assert load_status["progress_style"] == "width: 100%"
    assert load_status["dataset_rows"][0]["coverage_style"] == "width: 0%"


def test_data_load_status_view_prepares_dashboard_rows() -> None:
    view = data_load_status_view(
        {
            "overall_percent": 88,
            "datasets": [
                {
                    "label": "Daily bars",
                    "dataset": "prices_daily",
                    "group": "core",
                    "coverage_pct": 100,
                    "loaded_ticker_count": 2,
                    "expected_ticker_count": 2,
                    "row_count": 20,
                }
            ],
            "lanes": [
                {
                    "label": "Abnormal Volume",
                    "lane": "abnormal_volume",
                    "group": "critical",
                    "coverage_pct": 50,
                    "produced_count": 1,
                    "expected_count": 2,
                }
            ],
            "blockers": [],
            "warnings": [{"kind": "agent_lane", "item": "news", "reason": "stale"}],
        }
    )

    assert view["progress_style"] == "width: 88%"
    assert view["dataset_rows"][0]["count_label"] == "2/2 tickers"
    assert view["lane_rows"][0]["coverage_style"] == "width: 50%"
    assert view["issue_rows"][0]["kind"] == "Agent Lane"
    assert view["issue_rows"][0]["status_class"] == "warn"


def test_data_load_status_view_explains_source_health_rows() -> None:
    view = data_load_status_view(
        {
            "overall_percent": 88,
            "datasets": [],
            "lanes": [],
            "freshness_rows": [
                {
                    "source": "daily-market-bars",
                    "label": "Daily Market Bars",
                    "status": "HEALTHY",
                    "freshness": "FRESH",
                    "status_class": "pass",
                    "last_success_at": "2026-05-15T21:00:00+00:00",
                    "checked_at": "2026-05-15T21:00:00+00:00",
                    "critical": True,
                    "detail": "massive_daily_bars lane is HEALTHY / FRESH.",
                },
                {
                    "source": "rss-news",
                    "label": "Rss News",
                    "status": "STALE",
                    "freshness": "STALE",
                    "status_class": "warn",
                    "last_success_at": "2026-05-15T03:17:31+00:00",
                    "checked_at": "2026-05-16T09:43:59+00:00",
                    "critical": False,
                    "detail": "rss-news is STALE with STALE freshness.",
                },
            ],
            "blockers": [],
            "warnings": [],
        }
    )

    daily, news = view["freshness_rows"]
    assert daily["impact_label"] == "Execution-critical"
    assert daily["validity_label"] == "Current and usable"
    assert "No action needed" in daily["next_action"]
    assert "why" in daily["tooltip"].lower()
    assert news["impact_label"] == "Current-context"
    assert news["status"] == "Needs refresh"
    assert news["freshness"] == "Needs refresh"
    assert news["validity_label"] == "Refresh needed"
    assert "Rerun the news refresh" in news["next_action"]
    assert view["source_health_kpi"]["action_detail"] == "Refresh 1 current-context source."
    assert "stale" not in str(view).lower()


def test_live_config_view_exposes_check_rows() -> None:
    view = live_config_view(
        {
            "state": "blocked",
            "checks": [{"label": "Market data", "status": "BLOCK"}],
        }
    )

    assert view["check_rows"][0]["label"] == "Market data"
    assert view["check_rows"][0]["status"] == "BLOCK"
    assert view["check_rows"][0]["category"] == "Provider"
    assert view["check_rows"][0]["impact_label"] == "Execution-critical"
    assert "missing or incomplete" in view["check_rows"][0]["meaning"]


def test_live_config_view_explains_scope_and_check_actions() -> None:
    view = live_config_view(
        {
            "state": "ready",
            "status_label": "Ready",
            "status_class": "pass",
            "config_path": "research/config/live-refresh.local.json",
            "provider": "massive",
            "dataset_count": 7,
            "runtime_signal_count": 13,
            "ticker_count": 168,
            "blocker_count": 0,
            "warning_count": 0,
            "checks": [
                {
                    "label": "Runtime data coverage",
                    "status": "PASS",
                    "status_class": "pass",
                    "detail": "Core datasets cover 168 active universe tickers",
                },
                {
                    "label": "Subscription emails",
                    "status": "PASS",
                    "status_class": "pass",
                    "detail": "gmail configured for 3 service(s); article LLM ready",
                },
                {
                    "label": "Market data",
                    "status": "BLOCK",
                    "status_class": "block",
                    "detail": "Missing MASSIVE_API_KEY or POLYGON_API_KEY",
                },
            ],
        }
    )

    assert view["scope_label"] == "Configuration readiness"
    assert "not data freshness" in view["scope_detail"]
    assert view["runtime_signal_label"] == "13"
    assert "runtime signal lanes" in view["runtime_signals_tooltip"]
    assert "credentials" in view["provider_tooltip"].lower()

    coverage, email, market_data = view["check_rows"]
    assert coverage["category"] == "Coverage"
    assert coverage["impact_label"] == "Execution-critical"
    assert coverage["meaning"] == "Configured core ticker coverage, not freshness proof."
    assert coverage["next_action"] == "Check Agency Data Readiness for freshness."
    assert "not freshness proof" in coverage["tooltip"]
    assert email["category"] == "Email"
    assert email["impact_label"] == "Support/context"
    assert email["next_action"] == "No action; email configuration is usable."
    assert market_data["category"] == "Provider"
    assert market_data["impact_label"] == "Execution-critical"
    assert market_data["next_action"] == "Add the required provider key in .env."


def test_provider_readiness_view_adds_provider_rows() -> None:
    view = provider_readiness_view(
        {
            "provider_count": 2,
            "configured_count": 1,
            "active_required_count": 1,
            "blocker_count": 1,
            "warning_count": 0,
            "status_class": "block",
            "status_label": "Missing Provider Keys",
            "providers": [
                {
                    "label": "Alpaca",
                    "category": "market_data",
                    "purpose": "Daily bars.",
                    "required_now": True,
                    "configured": False,
                    "status": "BLOCK",
                    "status_class": "block",
                    "key_label": "ALPACA_API_KEY, ALPACA_SECRET_KEY",
                    "detail": "Required now.",
                },
                {
                    "label": "FRED",
                    "category": "macro",
                    "purpose": "Macro data.",
                    "required_now": False,
                    "configured": True,
                    "status": "PASS",
                    "status_class": "pass",
                    "key_label": "FRED_API_KEY",
                    "detail": "Configured.",
                }
            ],
        }
    )

    row = view["provider_rows"][0]
    assert row["required_label"] == "Active required"
    assert row["category"] == "Market Data"
    assert view["configured_label"] == "1/2 total configured"
    assert view["required_label"] == "0/1 required ready"
    assert view["planned_label"] == "1 planned provider configured"


def test_provider_readiness_view_explains_scope_actions_and_secret_state() -> None:
    view = provider_readiness_view(
        {
            "provider_count": 4,
            "configured_count": 1,
            "active_required_count": 2,
            "blocker_count": 1,
            "warning_count": 0,
            "status_class": "block",
            "status_label": "Missing Provider Keys",
            "providers": [
                {
                    "id": "alpaca",
                    "label": "Alpaca",
                    "category": "market_data_broker",
                    "purpose": "Paper broker account, positions, and order submission.",
                    "required_now": True,
                    "configured": False,
                    "status": "BLOCK",
                    "status_class": "block",
                    "key_label": "ALPACA_API_KEY, ALPACA_SECRET_KEY",
                    "detail": "Required now.",
                    "keys": [
                        {"name": "ALPACA_API_KEY", "present": False},
                        {"name": "ALPACA_SECRET_KEY", "present": False},
                    ],
                },
                {
                    "id": "polygon_massive",
                    "label": "Polygon or Massive",
                    "category": "market_flow",
                    "purpose": "Market-flow pressure.",
                    "required_now": True,
                    "configured": True,
                    "status": "PASS",
                    "status_class": "pass",
                    "key_label": "POLYGON_API_KEY or MASSIVE_API_KEY",
                    "detail": "Configured.",
                    "keys": [
                        {"name": "POLYGON_API_KEY", "present": True},
                        {"name": "MASSIVE_API_KEY", "present": False},
                    ],
                },
                {
                    "id": "fred",
                    "label": "FRED",
                    "category": "macro",
                    "purpose": "Macro regime context.",
                    "required_now": False,
                    "configured": False,
                    "status": "PLANNED",
                    "status_class": "neutral",
                    "key_label": "FRED_API_KEY",
                    "detail": "Planned provider.",
                    "keys": [{"name": "FRED_API_KEY", "present": False}],
                },
                {
                    "id": "finra",
                    "label": "FINRA OTC Transparency",
                    "category": "market_structure",
                    "purpose": "Market-structure context.",
                    "required_now": False,
                    "configured": True,
                    "status": "PASS",
                    "status_class": "pass",
                    "key_label": "No key required",
                    "detail": "No local API key is expected.",
                    "keys": [],
                },
            ],
        }
    )

    assert view["scope_label"] == "Credential readiness"
    assert "does not prove live API connectivity or data freshness" in view["scope_detail"]
    assert "all tracked providers" in view["configured_tooltip"]
    assert "today's configured workflow" in view["required_ready_tooltip"]
    assert "block paper flow" in view["missing_required_tooltip"]
    assert "roadmap" in view["planned_optional_tooltip"]

    rows = {row["label"]: row for row in view["provider_rows"]}
    assert rows["Alpaca"]["required_label"] == "Active required"
    assert rows["Alpaca"]["impact_label"] == "Execution-critical broker/provider"
    assert rows["Alpaca"]["secret_status_label"] == "Missing required keys"
    assert rows["Alpaca"]["next_action"] == (
        "Add ALPACA_API_KEY, ALPACA_SECRET_KEY in .env before broker submission."
    )
    assert "required by today's workflow" in rows["Alpaca"]["tooltip"]

    assert rows["Polygon or Massive"]["secret_status_label"] == "Credential available"
    assert "one configured provider" in rows["Polygon or Massive"]["next_action"]
    assert rows["FRED"]["required_label"] == "Planned optional"
    assert rows["FRED"]["impact_label"] == "Optional/roadmap"
    assert rows["FRED"]["secret_status_label"] == "Missing optional key"
    assert rows["FRED"]["next_action"] == (
        "No action for today; add FRED_API_KEY only when enabling this roadmap provider."
    )
    assert rows["FINRA OTC Transparency"]["secret_status_label"] == "No key required"
    assert rows["FINRA OTC Transparency"]["next_action"] == "No credential action required."


def test_provider_readiness_requires_alpaca_when_paper_broker_enabled(
    monkeypatch: MonkeyPatch,
) -> None:
    from agency.runtime.provider_readiness import load_provider_readiness

    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("AGENCY_ENABLE_LLM_REVIEW", "false")
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("MASSIVE_API_KEY", "massive-key")

    readiness = load_provider_readiness(
        {
            "provider": "massive",
            "checks": [
                {"label": "SEC User-Agent", "status": "PASS"},
                {"label": "Massive market-flow", "status": "PASS"},
            ],
        }
    )

    providers = {row["id"]: row for row in readiness["providers"]}
    assert providers["alpaca"]["required_now"] is True
    assert providers["alpaca"]["configured"] is True
    assert readiness["active_required_count"] == 3


def test_final_selection_rows_follow_service_contract() -> None:
    report = build_final_selection(_evidence_pack()).selection_report

    rows = final_selection_rows([report])

    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["action"] == "WATCH"
    assert rows[0]["deterministic_action"] == "WATCH"
    assert rows[0]["llm_action"] == "NO_REVIEW"
    assert rows[0]["llm_status_label"] == "Skipped By Policy"
    assert rows[0]["llm_status_detail"] == "LLM review is not enabled for this run."
    assert rows[0]["confirmed_signal_count"] == EXPECTED_CONFIRMED_SIGNAL_COUNT
    assert rows[0]["policy_gates"][0]["status"] == "PASS"
    assert rows[0]["decision_explanation"].startswith("The final action is WATCH")
    assert rows[0]["actionable_signals"][0]["summary"] == (
        "Fundamental metrics are constructive."
    )
    assert rows[0]["actionable_signals"][0]["score"] == "+0.70 bullish"


def test_final_selection_freshness_gate_shows_timestamp_proof() -> None:
    report = build_final_selection(_evidence_pack()).selection_report

    rows = final_selection_rows([report])

    freshness_gate = next(gate for gate in rows[0]["policy_gates"] if gate["name"] == "freshness")
    assert "Data as of 2026-05-07 09:30 UTC" in freshness_gate["meaning"]
    assert "report generated 2026-05-07 09:31 UTC" in freshness_gate["meaning"]
    assert "No refresh is needed only while those timestamps remain current" in freshness_gate["next_step"]
    assert rows[0]["freshness_proof_label"] == (
        "Data as of 2026-05-07 09:30 UTC; report generated 2026-05-07 09:31 UTC."
    )
    assert rows[0]["provenance_items"] == [
        {"label": "Generated", "value": "2026-05-07 09:31 UTC"},
        {"label": "Data as of", "value": "2026-05-07 09:30 UTC"},
        {"label": "Cycle", "value": "cycle-1"},
    ]


def test_final_selection_rows_sort_by_conviction_descending() -> None:
    low = _selection_report_for_cycle(
        "live-pit-current",
        "AAPL",
        "2026-05-07T09:31:00Z",
    )
    high = _selection_report_for_cycle(
        "live-pit-current",
        "MSFT",
        "2026-05-07T09:31:00Z",
    )
    high_tie = _selection_report_for_cycle(
        "live-pit-current",
        "AMZN",
        "2026-05-07T09:31:00Z",
    )
    low["final_conviction"] = 0.42
    high["final_conviction"] = 0.91
    high_tie["final_conviction"] = 0.91

    rows = final_selection_rows([low, high, high_tie])

    assert [row["ticker"] for row in rows] == ["AMZN", "MSFT", "AAPL"]
    assert [row["conviction_pct"] for row in rows] == [91, 91, 42]


def test_candidate_detail_report_rows_sort_by_latest_generated_at() -> None:
    old_high = _selection_report_for_cycle(
        "live-pit-old",
        "AAPL",
        "2026-05-07T09:31:00Z",
    )
    new_low = _selection_report_for_cycle(
        "live-pit-new",
        "AAPL",
        "2026-05-08T09:31:00Z",
    )
    old_high["final_conviction"] = 0.95
    old_high["generated_at"] = "2026-05-07T09:32:00Z"
    new_low["final_conviction"] = 0.40
    new_low["generated_at"] = "2026-05-08T09:32:00Z"

    rows = candidate_detail_report_rows([old_high, new_low])

    assert rows[0]["cycle_id"] == "live-pit-new"
    assert rows[0]["conviction_pct"] == 40


def test_signal_dashboard_rows_group_sort_and_summarize_lanes() -> None:
    selection_rows = final_selection_rows([_selection_report_with_signal_mix()])

    rows = signal_dashboard_rows(selection_rows)
    promotion = {
        "lanes": [
            _promotion_lane("fundamentals", "action_weighted"),
            _promotion_lane("technical_analysis", "corroborating"),
            _promotion_lane("news", "context_only"),
        ]
    }
    lane_rows = signal_lane_rows(rows, promotion)
    summary = signal_dashboard_summary(
        signal_rows=rows,
        lane_rows=lane_rows,
        cycle_id="live-pit-current",
        report_count=1,
    )

    assert [row["bucket"] for row in rows] == ["Actionable", "Context", "Suppressed"]
    assert [row["lane_key"] for row in rows] == [
        "fundamentals",
        "technical_analysis",
        "news",
    ]
    assert rows[0]["candidate_href"] == "/candidates/MSFT"
    assert rows[0]["source"] == "Sec Edgar / Official Filing"
    assert "Fundamentals produced a bullish signal for MSFT" in str(
        rows[0]["interpretation_text"]
    )
    assert "Included in the latest MSFT evidence pack" in str(
        rows[0]["decision_effect_text"]
    )
    assert "Supports the current WATCH posture for MSFT" in str(
        rows[0]["decision_alignment_text"]
    )
    assert "Confirmed evidence" in str(rows[0]["quality_text"])
    assert "source id fundamentals-msft" in str(rows[0]["provenance_text"])
    assert "2026-05-07 08:59 UTC" in str(rows[0]["provenance_text"])
    assert "T08:59:00" not in str(rows[0]["provenance_text"])
    assert rows[1]["actionability_label"] == "Context Only"
    assert "guarded from direct scoring" in str(rows[1]["decision_effect_text"])
    assert rows[2]["freshness_class"] == "pass"
    assert "Excluded from the latest MSFT decision score" in str(
        rows[2]["decision_effect_text"]
    )
    assert lane_rows[0]["lane_key"] == "fundamentals"
    assert lane_rows[0]["actionable_count"] == 1
    assert lane_rows[1]["lane_key"] == "news"
    assert lane_rows[1]["suppressed_count"] == 1
    assert lane_rows[2]["lane_key"] == "technical_analysis"
    assert lane_rows[2]["context_count"] == 1
    assert summary["signal_count"] == EXPECTED_SIGNAL_DASHBOARD_ROW_COUNT
    assert summary["actionable_count"] == 1
    assert summary["context_count"] == 1
    assert summary["suppressed_count"] == 1
    assert summary["lanes_with_data"] == EXPECTED_SIGNAL_DASHBOARD_ROW_COUNT


async def test_signals_context_uses_full_cycle_report_limit(
    monkeypatch: MonkeyPatch,
) -> None:
    current_reports = [
        _selection_report_for_cycle(
            "live-pit-current",
            f"T{index:03}",
            "2026-05-07T09:31:00Z",
        )
        for index in range(EXPECTED_SIGNAL_CONTEXT_REPORT_COUNT)
    ]
    older_report = _selection_report_for_cycle(
        "live-pit-older",
        "OLD",
        "2026-05-06T09:31:00Z",
    )

    async def fake_reports(
        *,
        limit: int = EXPECTED_SIGNALS_REPORT_LIMIT,
    ) -> list[dict[str, object]]:
        assert limit == EXPECTED_SIGNALS_REPORT_LIMIT
        return [*current_reports, older_report]

    def passthrough_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        return list(rows)

    monkeypatch.setattr(shared_module, "runtime_selection_reports", fake_reports)
    monkeypatch.setattr(
        signals_module,
        "enrich_signal_rows_with_evidence",
        passthrough_rows,
    )
    monkeypatch.setattr(
        signals_module,
        "load_live_config_readiness",
        lambda: {"runtime_signals": ["fundamentals"]},
    )
    monkeypatch.setattr(
        signals_module,
        "load_lane_promotion_status",
        lambda _signals: {"lanes": [_promotion_lane("fundamentals", "action_weighted")]},
    )

    context = await signals_module.signals_context()

    assert context["summary"]["cycle_id"] == "live-pit-current"
    assert context["summary"]["report_count"] == EXPECTED_SIGNAL_CONTEXT_REPORT_COUNT
    assert context["lane_rows"][0]["signal_count"] == EXPECTED_SIGNAL_CONTEXT_REPORT_COUNT
    assert len(context["signal_rows"]) == EXPECTED_SIGNALS_RENDER_LIMIT
    assert context["summary"]["signal_count"] > EXPECTED_SIGNALS_RENDER_LIMIT
    assert context["summary"]["visible_signal_count"] == EXPECTED_SIGNALS_RENDER_LIMIT
    assert context["summary"]["is_limited"] is True


async def test_final_selection_context_filters_to_latest_live_cycle(
    monkeypatch: MonkeyPatch,
) -> None:
    current_aapl = _selection_report_for_cycle(
        "live-pit-current",
        "AAPL",
        "2026-05-07T09:31:00Z",
    )
    current_msft = _selection_report_for_cycle(
        "live-pit-current",
        "MSFT",
        "2026-05-07T09:31:00Z",
    )
    older_nvda = _selection_report_for_cycle(
        "live-pit-older",
        "NVDA",
        "2026-05-06T09:31:00Z",
    )

    async def fake_reports(
        *,
        limit: int = EXPECTED_FINAL_SELECTION_REPORT_LIMIT,
    ) -> list[dict[str, object]]:
        assert limit == EXPECTED_FINAL_SELECTION_REPORT_LIMIT
        return [current_aapl, current_msft, older_nvda]

    monkeypatch.setattr(shared_module, "runtime_selection_reports", fake_reports)

    context = await final_selection_context()

    assert [row["ticker"] for row in context["final_rows"]] == ["AAPL", "MSFT"]
    summary = context["summary"]
    assert summary["report_count"] == EXPECTED_LATEST_CYCLE_REPORT_COUNT
    assert summary["all_report_count"] == EXPECTED_ALL_SELECTION_REPORT_COUNT
    assert summary["historical_count"] == EXPECTED_HISTORICAL_SELECTION_REPORT_COUNT
    assert summary["cycle_id"] == "live-pit-current"
    assert "older report" in str(summary["scope_detail"])


def test_dashboard_filters_risk_decisions_to_active_cycle() -> None:
    current = {
        "cycle_id": "live-pit-current",
        "ticker": "AAPL",
        "as_of": "2026-05-07T09:30:00Z",
    }
    older = {
        "cycle_id": "live-pit-older",
        "ticker": "AAPL",
        "as_of": "2026-05-06T09:30:00Z",
    }

    filtered = shared_module._risk_decisions_for_reports([older, current], [current])

    assert filtered == [current]


async def test_final_selection_context_prefers_latest_live_ready_cycle(
    monkeypatch: MonkeyPatch,
) -> None:
    live_ready = _selection_report_for_cycle(
        "live-ready-current",
        "AAPL",
        "2026-05-07T09:31:00Z",
    )
    live_pit = _selection_report_for_cycle(
        "live-pit-older",
        "MSFT",
        "2026-05-06T09:31:00Z",
    )

    async def fake_reports(
        *,
        limit: int = EXPECTED_FINAL_SELECTION_REPORT_LIMIT,
    ) -> list[dict[str, object]]:
        assert limit == EXPECTED_FINAL_SELECTION_REPORT_LIMIT
        return [live_ready, live_pit]

    monkeypatch.setattr(shared_module, "runtime_selection_reports", fake_reports)

    context = await final_selection_context()

    assert [row["ticker"] for row in context["final_rows"]] == ["AAPL"]
    assert context["summary"]["cycle_id"] == "live-ready-current"

async def test_final_selection_focus_context_only_enriches_requested_ticker(
    monkeypatch: MonkeyPatch,
) -> None:
    current_aapl = _selection_report_for_cycle(
        "live-pit-current",
        "AAPL",
        "2026-05-07T09:31:00Z",
    )
    current_nvda = _selection_report_for_cycle(
        "live-pit-current",
        "NVDA",
        "2026-05-07T09:31:00Z",
    )
    current_msft = _selection_report_for_cycle(
        "live-pit-current",
        "MSFT",
        "2026-05-07T09:31:00Z",
    )
    seen: dict[str, object] = {}

    async def fake_reports(
        *,
        limit: int = EXPECTED_FINAL_SELECTION_REPORT_LIMIT,
    ) -> list[dict[str, object]]:
        assert limit == EXPECTED_FINAL_SELECTION_REPORT_LIMIT
        return [current_aapl, current_nvda, current_msft]

    async def fake_lifecycle_events(
        reports: Sequence[Mapping[str, object]],
        _readiness: Mapping[str, object],
        *,
        event_type: str,
        limit_per_ticker: int,
    ) -> list[dict[str, object]]:
        seen["lifecycle_tickers"] = [str(report["ticker"]) for report in reports]
        seen["event_type"] = event_type
        seen["limit_per_ticker"] = limit_per_ticker
        return []

    async def fake_risk_decisions(
        *,
        ticker: str | None = None,
        limit: int = EXPECTED_FINAL_SELECTION_REPORT_LIMIT,
        raise_on_unavailable: bool = False,
    ) -> list[dict[str, object]]:
        seen["risk_ticker"] = ticker
        seen["risk_limit"] = limit
        seen["raise_on_unavailable"] = raise_on_unavailable
        return []

    monkeypatch.setattr(shared_module, "runtime_selection_reports", fake_reports)
    monkeypatch.setattr(
        final_selection_module,
        "_lifecycle_events_for_reports",
        fake_lifecycle_events,
    )
    monkeypatch.setattr(
        final_selection_module,
        "_dashboard_risk_decisions",
        fake_risk_decisions,
    )

    context = await final_selection_context(focus_ticker="nvda")

    assert [row["ticker"] for row in context["final_rows"]] == ["NVDA"]
    assert context["summary"]["report_count"] == 3
    assert context["focused_final_selection"]["found"] is True
    assert seen["lifecycle_tickers"] == ["NVDA"]
    assert seen["risk_ticker"] == "NVDA"
    assert seen["risk_limit"] == 1


def test_final_selection_summary_names_latest_cycle_scope() -> None:
    summary = final_selection_summary(
        [],
        all_report_count=2,
        cycle_id="live-pit-2026-05-10-20260510T062128Z",
    )

    assert summary["cycle_label"].endswith("20260510T062128Z")
    assert summary["historical_count"] == EXPECTED_SUMMARY_HISTORICAL_COUNT
    assert "latest-cycle" in str(summary["topbar_label"])


def test_final_selection_topbar_does_not_show_truncated_cycle_id() -> None:
    rows = final_selection_rows([
        _selection_report_for_cycle(
            "live-pit-paper-rehearsal-submit-20260519T201725Z",
            "NVDA",
            "2026-05-19T18:42:00Z",
        )
    ])
    summary = final_selection_summary(
        rows,
        all_report_count=160,
        cycle_id="live-pit-paper-rehearsal-submit-20260519T201725Z",
    )

    assert summary["topbar_label"] == "1 latest-cycle report / read-only"
    assert "...l-submit" not in str(summary["topbar_label"])
    assert "...l-submit" not in str(summary["detail"])
    assert "full cycle id" in str(summary["detail"]).lower()


def test_risk_decision_rows_summarize_risk_contract() -> None:
    decision = _risk_decision()

    rows = risk_decision_rows([decision])
    summary = risk_summary(rows, [_source_health("sec-edgar")])

    assert rows[0]["cycle_id"] == "cycle-1"
    assert rows[0]["decision"] == "ALLOW"
    assert rows[0]["decision_class"] == "pass"
    assert summary["allow_count"] == 1


def test_paper_review_queue_pairs_latest_cycle_with_risk_decision() -> None:
    report = build_final_selection(_evidence_pack()).selection_report
    decision = build_risk_decision(
        report,
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision

    rows = paper_review_queue([report], [decision], {"cycle_id": "cycle-1"})

    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["review_state"] == "Ready"
    assert rows[0]["risk_decision"] == "WARN"
    assert rows[0]["human_review_decision"] == "Pending"
    assert rows[0]["human_review_class"] == "neutral"
    assert rows[0]["candidate_href"] == "/candidates/AAPL?from=final-selection#candidate-AAPL"
    assert "decision=APPROVE" in str(rows[0]["approve_review_action"])
    assert rows[0]["source_count"] == EXPECTED_SOURCE_COUNT
    assert rows[0]["confirmed_signal_count"] == EXPECTED_CONFIRMED_SIGNAL_COUNT


def test_paper_review_queue_requires_caution_acknowledgement_for_watch_warning() -> None:
    report = build_final_selection(_evidence_pack()).selection_report
    report["policy_gates"] = [
        {
            "name": "evidence_breadth",
            "status": "BLOCK",
            "reason": "only one confirmed signal is available",
        }
    ]
    decision = build_risk_decision(
        report,
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision

    rows = paper_review_queue([report], [decision], {"cycle_id": "cycle-1"})

    assert rows[0]["review_state"] == "Ready"
    assert rows[0]["review_class"] == "warn"
    assert rows[0]["caution_acknowledgement_required"] is True
    assert "Caution:" in str(rows[0]["caution_acknowledgement_text"])
    assert "only one confirmed signal" in str(rows[0]["caution_acknowledgement_text"])
    assert "caution_acknowledged=true" not in str(rows[0]["approve_review_action"])


def test_paper_review_queue_shows_latest_human_review_state() -> None:
    report = build_final_selection(_evidence_pack()).selection_report

    rows = paper_review_queue(
        [report],
        [],
        {"cycle_id": "cycle-1"},
        review_events=[_human_review_event()],
    )

    assert rows[0]["human_review_decision"] == "Defer"
    assert rows[0]["human_review_class"] == "warn"
    assert rows[0]["human_review_reason"] == "paper review deferred"
    assert rows[0]["human_review_time_label"] == "2026-05-07 10:00 UTC"


def test_paper_review_progress_counts_review_states() -> None:
    progress = paper_review_progress(
        [
            {"human_review_decision": "pending"},
            {"human_review_decision": "APPROVE"},
            {"human_review_decision": "Defer"},
            {"human_review_decision": "reject"},
        ]
    )

    assert progress["total_count"] == EXPECTED_REVIEW_QUEUE_COUNT
    assert progress["reviewed_count"] == EXPECTED_REVIEWED_COUNT
    assert progress["pending_count"] == 1
    assert progress["approve_count"] == 1
    assert progress["defer_count"] == 1
    assert progress["reject_count"] == 1
    assert progress["reviewed_label"] == "3/4"
    assert progress["status_label"] == "1 Pending"
    assert progress["status_class"] == "warn"


def test_paper_review_progress_reports_complete_state() -> None:
    progress = paper_review_progress(
        [
            {"human_review_decision": "Approve"},
            {"human_review_decision": "Defer"},
        ]
    )

    assert progress["reviewed_label"] == "2/2"
    assert progress["status_label"] == "Review Complete"
    assert progress["status_class"] == "pass"


async def test_human_review_events_for_reports_filters_latest_cycle(
    monkeypatch: MonkeyPatch,
) -> None:
    report = build_final_selection(_evidence_pack()).selection_report

    async def fake_timeline(
        *,
        ticker: str,
        cycle_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        assert ticker == "AAPL"
        assert cycle_id == "cycle-1"
        assert limit == EXPECTED_TIMELINE_LIMIT
        return [_human_review_event(), _lifecycle_event()]

    monkeypatch.setattr(shared_module, "runtime_candidate_timeline", fake_timeline)
    monkeypatch.setattr(
        shared_module,
        "runtime_lifecycle_event_artifacts",
        lambda *, cycle_id, limit: [],
    )

    @asynccontextmanager
    async def unavailable_session() -> AsyncIterator[object]:
        raise OSError("database unavailable in this unit test")
        yield

    monkeypatch.setattr(shared_module, "get_session", unavailable_session)

    events = await human_review_events_for_reports([report], {"cycle_id": "cycle-1"})

    assert events == [_human_review_event()]


async def test_paper_review_status_from_runtime_exposes_progress(
    monkeypatch: MonkeyPatch,
) -> None:
    report = build_final_selection(_evidence_pack()).selection_report
    decision = build_risk_decision(
        report,
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision

    async def fake_review_events(
        reports: object,
        readiness: object,
    ) -> list[dict[str, object]]:
        del reports, readiness
        return [_human_review_event()]

    monkeypatch.setattr(
        command_module,
        "human_review_events_for_reports",
        fake_review_events,
    )

    status = await paper_review_status_from_runtime(
        reports=[report],
        risk_decisions=[decision],
        readiness={"cycle_id": "cycle-1", "ready": True, "verdict": "ready"},
    )

    progress = status["progress"]
    assert status["schema_version"] == "0.1.0"
    assert status["cycle_id"] == "cycle-1"
    assert progress["reviewed_label"] == "1/1"
    assert status["queue"][0]["human_review_decision"] == "Defer"


def test_execution_preview_rows_summarize_preview_contract() -> None:
    preview = build_execution_preview(_risk_decision()).preview

    rows = execution_preview_rows([preview])

    assert rows[0]["preview_state"] == "READY"
    assert rows[0]["state_class"] == "pass"
    assert rows[0]["side"] == "BUY"
    assert rows[0]["submit_label"] == "No size"
    assert rows[0]["approval_label"] == "Needs order approval"
    assert rows[0]["order_value_label"] == "No order size"
    assert "Connect broker account" in str(rows[0]["next_step"])


def test_execution_preview_rows_require_current_human_approval_for_submit() -> None:
    preview = build_execution_preview(
        _risk_decision(),
        generated_at="2026-05-07T09:33:00Z",
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
    ).preview
    order_key = (
        str(preview["cycle_id"]),
        str(preview["ticker"]),
        str(preview["as_of"]),
        str(preview["order_intent_hash"]),
    )

    rows = execution_preview_rows(
        [preview],
        approval_keys=set(),
        order_approval_keys={order_key},
    )

    row = rows[0]
    assert row["stale_order_approval_recorded"] is True
    assert row["human_approved"] is False
    assert row["order_approved"] is False
    assert row["submit_enabled"] is False
    assert row["submit_blocker"] == "current human approval required"


def test_execution_preview_rows_allow_order_intent_approval_while_execution_gate_closed() -> None:
    preview = build_execution_preview(
        _risk_decision(),
        generated_at="2026-05-07T09:33:00Z",
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
    ).preview
    approval_key = (
        str(preview["cycle_id"]),
        str(preview["ticker"]),
        str(preview["as_of"]),
    )

    rows = execution_preview_rows(
        [preview],
        approval_keys={approval_key},
        execution_gate={
            "ready": False,
            "detail": "Massive Live Trade Slices data is still loading.",
        },
    )

    row = rows[0]
    assert row["preview_state"] == "READY"
    assert row["human_approved"] is True
    assert row["order_approval_available"] is True
    assert row["submit_enabled"] is False
    assert row["submit_blocker"] == "Massive Live Trade Slices data is still loading."


def test_execution_preview_rows_show_filled_audit_state_and_disable_resubmit() -> None:
    preview = build_execution_preview(
        _risk_decision(),
        generated_at="2026-05-07T09:33:00Z",
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
    ).preview
    order_key = (
        str(preview["cycle_id"]),
        str(preview["ticker"]),
        str(preview["as_of"]),
        str(preview["order_intent_hash"]),
    )
    execution_state = {
        "state": "FILLED",
        "event_time": "2026-05-07T09:35:00Z",
        "reason": "Alpaca paper order filled",
        "payload": {
            "order": {
                "client_order_id": "ta-AAPL-BUY-abc",
                "filled_qty": 3.0,
                "filled_avg_price": 177.25,
                "status": "FILLED",
            },
            "preview": dict(preview),
            "raw_status": "FILLED",
        },
    }

    rows = execution_preview_rows(
        [preview],
        approval_keys={shared_module._runtime_payload_key(preview)},
        order_approval_keys={order_key},
        execution_states={order_key: execution_state},
    )

    row = rows[0]
    assert row["preview_state"] == "FILLED"
    assert row["state_class"] == "pass"
    assert row["submit_enabled"] is False
    assert row["order_approval_available"] is False
    assert row["submit_label"] == "Paper order filled"
    assert row["submission_confirmation_label"] == "Filled 3.0 @ 177.25"
    assert row["client_order_id"] == "ta-AAPL-BUY-abc"
    assert row["filled_qty"] == 3.0
    assert row["filled_avg_price"] == 177.25


def test_execution_preview_rows_explain_watch_promotion_path() -> None:
    preview = build_execution_preview(
        build_risk_decision(
            build_final_selection(_evidence_pack()).selection_report,
            {"source_count": 1, "degraded_source_count": 0},
            generated_at="2026-05-07T09:32:00Z",
        ).risk_decision
    ).preview
    key = (
        str(preview["cycle_id"]),
        str(preview["ticker"]),
        str(preview["as_of"]),
    )

    rows = execution_preview_rows(
        [preview],
        promotion_evaluations={
            key: {
                "state": "awaiting_research_approval",
                "status_label": "Approval Needed",
                "status_class": "warn",
                "detail": "This WATCH can become a paper BUY preview after approval.",
                "next_step": (
                    "Approve the current research report; the portfolio manager will "
                    "recalculate risk and order sizing."
                ),
                "can_promote_after_approval": True,
            }
        },
    )

    row = rows[0]
    assert row["paper_promotion_status_label"] == "Approval Needed"
    assert row["submit_label"] == "Approve research first"
    assert row["order_intent"] == "Eligible paper BUY after research approval"
    assert row["research_approval_available"] is True
    assert str(row["approve_research_action"]).startswith("/candidates/AAPL/reviews?")
    assert "decision=APPROVE" in str(row["approve_research_action"])
    assert "portfolio manager will recalculate" in str(row["next_step"])


def test_execution_preview_page_renders_clickable_research_approval(
    monkeypatch: MonkeyPatch,
) -> None:
    preview = build_execution_preview(
        build_risk_decision(
            build_final_selection(_evidence_pack()).selection_report,
            {"source_count": 1, "degraded_source_count": 0},
            generated_at="2026-05-07T09:32:00Z",
        ).risk_decision
    ).preview
    key = (
        str(preview["cycle_id"]),
        str(preview["ticker"]),
        str(preview["as_of"]),
    )
    rows = execution_preview_rows(
        [preview],
        promotion_evaluations={
            key: {
                "state": "awaiting_research_approval",
                "status_label": "Approval Needed",
                "status_class": "warn",
                "detail": "This WATCH can become a paper BUY preview after approval.",
                "next_step": "Approve the current research report.",
                "can_promote_after_approval": True,
            }
        },
    )
    broker = {
        "connected": True,
        "mode": "paper",
        "checked_at": datetime.now(UTC).isoformat(),
        "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
        "positions": [],
        "orders": [],
        "gross_exposure_pct": 0.0,
        "status_class": "pass",
        "detail": "paper broker connected",
    }
    execution_gate = {
        "ready": True,
        "status_label": "Ready",
        "status_class": "pass",
        "detail": "Broker and critical source freshness passed.",
        "checks": [],
    }

    async def fake_execution_preview_context() -> dict[str, object]:
        return {
            "summary": execution_module.execution_preview_summary(
                rows,
                broker=broker,
                policy=PortfolioPolicy(broker_submit_enabled=True),
                execution_gate=execution_gate,
            ),
            "broker": broker,
            "preview_rows": rows,
            "orderable_rows": [row for row in rows if row["preview_state"] == "READY"],
            "review_only_rows": [row for row in rows if row["preview_state"] == "DISABLED"],
            "approved_review_only_rows": [
                row
                for row in rows
                if row["preview_state"] == "DISABLED" and row["human_approved"] is True
            ],
            "blocked_rows": [row for row in rows if row["preview_state"] == "BLOCKED"],
            "data_health": None,
            "execution_freshness_gate": execution_gate,
            "leveraged_alternatives": execution_module.leveraged_alternative_panel([]),
        }

    monkeypatch.setattr(
        dashboard_module,
        "execution_preview_context",
        fake_execution_preview_context,
    )
    response = TestClient(create_app()).get("/execution-preview")

    assert response.status_code == HTTP_OK
    assert 'method="post" action="/candidates/AAPL/reviews?' in response.text
    assert "decision=APPROVE" in response.text
    assert ">Approve research first</button>" in response.text


def test_execution_preview_page_keeps_requested_ticker_in_focus(
    monkeypatch: MonkeyPatch,
) -> None:
    preview = build_execution_preview(
        build_risk_decision(
            build_final_selection(_evidence_pack()).selection_report,
            {"source_count": 1, "degraded_source_count": 0},
            generated_at="2026-05-07T09:32:00Z",
        ).risk_decision
    ).preview
    key = (
        str(preview["cycle_id"]),
        str(preview["ticker"]),
        str(preview["as_of"]),
    )
    rows = execution_preview_rows(
        [preview],
        approval_keys={key},
        promotion_evaluations={
            key: {
                "state": "not_eligible",
                "status_label": "Blocked checks",
                "status_class": "warn",
                "detail": "Research approval is recorded but promotion checks still need operator attention.",
                "next_step": "Use paper-only manual advance with caution, or wait for another cycle.",
                "manual_advance_available": True,
                "reasons": ["confirmed signal count 1 is below required 2."],
                "checks": [
                    {
                        "name": "confirmed_signal_count",
                        "label": "Confirmed signal count",
                        "status": "BLOCK",
                        "status_class": "warn",
                        "detail": "Policy requires at least 2 confirmed signals.",
                        "observed": "1",
                        "required": "2",
                    }
                ],
            }
        },
    )
    broker = {
        "connected": True,
        "mode": "paper",
        "checked_at": datetime.now(UTC).isoformat(),
        "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
        "positions": [],
        "orders": [],
        "gross_exposure_pct": 0.0,
        "status_class": "pass",
        "detail": "paper broker connected",
    }
    execution_gate = {
        "ready": True,
        "status_label": "Ready",
        "status_class": "pass",
        "detail": "Broker and critical source freshness passed.",
        "checks": [],
    }
    seen: dict[str, object] = {}

    async def fake_execution_preview_context(
        *,
        focus_ticker: str | None = None,
    ) -> dict[str, object]:
        seen["focus_ticker"] = focus_ticker
        focus = execution_module.execution_preview_focus_context(rows, focus_ticker or "AAPL")
        return {
            "summary": execution_module.execution_preview_summary(
                rows,
                broker=broker,
                policy=PortfolioPolicy(broker_submit_enabled=True),
                execution_gate=execution_gate,
            ),
            "broker": broker,
            "preview_rows": rows,
            "orderable_rows": [row for row in rows if row["preview_state"] == "READY"],
            "review_only_rows": [row for row in rows if row["preview_state"] == "DISABLED"],
            "approved_review_only_rows": [
                row
                for row in rows
                if row["preview_state"] == "DISABLED" and row["human_approved"] is True
            ],
            "blocked_rows": [row for row in rows if row["preview_state"] == "BLOCKED"],
            "focused_execution": focus,
            "data_health": None,
            "execution_freshness_gate": execution_gate,
            "leveraged_alternatives": execution_module.leveraged_alternative_panel([]),
        }

    monkeypatch.setattr(
        dashboard_module,
        "execution_preview_context",
        fake_execution_preview_context,
    )
    dashboard_module._clear_execution_preview_route_cache()

    response = TestClient(create_app()).get("/execution-preview?ticker=aapl")

    assert response.status_code == HTTP_OK
    assert seen["focus_ticker"] is None
    assert "Stay With AAPL" in response.text
    assert 'id="focused-preview-AAPL"' in response.text
    assert "AAPL can be manually advanced with caution" in response.text
    assert "confirmed signal count 1 is below required 2." in response.text
    assert ">Advance with caution</button>" in response.text
    assert 'href="/candidates/AAPL?from=execution-preview#focused-preview-AAPL"' in response.text
    assert "Actionable Execution Follow-Up" not in response.text
    assert "Show full clearance list" in response.text


def test_execution_preview_focused_routes_reuse_cached_base_context(
    monkeypatch: MonkeyPatch,
) -> None:
    preview = build_execution_preview(
        build_risk_decision(
            build_final_selection(_evidence_pack()).selection_report,
            {"source_count": 1, "degraded_source_count": 0},
            generated_at="2026-05-07T09:32:00Z",
        ).risk_decision
    ).preview
    key = (
        str(preview["cycle_id"]),
        str(preview["ticker"]),
        str(preview["as_of"]),
    )
    rows = execution_preview_rows([preview], approval_keys={key})
    second_row = dict(rows[0])
    second_row["ticker"] = "MSFT"
    rows = [rows[0], second_row]
    broker = {
        "connected": True,
        "mode": "paper",
        "checked_at": datetime.now(UTC).isoformat(),
        "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
        "positions": [],
        "orders": [],
        "gross_exposure_pct": 0.0,
        "status_class": "pass",
        "detail": "paper broker connected",
    }
    execution_gate = {
        "ready": True,
        "status_label": "Ready",
        "status_class": "pass",
        "detail": "Broker and critical source freshness passed.",
        "checks": [],
    }
    calls: list[str | None] = []

    async def fake_execution_preview_context(
        *,
        focus_ticker: str | None = None,
    ) -> dict[str, object]:
        calls.append(focus_ticker)
        return {
            "summary": execution_module.execution_preview_summary(
                rows,
                broker=broker,
                policy=PortfolioPolicy(broker_submit_enabled=True),
                execution_gate=execution_gate,
            ),
            "broker": broker,
            "preview_rows": rows,
            "orderable_rows": [row for row in rows if row["preview_state"] == "READY"],
            "review_only_rows": [row for row in rows if row["preview_state"] == "DISABLED"],
            "approved_review_only_rows": [
                row
                for row in rows
                if row["preview_state"] == "DISABLED" and row["human_approved"] is True
            ],
            "blocked_rows": [row for row in rows if row["preview_state"] == "BLOCKED"],
            "focused_execution": execution_module.execution_preview_focus_context(
                rows,
                focus_ticker,
            ),
            "data_health": None,
            "execution_freshness_gate": execution_gate,
            "leveraged_alternatives": execution_module.leveraged_alternative_panel([]),
        }

    if hasattr(dashboard_module, "_clear_execution_preview_route_cache"):
        dashboard_module._clear_execution_preview_route_cache()
    monkeypatch.setattr(
        dashboard_module,
        "execution_preview_context",
        fake_execution_preview_context,
    )

    client = TestClient(create_app())
    first = client.get("/execution-preview?ticker=AAPL")
    second = client.get("/execution-preview?ticker=MSFT")

    assert first.status_code == HTTP_OK
    assert second.status_code == HTTP_OK
    assert calls == [None]
    assert 'id="focused-preview-AAPL"' in first.text
    assert 'id="focused-preview-MSFT"' in second.text


def test_execution_preview_page_renders_operator_notice(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_execution_preview_context() -> dict[str, object]:
        return {
            "summary": {
                "broker_mode": "paper",
                "submit_gate_label": "Closed",
                "submit_gate_open": False,
                "headline": "No order can be submitted yet",
                "detail": "Broker submit is closed.",
                "no_order_explanation": "",
                "preview_count": 0,
                "ready_count": 0,
                "blocked_count": 0,
                "disabled_count": 0,
                "submit_ready_count": 0,
            },
            "broker": {
                "connected": False,
                "mode": "paper",
                "checked_at": datetime.now(UTC).isoformat(),
                "status_class": "warn",
                "status_label": "Broker Offline",
                "detail": "Broker submit is closed.",
            },
            "preview_rows": [],
            "orderable_rows": [],
            "review_only_rows": [],
            "approved_review_only_rows": [],
            "blocked_rows": [],
            "data_health": None,
            "execution_freshness_gate": {"ready": False, "detail": "Broker offline"},
            "leveraged_alternatives": execution_module.leveraged_alternative_panel([]),
        }

    monkeypatch.setattr(
        dashboard_module,
        "execution_preview_context",
        fake_execution_preview_context,
    )

    response = TestClient(create_app()).get(
        "/execution-preview"
        "?execution_notice=Broker%20is%20not%20connected%3B%20refresh%20Broker"
        "&execution_notice_class=warn"
    )

    assert response.status_code == HTTP_OK
    assert "Execution action needs attention" in response.text
    assert "Broker is not connected; refresh Broker" in response.text


def test_approve_execution_order_does_not_block_immediately_on_broker_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_broker() -> dict[str, object]:
        return {
            "connected": False,
            "mode": "paper",
            "checked_at": datetime.now(UTC).isoformat(),
            "account": None,
            "positions": [],
            "orders": [],
            "detail": "Broker is not connected.",
        }

    async def fake_sources() -> list[dict[str, object]]:
        return _fresh_critical_execution_sources()

    monkeypatch.setattr(dashboard_module, "_fresh_broker_status_context", fake_broker)
    monkeypatch.setattr(dashboard_module, "runtime_data_source_status", fake_sources)

    response = TestClient(create_app()).post(
        "/execution-preview/orders/approve"
        "?cycle_id=cycle-1&ticker=AAPL&as_of=2026-05-07T09%3A30%3A00Z"
        f"&order_intent_hash={'a' * 64}",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"].startswith("/execution-preview?execution_notice=")
    assert "execution+preview+not+found" in response.headers["location"]
    assert response.headers["location"].endswith("ticker=AAPL#focused-preview-AAPL")


def test_approve_execution_order_records_intent_while_execution_gate_closed(
    monkeypatch: MonkeyPatch,
) -> None:
    preview = build_execution_preview(
        _risk_decision(),
        generated_at="2026-05-07T09:33:00Z",
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
    ).preview
    recorded: list[dict[str, object]] = []

    async def fake_broker() -> dict[str, object]:
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {"status": "ACTIVE"},
            "positions": [],
            "orders": [],
        }

    async def fake_sources() -> list[dict[str, object]]:
        return _fresh_critical_execution_sources()

    async def fake_context(**_kwargs: object) -> dict[str, object]:
        return {
            "execution_freshness_gate": {
                "ready": False,
                "detail": "Massive Live Trade Slices data is still loading.",
            },
            "preview_rows": [
                {
                    "cycle_id": preview["cycle_id"],
                    "ticker": preview["ticker"],
                    "as_of": preview["as_of"],
                    "order_intent_hash": preview["order_intent_hash"],
                    "order_approval_available": True,
                    "preview": preview,
                }
            ],
        }

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[object]:
        class Session:
            async def commit(self) -> None:
                recorded.append({"committed": True})

        yield Session()

    async def fake_record_event(_session: object, event: dict[str, object]) -> None:
        recorded.append(event)

    def fail_if_freshness_required(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("order intent approval must not require submit freshness")

    monkeypatch.setattr(dashboard_module, "_fresh_broker_status_context", fake_broker)
    monkeypatch.setattr(dashboard_module, "runtime_data_source_status", fake_sources)
    monkeypatch.setattr(dashboard_module, "execution_preview_context", fake_context)
    monkeypatch.setattr(
        dashboard_module,
        "_require_immediate_execution_freshness",
        fail_if_freshness_required,
    )
    monkeypatch.setattr(dashboard_module, "get_session", fake_session)
    monkeypatch.setattr(dashboard_module, "record_candidate_lifecycle_event", fake_record_event)

    response = TestClient(create_app()).post(
        "/execution-preview/orders/approve"
        f"?cycle_id={preview['cycle_id']}&ticker={preview['ticker']}"
        f"&as_of={quote(str(preview['as_of']))}"
        f"&order_intent_hash={preview['order_intent_hash']}",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"] == (
        f"/execution-preview?ticker={preview['ticker']}#focused-preview-{preview['ticker']}"
    )
    approval_events = [
        event for event in recorded if event.get("event_type") == "ORDER_APPROVAL"
    ]
    assert len(approval_events) == 1


def test_execution_preview_rows_do_not_label_pending_watch_as_research_approved() -> None:
    preview = build_execution_preview(
        build_risk_decision(
            build_final_selection(_evidence_pack()).selection_report,
            {"source_count": 1, "degraded_source_count": 0},
            generated_at="2026-05-07T09:32:00Z",
        ).risk_decision
    ).preview
    key = (
        str(preview["cycle_id"]),
        str(preview["ticker"]),
        str(preview["as_of"]),
    )

    rows = execution_preview_rows(
        [preview],
        promotion_evaluations={
            key: {
                "state": "not_eligible",
                "status_label": "Research Only",
                "status_class": "neutral",
                "detail": "This WATCH is not eligible for paper promotion yet.",
                "reasons": [
                    "critical evidence freshness is STALE.",
                    "current human research approval is missing.",
                ],
                "can_promote_after_approval": False,
            }
        },
    )

    row = rows[0]
    assert row["human_approved"] is False
    assert row["human_review_decision"] == "Pending"
    assert row["order_intent"] == "WATCH review pending: not orderable yet"
    assert "Research approved" not in str(row["order_intent"])
    assert row["approval_label"] == "Needs research review"
    assert row["order_value_label"] == "No order - research only"
    assert row["size_label"] == "Not sized until trade action"
    assert row["deterministic_score_label"] == "WARN risk / final action is WATCH"
    assert row["paper_promotion_status_label"] == "Blocked checks"
    assert "blocked checks clear" in str(row["next_step"])
    assert row["paper_promotion_blockers"] == [
        "critical evidence freshness needs refresh.",
        "current human research approval is missing.",
    ]


def test_execution_preview_rows_explain_cautionary_watch_without_blocking_review() -> None:
    report = build_final_selection(_evidence_pack()).selection_report
    report["policy_gates"] = [
        {
            "name": "evidence_breadth",
            "status": "BLOCK",
            "reason": "only one confirmed signal is available",
        }
    ]
    preview = build_execution_preview(
        build_risk_decision(
            report,
            {"source_count": 1, "degraded_source_count": 0},
            generated_at="2026-05-07T09:32:00Z",
        ).risk_decision
    ).preview

    rows = execution_preview_rows([preview])

    row = rows[0]
    assert row["preview_state"] == "DISABLED"
    assert row["state_class"] == "neutral"
    assert row["caution_acknowledgement_required"] is True
    assert "Caution:" in str(row["reason"])
    assert "only one confirmed signal" in str(row["reason"])
    assert "Acknowledge the caution" in str(row["next_step"])


def test_execution_preview_rows_explain_approved_watch_blockers() -> None:
    preview = build_execution_preview(
        build_risk_decision(
            build_final_selection(_evidence_pack()).selection_report,
            {"source_count": 1, "degraded_source_count": 0},
            generated_at="2026-05-07T09:32:00Z",
        ).risk_decision
    ).preview
    key = (
        str(preview["cycle_id"]),
        str(preview["ticker"]),
        str(preview["as_of"]),
    )
    review_event = _human_review_event()
    review_payload = dict(review_event["payload"])
    review_payload["review_decision"] = "APPROVE"
    review_event = {
        **review_event,
        "status": "PASSED",
        "reason": "paper review approved",
        "payload": review_payload,
    }

    rows = execution_preview_rows(
        [preview],
        approval_keys={key},
        review_states={key: review_event},
        promotion_evaluations={
            key: {
                "state": "blocked_by_policy",
                "status_label": "Policy Blocked",
                "status_class": "block",
                "detail": "WATCH cannot create a paper BUY preview yet.",
                "reasons": ["confirmed signal count 1 is below required 2"],
                "can_promote_after_approval": False,
            }
        },
    )

    row = rows[0]
    assert row["human_approved"] is True
    assert row["human_review_decision"] == "Approve"
    assert row["human_review_class"] == "pass"
    assert row["human_review_reason"] == "paper review approved"
    assert row["submit_label"] == "Research approved"
    assert "confirmed signal count 1 is below required 2" in str(row["reason"])
    assert "No paper order can be submitted" in str(row["next_step"])


def test_execution_preview_rows_label_approved_promotable_watch_as_research_approved() -> None:
    preview = build_execution_preview(
        build_risk_decision(
            build_final_selection(_evidence_pack()).selection_report,
            {"source_count": 1, "degraded_source_count": 0},
            generated_at="2026-05-07T09:32:00Z",
        ).risk_decision
    ).preview
    key = (
        str(preview["cycle_id"]),
        str(preview["ticker"]),
        str(preview["as_of"]),
    )

    rows = execution_preview_rows(
        [preview],
        approval_keys={key},
        promotion_evaluations={
            key: {
                "state": "awaiting_research_approval",
                "status_label": "Approval Needed",
                "status_class": "warn",
                "detail": "This WATCH can become a paper BUY preview after approval.",
                "next_step": "Approve the current research report.",
                "can_promote_after_approval": True,
            }
        },
    )

    row = rows[0]
    assert row["human_approved"] is True
    assert row["research_approval_available"] is False
    assert row["submit_label"] == "Research approved"


async def test_order_approval_lookup_requires_current_preview_version(
    monkeypatch: MonkeyPatch,
) -> None:
    preview = build_execution_preview(
        _risk_decision(),
        generated_at="2026-05-07T09:33:00Z",
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
    ).preview
    event = build_order_approval_event(preview)
    stale_event = dict(event)
    stale_payload = dict(event["payload"])
    stale_payload["order_intent_version"] = "old-version"
    stale_event["payload"] = stale_payload

    async def fake_order_events(
        reports: object,
        readiness: object,
    ) -> list[dict[str, object]]:
        del reports, readiness
        return [stale_event]

    monkeypatch.setattr(
        execution_module,
        "order_approval_events_for_reports",
        fake_order_events,
    )

    approved = await execution_module.order_approval_keys_for_reports(
        reports=[_selection_report()],
        data_sources=[_source_health("daily-market-bars")],
        previews=[preview],
    )

    assert approved == set()


async def test_order_approval_lookup_ignores_artifact_only_approval_events(
    monkeypatch: MonkeyPatch,
) -> None:
    preview = build_execution_preview(
        _risk_decision(),
        generated_at="2026-05-07T09:33:00Z",
        policy=PortfolioPolicy(broker_submit_enabled=True),
        account={"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
    ).preview
    artifact_event = build_order_approval_event(preview)

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[object]:
        yield object()

    async def slow_lifecycle_query(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        await asyncio.sleep(10)
        return []

    async def empty_timeline(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(shared_module, "DASHBOARD_LIFECYCLE_QUERY_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(shared_module, "get_session", fake_session)
    monkeypatch.setattr(shared_module, "list_candidate_lifecycle_events", slow_lifecycle_query)
    monkeypatch.setattr(
        shared_module,
        "runtime_lifecycle_event_artifacts",
        lambda *, cycle_id, limit: [artifact_event],
    )
    monkeypatch.setattr(shared_module, "_timeline_lifecycle_events_for_reports", empty_timeline)

    approved = await execution_module.order_approval_keys_for_reports(
        reports=[_selection_report()],
        data_sources=[_source_health("daily-market-bars")],
        previews=[preview],
    )

    assert approved == set()


async def test_lifecycle_events_use_artifact_fallback_when_database_query_times_out(
    monkeypatch: MonkeyPatch,
) -> None:
    report = _selection_report_for_cycle(
        "live-pit-current",
        "AAPL",
        "2026-05-07T09:31:00Z",
    )
    artifact_event = {
        "cycle_id": "live-pit-current",
        "ticker": "AAPL",
        "event_type": "ORDER_APPROVAL",
        "status": "PASSED",
        "payload": {"approval_type": "ORDER_APPROVAL"},
    }

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[object]:
        yield object()

    async def slow_lifecycle_query(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        await asyncio.sleep(10)
        return []

    async def forbidden_timeline(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("timeline fallback should not run when artifacts are available")

    monkeypatch.setattr(shared_module, "DASHBOARD_LIFECYCLE_QUERY_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(shared_module, "get_session", fake_session)
    monkeypatch.setattr(shared_module, "list_candidate_lifecycle_events", slow_lifecycle_query)
    monkeypatch.setattr(
        shared_module,
        "runtime_lifecycle_event_artifacts",
        lambda *, cycle_id, limit: [artifact_event],
    )
    monkeypatch.setattr(shared_module, "_timeline_lifecycle_events_for_reports", forbidden_timeline)

    events = await shared_module._lifecycle_events_for_reports(
        [report],
        {"cycle_id": "live-pit-current"},
        event_type="ORDER_APPROVAL",
        limit_per_ticker=100,
    )

    assert events == [artifact_event]


async def test_human_review_events_merge_artifact_fallback_when_database_has_no_rows(
    monkeypatch: MonkeyPatch,
) -> None:
    report = _selection_report_for_cycle(
        "live-pit-current",
        "aapl",
        "2026-05-07T09:31:00Z",
    )
    older = {
        "cycle_id": "live-pit-current",
        "ticker": "AAPL",
        "event_type": "HUMAN_REVIEW",
        "event_time": "2026-05-07T09:35:00Z",
        "status": "WARN",
        "reason": "paper review deferred",
        "payload": {"review_decision": "DEFER", "as_of": "2026-05-07T09:31:00Z"},
    }
    newer = {
        "cycle_id": "live-pit-current",
        "ticker": "AAPL",
        "event_type": "HUMAN_REVIEW",
        "event_time": "2026-05-07T09:45:00Z",
        "status": "PASSED",
        "reason": "paper review approved",
        "payload": {"review_decision": "APPROVE", "as_of": "2026-05-07T09:31:00Z"},
    }

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[object]:
        yield object()

    async def empty_lifecycle_query(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(shared_module, "get_session", fake_session)
    monkeypatch.setattr(shared_module, "list_candidate_lifecycle_events", empty_lifecycle_query)
    monkeypatch.setattr(
        shared_module,
        "runtime_lifecycle_event_artifacts",
        lambda *, cycle_id, limit: [older, newer],
    )

    events = await shared_module._lifecycle_events_for_reports(
        [report],
        {"cycle_id": "live-pit-current"},
        event_type="HUMAN_REVIEW",
        limit_per_ticker=100,
    )
    indexed = shared_module._human_review_index(events)

    assert events == [newer, older]
    assert indexed[("live-pit-current", "AAPL", "2026-05-07T09:31:00Z")] == newer


async def test_operator_manual_advance_events_merge_artifact_fallback_when_database_succeeds(
    monkeypatch: MonkeyPatch,
) -> None:
    report = _selection_report_for_cycle(
        "live-pit-current",
        "aapl",
        "2026-05-07T09:31:00Z",
    )
    artifact_event = {
        "cycle_id": "live-pit-current",
        "ticker": "AAPL",
        "event_type": "OPERATOR_MANUAL_ADVANCE",
        "event_time": "2026-05-07T09:45:00Z",
        "status": "PASSED",
        "payload": {"as_of": "2026-05-07T09:31:00Z"},
    }

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[object]:
        yield object()

    async def empty_lifecycle_query(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(shared_module, "get_session", fake_session)
    monkeypatch.setattr(shared_module, "list_candidate_lifecycle_events", empty_lifecycle_query)
    monkeypatch.setattr(
        shared_module,
        "runtime_lifecycle_event_artifacts",
        lambda *, cycle_id, limit: [artifact_event],
    )

    events = await shared_module._lifecycle_events_for_reports(
        [report],
        {"cycle_id": "live-pit-current"},
        event_type="OPERATOR_MANUAL_ADVANCE",
        limit_per_ticker=100,
    )

    assert events == [artifact_event]


async def test_execution_preview_context_does_not_reuse_research_approval_for_promoted_order(
    monkeypatch: MonkeyPatch,
) -> None:
    report = _selection_report_for_cycle(
        "live-pit-current",
        "AAPL",
        "2026-05-07T09:31:00Z",
    )

    async def fake_reports(*, limit: int = 50, ticker: str | None = None) -> list[dict[str, object]]:
        del limit, ticker
        return [report]

    async def fake_sources() -> list[dict[str, object]]:
        checked_at = datetime.now(UTC).isoformat()
        return [
            {
                "schema_version": "0.1.0",
                "source": "daily-market-bars",
                "source_tier": "OFFICIAL_FILING",
                "status": "HEALTHY",
                "checked_at": checked_at,
                "freshness": "FRESH",
                "last_success_at": checked_at,
                "observed_lag_seconds": 60,
                "error_count": 0,
                "reliability_score": 1.0,
                "rate_limit_reset_at": None,
                "notes": [],
            },
            {
                "schema_version": "0.1.0",
                "source": "massive-stock-trades",
                "source_tier": "MARKET_DATA",
                "status": "HEALTHY",
                "checked_at": checked_at,
                "freshness": "FRESH",
                "last_success_at": checked_at,
                "observed_lag_seconds": 60,
                "error_count": 0,
                "reliability_score": 1.0,
                "rate_limit_reset_at": None,
                "notes": [],
            },
            {
                "schema_version": "0.1.0",
                "source": "sec-edgar",
                "source_tier": "OFFICIAL_FILING",
                "status": "HEALTHY",
                "checked_at": checked_at,
                "freshness": "FRESH",
                "last_success_at": checked_at,
                "observed_lag_seconds": 60,
                "error_count": 0,
                "reliability_score": 1.0,
                "rate_limit_reset_at": None,
                "notes": [],
            }
        ]

    async def fake_review_events(
        reports: object,
        readiness: object,
    ) -> list[dict[str, object]]:
        del reports, readiness
        event = _human_review_event()
        event["cycle_id"] = "live-pit-current"
        event["status"] = "RECORDED"
        event["reason"] = "paper review approved"
        event["payload"]["review_decision"] = "APPROVE"
        event["payload"]["as_of"] = str(report["as_of"])
        event["payload"]["selection_report_hash"] = selection_report_hash(report)
        return [event]

    async def fake_broker(**_kwargs: object) -> dict[str, object]:
        checked_at = datetime.now(UTC).isoformat()
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": checked_at,
            "account": {
                "status": "ACTIVE",
                "equity": 100000.0,
                "buying_power": 100000.0,
            },
            "positions": [],
            "orders": [],
        }

    def fake_scheduler_context(**_kwargs: object) -> dict[str, object]:
        return {
            "tradability": {
                "state": "tradable",
                "status_label": "Tradable",
                "status_class": "pass",
                "detail": "test scheduler tradable",
            },
        }

    monkeypatch.setenv("AGENCY_BROKER_SUBMIT_ENABLED", "true")
    monkeypatch.setenv("AGENCY_PAPER_TRADE_PROMOTION_ENABLED", "true")
    monkeypatch.setenv("AGENCY_PAPER_TRADE_MIN_CONVICTION", "0.1")
    monkeypatch.setenv("AGENCY_PAPER_TRADE_MIN_SOURCE_COUNT", "1")
    monkeypatch.setenv("AGENCY_PAPER_TRADE_MIN_CONFIRMED_SIGNALS", "1")
    monkeypatch.setenv("AGENCY_PAPER_TRADE_REQUIRE_POLICY_PASS", "false")
    monkeypatch.setattr(shared_module, "runtime_selection_reports", fake_reports)
    monkeypatch.setattr(execution_module, "runtime_data_source_status", fake_sources)
    monkeypatch.setattr(execution_module, "scheduler_work_queue_context", fake_scheduler_context)
    monkeypatch.setattr(command_module, "human_review_events_for_reports", fake_review_events)
    monkeypatch.setattr(market_regime_module, "broker_status_context", fake_broker)

    context = await execution_module.execution_preview_context()
    row = context["preview_rows"][0]

    assert row["side"] == "BUY"
    assert row["preview_state"] == "READY"
    assert row["human_approved"] is True
    assert row["order_approved"] is False
    assert row["submit_enabled"] is False
    assert row["submit_label"] == "Approve order"


def test_submit_execution_order_requires_persisted_order_approval_when_env_bypass_false(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_broker() -> dict[str, object]:
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
        }

    async def fake_sources() -> list[dict[str, object]]:
        checked_at = datetime.now(UTC).isoformat()
        return [
            {
                "schema_version": "0.1.0",
                "source": source,
                "source_tier": "MARKET_DATA",
                "status": "HEALTHY",
                "checked_at": checked_at,
                "freshness": "FRESH",
                "last_success_at": checked_at,
                "observed_lag_seconds": 1,
                "error_count": 0,
                "reliability_score": 1.0,
                "rate_limit_reset_at": None,
                "notes": [],
            }
            for source in ("daily-market-bars", "massive-stock-trades")
        ]

    async def fake_context(**_kwargs: object) -> dict[str, object]:
        return {
            "execution_freshness_gate": {"ready": True, "detail": "fresh"},
            "preview_rows": [
                {
                    "cycle_id": "cycle-1",
                    "ticker": "AAPL",
                    "as_of": "2026-05-07T09:30:00Z",
                    "order_intent_hash": "a" * 64,
                    "order_approved": False,
                    "submit_enabled": True,
                    "submit_blocker": "ready",
                }
            ],
        }

    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("AGENCY_BROKER_SUBMIT_ENABLED", "true")
    monkeypatch.setenv("AGENCY_REQUIRE_HUMAN_APPROVAL_FOR_ORDERS", "false")
    monkeypatch.setattr(dashboard_module, "_fresh_broker_status_context", fake_broker)
    monkeypatch.setattr(dashboard_module, "runtime_data_source_status", fake_sources)
    monkeypatch.setattr(dashboard_module, "execution_preview_context", fake_context)

    response = TestClient(create_app()).post(
        "/execution-preview/orders"
        "?cycle_id=cycle-1&ticker=AAPL&as_of=2026-05-07T09%3A30%3A00Z"
        f"&order_intent_hash={'a' * 64}",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"].startswith(
        "/execution-preview?execution_notice=hash-bound+order+approval+required"
    )
    assert "ticker=AAPL" in response.headers["location"]


def test_submit_execution_order_requires_final_operator_submit_phrase(
    monkeypatch: MonkeyPatch,
) -> None:
    broker_calls: list[str] = []

    async def fake_broker() -> dict[str, object]:
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
        }

    async def fake_sources() -> list[dict[str, object]]:
        return _fresh_critical_execution_sources()

    async def fake_context(**_kwargs: object) -> dict[str, object]:
        return {
            "execution_freshness_gate": {"ready": True, "detail": "fresh"},
            "preview_rows": [
                {
                    "cycle_id": "cycle-1",
                    "ticker": "AAPL",
                    "as_of": "2026-05-07T09:30:00Z",
                    "side": "BUY",
                    "quantity": None,
                    "notional": 1000.0,
                    "time_in_force": "DAY",
                    "order_intent_hash": "a" * 64,
                    "order_approved": True,
                    "submit_enabled": True,
                    "submit_blocker": "ready",
                    "preview": {
                        "cycle_id": "cycle-1",
                        "ticker": "AAPL",
                        "as_of": "2026-05-07T09:30:00Z",
                        "order_intent_hash": "a" * 64,
                        "order_intent_version": "0.1.0",
                    },
                }
            ],
        }

    class FakeClient:
        def __init__(self, _config: object) -> None:
            broker_calls.append("init")

        async def submit_order(self, _payload: object) -> dict[str, object]:
            broker_calls.append("submit")
            raise AssertionError("broker submit must not run without final operator phrase")

    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("AGENCY_BROKER_SUBMIT_ENABLED", "true")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(dashboard_module, "_fresh_broker_status_context", fake_broker)
    monkeypatch.setattr(dashboard_module, "runtime_data_source_status", fake_sources)
    monkeypatch.setattr(dashboard_module, "execution_preview_context", fake_context)
    monkeypatch.setattr(dashboard_module, "AlpacaBrokerClient", FakeClient)

    response = TestClient(create_app()).post(
        "/execution-preview/orders"
        "?cycle_id=cycle-1&ticker=AAPL&as_of=2026-05-07T09%3A30%3A00Z"
        f"&order_intent_hash={'a' * 64}",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"].startswith(
        "/execution-preview?execution_notice=Final+paper-submit+confirmation+phrase+is+required."
    )
    assert "ticker=AAPL" in response.headers["location"]
    assert broker_calls == []


def test_submit_execution_order_records_intent_before_broker_submit(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    submitted_audit: dict[str, object] = {}

    async def fake_broker() -> dict[str, object]:
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
        }

    async def fake_sources() -> list[dict[str, object]]:
        return _fresh_critical_execution_sources()

    async def fake_context(**_kwargs: object) -> dict[str, object]:
        return {
            "execution_freshness_gate": {"ready": True, "detail": "fresh"},
            "preview_rows": [
                {
                    "cycle_id": "cycle-1",
                    "ticker": "AAPL",
                    "as_of": "2026-05-07T09:30:00Z",
                    "side": "BUY",
                    "quantity": None,
                    "notional": 1000.0,
                    "time_in_force": "DAY",
                    "order_intent_hash": "a" * 64,
                    "order_approved": True,
                    "submit_enabled": True,
                    "submit_blocker": "ready",
                    "preview": {
                        "cycle_id": "cycle-1",
                        "ticker": "AAPL",
                        "as_of": "2026-05-07T09:30:00Z",
                        "order_intent_hash": "a" * 64,
                        "order_intent_version": "0.1.0",
                    },
                }
            ],
        }

    async def fake_record_intent(row: object, order_payload: object) -> None:
        del row, order_payload
        calls.append("intent")

    async def fake_record_submitted(
        row: object,
        order: object,
        reconciliation: object | None = None,
    ) -> None:
        del row
        calls.append("submitted")
        submitted_audit["order"] = order
        submitted_audit["reconciliation"] = reconciliation

    class FakeClient:
        def __init__(self, _config: object) -> None:
            self.client_order_id = ""

        async def submit_order(self, payload: object) -> dict[str, object]:
            calls.append("broker")
            self.client_order_id = str(payload["client_order_id"])  # type: ignore[index]
            return {
                "order_id": "order-1",
                "client_order_id": self.client_order_id,
                "ticker": "AAPL",
                "status": "FILLED",
            }

        async def order_by_client_order_id(self, client_order_id: str) -> dict[str, object]:
            calls.append("reconcile")
            assert client_order_id == self.client_order_id
            return {
                "order_id": "order-1",
                "client_order_id": self.client_order_id,
                "ticker": "AAPL",
                "status": "FILLED",
                "filled_qty": 3.0,
                "filled_avg_price": 177.25,
            }

    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("AGENCY_BROKER_SUBMIT_ENABLED", "true")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(dashboard_module, "_fresh_broker_status_context", fake_broker)
    monkeypatch.setattr(dashboard_module, "runtime_data_source_status", fake_sources)
    monkeypatch.setattr(dashboard_module, "execution_preview_context", fake_context)
    monkeypatch.setattr(dashboard_module, "_record_order_submission_intent", fake_record_intent)
    monkeypatch.setattr(dashboard_module, "_record_submitted_order", fake_record_submitted)
    monkeypatch.setattr(dashboard_module, "AlpacaBrokerClient", FakeClient)

    response = TestClient(create_app()).post(
        "/execution-preview/orders"
        "?cycle_id=cycle-1&ticker=AAPL&as_of=2026-05-07T09%3A30%3A00Z"
        f"&order_intent_hash={'a' * 64}",
        data={
            "submit_gate_armed": "true",
            "operator_phrase": "submit paper orders",
        },
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert response.headers["location"] == "/execution-preview?ticker=AAPL#focused-preview-AAPL"
    assert calls == ["intent", "broker", "reconcile", "submitted"]
    assert submitted_audit["order"]["status"] == "FILLED"  # type: ignore[index]
    assert submitted_audit["reconciliation"]["state"] == "client_order_id_confirmed"  # type: ignore[index]


def test_record_submitted_order_uses_state_specific_reason(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeSession:
        async def commit(self) -> None:
            captured["committed"] = True

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    async def fake_persist(
        session: object,
        **kwargs: object,
    ) -> dict[str, object]:
        del session
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(execution_module, "get_session", fake_session)
    monkeypatch.setattr(execution_module, "persist_order_execution_state", fake_persist)

    asyncio.run(
        execution_module._record_submitted_order(
            {
                "cycle_id": "cycle-1",
                "ticker": "AAPL",
                "as_of": "2026-05-07T09:30:00Z",
                "order_intent_hash": "a" * 64,
            },
            {
                "order_id": "order-1",
                "client_order_id": "client-1",
                "ticker": "AAPL",
                "status": "FILLED",
            },
        )
    )

    assert captured["committed"] is True
    assert "reason" not in captured


@pytest.mark.asyncio
async def test_reconcile_submitted_order_polls_until_terminal_status(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_sleep(_seconds: float) -> None:
        calls.append("sleep")

    class FakeClient:
        def __init__(self) -> None:
            self.responses = [
                {
                    "order_id": "order-1",
                    "client_order_id": "client-1",
                    "ticker": "AAPL",
                    "status": "NEW",
                    "submitted_at": "2026-05-21T15:08:13Z",
                    "filled_at": "",
                },
                {
                    "order_id": "order-1",
                    "client_order_id": "client-1",
                    "ticker": "AAPL",
                    "status": "FILLED",
                    "submitted_at": "2026-05-21T15:08:13Z",
                    "filled_at": "2026-05-21T15:08:14Z",
                    "filled_qty": 3.0,
                    "filled_avg_price": 177.25,
                },
            ]

        async def order_by_client_order_id(self, client_order_id: str) -> dict[str, object]:
            calls.append("reconcile")
            assert client_order_id == "client-1"
            return self.responses.pop(0)

    monkeypatch.setattr(dashboard_module.asyncio, "sleep", fake_sleep)

    order, reconciliation = await dashboard_module._reconcile_submitted_order(
        FakeClient(),  # type: ignore[arg-type]
        order_payload={"client_order_id": "client-1"},
        submitted_order={
            "order_id": "order-1",
            "client_order_id": "client-1",
            "ticker": "AAPL",
            "status": "NEW",
        },
    )

    assert calls == ["reconcile", "sleep", "reconcile"]
    assert order["status"] == "FILLED"
    assert reconciliation["state"] == "client_order_id_confirmed"
    assert reconciliation["terminal"] is True
    assert reconciliation["attempt_count"] == 2


def test_submit_execution_order_allows_closed_market_latest_session_sources(
    monkeypatch: MonkeyPatch,
) -> None:
    overnight = datetime(2026, 5, 12, 2, 30, tzinfo=UTC)
    latest_session_checked = datetime(2026, 5, 11, 22, 0, tzinfo=UTC).isoformat()
    calls: list[str] = []

    async def fake_broker() -> dict[str, object]:
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": overnight.isoformat(),
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
        }

    async def fake_sources() -> list[dict[str, object]]:
        return [
            {
                "schema_version": "0.1.0",
                "source": source,
                "source_tier": "MARKET_DATA",
                "status": "HEALTHY",
                "checked_at": latest_session_checked,
                "freshness": "FRESH",
                "last_success_at": latest_session_checked,
                "observed_lag_seconds": 60,
                "error_count": 0,
                "reliability_score": 1.0,
                "rate_limit_reset_at": None,
                "notes": [],
            }
            for source in ("daily-market-bars", "massive-stock-trades")
        ]

    async def fake_context(**_kwargs: object) -> dict[str, object]:
        return {
            "execution_freshness_gate": {"ready": True, "detail": "closed market fresh"},
            "preview_rows": [
                {
                    "cycle_id": "cycle-1",
                    "ticker": "AAPL",
                    "as_of": "2026-05-07T09:30:00Z",
                    "side": "BUY",
                    "quantity": None,
                    "notional": 1000.0,
                    "time_in_force": "DAY",
                    "order_intent_hash": "a" * 64,
                    "order_approved": True,
                    "submit_enabled": True,
                    "submit_blocker": "ready",
                    "preview": {
                        "cycle_id": "cycle-1",
                        "ticker": "AAPL",
                        "as_of": "2026-05-07T09:30:00Z",
                        "order_intent_hash": "a" * 64,
                        "order_intent_version": "0.1.0",
                    },
                }
            ],
        }

    async def fake_record_intent(row: object, order_payload: object) -> None:
        del row, order_payload
        calls.append("intent")

    async def fake_record_submitted(
        row: object,
        order: object,
        reconciliation: object | None = None,
    ) -> None:
        del row, order, reconciliation
        calls.append("submitted")

    class FakeClient:
        def __init__(self, _config: object) -> None:
            self.client_order_id = ""

        async def submit_order(self, payload: object) -> dict[str, object]:
            calls.append("broker")
            self.client_order_id = str(payload["client_order_id"])  # type: ignore[index]
            return {
                "order_id": "order-1",
                "client_order_id": self.client_order_id,
                "ticker": "AAPL",
                "status": "FILLED",
            }

        async def order_by_client_order_id(self, client_order_id: str) -> dict[str, object]:
            calls.append("reconcile")
            assert client_order_id == self.client_order_id
            return {
                "order_id": "order-1",
                "client_order_id": self.client_order_id,
                "ticker": "AAPL",
                "status": "FILLED",
            }

    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("AGENCY_BROKER_SUBMIT_ENABLED", "true")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(
        dashboard_module,
        "_execution_freshness_now",
        lambda: overnight,
        raising=False,
    )
    monkeypatch.setattr(
        dashboard_module,
        "classify_market_session",
        lambda _now: SimpleNamespace(phase="overnight_after_hours"),
        raising=False,
    )
    monkeypatch.setattr(dashboard_module, "_fresh_broker_status_context", fake_broker)
    monkeypatch.setattr(dashboard_module, "runtime_data_source_status", fake_sources)
    monkeypatch.setattr(dashboard_module, "execution_preview_context", fake_context)
    monkeypatch.setattr(dashboard_module, "_record_order_submission_intent", fake_record_intent)
    monkeypatch.setattr(dashboard_module, "_record_submitted_order", fake_record_submitted)
    monkeypatch.setattr(dashboard_module, "AlpacaBrokerClient", FakeClient)

    response = TestClient(create_app()).post(
        "/execution-preview/orders"
        "?cycle_id=cycle-1&ticker=AAPL&as_of=2026-05-07T09%3A30%3A00Z"
        f"&order_intent_hash={'a' * 64}",
        data={
            "submit_gate_armed": "true",
            "operator_phrase": "submit paper orders",
        },
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert calls == ["intent", "broker", "reconcile", "submitted"]


def test_submit_execution_order_rechecks_freshness_before_broker_submit(
    monkeypatch: MonkeyPatch,
) -> None:
    broker_calls: list[str] = []
    regular_market = datetime(2026, 5, 11, 14, 0, tzinfo=UTC)

    async def fake_broker() -> dict[str, object]:
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": regular_market.isoformat(),
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
        }

    async def fake_sources() -> list[dict[str, object]]:
        fresh = regular_market.isoformat()
        stale = (regular_market - timedelta(minutes=20)).isoformat()
        return [
            {
                "schema_version": "0.1.0",
                "source": "daily-market-bars",
                "source_tier": "MARKET_DATA",
                "status": "HEALTHY",
                "checked_at": fresh,
                "freshness": "FRESH",
                "last_success_at": fresh,
                "observed_lag_seconds": 1,
                "error_count": 0,
                "reliability_score": 1.0,
                "rate_limit_reset_at": None,
                "notes": [],
            },
            {
                "schema_version": "0.1.0",
                "source": "massive-stock-trades",
                "source_tier": "MARKET_DATA",
                "status": "HEALTHY",
                "checked_at": stale,
                "freshness": "FRESH",
                "last_success_at": stale,
                "observed_lag_seconds": 1,
                "error_count": 0,
                "reliability_score": 1.0,
                "rate_limit_reset_at": None,
                "notes": [],
            },
        ]

    async def fake_context(**_kwargs: object) -> dict[str, object]:
        return {
            "execution_freshness_gate": {"ready": True, "detail": "cached context said fresh"},
            "preview_rows": [
                {
                    "cycle_id": "cycle-1",
                    "ticker": "AAPL",
                    "as_of": "2026-05-07T09:30:00Z",
                    "side": "BUY",
                    "quantity": None,
                    "notional": 1000.0,
                    "time_in_force": "DAY",
                    "order_intent_hash": "a" * 64,
                    "order_approved": True,
                    "submit_enabled": True,
                    "submit_blocker": "ready",
                    "preview": {
                        "cycle_id": "cycle-1",
                        "ticker": "AAPL",
                        "as_of": "2026-05-07T09:30:00Z",
                        "order_intent_hash": "a" * 64,
                        "order_intent_version": "0.1.0",
                    },
                }
            ],
        }

    class FakeClient:
        def __init__(self, _config: object) -> None:
            broker_calls.append("init")

        async def submit_order(self, _payload: object) -> dict[str, object]:
            broker_calls.append("submit")
            raise AssertionError("broker submit must not run when critical freshness is stale")

    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("AGENCY_BROKER_SUBMIT_ENABLED", "true")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(
        dashboard_module,
        "_execution_freshness_now",
        lambda: regular_market,
        raising=False,
    )
    monkeypatch.setattr(
        dashboard_module,
        "classify_market_session",
        lambda _now: SimpleNamespace(phase="regular_market"),
        raising=False,
    )
    monkeypatch.setattr(dashboard_module, "_fresh_broker_status_context", fake_broker)
    monkeypatch.setattr(dashboard_module, "runtime_data_source_status", fake_sources)
    monkeypatch.setattr(dashboard_module, "execution_preview_context", fake_context)
    monkeypatch.setattr(dashboard_module, "AlpacaBrokerClient", FakeClient)

    response = TestClient(create_app()).post(
        "/execution-preview/orders"
        "?cycle_id=cycle-1&ticker=AAPL&as_of=2026-05-07T09%3A30%3A00Z"
        f"&order_intent_hash={'a' * 64}",
        data={
            "submit_gate_armed": "true",
            "operator_phrase": "submit paper orders",
        },
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert "massive-stock-trades+source-health+row" in response.headers["location"]
    assert "ticker=AAPL" in response.headers["location"]
    assert broker_calls == []


def test_immediate_execution_freshness_allows_closed_market_latest_session_sources(
    monkeypatch: MonkeyPatch,
) -> None:
    overnight = datetime(2026, 5, 12, 2, 30, tzinfo=UTC)
    latest_session_checked = datetime(2026, 5, 11, 22, 0, tzinfo=UTC).isoformat()
    broker = {
        "connected": True,
        "mode": "paper",
        "checked_at": overnight.isoformat(),
    }
    sources = [
        {
            **_source_health(source),
            "source_tier": "MARKET_DATA",
            "checked_at": latest_session_checked,
            "last_success_at": latest_session_checked,
        }
        for source in ("daily-market-bars", "massive-stock-trades")
    ]

    monkeypatch.setattr(
        dashboard_module,
        "_execution_freshness_now",
        lambda: overnight,
        raising=False,
    )
    monkeypatch.setattr(
        dashboard_module,
        "classify_market_session",
        lambda _now: SimpleNamespace(phase="overnight_after_hours"),
        raising=False,
    )

    gate = dashboard_module._require_immediate_execution_freshness(broker, sources)

    assert gate["ready"] is True
    assert gate["source_max_age_policy_label"] == "closed-market latest completed session"


def test_immediate_execution_freshness_keeps_broker_strict_after_close(
    monkeypatch: MonkeyPatch,
) -> None:
    overnight = datetime(2026, 5, 12, 2, 30, tzinfo=UTC)
    latest_session_checked = datetime(2026, 5, 11, 22, 0, tzinfo=UTC).isoformat()
    broker = {
        "connected": True,
        "mode": "paper",
        "checked_at": (overnight - timedelta(minutes=2)).isoformat(),
    }
    sources = [
        {
            **_source_health(source),
            "source_tier": "MARKET_DATA",
            "checked_at": latest_session_checked,
            "last_success_at": latest_session_checked,
        }
        for source in ("daily-market-bars", "massive-stock-trades")
    ]

    monkeypatch.setattr(
        dashboard_module,
        "_execution_freshness_now",
        lambda: overnight,
        raising=False,
    )
    monkeypatch.setattr(
        dashboard_module,
        "classify_market_session",
        lambda _now: SimpleNamespace(phase="overnight_after_hours"),
        raising=False,
    )

    with pytest.raises(dashboard_module.HTTPException) as exc:
        dashboard_module._require_immediate_execution_freshness(broker, sources)

    assert exc.value.status_code == 409
    assert "Broker snapshot is" in str(exc.value.detail)


def test_record_portfolio_snapshot_uses_fresh_broker_context(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    session = _FakeSession()

    async def fake_fresh_broker() -> dict[str, object]:
        calls.append("fresh-broker")
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": "2026-05-16T07:00:00Z",
            "account": {"status": "ACTIVE", "equity": 100000.0},
            "positions": [],
            "orders": [],
            "gross_exposure_pct": 0.0,
        }

    async def fake_persist_portfolio_snapshot(
        persisted_session: object,
        broker: object,
    ) -> None:
        calls.append("persist")
        assert persisted_session is session
        assert broker["checked_at"] == "2026-05-16T07:00:00Z"  # type: ignore[index]

    @asynccontextmanager
    async def fake_session_provider() -> AsyncIterator[_FakeSession]:
        yield session

    monkeypatch.setattr(dashboard_module, "_fresh_broker_status_context", fake_fresh_broker)
    monkeypatch.setattr(
        dashboard_module,
        "persist_portfolio_snapshot",
        fake_persist_portfolio_snapshot,
    )
    monkeypatch.setattr(dashboard_module, "get_session", fake_session_provider)

    response = TestClient(create_app()).post(
        "/portfolio-monitor/snapshots",
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert session.committed is True
    assert calls == ["fresh-broker", "persist"]


def test_submit_execution_order_reports_post_submit_audit_failure_without_retry_signal(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_broker() -> dict[str, object]:
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
        }

    async def fake_sources() -> list[dict[str, object]]:
        return _fresh_critical_execution_sources()

    async def fake_context(**_kwargs: object) -> dict[str, object]:
        return {
            "execution_freshness_gate": {"ready": True, "detail": "fresh"},
            "preview_rows": [
                {
                    "cycle_id": "cycle-1",
                    "ticker": "AAPL",
                    "as_of": "2026-05-07T09:30:00Z",
                    "side": "BUY",
                    "quantity": None,
                    "notional": 1000.0,
                    "time_in_force": "DAY",
                    "order_intent_hash": "a" * 64,
                    "order_approved": True,
                    "submit_enabled": True,
                    "submit_blocker": "ready",
                    "preview": {
                        "cycle_id": "cycle-1",
                        "ticker": "AAPL",
                        "as_of": "2026-05-07T09:30:00Z",
                        "order_intent_hash": "a" * 64,
                        "order_intent_version": "0.1.0",
                    },
                }
            ],
        }

    async def fake_record_intent(row: object, order_payload: object) -> None:
        del row, order_payload

    async def fake_record_submitted(
        row: object,
        order: object,
        reconciliation: object | None = None,
    ) -> None:
        del row, order, reconciliation
        raise OSError("audit db unavailable")

    class FakeClient:
        def __init__(self, _config: object) -> None:
            self.client_order_id = ""

        async def submit_order(self, payload: object) -> dict[str, object]:
            self.client_order_id = str(payload["client_order_id"])  # type: ignore[index]
            return {
                "order_id": "order-1",
                "client_order_id": self.client_order_id,
                "ticker": "AAPL",
                "status": "ACCEPTED",
            }

        async def order_by_client_order_id(self, client_order_id: str) -> dict[str, object]:
            return {
                "order_id": "order-1",
                "client_order_id": client_order_id,
                "ticker": "AAPL",
                "status": "FILLED",
            }

    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("AGENCY_BROKER_SUBMIT_ENABLED", "true")
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(dashboard_module, "_fresh_broker_status_context", fake_broker)
    monkeypatch.setattr(dashboard_module, "runtime_data_source_status", fake_sources)
    monkeypatch.setattr(dashboard_module, "execution_preview_context", fake_context)
    monkeypatch.setattr(dashboard_module, "_record_order_submission_intent", fake_record_intent)
    monkeypatch.setattr(dashboard_module, "_record_submitted_order", fake_record_submitted)
    monkeypatch.setattr(dashboard_module, "AlpacaBrokerClient", FakeClient)

    response = TestClient(create_app()).post(
        "/execution-preview/orders"
        "?cycle_id=cycle-1&ticker=AAPL&as_of=2026-05-07T09%3A30%3A00Z"
        f"&order_intent_hash={'a' * 64}",
        data={
            "submit_gate_armed": "true",
            "operator_phrase": "submit paper orders",
        },
        follow_redirects=False,
    )

    assert response.status_code == HTTP_SEE_OTHER
    assert "verify+Alpaca+before+retrying" in response.headers["location"]
    assert "ticker=AAPL" in response.headers["location"]


def test_execution_preview_summary_explains_portfolio_manager_check() -> None:
    summary = execution_module.execution_preview_summary(
        [],
        broker={
            "connected": True,
            "mode": "paper",
            "gross_exposure_pct": 12.5,
            "account": {
                "equity": 100000.0,
                "buying_power": 200000.0,
            },
            "positions": [{"ticker": "AAPL"}],
        },
    )

    assert summary["portfolio_check_label"] == "Checked"
    assert summary["portfolio_equity_label"] == "$100,000.00"
    assert summary["portfolio_buying_power_label"] == "$200,000.00"
    assert summary["portfolio_position_count"] == 1
    assert "current Alpaca paper account" in str(summary["portfolio_check_detail"])


def test_pending_opening_order_exposure_counts_short_sells_and_limit_orders() -> None:
    broker = {
        "account": {"equity": 10000.0},
        "positions": [{"ticker": "AAPL", "side": "long", "qty": 5.0}],
        "orders": [
            {
                "ticker": "MSFT",
                "side": "SELL",
                "status": "ACCEPTED",
                "qty": 10.0,
                "limit_price": 200.0,
            },
            {
                "ticker": "AAPL",
                "side": "SELL",
                "status": "ACCEPTED",
                "qty": 5.0,
                "limit_price": 100.0,
            },
        ],
    }

    assert portfolio_module._pending_opening_order_exposure_pct(broker) == 20.0


def test_portfolio_and_learning_summaries_use_contract_payloads() -> None:
    portfolio = build_portfolio_monitor([], generated_at="2026-05-07T09:34:00Z")
    learning = build_learning_outcome(generated_at="2026-05-07T09:35:00Z")

    assert portfolio_monitor_summary(portfolio)["position_count"] == 0
    assert learning_summary(learning)["status"] == "PREMATURE"


def test_candidate_detail_summary_uses_latest_report() -> None:
    reports = final_selection_rows([build_final_selection(_evidence_pack()).selection_report])
    summary = candidate_detail_summary("AAPL", reports, [_lifecycle_event()])

    assert summary["report_count"] == 1
    assert summary["event_count"] == 1
    assert summary["latest_action"] == "WATCH"
    assert "backed by 2 independent source(s)" in str(summary["detail"])


def test_candidate_decision_brief_explains_selection_action() -> None:
    reports = final_selection_rows([build_final_selection(_evidence_pack()).selection_report])

    brief = candidate_decision_brief(
        "AAPL",
        reports[0],
        {
            "detail": "2 matching email events.",
            "meaning": "Email alerts are mixed.",
            "status_class": "warn",
        },
        {"decision": "Pending"},
    )

    assert brief["state_label"] == "Selected For Review"
    assert brief["headline"] == "AAPL is selected for human review, not automatic trading."
    assert "approve, defer, or reject" in str(brief["next_step"])
    assert brief["signal_counts"][0]["value"] == EXPECTED_CONFIRMED_SIGNAL_COUNT
    assert brief["support_cards"][0]["label"] == "Fundamentals"
    assert len(brief["decision_points"]) == EXPECTED_BRIEF_POINT_COUNT


def test_candidate_decision_brief_shows_concrete_signal_evidence() -> None:
    reports = final_selection_rows([build_final_selection(_evidence_pack()).selection_report])

    brief = candidate_decision_brief(
        "AAPL",
        reports[0],
        {
            "detail": "2 matching email events.",
            "meaning": "Email alerts are mixed.",
            "status_class": "warn",
        },
        {"decision": "Pending"},
    )

    support = brief["support_cards"][0]
    assert support["label"] == "Fundamentals"
    assert "score +0.70 bullish" in str(support["detail"])
    assert "90% confidence" in str(support["detail"])
    assert "source sec-edgar" in str(support["detail"])
    assert "as of 2026-05-07 08:59 UTC" in str(support["detail"])
    assert "actionable" in str(support["meta"]).lower()


def test_candidate_decision_brief_support_cards_are_decision_driving_only() -> None:
    reports = final_selection_rows([_selection_report_with_signal_mix()])

    brief = candidate_decision_brief(
        "MSFT",
        reports[0],
        {
            "detail": "No email events.",
            "meaning": "Email alerts are unavailable.",
            "status_class": "neutral",
        },
        {"decision": "Pending"},
    )

    assert [card["label"] for card in brief["support_cards"]] == ["Fundamentals"]
    assert "advisory bullish" in str(brief["signal_mix_note"]).lower()


def test_candidate_detail_report_rows_add_signal_trigger_evidence() -> None:
    reports = candidate_detail_report_rows(
        [build_final_selection(_evidence_pack()).selection_report]
    )

    signal = reports[0]["actionable_signals"][0]
    assert "trigger_headline" in signal
    assert "trigger_detail" in signal
    assert "trigger_cards" in signal
    assert "2026-05-07 08:59 UTC" in str(signal["trigger_window"])


def test_candidate_detail_report_rows_can_skip_rich_signal_reconstruction(
    monkeypatch: MonkeyPatch,
) -> None:
    def forbidden_enrichment(_rows: object) -> list[dict[str, object]]:
        raise AssertionError("audit shell should not rebuild rich signal evidence")

    monkeypatch.setattr(
        candidates_module,
        "enrich_signal_rows_with_evidence",
        forbidden_enrichment,
    )

    reports = candidate_detail_report_rows(
        [_selection_report_with_signal_mix()],
        include_rich_signal_evidence=False,
    )

    assert reports
    assert reports[0]["ticker"] == "MSFT"
    assert reports[0]["actionable_signals"]


async def test_candidate_detail_light_context_skips_timeline_and_risk_lookups(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_reports(
        *,
        ticker: str | None = None,
        limit: int = EXPECTED_FINAL_SELECTION_REPORT_LIMIT,
    ) -> list[dict[str, object]]:
        assert ticker == "MSFT"
        assert limit == 1
        return [_selection_report_with_signal_mix()]

    async def forbidden_timeline(**_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("light candidate audit should not query timeline")

    async def forbidden_risk(**_kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("light candidate audit should not query risk decisions")

    async def fake_data_load_status() -> dict[str, object]:
        return {"state": "ready", "datasets": [], "lane_states": []}

    monkeypatch.setattr(candidates_module, "_dashboard_selection_reports", fake_reports)
    monkeypatch.setattr(candidates_module, "_dashboard_candidate_timeline", forbidden_timeline)
    monkeypatch.setattr(candidates_module, "_dashboard_risk_decisions", forbidden_risk)
    monkeypatch.setattr(
        candidates_module,
        "_candidate_audit_light_data_load_status",
        fake_data_load_status,
    )

    context = await candidates_module.candidate_detail_context(
        "msft",
        include_rich_signal_evidence=False,
    )

    assert context["ticker"] == "MSFT"
    assert context["timeline"] == []
    assert context["review"]["can_record"] is True


def test_candidate_signal_template_shows_hard_cards_for_all_signal_groups() -> None:
    template = Path("src/agency/templates/candidate_detail.html").read_text()

    assert template.count("signal-trigger-card-grid") >= 3


def test_candidate_email_evidence_summarizes_email_and_feed_rows(tmp_path: Path) -> None:
    event_path = tmp_path / "subscription_emails.parquet"
    news_path = tmp_path / "news_rss.parquet"
    pd.DataFrame(
        [
            {
                "ticker": "MSFT",
                "service": "seeking_alpha",
                "event_type": "sa_analyst_article",
                "direction": "BULLISH",
                "title": "Seeking Alpha Email: MSFT article",
                "timestamp_as_of": "2026-05-08T12:00:00+00:00",
                "linked_content_status": "article_analyzed",
                "linked_content_summary": "Linked content thesis: constructive context.",
            },
            {
                "ticker": "MSFT",
                "service": "seeking_alpha",
                "event_type": "sa_rank_change",
                "direction": "BEARISH",
                "title": "Seeking Alpha Email: MSFT rank change",
                "timestamp_as_of": "2026-05-08T11:00:00+00:00",
                "linked_content_status": "not_requested",
                "linked_content_summary": None,
            },
            {
                "ticker": "AAPL",
                "service": "zacks",
                "event_type": "zacks_rank_change",
                "direction": "BULLISH",
                "title": "Other ticker",
                "timestamp_as_of": "2026-05-08T10:00:00+00:00",
                "linked_content_status": "not_requested",
                "linked_content_summary": None,
            },
        ]
    ).to_parquet(event_path)
    pd.DataFrame(
        [
            {
                "ticker": "MSFT",
                "feed_name": "Seeking Alpha Email",
                "title": "MSFT email-derived row",
                "summary": "Email-derived evidence classified as bullish.",
                "timestamp_as_of": "2026-05-08T12:00:00+00:00",
                "source_tier": "PAID_SUB_EMAIL",
            },
            {
                "ticker": "MSFT",
                "feed_name": "SEC",
                "title": "Non-email row",
                "summary": "Official filing.",
                "timestamp_as_of": "2026-05-08T09:00:00+00:00",
                "source_tier": "OFFICIAL_FILING",
            },
        ]
    ).to_parquet(news_path)

    evidence = candidate_email_evidence("msft", event_path=event_path, news_path=news_path)

    assert evidence["event_count"] == EXPECTED_EMAIL_EVENT_COUNT
    assert evidence["feed_count"] == 1
    assert evidence["analyzed_count"] == 1
    assert evidence["direction_summary"] == "Bullish 1, Bearish 1"
    assert "mixed" in str(evidence["meaning"])
    assert evidence["service_summary"] == "Seeking Alpha 2"
    assert evidence["rows"][0]["linked_status_label"] == "Article Analyzed"
    assert "Article opened for MSFT" in str(evidence["rows"][0]["summary"])
    assert "Direct relevance" in str(evidence["rows"][0]["summary"])
    assert evidence["feed_rows"][0]["title"] == "MSFT email-derived row"
    assert len(evidence["paired_rows"]) == EXPECTED_EMAIL_EVENT_COUNT
    assert evidence["paired_rows"][0]["mailbox"]["title"] == "Seeking Alpha Email: MSFT article"
    assert evidence["paired_rows"][0]["interpretation"]["title"] == "MSFT email-derived row"
    assert evidence["primary_takeaway"].startswith("Mailbox history is mixed")
    assert "Strongest analyzed article signal is bullish" in str(evidence["primary_takeaway"])
    assert evidence["pipeline_summary"].startswith("Analyzed article rows feed")
    assert evidence["insight_cards"][0]["article_focus"] == "Direct headline focus on MSFT"
    assert "Direct relevance" in str(evidence["insight_cards"][0]["relevance"])
    assert "context-only bullish thesis" in str(
        evidence["paired_rows"][0]["interpretation"]["summary"]
    )
    assert evidence["paired_rows"][0]["interpretation"]["status_label"] == "Article Thesis"
    assert evidence["paired_rows"][1]["interpretation"]["status_label"] == "Pending"
    assert "Headline-only bearish" in str(evidence["paired_rows"][1]["mailbox"]["summary"])

    judged = candidate_email_evidence_with_judgement(
        "MSFT",
        evidence,
        {
            "action": "WATCH",
            "gate_status": "PASS",
            "conviction_pct": 58,
            "actionable_signals": [
                {"direction": "BULLISH", "summary": "insider activity is constructive"}
            ],
            "context_signals": [],
            "suppressed_signals": [],
        },
    )
    assert "supports the judgment" in str(
        judged["insight_cards"][0]["judgement_contribution"]
    )
    assert "does not change the judgment yet" in str(
        judged["insight_cards"][1]["judgement_contribution"]
    )


def test_candidate_news_evidence_shows_match_reason_and_confidence(tmp_path: Path) -> None:
    news_path = tmp_path / "news_rss.parquet"
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "feed_name": "PR Newswire",
                "title": "Apple Inc. announces AI launch",
                "summary": "The company raised its outlook.",
                "timestamp_as_of": "2026-05-08T12:00:00+00:00",
                "source_tier": "RSS_HEADLINE",
                "ticker_match_status": "resolved",
                "ticker_match_method": "legal_name",
                "ticker_match_confidence": 0.88,
                "ticker_match_reason": "Legal-name alias 'Apple Inc.' matched AAPL.",
                "matched_text": "Apple Inc.",
            }
        ]
    ).to_parquet(news_path)

    evidence = candidate_news_evidence("aapl", news_path=news_path)

    assert evidence["resolved_count"] == 1
    assert evidence["rows"][0]["match_explanation"] == (
        'PR Newswire matched AAPL by legal name "Apple Inc."; confidence 0.88.'
    )
    assert evidence["rows"][0]["signal_use"] == "Ticker news signal"


def test_unresolved_generic_news_is_reported_as_context_not_signal(tmp_path: Path) -> None:
    news_path = tmp_path / "news_rss.parquet"
    pd.DataFrame(
        [
            {
                "ticker": None,
                "feed_name": "PR Newswire",
                "title": "Global market futures rise",
                "summary": "No company-specific ticker was detected.",
                "timestamp_as_of": "2026-05-08T12:00:00+00:00",
                "source_tier": "RSS_HEADLINE",
                "ticker_match_status": "unresolved",
                "ticker_match_method": None,
                "ticker_match_confidence": 0.0,
                "ticker_match_reason": "No high-confidence ticker match was found.",
                "matched_text": None,
            }
        ]
    ).to_parquet(news_path)

    evidence = candidate_news_evidence("AAPL", news_path=news_path)

    assert evidence["resolved_count"] == 0
    assert evidence["unresolved_context_count"] == 1
    assert evidence["context_rows"][0]["signal_use"] == "Context only"
    assert evidence["context_rows"][0]["match_explanation"] == (
        "Generic PR Newswire headline collected but not attached to AAPL because "
        "no high-confidence ticker match was found."
    )


def test_candidate_news_evidence_labels_already_used_rss_rows(tmp_path: Path) -> None:
    news_path = tmp_path / "news_rss.parquet"
    ledger_path = tmp_path / "news_rss_consumed.json"
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "feed_name": "PR Newswire",
                "title": "Apple Inc. announces AI launch",
                "summary": "The company raised its outlook.",
                "timestamp_as_of": "2026-05-08T12:00:00+00:00",
                "source_tier": "RSS_HEADLINE",
                "source_id": "rss:aapl:1",
                "ticker_match_status": "resolved",
                "ticker_match_method": "legal_name",
                "ticker_match_confidence": 0.88,
                "matched_text": "Apple Inc.",
            },
            {
                "ticker": "AAPL",
                "feed_name": "PR Newswire",
                "title": "Apple supplier signs expansion deal",
                "summary": "The supplier announced capacity expansion.",
                "timestamp_as_of": "2026-05-08T11:00:00+00:00",
                "source_tier": "RSS_HEADLINE",
                "source_id": "rss:aapl:2",
                "ticker_match_status": "resolved",
                "ticker_match_method": "alias",
                "ticker_match_confidence": 0.74,
                "matched_text": "Apple",
            },
        ]
    ).to_parquet(news_path)
    ledger_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": {
                    "rss:aapl:1": {
                        "source_id": "rss:aapl:1",
                        "cycle_id": "cycle-1",
                        "ticker": "AAPL",
                        "as_of": "2026-05-08T00:00:00+00:00",
                        "used_at": "2026-05-08T13:00:00+00:00",
                        "lane": "news",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    evidence = candidate_news_evidence(
        "AAPL",
        news_path=news_path,
        news_consumption_ledger_path=ledger_path,
    )

    used_row = next(row for row in evidence["rows"] if row["source_id"] == "rss:aapl:1")
    unused_row = next(row for row in evidence["rows"] if row["source_id"] == "rss:aapl:2")
    assert evidence["used_count"] == 1
    assert evidence["unused_resolved_count"] == 1
    assert used_row["signal_use"] == "Already used in prior live decision"
    assert used_row["consumption_note"] == (
        "Already used by cycle cycle-1 at 2026-05-08 13:00 UTC; "
        "the live news lane will not reuse this headline automatically."
    )
    assert unused_row["signal_use"] == "Ticker news signal"


def test_candidate_email_empty_state_uses_operator_friendly_copy(tmp_path: Path) -> None:
    evidence = candidate_email_evidence(
        "NVDA",
        event_path=tmp_path / "missing_subscription_emails.parquet",
        news_path=tmp_path / "missing_news_rss.parquet",
    )
    judged = candidate_email_evidence_with_judgement(
        "NVDA",
        evidence,
        {
            "action": "WATCH",
            "gate_status": "PASS",
            "conviction_pct": 100,
            "actionable_signals": [{"direction": "BULLISH", "summary": "institutional positioning is constructive"}],
            "context_signals": [],
            "suppressed_signals": [],
        },
    )

    assert "No subscription article analysis is attached" in str(judged["judgement_summary"])
    assert "subscription_thesis" not in str(judged["pipeline_summary"])
    assert "No analyzed subscription article changes" not in str(judged["judgement_summary"])


def test_candidate_email_evidence_counts_keyword_only_analysis(tmp_path: Path) -> None:
    event_path = tmp_path / "subscription_emails.parquet"
    news_path = tmp_path / "missing_news.parquet"
    pd.DataFrame(
        [
            {
                "ticker": "MSFT",
                "service": "seeking_alpha",
                "event_type": "sa_analyst_article",
                "direction": "BULLISH",
                "title": "Seeking Alpha Email: MSFT: keyword-only article",
                "timestamp_as_of": "2026-05-08T12:00:00+00:00",
                "linked_content_status": "article_analyzed_deterministic_fallback",
                "linked_content_summary": "Linked content thesis: keyword-only context.",
            }
        ]
    ).to_parquet(event_path)

    evidence = candidate_email_evidence("MSFT", event_path=event_path, news_path=news_path)

    assert evidence["analyzed_count"] == 1
    assert evidence["rows"][0]["linked_status_label"] == "Keyword-Only Analysis"
    assert evidence["rows"][0]["linked_status_class"] == "warn"
    assert "keyword-only fallback" in str(evidence["rows"][0]["detail"])
    assert evidence["paired_rows"][0]["interpretation"]["status_class"] == "warn"


def test_candidate_email_evidence_treats_legacy_asset_links_as_headline_rows(
    tmp_path: Path,
) -> None:
    event_path = tmp_path / "subscription_emails.parquet"
    news_path = tmp_path / "news_rss.parquet"
    asset_url = "https://staticx.zacks.com/images/zacks/logos/zacks_logo.png"
    pd.DataFrame(
        [
            {
                "ticker": "AMZN",
                "service": "zacks",
                "event_type": "zacks_rank_change",
                "direction": "BEARISH",
                "title": "Zacks Email: zacks rank change - Daily portfolio update",
                "timestamp_as_of": "2026-05-08T11:15:04+00:00",
                "linked_content_status": "article_fetch_limited",
                "linked_content_url": asset_url,
                "source_url": asset_url,
            },
        ]
    ).to_parquet(event_path)
    pd.DataFrame(
        [
            {
                "ticker": "AMZN",
                "feed_name": "Zacks Email",
                "title": "Zacks Email: zacks rank change - Daily portfolio update",
                "summary": "Email-derived Zacks evidence classified as bearish.",
                "timestamp_as_of": "2026-05-08T11:15:04+00:00",
                "source_tier": "PAID_SUB_EMAIL",
                "source_url": asset_url,
            },
        ]
    ).to_parquet(news_path)

    evidence = candidate_email_evidence("AMZN", event_path=event_path, news_path=news_path)

    assert evidence["rows"][0]["linked_status_label"] == "Non-Article Link"
    assert "static/non-article" in str(evidence["meaning"])
    assert evidence["paired_rows"][0]["interpretation"]["status_label"] == "Headline Row"
    assert evidence["paired_rows"][0]["interpretation"]["status_class"] == "neutral"


def test_candidate_email_evidence_dedupes_attempts_and_shows_time(
    tmp_path: Path,
) -> None:
    event_path = tmp_path / "subscription_emails.parquet"
    news_path = tmp_path / "news_rss.parquet"
    title = "Seeking Alpha Email: sa news - AAPL: chip report"
    source_url = "https://email.example.test/aapl-chip-report"
    message_hash = "same-message"
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "service": "seeking_alpha",
                "event_type": "sa_news",
                "direction": "BULLISH",
                "title": title,
                "timestamp_as_of": "2026-05-08T16:56:16+00:00",
                "linked_content_status": "not_requested",
                "source_url": source_url,
                "message_id_hash": message_hash,
            },
            {
                "ticker": "AAPL",
                "service": "seeking_alpha",
                "event_type": "sa_news",
                "direction": "BULLISH",
                "title": title,
                "timestamp_as_of": "2026-05-08T16:56:16+00:00",
                "linked_content_status": "article_fetch_limited",
                "source_url": source_url,
                "message_id_hash": message_hash,
            },
        ]
    ).to_parquet(event_path)
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "feed_name": "Seeking Alpha Email",
                "title": title,
                "summary": "Email-derived evidence classified as bullish.",
                "timestamp_as_of": "2026-05-08T16:56:16+00:00",
                "source_tier": "PAID_SUB_EMAIL",
                "source_url": source_url,
            },
        ]
    ).to_parquet(news_path)

    evidence = candidate_email_evidence("AAPL", event_path=event_path, news_path=news_path)

    assert evidence["event_count"] == 1
    assert len(evidence["rows"]) == 1
    assert len(evidence["insight_cards"]) == 1
    assert evidence["rows"][0]["linked_status_label"] == "Limit Reached"
    assert evidence["rows"][0]["timestamp_label"] == "2026-05-08 16:56 UTC"
    assert evidence["insight_cards"][0]["timestamp_label"] == "2026-05-08 16:56 UTC"
    assert "2026-05-08 16:56 UTC" in str(evidence["paired_rows"][0]["mailbox"]["meta"])
    assert evidence["paired_rows"][0]["mailbox"]["status_label"] == "Limit Reached"


def test_candidate_email_evidence_ties_articles_to_current_judgement() -> None:
    latest_report: dict[str, object] = {
        "action": "WATCH",
        "gate_status": "PASS",
        "conviction_pct": 64,
        "actionable_signals": [
            {
                "direction": "BULLISH",
                "summary": "abnormal volume and fundamentals support review",
                "score": "+0.70 bullish",
            }
        ],
        "context_signals": [],
        "suppressed_signals": [
            {
                "direction": "BEARISH",
                "summary": "valuation risk still needs monitoring",
                "score": "-0.40 bearish",
            }
        ],
    }
    direct = {
        "ticker": "MSFT",
        "title": "Seeking Alpha Email: MSFT: analyst article",
        "timestamp": "2026-05-08T12:00:00+00:00",
        "direction": "BULLISH",
        "article_direction": "BULLISH",
        "linked_content_status": "article_analyzed",
        "article_focus": "Direct headline focus on MSFT",
        "ticker_relevance": "Direct relevance: the article is focused on MSFT.",
        "catalyst_text": "analyst/rating",
        "risk_text": "valuation",
        "thesis": "Direct relevance: the article is focused on MSFT.",
        "decision_use": "Treat as context-only bullish thesis.",
    }
    headline_only = {
        **direct,
        "title": "Seeking Alpha Email: MSFT: headline only",
        "timestamp": "2026-05-08T11:00:00+00:00",
        "linked_content_status": "not_requested",
    }

    evidence = candidate_email_evidence_with_judgement(
        "MSFT",
        {
            "primary_takeaway": "Strongest analyzed article signal is bullish.",
            "rows": [direct, headline_only],
            "insight_cards": [direct, headline_only],
            "feed_rows": [],
        },
        latest_report,
    )

    first_card = evidence["insight_cards"][0]
    assert "current MSFT Watch judgment" in str(first_card["judgement_contribution"])
    assert "supports the judgment" in str(first_card["judgement_contribution"])
    assert "adds analyst/rating" in str(first_card["judgement_contribution"])
    assert "abnormal volume and fundamentals support review" in str(
        first_card["judgement_contribution"]
    )
    assert first_card["judgement_class"] == "pass"
    assert "Judgment contribution" in str(evidence["primary_takeaway"])
    assert "does not change the judgment yet" in str(
        evidence["rows"][1]["judgement_contribution"]
    )
    assert "does not change the judgment yet" in str(
        evidence["paired_rows"][1]["interpretation"]["summary"]
    )

    secondary = {
        **direct,
        "ticker": "NVDA",
        "title": "Seeking Alpha Email: MSFT: quantum basket article",
        "article_focus": "Secondary context; headline focus is MSFT",
        "ticker_relevance": (
            "Secondary relevance: headline focus is MSFT, while NVDA was detected "
            "in the article context. Use it as basket/theme evidence, not as a "
            "standalone NVDA thesis."
        ),
    }
    nvda_evidence = candidate_email_evidence_with_judgement(
        "NVDA",
        {
            "primary_takeaway": "Strongest analyzed article signal is bullish.",
            "rows": [secondary],
            "insight_cards": [secondary],
            "feed_rows": [],
        },
        latest_report,
    )

    secondary_card = nvda_evidence["insight_cards"][0]
    assert "current NVDA Watch judgment" in str(
        secondary_card["judgement_contribution"]
    )
    assert "secondary theme or basket context" in str(
        secondary_card["judgement_contribution"]
    )
    assert "not as a standalone NVDA thesis" in str(
        secondary_card["judgement_contribution"]
    )
    assert secondary_card["judgement_class"] == "warn"


def test_candidate_review_summary_uses_latest_human_review_event() -> None:
    reports = final_selection_rows([build_final_selection(_evidence_pack()).selection_report])

    review = candidate_review_summary(reports, [_human_review_event()])

    assert review["can_record"] is True
    assert review["decision"] == "Defer"
    assert review["status_class"] == "warn"
    assert review["reason"] == "paper review deferred"
    assert review["event_time_label"] == "2026-05-07 10:00 UTC"
    assert "decision=APPROVE" in str(review["approve_action"])
    assert "decision=DEFER" in str(review["defer_action"])
    assert "decision=REJECT" in str(review["reject_action"])


def test_candidate_detail_report_rows_show_human_review_state() -> None:
    report = build_final_selection(_evidence_pack()).selection_report

    rows = candidate_detail_report_rows([report], review_events=[_human_review_event()])

    assert rows[0]["human_review_decision"] == "Defer"
    assert rows[0]["human_review_class"] == "warn"
    assert rows[0]["human_review_reason"] == "paper review deferred"


def test_candidate_detail_sticky_bar_uses_current_review_state() -> None:
    template = Path("src/agency/templates/candidate_detail.html").read_text()

    assert "pending review</span>" not in template
    assert "Review: {{ review.decision }}" in template


def test_candidate_detail_caution_requires_real_checkbox_acknowledgement() -> None:
    template = Path("src/agency/templates/candidate_detail.html").read_text()

    assert 'href="#paper-review-heading">Review Caution' in template
    assert 'name="caution_acknowledged"' in template
    assert 'value="true"' in template


def test_candidate_detail_exposes_manual_llm_review_button() -> None:
    template = Path("src/agency/templates/candidate_detail.html").read_text()

    assert 'action="/candidates/{{ ticker }}/llm-review"' in template
    assert "Run LLM review for this stock" in template
    assert 'name="cycle_id"' in template
    assert 'name="as_of"' in template


def test_execution_preview_banner_uses_submit_gate_state() -> None:
    template = Path("src/agency/templates/execution_preview.html").read_text()

    assert "Broker submit is disabled until you explicitly enable it in Policy." not in template
    assert "summary.submit_gate_open" in template
    assert "approved READY order-intent rows only" in template


def test_candidate_review_summary_handles_missing_report() -> None:
    review = candidate_review_summary([], [])

    assert review["can_record"] is False
    assert review["decision"] == "No Report"
    assert review["status_class"] == "neutral"


def test_policy_sections_are_loaded_control_groups() -> None:
    sections = policy_sections()

    assert sections[0]["title"] == "Targets and Discipline"
    assert sections[-1]["title"] == "Permissions"


def test_timeline_rows_summarize_lifecycle_events() -> None:
    rows = timeline_rows([_lifecycle_event()])

    assert rows == [
        {
            "event_type": "DETERMINISTIC_ACTION",
            "event_time": "2026-05-07T09:31:00Z",
            "event_time_label": "2026-05-07 09:31 UTC",
            "status": "ACTIONABLE",
            "reason": "quality_positive",
        }
    ]


def test_final_selection_rows_show_human_review_state() -> None:
    report = build_final_selection(_evidence_pack()).selection_report

    rows = final_selection_rows([report], review_events=[_human_review_event()])

    assert rows[0]["human_review_decision"] == "Defer"
    assert rows[0]["human_review_class"] == "warn"
    assert rows[0]["human_review_time_label"] == "2026-05-07 10:00 UTC"


def test_command_dashboard_template_places_review_queue_before_system_health() -> None:
    template = Path("src/agency/templates/dashboard.html").read_text()

    assert template.index('id="review-queue-heading"') < template.index(
        'id="system-status-heading"'
    )


def test_command_dashboard_execute_link_preserves_selected_ticker() -> None:
    template = Path("src/agency/templates/dashboard.html").read_text()

    assert (
        'href="/execution-preview?ticker={{ item.ticker }}#focused-preview-{{ item.ticker }}"'
        in template
    )


def test_contracts_endpoint_lists_contracts() -> None:
    client = TestClient(create_app())

    response = client.get("/contracts")

    assert response.status_code == HTTP_OK
    names = {item["name"] for item in response.json()}
    assert {
        "selection-report",
        "evidence-pack",
        "data-source-health",
        "agent-run",
        "prompt-audit",
        "execution-state",
        "risk-snapshot",
        "portfolio-snapshot",
        "risk-decision",
        "execution-preview",
    }.issubset(names)


def test_contract_schema_endpoint_returns_json_schema() -> None:
    client = TestClient(create_app())

    response = client.get("/contracts/selection-report")

    assert response.status_code == HTTP_OK
    assert response.json()["title"] == "SelectionReport"


def test_contract_schema_endpoint_exposes_runtime_audit_contract() -> None:
    client = TestClient(create_app())

    response = client.get("/contracts/execution-state")

    assert response.status_code == HTTP_OK
    assert response.json()["title"] == "ExecutionState"


def test_contract_schema_endpoint_rejects_unknown_contract() -> None:
    client = TestClient(create_app())

    response = client.get("/contracts/unknown")

    assert response.status_code == HTTP_NOT_FOUND


def test_data_source_status_endpoint_returns_valid_status_payload(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENCY_RUNTIME_ARTIFACT_FALLBACK", "false")
    client = TestClient(create_app())

    response = client.get("/status/data-sources")

    assert response.status_code == HTTP_OK
    payload = response.json()
    assert payload
    assert payload[0]["source"]
    assert payload[0]["status"] in {
        "HEALTHY",
        "DEGRADED",
        "STALE",
        "UNAVAILABLE",
        "RATE_LIMITED",
    }


def test_live_readiness_status_endpoint_returns_gate(monkeypatch: MonkeyPatch) -> None:
    async def empty_rows() -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(health_module, "_default_source_status", empty_rows)
    monkeypatch.setattr(health_module, "_default_selection_reports", empty_rows)
    monkeypatch.setattr(health_module, "_default_risk_decisions", empty_rows)
    client = TestClient(create_app())

    response = client.get("/status/live-readiness")

    assert response.status_code == HTTP_OK
    assert response.json()["ready"] is False
    assert "verdict" in response.json()


async def test_runtime_data_source_status_uses_repository_payloads() -> None:
    async def reader(session: object) -> list[dict[str, object]]:
        assert session == "fake-session"
        return [_source_health("sec-edgar")]

    payloads = await runtime_data_source_status(
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["source"] == "sec-edgar"
    assert payloads[0]["status"] == "HEALTHY"


async def test_runtime_data_source_status_overlays_unified_readiness(
    monkeypatch: MonkeyPatch,
) -> None:
    raw_daily = _source_health("daily-market-bars")
    raw_daily["source_tier"] = "MARKET_DATA"

    def fake_data_load_status(**_: object) -> dict[str, object]:
        return {
            "freshness_rows": [
                {
                    "source": "daily-market-bars",
                    "status": "DEGRADED",
                    "freshness": "FRESH",
                    "checked_at": "2026-05-19T08:57:20+00:00",
                    "last_success_at": "2026-05-18T00:00:00+00:00",
                    "detail": (
                        "massive_daily_bars lane is DEGRADED / FRESH; "
                        "Active-universe coverage is 1/2 active ticker(s); missing MSFT."
                    ),
                }
            ]
        }

    async def reader(session: object) -> list[dict[str, object]]:
        assert session == "fake-session"
        return [raw_daily]

    monkeypatch.setattr(health_module, "load_data_load_status", fake_data_load_status)

    payloads = await runtime_data_source_status(
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["source"] == "daily-market-bars"
    assert payloads[0]["status"] == "DEGRADED"
    assert payloads[0]["freshness"] == "FRESH"
    assert payloads[0]["checked_at"] == "2099-01-01T09:30:00Z"
    assert "unified_readiness_override" in " ".join(payloads[0]["notes"])
    assert "missing MSFT" in " ".join(payloads[0]["notes"])


async def test_runtime_data_source_status_falls_back_for_empty_repository() -> None:
    async def reader(session: object) -> list[dict[str, object]]:
        del session
        return []

    payloads = await runtime_data_source_status(
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["source"] == "source-health-monitor"


async def test_runtime_data_source_status_filters_demo_seed_rows() -> None:
    async def reader(session: object) -> list[dict[str, object]]:
        assert session == "fake-session"
        noted_demo = _source_health("yfinance-daily")
        noted_demo["notes"] = ["demo runtime seed"]
        return [
            _source_health("demo-runtime-seed"),
            noted_demo,
            _source_health("sec-edgar"),
        ]

    payloads = await runtime_data_source_status(
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert [payload["source"] for payload in payloads] == ["sec-edgar"]


async def test_runtime_data_source_status_uses_latest_artifact_when_db_unavailable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENCY_RUNTIME_ARTIFACT_FALLBACK", "true")
    artifact = tmp_path / "source-health.json"
    artifact.write_text(
        json.dumps([_source_health("massive-stock-trades")]),
        encoding="utf-8",
    )

    payloads = await runtime_data_source_status(
        session_provider=_raising_session_provider,
        artifact_root=tmp_path,
    )

    assert [payload["source"] for payload in payloads] == ["massive-stock-trades"]
    assert "runtime_artifact_fallback" in payloads[0]["notes"]
    assert health_module._source_health_origin_label(payloads) == "runtime artifact fallback"
    assert shared_module._source_health_origin_label(payloads) == "runtime artifact fallback"


async def test_runtime_data_source_status_falls_back_for_missing_db() -> None:
    payloads = await runtime_data_source_status(
        session_provider=_raising_session_provider,
        artifact_root=Path("missing-runtime-artifacts"),
    )

    assert payloads[0]["source"] == "source-health-monitor"


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


@asynccontextmanager
async def _fake_session_provider() -> AsyncIterator[object]:
    yield "fake-session"


@asynccontextmanager
async def _raising_session_provider() -> AsyncIterator[object]:
    raise OSError("database unavailable")
    yield


def _source_health(source: str) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "source": source,
        "source_tier": "OFFICIAL_FILING",
        "status": "HEALTHY",
        "checked_at": "2099-01-01T09:30:00Z",
        "freshness": "FRESH",
        "last_success_at": "2099-01-01T09:29:00Z",
        "observed_lag_seconds": 60,
        "error_count": 0,
        "reliability_score": 1.0,
        "rate_limit_reset_at": None,
        "notes": [],
    }


def _fresh_critical_execution_sources() -> list[dict[str, object]]:
    checked_at = datetime.now(UTC).isoformat()
    return [
        {
            "schema_version": "0.1.0",
            "source": source,
            "source_tier": "MARKET_DATA",
            "status": "HEALTHY",
            "checked_at": checked_at,
            "freshness": "FRESH",
            "last_success_at": checked_at,
            "observed_lag_seconds": 1,
            "error_count": 0,
            "reliability_score": 1.0,
            "rate_limit_reset_at": None,
            "notes": [],
        }
        for source in ("daily-market-bars", "massive-stock-trades")
    ]


def _degraded_source_health() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "source": "source-health-monitor",
        "source_tier": "MARKET_DATA",
        "status": "UNAVAILABLE",
        "checked_at": "2099-01-01T09:30:00Z",
        "freshness": "UNAVAILABLE",
        "last_success_at": None,
        "observed_lag_seconds": None,
        "error_count": 0,
        "reliability_score": 0.0,
        "rate_limit_reset_at": None,
        "notes": ["runtime source monitors are not wired yet"],
    }


def _market_regime_snapshot() -> dict[str, object]:
    return {
        "active_nav": "market",
        "summary": {
            "topbar_label": "Risk On / data through 2026-05-08",
            "status_class": "pass",
            "headline": "Market backdrop is constructive enough for normal paper review.",
            "interpretation": "Benchmarks and breadth are supportive.",
            "decision_guidance": "Use sector tailwinds as corroboration.",
            "regime_label": "Risk On",
            "as_of": "2026-05-08",
            "confidence_pct": 91,
        },
        "kpis": [
            {"label": "Regime", "value": "Risk On", "detail": "91% confidence", "class": "pass"}
        ],
        "breadth": {
            "state_class": "pass",
            "breadth_score_label": "67%",
            "detail": "2/2 tickers priced",
            "above_sma20_label": "100%",
            "above_sma50_label": "100%",
            "advancers_5d_label": "100%",
            "coverage_label": "100%",
        },
        "benchmark_rows": [
            {
                "ticker": "SPY",
                "label": "S&P 500",
                "latest_price": "$500.00",
                "return_5d": "+1.0%",
                "return_20d": "+4.0%",
                "return_60d": "+8.0%",
                "tone_class": "pass",
                "observations": 70,
            }
        ],
        "sector_rows": [
            {
                "rank": 1,
                "ticker": "XLK",
                "label": "Technology",
                "stance": "Tailwind",
                "stance_class": "pass",
                "score_label": "+1.30",
                "score_gauge_style": "width: 43%",
                "return_20d": "+5.0%",
                "return_20d_class": "pass",
                "return_20d_gauge_style": "width: 20%",
                "return_60d": "+12.0%",
                "return_60d_class": "pass",
                "return_60d_gauge_style": "width: 48%",
                "excess_5d": "+1.0%",
                "excess_20d": "+2.0%",
                "excess_20d_class": "pass",
                "excess_20d_gauge_style": "width: 13%",
                "excess_60d": "+4.0%",
                "observations": 70,
                "latest_date": "2026-05-08",
                "guidance": "Technology is adding top-down support.",
            }
        ],
        "quality_rows": [
            {"label": "Sector ETF prices", "status": "PASS", "status_class": "pass", "detail": "ok"}
        ],
        "universe": {
            "member_count": 2,
            "priced_count": 2,
            "coverage_label": "100%",
            "state_class": "pass",
        },
        "data_source": {
            "provider_label": "massive",
            "row_count_label": "10 rows",
            "detail": "10 cached daily price rows across 2 tickers",
        },
    }


def _selection_report() -> dict[str, object]:
    return {
        "ticker": "AAPL",
        "final_action": "WATCH",
        "final_conviction": 0.62,
        "as_of": "2026-05-07T09:30:00Z",
        "policy_gates": [{"name": "evidence_breadth", "status": "WARN", "reason": "one source"}],
        "risk_flags": ["news_breadth_low"],
    }


def _selection_report_for_cycle(
    cycle_id: str,
    ticker: str,
    generated_at: str,
) -> dict[str, object]:
    report = build_final_selection(_evidence_pack()).selection_report
    report["cycle_id"] = cycle_id
    report["ticker"] = ticker
    report["generated_at"] = generated_at
    return report


def _selection_report_with_signal_mix() -> dict[str, object]:
    as_of = "2026-05-07T09:30:00Z"
    generated_at = "2026-05-07T09:31:00Z"
    cycle_id = "live-pit-current"
    ticker = "MSFT"
    pack = build_evidence_pack(
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
        generated_at=generated_at,
        signals=[
            build_signal_result(
                cycle_id=cycle_id,
                ticker=ticker,
                as_of=as_of,
                lane="fundamentals",
                score=0.74,
                provenance=_provenance("fundamentals-msft"),
                confidence=0.91,
                summary="Fundamentals support the current review.",
            ),
            build_signal_result(
                cycle_id=cycle_id,
                ticker=ticker,
                as_of=as_of,
                lane="technical_analysis",
                score=0.22,
                provenance=_provenance(
                    "technical-msft",
                    source="massive",
                    source_tier="INFERRED_FROM_BARS",
                    verification_level="INFERRED",
                ),
                confidence=0.62,
                summary="Technical setup is constructive but still corroborating.",
            ),
            build_signal_result(
                cycle_id=cycle_id,
                ticker=ticker,
                as_of=as_of,
                lane="news",
                score=-0.03,
                provenance=_provenance(
                    "news-msft",
                    source="rss-news",
                    source_tier="RSS_HEADLINE",
                    verification_level="INFERRED",
                ),
                confidence=0.4,
                summary="News headline is too weak to affect the decision.",
            ),
        ],
    )
    return build_final_selection(pack).selection_report


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
                provenance=_provenance("fundamentals"),
                confidence=0.9,
            ),
            build_signal_result(
                cycle_id="cycle-1",
                ticker="AAPL",
                as_of="2026-05-07T09:30:00Z",
                lane="insider",
                score=0.7,
                provenance=_provenance("insider"),
                confidence=0.9,
            )
        ],
    )


def _risk_decision() -> dict[str, object]:
    report = build_final_selection(_evidence_pack()).selection_report
    report["final_action"] = "BUY"
    return build_risk_decision(
        report,
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision


def _promotion_lane(lane: str, state: str) -> dict[str, object]:
    return {
        "lane": lane,
        "state": state,
        "configured": True,
        "dataset": f"{lane}_dataset",
        "source": f"{lane}_source",
        "verification_level": "CONFIRMED",
        "runtime_effect": f"{lane} runtime effect",
        "evidence_required": f"{lane} evidence required",
        "rationale": f"{lane} rationale",
    }


def _provenance(
    source_id: str,
    *,
    source: str = "sec-edgar",
    source_tier: str = "OFFICIAL_FILING",
    freshness: str = "FRESH",
    verification_level: str = "CONFIRMED",
) -> dict[str, object]:
    return {
        "source": source,
        "source_tier": source_tier,
        "source_id": source_id,
        "source_url": None,
        "timestamp_observed": "2026-05-07T09:00:00Z",
        "timestamp_as_of": "2026-05-07T08:59:00Z",
        "freshness": freshness,
        "confidence": 1.0,
        "verification_level": verification_level,
    }


def _lifecycle_event() -> dict[str, object]:
    return {
        "event_type": "DETERMINISTIC_ACTION",
        "event_time": "2026-05-07T09:31:00Z",
        "status": "ACTIONABLE",
        "reason": "quality_positive",
    }


def _human_review_event() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "event_id": "d" * 64,
        "cycle_id": "cycle-1",
        "ticker": "AAPL",
        "event_type": "HUMAN_REVIEW",
        "event_time": "2026-05-07T10:00:00Z",
        "status": "WARN",
        "reason": "paper review deferred",
        "payload": {
            "review_decision": "DEFER",
            "reviewed_by": "local-user",
            "paper_only": True,
            "as_of": "2026-05-07T09:30:00Z",
        },
    }
