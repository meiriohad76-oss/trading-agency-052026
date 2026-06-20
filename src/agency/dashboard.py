from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from data_refresh.market_calendar import classify_market_session
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy.exc import SQLAlchemyError

from agency.api.health import runtime_data_source_status
from agency.broker import (
    AlpacaBrokerClient,
    AlpacaBrokerError,
    AlpacaTradingConfig,
    build_market_order_payload,
)
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import (
    make_lifecycle_event_id,
    record_candidate_lifecycle_event,
    record_prompt_audit,
    upsert_selection_report,
)
from agency.runtime.artifact_fallbacks import (
    DEFAULT_RUNTIME_ARTIFACT_ROOT,
    append_runtime_lifecycle_event_artifact,
    runtime_execution_preview_artifacts,
    runtime_risk_decision_artifacts,
    runtime_selection_report_artifacts,
)
from agency.runtime.lane_promotion import load_lane_promotion_status
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.runtime.scheduler_runner import (
    launch_subscription_email_article_analysis_after_login,
    launch_subscription_email_login_refresh,
    run_manual_dataset_refresh,
    run_manual_massive_lane_refresh,
)
from agency.runtime.scheduler_work_queue import execution_freshness_gate
from agency.services import (
    OpenAILlmReviewProvider,
    PortfolioPolicy,
    build_and_persist_human_review_event,
    build_final_selection,
    build_human_review_event,
    build_operator_manual_advance_event,
    build_order_approval_event,
    evaluate_deterministic_rules,
    load_active_portfolio_policy,
    persist_portfolio_snapshot,
    selection_report_hash,
)
from agency.services.risk import load_policy_from_db
from agency.views._shared import (
    FINAL_SELECTION_REPORT_LIMIT,
    _dashboard_risk_decisions,
    _dashboard_selection_reports,
    _env_bool_text,
    _mapping_field,
    _matching_payload,
    _operator_text,
    _optional_float_field,
    _runtime_payload_key,
    _string_list,
    dashboard_data_health,
    live_dashboard_data_load_status,
)

# Route handlers below reference these view-model constructors. Helper symbols
# that are not used directly by routes are still re-exported here so existing
# callers of ``agency.dashboard`` (and tests) keep working after the split.
from agency.views.candidates import (  # noqa: F401
    _candidate_review_redirect_url,
    _review_caution,
    candidate_decision_brief,
    candidate_detail_context,
    candidate_detail_report_rows,
    candidate_detail_summary,
    candidate_email_evidence,
    candidate_email_evidence_with_judgement,
    candidate_news_evidence,
    candidate_review_summary,
    candidate_rows,
    timeline_rows,
)
from agency.views.cockpit import (  # noqa: F401
    cached_cockpit_context,
    cached_cockpit_context_with_timeout,
    clear_cockpit_context_cache,
    cockpit_audit_payload,
    cockpit_context,
    cockpit_cycle_payload,
    cockpit_ticker_detail_payload,
    normalize_ticker,
    safe_cockpit_api_payload,
)
from agency.views.command import (  # noqa: F401
    broker_status_view,
    command_status_overview,
    command_summary,
    dashboard_context,
    data_load_status_view,
    data_refresh_progress_view,
    human_review_events_for_reports,
    live_config_view,
    operational_readiness_context,
    paper_review_progress,
    paper_review_queue,
    paper_review_status_context,
    paper_review_status_from_runtime,
    policy_sections,
    policy_summary,
    provider_readiness_view,
    readiness_view,
    scheduler_work_queue_raw_context,
    scheduler_work_queue_status_context,
    source_status_rows,
)
from agency.views.execution import (  # noqa: F401
    _record_failed_order_submission,
    _record_order_submission_intent,
    _record_submitted_order,
    execution_preview_context,
    execution_preview_focus_context,
    execution_preview_order_row,
    execution_preview_rows,
    row_from_execution_context,
)
from agency.views.final_selection import (  # noqa: F401
    final_selection_context,
    final_selection_focus_context,
    final_selection_rows,
    final_selection_summary,
)
from agency.views.learning import learning_context, learning_summary  # noqa: F401
from agency.views.market_regime import (  # noqa: F401
    broker_status_context,
    market_regime_context,
)
from agency.views.portfolio import (  # noqa: F401
    portfolio_monitor_context,
    portfolio_monitor_summary,
)
from agency.views.risk import (  # noqa: F401
    risk_context,
    risk_decision_rows,
    risk_summary,
)
from agency.views.signals import (  # noqa: F401
    signal_dashboard_rows,
    signal_dashboard_summary,
    signal_lane_rows,
    signals_context,
)

_DEFAULT_EXECUTION_PREVIEW_CONTEXT_ID = id(execution_preview_context)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _operator_template_finalize(value: object) -> object:
    if isinstance(value, Markup):
        return value
    if isinstance(value, str):
        return _operator_text(value)
    return value


templates.env.finalize = _operator_template_finalize
EXECUTION_PREVIEW_ROUTE_CACHE_TTL_SECONDS = 300.0
FINAL_SELECTION_ROUTE_CACHE_TTL_SECONDS = 60.0
COMMAND_DASHBOARD_ROUTE_CACHE_TTL_SECONDS = 15.0
STATUS_ROUTE_CACHE_TTL_SECONDS = 60.0
STATUS_ROUTE_TIMEOUT_CACHE_TTL_SECONDS = 1.0
STATUS_ROUTE_TIMEOUT_SECONDS = 8.0
DASHBOARD_ROUTE_CONTEXT_TIMEOUT_SECONDS = 2.5
DASHBOARD_ROUTE_CONTEXT_CACHE_TTL_SECONDS = 120.0
EXECUTION_STATUS_REASON_LIMIT = 3
_execution_preview_route_cache: dict[str, object] = {
    "expires_at": 0.0,
    "context": None,
    "builder_id": 0,
}
_execution_preview_route_cache_lock = asyncio.Lock()
_execution_preview_status_cache: dict[str, object] = {
    "expires_at": 0.0,
    "payload": None,
    "builder_id": 0,
    "task": None,
    "version": 0,
}
_paper_review_status_cache: dict[str, object] = {
    "expires_at": 0.0,
    "payload": None,
    "builder_id": 0,
    "task": None,
    "version": 0,
}
_scheduler_work_queue_status_cache: dict[str, object] = {
    "expires_at": 0.0,
    "payload": None,
    "builder_id": 0,
    "task": None,
    "version": 0,
}
_dashboard_route_context_cache: dict[str, tuple[float, dict[str, object], int]] = {}
_dashboard_route_context_inflight: dict[str, asyncio.Task[dict[str, object]]] = {}
_final_selection_route_cache: dict[str, object] = {
    "expires_at": 0.0,
    "context": None,
    "builder_id": 0,
}
_command_dashboard_route_cache: dict[str, object] = {
    "expires_at": 0.0,
    "context": None,
    "builder_id": 0,
}
_command_dashboard_route_cache_lock = asyncio.Lock()
_final_selection_route_cache_lock = asyncio.Lock()
_execution_preview_status_cache_lock = asyncio.Lock()
_paper_review_status_cache_lock = asyncio.Lock()
_scheduler_work_queue_status_cache_lock = asyncio.Lock()
BROKER_RECONCILIATION_TERMINAL_STATUSES = {
    "FILLED",
    "CANCELED",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
}
BROKER_RECONCILIATION_MAX_ATTEMPTS = 5
BROKER_RECONCILIATION_POLL_SECONDS = 0.25


async def _bounded_dashboard_context(
    key: str,
    builder: Callable[[], object],
    fallback_builder: Callable[[], dict[str, object]],
    *,
    timeout_seconds: float | None = None,
    ttl_seconds: float = DASHBOARD_ROUTE_CONTEXT_CACHE_TTL_SECONDS,
) -> dict[str, object]:
    """Return a dashboard context without letting a heavy route freeze first paint."""

    timeout = (
        DASHBOARD_ROUTE_CONTEXT_TIMEOUT_SECONDS
        if timeout_seconds is None
        else timeout_seconds
    )
    builder_id = id(builder)
    cached = _dashboard_route_context_cache.get(key)
    if cached is not None:
        cached_at, context, cached_builder_id = cached
        if cached_builder_id == builder_id and time.monotonic() - cached_at <= ttl_seconds:
            return dict(context)
    task = _dashboard_route_context_inflight.get(key)
    if task is None or task.done():
        task = asyncio.create_task(_call_dashboard_context_builder(builder))
        _dashboard_route_context_inflight[key] = task
    try:
        context = await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except TimeoutError:
        task.add_done_callback(
            lambda completed, *, cache_key=key, cache_builder_id=builder_id: (
                _store_bounded_dashboard_context_result(
                    cache_key,
                    completed,
                    cache_builder_id,
                )
            )
        )
        return fallback_builder()
    except Exception as exc:  # noqa: BLE001 - dashboards should render an operator state
        if _dashboard_route_context_inflight.get(key) is task:
            _dashboard_route_context_inflight.pop(key, None)
        return _dashboard_route_failed_context(key, exc, fallback_builder())
    if _dashboard_route_context_inflight.get(key) is task:
        _dashboard_route_context_inflight.pop(key, None)
    _dashboard_route_context_cache[key] = (time.monotonic(), dict(context), builder_id)
    return dict(context)


async def _call_dashboard_context_builder(
    builder: Callable[[], object],
) -> dict[str, object]:
    result = builder()
    if isinstance(result, Awaitable):
        return dict(await result)
    return dict(result)


def _store_bounded_dashboard_context_result(
    key: str,
    task: asyncio.Task[dict[str, object]],
    builder_id: int,
) -> None:
    if _dashboard_route_context_inflight.get(key) is task:
        _dashboard_route_context_inflight.pop(key, None)
    try:
        context = task.result()
    except Exception:
        return
    _dashboard_route_context_cache[key] = (time.monotonic(), dict(context), builder_id)


def _dashboard_route_failed_context(
    key: str,
    exc: Exception,
    context: dict[str, object],
) -> dict[str, object]:
    context["route_context_status"] = {
        "status_label": "Dashboard check failed",
        "status_class": "block",
        "detail": f"{key} could not build its live context: {exc}",
    }
    return context


def _route_delayed_data_health(page_label: str, route_label: str) -> dict[str, object]:
    return dashboard_data_health(
        page_label,
        data_load_status={
            "status_checked_at": datetime.now(UTC).isoformat(),
            "overall_percent": 0,
            "health_monitor": {
                "status_label": "Dashboard check still running",
                "status_class": "warn",
                "live": False,
                "origin": "bounded dashboard route",
                "latest_checked_at": datetime.now(UTC).isoformat(),
                "detail": (
                    f"{route_label} did not finish its source-proof check inside the "
                    "first-screen budget."
                ),
            },
        },
        extra_rows=(
            {
                "kind": "Dashboard route",
                "name": route_label,
                "status_label": "Still checking",
                "status_class": "warn",
                "coverage_label": "live context not displayed yet",
                "freshness_label": "source proof pending",
                "last_update": datetime.now(UTC).isoformat(),
                "detail": (
                    "The dashboard shell is usable, but detailed rows are hidden until "
                    "the live context finishes loading."
                ),
            },
        ),
    )


def _command_delayed_context() -> dict[str, object]:
    data_health = _route_delayed_data_health("Command center", "Command operating picture")
    fallback_review_queue = _runtime_artifact_review_queue()
    fallback_review_progress = paper_review_progress(fallback_review_queue)
    issue_summary = {
        "status_class": "warn",
        "tooltip": "Command is still checking live runtime proof.",
        "blocker_count": 0,
        "warning_count": 1,
    }
    readiness_coverage = {
        "market_flow_status_label": "checking",
        "expected_ticker_count": 0,
        "critical_agent_ready_label": "checking agents",
        "overall_percent": 0,
        "core_dataset_percent": 0,
        "critical_lane_percent": 0,
    }
    command_map = {
        "freshness": {"tooltip": "Core data proof is being checked."},
        "agents": {"tooltip": "Agent readiness is being checked."},
        "loading": {"tooltip": "Refresh progress is being checked."},
    }
    full_live_readiness = {
        "status_class": "warn",
        "status_label": "Checking",
        "mode_label": "Checking",
        "mode_summary": "Checking live operating state",
        "mode_tooltip": "Command is building live source proof.",
        "coverage": readiness_coverage,
        "tradable_ready": False,
        "trading_gate_label": "Checking",
        "readiness_scope_label": "current runtime",
        "progress_style": "width: 0%",
        "active_refresh": {"status_label": "Checking", "eta_label": "calculating"},
        "blocking_reason_label": "Core source proof is not displayed yet.",
        "command_map": command_map,
    }
    return {
        "route_context_status": {
            "status": "delayed",
            "status_label": "Command check still running",
            "status_class": "warn",
            "detail": (
                "Command missed the first-screen budget, so detailed "
                "runtime rows are hidden until live source proof finishes loading."
            ),
            "action": "Reload Command after the proof timestamp updates, or open Cockpit for the current first-screen workflow.",
        },
        "summary": {
            "source_count": 0,
            "candidate_count": 0,
            "hero_class": "operator-state-attention",
            "headline": "Command is checking live source proof",
            "detail": (
                "Navigation is available now. Detailed queues and lane rows are hidden "
                "until the current runtime context finishes loading."
            ),
        },
        "command_freshness_label": "source proof checking",
        "operator_checklist": {
            "item_rows": [
                {
                    "state": "attention",
                    "href": "#data-load-heading",
                    "label": "Data proof",
                    "value": "Checking",
                    "detail": "Wait for the current runtime check to finish.",
                }
            ]
        },
        "email_alert_active": False,
        "email_progress_active": False,
        "data_health": data_health,
        "data_load_status": {
            "status_class": "warn",
            "status_label": "Checking",
            "source_health_kpi": {
                "label": "Checking",
                "detail": "Source proof pending",
                "short_detail": "pending",
                "tooltip": "Source health is being checked.",
            },
            "market_flow_summary": {
                "status_class": "warn",
                "status_label": "Checking",
                "usable_ticker_count": 0,
                "expected_ticker_count": 0,
            },
            "subscription_email_status": {},
        },
        "full_live_readiness": full_live_readiness,
        "status_overview": {
            "issue_summary": issue_summary,
            "trade_pull": {
                "tooltip": "Live trade slice coverage is being checked.",
                "status_label": "Checking",
                "status_class": "warn",
                "percent_complete": 0,
                "progress_style": "width: 0%",
                "ticker_progress_label": "source proof pending",
                "eta_label": "calculating",
                "freshness_label": "not displayed yet",
                "row_count_label": "not displayed",
                "detail": "Live trade slice rows are hidden until current source proof finishes.",
                "updated_at": datetime.now(UTC).isoformat(),
            },
            "rows": [],
            "process_rows": [
                {
                    "id": "process-command-context",
                    "process": "Command context",
                    "status_label": "Checking",
                    "status_class": "warn",
                    "progress_label": "live proof running",
                    "eta_label": "calculating",
                    "freshness_label": "not displayed yet",
                    "last_update": datetime.now(UTC).isoformat(),
                    "action": "Wait for the dashboard to finish, then reload if the proof timestamp does not update.",
                    "detail": "The route missed the first-screen budget and is warming in the background.",
                    "tooltip": "No detailed command rows are displayed until the live context finishes.",
                }
            ],
        },
        "review_progress": fallback_review_progress
        if fallback_review_queue
        else {
            "pending_count": 0,
            "reviewed_label": "0",
            "approve_count": 0,
            "defer_count": 0,
            "reject_count": 0,
            "status_class": "warn",
            "status_label": "Checking",
            "detail": "Review queue is not displayed until source proof finishes loading.",
        },
        "review_queue": fallback_review_queue,
        "readiness": {"cycle_id": "checking"},
        "scheduler": {
            "status_class": "warn",
            "status_label": "Checking",
            "refresh_workload": {
                "running_count": 0,
                "live_critical_due_count": 0,
            },
        },
        "provider_readiness": {
            "status_class": "warn",
            "status_label": "Checking",
            "active_ready_label": "checking providers",
            "configured_label": "configuration proof pending",
            "connections_tooltip": "Provider readiness is being checked.",
        },
        "data_refresh": {"trade_pull": {"state": "checking"}},
        "overview_trade_pull": {
            "tooltip": "Live trade slice coverage is being checked.",
            "status_label": "Checking",
            "status_class": "warn",
            "percent_complete": 0,
            "progress_style": "width: 0%",
            "ticker_progress_label": "source proof pending",
            "eta_label": "calculating",
            "freshness_label": "not displayed yet",
            "row_count_label": "not displayed",
            "detail": "Live trade slice rows are hidden until current source proof finishes.",
            "updated_at": datetime.now(UTC).isoformat(),
        },
    }


def _runtime_artifact_review_queue() -> list[dict[str, object]]:
    reports = runtime_selection_report_artifacts(limit=FINAL_SELECTION_REPORT_LIMIT)
    if not reports:
        return []
    cycle_id = str(reports[0].get("cycle_id") or "").strip()
    if not cycle_id:
        return []
    cycle_reports = [
        report for report in reports if str(report.get("cycle_id") or "") == cycle_id
    ]
    risk_decisions = runtime_risk_decision_artifacts(limit=FINAL_SELECTION_REPORT_LIMIT)
    readiness = {
        "cycle_id": cycle_id,
        "ready": False,
        "verdict": "checking_live_source_proof",
    }
    return paper_review_queue(
        cycle_reports,
        risk_decisions,
        readiness,
        review_events=[],
    )


def _final_selection_delayed_context(focus_ticker: str | None = None) -> dict[str, object]:
    normalized = str(focus_ticker or "").strip().upper()
    return {
        "data_health": _route_delayed_data_health("Final selection dashboard", "Candidate review queue"),
        "final_rows": [],
        "actionable_rows": [],
        "watch_rows": [],
        "no_trade_rows": [],
        "blocked_rows": [],
        "trace_rows": [],
        "focused_ticker": normalized,
        "focused_final_selection": final_selection_focus_context([], normalized),
        "summary": {
            "report_count": 0,
            "all_report_count": 0,
            "selected_count": 0,
            "actionable_count": 0,
            "blocked_count": 0,
            "no_trade_count": 0,
            "historical_count": 0,
            "cycle_id": "checking",
            "cycle_label": "checking",
            "topbar_label": "checking candidates",
            "headline": "Candidate review is checking source proof",
            "detail": "The queue is hidden until the current final-selection context finishes loading.",
            "scope_detail": "Current cycle proof is pending.",
        },
    }


def _execution_preview_delayed_context(focus_ticker: str | None = None) -> dict[str, object]:
    normalized = str(focus_ticker or "").strip().upper()
    return {
        "broker": {"connected": False, "status_class": "warn", "detail": "Broker proof is being checked."},
        "data_health": _route_delayed_data_health("Execution preview dashboard", "Paper clearance queue"),
        "preview_rows": [],
        "focused_execution": execution_preview_focus_context([], normalized),
        "orderable_rows": [],
        "review_only_rows": [],
        "approved_review_only_rows": [],
        "blocked_rows": [],
        "leveraged_alternatives": {
            "rows": [],
            "review_count": 0,
            "triggered_count": 0,
            "available_count": 0,
            "status_label": "Checking",
            "status_class": "warn",
            "headline": "Leveraged-advisory context is checking source proof.",
            "detail": "No advisory alternatives are displayed until the execution context finishes.",
        },
        "summary": {
            "preview_count": 0,
            "ready_count": 0,
            "blocked_count": 0,
            "disabled_count": 0,
            "submit_ready_count": 0,
            "broker_connected": False,
            "broker_mode": "paper",
            "submit_gate_open": False,
            "submit_gate_label": "Checking",
            "submit_gate_class": "warn",
            "portfolio_check_label": "Checking",
            "portfolio_check_class": "warn",
            "portfolio_check_detail": "Broker and source proof are being checked.",
            "portfolio_equity_label": "Checking",
            "portfolio_buying_power_label": "Checking",
            "portfolio_position_count": 0,
            "portfolio_gross_exposure_label": "Checking",
            "policy_default_position_label": "Checking",
            "policy_max_exposure_label": "Checking",
            "policy_exit_rules_label": "Checking",
            "headline": "Execution preview is checking source proof",
            "detail": "Paper-order rows are hidden until current broker and data proof finish loading.",
            "workflow_guidance": "Wait for the proof timestamp to update before approving or submitting paper orders.",
            "no_order_explanation": "No order rows are displayed while the execution context is still checking.",
        },
        "execution_freshness_gate": {"ready": False, "detail": "Execution proof is checking."},
        "freshness_gate": {"ready": False},
        "scheduler_tradability": {},
    }


def _risk_delayed_context() -> dict[str, object]:
    return {
        "data_health": _route_delayed_data_health("Risk dashboard", "Risk gate"),
        "risk_rows": [],
        "allow_rows": [],
        "warn_rows": [],
        "block_rows": [],
        "data_sources": [],
        "summary": {
            "decision_count": 0,
            "allow_count": 0,
            "warn_count": 0,
            "block_count": 0,
            "degraded_source_count": 0,
            "headline": "Risk gate is checking source proof",
            "detail": "Risk rows are hidden until the current policy and source-health context finishes loading.",
            "warn_meaning": "WARN rows require human review after source proof is visible.",
            "blocked_meaning": "Policy-stopped rows are shown only after the current risk context is loaded.",
            "next_action": "Wait for the risk check to finish, then reload if proof does not update.",
        },
    }


def _signals_delayed_context() -> dict[str, object]:
    return {
        "active_nav": "signals",
        "evidence_currentness": {
            "is_current": False,
            "display_mode": "work_in_progress",
            "status_label": "Signal evidence is being checked",
            "reason": "Signal rows are hidden until the latest source proof finishes loading.",
        },
        "data_health": _route_delayed_data_health("Signals dashboard", "Signal evidence"),
        "lane_rows": [],
        "signal_rows": [],
        "summary": {
            "topbar_label": "checking signals",
            "headline": "Signal evidence is checking source proof",
            "detail": "No signal rows are displayed until the current evidence context finishes loading.",
            "signal_count": 0,
            "actionable_count": 0,
            "context_count": 0,
            "suppressed_count": 0,
            "configured_lanes": 0,
            "lanes_with_data": 0,
            "cycle_label": "checking",
            "render_label": "Detailed signal rows are hidden while source proof is pending",
            "bullish_count": 0,
            "bearish_count": 0,
            "is_limited": False,
            "actionable_description": "Signals are not displayed until source proof is current.",
            "context_description": "Context rows are hidden while the dashboard is checking.",
            "suppressed_description": "Suppressed rows are hidden while the dashboard is checking.",
        },
    }


def _portfolio_delayed_context() -> dict[str, object]:
    return {
        "broker": {"connected": False, "detail": "Broker proof is being checked.", "status_class": "warn"},
        "data_health": _route_delayed_data_health("Portfolio monitor dashboard", "Portfolio monitor"),
        "positions": [],
        "snapshot_rows": [],
        "summary": {
            "position_count": 0,
            "headline": "Portfolio monitor is checking broker proof",
            "detail": "Positions and account values are hidden until the live broker context finishes loading.",
            "hourly_return_pct": None,
            "hourly_status_label": "Checking",
            "hourly_status_class": "warn",
            "equity": None,
            "gross_exposure_pct": None,
            "close_candidate_count": 0,
            "policy_compliance_class": "warn",
            "policy_compliance_label": "Checking",
            "max_gross_exposure_pct": 0.0,
            "available_exposure_pct": None,
            "take_profit_pct": 0.0,
            "stop_loss_pct": 0.0,
            "trailing_stop_pct": 0.0,
            "hourly_loss_alert_pct": 0.0,
            "hourly_reason": "Broker and portfolio policy proof are being checked.",
            "cash": 0.0,
            "buying_power": 0.0,
        },
    }


def _market_regime_delayed_context() -> dict[str, object]:
    return {
        "snapshot_type": "checking",
        "bluf": {
            "headline": "Market briefing is checking source proof",
            "operator_message": "Market, sector, breadth, and macro rows are hidden until the current context finishes loading.",
        },
        "summary": {
            "topbar_label": "checking market",
            "status_class": "warn",
            "decision_guidance": "Wait for current market proof before using this page for candidate context.",
            "as_of_label": "checking",
        },
        "kpis": [],
        "data_health": _route_delayed_data_health("Market regime dashboard", "Universe and market briefing"),
        "portfolio_context": {
            "headwind_positions": [],
            "topping_positions": [],
            "tailwind_positions": [],
        },
        "sector_rows": [],
        "breadth": {"state_class": "warn", "breadth_score_label": "checking"},
        "benchmark_rows": [],
        "market_backdrop": {"macro_tilt": "CHECKING"},
        "macro": {"tiles": []},
        "intraday_drift": None,
        "data_sources": [],
        "tooltips": {},
        "change": None,
    }


def _learning_delayed_context() -> dict[str, object]:
    return {
        "outcome": {"requirements": []},
        "near_miss": {"rows": [], "near_miss_count": 0},
        "summary": {
            "status": "Checking",
            "sample_count": 0,
            "required_sample_count": 0,
            "near_miss_count": 0,
            "headline": "Learning loop is checking source proof",
            "detail": "Near-miss and outcome rows are hidden until the current learning context finishes loading.",
        },
        "data_health": _route_delayed_data_health("Learning dashboard", "Learning loop"),
    }


@router.get("/")
async def dashboard() -> Response:
    return RedirectResponse("/cockpit", status_code=303)


@router.get("/command")
async def command_dashboard(request: Request) -> Response:
    return await _command_dashboard_response(request)


async def _command_dashboard_response(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        await _command_dashboard_route_context(),
    )


async def _command_dashboard_route_context() -> dict[str, object]:
    context = await _bounded_dashboard_context(
        "command",
        _command_dashboard_route_context_uncached,
        _command_delayed_context,
        timeout_seconds=DASHBOARD_ROUTE_CONTEXT_TIMEOUT_SECONDS,
        ttl_seconds=COMMAND_DASHBOARD_ROUTE_CACHE_TTL_SECONDS,
    )
    return _normalized_command_dashboard_context(context)


def _normalized_command_dashboard_context(context: Mapping[str, object]) -> dict[str, object]:
    output = dict(context)
    fallback = _command_delayed_context()
    fallback_trade_pull = dict(fallback["overview_trade_pull"])  # type: ignore[index]
    data_refresh = output.get("data_refresh")
    if not isinstance(data_refresh, dict):
        data_refresh = {}
    if not isinstance(data_refresh.get("trade_pull"), dict):
        data_refresh["trade_pull"] = dict(fallback["data_refresh"]["trade_pull"])  # type: ignore[index]
    output["data_refresh"] = data_refresh
    if not isinstance(output.get("overview_trade_pull"), dict):
        output["overview_trade_pull"] = fallback_trade_pull
    status_overview = output.get("status_overview")
    if not isinstance(status_overview, dict):
        status_overview = {}
    if not isinstance(status_overview.get("trade_pull"), dict):
        status_overview["trade_pull"] = dict(output["overview_trade_pull"])  # type: ignore[index]
    output["status_overview"] = status_overview
    return output


async def _command_dashboard_route_context_uncached() -> dict[str, object]:
    cached = _command_dashboard_route_cache.get("context")
    expires_at = _command_dashboard_route_cache.get("expires_at", 0.0)
    builder_id = id(dashboard_context)
    if (
        isinstance(cached, dict)
        and isinstance(expires_at, float)
        and expires_at > time.monotonic()
        and _command_dashboard_route_cache.get("builder_id") == builder_id
    ):
        return dict(cached)
    async with _command_dashboard_route_cache_lock:
        cached = _command_dashboard_route_cache.get("context")
        expires_at = _command_dashboard_route_cache.get("expires_at", 0.0)
        if (
            isinstance(cached, dict)
            and isinstance(expires_at, float)
            and expires_at > time.monotonic()
            and _command_dashboard_route_cache.get("builder_id") == builder_id
        ):
            return dict(cached)
        context = await dashboard_context()
        _store_command_dashboard_route_cache(context)
        return dict(context)


def _store_command_dashboard_route_cache(context: Mapping[str, object]) -> None:
    _command_dashboard_route_cache["context"] = dict(context)
    _command_dashboard_route_cache["expires_at"] = (
        time.monotonic() + COMMAND_DASHBOARD_ROUTE_CACHE_TTL_SECONDS
    )
    _command_dashboard_route_cache["builder_id"] = id(dashboard_context)


def _clear_command_dashboard_route_cache() -> None:
    _command_dashboard_route_cache["context"] = None
    _command_dashboard_route_cache["expires_at"] = 0.0
    _command_dashboard_route_cache["builder_id"] = 0


def _clear_operator_route_caches() -> None:
    _clear_command_dashboard_route_cache()
    _clear_execution_preview_route_cache()
    _clear_final_selection_route_cache()
    _clear_execution_preview_status_cache()
    _clear_paper_review_status_cache()
    _clear_scheduler_work_queue_status_cache()
    clear_cockpit_context_cache()


@router.get("/cockpit")
async def cockpit(request: Request) -> Response:
    return await _cockpit_response(request)


async def _cockpit_response(request: Request) -> Response:
    qa_enabled = _env_bool_text("AGENCY_COCKPIT_QA_SCENARIOS")
    qa_scenario = request.query_params.get("scenario") if qa_enabled else None
    qa_cache_flag = qa_enabled if qa_enabled else None
    return templates.TemplateResponse(
        request,
        "cockpit.html",
        await cached_cockpit_context_with_timeout(
            qa_scenario=qa_scenario,
            qa_scenarios_enabled=qa_cache_flag,
        ),
    )


@router.get("/api/cockpit")
async def cockpit_api(request: Request) -> dict[str, object]:
    qa_enabled = _env_bool_text("AGENCY_COCKPIT_QA_SCENARIOS")
    qa_scenario = request.query_params.get("scenario") if qa_enabled else None
    qa_cache_flag = qa_enabled if qa_enabled else None
    return safe_cockpit_api_payload(
        await cached_cockpit_context_with_timeout(
            qa_scenario=qa_scenario,
            qa_scenarios_enabled=qa_cache_flag,
        )
    )


@router.get("/api/cycle")
async def cockpit_cycle_api() -> dict[str, object]:
    return cockpit_cycle_payload(await cached_cockpit_context_with_timeout())


@router.get("/api/audit/{ticker}")
async def cockpit_audit_api(ticker: str) -> dict[str, object]:
    try:
        return cockpit_audit_payload(await cached_cockpit_context_with_timeout(), ticker)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/cockpit/ticker/{ticker}")
async def cockpit_ticker_detail_api(ticker: str) -> dict[str, object]:
    try:
        return await cockpit_ticker_detail_payload(normalize_ticker(ticker))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/cockpit/submit")
async def cockpit_submit(request: Request) -> JSONResponse:
    """Submit the cockpit paper manifest through the execution-preview safety path."""

    if _env_bool_text("LIVE_TRADING"):
        raise HTTPException(
            status_code=403,
            detail="Cockpit clearance is paper-only; live trading is locked off.",
        )
    body = await request.body()
    payload = _cockpit_submit_payload_from_body(request, body)
    if _cockpit_submit_ack(payload) is not True:
        raise HTTPException(status_code=400, detail="Confirm the paper-only submit checkbox first.")
    if _cockpit_submit_phrase(payload).strip() != "submit paper orders":
        raise HTTPException(status_code=400, detail="Type the exact phrase: submit paper orders.")
    orders = _cockpit_submit_orders_from_json(payload) if _cockpit_payload_is_json(request) else _cockpit_submit_orders_from_form(payload)
    if not orders:
        raise HTTPException(status_code=400, detail="No paper order rows were included in the cockpit manifest.")

    broker, data_sources = await asyncio.gather(
        _fresh_broker_status_context(),
        runtime_data_source_status(),
    )
    _require_immediate_execution_freshness(broker, data_sources)
    context = await execution_preview_context(
        broker=broker,
        data_sources=data_sources,
        validate_contracts=True,
    )
    gate = _mapping_field(context, "execution_freshness_gate")
    if gate.get("ready") is not True:
        raise HTTPException(
            status_code=409,
            detail=str(gate.get("detail") or "Execution data is not fresh enough."),
        )

    accepted: list[dict[str, object]] = []
    rejected: list[dict[str, object]] = []
    reconcile_pending: list[dict[str, object]] = []
    for order in orders:
        row = row_from_execution_context(
            context,
            cycle_id=str(order["cycle_id"]),
            ticker=str(order["ticker"]),
            as_of=str(order["as_of"]),
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"execution preview not found for {order['ticker']}")
        if str(row.get("order_intent_hash") or "") != str(order["order_intent_hash"]):
            raise HTTPException(status_code=409, detail="order details changed; refresh cockpit and approve again")
        _reject_tampered_cockpit_order_hints(row, order)
        try:
            accepted_row = await _submit_execution_order_core(
                request=request,
                cycle_id=str(row["cycle_id"]),
                ticker=str(row["ticker"]),
                as_of=str(row["as_of"]),
                order_intent_hash=str(row["order_intent_hash"]),
                broker=broker,
                data_sources=data_sources,
                context=context,
            )
        except HTTPException as exc:
            if exc.status_code == 202:
                accepted_row = {
                    "ticker": str(row.get("ticker") or order["ticker"]),
                    "broker_order_id": str(
                        row.get("broker_order_id")
                        or row.get("order_id")
                        or row.get("submitted_order_id")
                        or ""
                    ),
                    "order_intent_hash": str(row.get("order_intent_hash") or ""),
                    "detail": str(exc.detail),
                    "status_code": exc.status_code,
                }
                accepted.append(accepted_row)
                reconcile_pending.append(accepted_row)
                continue
            rejected.append(
                {
                    "ticker": str(row.get("ticker") or order["ticker"]),
                    "detail": str(exc.detail),
                    "status_code": exc.status_code,
                }
            )
        else:
            accepted.append(accepted_row)
    if reconcile_pending and not rejected:
        _clear_operator_route_caches()
        return JSONResponse(
            {
                "state": "reconcile_pending",
                "detail": "Paper submit was accepted and needs broker reconciliation.",
                "accepted": accepted,
                "rejected": rejected,
            },
            status_code=202,
        )
    if accepted and rejected:
        _clear_operator_route_caches()
        return JSONResponse(
            {
                "state": "partial",
                "detail": "Some paper orders were accepted and some require review.",
                "accepted": accepted,
                "rejected": rejected,
            },
            status_code=207,
        )
    if rejected:
        return JSONResponse(
            {
                "state": "rejected",
                "detail": "No paper orders were submitted. Review the rejected rows below.",
                "accepted": accepted,
                "rejected": rejected,
            },
            status_code=409,
        )
    _clear_operator_route_caches()
    return JSONResponse(
        {
            "state": "accepted",
            "detail": "Paper manifest accepted by the execution-preview submit path.",
            "accepted": accepted,
            "rejected": rejected,
        }
    )


def _cockpit_submit_payload_from_body(
    request: Request,
    body: bytes,
) -> Mapping[str, object]:
    if _cockpit_payload_is_json(request):
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid cockpit submit JSON payload.") from exc
        if not isinstance(payload, Mapping):
            raise HTTPException(status_code=400, detail="Cockpit submit JSON payload must be an object.")
        return payload
    return parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)


def _cockpit_payload_is_json(request: Request) -> bool:
    return "application/json" in request.headers.get("content-type", "").lower()


def _cockpit_submit_ack(payload: Mapping[str, object]) -> bool:
    if "orders" in payload:
        value = payload.get("submit_ack", payload.get("submit_gate_armed", False))
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return _cockpit_form_first(payload, "submit_ack") == "on"


def _cockpit_submit_phrase(payload: Mapping[str, object]) -> str:
    if "orders" in payload:
        return str(payload.get("submit_phrase") or payload.get("operator_phrase") or "")
    return _cockpit_form_first(payload, "submit_phrase")


def _cockpit_submit_orders_from_json(payload: Mapping[str, object]) -> list[dict[str, object]]:
    raw_orders = payload.get("orders", [])
    if not isinstance(raw_orders, Sequence) or isinstance(raw_orders, str | bytes):
        raise HTTPException(status_code=400, detail="Cockpit submit orders must be a list.")
    orders: list[dict[str, object]] = []
    for raw_order in raw_orders:
        if not isinstance(raw_order, Mapping):
            raise HTTPException(status_code=400, detail="Each cockpit submit order must be an object.")
        ticker = str(raw_order.get("ticker") or "").strip().upper()
        orders.append(
            {
                "cycle_id": str(raw_order.get("cycle_id") or ""),
                "ticker": ticker,
                "as_of": str(raw_order.get("as_of") or ""),
                "order_intent_hash": str(raw_order.get("order_intent_hash") or ""),
                "notional_hint": str(raw_order.get("notional_hint") or ""),
                "side_hint": str(raw_order.get("side_hint") or ""),
            }
        )
    return [
        order
        for order in orders
        if order["cycle_id"] and order["ticker"] and order["as_of"]
    ]


def _cockpit_submit_orders_from_form(form: object) -> list[dict[str, object]]:
    cycles = _cockpit_form_values(form, "cycle_id")
    tickers = _cockpit_form_values(form, "ticker")
    as_of_values = _cockpit_form_values(form, "as_of")
    hashes = _cockpit_form_values(form, "order_intent_hash")
    notional_hints = _cockpit_form_values(form, "notional_hint")
    side_hints = _cockpit_form_values(form, "side_hint")
    orders: list[dict[str, object]] = []
    for index, ticker in enumerate(tickers):
        orders.append(
            {
                "cycle_id": _indexed(cycles, index),
                "ticker": ticker.upper(),
                "as_of": _indexed(as_of_values, index),
                "order_intent_hash": _indexed(hashes, index),
                "notional_hint": _indexed(notional_hints, index),
                "side_hint": _indexed(side_hints, index),
            }
        )
    return [
        order
        for order in orders
        if order["cycle_id"] and order["ticker"] and order["as_of"]
    ]


def _cockpit_form_first(form: object, key: str) -> str:
    values = _cockpit_form_values(form, key)
    return values[0] if values else ""


def _cockpit_form_values(form: object, key: str) -> list[str]:
    getlist = getattr(form, "getlist", None)
    if callable(getlist):
        return [str(value) for value in getlist(key)]
    value = getattr(form, "get", lambda _key: None)(key)
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return [str(value)] if value is not None else []


def _indexed(values: Sequence[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def _reject_tampered_cockpit_order_hints(
    row: Mapping[str, object],
    order: Mapping[str, object],
) -> None:
    side_hint = str(order.get("side_hint") or "").upper()
    if side_hint and side_hint != str(row.get("side") or "").upper():
        raise HTTPException(
            status_code=409,
            detail="Order side changed since the page loaded; refresh cockpit before submitting.",
        )
    notional_hint = _optional_float_text(order.get("notional_hint"))
    row_notional = _optional_float_field(row, "notional")
    if notional_hint is not None and row_notional is not None and abs(notional_hint - row_notional) > 0.01:
        raise HTTPException(
            status_code=409,
            detail="Order value changed since the page loaded; refresh cockpit before submitting.",
        )


def _optional_float_text(value: object) -> float | None:
    text = str(value or "").replace("$", "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


@router.get("/status/paper-review")
async def paper_review_status() -> dict[str, object]:
    return await _paper_review_status_payload()


@router.get("/status/execution-preview")
async def execution_preview_status() -> dict[str, object]:
    return await _execution_preview_status_payload_cached()


@router.get("/status/operational-readiness")
async def operational_readiness_status() -> dict[str, object]:
    return await operational_readiness_context()


@router.get("/status/lane-promotion")
async def lane_promotion_status() -> dict[str, object]:
    live_config = load_live_config_readiness()
    runtime_signals = live_config.get("runtime_signals", [])
    signals = [str(item) for item in runtime_signals] if isinstance(runtime_signals, list) else []
    return load_lane_promotion_status(signals)


@router.get("/status/scheduler-work-queue")
async def scheduler_work_queue_status() -> dict[str, object]:
    return await _scheduler_work_queue_status_payload()


@router.post("/scheduler/massive-lanes/{lane_id}/refresh")
async def refresh_massive_lane(
    lane_id: str,
    background_tasks: BackgroundTasks,
) -> Response:
    queue = await scheduler_work_queue_raw_context()
    background_tasks.add_task(
        run_manual_massive_lane_refresh,
        lane_id,
        queue_provider=lambda: queue,
    )
    return RedirectResponse(url="/#scheduler-heading", status_code=303)


@router.post("/scheduler/datasets/{dataset}/refresh")
async def refresh_scheduler_dataset(
    dataset: str,
    background_tasks: BackgroundTasks,
) -> Response:
    queue = await scheduler_work_queue_raw_context()
    background_tasks.add_task(
        run_manual_dataset_refresh,
        dataset,
        queue_provider=lambda: queue,
    )
    return RedirectResponse(url="/#scheduler-heading", status_code=303)


@router.post("/scheduler/subscription-emails/login-refresh")
async def refresh_subscription_email_with_login(
    background_tasks: BackgroundTasks,
    return_to: str | None = None,
) -> Response:
    background_tasks.add_task(launch_subscription_email_login_refresh)
    return RedirectResponse(
        url=_scheduler_return_url(return_to, default="/#scheduler-heading", anchor="email-agent"),
        status_code=303,
    )


@router.post("/scheduler/subscription-emails/continue-after-login")
async def continue_subscription_email_after_login(
    background_tasks: BackgroundTasks,
    return_to: str | None = None,
) -> Response:
    background_tasks.add_task(launch_subscription_email_article_analysis_after_login)
    return RedirectResponse(
        url=_scheduler_return_url(return_to, default="/#scheduler-heading", anchor="email-agent"),
        status_code=303,
    )


def _scheduler_return_url(
    return_to: str | None,
    *,
    default: str,
    anchor: str,
) -> str:
    if str(return_to or "").strip().lower() == "cockpit":
        return f"/cockpit#{anchor}"
    return default


@router.get("/candidates/{ticker}")
async def candidate_detail(request: Request, ticker: str) -> Response:
    audit_mode = str(request.query_params.get("audit") or "").strip().lower()
    return_source = str(request.query_params.get("from") or "").strip().lower()
    return templates.TemplateResponse(
        request,
        "candidate_detail.html",
        await candidate_detail_context(
            ticker,
            include_rich_signal_evidence=audit_mode != "light",
            return_source=return_source,
        ),
    )


@router.post("/candidates/{ticker}/reviews")
async def record_candidate_review(
    request: Request,
    ticker: str,
    cycle_id: str,
    as_of: str,
    decision: str,
    review_reason: str | None = None,
    notes: str | None = None,
    caution_acknowledged: bool = False,
    return_to: str | None = None,
) -> Response:
    report_hash = await _selection_report_hash_for_review(
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
    )
    if report_hash is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "current selection report not found; refresh the candidate page "
                "before recording approval for these report details"
            ),
        )
    caution_acknowledged = caution_acknowledged or await _request_form_bool(
        request,
        "caution_acknowledged",
    )
    if (
        decision.upper() == "APPROVE"
        and not caution_acknowledged
        and await _caution_acknowledgement_required_for_review(
            cycle_id=cycle_id,
            ticker=ticker,
            as_of=as_of,
        )
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "caution acknowledgement is required before approving this "
                "research/watch-list candidate"
            ),
        )
    try:
        async with get_session() as session:
            if caution_acknowledged:
                await build_and_persist_human_review_event(
                    session,
                    cycle_id=cycle_id,
                    ticker=ticker,
                    as_of=as_of,
                    decision=decision,
                    review_reason=review_reason,
                    notes=notes,
                    selection_report_hash=report_hash,
                    caution_acknowledged=True,
                )
            else:
                await build_and_persist_human_review_event(
                    session,
                    cycle_id=cycle_id,
                    ticker=ticker,
                    as_of=as_of,
                    decision=decision,
                    review_reason=review_reason,
                    notes=notes,
                    selection_report_hash=report_hash,
                )
            await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        try:
            if caution_acknowledged:
                event = build_human_review_event(
                    cycle_id=cycle_id,
                    ticker=ticker,
                    as_of=as_of,
                    decision=decision,
                    review_reason=review_reason,
                    notes=notes,
                    selection_report_hash=report_hash,
                    caution_acknowledged=True,
                )
            else:
                event = build_human_review_event(
                    cycle_id=cycle_id,
                    ticker=ticker,
                    as_of=as_of,
                    decision=decision,
                    review_reason=review_reason,
                    notes=notes,
                    selection_report_hash=report_hash,
                )
            append_runtime_lifecycle_event_artifact(event)
        except ValueError as review_error:
            raise HTTPException(status_code=400, detail=str(review_error)) from review_error
        except OSError as write_error:
            raise HTTPException(
                status_code=503,
                detail="review persistence unavailable",
            ) from write_error
    _clear_operator_route_caches()
    return RedirectResponse(
        url=_candidate_review_redirect_url(
            ticker=ticker,
            decision=decision,
            return_to=return_to,
        ),
        status_code=303,
    )


@router.post("/candidates/{ticker}/llm-review")
async def run_candidate_llm_review(request: Request, ticker: str) -> Response:
    normalized_ticker = ticker.upper()
    cycle_id = await _request_value(request, "cycle_id")
    as_of = await _request_value(request, "as_of")
    if not cycle_id or not as_of:
        raise HTTPException(
            status_code=400,
            detail="cycle_id and as_of are required to run a hashable candidate LLM review",
        )
    report = await _selection_report_for_manual_llm_review(
        ticker=normalized_ticker,
        cycle_id=cycle_id,
        as_of=as_of,
    )
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="selection report not found; refresh the candidate page before rerunning LLM review",
        )
    evidence_pack = _mapping_field(report, "evidence_pack")
    deterministic = evaluate_deterministic_rules(evidence_pack).decision
    provider = OpenAILlmReviewProvider.from_env(enabled=True)
    llm_event: dict[str, object] | None = None
    try:
        result = await provider.review(evidence_pack, deterministic)
        event_time = datetime.now(UTC).isoformat()
        llm_event = _manual_llm_lifecycle_event(
            result.lifecycle_event,
            event_time=event_time,
        )
        updated_report = build_final_selection(
            evidence_pack,
            generated_at=str(report["generated_at"]),
            llm_review=result.review,
            llm_lifecycle_event=llm_event,
        ).selection_report
        prompt_audit = (
            _manual_prompt_audit(result.prompt_audit, event_time=event_time)
            if result.prompt_audit is not None
            else None
        )
        async with get_session() as session:
            await upsert_selection_report(session, updated_report)
            await record_candidate_lifecycle_event(session, llm_event)
            if prompt_audit is not None:
                await record_prompt_audit(session, prompt_audit)
            await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        if llm_event is not None:
            with suppress(OSError):
                append_runtime_lifecycle_event_artifact(llm_event)
        raise HTTPException(
            status_code=503,
            detail="LLM review completed but report persistence is unavailable",
        ) from exc
    return RedirectResponse(
        url=f"/candidates/{normalized_ticker}?llm_review=completed",
        status_code=303,
    )


@router.get("/final-selection")
async def final_selection(request: Request) -> Response:
    focus_ticker = str(request.query_params.get("ticker") or "").strip().upper()
    return templates.TemplateResponse(
        request,
        "final_selection.html",
        await _final_selection_route_context(focus_ticker=focus_ticker or None),
    )


async def _final_selection_route_context(
    *,
    focus_ticker: str | None,
) -> dict[str, object]:
    return await _bounded_dashboard_context(
        f"final-selection:{focus_ticker or 'all'}",
        lambda: _final_selection_route_context_uncached(focus_ticker=focus_ticker),
        lambda: _final_selection_delayed_context(focus_ticker),
        timeout_seconds=DASHBOARD_ROUTE_CONTEXT_TIMEOUT_SECONDS,
        ttl_seconds=FINAL_SELECTION_ROUTE_CACHE_TTL_SECONDS,
    )


async def _final_selection_route_context_uncached(
    *,
    focus_ticker: str | None,
) -> dict[str, object]:
    if not focus_ticker:
        context = await final_selection_context()
        _store_final_selection_route_cache(context)
        return context
    return await final_selection_context(focus_ticker=focus_ticker)


async def _final_selection_route_base_context(
    *,
    focus_ticker: str | None = None,
) -> dict[str, object]:
    cached = _final_selection_route_cache.get("context")
    expires_at = _final_selection_route_cache.get("expires_at", 0.0)
    builder_id = id(final_selection_context)
    if (
        isinstance(cached, dict)
        and isinstance(expires_at, float)
        and expires_at > time.monotonic()
        and _final_selection_route_cache.get("builder_id") == builder_id
    ):
        return dict(cached)
    async with _final_selection_route_cache_lock:
        cached = _final_selection_route_cache.get("context")
        expires_at = _final_selection_route_cache.get("expires_at", 0.0)
        if (
            isinstance(cached, dict)
            and isinstance(expires_at, float)
            and expires_at > time.monotonic()
            and _final_selection_route_cache.get("builder_id") == builder_id
        ):
            return dict(cached)
        context = await final_selection_context()
        _store_final_selection_route_cache(context)
        return dict(context)


def _store_final_selection_route_cache(context: Mapping[str, object]) -> None:
    cached_context = dict(context)
    cached_context["focused_ticker"] = ""
    cached_context["focused_final_selection"] = final_selection_focus_context([], None)
    _final_selection_route_cache["context"] = cached_context
    _final_selection_route_cache["expires_at"] = (
        time.monotonic() + FINAL_SELECTION_ROUTE_CACHE_TTL_SECONDS
    )
    _final_selection_route_cache["builder_id"] = id(final_selection_context)


def _clear_final_selection_route_cache() -> None:
    _final_selection_route_cache["context"] = None
    _final_selection_route_cache["expires_at"] = 0.0
    _final_selection_route_cache["builder_id"] = 0


@router.post("/execution-preview/operator-advance")
async def record_operator_manual_advance(
    request: Request,
    cycle_id: str,
    ticker: str,
    as_of: str,
    override_reason: str | None = None,
    blocked_reason: str | None = None,
    acknowledged: bool = False,
) -> Response:
    report_hash = await _selection_report_hash_for_review(
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
    )
    if report_hash is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "current selection report not found; refresh the execution preview "
                "before recording a manual advance for these report details"
            ),
        )
    reason = override_reason or await _request_form_text(request, "override_reason")
    blocked = blocked_reason or await _request_form_text(request, "blocked_reason")
    acknowledged = acknowledged or await _request_form_bool(request, "acknowledged")
    try:
        event = build_operator_manual_advance_event(
            cycle_id=cycle_id,
            ticker=ticker,
            as_of=as_of,
            selection_report_hash=report_hash,
            override_reason=reason or "",
            blocked_reason=blocked,
            acknowledged=acknowledged,
        )
        async with get_session() as session:
            await record_candidate_lifecycle_event(session, event)
            await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        try:
            append_runtime_lifecycle_event_artifact(event)
        except OSError as write_error:
            raise HTTPException(
                status_code=503,
                detail="operator manual advance could not be persisted",
            ) from write_error
    _clear_operator_route_caches()
    normalized_ticker = ticker.upper()
    query = urlencode({"ticker": normalized_ticker})
    return RedirectResponse(
        url=f"/execution-preview?{query}#focused-preview-{normalized_ticker}",
        status_code=303,
    )


@router.get("/risk")
async def risk(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "risk.html",
        await _bounded_dashboard_context(
            "risk",
            risk_context,
            _risk_delayed_context,
        ),
    )


@router.get("/execution-preview")
async def execution_preview(request: Request) -> Response:
    focus_ticker = str(request.query_params.get("ticker") or "").strip().upper()
    context = await _execution_preview_route_context(focus_ticker=focus_ticker or None)
    notice = _execution_notice_from_request(request)
    if notice is not None:
        context["execution_notice"] = notice
    return templates.TemplateResponse(
        request,
        "execution_preview.html",
        context,
    )


async def _execution_preview_route_context(
    *,
    focus_ticker: str | None,
) -> dict[str, object]:
    return await _bounded_dashboard_context(
        f"execution-preview:{focus_ticker or 'all'}",
        lambda: _execution_preview_route_context_uncached(focus_ticker=focus_ticker),
        lambda: _execution_preview_delayed_context(focus_ticker),
        timeout_seconds=DASHBOARD_ROUTE_CONTEXT_TIMEOUT_SECONDS,
        ttl_seconds=EXECUTION_PREVIEW_ROUTE_CACHE_TTL_SECONDS,
    )


async def _execution_preview_route_context_uncached(
    *,
    focus_ticker: str | None,
) -> dict[str, object]:
    if not focus_ticker:
        return await _execution_preview_route_base_context()
    context = await _execution_preview_route_base_context()
    rows_value = context.get("preview_rows")
    preview_rows = rows_value if isinstance(rows_value, list) else []
    context["focused_execution"] = execution_preview_focus_context(
        preview_rows,
        focus_ticker,
    )
    return context


async def _execution_preview_route_base_context() -> dict[str, object]:
    cached = _execution_preview_route_cache.get("context")
    expires_at = _execution_preview_route_cache.get("expires_at", 0.0)
    builder_id = id(execution_preview_context)
    if (
        isinstance(cached, dict)
        and isinstance(expires_at, float)
        and expires_at > time.monotonic()
        and _execution_preview_route_cache.get("builder_id") == builder_id
    ):
        return dict(cached)
    async with _execution_preview_route_cache_lock:
        cached = _execution_preview_route_cache.get("context")
        expires_at = _execution_preview_route_cache.get("expires_at", 0.0)
        if (
            isinstance(cached, dict)
            and isinstance(expires_at, float)
            and expires_at > time.monotonic()
            and _execution_preview_route_cache.get("builder_id") == builder_id
        ):
            return dict(cached)
        context = await execution_preview_context()
        _store_execution_preview_route_cache(context)
        return dict(context)


def _store_execution_preview_route_cache(context: Mapping[str, object]) -> None:
    _execution_preview_route_cache["context"] = dict(context)
    _execution_preview_route_cache["expires_at"] = (
        time.monotonic() + EXECUTION_PREVIEW_ROUTE_CACHE_TTL_SECONDS
    )
    _execution_preview_route_cache["builder_id"] = id(execution_preview_context)


def _clear_execution_preview_route_cache() -> None:
    _execution_preview_route_cache["context"] = None
    _execution_preview_route_cache["expires_at"] = 0.0
    _execution_preview_route_cache["builder_id"] = 0


async def warm_execution_preview_route_cache() -> bool:
    try:
        await asyncio.wait_for(
            _execution_preview_route_base_context(),
            timeout=STATUS_ROUTE_TIMEOUT_SECONDS * 3,
        )
    except Exception:  # noqa: BLE001 - startup warmup must not break the app
        return False
    return True


def _clear_execution_preview_status_cache() -> None:
    _execution_preview_status_cache["payload"] = None
    _execution_preview_status_cache["expires_at"] = 0.0
    _execution_preview_status_cache["builder_id"] = 0
    _execution_preview_status_cache["task"] = None
    _execution_preview_status_cache["version"] = (
        int(_execution_preview_status_cache.get("version") or 0) + 1
    )


def _clear_paper_review_status_cache() -> None:
    _paper_review_status_cache["payload"] = None
    _paper_review_status_cache["expires_at"] = 0.0
    _paper_review_status_cache["builder_id"] = 0
    _paper_review_status_cache["task"] = None
    _paper_review_status_cache["version"] = (
        int(_paper_review_status_cache.get("version") or 0) + 1
    )


def _clear_scheduler_work_queue_status_cache() -> None:
    _scheduler_work_queue_status_cache["payload"] = None
    _scheduler_work_queue_status_cache["expires_at"] = 0.0
    _scheduler_work_queue_status_cache["builder_id"] = 0
    _scheduler_work_queue_status_cache["task"] = None
    _scheduler_work_queue_status_cache["version"] = (
        int(_scheduler_work_queue_status_cache.get("version") or 0) + 1
    )


async def _execution_preview_status_payload_cached() -> dict[str, object]:
    return await _status_payload_cached_singleflight(
        cache=_execution_preview_status_cache,
        lock=_execution_preview_status_cache_lock,
        builder_id=id(execution_preview_context),
        builder=_execution_preview_status_payload_sync,
        timeout_payload_factory=_execution_preview_status_timeout_payload,
    )


async def _paper_review_status_payload() -> dict[str, object]:
    return await _status_payload_cached_singleflight(
        cache=_paper_review_status_cache,
        lock=_paper_review_status_cache_lock,
        builder_id=id(paper_review_status_context),
        builder=_paper_review_status_context_sync,
        timeout_payload_factory=_paper_review_status_timeout_payload,
    )


def _execution_preview_route_base_context_sync() -> dict[str, object]:
    return asyncio.run(_execution_preview_route_base_context())


def _execution_preview_status_payload_sync() -> dict[str, object]:
    return _execution_preview_status_payload(_execution_preview_route_base_context_sync())


def _execution_preview_status_payload_from_artifact() -> dict[str, object] | None:
    if id(execution_preview_context) != _DEFAULT_EXECUTION_PREVIEW_CONTEXT_ID:
        return None
    previews = runtime_execution_preview_artifacts(
        limit=FINAL_SELECTION_REPORT_LIMIT,
    )
    if not previews:
        return None
    rows = [_execution_preview_artifact_status_row(preview) for preview in previews]
    compact_rows = [_execution_preview_status_preview(row) for row in rows]
    ready_count = sum(1 for row in rows if row["preview_state"] == "READY")
    blocked_count = sum(
        1 for row in rows if _execution_preview_artifact_is_operator_blocker(row)
    )
    disabled_count = sum(
        1
        for row in rows
        if row["preview_state"] == "DISABLED"
        or _execution_preview_artifact_is_context_only(row)
    )
    submit_ready_count = sum(1 for row in rows if row["submit_enabled"] is True)
    approval_available_count = sum(
        1 for row in rows if row["order_approval_available"] is True
    )
    cycle_id = str(rows[0]["cycle_id"]) if rows else ""
    generated_at = str(previews[0].get("generated_at") or "")
    artifact_path = DEFAULT_RUNTIME_ARTIFACT_ROOT / "execution-previews.json"
    return {
        "schema_version": "0.1.0",
        "available": True,
        "cycle_id": cycle_id,
        "ready": submit_ready_count > 0,
        "verdict": _execution_preview_status_verdict(
            preview_count=len(rows),
            ready_count=ready_count,
            blocked_count=blocked_count,
            submit_ready_count=submit_ready_count,
            order_approval_available_count=approval_available_count,
        ),
        "preview_count": len(rows),
        "ready_count": ready_count,
        "orderable_count": ready_count,
        "submit_ready_count": submit_ready_count,
        "order_approval_available_count": approval_available_count,
        "review_only_count": disabled_count,
        "blocked_count": blocked_count,
        "disabled_count": disabled_count,
        "submit_gate_open": submit_ready_count > 0,
        "submit_gate_label": "Open" if submit_ready_count > 0 else "Closed",
        "headline": _execution_preview_artifact_headline(
            preview_count=len(rows),
            ready_count=ready_count,
            submit_ready_count=submit_ready_count,
        ),
        "detail": (
            "Execution status is read from the latest runtime execution-preview "
            f"artifact written at {generated_at or 'an unknown time'}. Open the full "
            "Execution Preview screen before submitting paper orders; it revalidates "
            "broker, approvals, and freshness."
        ),
        "freshness_gate": {
            "ready": False,
            "status_label": "Full execution recheck required",
            "status_class": "warn",
            "detail": (
                "This fast status confirms artifact rows exist. The full execution "
                "page still performs broker and freshness validation before submit."
            ),
        },
        "runtime_origin": "runtime_artifact_selected",
        "runtime_artifact_path": str(artifact_path),
        "runtime_artifact_timestamp": generated_at,
        "rows": compact_rows,
        "previews": compact_rows,
        "blockers": [
            _execution_preview_blocker(row)
            for row in rows
            if _execution_preview_artifact_is_operator_blocker(row)
        ][:20],
    }


def _execution_preview_artifact_status_row(
    preview: Mapping[str, object],
) -> dict[str, object]:
    state = str(preview.get("preview_state") or "").upper()
    reasons = _execution_preview_artifact_reasons(preview, state)
    submit_enabled = preview.get("submit_enabled") is True
    hash_value = str(preview.get("order_intent_hash") or "")
    return {
        "cycle_id": str(preview.get("cycle_id") or ""),
        "ticker": str(preview.get("ticker") or "").upper(),
        "as_of": str(preview.get("as_of") or ""),
        "preview_state": state,
        "final_action": str(preview.get("final_action") or "").upper(),
        "side": str(preview.get("side") or "NONE").upper(),
        "risk_decision": str(preview.get("risk_decision") or ""),
        "submit_enabled": submit_enabled,
        "order_approval_available": False,
        "submit_blocker": _execution_preview_artifact_submit_blocker(
            state,
            reasons,
            submit_enabled=submit_enabled,
        ),
        "paper_promotion_status_label": _execution_preview_artifact_promotion_label(
            preview,
            state,
        ),
        "paper_promotion_reasons": reasons,
        "paper_promotion_reason_count": len(reasons),
        "order_intent_hash_label": hash_value[:12],
        "order_value_label": _execution_preview_artifact_order_value_label(preview),
        "approval_label": "Full execution recheck required",
        "execution_state": "NONE",
        "execution_status_label": "Not submitted",
        "execution_status_class": "neutral",
        "execution_reason": "No order submission is recorded in the status artifact.",
        "execution_event_time": "",
        "execution_event_time_label": "not submitted",
        "client_order_id": "",
        "filled_qty": None,
        "filled_avg_price": None,
        "submission_confirmation_label": "No paper submission recorded",
        "next_step": _execution_preview_artifact_next_step(state, submit_enabled),
    }


def _execution_preview_artifact_submit_blocker(
    state: str,
    reasons: Sequence[str],
    *,
    submit_enabled: bool,
) -> str:
    if submit_enabled:
        return ""
    if reasons:
        return reasons[0]
    if state == "DISABLED":
        return "Research-only preview; no paper order is available from this artifact."
    if state == "BLOCKED":
        return "Risk or policy checks stopped this preview before paper submission."
    return "Open Execution Preview to revalidate broker, approvals, and freshness."


def _execution_preview_artifact_final_action(row: Mapping[str, object]) -> str:
    final_action = str(row.get("final_action") or "").upper()
    if final_action:
        return final_action
    reasons = row.get("paper_promotion_reasons")
    if isinstance(reasons, list) and reasons:
        return str(reasons[0]).strip().split(maxsplit=1)[0].strip(":").upper()
    return ""


def _execution_preview_artifact_is_context_only(row: Mapping[str, object]) -> bool:
    return (
        row.get("submit_enabled") is not True
        and _execution_preview_artifact_final_action(row) in {"NO_TRADE", "WATCH", "HOLD"}
    )


def _execution_preview_artifact_is_operator_blocker(row: Mapping[str, object]) -> bool:
    return (
        str(row.get("preview_state") or "").upper() == "BLOCKED"
        and not _execution_preview_artifact_is_context_only(row)
    )


def _execution_preview_artifact_reasons(
    preview: Mapping[str, object],
    state: str,
) -> list[str]:
    reasons = _string_list(preview, "reasons")
    final_action = str(preview.get("final_action") or "").upper()
    if final_action == "WATCH" or state == "DISABLED":
        lead = "No order - research only"
        return [lead, *[reason for reason in reasons if reason != lead]]
    return reasons


def _execution_preview_artifact_promotion_label(
    preview: Mapping[str, object],
    state: str,
) -> str:
    final_action = str(preview.get("final_action") or "").upper()
    if state == "READY":
        return "Paper preview ready for full recheck"
    if final_action == "WATCH":
        return "Research only"
    if state == "DISABLED":
        return "No paper order"
    return "Stopped by policy or risk"


def _execution_preview_artifact_order_value_label(
    preview: Mapping[str, object],
) -> str:
    value = preview.get("notional")
    if isinstance(value, int | float) and value > 0:
        return f"${value:,.2f}"
    return "No paper order"


def _execution_preview_artifact_next_step(state: str, submit_enabled: bool) -> str:
    if submit_enabled:
        return (
            "Open Execution Preview, confirm the broker and freshness proof, then "
            "approve the exact order intent."
        )
    if state == "READY":
        return "Open Execution Preview to complete order approval and freshness recheck."
    if state == "DISABLED":
        return "Use this ticker for research only; no paper order is available right now."
    if state == "BLOCKED":
        return (
            "Open the ticker detail to review the reason, or wait for a refreshed "
            "runtime cycle with enough confirmed evidence."
        )
    return "Open Execution Preview for the full paper-trading recheck."


def _execution_preview_artifact_headline(
    *,
    preview_count: int,
    ready_count: int,
    submit_ready_count: int,
) -> str:
    if submit_ready_count > 0:
        return f"{submit_ready_count} paper order(s) are ready for submit recheck."
    if ready_count > 0:
        return f"{ready_count} orderable preview(s) need approval or freshness recheck."
    if preview_count > 0:
        return f"{preview_count} execution preview row(s) are available for review."
    return "No execution previews yet."


def _paper_review_status_context_sync() -> dict[str, object]:
    return asyncio.run(paper_review_status_context())


async def _scheduler_work_queue_status_payload() -> dict[str, object]:
    return await _status_payload_cached_singleflight(
        cache=_scheduler_work_queue_status_cache,
        lock=_scheduler_work_queue_status_cache_lock,
        builder_id=id(scheduler_work_queue_status_context),
        builder=_scheduler_work_queue_status_context_sync,
        timeout_payload_factory=_scheduler_work_queue_status_timeout_payload,
    )


async def _status_payload_cached_singleflight(
    *,
    cache: dict[str, object],
    lock: asyncio.Lock,
    builder_id: int,
    builder: Callable[[], dict[str, object]],
    timeout_payload_factory: Callable[[], dict[str, object]],
) -> dict[str, object]:
    task = cache.get("task")
    cached = _status_cache_payload(
        cache,
        builder_id=builder_id,
    )
    if cached is not None and not _timeout_cache_hides_pending_task(cached, task):
        return cached
    async with lock:
        task = cache.get("task")
        cached = _status_cache_payload(
            cache,
            builder_id=builder_id,
        )
        if cached is not None and not _timeout_cache_hides_pending_task(cached, task):
            return cached
        task = cache.get("task")
        created_task = False
        if not isinstance(task, asyncio.Task) or task.done():
            task = asyncio.create_task(asyncio.to_thread(builder))
            created_task = True
            version = int(cache.get("version") or 0)
            cache["task"] = task
            task.add_done_callback(
                lambda completed, cache=cache, builder_id=builder_id, version=version: (
                    _store_status_cache_task_result(
                        cache,
                        builder_id=builder_id,
                        version=version,
                        task=completed,
                    )
                )
            )
    if not created_task:
        if task.done():
            try:
                payload = task.result()
            except BaseException:
                payload = timeout_payload_factory()
                _store_status_cache(
                    cache,
                    payload,
                    builder_id=builder_id,
                    ttl_seconds=STATUS_ROUTE_TIMEOUT_CACHE_TTL_SECONDS,
                )
                return dict(payload)
            _store_status_cache(
                cache,
                payload,
                builder_id=builder_id,
                ttl_seconds=STATUS_ROUTE_CACHE_TTL_SECONDS,
            )
            return dict(payload)
        try:
            payload = await asyncio.wait_for(
                asyncio.shield(task),
                timeout=STATUS_ROUTE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            payload = timeout_payload_factory()
            _store_status_cache(
                cache,
                payload,
                builder_id=builder_id,
                ttl_seconds=STATUS_ROUTE_TIMEOUT_CACHE_TTL_SECONDS,
            )
            return dict(payload)
        _store_status_cache(
            cache,
            payload,
            builder_id=builder_id,
            ttl_seconds=STATUS_ROUTE_CACHE_TTL_SECONDS,
        )
        return dict(payload)
    try:
        payload = await asyncio.wait_for(
            asyncio.shield(task),
            timeout=STATUS_ROUTE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        payload = timeout_payload_factory()
        _store_status_cache(
            cache,
            payload,
            builder_id=builder_id,
            ttl_seconds=STATUS_ROUTE_TIMEOUT_CACHE_TTL_SECONDS,
        )
        return dict(payload)
    _store_status_cache(
        cache,
        payload,
        builder_id=builder_id,
        ttl_seconds=STATUS_ROUTE_CACHE_TTL_SECONDS,
    )
    return dict(payload)


def _timeout_cache_hides_pending_task(
    cached: Mapping[str, object],
    task: object,
) -> bool:
    return (
        _is_status_timeout_payload(cached)
        and isinstance(task, asyncio.Task)
        and not task.done()
    )


def _is_status_timeout_payload(payload: Mapping[str, object]) -> bool:
    text = " ".join(
        str(payload.get(key) or "")
        for key in ("verdict", "state", "status", "status_label", "headline")
    ).casefold()
    return (
        "status_timeout" in text
        or "status timeout" in text
        or "status_delayed" in text
        or "status delayed" in text
        or "queue status delayed" in text
    )


def _store_status_cache_task_result(
    cache: dict[str, object],
    *,
    builder_id: int,
    version: int,
    task: asyncio.Task[dict[str, object]],
) -> None:
    if int(cache.get("version") or 0) != version:
        return
    try:
        payload = task.result()
    except BaseException:
        if cache.get("task") is task:
            cache["task"] = None
        return
    _store_status_cache(
        cache,
        payload,
        builder_id=builder_id,
        ttl_seconds=STATUS_ROUTE_CACHE_TTL_SECONDS,
    )
    if cache.get("task") is task:
        cache["task"] = None


def _scheduler_work_queue_status_context_sync() -> dict[str, object]:
    return asyncio.run(scheduler_work_queue_status_context())


def _status_cache_payload(
    cache: Mapping[str, object],
    *,
    builder_id: int,
) -> dict[str, object] | None:
    payload = cache.get("payload")
    expires_at = cache.get("expires_at", 0.0)
    if (
        isinstance(payload, dict)
        and isinstance(expires_at, float)
        and expires_at > time.monotonic()
        and cache.get("builder_id") == builder_id
    ):
        return dict(payload)
    return None


def _store_status_cache(
    cache: dict[str, object],
    payload: Mapping[str, object],
    *,
    builder_id: int,
    ttl_seconds: float = STATUS_ROUTE_CACHE_TTL_SECONDS,
) -> None:
    cache["payload"] = dict(payload)
    cache["expires_at"] = time.monotonic() + ttl_seconds
    cache["builder_id"] = builder_id


def _execution_preview_status_timeout_payload() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": "",
        "ready": False,
        "verdict": "status_timeout",
        "preview_count": 0,
        "ready_count": 0,
        "orderable_count": 0,
        "submit_ready_count": 0,
        "order_approval_available_count": 0,
        "review_only_count": 0,
        "blocked_count": 0,
        "disabled_count": 0,
        "submit_gate_open": False,
        "submit_gate_label": "Status delayed",
        "headline": "Execution status is still loading.",
        "detail": (
            "The execution-preview status reader exceeded the operator budget. "
            "Reload this status after the runtime cache warms before approving paper orders."
        ),
        "freshness_gate": {
            "ready": False,
            "status_label": "Status delayed",
            "status_class": "warn",
            "detail": "Execution freshness could not be verified inside the status budget.",
        },
        "rows": [],
        "previews": [],
        "blockers": [
            {
                "ticker": "",
                "state": "status_timeout",
                "side": "NONE",
                "risk_decision": "UNKNOWN",
                "reason": "Execution status reader exceeded the operator budget.",
            }
        ],
    }


def _paper_review_status_timeout_payload() -> dict[str, object]:
    progress = {
        "total_count": 0,
        "reviewed_count": 0,
        "pending_count": 0,
        "approve_count": 0,
        "defer_count": 0,
        "reject_count": 0,
        "reviewed_label": "0/0",
        "status_label": "Review status delayed",
        "status_class": "warn",
        "detail": (
            "Paper-review queue did not load inside the operator budget. "
            "Reload after the runtime cache warms before using review actions."
        ),
    }
    return {
        "schema_version": "0.1.0",
        "cycle_id": None,
        "ready": False,
        "verdict": "status_timeout",
        "status_label": progress["status_label"],
        "status_class": progress["status_class"],
        "detail": progress["detail"],
        "total_count": progress["total_count"],
        "pending_count": progress["pending_count"],
        "approved_count": progress["approve_count"],
        "progress": progress,
        "queue": [],
    }


def _scheduler_work_queue_status_timeout_payload() -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "headline": "Automation queue status is still loading.",
        "status_label": "Queue status delayed",
        "status_class": "warn",
        "tradability_detail": (
            "The scheduler queue did not load inside the operator budget. "
            "Refresh this panel after the runtime cache warms before relying on lane-refresh actions."
        ),
        "summary": {
            "headline": "Automation queue status is still loading.",
            "counts": {"due_now": 0, "running": 0},
        },
        "ticker_tiers": {"tiers": {}},
        "tradability": {
            "status_label": "Queue status delayed",
            "status_class": "warn",
            "detail": "Scheduler queue proof exceeded the operator budget.",
        },
        "repair_plan": {"jobs": []},
        "execution_freshness_gate": {"checks": []},
        "scheduler_runtime": {
            "status_label": "Status delayed",
            "status_class": "warn",
            "detail": "Scheduler heartbeat was not loaded inside the status budget.",
        },
        "runtime": {
            "status_label": "Status delayed",
            "status_class": "warn",
            "detail": "Scheduler heartbeat was not loaded inside the status budget.",
        },
        "automation_status": {
            "label": "Automation Status",
            "status_label": "Status delayed",
            "status_class": "warn",
            "detail": "Scheduler heartbeat was not loaded inside the status budget.",
            "tooltip": "Automation status could not be verified inside the status budget.",
        },
        "trading_freshness_gate": {
            "label": "Data Currency Check",
            "status_label": "Queue status delayed",
            "status_class": "warn",
            "detail": "Scheduler queue proof exceeded the operator budget.",
            "tooltip": "Data currency could not be verified inside the status budget.",
        },
        "refresh_workload": {
            "label": "Refresh Workload",
            "status_label": "Queue status delayed",
            "status_class": "warn",
            "detail": "Refresh workload was not loaded inside the status budget.",
            "live_critical_due_count": 0,
            "support_due_count": 0,
            "repair_due_count": 0,
            "running_count": 0,
            "next_live_eta_label": "checking",
            "tooltip": "Refresh workload could not be verified inside the status budget.",
        },
        "massive_orchestrator": {
            "state": "status_delayed",
            "status_label": "Status delayed",
            "status_class": "warn",
            "detail": "Market-data pipeline queue proof is still loading.",
            "due_now_count": 0,
            "blocked_count": 0,
            "lanes": [],
            "raw_lanes": [],
            "derived_signal_lanes": [],
            "lane_summary": {
                "execution_ready_count": 0,
                "execution_needs_refresh_count": 0,
                "support_due_count": 0,
                "research_disabled_count": 0,
            },
        },
        "massive_lane_rows": [],
        "massive_signal_rows": [],
        "repair": {"jobs": []},
        "repair_rows": [],
        "freshness_checks": [],
        "job_rows": [],
        "next_job_rows": [],
        "jobs": [],
        "next_jobs": [],
        "job_count": 0,
        "stale_rows": [],
        "tier_rows": [],
        "market_phase": "unknown",
    }


def _execution_preview_status_payload(
    context: dict[str, object],
) -> dict[str, object]:
    summary = _mapping_field(context, "summary")
    preview_rows_value = context.get("preview_rows")
    preview_rows = preview_rows_value if isinstance(preview_rows_value, list) else []
    rows = [
        _execution_preview_status_row(row)
        for row in preview_rows
        if isinstance(row, dict)
    ]
    compact_rows = [_execution_preview_status_preview(row) for row in rows]
    blockers = [
        _execution_preview_blocker(row)
        for row in rows
        if _execution_preview_status_needs_operator_attention(row)
    ]
    cycle_id = str(rows[0]["cycle_id"]) if rows else ""
    ready_count = _status_int(summary, "ready_count")
    blocked_count = _status_int(summary, "blocked_count")
    submit_ready_count = _status_int(summary, "submit_ready_count")
    approval_available_count = sum(
        1 for row in rows if row["order_approval_available"] is True
    )
    freshness_gate = context.get("execution_freshness_gate", {})
    freshness = freshness_gate if isinstance(freshness_gate, dict) else {}
    submit_gate_open = bool(summary.get("submit_gate_open") is True)
    return {
        "schema_version": "0.1.0",
        "cycle_id": cycle_id,
        "ready": submit_ready_count > 0,
        "verdict": _execution_preview_status_verdict(
            preview_count=_status_int(summary, "preview_count"),
            ready_count=ready_count,
            blocked_count=blocked_count,
            submit_ready_count=submit_ready_count,
            order_approval_available_count=approval_available_count,
        ),
        "preview_count": _status_int(summary, "preview_count"),
        "ready_count": ready_count,
        "orderable_count": ready_count,
        "submit_ready_count": submit_ready_count,
        "order_approval_available_count": approval_available_count,
        "review_only_count": sum(1 for row in rows if row["preview_state"] == "DISABLED"),
        "blocked_count": blocked_count,
        "disabled_count": _status_int(summary, "disabled_count"),
        "submit_gate_open": submit_gate_open,
        "submit_gate_label": _operator_text(summary.get("submit_gate_label") or "Unknown"),
        "headline": _operator_text(summary.get("headline") or ""),
        "detail": _operator_text(summary.get("detail") or ""),
        "freshness_gate": {
            "ready": freshness.get("ready") is True,
            "status_label": _operator_text(freshness.get("status_label") or "Unknown"),
            "status_class": str(freshness.get("status_class") or "neutral"),
            "detail": _operator_text(freshness.get("detail") or ""),
        },
        "rows": compact_rows,
        "previews": compact_rows,
        "blockers": blockers[:20],
    }


def _execution_preview_status_row(row: dict[str, object]) -> dict[str, object]:
    reasons = row.get("paper_promotion_reasons")
    paper_promotion_reasons = reasons if isinstance(reasons, list) else []
    compact_reasons = [
        _operator_text(reason)
        for reason in paper_promotion_reasons[:EXECUTION_STATUS_REASON_LIMIT]
        if reason is not None
    ]
    return {
        "cycle_id": str(row.get("cycle_id") or ""),
        "ticker": str(row.get("ticker") or "").upper(),
        "as_of": str(row.get("as_of") or ""),
        "preview_state": _operator_text(row.get("preview_state") or ""),
        "final_action": _operator_text(row.get("final_action") or ""),
        "side": str(row.get("side") or "NONE"),
        "risk_decision": _operator_text(row.get("risk_decision") or ""),
        "submit_enabled": row.get("submit_enabled") is True,
        "order_approval_available": row.get("order_approval_available") is True,
        "submit_blocker": _operator_text(row.get("submit_blocker") or ""),
        "paper_promotion_status_label": _operator_text(
            row.get("paper_promotion_status_label") or ""
        ),
        "paper_promotion_reasons": compact_reasons,
        "paper_promotion_reason_count": len(paper_promotion_reasons),
        "order_intent_hash_label": str(row.get("order_intent_hash_label") or ""),
        "order_value_label": _operator_text(row.get("order_value_label") or ""),
        "approval_label": _operator_text(row.get("approval_label") or ""),
        "execution_state": str(row.get("execution_state") or "NONE"),
        "execution_status_label": _operator_text(row.get("execution_status_label") or ""),
        "execution_status_class": str(row.get("execution_status_class") or "neutral"),
        "execution_reason": _operator_text(row.get("execution_reason") or ""),
        "execution_event_time": str(row.get("execution_event_time") or ""),
        "execution_event_time_label": str(row.get("execution_event_time_label") or ""),
        "client_order_id": str(row.get("client_order_id") or ""),
        "filled_qty": row.get("filled_qty"),
        "filled_avg_price": row.get("filled_avg_price"),
        "submission_confirmation_label": _operator_text(
            row.get("submission_confirmation_label") or ""
        ),
        "next_step": _operator_text(row.get("next_step") or ""),
    }


def _execution_preview_status_preview(row: dict[str, object]) -> dict[str, object]:
    reasons = row.get("paper_promotion_reasons")
    paper_promotion_reasons = reasons if isinstance(reasons, list) else []
    return {
        "cycle_id": str(row.get("cycle_id") or ""),
        "ticker": str(row.get("ticker") or "").upper(),
        "as_of": str(row.get("as_of") or ""),
        "preview_state": str(row.get("preview_state") or ""),
        "final_action": str(row.get("final_action") or ""),
        "side": str(row.get("side") or "NONE"),
        "risk_decision": str(row.get("risk_decision") or ""),
        "submit_enabled": row.get("submit_enabled") is True,
        "order_approval_available": row.get("order_approval_available") is True,
        "submit_blocker": str(row.get("submit_blocker") or ""),
        "paper_promotion_status_label": str(
            row.get("paper_promotion_status_label") or ""
        ),
        "paper_promotion_reasons": [str(reason) for reason in paper_promotion_reasons],
        "paper_promotion_reason_count": int(row.get("paper_promotion_reason_count") or 0),
        "approval_label": str(row.get("approval_label") or ""),
        "order_intent_hash_label": str(row.get("order_intent_hash_label") or ""),
        "order_value_label": str(row.get("order_value_label") or ""),
        "next_step": str(row.get("next_step") or ""),
    }


def _execution_preview_blocker(row: dict[str, object]) -> dict[str, object]:
    reasons = row.get("paper_promotion_reasons")
    first_reason = ""
    if isinstance(reasons, list) and reasons:
        first_reason = str(reasons[0])
    reason = _operator_text(
        first_reason or str(row.get("submit_blocker") or row.get("next_step") or "")
    )
    return {
        "ticker": row["ticker"],
        "state": row["preview_state"],
        "side": row["side"],
        "risk_decision": row["risk_decision"],
        "reason": reason,
    }


def _execution_preview_status_needs_operator_attention(row: Mapping[str, object]) -> bool:
    if _execution_preview_artifact_is_operator_blocker(row):
        return True
    state = str(row.get("preview_state") or "").upper()
    if state not in {"BLOCKED", "DISABLED"}:
        return False
    if row.get("submit_enabled") is True:
        return False
    reasons = row.get("paper_promotion_reasons")
    has_reason = isinstance(reasons, list) and any(str(reason).strip() for reason in reasons)
    return has_reason or bool(str(row.get("submit_blocker") or row.get("next_step") or "").strip())


def _execution_preview_status_verdict(
    *,
    preview_count: int,
    ready_count: int,
    blocked_count: int,
    submit_ready_count: int,
    order_approval_available_count: int,
) -> str:
    if submit_ready_count > 0:
        return "submit_ready"
    if order_approval_available_count > 0:
        return "awaiting_order_approval"
    if ready_count > 0:
        return "orderable_needs_approval_or_freshness"
    if blocked_count > 0:
        return "research_only_or_blocked"
    if preview_count > 0:
        return "research_only_or_context_only"
    return "no_execution_previews"


def _status_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key, 0)
    return value if isinstance(value, int) else 0


def _execution_notice_from_request(request: Request) -> dict[str, object] | None:
    detail = str(request.query_params.get("execution_notice") or "").strip()
    if not detail:
        return None
    status_class = str(request.query_params.get("execution_notice_class") or "warn")
    if status_class not in {"pass", "warn", "block", "neutral"}:
        status_class = "warn"
    return {
        "headline": "Execution action needs attention",
        "detail": detail[:500],
        "status_class": status_class,
    }


def _execution_preview_notice_redirect(
    detail: str,
    *,
    status_class: str = "warn",
    ticker: str | None = None,
    anchor: str = "orderable-heading",
) -> RedirectResponse:
    message = detail.strip() or "Execution action could not be completed."
    query_values = {
        "execution_notice": message[:500],
        "execution_notice_class": status_class,
    }
    normalized_ticker = str(ticker or "").strip().upper()
    if normalized_ticker:
        query_values["ticker"] = normalized_ticker
        anchor = f"focused-preview-{normalized_ticker}"
    query = urlencode(query_values)
    return RedirectResponse(url=f"/execution-preview?{query}#{anchor}", status_code=303)


@router.post("/execution-preview/orders/approve")
async def approve_execution_order(
    request: Request,
    cycle_id: str,
    ticker: str,
    as_of: str,
    order_intent_hash: str,
) -> Response:
    del request
    try:
        broker, data_sources = await asyncio.gather(
            _fresh_broker_status_context(),
            runtime_data_source_status(),
        )
        context = await execution_preview_context(
            broker=broker,
            data_sources=data_sources,
            validate_contracts=True,
        )
        row = row_from_execution_context(
            context,
            cycle_id=cycle_id,
            ticker=ticker,
            as_of=as_of,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="execution preview not found")
        if row.get("order_approval_available") is not True:
            raise HTTPException(status_code=400, detail="only READY paper orders can be approved")
        if str(row["order_intent_hash"]) != order_intent_hash:
            raise HTTPException(
                status_code=409,
                detail="order details changed; refresh and approve again",
            )
        try:
            event = build_order_approval_event(_mapping_field(row, "preview"))
            async with get_session() as session:
                await record_candidate_lifecycle_event(session, event)
                await session.commit()
        except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
            raise HTTPException(
                status_code=503,
                detail="order approval could not be persisted",
            ) from exc
    except HTTPException as exc:
        return _execution_preview_notice_redirect(str(exc.detail), ticker=ticker)
    _clear_operator_route_caches()
    normalized_ticker = ticker.upper()
    query = urlencode({"ticker": normalized_ticker})
    return RedirectResponse(
        url=f"/execution-preview?{query}#focused-preview-{normalized_ticker}",
        status_code=303,
    )


@router.post("/execution-preview/orders")
async def submit_execution_order(
    request: Request,
    cycle_id: str,
    ticker: str,
    as_of: str,
    order_intent_hash: str,
) -> Response:
    normalized_ticker = ticker.upper()
    try:
        await _submit_execution_order_core(
            request=request,
            cycle_id=cycle_id,
            ticker=ticker,
            as_of=as_of,
            order_intent_hash=order_intent_hash,
        )
    except HTTPException as exc:
        status_class = "warn" if exc.status_code == 202 else "block" if exc.status_code >= 500 else "warn"
        return _execution_preview_notice_redirect(
            str(exc.detail),
            status_class=status_class,
            ticker=normalized_ticker,
        )
    _clear_operator_route_caches()
    query = urlencode({"ticker": normalized_ticker})
    return RedirectResponse(
        url=f"/execution-preview?{query}#focused-preview-{normalized_ticker}",
        status_code=303,
    )


async def _submit_execution_order_core(
    *,
    request: Request,
    cycle_id: str,
    ticker: str,
    as_of: str,
    order_intent_hash: str,
    broker: dict[str, object] | None = None,
    data_sources: list[dict[str, object]] | None = None,
    context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    normalized_ticker = ticker.upper()
    if not _env_bool_text("AGENCY_ALPACA_BROKER_ENABLED"):
        raise HTTPException(status_code=409, detail="Alpaca broker is disabled")
    policy = await load_active_portfolio_policy()
    if not policy.broker_submit_enabled:
        raise HTTPException(status_code=409, detail="broker submission is disabled")
    if broker is None or data_sources is None:
        broker, data_sources = await asyncio.gather(
            _fresh_broker_status_context(),
            runtime_data_source_status(),
        )
    try:
        _require_immediate_execution_freshness(broker, data_sources)
    except HTTPException as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc.detail)) from exc
    if context is None:
        context = await execution_preview_context(
            broker=broker,
            data_sources=data_sources,
            validate_contracts=True,
        )
    gate = _mapping_field(context, "execution_freshness_gate")
    if gate["ready"] is not True:
        raise HTTPException(status_code=409, detail=str(gate["detail"]))
    row = row_from_execution_context(
        context,
        cycle_id=cycle_id,
        ticker=ticker,
        as_of=as_of,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="execution preview not found")
    if str(row["order_intent_hash"]) != order_intent_hash:
        raise HTTPException(status_code=409, detail="order details changed; refresh and approve again")
    if row["order_approved"] is not True:
        raise HTTPException(
            status_code=409,
            detail="approval for the current order details is required",
        )
    if row["submit_enabled"] is not True:
        raise HTTPException(status_code=409, detail=str(row["submit_blocker"]))
    submit_gate_armed, operator_phrase = await _paper_submit_confirmation(request)
    if submit_gate_armed is not True or operator_phrase.strip().lower() != "submit paper orders":
        raise HTTPException(
            status_code=400,
            detail="Final paper-submit confirmation phrase is required.",
        )
    order_payload: dict[str, object] | None = None
    order_submitted = False
    reconciled_order: Mapping[str, object] = {}
    try:
        config = AlpacaTradingConfig.from_env()
        config.require_paper(purpose="execution preview order submission")
        client = AlpacaBrokerClient(config)
        order_payload = build_market_order_payload(
            cycle_id=cycle_id,
            ticker=ticker,
            side=str(row["side"]),
            quantity=_optional_float_field(row, "quantity"),
            notional=_optional_float_field(row, "notional"),
            time_in_force=str(row["time_in_force"]),
            order_intent_hash=order_intent_hash,
        )
        await _record_order_submission_intent(row, order_payload)
        order = await client.submit_order(order_payload)
        order_submitted = True
        reconciled_order, reconciliation = await _reconcile_submitted_order(
            client,
            order_payload=order_payload,
            submitted_order=order,
        )
        await _record_submitted_order(row, reconciled_order, reconciliation)
    except AlpacaBrokerError as exc:
        if order_payload is not None and not order_submitted:
            with suppress(MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
                await _record_failed_order_submission(row, order_payload, str(exc))
        if order_submitted:
            raise HTTPException(
                status_code=202,
                detail=(
                    "paper order was submitted, but broker reconciliation failed; "
                    "verify Alpaca before retrying"
                ),
            ) from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        if order_submitted:
            raise HTTPException(
                status_code=202,
                detail=(
                    "paper order was submitted, but execution audit persistence failed; "
                    "verify Alpaca before retrying"
                ),
            ) from None
        raise HTTPException(
            status_code=503,
            detail="order details or submission audit persistence failed",
        ) from None
    return {
        "ticker": normalized_ticker,
        "broker_order_id": str(
            reconciled_order.get("id")
            or reconciled_order.get("order_id")
            or row.get("broker_order_id")
            or row.get("order_id")
            or row.get("submitted_order_id")
            or ""
        ),
        "order_intent_hash": str(row.get("order_intent_hash") or order_intent_hash),
    }


async def _paper_submit_confirmation(request: Request) -> tuple[bool, str]:
    body = await request.body()
    if _cockpit_payload_is_json(request):
        payload = _cockpit_submit_payload_from_body(request, body)
        return _cockpit_submit_ack(payload), _cockpit_submit_phrase(payload)
    values = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    armed_value = str(
        next(iter(values.get("submit_gate_armed") or values.get("submit_ack") or [""]), "")
    )
    phrase = str(
        next(iter(values.get("operator_phrase") or values.get("submit_phrase") or [""]), "")
    )
    return armed_value.strip().lower() in {"1", "true", "yes", "on"}, phrase


async def _fresh_broker_status_context() -> dict[str, object]:
    try:
        return await broker_status_context(use_cache=False)
    except TypeError:
        return await broker_status_context()


def _require_immediate_execution_freshness(
    broker: dict[str, object],
    data_sources: list[dict[str, object]],
) -> dict[str, object]:
    current_time = _execution_freshness_now()
    market_phase = classify_market_session(current_time).phase
    gate = execution_freshness_gate(
        broker,
        data_sources,
        now=current_time,
        market_phase=market_phase,
    )
    if gate.get("ready") is not True:
        raise HTTPException(
            status_code=409,
            detail=str(
                gate.get("detail")
                or "Broker state or critical market evidence is not fresh enough to submit."
            ),
        )
    return gate


def _execution_freshness_now() -> datetime:
    return datetime.now(UTC)


async def _reconcile_submitted_order(
    client: AlpacaBrokerClient,
    *,
    order_payload: dict[str, object],
    submitted_order: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    client_order_id = str(order_payload.get("client_order_id") or "").strip()
    if not client_order_id:
        raise AlpacaBrokerError("paper order payload is missing client_order_id")
    submitted_client_order_id = str(submitted_order.get("client_order_id") or "").strip()
    if submitted_client_order_id and submitted_client_order_id != client_order_id:
        raise AlpacaBrokerError(
            "Alpaca paper order response client_order_id did not match the approved intent"
        )
    reconciled_order = submitted_order
    for attempt in range(1, BROKER_RECONCILIATION_MAX_ATTEMPTS + 1):
        try:
            reconciled_order = await client.order_by_client_order_id(client_order_id)
        except AlpacaBrokerError as exc:
            return submitted_order, {
                "state": "client_order_id_lookup_failed",
                "client_order_id": client_order_id,
                "attempt_count": attempt,
                "error": str(exc),
            }
        reconciled_client_order_id = str(
            reconciled_order.get("client_order_id") or ""
        ).strip()
        if reconciled_client_order_id != client_order_id:
            raise AlpacaBrokerError(
                "Alpaca paper order reconciliation returned a different client_order_id"
            )
        status = str(reconciled_order.get("status", "")).upper()
        terminal = status in BROKER_RECONCILIATION_TERMINAL_STATUSES
        if terminal or attempt == BROKER_RECONCILIATION_MAX_ATTEMPTS:
            return reconciled_order, {
                "state": "client_order_id_confirmed",
                "client_order_id": client_order_id,
                "attempt_count": attempt,
                "terminal": terminal,
                "order_id_present": bool(str(reconciled_order.get("order_id", "")).strip()),
                "status": status,
            }
        await asyncio.sleep(BROKER_RECONCILIATION_POLL_SECONDS)
    return reconciled_order, {
        "state": "client_order_id_confirmed",
        "client_order_id": client_order_id,
        "attempt_count": BROKER_RECONCILIATION_MAX_ATTEMPTS,
        "terminal": False,
        "order_id_present": bool(str(reconciled_order.get("order_id", "")).strip()),
        "status": str(reconciled_order.get("status", "")).upper(),
    }


async def _selection_report_hash_for_review(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
) -> str | None:
    reports = await _dashboard_selection_reports(ticker=ticker, limit=50)
    key = (cycle_id, ticker.upper(), as_of)
    for report in reports:
        if _runtime_payload_key(report) == key:
            return selection_report_hash(report)
    return None


async def _selection_report_for_manual_llm_review(
    *,
    ticker: str,
    cycle_id: str,
    as_of: str,
) -> dict[str, object] | None:
    reports = await _dashboard_selection_reports(ticker=ticker, limit=50)
    key = (cycle_id, ticker.upper(), as_of)
    for report in reports:
        if _runtime_payload_key(report) == key:
            return dict(report)
    return None


def _manual_llm_lifecycle_event(
    event: Mapping[str, object],
    *,
    event_time: str,
) -> dict[str, object]:
    output = dict(event)
    cycle_id = str(output["cycle_id"])
    ticker = str(output["ticker"]).upper()
    event_type = str(output["event_type"])
    output["ticker"] = ticker
    output["event_time"] = event_time
    output["event_id"] = make_lifecycle_event_id(
        cycle_id=cycle_id,
        ticker=ticker,
        event_type=event_type,
        event_time=event_time,
    )
    payload = output.get("payload")
    output["payload"] = {
        **(dict(payload) if isinstance(payload, Mapping) else {}),
        "manual_trigger": True,
        "triggered_by": "candidate_detail",
    }
    return output


def _manual_prompt_audit(
    prompt_audit: Mapping[str, object],
    *,
    event_time: str,
) -> dict[str, object]:
    output = dict(prompt_audit)
    output["created_at"] = event_time
    payload = output.get("payload")
    output["payload"] = {
        **(dict(payload) if isinstance(payload, Mapping) else {}),
        "manual_trigger": True,
        "triggered_by": "candidate_detail",
    }
    return output


async def _request_value(request: Request, field_name: str) -> str | None:
    value = request.query_params.get(field_name)
    if value is not None and value.strip():
        return " ".join(value.split())
    return await _request_form_text(request, field_name)


async def _caution_acknowledgement_required_for_review(
    *,
    cycle_id: str,
    ticker: str,
    as_of: str,
) -> bool:
    reference = {"cycle_id": cycle_id, "ticker": ticker.upper(), "as_of": as_of}
    reports, risk_decisions = await asyncio.gather(
        _dashboard_selection_reports(ticker=ticker, limit=50),
        _dashboard_risk_decisions(ticker=ticker, limit=50),
    )
    report = _matching_payload(reports, reference)
    if report is None:
        return False
    caution = _review_caution(report, _matching_payload(risk_decisions, report))
    return bool(caution["required"])


async def _request_form_bool(request: Request, field_name: str) -> bool:
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        try:
            body = (await request.body()).decode("utf-8")
        except UnicodeDecodeError:
            return False
        values = parse_qs(body, keep_blank_values=True)
        return any(_truthy_form_value(value) for value in values.get(field_name, []))
    if "multipart/form-data" not in content_type:
        return False
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return False
    return _truthy_form_value(form.get(field_name))


async def _request_form_text(request: Request, field_name: str) -> str | None:
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type:
        try:
            body = (await request.body()).decode("utf-8")
        except UnicodeDecodeError:
            return None
        values = parse_qs(body, keep_blank_values=True)
        return _clean_form_text(values.get(field_name, [""])[0])
    if "multipart/form-data" not in content_type:
        return None
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return None
    return _clean_form_text(form.get(field_name))


def _truthy_form_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _clean_form_text(value: object) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


@router.get("/policy")
async def policy(request: Request) -> Response:
    db_policy: PortfolioPolicy | None = None
    try:
        async with get_session() as session:
            db_policy = await load_policy_from_db(session)
    except Exception:  # noqa: BLE001
        pass

    active_policy = await load_active_portfolio_policy()
    db_backed = db_policy is not None
    data_load_status = await live_dashboard_data_load_status()
    return templates.TemplateResponse(
        request,
        "policy.html",
        {
            "policy_sections": policy_sections(active_policy),
            "policy": active_policy.as_dict(),
            "summary": policy_summary(db_backed=db_backed, policy=active_policy),
            "data_health": dashboard_data_health(
                "Policy dashboard",
                data_load_status=data_load_status,
                extra_rows=(
                    {
                        "kind": "Policy source",
                        "name": "Portfolio and execution policy",
                        "status_label": "DB-backed" if db_backed else "Local fallback",
                        "status_class": "pass" if db_backed else "warn",
                        "coverage_label": "active policy loaded",
                        "freshness_label": "loaded on request",
                        "last_update": "database" if db_backed else "environment/local config",
                        "detail": (
                            "Risk and execution gates read these limits before "
                            "paper sizing and submission."
                        ),
                    },
                ),
            ),
        },
    )


@router.get("/portfolio-monitor")
async def portfolio_monitor(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "portfolio_monitor.html",
        await _bounded_dashboard_context(
            "portfolio-monitor",
            portfolio_monitor_context,
            _portfolio_delayed_context,
        ),
    )


@router.get("/signals")
async def signals(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "signals.html",
        await _bounded_dashboard_context(
            "signals",
            signals_context,
            _signals_delayed_context,
        ),
    )


@router.get("/market-regime")
async def market_regime(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "market_regime.html",
        await _bounded_dashboard_context(
            "market-regime",
            market_regime_context,
            _market_regime_delayed_context,
        ),
    )


@router.post("/market-regime/refresh")
async def market_regime_refresh() -> RedirectResponse:
    from agency.views import market_regime as market_regime_view

    await market_regime_view.refresh_market_regime_context()
    return RedirectResponse("/market-regime", status_code=303)


@router.get("/universe")
async def universe() -> RedirectResponse:
    # Legacy alias. The V3 navigation exposes this workflow as "Universe & market".
    return RedirectResponse("/market-regime", status_code=303)


@router.post("/portfolio-monitor/snapshots")
async def record_portfolio_snapshot() -> Response:
    broker = await _fresh_broker_status_context()
    if broker.get("connected") is not True:
        raise HTTPException(status_code=503, detail=str(broker.get("detail", "broker offline")))
    try:
        async with get_session() as session:
            await persist_portfolio_snapshot(session, broker)
            await session.commit()
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=503,
            detail="portfolio snapshot persistence unavailable",
        ) from exc
    return RedirectResponse(url="/portfolio-monitor", status_code=303)


@router.get("/status/broker")
async def broker_status() -> dict[str, object]:
    return await broker_status_context()


@router.get("/learning")
async def learning(request: Request) -> Response:
    return templates.TemplateResponse(
        request,
        "learning.html",
        await _bounded_dashboard_context(
            "learning",
            learning_context,
            _learning_delayed_context,
        ),
    )
