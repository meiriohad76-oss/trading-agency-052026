"""View-model constructors for the command page."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from agency.api.health import (
    contract_summaries,
    runtime_data_source_status,  # noqa: F401 - kept for dashboard test monkeypatching.
    runtime_data_source_status_with_load_status,
    unavailable_data_source_status,
)
from agency.runtime import build_live_readiness, scheduler_work_queue_context
from agency.runtime.data_load_status import SOURCE_HEALTH_MAX_AGE_SECONDS, load_data_load_status
from agency.runtime.data_refresh_progress import load_data_refresh_progress
from agency.runtime.full_live_readiness import load_full_live_readiness
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.runtime.operational_readiness import build_operational_readiness
from agency.runtime.provider_readiness import load_provider_readiness
from agency.services import PortfolioPolicy, load_active_portfolio_policy
from agency.views._shared import (
    ACTIONABLE_ACTIONS,
    FINAL_SELECTION_REPORT_LIMIT,
    REFRESHABLE_MASSIVE_LANES,
    _active_cycle_reports,
    _dashboard_risk_decisions,
    _dashboard_selection_reports,
    _format_timestamp_or_text,
    _human_review_index,
    _int_field,
    _is_actionable_candidate,
    _label_text,
    _lifecycle_events_for_reports,
    _list_field,
    _mapping_field,
    _mapping_list_field,
    _operator_text,
    _plural,
    _risk_decisions_for_reports,
    _runtime_payload_key,
    _source_health_origin_label,
    _source_is_degraded,
    dashboard_data_health,
)

DASHBOARD_RUNTIME_QUERY_TIMEOUT_SECONDS = 30.0
COMMAND_DASHBOARD_REPORT_LIMIT = 20
LIVE_CRITICAL_SCHEDULER_DATASETS = {"prices_daily", "stock_trades"}
LIVE_CRITICAL_SCHEDULER_SIGNALS = {
    "abnormal_volume",
    "block_trade_pressure",
    "buy_sell_pressure",
    "market_flow_trend",
    "pre_market_unusual_activity",
    "sector_momentum",
    "technical_analysis",
    "unusual_trade_activity",
}
SCHEDULER_DATASET_REFRESH_ACTIONS = {
    "news_rss": {
        "url": "/scheduler/datasets/news_rss/refresh",
        "label": "Refresh RSS/news",
        "detail": "Runs only the RSS/news refresh job if the scheduler policy marks it due.",
    },
    "subscription_emails": {
        "url": "/scheduler/subscription-emails/login-refresh",
        "label": "Open email login refresh",
        "detail": (
            "Opens a visible local refresh window so the operator can log in to "
            "Seeking Alpha before article links are opened."
        ),
    },
    "sec_company_facts": {
        "url": "/scheduler/datasets/sec_company_facts/refresh",
        "label": "Refresh SEC facts",
        "detail": "Runs only the SEC company-facts refresh if the scheduler policy marks it due.",
    },
    "sec_form4": {
        "url": "/scheduler/datasets/sec_form4/refresh",
        "label": "Refresh Form 4",
        "detail": "Runs only the SEC Form 4 refresh if the scheduler policy marks it due.",
    },
    "sec_13f": {
        "url": "/scheduler/datasets/sec_13f/refresh",
        "label": "Refresh 13F",
        "detail": "Runs only the SEC 13F refresh if the scheduler policy marks it due.",
    },
    "prices_daily": {
        "url": "/scheduler/massive-lanes/massive_daily_bars/refresh",
        "label": "Refresh daily bars",
        "detail": "Runs the Massive daily-bars lane under the trade-aware lane policy.",
    },
    "stock_trades": {
        "url": "/scheduler/massive-lanes/massive_live_trade_slices/refresh",
        "label": "Refresh live trades",
        "detail": "Runs the Massive live-trade-slices lane under the trade-aware lane policy.",
    },
}


class RuntimeRowsUnavailable(RuntimeError):
    """Raised when persisted runtime rows cannot be read for status endpoints."""


async def dashboard_context() -> dict[str, object]:
    from agency.views.candidates import candidate_rows
    from agency.views.market_regime import broker_status_context
    from agency.views.portfolio import _broker_execution_enabled

    data_refresh_task = asyncio.to_thread(load_data_refresh_progress)
    active_policy_task = load_active_portfolio_policy()
    (
        reports,
        source_load_status,
        risk_decisions,
        broker,
        data_refresh,
        active_policy,
    ) = await asyncio.gather(
        _dashboard_selection_reports_live(FINAL_SELECTION_REPORT_LIMIT),
        _runtime_data_source_status_with_load_status_live(),
        _dashboard_risk_decisions_live(FINAL_SELECTION_REPORT_LIMIT),
        broker_status_context(allow_live_read=False),
        data_refresh_task,
        active_policy_task,
    )
    data_sources = _mapping_list_field(source_load_status, "data_sources")
    data_load_status = _mapping_field(source_load_status, "data_load_status")
    live_config = _mapping_field(data_load_status, "live_config")
    if not live_config:
        live_config = await asyncio.to_thread(load_live_config_readiness)
    active_reports = _active_cycle_reports(reports)
    active_risk_decisions = _risk_decisions_for_reports(risk_decisions, active_reports)
    candidates = candidate_rows(active_reports)
    contracts = contract_summaries()
    readiness = readiness_view(
        build_live_readiness(
            source_health=data_sources,
            selection_reports=active_reports,
            risk_decisions=active_risk_decisions,
            lane_states=_mapping_list_field_or_empty(data_load_status, "lane_states"),
        )
    )
    paper_status = await paper_review_status_from_runtime(
        reports=active_reports,
        risk_decisions=active_risk_decisions,
        readiness=readiness,
    )
    review_queue = _mapping_list_field(paper_status, "queue")
    review_progress = _mapping_field(paper_status, "progress")
    summary = command_summary(
        candidates=candidates,
        data_sources=data_sources,
        contracts=contracts,
        readiness=readiness,
        review_queue=review_queue,
    )
    full_live_readiness = load_full_live_readiness(
        live_config=live_config,
        data_refresh=data_refresh,
        data_load_status=data_load_status,
    )
    scheduler_status_task = asyncio.to_thread(
        scheduler_work_queue_context,
        reports=active_reports,
        review_queue=review_queue,
        source_health=data_sources,
        broker=broker,
        data_load_status=data_load_status,
        data_refresh_progress=data_refresh,
    )
    operational_readiness = build_operational_readiness(
        health={"status": "ok", "service": "trading-agency-v3"},
        live_config=live_config,
        data_refresh=data_refresh,
        data_load_status=data_load_status,
        live_readiness=readiness,
        paper_review=paper_status,
        broker_execution_enabled=_broker_execution_enabled(),
    )
    provider_readiness = load_provider_readiness(live_config)
    data_refresh_view = data_refresh_progress_view(data_refresh)
    data_load_status_view_model = data_load_status_view(data_load_status)
    full_live_readiness_view_model = full_live_readiness_view(full_live_readiness)
    scheduler_status = await scheduler_status_task
    scheduler_view_model = scheduler_work_queue_view(scheduler_status)
    operational_readiness_view_model = operational_readiness_view(operational_readiness)
    provider_readiness_view_model = provider_readiness_view(provider_readiness)
    broker_view_model = broker_status_view(broker)
    runtime_signals = live_config.get("runtime_signals")
    runtime_signal_names = (
        tuple(str(lane) for lane in runtime_signals if isinstance(lane, str))
        if isinstance(runtime_signals, list)
        else ()
    )
    return {
        "actions": command_actions(),
        "broker_status": broker_view_model,
        "contracts": contracts,
        "data_sources": source_status_rows(data_sources),
        "candidates": candidates,
        "data_refresh": data_refresh_view,
        "data_load_status": data_load_status_view_model,
        "full_live_readiness": full_live_readiness_view_model,
        "live_config": live_config_view(live_config),
        "operational_readiness": operational_readiness_view_model,
        "provider_readiness": provider_readiness_view_model,
        "policy_sections": policy_sections(active_policy),
        "policy_summary": policy_summary(policy=active_policy),
        "readiness": readiness,
        "review_progress": review_progress,
        "review_queue": review_queue,
        "scheduler": scheduler_view_model,
        "status_overview": command_status_overview(
            broker=broker_view_model,
            data_load_status=data_load_status_view_model,
            data_refresh=data_refresh_view,
            full_live_readiness=full_live_readiness_view_model,
            operational_readiness=operational_readiness_view_model,
            provider_readiness=provider_readiness_view_model,
            review_progress=review_progress,
            scheduler=scheduler_view_model,
        ),
        "data_health": dashboard_data_health(
            "Command dashboard",
            data_load_status=data_load_status,
            datasets=(
                "prices_daily",
                "stock_trades",
                "sec_company_facts",
                "sec_form4",
                "sec_13f",
                "news_rss",
                "subscription_emails",
            ),
            lanes=runtime_signal_names,
        ),
        "summary": summary,
    }

async def _dashboard_readiness_inputs(
    *,
    data_sources: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    live_config, data_refresh, data_load_status, active_policy = await asyncio.gather(
        asyncio.to_thread(load_live_config_readiness),
        asyncio.to_thread(load_data_refresh_progress),
        asyncio.to_thread(
            load_data_load_status,
            source_health_rows=data_sources,
            source_health_origin=_source_health_origin_label(data_sources),
        ),
        load_active_portfolio_policy(),
    )
    return {
        "live_config": live_config,
        "data_refresh": data_refresh,
        "data_load_status": data_load_status,
        "active_policy": active_policy,
    }

def command_summary(
    *,
    candidates: Sequence[Mapping[str, object]],
    data_sources: Sequence[Mapping[str, object]],
    contracts: Sequence[Mapping[str, object]],
    readiness: Mapping[str, object] | None = None,
    review_queue: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    degraded_source_count = (
        _int_field(readiness, "degraded_source_count")
        if readiness is not None
        else sum(1 for source in data_sources if _source_is_degraded(source))
    )
    candidate_count = len(candidates)
    actionable_candidate_count = sum(
        1 for candidate in candidates if _is_actionable_candidate(candidate)
    )
    blocked_candidate_count = sum(
        1 for candidate in candidates if candidate.get("gate_status") == "BLOCK"
    )
    return {
        "candidate_count": candidate_count,
        "actionable_candidate_count": actionable_candidate_count,
        "blocked_candidate_count": blocked_candidate_count,
        "source_count": len(data_sources),
        "degraded_source_count": degraded_source_count,
        "contract_count": len(contracts),
        "review_queue_count": len(review_queue),
        "hero_class": _command_hero_class(candidate_count, degraded_source_count),
        "headline": _command_headline(candidate_count, actionable_candidate_count),
        "detail": _command_detail(candidate_count, degraded_source_count),
    }

def command_actions() -> list[dict[str, str]]:
    return [
        {"label": "System status", "href": "#system-status-heading"},
        {"label": "Data readiness", "href": "#status-data-readiness"},
        {"label": "Trade pull", "href": "#trade-pull-status-heading"},
        {"label": "Scheduler", "href": "#status-scheduler"},
        {"label": "Review queue", "href": "#review-queue-heading"},
        {"label": "Review candidates", "href": "#candidates-heading"},
        {"label": "Review data sources", "href": "#source-heading"},
        {"label": "Review contracts", "href": "#contracts-heading"},
    ]


async def _dashboard_selection_reports_live(
    limit: int,
) -> list[dict[str, object]]:
    return await _rows_from_live_runtime(
        _dashboard_selection_reports(limit=limit),
    )


async def _runtime_data_source_status_live() -> list[dict[str, object]]:
    payload = await _runtime_data_source_status_with_load_status_live()
    data_sources = _mapping_list_field(payload, "data_sources")
    if not data_sources:
        return unavailable_data_source_status("live source-health reader returned no rows")
    return [dict(row) for row in data_sources]


async def _runtime_data_source_status_with_load_status_live() -> dict[str, object]:
    try:
        payload = await asyncio.wait_for(
            runtime_data_source_status_with_load_status(),
            timeout=DASHBOARD_RUNTIME_QUERY_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        rows = unavailable_data_source_status(
            "live source-health reader timed out or failed"
        )
        return {
            "data_sources": rows,
            "data_load_status": await asyncio.to_thread(
                load_data_load_status,
                source_health_rows=rows,
                source_health_origin=_source_health_origin_label(rows),
            ),
        }
    data_source_rows: list[Mapping[str, object]] = _mapping_list_field(payload, "data_sources")
    if not data_source_rows:
        data_source_rows = [
            cast(Mapping[str, object], row)
            for row in unavailable_data_source_status(
                "live source-health reader returned no rows"
            )
        ]
    data_load_status = _mapping_field(payload, "data_load_status")
    if not data_load_status:
        data_load_status = await asyncio.to_thread(
            load_data_load_status,
            source_health_rows=data_source_rows,
            source_health_origin=_source_health_origin_label(data_source_rows),
        )
    return {
        "data_sources": [dict(row) for row in data_source_rows],
        "data_load_status": data_load_status,
    }



async def _dashboard_risk_decisions_live(
    limit: int,
) -> list[dict[str, object]]:
    return await _rows_from_live_runtime(
        _dashboard_risk_decisions(limit=limit),
    )


async def _dashboard_selection_reports_live_checked(
    limit: int,
) -> list[dict[str, object]]:
    try:
        try:
            return list(
                await asyncio.wait_for(
                    _dashboard_selection_reports(
                        limit=limit,
                        raise_on_unavailable=True,
                    ),
                    timeout=DASHBOARD_RUNTIME_QUERY_TIMEOUT_SECONDS,
                )
            )
        except TypeError as exc:
            if "raise_on_unavailable" not in str(exc):
                raise
            return list(
                await asyncio.wait_for(
                    _dashboard_selection_reports(limit=limit),
                    timeout=DASHBOARD_RUNTIME_QUERY_TIMEOUT_SECONDS,
                )
            )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeRowsUnavailable(
            "Runtime selection-report reader is unavailable."
        ) from exc


async def _dashboard_risk_decisions_live_checked(
    limit: int,
) -> list[dict[str, object]]:
    try:
        try:
            return list(
                await asyncio.wait_for(
                    _dashboard_risk_decisions(
                        limit=limit,
                        raise_on_unavailable=True,
                    ),
                    timeout=DASHBOARD_RUNTIME_QUERY_TIMEOUT_SECONDS,
                )
            )
        except TypeError as exc:
            if "raise_on_unavailable" not in str(exc):
                raise
            return list(
                await asyncio.wait_for(
                    _dashboard_risk_decisions(limit=limit),
                    timeout=DASHBOARD_RUNTIME_QUERY_TIMEOUT_SECONDS,
                )
            )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeRowsUnavailable(
            "Runtime risk-decision reader is unavailable."
        ) from exc


async def _rows_from_live_runtime(
    rows_awaitable: Awaitable[Sequence[dict[str, object]]],
) -> list[dict[str, object]]:
    try:
        rows = await asyncio.wait_for(
            rows_awaitable,
            timeout=DASHBOARD_RUNTIME_QUERY_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        return []
    return list(rows)


def source_status_rows(sources: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in sources:
        raw_status = str(source.get("status", "unknown"))
        raw_freshness = str(source.get("freshness", "unknown"))
        reliability_score = source.get("reliability_score", 0.0)
        if not isinstance(reliability_score, int | float):
            reliability_score = 0.0
        rows.append(
            {
                "source": str(source.get("source", "")),
                "status": _source_operator_status(raw_status),
                "freshness": _source_operator_status(raw_freshness),
                "raw_status": raw_status,
                "raw_freshness": raw_freshness,
                "reliability_pct": round(float(reliability_score) * 100),
                "status_class": _source_status_class(source),
                "checked_at": str(source.get("checked_at", "")),
            }
        )
    return rows


def _source_operator_status(value: str) -> str:
    if value.upper() == "STALE":
        return "Needs refresh"
    return _operator_text(value)

def readiness_view(summary: Mapping[str, object]) -> dict[str, object]:
    view = dict(summary)
    verdict = str(summary["verdict"])
    view["detail"] = _humanize_seconds_in_text(str(summary.get("detail") or ""))
    view["verdict_label"] = _label_text(verdict)
    view["status_class"] = _readiness_status_class(verdict)
    view["blocker_rows"] = _readiness_blocker_rows(summary)
    return view

def data_refresh_progress_view(progress: Mapping[str, object]) -> dict[str, object]:
    view = dict(progress)
    view["progress_style"] = f"width: {_bounded_percent(progress, 'percent_complete')}%"
    view["updated_at_label"] = _format_timestamp_or_text(progress.get("updated_at"))
    refresh_display = _data_refresh_display(progress)
    view.update(refresh_display)
    view["display_progress_style"] = (
        f"width: {_bounded_percent(refresh_display, 'display_percent_complete')}%"
    )
    trade_pull = progress.get("trade_pull")
    view["trade_pull"] = trade_pull_progress_view(
        cast(Mapping[str, object], trade_pull) if isinstance(trade_pull, Mapping) else {}
    )
    view["massive_lanes"] = _data_refresh_massive_lane_rows(
        _mapping_list_field_or_empty(progress, "massive_lanes")
    )
    return view

def _data_refresh_display(progress: Mapping[str, object]) -> dict[str, object]:
    state = str(progress.get("state") or "idle").lower()
    raw_status_label = str(progress.get("status_label") or _label_text(state))
    scope = _data_refresh_scope(progress)
    status_label = _data_refresh_display_status_label(state, raw_status_label, scope)
    status_class = _data_refresh_display_status_class(state, progress, scope)
    display_state = _data_refresh_display_state(state, scope)
    return {
        "display_status_label": status_label,
        "display_status_class": status_class,
        "display_state": display_state,
        "display_percent_complete": _bounded_percent(progress, "percent_complete"),
        "display_progress_label": _data_refresh_display_progress_label(progress, state),
        "current_job_label": _data_refresh_current_job_label(progress),
        "refresh_impact": _data_refresh_impact(scope, state),
        "next_action_label": _data_refresh_next_action(scope, state),
        "progress_tooltip": (
            "Progress shows the active refresh stop point. If a refresh failed, "
            "the label shows the failed job count instead of implying success."
        ),
        "dataset_tooltip": (
            "Dataset shows the current or failed dataset/lane from the latest "
            "refresh status file."
        ),
        "jobs_tooltip": (
            "Jobs is completed jobs divided by planned jobs for the latest refresh command."
        ),
        "eta_tooltip": (
            "ETA is only meaningful while a refresh is running. Failed, idle, or complete "
            "refreshes show no active ETA."
        ),
        "impact_tooltip": (
            "Refresh Impact separates live-critical failures from support and repair "
            "work so background repairs do not look like paper-trading blockers."
        ),
        "next_action_tooltip": (
            "Next Action tells the operator what to do with this refresh state before "
            "trusting affected data."
        ),
        "failure_label": _data_refresh_failure_label(progress, scope, state),
        "failure_detail": _data_refresh_failure_detail(progress, scope, state),
    }


def _data_refresh_scope(progress: Mapping[str, object]) -> str:
    candidates = [
        str(item)
        for item in _list_or_empty(progress.get("failed_datasets"))
        if str(item).strip()
    ]
    current = str(progress.get("current_dataset") or "").strip()
    if current and current.lower() != "none":
        candidates.append(current)
    if not candidates:
        return "none"
    normalized = {candidate.lower() for candidate in candidates}
    if any(_data_refresh_dataset_is_live_critical(value) for value in normalized):
        return "live_critical"
    if any(_data_refresh_dataset_is_repair(value) for value in normalized):
        return "repair"
    if any(_data_refresh_dataset_is_support(value) for value in normalized):
        return "support"
    return "unknown"


def _data_refresh_dataset_is_live_critical(value: str) -> bool:
    live_tokens = {
        "prices_daily",
        "stock_trades",
        "massive_daily_bars",
        "massive_live_trade_slices",
        "massive_premarket_trade_slices",
        "massive_block_trade_feed",
    }
    return value in live_tokens or value in LIVE_CRITICAL_SCHEDULER_DATASETS


def _data_refresh_dataset_is_repair(value: str) -> bool:
    repair_tokens = ("backtest", "repair", "historical", "full_depth", "trade_tape")
    return any(token in value for token in repair_tokens)


def _data_refresh_dataset_is_support(value: str) -> bool:
    support_tokens = (
        "sec_",
        "news",
        "rss",
        "subscription",
        "email",
        "form4",
        "13f",
        "company_facts",
        "reference",
        "options",
    )
    return any(token in value for token in support_tokens)


def _data_refresh_display_status_label(
    state: str,
    raw_status_label: str,
    scope: str,
) -> str:
    if state in {"failed", "blocked"}:
        prefix = "Blocked" if state == "blocked" else "Failed"
        return f"{prefix} - {_data_refresh_scope_label(scope)}"
    if state == "stale":
        return "Refresh monitor needs restart"
    if state == "running":
        return "Refreshing"
    if state in {"complete", "planned", "idle", "unavailable"}:
        return raw_status_label
    return raw_status_label or _label_text(state)


def _data_refresh_display_status_class(
    state: str,
    progress: Mapping[str, object],
    scope: str,
) -> str:
    if state in {"failed", "blocked"}:
        if scope in {"support", "repair"}:
            return "warn"
        return "block"
    if state == "stale":
        return "block"
    return str(progress.get("status_class") or "neutral")


def _data_refresh_display_state(state: str, scope: str) -> str:
    if state == "stale":
        return "needs_refresh"
    if state in {"failed", "blocked"} and scope in {"support", "repair"}:
        return f"{state}_{scope}"
    return state


def _data_refresh_scope_label(scope: str) -> str:
    return {
        "live_critical": "Live Critical",
        "support": "Support",
        "repair": "Repair",
        "unknown": "Scope Unknown",
        "none": "No Active Scope",
    }.get(scope, "Scope Unknown")


def _data_refresh_display_progress_label(
    progress: Mapping[str, object],
    state: str,
) -> str:
    completed = _optional_int(progress, "completed_jobs")
    total = _optional_int(progress, "total_jobs")
    jobs = f"{completed}/{total}" if total else f"{completed}/?"
    if state == "failed":
        return f"Failed after {jobs} jobs"
    if state == "blocked":
        return f"Blocked after {jobs} jobs"
    if state == "running":
        return f"{_bounded_percent(progress, 'percent_complete')}% complete"
    if state == "complete":
        return "Complete"
    return f"{_bounded_percent(progress, 'percent_complete')}%"


def _data_refresh_current_job_label(progress: Mapping[str, object]) -> str:
    dataset = str(progress.get("current_dataset") or "None")
    if dataset.lower() == "none":
        failures = [str(item) for item in _list_or_empty(progress.get("failed_datasets"))]
        if failures:
            dataset = failures[0]
    return dataset


def _data_refresh_impact(scope: str, state: str) -> dict[str, str]:
    if state in {"idle", "complete", "planned"}:
        return {
            "label": "No active load blocker",
            "status_class": "pass" if state == "complete" else "neutral",
            "detail": "No active refresh failure is recorded for the latest status snapshot.",
        }
    if state == "running":
        if scope == "live_critical":
            return {
                "label": "Live-critical refresh running",
                "status_class": "warn",
                "detail": (
                    "A live-critical lane is actively loading. Wait for it to finish before "
                    "submitting paper orders that depend on fresh market evidence."
                ),
            }
        if scope == "support":
            return {
                "label": "Support refresh running",
                "status_class": "neutral",
                "detail": (
                    "A support/context source is actively loading. It does not block paper "
                    "orders by itself, but affected context is still updating."
                ),
            }
        if scope == "repair":
            return {
                "label": "Repair refresh running",
                "status_class": "neutral",
                "detail": (
                    "Historical repair or backtest coverage is actively loading. Live review "
                    "can continue unless a downstream agent explicitly requires this lane."
                ),
            }
        return {
            "label": "Refresh running",
            "status_class": "neutral",
            "detail": "A refresh job is actively loading; wait for completion before trusting affected data.",
        }
    if scope == "live_critical":
        return {
            "label": "Live-critical affected",
            "status_class": "block",
            "detail": (
                "The affected lane can change review, risk, or paper-order readiness. "
                "Fix and rerun it before submitting paper orders that depend on it."
            ),
        }
    if scope == "support":
        return {
            "label": "Support/context failed",
            "status_class": "warn",
            "detail": (
                "The affected dataset improves context and source quality. It does not "
                "automatically block paper orders, but affected evidence should be treated "
                "as incomplete until the refresh succeeds."
            ),
        }
    if scope == "repair":
        return {
            "label": "Research/repair affected",
            "status_class": "warn",
            "detail": (
                "The affected work is historical repair or backtest coverage. It should not "
                "block live review unless a downstream agent explicitly requires it."
            ),
        }
    return {
        "label": "Impact unknown",
        "status_class": "block" if state in {"failed", "blocked", "stale"} else "neutral",
        "detail": "The refresh scope is not recognized, so treat the status as blocking until inspected.",
    }


def _data_refresh_next_action(scope: str, state: str) -> str:
    if state == "running":
        return "Wait for the active lane refresh to finish, then re-check data health."
    if state == "stale":
        return "Restart or inspect the refresh monitor before trusting the progress state."
    if state in {"failed", "blocked"}:
        if scope == "live_critical":
            return "Fix the failed live-critical lane and rerun it before paper-order submission."
        if scope == "support":
            return "Review can continue with current health gates; rerun the support refresh for complete context."
        if scope == "repair":
            return "Keep live work moving; schedule or resume the repair job off-hours."
        return "Inspect logs and rerun the failed refresh before relying on affected data."
    if state == "complete":
        return "Use the loaded data, subject to each lane's freshness badge."
    return "No refresh action is required unless a lane or source falls outside policy."


def _data_refresh_failure_label(
    progress: Mapping[str, object],
    scope: str,
    state: str,
) -> str:
    if state not in {"failed", "blocked"} and progress.get("has_failures") is not True:
        return ""
    return f"{_data_refresh_scope_label(scope)} dataset failure"


def _data_refresh_failure_detail(
    progress: Mapping[str, object],
    scope: str,
    state: str,
) -> str:
    if state not in {"failed", "blocked"} and progress.get("has_failures") is not True:
        return ""
    datasets = [
        str(item) for item in _list_or_empty(progress.get("failed_datasets")) if str(item)
    ]
    dataset_label = ", ".join(datasets) if datasets else _data_refresh_current_job_label(progress)
    impact = _data_refresh_impact(scope, state)
    return f"{dataset_label} did not complete. {impact['detail']}"


def _data_refresh_massive_lane_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [_data_refresh_massive_lane_view(row) for row in rows]


def _data_refresh_massive_lane_view(row: Mapping[str, object]) -> dict[str, object]:
    view = dict(row)
    status_label = _data_refresh_massive_lane_status_label(row)
    status_class = _data_refresh_massive_lane_status_class(row, status_label)
    impact_label, impact_detail = _data_refresh_massive_lane_impact(row)
    tooltip = (
        f"{status_label}. {impact_detail} "
        f"Manifest status: {row.get('manifest_status', 'missing')}; "
        f"coverage: {row.get('manifest_coverage_pct', 0)}%; "
        f"detail: {row.get('detail', 'No lane detail recorded.')}"
    )
    view.update(
        {
            "display_status_label": status_label,
            "display_status_class": status_class,
            "updated_at_label": _format_timestamp_or_text(row.get("updated_at")),
            "impact_label": impact_label,
            "impact_detail": impact_detail,
            "tooltip": _humanize_seconds_in_text(tooltip),
            "progress_tooltip": (
                "Lane progress is based on the lane manifest and, when available, "
                "the active lane progress file."
            ),
            "rows_tooltip": "Rows is the latest persisted row count from the lane manifest.",
            "updated_tooltip": "Updated is the latest progress or manifest timestamp for this lane.",
        }
    )
    return view


def _data_refresh_massive_lane_status_label(row: Mapping[str, object]) -> str:
    lane_id = str(row.get("lane_id") or "")
    state = str(row.get("state") or "").lower()
    manifest_status = str(row.get("manifest_status") or "").lower()
    if state == "ready":
        return "Verified Current"
    if state == "running":
        return "Refreshing"
    if state == "partial_usable":
        return "Usable With Gaps"
    if state == "partial":
        if "backtest" in lane_id or "trade_tape" in lane_id:
            return "Research Repair Partial"
        return "Partial Coverage"
    if state == "missing_manifest":
        if "options" in lane_id:
            return "Disabled / Entitlement Not Verified"
        if "reference" in lane_id:
            return "Reference Not Loaded"
        return "Not Loaded"
    if state == "stale":
        return "Refresh recommended"
    if state == "failed":
        return "Failed"
    if state == "blocked":
        return "Blocked"
    if manifest_status == "partial_usable":
        return "Usable With Gaps"
    if manifest_status == "complete":
        return "Verified Current"
    return str(row.get("status_label") or state.replace("_", " ").title() or "Unknown")


def _data_refresh_massive_lane_status_class(
    row: Mapping[str, object],
    status_label: str,
) -> str:
    if status_label in {"Verified Current"}:
        return "pass"
    if status_label in {"Failed", "Blocked", "Refresh recommended"}:
        return "block"
    if status_label == "Disabled / Entitlement Not Verified":
        return "neutral"
    if status_label in {
        "Usable With Gaps",
        "Research Repair Partial",
        "Partial Coverage",
        "Reference Not Loaded",
        "Not Loaded",
        "Refreshing",
    }:
        return "warn"
    return str(row.get("status_class") or "neutral")


def _data_refresh_massive_lane_impact(row: Mapping[str, object]) -> tuple[str, str]:
    lane_id = str(row.get("lane_id") or "")
    if lane_id in {
        "massive_daily_bars",
        "massive_live_trade_slices",
        "massive_premarket_trade_slices",
        "massive_block_trade_feed",
    }:
        return (
            "Execution-critical",
            "This lane can affect paper-order readiness because live decisions depend on its market data.",
        )
    if "options" in lane_id:
        return (
            "Optional / entitlement",
            "This lane is optional until the Massive options entitlement is verified and enabled.",
        )
    if "backtest" in lane_id or "trade_tape" in lane_id:
        return (
            "Research/repair",
            "This lane supports backtesting and historical research; it should not block live paper trading.",
        )
    return (
        "Support/context",
        "This lane supports context, reference data, or source hygiene for the agency.",
    )

def trade_pull_progress_view(trade_pull: Mapping[str, object]) -> dict[str, object]:
    view: dict[str, object] = {
        "state": "idle",
        "status_label": "No Pull",
        "status_class": "neutral",
        "percent_complete": 0,
        "ticker_progress_label": "not tracked",
        "current_ticker": "None",
        "current_trade_date": "not active",
        "current_rows_downloaded": 0,
        "current_pages_downloaded": 0,
        "row_count_label": "0",
        "latest_as_of": "not recorded",
        "window_label": "not recorded",
        "guardrail_label": "not configured",
        "detail": "No Massive stock-trades pull status is available yet.",
        "updated_at": "not recorded",
        "job_position_label": "not in latest batch",
    }
    view.update(trade_pull)
    view["status_label"] = _trade_pull_display_status(view)
    view["tooltip"] = _trade_pull_tooltip(view)
    view["progress_style"] = f"width: {_bounded_percent(view, 'percent_complete')}%"
    view["latest_as_of_label"] = _format_timestamp_or_text(view.get("latest_as_of"))
    view["updated_at_label"] = _format_timestamp_or_text(view.get("updated_at"))
    return view

def broker_status_view(broker: Mapping[str, object]) -> dict[str, object]:
    view = dict(broker)
    view["status_label"] = str(broker.get("status_label") or "Broker Unknown")
    view["status_class"] = str(broker.get("status_class") or "neutral")
    view["detail"] = str(broker.get("detail") or "No broker status detail is available.")
    view["mode_label"] = _label_text(str(broker.get("mode") or "unknown"))
    view["checked_at"] = str(broker.get("checked_at") or "not checked")
    return view

def command_status_overview(
    *,
    broker: Mapping[str, object],
    data_load_status: Mapping[str, object],
    data_refresh: Mapping[str, object],
    full_live_readiness: Mapping[str, object],
    operational_readiness: Mapping[str, object],
    provider_readiness: Mapping[str, object],
    review_progress: Mapping[str, object] | None = None,
    scheduler: Mapping[str, object],
) -> dict[str, object]:
    trade_pull = _optional_mapping(data_refresh, "trade_pull")
    tradable_ready = full_live_readiness.get("tradable_ready") is True
    review_operational = full_live_readiness.get("review_operational_ready") is True
    data_blockers = _optional_int(data_load_status, "blocker_count")
    data_warnings = _optional_int(data_load_status, "warning_count")
    refresh_status = str(data_refresh.get("status_label") or "Idle")
    refresh_eta = str(data_refresh.get("eta_label") or "not available")
    rows = [
        _status_overview_row(
            "status-server",
            "Dashboard response",
            "Rendered",
            "pass",
            "FastAPI rendered this command dashboard and loaded runtime readers for this request.",
        ),
        _status_overview_row(
            "status-live-runtime",
            "Live Runtime",
            str(full_live_readiness.get("status_label") or "Unknown"),
            str(full_live_readiness.get("status_class") or "neutral"),
            str(full_live_readiness.get("detail") or "No full-live readiness detail."),
        ),
        _status_overview_row(
            "status-broker",
            "Broker",
            str(broker.get("status_label") or "Broker Unknown"),
            str(broker.get("status_class") or "neutral"),
            f"{broker.get('mode_label', 'Unknown')} mode. {broker.get('detail', '')}".strip(),
        ),
        _status_overview_row(
            "status-data-readiness",
            "Data Readiness",
            str(data_load_status.get("status_label") or "Unknown"),
            str(data_load_status.get("status_class") or "neutral"),
            (
                f"{data_load_status.get('overall_percent', 0)}% ready; "
                f"{data_load_status.get('blocker_count', 0)} blocker(s), "
                f"{data_load_status.get('warning_count', 0)} warning(s)."
            ),
        ),
        _status_overview_row(
            "status-review-operational",
            "Review Operational",
            "Ready" if review_operational else "Blocked",
            "pass" if review_operational else "block",
            (
                str(full_live_readiness.get("detail") or "")
                if review_operational
                else str(operational_readiness.get("status_label") or "Review readiness is blocked.")
            ),
        ),
        _status_overview_row(
            "status-tradable-ready",
            "Tradable Ready",
            "Ready" if tradable_ready else "Gated",
            "pass" if tradable_ready else "warn",
            (
                "Paper order submission can proceed after review and risk checks."
                if tradable_ready
                else "Review can continue, but order submission remains gated."
            ),
        ),
        _status_overview_row(
            "status-scheduler",
            "Scheduler",
            str(scheduler.get("status_label") or "Unknown"),
            str(scheduler.get("status_class") or "neutral"),
            str(scheduler.get("tradability_detail") or "No scheduler detail available."),
        ),
        _status_overview_row(
            "status-provider-config",
            "Provider Connections",
            str(provider_readiness.get("status_label") or "Unknown"),
            str(provider_readiness.get("status_class") or "neutral"),
            (
                f"{provider_readiness.get('configured_count', 0)}/"
                f"{provider_readiness.get('provider_count', 0)} providers configured."
            ),
        ),
    ]
    return {
        "rows": rows,
        "process_rows": _system_process_rows(
            broker=broker,
            data_load_status=data_load_status,
            data_refresh=data_refresh,
            full_live_readiness=full_live_readiness,
            operational_readiness=operational_readiness,
            provider_readiness=provider_readiness,
            review_progress=review_progress or {},
            scheduler=scheduler,
        ),
        "issue_summary": {
            "blocker_count": data_blockers,
            "warning_count": data_warnings,
            "status_class": "block" if data_blockers else "warn" if data_warnings else "pass",
            "refresh_label": f"{refresh_status}: {refresh_eta} ETA"
            if refresh_eta not in {"", "not available"}
            else refresh_status,
            "tooltip": (
                "Hard blockers stop review or operation. Execution gates can allow "
                "review while blocking paper-order submission. Warnings require review "
                "but may still allow candidate analysis."
            ),
        },
        "trade_pull": {
            "status_label": _trade_pull_display_status(trade_pull),
            "status_class": str(trade_pull.get("status_class") or "neutral"),
            "percent_complete": _optional_int(trade_pull, "percent_complete"),
            "progress_style": f"width: {_optional_int(trade_pull, 'percent_complete')}%",
            "eta_label": _trade_pull_eta_label(trade_pull, data_refresh),
            "freshness_label": _format_timestamp_or_text(trade_pull.get("latest_as_of")),
            "updated_at": _format_timestamp_or_text(trade_pull.get("updated_at")),
            "detail": _humanize_seconds_in_text(
                str(
                    trade_pull.get("detail")
                    or "No Massive stock-trades pull status is available yet."
                )
            ),
            "ticker_progress_label": str(
                trade_pull.get("coverage_scope_label")
                or trade_pull.get("ticker_progress_label")
                or "not tracked"
            ),
            "row_count_label": str(trade_pull.get("row_count_label") or "0"),
            "tooltip": _trade_pull_tooltip(trade_pull),
        },
    }


def _trade_pull_display_status(trade_pull: Mapping[str, object]) -> str:
    state = str(trade_pull.get("state") or "").casefold()
    status_class = str(trade_pull.get("status_class") or "").casefold()
    if state == "ready" or status_class == "pass":
        return "Usable for live review"
    return str(trade_pull.get("status_label") or "No Pull")


def _trade_pull_eta_label(
    trade_pull: Mapping[str, object],
    data_refresh: Mapping[str, object],
) -> str:
    if trade_pull.get("is_running") is True or str(trade_pull.get("state") or "") == "running":
        return str(data_refresh.get("eta_label") or trade_pull.get("eta_label") or "not available")
    return "not running"


def _trade_pull_tooltip(trade_pull: Mapping[str, object]) -> str:
    return _humanize_seconds_in_text(
        "Usable means latest-slice market-flow signals can run for covered tickers. "
        "Partial means the full-depth historical trade tape may still be incomplete. "
        f"Scope: {trade_pull.get('coverage_scope_label') or trade_pull.get('ticker_progress_label') or 'not tracked'}. "
        f"Freshness: {trade_pull.get('latest_as_of') or 'not recorded'}."
    )

def _system_process_rows(
    *,
    broker: Mapping[str, object],
    data_load_status: Mapping[str, object],
    data_refresh: Mapping[str, object],
    full_live_readiness: Mapping[str, object],
    operational_readiness: Mapping[str, object],
    provider_readiness: Mapping[str, object],
    review_progress: Mapping[str, object],
    scheduler: Mapping[str, object],
) -> list[dict[str, str]]:
    dataset_rows = _mapping_list_field_or_empty(data_load_status, "dataset_rows")
    lane_rows = _mapping_list_field_or_empty(data_load_status, "lane_rows")
    trade_pull = _optional_mapping(data_refresh, "trade_pull")
    scheduler_counts = _optional_mapping(_optional_mapping(scheduler, "summary"), "counts")
    massive_orchestrator = _optional_mapping(scheduler, "massive_orchestrator")
    repair = _optional_mapping(scheduler, "repair")
    freshness_checks = _mapping_list_field_or_empty(scheduler, "freshness_checks")
    full_live_coverage = _optional_mapping(full_live_readiness, "coverage")
    full_live_active_refresh = _optional_mapping(full_live_readiness, "active_refresh")
    health_monitor = _optional_mapping(data_load_status, "health_monitor")
    broker_status = str(broker.get("status_label") or "Broker Unknown")
    broker_class = str(broker.get("status_class") or "neutral")
    return [
        _process_row(
            "process-server",
            "Dashboard response",
            "Rendered",
            "pass",
            "Serving pages",
            "now",
            "live response",
            str(data_load_status.get("status_checked_at") or "not checked"),
            "FastAPI rendered the command page and loaded the runtime readers for this request.",
            "Use the health, lane, and readiness rows below to decide whether the agency can trade.",
        ),
        _process_row(
            "process-health-monitor",
            "Health monitor and source-health reader",
            str(health_monitor.get("status_label") or "Not Checked"),
            str(health_monitor.get("status_class") or "block"),
            f"{health_monitor.get('row_count', 0)} source-health row(s)",
            "live query",
            str(health_monitor.get("latest_checked_at") or "not checked"),
            str(health_monitor.get("latest_checked_at") or "not checked"),
            str(health_monitor.get("detail") or "Source-health reliability was not verified."),
            _health_monitor_action(health_monitor),
        ),
        _process_row(
            "process-scheduler",
            "Scheduler and ticker tiers",
            str(scheduler.get("status_label") or "Unknown"),
            str(scheduler.get("status_class") or "neutral"),
            (
                f"{scheduler_counts.get('running', 0)} running; "
                f"{scheduler_counts.get('due_now', 0)} due now"
            ),
            _next_job_eta(scheduler),
            str(scheduler.get("market_phase") or "market phase unknown"),
            str(scheduler.get("generated_at") or "not recorded"),
            str(scheduler.get("tradability_detail") or "Scheduler detail is unavailable."),
            _scheduler_action(scheduler),
        ),
        _process_row(
            "process-massive-orchestrator",
            "Massive multi-lane orchestrator",
            str(massive_orchestrator.get("status_label") or "Unknown"),
            str(massive_orchestrator.get("status_class") or "neutral"),
            (
                f"{massive_orchestrator.get('running_count', 0)} running; "
                f"{massive_orchestrator.get('due_now_count', 0)} due; "
                f"{massive_orchestrator.get('blocked_count', 0)} blocked"
            ),
            _massive_orchestrator_eta(massive_orchestrator),
            str(massive_orchestrator.get("market_phase") or "market phase unknown"),
            str(massive_orchestrator.get("generated_at") or "not recorded"),
            str(
                massive_orchestrator.get("detail")
                or "Massive lane orchestration detail is unavailable."
            ),
            _massive_orchestrator_action(massive_orchestrator),
        ),
        _process_row(
            "process-refresh",
            "Data refresh worker",
            str(data_refresh.get("status_label") or "Idle"),
            str(data_refresh.get("status_class") or "neutral"),
            (
                f"{data_refresh.get('percent_complete', 0)}%; "
                f"{data_refresh.get('completed_jobs', 0)}/{data_refresh.get('total_jobs', 0)} jobs"
            ),
            str(data_refresh.get("eta_label") or "not available"),
            str(data_refresh.get("current_dataset") or "none running"),
            str(data_refresh.get("updated_at") or "not recorded"),
            str(data_refresh.get("detail") or "No refresh detail available."),
            _refresh_action(data_refresh),
        ),
        _process_row(
            "process-massive-live",
            "Massive live trade slices",
            str(trade_pull.get("status_label") or "No Pull"),
            str(trade_pull.get("status_class") or "neutral"),
            (
                f"{trade_pull.get('percent_complete', 0)}%; "
                f"{trade_pull.get('pipeline_usable_label') or trade_pull.get('ticker_progress_label') or 'no ticker progress'}"
            ),
            str(data_refresh.get("eta_label") or "not available"),
            str(trade_pull.get("latest_as_of") or "not recorded"),
            str(trade_pull.get("updated_at") or "not recorded"),
            str(trade_pull.get("detail") or "Massive live trade-pull detail is unavailable."),
            _trade_pull_action(trade_pull),
        ),
        _process_row(
            "process-massive-repair",
            "Massive full-depth repair and backtest tape",
            str(repair.get("status_label") or "Unknown"),
            str(repair.get("status_class") or "neutral"),
            f"{repair.get('job_count', 0)} repair job(s)",
            "off-hours" if repair.get("state") == "deferred" else "now",
            str(repair.get("market_phase") or "market phase unknown"),
            str(repair.get("generated_at") or "not recorded"),
            str(repair.get("detail") or "No baseline-repair detail available."),
            "Let this run in quiet-market windows; live latest slices can keep review moving.",
        ),
        _process_row_for_rows(
            "process-prices-technical",
            "Daily bars and technical-analysis workers",
            [*_select_rows(dataset_rows, "dataset", {"prices_daily"}), *_select_rows(lane_rows, "lane", {"abnormal_volume", "technical_analysis", "sector_momentum"})],
            "Daily price, abnormal volume, technical setup, and sector context used by the signal dashboards.",
        ),
        _process_row_for_rows(
            "process-market-flow",
            "Market-flow trade workers",
            [*_select_rows(dataset_rows, "dataset", {"stock_trades"}), *_select_rows(lane_rows, "lane", {"buy_sell_pressure", "block_trade_pressure", "unusual_trade_activity", "pre_market_unusual_activity", "market_flow_trend"})],
            "Massive trade prints feed buy/sell pressure, blocks, unusual trades, pre-market activity, and market-flow trend.",
        ),
        _process_row_for_rows(
            "process-sec-filings",
            "SEC and filing workers",
            [*_select_rows(dataset_rows, "dataset", {"sec_company_facts", "sec_form4", "sec_13f"}), *_select_rows(lane_rows, "lane", {"fundamentals", "insider", "institutional"})],
            "SEC company facts, insider Form 4, and 13F evidence supply slower-moving confirmation lanes.",
        ),
        _process_row_for_rows(
            "process-news",
            "RSS/news worker",
            [*_select_rows(dataset_rows, "dataset", {"news_rss"}), *_select_rows(lane_rows, "lane", {"news"})],
            "Headline/news rows add current context and can trigger affected-ticker mini cycles.",
        ),
        _process_row_for_rows(
            "process-email",
            "Subscription email and article-analysis worker",
            [*_select_rows(dataset_rows, "dataset", {"subscription_emails"}), *_select_rows(lane_rows, "lane", {"subscription_thesis"})],
            "Mailbox alerts, opened article links, and LLM article theses provide paid-source context.",
        ),
        _process_row(
            "process-selection-llm",
            "Runtime selection and LLM reviewer",
            str(full_live_readiness.get("status_label") or "Unknown"),
            str(full_live_readiness.get("status_class") or "neutral"),
            (
                f"{full_live_coverage.get('signal_count', data_load_status.get('signal_count', 0))} signals; "
                f"{full_live_coverage.get('evidence_pack_count', data_load_status.get('evidence_pack_count', 0))} evidence packs"
            ),
            str(full_live_active_refresh.get("eta_label", "not available")),
            "latest cycle",
            str(data_load_status.get("generated_at") or "not recorded"),
            str(full_live_readiness.get("detail") or "Selection/LLM readiness detail is unavailable."),
            "Review final-selection rows by conviction; LLM output is visible in selection and candidate detail.",
        ),
        _process_row(
            "process-risk-portfolio",
            "Risk engine and portfolio policy",
            str(operational_readiness.get("status_label") or "Unknown"),
            str(operational_readiness.get("status_class") or "neutral"),
            (
                f"{operational_readiness.get('blocker_count', 0)} blockers; "
                f"{operational_readiness.get('warning_count', 0)} warnings"
            ),
            "per review cycle",
            "policy and broker snapshot",
            str(operational_readiness.get("generated_at") or broker.get("checked_at") or "not recorded"),
            str(operational_readiness.get("detail") or "Risk and portfolio policy gate detail is unavailable."),
            "Open Risk, then Execution Preview for rows that are ALLOW and orderable.",
        ),
        _process_row(
            "process-broker",
            "Alpaca paper broker and portfolio monitor",
            broker_status,
            broker_class,
            (
                f"{len(_list_or_empty(broker.get('positions')))} positions; "
                f"{len(_list_or_empty(broker.get('orders')))} open orders"
            ),
            "broker read <1m for execution",
            str(broker.get("checked_at") or "not checked"),
            str(broker.get("checked_at") or "not checked"),
            str(broker.get("detail") or "Broker detail is unavailable."),
            "If this is not connected, execution stays local and cannot submit paper orders.",
        ),
        _process_row(
            "process-human-review",
            "Human review and order approval queue",
            str(review_progress.get("status_label") or "Unknown"),
            str(review_progress.get("status_class") or "neutral"),
            (
                f"{review_progress.get('reviewed_label', '0/0')} reviewed; "
                f"{review_progress.get('pending_count', 0)} pending"
            ),
            "user-driven",
            "latest cycle",
            str(data_load_status.get("generated_at") or "not recorded"),
            str(review_progress.get("detail") or "Review queue detail is unavailable."),
            "Approve, defer, or reject research first; orderable rows need a separate order approval.",
        ),
        _process_row(
            "process-execution",
            "Execution freshness and paper-order gate",
            _freshness_gate_status_label(freshness_checks),
            _freshness_gate_status_class(freshness_checks),
            f"{len(freshness_checks)} freshness check(s)",
            "before submit",
            _freshness_gate_freshness_label(freshness_checks),
            str(broker.get("checked_at") or "not checked"),
            _freshness_gate_detail(freshness_checks),
            "Submit only READY rows with broker, critical data, risk, and order approval all open.",
        ),
        _process_row(
            "process-provider",
            "Provider keys and quotas",
            str(provider_readiness.get("status_label") or "Unknown"),
            str(provider_readiness.get("status_class") or "neutral"),
            (
                f"{provider_readiness.get('configured_count', 0)}/"
                f"{provider_readiness.get('provider_count', 0)} configured"
            ),
            "continuous",
            "env/local config",
            str(provider_readiness.get("generated_at") or "not recorded"),
            "Provider readiness checks credentials without displaying secret values.",
            "Fix missing required providers before running live cycles.",
        ),
    ]

def _process_row(
    row_id: str,
    process: str,
    status_label: str,
    status_class: str,
    progress_label: str,
    eta_label: str,
    freshness_label: str,
    last_update: str,
    detail: str,
    action: str,
) -> dict[str, str]:
    return {
        "id": row_id,
        "process": process,
        "status_label": _process_status_label(status_label),
        "status_class": status_class,
        "progress_label": progress_label,
        "eta_label": eta_label,
        "freshness_label": _compact_timestamp_label(freshness_label),
        "last_update": _compact_timestamp_label(last_update),
        "detail": _humanize_seconds_in_text(detail),
        "action": action,
        "tooltip": _humanize_seconds_in_text(
            f"{process}: {detail} Action: {action}"
        ),
    }

_SECONDS_TOKEN_RE = re.compile(r"\b(\d{3,})s\b")
_ISO_TIMESTAMP_TOKEN_RE = re.compile(
    r"(?<!\d)\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})(?!\d)"
)

def _humanize_seconds_in_text(value: str) -> str:
    with_durations = _SECONDS_TOKEN_RE.sub(
        lambda match: _duration_label(int(match.group(1))),
        value,
    )
    return _ISO_TIMESTAMP_TOKEN_RE.sub(
        lambda match: _format_timestamp_or_text(match.group(0), default=match.group(0)),
        with_durations,
    )

def _duration_label(seconds: int) -> str:
    if seconds >= 86_400:
        days, remainder = divmod(seconds, 86_400)
        hours = remainder // 3_600
        return f"{days}d {hours}h" if hours else f"{days}d"
    if seconds >= 3_600:
        hours, remainder = divmod(seconds, 3_600)
        minutes = remainder // 60
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if seconds >= 60:
        minutes, remainder = divmod(seconds, 60)
        return f"{minutes}m {remainder}s" if remainder else f"{minutes}m"
    return f"{seconds}s"

def _process_status_label(value: str) -> str:
    text = str(value or "").strip()
    normalized = text.casefold()
    replacements = {
        "operational": "Healthy",
        "complete": "Complete",
        "completed": "Complete",
        "attention": "Needs Review",
        "operational with attention": "Needs Review",
        "ready with partial lanes": "Partial",
        "context only": "Context",
        "broker connected": "Connected",
        "provider keys ready": "Keys Ready",
        "not verified": "Not Checked",
        "health monitor fallback": "Unavailable",
        "health monitor unavailable": "Unavailable",
        "health monitor stale": "Needs Refresh",
        "health monitor missing": "Missing",
        "health monitor unverified": "Unverified",
        "live health monitor": "Live",
        "cached health snapshot": "Cached",
    }
    return replacements.get(normalized, text or "Unknown")

def _compact_timestamp_label(value: str) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "not recorded", "not checked"}:
        return text or "not recorded"
    return _format_timestamp_or_text(text, default=text)

def _process_row_for_rows(
    row_id: str,
    process: str,
    rows: Sequence[Mapping[str, object]],
    default_detail: str,
) -> dict[str, str]:
    status_class = _combined_status_class(rows)
    return _process_row(
        row_id,
        process,
        _combined_status_label(status_class),
        status_class,
        _combined_progress_label(rows),
        "on cadence",
        _combined_freshness_label(rows),
        _combined_last_update(rows),
        _combined_detail(rows, default_detail),
        _combined_action(status_class),
    )

def _select_rows(
    rows: Sequence[Mapping[str, object]],
    key: str,
    values: set[str],
) -> list[Mapping[str, object]]:
    return [row for row in rows if str(row.get(key) or "") in values]

def _combined_status_class(rows: Sequence[Mapping[str, object]]) -> str:
    classes = {str(row.get("status_class") or "neutral") for row in rows}
    if "block" in classes:
        return "block"
    if "warn" in classes:
        return "warn"
    if "pass" in classes:
        return "pass"
    return "neutral"

def _combined_status_label(status_class: str) -> str:
    return {
        "pass": "Operational",
        "warn": "Attention",
        "block": "Blocked",
        "neutral": "Not Verified",
    }.get(status_class, "Not Verified")

def _combined_progress_label(rows: Sequence[Mapping[str, object]]) -> str:
    if not rows:
        return "not configured"
    ready = sum(1 for row in rows if str(row.get("status_class") or "") == "pass")
    total = len(rows)
    coverage_values = [
        _optional_int(row, "coverage_pct")
        for row in rows
        if "coverage_pct" in row
    ]
    average = round(sum(coverage_values) / len(coverage_values)) if coverage_values else 0
    return f"{ready}/{total} healthy; {average}% avg coverage"

def _combined_freshness_label(rows: Sequence[Mapping[str, object]]) -> str:
    values = [
        str(row.get("source_freshness") or row.get("freshness") or "")
        for row in rows
        if str(row.get("source_freshness") or row.get("freshness") or "")
    ]
    if not values:
        return "not checked"
    unique = sorted(set(values))
    if len(unique) == 1:
        return unique[0]
    return ", ".join(unique[:3])

def _combined_last_update(rows: Sequence[Mapping[str, object]]) -> str:
    candidates = [
        str(row.get("source_last_success_at") or row.get("max_as_of") or "")
        for row in rows
        if str(row.get("source_last_success_at") or row.get("max_as_of") or "")
    ]
    return max(candidates) if candidates else "not recorded"

def _combined_detail(rows: Sequence[Mapping[str, object]], default_detail: str) -> str:
    for status_class in ("block", "warn"):
        for row in rows:
            if str(row.get("status_class") or "") == status_class:
                return str(row.get("detail") or default_detail)
    return default_detail

def _combined_action(status_class: str) -> str:
    if status_class == "pass":
        return "Use normally in review and candidate scoring."
    if status_class == "warn":
        return "Use for review, but inspect the data-health detail before acting."
    if status_class == "block":
        return "Refresh this lane before relying on it for execution."
    return "Run the relevant refresh or runtime cycle to verify this lane."

def _next_job_eta(scheduler: Mapping[str, object]) -> str:
    for row in _mapping_list_field_or_empty(scheduler, "next_job_rows"):
        eta = str(row.get("eta_label") or "")
        if eta:
            return eta
    return "no due job"

def _scheduler_action(scheduler: Mapping[str, object]) -> str:
    status_class = str(scheduler.get("status_class") or "neutral")
    if status_class == "pass":
        return "Scheduler does not block paper-order readiness."
    if status_class == "warn":
        return "Run due jobs or inspect datasets that need refresh before paper submission."
    return "Fix scheduler or freshness blockers before using execution."

def _massive_orchestrator_eta(orchestrator: Mapping[str, object]) -> str:
    for row in _mapping_list_field_or_empty(orchestrator, "lanes"):
        if str(row.get("status") or "") in {"RUNNING", "DUE_NOW"}:
            return str(row.get("eta_label") or "not available")
    return "no due lane"

def _massive_orchestrator_action(orchestrator: Mapping[str, object]) -> str:
    status_class = str(orchestrator.get("status_class") or "neutral")
    if status_class == "pass":
        return "Use Massive-backed lanes normally in review and paper-gate checks."
    if status_class == "warn":
        return "Run due Massive lanes in priority order; live lanes take precedence over repair."
    if status_class == "block":
        return "Fix Massive credentials or source-health before relying on market-flow evidence."
    return "Run the scheduler status check to verify Massive lane readiness."

def _refresh_action(data_refresh: Mapping[str, object]) -> str:
    state = str(data_refresh.get("state") or "idle")
    if state == "running":
        return "Wait for the active refresh, then verify data health again."
    if state in {"failed", "blocked", "stale"}:
        return "Open logs, fix the failed source, and rerun the refresh."
    return "Rerun only when a source falls outside policy or the scheduler marks it due."

def _trade_pull_action(trade_pull: Mapping[str, object]) -> str:
    status_class = str(trade_pull.get("status_class") or "neutral")
    if status_class == "pass":
        return "Use market-flow signals normally."
    if status_class == "warn":
        return "Use latest-slice signals; let full-depth repair finish for research/backtests."
    return "Repair Massive trade coverage before relying on market-flow signals."

def _health_monitor_action(health_monitor: Mapping[str, object]) -> str:
    if str(health_monitor.get("status_class") or "") == "pass":
        return "Health badges can be used; still follow each lane's freshness gate."
    if str(health_monitor.get("status_class") or "") == "warn":
        return "Use as review context only until the live source-health reader is available."
    return "Do not rely on dashboard health badges for execution until monitoring refreshes."

def _freshness_gate_status_label(checks: Sequence[Mapping[str, object]]) -> str:
    status_class = _freshness_gate_status_class(checks)
    return {"pass": "Fresh", "warn": "Review Freshness", "block": "Blocked"}.get(
        status_class,
        "Not Checked",
    )

def _freshness_gate_status_class(checks: Sequence[Mapping[str, object]]) -> str:
    statuses = {str(check.get("status_class") or "neutral") for check in checks}
    if "block" in statuses:
        return "block"
    if "warn" in statuses:
        return "warn"
    if "pass" in statuses:
        return "pass"
    return "neutral"

def _freshness_gate_freshness_label(checks: Sequence[Mapping[str, object]]) -> str:
    if not checks:
        return "not checked"
    return f"{sum(1 for check in checks if check.get('status_class') == 'pass')}/{len(checks)} pass"

def _freshness_gate_detail(checks: Sequence[Mapping[str, object]]) -> str:
    for status_class in ("block", "warn"):
        for check in checks:
            if str(check.get("status_class") or "") == status_class:
                return str(check.get("detail") or "Freshness check needs attention.")
    if checks:
        return "Broker state and critical evidence freshness checks are passing."
    return "Execution freshness checks are not loaded yet."

def _mapping_list_field_or_empty(
    payload: Mapping[str, object],
    key: str,
) -> list[Mapping[str, object]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [
        cast(Mapping[str, object], item)
        for item in value
        if isinstance(item, Mapping)
    ]

def _list_or_empty(value: object) -> list[object]:
    return value if isinstance(value, list) else []

def _bounded_percent(row: Mapping[str, object], key: str) -> int:
    return max(0, min(100, _int_field(row, key)))

def _status_overview_row(
    row_id: str,
    label: str,
    value: str,
    status_class: str,
    detail: str,
) -> dict[str, str]:
    return {
        "id": row_id,
        "label": label,
        "value": value,
        "status_class": status_class,
        "detail": _humanize_seconds_in_text(detail or "No detail available."),
    }

def data_load_status_view(status: Mapping[str, object]) -> dict[str, object]:
    view = cast(dict[str, object], _humanize_nested(dict(status)))
    view["detail"] = _operator_text(status.get("detail") or "")
    if isinstance(view.get("health_monitor"), dict):
        monitor = cast(dict[str, object], view["health_monitor"])
        monitor["status_label"] = _operator_text(monitor.get("status_label") or "not verified")
        monitor["detail"] = _operator_text(monitor.get("detail") or "")
    view["as_of_label"] = _format_timestamp_or_text(status.get("as_of"))
    view["generated_at_label"] = _format_timestamp_or_text(status.get("generated_at"))
    view["status_checked_at_label"] = _format_timestamp_or_text(
        status.get("status_checked_at"),
        default="not checked",
    )
    view["progress_style"] = f"width: {_bounded_percent(status, 'overall_percent')}%"
    view["source_summary"] = dict(_optional_mapping(status, "source_summary"))
    view["dataset_summary"] = dict(_optional_mapping(status, "dataset_summary"))
    view["agent_summary"] = dict(_optional_mapping(status, "agent_summary"))
    view["dataset_rows"] = [
        _data_load_row(cast(Mapping[str, object], row))
        for row in _list_field(status, "datasets")
    ]
    view["lane_rows"] = [
        _data_load_row(cast(Mapping[str, object], row))
        for row in _list_field(status, "lanes")
    ]
    view["lane_state_rows"] = [
        _lane_state_row(cast(Mapping[str, object], row))
        for row in _list_field_or_empty(status, "lane_states")
    ]
    view["issue_rows"] = [
        _data_load_issue(cast(Mapping[str, object], row), fallback_status_class="block")
        for row in _list_field(status, "blockers")
    ] + [
        _data_load_issue(cast(Mapping[str, object], row), fallback_status_class="warn")
        for row in _list_field(status, "warnings")
    ]
    freshness_rows = [
        _freshness_status_row(cast(Mapping[str, object], row))
        for row in _list_field_or_empty(status, "freshness_rows")
    ]
    view["freshness_rows"] = freshness_rows
    source_kpi = _source_health_kpi(freshness_rows)
    view["source_health_kpi"] = source_kpi
    view["runtime_coverage_label"] = (
        f"{view.get('overall_percent', 0)}% loaded · "
        f"{view.get('expected_ticker_count', 0)} tickers · "
        f"{view.get('signal_count', 0)} signals"
    )
    view["runtime_coverage_detail"] = (
        f"{view.get('mode_label', 'Runtime')} · {source_kpi['short_detail']}"
    )
    view["runtime_coverage_tooltip"] = (
        "Runtime coverage measures datasets and signal outputs loaded for the latest "
        "cycle. It is not the same as paper-trading permission; execution still needs "
        "freshness, broker, risk, and order-approval gates."
    )
    return view


def _source_health_kpi(rows: Sequence[Mapping[str, object]]) -> dict[str, str]:
    blocked = needs_refresh = partial = check_needs_refresh = verified = 0
    context_refresh = 0
    for row in rows:
        status_class = str(row.get("status_class") or "")
        status = str(row.get("status") or "").upper()
        freshness = str(row.get("freshness") or "").upper()
        detail = str(row.get("detail") or "").lower()
        impact = _source_impact_label(row)
        if status_class == "pass":
            verified += 1
        elif "source-health row is" in detail or "older than" in detail:
            check_needs_refresh += 1
        elif freshness == "PARTIAL" or status == "DEGRADED":
            partial += 1
        elif freshness == "STALE" or status == "STALE":
            needs_refresh += 1
        elif status_class == "block":
            blocked += 1
        else:
            partial += 1
        if impact == "Current-context" and (
            status_class in {"warn", "block"} or freshness == "STALE" or status == "STALE"
        ):
            context_refresh += 1
    total = len(rows)
    action_detail = _source_health_action_detail(
        blocked=blocked,
        stale=needs_refresh,
        partial=partial,
        check_stale=check_needs_refresh,
        context_refresh=context_refresh,
    )
    return {
        "label": f"{total} monitored",
        "detail": (
            f"{blocked} unavailable/blocked · {needs_refresh} need refresh · "
            f"{partial} partial · {check_needs_refresh} health-proof refresh"
        ),
        "short_detail": (
            "data source unavailable"
            if blocked
            else "health proof needs refresh"
            if check_needs_refresh
            else f"{verified}/{total} verified current"
        ),
        "action_detail": action_detail,
        "tooltip": (
            "Source Health buckets: unavailable/blocked cannot be used; data needing "
            "refresh is outside policy; partial usable can support review with warnings; "
            "health-proof refresh means the data may be valid but monitor proof must "
            "refresh; verified current passes."
        ),
    }

def full_live_readiness_view(readiness: Mapping[str, object]) -> dict[str, object]:
    view = cast(dict[str, object], _humanize_nested(dict(readiness)))
    coverage = _mapping_field(readiness, "coverage")
    active_refresh = _mapping_field(readiness, "active_refresh")
    view["detail"] = _operator_text(readiness.get("detail") or "")
    view["coverage"] = cast(dict[str, object], _humanize_nested(dict(coverage)))
    view["active_refresh"] = cast(dict[str, object], _humanize_nested(dict(active_refresh)))
    view["mode_label"] = _agency_mode_label(readiness)
    view["trading_gate_label"] = _trading_gate_label(readiness)
    view["mode_summary"] = f"{view['mode_label']} · {view['trading_gate_label']}"
    view["mode_tooltip"] = _agency_mode_tooltip(readiness, coverage)
    view["blocking_reason_label"] = _humanize_seconds_in_text(_full_live_blocking_reason(readiness))
    view["progress_style"] = f"width: {_bounded_percent(coverage, 'overall_percent')}%"
    command_rows = _full_live_command_rows(readiness)
    view["command_rows"] = command_rows
    view["command_map"] = {str(row["id"]): row for row in command_rows}
    view["provider_usage_rows"] = [
        _humanized_mapping(cast(Mapping[str, object], row), fields=("detail",))
        for row in _list_field(readiness, "provider_usage")
    ]
    view["issue_rows"] = [
        _data_load_issue(cast(Mapping[str, object], row), fallback_status_class="block")
        for row in _list_field(readiness, "blockers")
    ] + [
        _data_load_issue(cast(Mapping[str, object], row), fallback_status_class="warn")
        for row in _list_field(readiness, "warnings")
    ]
    view["next_action_rows"] = [
        _operator_text(row) for row in _list_field(readiness, "next_actions")
    ]
    view["refresh_job_rows"] = [
        cast(Mapping[str, object], _humanize_nested(row))
        for row in _mapping_list_field(active_refresh, "dataset_rows")[:8]
    ]
    view["blocker_count"] = _optional_int(readiness, "blocker_count") or len(
        _list_field(readiness, "blockers")
    )
    view["warning_count"] = _optional_int(readiness, "warning_count") or len(
        _list_field(readiness, "warnings")
    )
    return view

def _humanized_mapping(
    row: Mapping[str, object],
    *,
    fields: Sequence[str],
) -> dict[str, object]:
    view = dict(row)
    for field in fields:
        if field in view:
            view[field] = _operator_text(view[field])
    return view

def _humanize_nested(value: object) -> object:
    if isinstance(value, str):
        return _operator_text(value)
    if isinstance(value, Mapping):
        return {key: _humanize_nested(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_humanize_nested(item) for item in value]
    return value

def scheduler_work_queue_view(status: Mapping[str, object]) -> dict[str, object]:
    view = cast(dict[str, object], _humanize_nested(dict(status)))
    summary = _mapping_field(view, "summary")
    ticker_tiers = _mapping_field(view, "ticker_tiers")
    tiers = _mapping_field(ticker_tiers, "tiers")
    tradability = _mapping_field(view, "tradability")
    repair = _mapping_field(view, "repair_plan")
    gate = _mapping_field(view, "execution_freshness_gate")
    scheduler_runtime = _mapping_field(view, "scheduler_runtime")
    massive_orchestrator = _mapping_field(view, "massive_orchestrator")
    view["headline"] = str(summary["headline"])
    view["status_label"] = str(tradability["status_label"])
    view["status_class"] = str(tradability["status_class"])
    view["tradability_detail"] = str(tradability["detail"])
    view["runtime"] = scheduler_runtime
    view["job_rows"] = _mapping_list_field(view, "jobs")[:10]
    view["next_job_rows"] = _mapping_list_field(view, "next_jobs")
    view["stale_rows"] = [
        _scheduler_dataset_review_row(row)
        for row in _mapping_list_field(view, "stale_datasets")[:8]
    ]
    raw_massive_lane_rows = _mapping_list_field(massive_orchestrator, "lanes")
    massive_lane_rows = _massive_lane_view_rows(raw_massive_lane_rows)
    raw_massive_signal_rows = _mapping_list_field(
        massive_orchestrator,
        "derived_signal_lanes",
    )
    massive_signal_rows = _massive_signal_view_rows(
        raw_massive_signal_rows,
        massive_lane_rows,
    )
    massive_view = dict(massive_orchestrator)
    massive_view["lanes"] = massive_lane_rows
    massive_view["raw_lanes"] = massive_lane_rows
    massive_view["derived_signal_lanes"] = massive_signal_rows
    massive_view["lane_summary"] = _massive_lane_summary(massive_lane_rows)
    view["massive_orchestrator"] = massive_view
    view["massive_lane_rows"] = massive_lane_rows
    view["massive_signal_rows"] = massive_signal_rows
    view["repair"] = repair
    view["repair_rows"] = _mapping_list_field(repair, "jobs")[:6]
    view["freshness_checks"] = _mapping_list_field(gate, "checks")
    repair_rows = _mapping_list_field(repair, "jobs")
    view["automation_status"] = _scheduler_automation_status(scheduler_runtime)
    view["trading_freshness_gate"] = _scheduler_trading_freshness_gate(tradability)
    view["refresh_workload"] = _scheduler_refresh_workload(
        jobs=_mapping_list_field(view, "jobs"),
        massive_lanes=massive_lane_rows,
        repair_rows=repair_rows,
    )
    view["tier_rows"] = [
        dict(_mapping_field(tiers, key))
        for key in ("T0", "T1", "T2", "T3")
        if key in tiers
    ]
    return view


def _scheduler_dataset_review_row(row: Mapping[str, object]) -> dict[str, object]:
    view = dict(row)
    dataset = str(view.get("dataset") or view.get("name") or "").strip()
    action = SCHEDULER_DATASET_REFRESH_ACTIONS.get(dataset, {})
    view["refresh_action_url"] = str(action.get("url") or "")
    view["refresh_button_label"] = str(action.get("label") or "Open scheduler")
    view["refresh_action_detail"] = str(
        action.get("detail")
        or "Open Command at the scheduler and use the lane policy controls."
    )
    view["refresh_enabled"] = bool(view["refresh_action_url"])
    return view


def _scheduler_automation_status(runtime: Mapping[str, object]) -> dict[str, object]:
    status_label = str(runtime.get("status_label") or "Unknown")
    status_class = str(runtime.get("status_class") or "neutral")
    detail = str(runtime.get("detail") or "Scheduler heartbeat has not been checked.")
    return {
        "label": "Automation Status",
        "status_label": status_label,
        "status_class": status_class,
        "detail": detail,
        "tooltip": (
            "Automation Status is based on the scheduler heartbeat, active command, "
            "and recent tick state. It answers whether automatic refresh is alive."
        ),
    }


def _scheduler_trading_freshness_gate(
    tradability: Mapping[str, object],
) -> dict[str, object]:
    status_label = str(tradability.get("status_label") or "Unknown")
    status_class = str(tradability.get("status_class") or "neutral")
    detail = str(tradability.get("detail") or "Trading freshness gate is not checked.")
    return {
        "label": "Trading Freshness Gate",
        "status_label": status_label,
        "status_class": status_class,
        "detail": detail,
        "tooltip": (
            "Trading Freshness Gate uses broker freshness and live-critical evidence "
            "freshness. It answers whether review or paper-order submission can proceed."
        ),
    }


def _scheduler_refresh_workload(
    *,
    jobs: Sequence[Mapping[str, object]],
    massive_lanes: Sequence[Mapping[str, object]],
    repair_rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    due_rows = [
        *[row for row in jobs if _scheduler_row_status(row) == "DUE_NOW"],
        *[row for row in massive_lanes if _scheduler_row_status(row) == "DUE_NOW"],
    ]
    live_critical_due = [
        row for row in due_rows if _scheduler_row_is_live_critical(row)
    ]
    support_due = [
        row for row in due_rows if not _scheduler_row_is_live_critical(row)
    ]
    repair_due = [
        row for row in repair_rows if _scheduler_row_status(row) == "DUE_NOW"
    ]
    running_count = sum(
        1
        for row in [*jobs, *massive_lanes, *repair_rows]
        if _scheduler_row_status(row) == "RUNNING"
    )
    next_live_eta_label = _first_eta_label(live_critical_due)
    status_label = _scheduler_workload_status_label(
        live_count=len(live_critical_due),
        support_count=len(support_due),
        repair_count=len(repair_due),
        running_count=running_count,
    )
    status_class = "warn" if live_critical_due else "pass"
    if not live_critical_due and (support_due or repair_due or running_count):
        status_class = "neutral"
    detail = (
        f"{len(live_critical_due)} live-critical due; "
        f"{len(support_due)} support due; "
        f"{len(repair_due)} repair due; "
        f"{running_count} running."
    )
    if next_live_eta_label != "not needed":
        detail = f"{detail} Next live-critical ETA: {next_live_eta_label}."
    return {
        "label": "Refresh Workload",
        "status_label": status_label,
        "status_class": status_class,
        "detail": detail,
        "live_critical_due_count": len(live_critical_due),
        "support_due_count": len(support_due),
        "repair_due_count": len(repair_due),
        "running_count": running_count,
        "next_live_eta_label": next_live_eta_label,
        "tooltip": (
            "Refresh Workload separates live-critical due jobs from support and repair jobs. "
            "Live-critical due jobs can block paper orders; support and repair jobs improve "
            "coverage without automatically blocking review."
        ),
    }


def _scheduler_row_status(row: Mapping[str, object]) -> str:
    return str(row.get("status") or "").upper()


def _scheduler_row_is_live_critical(row: Mapping[str, object]) -> bool:
    if row.get("blocks_execution") is True:
        return True
    dataset = str(row.get("dataset") or row.get("raw_source_dataset") or "")
    if dataset in LIVE_CRITICAL_SCHEDULER_DATASETS:
        return True
    signal_lane = str(row.get("signal_lane") or row.get("name") or "")
    return signal_lane in LIVE_CRITICAL_SCHEDULER_SIGNALS


def _first_eta_label(rows: Sequence[Mapping[str, object]]) -> str:
    for row in rows:
        eta = str(row.get("eta_label") or "").strip()
        if eta:
            return eta
    return "not needed"


def _scheduler_workload_status_label(
    *,
    live_count: int,
    support_count: int,
    repair_count: int,
    running_count: int,
) -> str:
    if live_count:
        return f"{live_count} live-critical due"
    if support_count or repair_count:
        return "Support/repair due"
    if running_count:
        return "Refresh running"
    return "Queue clear"


def _massive_lane_view_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [_massive_lane_view(row) for row in rows]


def _massive_lane_view(row: Mapping[str, object]) -> dict[str, object]:
    view = dict(row)
    status_label = _massive_lane_display_status_label(row)
    health_label = _massive_lane_display_health_label(row)
    impact_label, impact_detail = _massive_lane_impact(row)
    show_live_ticker_progress = _massive_lane_show_live_ticker_progress(row)
    coverage_label = _massive_lane_coverage_label(
        row,
        show_live_ticker_progress=show_live_ticker_progress,
    )
    bucket_label = _massive_lane_bucket_label(row, status_label=status_label)
    action_label = _massive_lane_action_label(row, status_label=status_label)
    refresh_control = _massive_lane_refresh_control(row)
    view.update(
        {
            "display_status_label": status_label,
            "display_status_class": _massive_display_status_class(status_label),
            "display_health_label": health_label,
            "display_health_class": _massive_display_health_class(health_label),
            "impact_label": impact_label,
            "impact_detail": impact_detail,
            "bucket_label": bucket_label,
            "action_label": action_label,
            "show_live_ticker_progress": show_live_ticker_progress,
            "coverage_label": coverage_label,
            "status_tooltip": _massive_lane_status_tooltip(row, status_label),
            "health_tooltip": _massive_lane_health_tooltip(row, health_label),
            "impact_tooltip": impact_detail,
            "coverage_tooltip": _massive_lane_coverage_tooltip(row, coverage_label),
            "budget_tooltip": _massive_lane_budget_tooltip(row),
            "action_tooltip": _massive_lane_action_tooltip(row, action_label),
            **refresh_control,
        }
    )
    return view


def _massive_signal_view_rows(
    signals: Sequence[Mapping[str, object]],
    lanes: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    lane_index = {str(row.get("lane_id") or row.get("name") or ""): row for row in lanes}
    return [_massive_signal_view(row, lane_index) for row in signals]


def _massive_signal_view(
    row: Mapping[str, object],
    lane_index: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    view = dict(row)
    required_lanes = [str(value) for value in _list_or_empty(row.get("requires_raw_lanes"))]
    required_rows = [lane_index[lane] for lane in required_lanes if lane in lane_index]
    is_execution_critical = any(lane.get("blocks_execution") is True for lane in required_rows)
    if is_execution_critical:
        impact_label = "Execution-critical signal"
        impact_detail = (
            "This signal depends on execution-critical Massive raw lanes; waiting or "
            "missing raw data blocks or weakens paper-trading evidence."
        )
    else:
        impact_label = "Context signal"
        impact_detail = (
            "This signal uses Massive context lanes. Missing data weakens context but "
            "does not by itself close paper-order execution."
        )
    missing_lanes = [lane for lane in required_lanes if lane not in lane_index]
    raw_status = str(row.get("status") or "UNKNOWN")
    view.update(
        {
            "impact_label": impact_label,
            "impact_detail": impact_detail,
            "missing_raw_lanes": missing_lanes,
            "requirement_summary": _massive_signal_requirement_summary(
                raw_status,
                required_lanes=required_lanes,
                missing_lanes=missing_lanes,
                is_execution_critical=is_execution_critical,
            ),
            "tooltip": (
                f"{impact_detail} Required raw lanes: "
                f"{', '.join(required_lanes) if required_lanes else 'none'}."
            ),
        }
    )
    return view


def _massive_lane_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    execution_ready = [
        row for row in rows if row.get("bucket_label") == "Execution-Critical Ready"
    ]
    execution_needs_refresh = [
        row
        for row in rows
        if row.get("bucket_label") == "Execution-Critical Needs Refresh"
    ]
    support_due = [
        row for row in rows if row.get("bucket_label") == "Support / Context Due"
    ]
    research_disabled = [
        row
        for row in rows
        if row.get("bucket_label") == "Research / Disabled / Not Entitled"
    ]
    return {
        "execution_ready_count": len(execution_ready),
        "execution_needs_refresh_count": len(execution_needs_refresh),
        "support_due_count": len(support_due),
        "research_disabled_count": len(research_disabled),
        "execution_ready_tooltip": (
            "Execution-critical lanes with enough local data loaded for their current "
            "window. Health proof may still require verification before paper orders."
        ),
        "execution_needs_refresh_tooltip": (
            "Execution-critical lanes that are due, running, waiting, or blocked. These "
            "can affect paper-trading evidence freshness."
        ),
        "support_due_tooltip": (
            "Non-execution lanes that improve context or source hygiene. These should "
            "not be confused with live-trading blockers."
        ),
        "research_disabled_tooltip": (
            "Research, repair, optional, disabled, or entitlement-dependent lanes. These "
            "are tracked separately so they do not look like live failures."
        ),
    }


def _massive_lane_display_status_label(row: Mapping[str, object]) -> str:
    status = _scheduler_row_status(row)
    lane_id = str(row.get("lane_id") or row.get("name") or "")
    manifest_status = str(row.get("manifest_status") or "").lower()
    manifest_coverage = _optional_int(row, "manifest_coverage_pct")
    if status == "READY_FROM_RAW":
        return "Ready From Live Slices"
    if status == "SKIPPED" and (
        manifest_status in {"complete", "partial_usable"} or manifest_coverage > 0
    ):
        return "Loaded / No Pull Needed"
    if status == "DUE_NOW":
        return "Refresh Due"
    if status == "RUNNING":
        return "Refreshing"
    if status == "DEFERRED":
        return "Scheduled Later"
    if status == "WAITING":
        return "Waiting For Raw Lane"
    if status == "BLOCKED":
        return "Blocked"
    if status == "DISABLED":
        if "options" in lane_id:
            return "Disabled / Entitlement Not Verified"
        if "backtest" in lane_id:
            return "Disabled / Research Lane"
        return "Disabled / Not Enabled"
    return status.replace("_", " ").title() if status else "Unknown"


def _massive_lane_display_health_label(row: Mapping[str, object]) -> str:
    freshness = str(row.get("health_freshness") or "").upper()
    health_status = str(row.get("health_status") or "").upper()
    manifest_status = str(row.get("manifest_status") or "").lower()
    if freshness == "PARTIAL" and health_status == "PARTIAL_USABLE":
        return "Usable With Gaps"
    if freshness == "PARTIAL":
        return "Partial Coverage"
    if freshness == "UNKNOWN" and manifest_status == "complete":
        return "Health Check Needed"
    if freshness == "UNAVAILABLE":
        return "Not Enabled / Not Entitled"
    if freshness in {"FRESH", "COMPLETE"} or health_status in {"FRESH", "COMPLETE"}:
        return "Verified Current"
    if freshness == "STALE":
        return "Refresh recommended"
    return freshness.replace("_", " ").title() if freshness else "Unverified"


def _massive_lane_impact(row: Mapping[str, object]) -> tuple[str, str]:
    lane_id = str(row.get("lane_id") or row.get("name") or "")
    if row.get("blocks_execution") is True:
        return (
            "Execution-critical",
            "This lane can affect paper-order readiness when its data or health proof needs refresh, is due, or is blocked.",
        )
    if "options" in lane_id:
        return (
            "Optional / entitlement",
            "This lane is optional until the provider entitlement is verified and enabled.",
        )
    if "backtest" in lane_id:
        return (
            "Research/repair",
            "This lane supports research and backtesting. It should not block live review or paper orders.",
        )
    return (
        "Support/context",
        "This lane improves context or source hygiene. It does not directly block paper-order submission.",
    )


def _massive_lane_bucket_label(
    row: Mapping[str, object],
    *,
    status_label: str,
) -> str:
    lane_id = str(row.get("lane_id") or row.get("name") or "")
    if (
        row.get("blocks_execution") is not True
        and (
            _scheduler_row_status(row) in {"DISABLED", "DEFERRED"}
            or "backtest" in lane_id
            or "options" in lane_id
        )
    ):
        return "Research / Disabled / Not Entitled"
    if row.get("blocks_execution") is True:
        if status_label in {
            "Blocked",
            "Refresh Due",
            "Refreshing",
            "Waiting For Raw Lane",
        }:
            return "Execution-Critical Needs Refresh"
        return "Execution-Critical Ready"
    if _scheduler_row_status(row) in {"DUE_NOW", "RUNNING", "WAITING"}:
        return "Support / Context Due"
    return "Research / Disabled / Not Entitled"


def _massive_lane_action_label(
    row: Mapping[str, object],
    *,
    status_label: str,
) -> str:
    if status_label == "Refresh Due":
        return "Run lane refresh"
    if status_label == "Refreshing":
        return "Wait for refresh"
    if status_label == "Blocked":
        return "Fix lane blocker"
    if status_label == "Scheduled Later":
        return "No action now"
    if status_label == "Disabled / Entitlement Not Verified":
        return "Verify entitlement"
    if status_label == "Disabled / Research Lane":
        return "Enable only for research"
    if status_label == "Loaded / No Pull Needed":
        return "No pull needed"
    if status_label == "Ready From Live Slices":
        return "Derived locally"
    if status_label == "Waiting For Raw Lane":
        return "Wait for raw lane"
    return str(row.get("reason") or "Inspect lane detail")


def _massive_lane_refresh_control(row: Mapping[str, object]) -> dict[str, object]:
    lane_id = str(row.get("lane_id") or row.get("name") or "").strip()
    status = _scheduler_row_status(row)
    command = row.get("command")
    command_available = isinstance(command, list) and bool(command)
    enabled = bool(lane_id) and status == "DUE_NOW" and command_available
    scope_label = _massive_lane_refresh_scope_label(row)
    disabled_reason = "" if enabled else _massive_lane_refresh_disabled_reason(row)
    tooltip = (
        f"Starts only this data lane through the scheduler's trade-aware policy. "
        f"Scope: {scope_label}. Budget: {row.get('request_budget_label', 'not recorded')}."
        if enabled
        else (
            f"Lane refresh is unavailable because the current trade-aware policy "
            f"does not expose a runnable command for status {status or 'UNKNOWN'}. "
            f"{disabled_reason}"
        )
    )
    return {
        "refresh_enabled": enabled,
        "refresh_action_url": f"/scheduler/massive-lanes/{lane_id}/refresh" if lane_id else "",
        "refresh_button_label": _massive_lane_refresh_button_label(lane_id, enabled=enabled),
        "refresh_disabled_reason": disabled_reason,
        "refresh_scope_label": scope_label,
        "refresh_tooltip": tooltip,
    }


def _massive_lane_refresh_button_label(lane_id: str, *, enabled: bool) -> str:
    label = REFRESHABLE_MASSIVE_LANES.get(lane_id)
    if label:
        return label
    return "Refresh lane" if enabled else "Policy locked"


def _massive_lane_refresh_scope_label(row: Mapping[str, object]) -> str:
    batch_count = _optional_int(row, "command_ticker_count") or _optional_int(
        row,
        "batch_ticker_count",
    )
    ticker_count = _optional_int(row, "ticker_count")
    if ticker_count and batch_count:
        return f"{ticker_count} planned ticker(s); next safe batch {batch_count} ticker(s)"
    if batch_count:
        return f"next safe batch {batch_count} ticker(s)"
    if ticker_count:
        return f"{ticker_count} planned ticker(s)"
    return "lane-level scope only"


def _massive_lane_refresh_disabled_reason(row: Mapping[str, object]) -> str:
    status = _scheduler_row_status(row)
    reason = str(row.get("reason") or "No lane reason recorded.")
    if status == "RUNNING":
        return "This lane is already refreshing."
    if status == "DEFERRED":
        return f"Scheduled later by market-session policy. {reason}"
    if status == "WAITING":
        return f"Waiting for the required raw lane or prerequisite data. {reason}"
    if status == "BLOCKED":
        return f"Blocked by lane policy. {reason}"
    if status == "DISABLED":
        return f"Disabled by configuration or entitlement policy. {reason}"
    if status in {"SKIPPED", "READY", "READY_FROM_RAW"}:
        return f"The lane is fresh enough or derived locally; no pull is needed now. {reason}"
    if status == "DUE_NOW":
        return f"The lane is due, but no safe lane command is available. {reason}"
    return reason


def _massive_lane_show_live_ticker_progress(row: Mapping[str, object]) -> bool:
    lane_id = str(row.get("lane_id") or row.get("name") or "")
    dataset = str(row.get("raw_source_dataset") or row.get("dataset") or "")
    if dataset != "stock_trades":
        return False
    return "live_trade_slices" in lane_id or "premarket_trade_slices" in lane_id


def _massive_lane_coverage_label(
    row: Mapping[str, object],
    *,
    show_live_ticker_progress: bool,
) -> str:
    coverage = _optional_int(row, "manifest_coverage_pct")
    manifest = str(row.get("manifest_status") or "missing").replace("_", " ")
    if show_live_ticker_progress:
        fresh = _optional_int(row, "fresh_ticker_count")
        pending = _optional_int(row, "pending_ticker_count")
        return f"{fresh} fresh / {pending} pending"
    if coverage:
        return f"Manifest {manifest} / {coverage}% coverage"
    ticker_count = _optional_int(row, "ticker_count")
    if ticker_count:
        return f"{ticker_count} planned; manifest {manifest}"
    return f"Manifest {manifest}"


def _massive_display_status_class(status_label: str) -> str:
    if status_label == "Blocked":
        return "block"
    if status_label in {"Refresh Due", "Refreshing", "Waiting For Raw Lane"}:
        return "warn"
    if status_label in {"Loaded / No Pull Needed", "Ready From Live Slices"}:
        return "pass"
    return "neutral"


def _massive_display_health_class(health_label: str) -> str:
    if health_label == "Refresh recommended":
        return "block"
    if health_label in {"Usable With Gaps", "Partial Coverage", "Health Check Needed"}:
        return "warn"
    if health_label == "Verified Current":
        return "pass"
    return "neutral"


def _massive_lane_status_tooltip(row: Mapping[str, object], status_label: str) -> str:
    return (
        f"{status_label}. Raw scheduler status: {row.get('status', 'unknown')}. "
        f"Reason: {row.get('reason', 'No Massive lane rationale recorded.')}"
    )


def _massive_lane_health_tooltip(row: Mapping[str, object], health_label: str) -> str:
    return (
        f"{health_label}. Health source: {row.get('health_source', 'unknown')}. "
        f"Raw health: {row.get('health_status', 'unknown')} / "
        f"{row.get('health_freshness', 'unknown')}. "
        f"Checked: {_format_timestamp_or_text(row.get('health_checked_at'), default='not checked')}."
    )


def _massive_lane_coverage_tooltip(row: Mapping[str, object], coverage_label: str) -> str:
    return (
        f"{coverage_label}. Manifest: {row.get('manifest_status', 'missing')} / "
        f"{row.get('manifest_coverage_pct', 0)}%. Planned ticker tier: "
        f"{row.get('ticker_tier', 'not recorded')}."
    )


def _massive_lane_budget_tooltip(row: Mapping[str, object]) -> str:
    return (
        f"Cadence: {row.get('cadence_minutes') or 'window'}. ETA: "
        f"{row.get('eta_label', 'not available')}. Budget: "
        f"{row.get('request_budget_label', 'not recorded')}."
    )


def _massive_lane_action_tooltip(row: Mapping[str, object], action_label: str) -> str:
    return (
        f"{action_label}. This action is derived from lane status "
        f"{row.get('status', 'unknown')} and execution impact."
    )


def _massive_signal_requirement_summary(
    status: str,
    *,
    required_lanes: Sequence[str],
    missing_lanes: Sequence[str],
    is_execution_critical: bool,
) -> str:
    if missing_lanes:
        return f"Missing raw lane declaration: {', '.join(missing_lanes)}"
    if status.upper() == "READY":
        return "Required raw lanes are ready."
    if status.upper() == "WAITING":
        prefix = "Execution evidence waiting" if is_execution_critical else "Context waiting"
        return f"{prefix}: {', '.join(required_lanes) if required_lanes else 'no raw lanes'}"
    if status.upper() == "BLOCKED":
        return "Required raw lane is blocked."
    return status.replace("_", " ").title() if status else "Requirement unverified."


def live_config_view(readiness: Mapping[str, object]) -> dict[str, object]:
    view = dict(readiness)
    view["scope_label"] = "Configuration readiness"
    view["scope_detail"] = (
        "This panel checks whether the agency is configured to run; it is not data "
        "freshness proof. Use Agency Data Readiness and Lane Refresh for freshness, "
        "coverage health, and active load progress."
    )
    view["provider_tooltip"] = (
        "Provider is the configured market-data provider for refresh commands. "
        "Readiness here checks credentials/config only; live data freshness is shown elsewhere."
    )
    view["datasets_tooltip"] = (
        "Datasets counts configured source groups in the live refresh config, not the "
        "number of datasets currently fresh on disk."
    )
    view["tickers_tooltip"] = (
        "Tickers is the configured universe size from explicit tickers or active universe membership."
    )
    view["blockers_tooltip"] = (
        "Blockers are missing required configuration items. A blocker prevents the configured "
        "workflow from being considered ready."
    )
    view["runtime_signal_label"] = str(_optional_int(view, "runtime_signal_count"))
    view["runtime_signals_tooltip"] = (
        "Runtime Signals counts configured runtime signal lanes that the live cycle may evaluate. "
        "Signal freshness and health are shown in Agency Data Readiness and Signals."
    )
    view["config_tooltip"] = (
        "Config path is the local live-refresh JSON file used to build this readiness check."
    )
    view["check_rows"] = [
        _live_config_check_row(cast(Mapping[str, object], row))
        for row in _list_field(readiness, "checks")
        if isinstance(row, Mapping)
    ]
    return view

def _live_config_check_row(row: Mapping[str, object]) -> dict[str, object]:
    view = dict(row)
    label = str(row.get("label") or "Unknown check")
    status = str(row.get("status") or "UNKNOWN").upper()
    detail = str(row.get("detail") or "No check detail recorded.")
    category = _live_config_check_category(label)
    impact_label, impact_detail = _live_config_check_impact(label, status)
    meaning = _live_config_check_meaning(label, status, detail)
    next_action = _live_config_check_next_action(label, status, detail)
    view.update(
        {
            "label": label,
            "status": status,
            "status_class": str(row.get("status_class") or _live_config_status_class(status)),
            "detail": detail,
            "category": category,
            "impact_label": impact_label,
            "impact_detail": impact_detail,
            "meaning": meaning,
            "next_action": next_action,
            "tooltip": (
                f"{label}: {meaning} Impact: {impact_detail} "
                f"Next action: {next_action} Detail: {detail}"
            ),
        }
    )
    return view


def _live_config_check_category(label: str) -> str:
    normalized = label.casefold()
    if "config" in normalized:
        return "Config"
    if "ticker" in normalized or "coverage" in normalized:
        return "Coverage"
    if "market data" in normalized or "massive" in normalized or "alpaca" in normalized:
        return "Provider"
    if "subscription" in normalized or "rss" in normalized:
        return "Email"
    if "sec" in normalized or "13f" in normalized or "cusip" in normalized:
        return "Filing"
    if "options" in normalized:
        return "Optional"
    return "Config"


def _live_config_check_impact(label: str, status: str) -> tuple[str, str]:
    normalized = label.casefold()
    if (
        "market data" in normalized
        or "massive" in normalized
        or "ticker" in normalized
        or "coverage" in normalized
    ):
        return (
            "Execution-critical",
            "This configuration can affect live evidence, review readiness, or paper-order gates.",
        )
    if "options" in normalized:
        return (
            "Optional",
            "This configuration improves optional options context and should not block core paper trading.",
        )
    if "subscription" in normalized or "rss" in normalized or "sec" in normalized or "13f" in normalized or "cusip" in normalized:
        return (
            "Support/context",
            "This configuration improves context and evidence quality but does not by itself prove freshness.",
        )
    if status == "BLOCK":
        return (
            "Execution-critical",
            "This missing configuration blocks the configured workflow until fixed.",
        )
    return (
        "Config",
        "This check verifies a required local configuration item.",
    )


def _live_config_check_meaning(label: str, status: str, detail: str) -> str:
    normalized = label.casefold()
    if "runtime data coverage" in normalized:
        return "Configured core ticker coverage, not freshness proof."
    if "ticker universe" in normalized:
        return "The configured review universe can be resolved."
    if "market data" in normalized:
        if status != "PASS":
            return "The primary market-data provider configuration is missing or incomplete."
        return "The primary market-data provider credentials/config are available."
    if "massive" in normalized:
        if status != "PASS":
            return "Massive market-flow credentials/config are missing or incomplete."
        return "Massive market-flow credentials/config are available."
    if "subscription" in normalized:
        return "Subscription email ingestion is configured for the enabled services."
    if "rss" in normalized:
        return "RSS source list is configured for headline context."
    if "sec user-agent" in normalized:
        return "SEC requests include a required User-Agent identity."
    if "13f" in normalized:
        return "Institutional filing source list is configured."
    if "cusip" in normalized:
        return "CUSIP-to-ticker mapping is present for 13F interpretation."
    if "config file" in normalized:
        return "The live refresh configuration file was loaded."
    if status == "BLOCK":
        return "Required configuration is missing."
    if status == "WARN":
        return "Configuration is usable but needs operator attention."
    return detail


def _live_config_check_next_action(label: str, status: str, detail: str) -> str:
    normalized = label.casefold()
    detail_lower = detail.casefold()
    if status == "PASS":
        if "runtime data coverage" in normalized:
            return "Check Agency Data Readiness for freshness."
        if "subscription" in normalized:
            return "No action; email configuration is usable."
        return "No action."
    if "missing" in detail_lower and ("api_key" in detail_lower or "key" in detail_lower):
        return "Add the required provider key in .env."
    if "ticker" in normalized or "coverage" in normalized:
        return "Refresh or repair active-universe membership and core dataset manifests."
    if "subscription" in normalized:
        return "Update subscription email config or mailbox credentials."
    if "sec user-agent" in normalized:
        return "Set SEC_USER_AGENT or sec_user_agent in the live config."
    if "rss" in normalized or "13f" in normalized:
        return "Add the missing configured list in live-refresh config."
    if "cusip" in normalized:
        return "Create or point the config to the CUSIP map file."
    if "config file" in normalized:
        return "Create or fix the live-refresh config file."
    return "Inspect the config check detail and update local configuration."


def _live_config_status_class(status: str) -> str:
    if status == "PASS":
        return "pass"
    if status == "WARN":
        return "warn"
    if status == "BLOCK":
        return "block"
    return "neutral"

def provider_readiness_view(readiness: Mapping[str, object]) -> dict[str, object]:
    view = dict(readiness)
    provider_rows = [
        cast(Mapping[str, object], row) for row in _list_field(readiness, "providers")
    ]
    required_total = sum(1 for row in provider_rows if row.get("required_now") is True)
    required_ready = sum(
        1
        for row in provider_rows
        if row.get("required_now") is True and row.get("configured") is True
    )
    planned_total = sum(1 for row in provider_rows if row.get("required_now") is not True)
    planned_configured = sum(
        1
        for row in provider_rows
        if row.get("required_now") is not True and row.get("configured") is True
    )
    configured_count = _optional_int(view, "configured_count")
    provider_count = _optional_int(view, "provider_count")
    view["scope_label"] = "Credential readiness"
    view["scope_detail"] = (
        "Checks whether local provider credentials and config are present. This does "
        "not prove live API connectivity or data freshness; use the data-source "
        "health and lane refresh panels for that."
    )
    view["configured_label"] = f"{configured_count}/{provider_count} total configured"
    view["required_ready_count"] = required_ready
    view["required_label"] = f"{required_ready}/{required_total} required ready"
    view["active_ready_label"] = f"{required_ready}/{required_total} active ready"
    view["planned_configured_count"] = planned_configured
    view["planned_missing_count"] = max(0, planned_total - planned_configured)
    view["planned_optional_label"] = f"{max(0, planned_total - planned_configured)} planned optional"
    view["connections_tooltip"] = (
        "Active required providers are needed by today's configured workflow. "
        "Alpaca counts as active when paper broker or broker submission is enabled. "
        "Planned optional providers are roadmap integrations and do not block today."
    )
    view["configured_tooltip"] = (
        "Counts all tracked providers with local credentials or no-key config ready. "
        "This includes optional providers so the future integration roadmap stays visible."
    )
    view["required_ready_tooltip"] = (
        "Active required providers are needed by today's configured workflow, such as "
        "broker, selected market-flow source, SEC identity, email agents, or LLM review."
    )
    view["missing_required_tooltip"] = (
        "Missing active required provider credentials block paper flow until fixed."
    )
    view["planned_optional_tooltip"] = (
        "Planned optional providers are roadmap/context integrations. Missing optional "
        "keys do not block today's paper-trading flow."
    )
    view["planned_label"] = (
        f"{planned_configured} planned provider configured"
        if planned_configured == 1
        else f"{planned_configured} planned providers configured"
    )
    view["provider_rows"] = [
        _provider_readiness_row(row)
        for row in provider_rows
    ]
    return view

def _data_load_row(row: Mapping[str, object]) -> dict[str, object]:
    view = dict(row)
    if "detail" in view:
        view["detail"] = _operator_text(view["detail"])
    for key in ("status", "status_label", "source_freshness", "freshness"):
        if key in view:
            view[key] = _operator_text(view[key])
    name = row.get("label") or row.get("lane") or row.get("dataset") or "Unknown"
    view["name"] = _label_text(str(name))
    view["group_label"] = _label_text(str(row.get("group") or "unknown"))
    view["count_label"] = _data_load_count_label(row)
    view["coverage_style"] = f"width: {_bounded_percent(row, 'coverage_pct')}%"
    view["max_as_of_label"] = _format_timestamp_or_text(row.get("max_as_of"))
    view["source_last_success_at_label"] = _format_timestamp_or_text(
        row.get("source_last_success_at") or row.get("last_success_at")
    )
    return view


def _lane_state_row(row: Mapping[str, object]) -> dict[str, object]:
    view = dict(row)
    view["name"] = _label_text(str(row.get("label") or row.get("lane_id") or "Unknown"))
    view["lane_kind_label"] = _label_text(str(row.get("lane_kind") or "lane"))
    view["status_label"] = _operator_text(row.get("status_label") or "Unknown")
    view["operator_message"] = _operator_text(
        row.get("operator_message") or "No lane-state explanation recorded."
    )
    view["recommended_action"] = _operator_text(
        row.get("recommended_action") or "No lane action recorded."
    )
    view["latest_as_of_label"] = _format_timestamp_or_text(row.get("latest_as_of"))
    view["checked_at_label"] = _format_timestamp_or_text(row.get("checked_at"))
    requirements = [
        str(item)
        for item in _list_field_or_empty(row, "raw_lanes_required")
        if str(item).strip()
    ]
    view["requirement_label"] = ", ".join(requirements) if requirements else "Direct source"
    return view

def _data_load_issue(
    row: Mapping[str, object],
    *,
    fallback_status_class: str = "neutral",
) -> dict[str, object]:
    return {
        "kind": _label_text(str(row.get("kind") or "issue")),
        "item": _label_text(str(row.get("item") or "unknown")),
        "reason": _humanize_seconds_in_text(
            _operator_text(row.get("reason") or "No detail available.")
        ),
        "status_class": str(row.get("status_class") or fallback_status_class),
    }

def _freshness_status_row(row: Mapping[str, object]) -> dict[str, object]:
    source = str(row.get("source") or "")
    status = str(row.get("status") or "UNKNOWN")
    freshness = str(row.get("freshness") or "UNKNOWN")
    status_class = str(row.get("status_class") or "neutral")
    display_status = "Needs refresh" if status.upper() == "STALE" else _operator_text(status)
    display_freshness = "Needs refresh" if freshness.upper() == "STALE" else _operator_text(freshness)
    detail = _operator_text(row.get("detail") or "No freshness detail recorded.")
    impact_label = _source_impact_label(row)
    validity_label = _source_validity_label(row)
    next_action = _source_next_action(row, impact_label=impact_label)
    tooltip = (
        f"Why this status: {detail} Impact: {impact_label}. "
        f"Validity: {validity_label}. Next action: {next_action}"
    )
    return {
        "label": str(row.get("label") or row.get("source") or "Unknown source"),
        "source": source,
        "status": display_status,
        "freshness": display_freshness,
        "status_class": status_class,
        "last_success_at": str(row.get("last_success_at") or "not recorded"),
        "last_success_at_label": _format_timestamp_or_text(row.get("last_success_at")),
        "checked_at": str(row.get("checked_at") or "not checked"),
        "checked_at_label": _format_timestamp_or_text(
            row.get("checked_at"),
            default="not checked",
        ),
        "critical": "Critical" if row.get("critical") is True else "Supporting",
        "impact_label": impact_label,
        "validity_label": validity_label,
        "next_action": next_action,
        "tooltip": _operator_text(tooltip),
        "detail": detail,
    }


def _source_health_action_detail(
    *,
    blocked: int,
    stale: int,
    partial: int,
    check_stale: int,
    context_refresh: int,
) -> str:
    if blocked:
        return f"Resolve {_count_phrase(blocked, 'blocked source')} before execution."
    if context_refresh:
        return f"Refresh {_count_phrase(context_refresh, 'current-context source')}."
    if stale:
        return f"Refresh {_count_phrase(stale, 'source needing refresh')}."
    if check_stale:
        return f"Refresh {_count_phrase(check_stale, 'health-proof row')}."
    if partial:
        return f"Review {_count_phrase(partial, 'partial source')} before trading."
    return "No source refresh action required."


def _count_phrase(count: int, label: str) -> str:
    return f"{count} {label}" if count == 1 else f"{count} {label}s"


def _source_impact_label(row: Mapping[str, object]) -> str:
    source = str(row.get("source") or "").lower()
    if row.get("critical") is True or source in {"daily-market-bars", "massive-stock-trades"}:
        return "Execution-critical"
    if source in {"rss-news", "subscription-email-thesis"}:
        return "Current-context"
    if source in {"sec-company-facts", "sec-form4", "sec-13f"}:
        return "Slow-moving support"
    return "Supporting"


def _source_validity_label(row: Mapping[str, object]) -> str:
    status_class = str(row.get("status_class") or "")
    status = str(row.get("status") or "").upper()
    freshness = str(row.get("freshness") or "").upper()
    detail = str(row.get("detail") or "").lower()
    if status_class == "block":
        return "Blocked"
    if freshness == "STALE" or status == "STALE":
        return "Refresh needed"
    if "source-health row is" in detail or "older than" in detail:
        return "Proof needs refresh"
    if freshness == "PARTIAL" or status == "DEGRADED":
        return "Usable with caveat"
    if status_class == "pass":
        return "Current and usable"
    if status_class == "warn":
        return "Review before use"
    return "Not verified"


def _source_next_action(row: Mapping[str, object], *, impact_label: str) -> str:
    source = str(row.get("source") or "").lower()
    status_class = str(row.get("status_class") or "")
    status = str(row.get("status") or "").upper()
    freshness = str(row.get("freshness") or "").upper()
    detail = str(row.get("detail") or "").lower()
    if status_class == "block":
        if source in {"daily-market-bars", "massive-stock-trades"}:
            return "Refresh the Massive lane before paper-trading decisions."
        return "Refresh this source before relying on its evidence."
    if source in {"rss-news", "subscription-email-thesis"} and (
        status_class == "warn" or freshness == "STALE" or status == "STALE"
    ):
        if source == "rss-news":
            return "Rerun the news refresh so headline context reflects the latest session."
        return "Rerun email ingest and article analysis, including any required login step."
    if freshness == "PARTIAL" or status == "DEGRADED":
        return "Use covered tickers for review and let the repair lane finish."
    if "source-health row is" in detail or "older than" in detail:
        return "Refresh source-health monitoring proof."
    if impact_label == "Slow-moving support":
        return "No action if the latest filing period is already loaded; refresh on schedule."
    if status_class == "pass":
        return "No action needed for this source."
    return "Review this source before using its evidence."

def _full_live_command_rows(readiness: Mapping[str, object]) -> list[dict[str, object]]:
    coverage = _mapping_field(readiness, "coverage")
    active_refresh = _mapping_field(readiness, "active_refresh")
    status_class = str(readiness.get("status_class", "neutral"))
    freshness_class = "block" if _optional_int(coverage, "critical_source_blocker_count") else (
        "warn" if _optional_int(coverage, "source_warning_count") else "pass"
    )
    agent_blocked = _optional_int(coverage, "agent_blocked_count")
    agent_warning = _optional_int(coverage, "agent_warning_count")
    agent_class = "block" if agent_blocked else "warn" if agent_warning else "pass"
    refresh_state = str(active_refresh.get("state", "idle"))
    refresh_class = str(active_refresh.get("status_class", "neutral"))
    mode_label = _agency_mode_label(readiness)
    trading_gate = _trading_gate_label(readiness)
    freshness_value = _freshness_proof_value(coverage)
    ready_critical, total_critical = _critical_lane_counts(coverage)
    usable_critical = _critical_usable_with_warnings(coverage)
    active_refresh_value = _active_refresh_value(active_refresh)
    return [
        {
            "id": "system",
            "label": "Agency Mode",
            "value": f"{mode_label} · {trading_gate}",
            "status_class": status_class,
            "detail": _humanize_seconds_in_text(
                str(readiness.get("detail", "No readiness detail available."))
            ),
            "tooltip": _agency_mode_tooltip(readiness, coverage),
        },
        {
            "id": "freshness",
            "label": "Freshness Proof",
            "value": freshness_value,
            "status_class": freshness_class,
            "detail": _freshness_proof_detail(coverage),
            "tooltip": _freshness_proof_tooltip(coverage),
        },
        {
            "id": "agents",
            "label": "Signal Worker Readiness",
            "value": (
                f"{ready_critical}/{total_critical} fully ready · "
                f"{usable_critical}/{total_critical} usable with warnings"
            ),
            "status_class": agent_class,
            "detail": (
                f"{coverage.get('critical_lane_percent', 0)}% critical-lane output coverage; "
                f"{coverage.get('agent_ready_count', 0)}/"
                f"{coverage.get('agent_total_count', 0)} total lanes fully ready."
            ),
            "tooltip": _signal_worker_tooltip(coverage),
        },
        {
            "id": "loading",
            "label": "Active Refresh",
            "value": active_refresh_value,
            "status_class": refresh_class,
            "detail": _active_refresh_detail(active_refresh, refresh_state),
            "tooltip": _active_refresh_tooltip(active_refresh),
        },
    ]


def _agency_mode_label(readiness: Mapping[str, object]) -> str:
    if readiness.get("tradable_ready") is True:
        return "Paper Trading Ready"
    if readiness.get("review_operational_ready") is True:
        return "Review Ready"
    verdict = str(readiness.get("verdict") or "").casefold()
    if verdict == "loading" and not _list_field(readiness, "blockers"):
        return "Loading"
    if "context" in verdict:
        return "Context Only"
    return "Review Gated"


def _trading_gate_label(readiness: Mapping[str, object]) -> str:
    return "Paper Trading Ready" if readiness.get("tradable_ready") is True else "Paper Trading Gated"


def _agency_mode_tooltip(
    readiness: Mapping[str, object],
    coverage: Mapping[str, object],
) -> str:
    blocking_reason = _full_live_blocking_reason(readiness)
    return _humanize_seconds_in_text(
        "Agency mode answers whether you can review candidates and whether paper-order "
        "submission is open. Review Ready allows candidate review; Paper Trading Gated "
        "means execution still requires freshness, broker, risk, and order-approval gates. "
        f"Current reason: {blocking_reason}. "
        f"Backend verdict: {readiness.get('verdict') or readiness.get('status_label') or 'unknown'}. "
        f"Universe: {coverage.get('expected_ticker_count', 0)} tickers; "
        f"signals: {coverage.get('signal_count', 0)}."
    )

def _full_live_blocking_reason(readiness: Mapping[str, object]) -> str:
    blockers = [
        cast(Mapping[str, object], row)
        for row in _list_field(readiness, "blockers")
        if isinstance(row, Mapping)
    ]
    if blockers:
        first = blockers[0]
        item = str(first.get("item") or "readiness")
        reason = str(first.get("reason") or readiness.get("detail") or "No reason recorded.")
        return _operator_text(f"{item}: {reason}")
    detail = str(readiness.get("detail") or "").strip()
    if detail:
        return _operator_text(detail)
    if readiness.get("review_operational_ready") is True:
        return "Review is operational; execution still depends on downstream gates."
    return "Review and execution gates are not open yet."


def _freshness_proof_value(coverage: Mapping[str, object]) -> str:
    headline = str(coverage.get("source_headline") or "")
    if "health proof" in headline.lower() or "source-health row" in headline.lower():
        return "Health proof needs refresh"
    if "critical stale source" in headline.lower():
        return "Health proof needs refresh"
    if _optional_int(coverage, "critical_source_blocker_count"):
        return "Health proof needs refresh"
    if _optional_int(coverage, "source_warning_count"):
        return "Usable with warnings"
    return "Verified current"


def _freshness_proof_detail(coverage: Mapping[str, object]) -> str:
    return _humanize_seconds_in_text(
        f"{coverage.get('fresh_source_count', 0)}/{coverage.get('source_count', 0)} "
        f"sources have verified-current health proof; "
        f"{coverage.get('stale_source_count', 0)} blocked and "
        f"{coverage.get('source_warning_count', 0)} warning."
    )


def _freshness_proof_tooltip(coverage: Mapping[str, object]) -> str:
    return _humanize_seconds_in_text(
        "Freshness proof is the monitor timestamp that confirms displayed source state. "
        "It is different from source data freshness. A source can be HEALTHY/FRESH while "
        "its health proof is too old for execution. "
        f"Current headline: {_operator_text(coverage.get('source_headline', 'unknown'))}."
    )


def _critical_lane_counts(coverage: Mapping[str, object]) -> tuple[int, int]:
    label = str(coverage.get("critical_agent_ready_label") or "")
    match = re.search(r"(\d+)\s*/\s*(\d+)", label)
    if match:
        return int(match.group(1)), int(match.group(2))
    return _optional_int(coverage, "agent_ready_count"), _optional_int(coverage, "agent_total_count")


def _critical_usable_with_warnings(coverage: Mapping[str, object]) -> int:
    ready, total = _critical_lane_counts(coverage)
    blocked = min(_optional_int(coverage, "agent_blocked_count"), total)
    return max(0, total - ready - blocked)


def _signal_worker_tooltip(coverage: Mapping[str, object]) -> str:
    ready, total = _critical_lane_counts(coverage)
    usable = _critical_usable_with_warnings(coverage)
    return (
        "Fully ready means the worker produced output and source freshness passed. "
        "Usable with warnings means rows exist but source freshness, coverage, or health "
        "proof is partial. "
        f"Critical lanes: {ready}/{total} fully ready, {usable}/{total} usable with warnings; "
        f"output coverage {coverage.get('critical_lane_percent', 0)}%."
    )


def _active_refresh_value(active_refresh: Mapping[str, object]) -> str:
    state = str(active_refresh.get("state") or "idle")
    dataset = str(active_refresh.get("running_dataset") or active_refresh.get("current_dataset") or "")
    if state == "running":
        if dataset in {"sec_form4", "sec_company_facts", "sec_13f", "news_rss", "subscription_emails"}:
            return "Support refresh running"
        if dataset:
            return "Live-critical loading"
        return "Refresh running"
    if state in {"failed", "blocked"}:
        return "Refresh failed"
    if state == "stale":
        return "Refresh needs attention"
    return "No active refresh"


def _active_refresh_detail(active_refresh: Mapping[str, object], refresh_state: str) -> str:
    dataset = _label_text(
        str(active_refresh.get("running_dataset") or active_refresh.get("current_dataset") or "no dataset")
    )
    eta = str(active_refresh.get("eta_label") or "not available")
    value = _active_refresh_value(active_refresh)
    if value == "Support refresh running":
        return f"{dataset} running · ETA {eta} · support lane · review can continue."
    if value == "Live-critical loading":
        return f"{dataset} running · ETA {eta} · live-critical lane may gate execution."
    if value == "Refresh needs attention":
        return f"{dataset} refresh monitor needs attention; ETA {eta}."
    return f"ETA {eta}; state {refresh_state}."


def _active_refresh_tooltip(active_refresh: Mapping[str, object]) -> str:
    dataset = str(active_refresh.get("running_dataset") or active_refresh.get("current_dataset") or "none")
    return (
        "Active Refresh explains whether a running job blocks review or paper trading. "
        f"Dataset: {dataset}. ETA: {active_refresh.get('eta_label', 'not available')}. "
        f"Jobs: {active_refresh.get('completed_jobs', 0)}/{active_refresh.get('total_jobs', 0)}. "
        f"Status file: {active_refresh.get('status_path', 'not recorded')}."
    )

def _optional_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return 0

def _optional_mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}

def _list_field_or_empty(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    return value if isinstance(value, list) else []

def _data_load_count_label(row: Mapping[str, object]) -> str:
    produced = row.get("produced_count")
    expected = row.get("expected_count")
    loaded = row.get("loaded_ticker_count")
    ticker_expected = row.get("expected_ticker_count")
    row_count = row.get("row_count")
    if isinstance(produced, int) and isinstance(expected, int):
        return f"{produced}/{expected} rows"
    if isinstance(produced, int):
        return f"{produced} rows"
    if isinstance(loaded, int) and isinstance(ticker_expected, int):
        return f"{loaded}/{ticker_expected} tickers"
    if isinstance(row_count, int):
        return f"{row_count:,} rows"
    return "coverage n/a"

def operational_readiness_view(readiness: Mapping[str, object]) -> dict[str, object]:
    view = dict(readiness)
    view["check_rows"] = [
        cast(Mapping[str, object], row) for row in _list_field(readiness, "checks")
    ]
    view["key_rows"] = [
        cast(Mapping[str, object], row) for row in _list_field(readiness, "keys")
    ]
    view["next_action_rows"] = [str(action) for action in _list_field(readiness, "next_actions")]
    view["broker_execution_label"] = (
        "Enabled" if readiness.get("broker_execution_enabled") is True else "Disabled"
    )
    return view

async def paper_review_status_context() -> dict[str, object]:
    report_result, data_sources, risk_result = await asyncio.gather(
        _dashboard_selection_reports_live_checked(FINAL_SELECTION_REPORT_LIMIT),
        _runtime_data_source_status_live(),
        _dashboard_risk_decisions_live_checked(FINAL_SELECTION_REPORT_LIMIT),
        return_exceptions=True,
    )
    if isinstance(report_result, BaseException) or isinstance(risk_result, BaseException):
        return _runtime_unavailable_paper_status(
            _runtime_unavailable_readiness(report_result, risk_result)
        )
    if isinstance(data_sources, BaseException):
        data_sources = unavailable_data_source_status(
            "live source-health reader timed out or failed"
        )
    reports = _active_cycle_reports(cast(Sequence[Mapping[str, object]], report_result))
    risk_decisions = _risk_decisions_for_reports(
        cast(Sequence[Mapping[str, object]], risk_result),
        reports,
    )
    data_load_status = await asyncio.to_thread(
        load_data_load_status,
        source_health_rows=data_sources,
        source_health_origin=_source_health_origin_label(data_sources),
    )
    readiness = readiness_view(
        build_live_readiness(
            source_health=data_sources,
            selection_reports=reports,
            risk_decisions=risk_decisions,
            lane_states=_mapping_list_field_or_empty(data_load_status, "lane_states"),
        )
    )
    return await paper_review_status_from_runtime(
        reports=reports,
        risk_decisions=risk_decisions,
        readiness=readiness,
    )

async def operational_readiness_context() -> dict[str, object]:
    from agency.views.portfolio import _broker_execution_enabled
    report_result, source_load_status, risk_result = await asyncio.gather(
        _dashboard_selection_reports_live_checked(FINAL_SELECTION_REPORT_LIMIT),
        _runtime_data_source_status_with_load_status_live(),
        _dashboard_risk_decisions_live_checked(FINAL_SELECTION_REPORT_LIMIT),
        return_exceptions=True,
    )
    source_load_status = (
        source_load_status
        if isinstance(source_load_status, Mapping)
        else {"data_sources": [], "data_load_status": {}}
    )
    data_sources = _mapping_list_field(source_load_status, "data_sources")
    data_load_status = _mapping_field(source_load_status, "data_load_status")
    live_config = _mapping_field(data_load_status, "live_config")
    if not live_config:
        live_config = await asyncio.to_thread(load_live_config_readiness)
    if isinstance(report_result, BaseException) or isinstance(risk_result, BaseException):
        readiness = _runtime_unavailable_readiness(report_result, risk_result)
        paper_status = _runtime_unavailable_paper_status(readiness)
    else:
        reports = _active_cycle_reports(cast(Sequence[Mapping[str, object]], report_result))
        risk_decisions = _risk_decisions_for_reports(
            cast(Sequence[Mapping[str, object]], risk_result),
            reports,
        )
        readiness = build_live_readiness(
            source_health=data_sources,
            selection_reports=reports,
            risk_decisions=risk_decisions,
            lane_states=_mapping_list_field_or_empty(data_load_status, "lane_states"),
        )
        paper_status = await paper_review_status_from_runtime(
            reports=reports,
            risk_decisions=risk_decisions,
            readiness=readiness,
        )
    return build_operational_readiness(
        health={"status": "ok", "service": "trading-agency-v3"},
        live_config=live_config,
        data_refresh=await asyncio.to_thread(load_data_refresh_progress),
        data_load_status=data_load_status,
        live_readiness=readiness,
        paper_review=paper_status,
        broker_execution_enabled=_broker_execution_enabled(),
    )


def _runtime_unavailable_readiness(*errors: object) -> dict[str, object]:
    details = [
        str(error)
        for error in errors
        if isinstance(error, BaseException) and str(error)
    ]
    detail = (
        "Runtime repository is unavailable for selection reports or risk decisions. "
        "Refresh/restart the runtime database connection, then reload this status."
    )
    if details:
        detail = f"{detail} Reader detail: {'; '.join(details)}"
    return {
        "schema_version": "0.1.0",
        "ready": False,
        "verdict": "runtime_reader_unavailable",
        "cycle_id": None,
        "source_count": 0,
        "degraded_source_count": 0,
        "selection_report_count": 0,
        "risk_decision_count": 0,
        "reviewable_candidate_count": 0,
        "open_risk_decision_count": 0,
        "blocked_risk_decision_count": 0,
        "source_status_counts": {},
        "final_action_counts": {},
        "risk_decision_counts": {},
        "blockers": [
            {
                "kind": "runtime_reader_unavailable",
                "item": "runtime",
                "reason": detail,
            }
        ],
        "headline": "Runtime repository is unavailable.",
        "detail": detail,
    }


def _runtime_unavailable_paper_status(
    readiness: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "cycle_id": readiness.get("cycle_id"),
        "ready": False,
        "verdict": readiness.get("verdict"),
        "progress": {
            "total_count": 0,
            "reviewed_count": 0,
            "pending_count": 0,
            "approve_count": 0,
            "defer_count": 0,
            "reject_count": 0,
            "reviewed_label": "0/0",
            "status_label": "Runtime Unavailable",
            "status_class": "block",
            "detail": "Paper-review queue cannot be read until runtime storage is available.",
        },
        "queue": [],
    }

async def scheduler_work_queue_raw_context() -> dict[str, object]:
    from agency.views.market_regime import broker_status_context

    raw_reports, data_sources, raw_risk_decisions, broker = await asyncio.gather(
        _dashboard_selection_reports_live(FINAL_SELECTION_REPORT_LIMIT),
        _runtime_data_source_status_live(),
        _dashboard_risk_decisions_live(FINAL_SELECTION_REPORT_LIMIT),
        broker_status_context(),
    )
    reports = _active_cycle_reports(raw_reports)
    risk_decisions = _risk_decisions_for_reports(raw_risk_decisions, reports)
    data_load_status = await asyncio.to_thread(
        load_data_load_status,
        source_health_rows=data_sources,
        source_health_origin=_source_health_origin_label(data_sources),
    )
    readiness = build_live_readiness(
        source_health=data_sources,
        selection_reports=reports,
        risk_decisions=risk_decisions,
        lane_states=_mapping_list_field_or_empty(data_load_status, "lane_states"),
    )
    paper_status = await paper_review_status_from_runtime(
        reports=reports,
        risk_decisions=risk_decisions,
        readiness=readiness,
    )
    return scheduler_work_queue_context(
        reports=reports,
        review_queue=_mapping_list_field(paper_status, "queue"),
        source_health=data_sources,
        broker=broker,
        data_load_status=data_load_status,
        data_refresh_progress=load_data_refresh_progress(),
    )


async def scheduler_work_queue_status_context() -> dict[str, object]:
    return scheduler_work_queue_view(await scheduler_work_queue_raw_context())


async def paper_review_status_from_runtime(
    *,
    reports: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
    readiness: Mapping[str, object],
) -> dict[str, object]:
    review_events = await human_review_events_for_reports(reports, readiness)
    queue = paper_review_queue(
        reports,
        risk_decisions,
        readiness,
        review_events=review_events,
    )
    return {
        "schema_version": "0.1.0",
        "cycle_id": readiness.get("cycle_id"),
        "ready": readiness.get("ready"),
        "verdict": readiness.get("verdict"),
        "progress": paper_review_progress(queue),
        "queue": queue,
    }

async def human_review_events_for_reports(
    reports: Sequence[Mapping[str, object]],
    readiness: Mapping[str, object],
) -> list[dict[str, object]]:
    try:
        return await asyncio.wait_for(
            _lifecycle_events_for_reports(
                reports,
                readiness,
                event_type="HUMAN_REVIEW",
                limit_per_ticker=50,
            ),
            timeout=DASHBOARD_RUNTIME_QUERY_TIMEOUT_SECONDS,
        )
    except Exception:  # noqa: BLE001
        return []

def paper_review_queue(
    reports: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
    readiness: Mapping[str, object],
    *,
    review_events: Sequence[Mapping[str, object]] = (),
) -> list[dict[str, object]]:
    from agency.views.candidates import _paper_review_row, _paper_review_sort_key
    cycle_id = readiness.get("cycle_id")
    if not isinstance(cycle_id, str) or not cycle_id:
        return []
    risks = _risk_decision_index(risk_decisions)
    reviews = _human_review_index(review_events)
    rows = [
        _paper_review_row(
            report,
            risks.get(_runtime_payload_key(report)),
            reviews.get(_runtime_payload_key(report)),
        )
        for report in reports
        if report.get("cycle_id") == cycle_id
        and str(report.get("final_action")) in ACTIONABLE_ACTIONS
    ]
    return sorted(rows, key=_paper_review_sort_key)

def paper_review_progress(
    review_queue: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    from agency.views.candidates import (
        _review_progress_detail,
        _review_progress_status_class,
        _review_progress_status_label,
    )
    total_count = len(review_queue)
    decisions = [_review_decision_key(row.get("human_review_decision")) for row in review_queue]
    pending_count = decisions.count("pending")
    approve_count = decisions.count("approve")
    defer_count = decisions.count("defer")
    reject_count = decisions.count("reject")
    reviewed_count = total_count - pending_count
    return {
        "total_count": total_count,
        "reviewed_count": reviewed_count,
        "pending_count": pending_count,
        "approve_count": approve_count,
        "defer_count": defer_count,
        "reject_count": reject_count,
        "reviewed_label": f"{reviewed_count}/{total_count}" if total_count else "0/0",
        "status_label": _review_progress_status_label(total_count, pending_count),
        "status_class": _review_progress_status_class(total_count, pending_count),
        "detail": _review_progress_detail(total_count, pending_count),
    }

def _review_decision_key(value: object) -> str:
    return str(value or "").strip().casefold()

def policy_sections(policy: PortfolioPolicy | None = None) -> list[dict[str, object]]:
    resolved_policy = policy or PortfolioPolicy.from_env()
    return [
        {
            "title": "Targets and Discipline",
            "items": [
                {
                    "label": "Weekly planning target",
                    "value": f"{resolved_policy.weekly_planning_target_pct:.1f}%",
                },
                {
                    "label": "Minimum final conviction",
                    "value": f"{resolved_policy.min_final_conviction:.2f}",
                },
                {
                    "label": "Maximum weekly drawdown",
                    "value": f"{resolved_policy.max_weekly_drawdown_pct:.1f}%",
                },
                {
                    "label": "Minimum hold",
                    "value": f"{resolved_policy.minimum_hold_days} days",
                },
            ],
        },
        {
            "title": "Capacity",
            "items": [
                {"label": "Maximum positions", "value": str(resolved_policy.max_positions)},
                {
                    "label": "Maximum new per cycle",
                    "value": str(resolved_policy.max_new_positions_per_cycle),
                },
                {
                    "label": "Maximum single name",
                    "value": f"{resolved_policy.max_single_name_pct:.0f}%",
                },
                {
                    "label": "Maximum sector exposure",
                    "value": f"{resolved_policy.max_sector_exposure_pct:.0f}%",
                },
                {"label": "Cash reserve", "value": f"{resolved_policy.cash_reserve_pct:.0f}%"},
                {
                    "label": "Maximum gross exposure",
                    "value": f"{resolved_policy.max_gross_exposure_pct:.0f}%",
                },
            ],
        },
        {
            "title": "Trade Defaults",
            "items": [
                {"label": "Default stop", "value": f"{resolved_policy.stop_loss_pct:.1f}%"},
                {
                    "label": "Default take profit",
                    "value": f"{resolved_policy.take_profit_pct:.1f}%",
                },
                {"label": "Trailing stop", "value": f"{resolved_policy.trailing_stop_pct:.1f}%"},
                {
                    "label": "Hourly loss alert",
                    "value": f"{resolved_policy.hourly_loss_alert_pct:.1f}%",
                },
                {
                    "label": "Default position size",
                    "value": f"{resolved_policy.default_position_pct:.0f}%",
                },
                {
                    "label": "Bracket orders",
                    "value": "Enabled" if resolved_policy.bracket_orders_enabled else "Disabled",
                },
            ],
        },
        {
            "title": "Permissions",
            "items": [
                {
                    "label": "Shorts",
                    "value": "Enabled" if resolved_policy.allow_short_trades else "Disabled",
                },
                {
                    "label": "Live trading",
                    "value": "Enabled" if resolved_policy.live_trading_enabled else "Disabled",
                },
                {
                    "label": "Broker submission",
                    "value": "Enabled" if resolved_policy.broker_submit_enabled else "Disabled",
                },
                {"label": "Policy source", "value": "Env plus optional local JSON"},
            ],
        },
    ]

def policy_summary(
    *,
    db_backed: bool = False,
    policy: PortfolioPolicy | None = None,
) -> dict[str, object]:
    resolved_policy = policy or PortfolioPolicy.from_env()
    state = "enabled" if resolved_policy.broker_submit_enabled else "disabled"
    source_label = "DB Backed" if db_backed else "File backed"
    headline = (
        "Portfolio policy is stored in the database."
        if db_backed
        else "Portfolio policy is loaded from local controls."
    )
    return {
        "headline": headline,
        "detail": (
            f"Broker submission is {state}; policy values are visible before every paper run."
        ),
        "db_backed": db_backed,
        "source_label": source_label,
    }

def _risk_decision_index(
    risk_decisions: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str, str], Mapping[str, object]]:
    indexed: dict[tuple[str, str, str], Mapping[str, object]] = {}
    for decision in risk_decisions:
        key = _runtime_payload_key(decision)
        if all(key) and key not in indexed:
            indexed[key] = decision
    return indexed

def _source_status_class(source: Mapping[str, object]) -> str:
    age_seconds = _source_checked_age_seconds(source)
    if age_seconds is None or age_seconds > SOURCE_HEALTH_MAX_AGE_SECONDS:
        return "block"
    return "warn" if _source_is_degraded(source) else "pass"


def _source_checked_age_seconds(source: Mapping[str, object]) -> int | None:
    checked_at = source.get("checked_at")
    if not isinstance(checked_at, str) or not checked_at.strip():
        return None
    try:
        parsed = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds()))

def _readiness_status_class(verdict: str) -> str:
    if verdict == "ready_for_paper_validation":
        return "pass"
    if verdict in {"context_only_source_health", "context_only_lane_state"}:
        return "warn"
    return "block"

def _readiness_blocker_rows(summary: Mapping[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for blocker in _list_field(summary, "blockers"):
        payload = cast(Mapping[str, object], blocker)
        kind = str(payload["kind"])
        rows.append(
            {
                "kind": _label_text(kind),
                "item": str(payload["item"]),
                "reason": _humanize_seconds_in_text(str(payload["reason"])),
                "status_class": "warn" if kind == "source_health" else "block",
            }
        )
    return rows

def _provider_readiness_row(row: Mapping[str, object]) -> dict[str, object]:
    provider_id = str(row.get("id") or "").strip()
    required_now = row.get("required_now") is True
    configured = row.get("configured") is True
    status = str(row.get("status") or "UNKNOWN")
    key_label = str(row.get("key_label") or "No key required")
    keys = [
        cast(Mapping[str, object], item)
        for item in _list_field_or_empty(row, "keys")
        if isinstance(item, Mapping)
    ]
    secret_status = _provider_secret_status(
        configured=configured,
        required_now=required_now,
        status=status,
        keys=keys,
    )
    requirement_label = _provider_requirement_label(required_now, configured)
    requirement_reason = _provider_requirement_reason(required_now, configured)
    impact_label = _provider_impact_label(provider_id, required_now, configured, status)
    next_action = _provider_next_action(
        provider_id=provider_id,
        required_now=required_now,
        configured=configured,
        status=status,
        key_label=key_label,
        keys=keys,
    )
    detail = str(row.get("detail") or "")
    tooltip = (
        f"{row.get('label', 'Provider')}: {requirement_reason} "
        f"{secret_status}. {detail} Next action: {next_action}"
    )
    return {
        "id": provider_id,
        "label": str(row.get("label") or "Provider"),
        "category": _label_text(str(row.get("category") or "unknown")),
        "purpose": str(row.get("purpose") or ""),
        "required_label": requirement_label,
        "requirement_reason": requirement_reason,
        "configured": configured,
        "status": status,
        "status_class": str(row.get("status_class") or "neutral"),
        "key_label": key_label,
        "secret_status_label": secret_status,
        "impact_label": impact_label,
        "next_action": next_action,
        "detail": detail,
        "tooltip": tooltip,
    }

def _provider_requirement_label(required_now: bool, configured: bool) -> str:
    if required_now:
        return "Active required"
    if configured:
        return "Optional configured"
    return "Planned optional"

def _provider_requirement_reason(required_now: bool, configured: bool) -> str:
    if required_now:
        return "This provider is required by today's workflow."
    if configured:
        return "This provider is optional for today's workflow and currently configured."
    return "This provider is planned for future capabilities and does not block today's paper flow."

def _provider_secret_status(
    *,
    configured: bool,
    required_now: bool,
    status: str,
    keys: Sequence[Mapping[str, object]],
) -> str:
    if not keys:
        return "No key required"
    present_count = sum(1 for key in keys if key.get("present") is True)
    if configured:
        return "Credential available"
    if 0 < present_count < len(keys):
        return "Partial required keys" if required_now else "Partial optional keys"
    if required_now or status == "BLOCK":
        return "Missing required keys"
    return "Missing optional key" if len(keys) == 1 else "Missing optional keys"

def _provider_impact_label(
    provider_id: str,
    required_now: bool,
    configured: bool,
    status: str,
) -> str:
    if not required_now and not configured and status == "PLANNED":
        return "Optional/roadmap"
    return {
        "alpaca": "Execution-critical broker/provider",
        "sec_edgar": "Filings and ownership evidence",
        "openai": "LLM review/explanation",
        "openfigi": "Reference-data support",
        "benzinga": "News/activity context",
        "unusual_whales": "Options/activity context",
        "fred": "Macro regime context",
        "polygon_massive": "Market-flow provider",
        "subscription_email_agents": "Subscription context",
        "thetadata": "Options-history context",
        "finra": "Market-structure context",
    }.get(provider_id, "Provider support")

def _provider_next_action(
    *,
    provider_id: str,
    required_now: bool,
    configured: bool,
    status: str,
    key_label: str,
    keys: Sequence[Mapping[str, object]],
) -> str:
    if not keys:
        return "No credential action required."
    missing_keys = [
        str(key.get("name"))
        for key in keys
        if key.get("present") is not True and key.get("name")
    ]
    missing_label = ", ".join(missing_keys) if missing_keys else key_label
    if configured:
        if provider_id == "polygon_massive" and missing_keys:
            return (
                "No action; market-flow credential is satisfied by one configured provider. "
                "Add the alternate provider only for failover or source switching."
            )
        if required_now:
            return "No action; required provider credential is present."
        return "No action; optional provider credential is available."
    if status == "WARN":
        return f"Complete {missing_label} in .env before enabling this provider."
    if required_now or status == "BLOCK":
        if provider_id == "alpaca":
            return f"Add {key_label} in .env before broker submission."
        if provider_id == "openai":
            return f"Add {key_label} in .env before enabling LLM review."
        if provider_id == "polygon_massive":
            return f"Add {key_label} in .env before market-flow refresh."
        if provider_id == "sec_edgar":
            return "Set SEC_USER_AGENT in .env or live-refresh.local.json before SEC refresh."
        return f"Add {key_label} in .env before workflows require this provider."
    return f"No action for today; add {key_label} only when enabling this roadmap provider."

def _command_hero_class(candidate_count: int, degraded_source_count: int) -> str:
    if degraded_source_count > 0:
        return "hero-watch"
    if candidate_count > 0:
        return "hero-success"
    return "hero-info"

def _command_headline(candidate_count: int, actionable_candidate_count: int) -> str:
    if candidate_count == 0:
        return "Runtime online. No final candidates yet."
    return (
        f"Runtime online. {actionable_candidate_count} "
        f"{_plural('actionable candidate', actionable_candidate_count)} across "
        f"{candidate_count} {_plural('report', candidate_count)}."
    )

def _command_detail(candidate_count: int, degraded_source_count: int) -> str:
    if degraded_source_count == 0:
        source_note = "All active cycle sources look ready"
    elif degraded_source_count == 1:
        source_note = "1 source needs attention"
    else:
        source_note = f"{degraded_source_count} sources need attention"
    if candidate_count == 0:
        return f"{source_note}; candidate rows will appear after selection reports persist."
    return f"{source_note}; dashboard counts are backed by runtime readers."
