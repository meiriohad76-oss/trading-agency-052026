"""View-model constructors for the command page."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast
import asyncio

from agency.api.health import contract_summaries, runtime_data_source_status
from agency.runtime import build_live_readiness, scheduler_work_queue_context
from agency.runtime.data_load_status import load_data_load_status
from agency.runtime.data_refresh_progress import load_data_refresh_progress
from agency.runtime.full_live_readiness import load_full_live_readiness
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.runtime.operational_readiness import build_operational_readiness
from agency.runtime.provider_readiness import load_provider_readiness
from agency.services import PortfolioPolicy

from agency.views._shared import (
    ACTIONABLE_ACTIONS,
    FINAL_SELECTION_REPORT_LIMIT,
    _active_cycle_reports,
    _dashboard_risk_decisions,
    _dashboard_selection_reports,
    _float_field,
    _human_review_index,
    _int_field,
    _is_actionable_candidate,
    _label_text,
    _lifecycle_events_for_reports,
    _list_field,
    _mapping_field,
    _mapping_list_field,
    _plural,
    _risk_decisions_for_reports,
    _runtime_payload_key,
    _source_is_degraded,
)


async def dashboard_context() -> dict[str, object]:
    from agency.views.candidates import candidate_rows
    from agency.views.portfolio import _broker_execution_enabled
    reports, data_sources, risk_decisions = await asyncio.gather(
        _dashboard_selection_reports(limit=FINAL_SELECTION_REPORT_LIMIT),
        runtime_data_source_status(),
        _dashboard_risk_decisions(limit=FINAL_SELECTION_REPORT_LIMIT),
    )
    active_reports = _active_cycle_reports(reports)
    active_risk_decisions = _risk_decisions_for_reports(risk_decisions, active_reports)
    candidates = candidate_rows(active_reports)
    contracts = contract_summaries()
    readiness = readiness_view(
        build_live_readiness(
            source_health=data_sources,
            selection_reports=active_reports,
            risk_decisions=active_risk_decisions,
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
    live_config = load_live_config_readiness()
    data_refresh = load_data_refresh_progress()
    data_load_status = load_data_load_status()
    full_live_readiness = load_full_live_readiness(
        live_config=live_config,
        data_refresh=data_refresh,
        data_load_status=data_load_status,
    )
    scheduler_status = scheduler_work_queue_context(
        reports=active_reports,
        review_queue=review_queue,
        source_health=data_sources,
        data_load_status=data_load_status,
        data_refresh_progress=data_refresh,
    )
    operational_readiness = build_operational_readiness(
        health={"status": "ok", "service": "trading-agency-v2"},
        live_config=live_config,
        data_refresh=data_refresh,
        data_load_status=data_load_status,
        live_readiness=readiness,
        paper_review=paper_status,
        broker_execution_enabled=_broker_execution_enabled(),
    )
    provider_readiness = load_provider_readiness(live_config)
    return {
        "actions": command_actions(),
        "contracts": contracts,
        "data_sources": source_status_rows(data_sources),
        "candidates": candidates,
        "data_refresh": data_refresh_progress_view(data_refresh),
        "data_load_status": data_load_status_view(data_load_status),
        "full_live_readiness": full_live_readiness_view(full_live_readiness),
        "live_config": live_config_view(live_config),
        "operational_readiness": operational_readiness_view(operational_readiness),
        "provider_readiness": provider_readiness_view(provider_readiness),
        "readiness": readiness,
        "review_progress": review_progress,
        "review_queue": review_queue,
        "scheduler": scheduler_work_queue_view(scheduler_status),
        "summary": summary,
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
        1 for candidate in candidates if candidate["gate_status"] == "BLOCK"
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
        {"label": "Review config", "href": "#live-config-heading"},
        {"label": "Review providers", "href": "#provider-readiness-heading"},
        {"label": "Review readiness", "href": "#readiness-heading"},
        {"label": "Review queue", "href": "#review-queue-heading"},
        {"label": "Review candidates", "href": "#candidates-heading"},
        {"label": "Review data sources", "href": "#source-heading"},
        {"label": "Review contracts", "href": "#contracts-heading"},
    ]

def source_status_rows(sources: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "source": str(source["source"]),
            "status": str(source["status"]),
            "freshness": str(source["freshness"]),
            "reliability_pct": round(_float_field(source, "reliability_score") * 100),
            "status_class": _source_status_class(source),
            "checked_at": str(source["checked_at"]),
        }
        for source in sources
    ]

def readiness_view(summary: Mapping[str, object]) -> dict[str, object]:
    view = dict(summary)
    verdict = str(summary["verdict"])
    view["verdict_label"] = _label_text(verdict)
    view["status_class"] = _readiness_status_class(verdict)
    view["blocker_rows"] = _readiness_blocker_rows(summary)
    return view

def data_refresh_progress_view(progress: Mapping[str, object]) -> dict[str, object]:
    view = dict(progress)
    view["progress_style"] = f"width: {_int_field(progress, 'percent_complete')}%"
    trade_pull = progress.get("trade_pull")
    view["trade_pull"] = trade_pull_progress_view(
        cast(Mapping[str, object], trade_pull) if isinstance(trade_pull, Mapping) else {}
    )
    return view

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
    view["progress_style"] = f"width: {_int_field(view, 'percent_complete')}%"
    return view

def data_load_status_view(status: Mapping[str, object]) -> dict[str, object]:
    view = dict(status)
    view["progress_style"] = f"width: {_int_field(status, 'overall_percent')}%"
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
    view["issue_rows"] = [
        _data_load_issue(cast(Mapping[str, object], row))
        for row in (
            _list_field(status, "blockers") + _list_field(status, "warnings")
        )
    ]
    view["freshness_rows"] = [
        _freshness_status_row(cast(Mapping[str, object], row))
        for row in _list_field_or_empty(status, "freshness_rows")
    ]
    return view

def full_live_readiness_view(readiness: Mapping[str, object]) -> dict[str, object]:
    view = dict(readiness)
    coverage = _mapping_field(readiness, "coverage")
    active_refresh = _mapping_field(readiness, "active_refresh")
    view["coverage"] = dict(coverage)
    view["active_refresh"] = dict(active_refresh)
    view["progress_style"] = f"width: {_int_field(coverage, 'overall_percent')}%"
    command_rows = _full_live_command_rows(readiness)
    view["command_rows"] = command_rows
    view["command_map"] = {str(row["id"]): row for row in command_rows}
    view["provider_usage_rows"] = [
        cast(Mapping[str, object], row)
        for row in _list_field(readiness, "provider_usage")
    ]
    view["issue_rows"] = [
        _data_load_issue(cast(Mapping[str, object], row))
        for row in (
            _list_field(readiness, "blockers") + _list_field(readiness, "warnings")
        )
    ]
    view["next_action_rows"] = [str(row) for row in _list_field(readiness, "next_actions")]
    view["refresh_job_rows"] = _mapping_list_field(active_refresh, "dataset_rows")[:8]
    return view

def scheduler_work_queue_view(status: Mapping[str, object]) -> dict[str, object]:
    view = dict(status)
    summary = _mapping_field(status, "summary")
    ticker_tiers = _mapping_field(status, "ticker_tiers")
    tiers = _mapping_field(ticker_tiers, "tiers")
    tradability = _mapping_field(status, "tradability")
    repair = _mapping_field(status, "repair_plan")
    gate = _mapping_field(status, "execution_freshness_gate")
    view["headline"] = str(summary["headline"])
    view["status_label"] = str(tradability["status_label"])
    view["status_class"] = str(tradability["status_class"])
    view["tradability_detail"] = str(tradability["detail"])
    view["job_rows"] = _mapping_list_field(status, "jobs")[:10]
    view["next_job_rows"] = _mapping_list_field(status, "next_jobs")
    view["stale_rows"] = _mapping_list_field(status, "stale_datasets")[:8]
    view["repair"] = repair
    view["repair_rows"] = _mapping_list_field(repair, "jobs")[:6]
    view["freshness_checks"] = _mapping_list_field(gate, "checks")
    view["tier_rows"] = [
        dict(_mapping_field(tiers, key))
        for key in ("T0", "T1", "T2", "T3")
        if key in tiers
    ]
    return view

def live_config_view(readiness: Mapping[str, object]) -> dict[str, object]:
    view = dict(readiness)
    view["check_rows"] = _list_field(readiness, "checks")
    return view

def provider_readiness_view(readiness: Mapping[str, object]) -> dict[str, object]:
    view = dict(readiness)
    view["provider_rows"] = [
        _provider_readiness_row(cast(Mapping[str, object], row))
        for row in _list_field(readiness, "providers")
    ]
    return view

def _data_load_row(row: Mapping[str, object]) -> dict[str, object]:
    view = dict(row)
    name = row.get("label") or row.get("lane") or row.get("dataset") or "Unknown"
    view["name"] = str(name)
    view["group_label"] = _label_text(str(row.get("group") or "unknown"))
    view["count_label"] = _data_load_count_label(row)
    view["coverage_style"] = f"width: {_int_field(row, 'coverage_pct')}%"
    return view

def _data_load_issue(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "kind": _label_text(str(row.get("kind") or "issue")),
        "item": str(row.get("item") or "unknown"),
        "reason": str(row.get("reason") or "No detail available."),
    }

def _freshness_status_row(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "label": str(row.get("label") or row.get("source") or "Unknown source"),
        "status": str(row.get("status") or "UNKNOWN"),
        "freshness": str(row.get("freshness") or "UNKNOWN"),
        "status_class": str(row.get("status_class") or "neutral"),
        "last_success_at": str(row.get("last_success_at") or "not recorded"),
        "checked_at": str(row.get("checked_at") or "not checked"),
        "critical": "Critical" if row.get("critical") is True else "Supporting",
        "detail": str(row.get("detail") or "No freshness detail recorded."),
    }

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
    return [
        {
            "id": "system",
            "label": "System readiness",
            "value": str(readiness.get("status_label", "Unknown")),
            "status_class": status_class,
            "detail": str(readiness.get("detail", "No readiness detail available.")),
        },
        {
            "id": "freshness",
            "label": "Data freshness",
            "value": str(coverage.get("source_headline", "Source freshness unknown.")),
            "status_class": freshness_class,
            "detail": (
                f"{coverage.get('fresh_source_count', 0)}/"
                f"{coverage.get('source_count', 0)} sources fresh; "
                f"{coverage.get('stale_source_count', 0)} stale."
            ),
        },
        {
            "id": "agents",
            "label": "Agent lanes",
            "value": str(coverage.get("critical_agent_ready_label", "critical lanes unknown")),
            "status_class": agent_class,
            "detail": (
                f"{coverage.get('agent_ready_count', 0)}/"
                f"{coverage.get('agent_total_count', 0)} total lanes ready."
            ),
        },
        {
            "id": "loading",
            "label": "Loading progress",
            "value": str(active_refresh.get("status_label", "Unknown")),
            "status_class": refresh_class,
            "detail": (
                f"ETA {active_refresh.get('eta_label', 'not available')}; "
                f"state {refresh_state}."
            ),
        },
    ]

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
    reports, data_sources, risk_decisions = await asyncio.gather(
        _dashboard_selection_reports(limit=FINAL_SELECTION_REPORT_LIMIT),
        runtime_data_source_status(),
        _dashboard_risk_decisions(limit=FINAL_SELECTION_REPORT_LIMIT),
    )
    readiness = readiness_view(
        build_live_readiness(
            source_health=data_sources,
            selection_reports=reports,
            risk_decisions=risk_decisions,
        )
    )
    return await paper_review_status_from_runtime(
        reports=reports,
        risk_decisions=risk_decisions,
        readiness=readiness,
    )

async def operational_readiness_context() -> dict[str, object]:
    from agency.views.portfolio import _broker_execution_enabled
    reports, data_sources, risk_decisions = await asyncio.gather(
        _dashboard_selection_reports(limit=FINAL_SELECTION_REPORT_LIMIT),
        runtime_data_source_status(),
        _dashboard_risk_decisions(limit=FINAL_SELECTION_REPORT_LIMIT),
    )
    readiness = build_live_readiness(
        source_health=data_sources,
        selection_reports=reports,
        risk_decisions=risk_decisions,
    )
    paper_status = await paper_review_status_from_runtime(
        reports=reports,
        risk_decisions=risk_decisions,
        readiness=readiness,
    )
    return build_operational_readiness(
        health={"status": "ok", "service": "trading-agency-v2"},
        live_config=load_live_config_readiness(),
        data_refresh=load_data_refresh_progress(),
        data_load_status=load_data_load_status(),
        live_readiness=readiness,
        paper_review=paper_status,
        broker_execution_enabled=_broker_execution_enabled(),
    )

async def scheduler_work_queue_status_context() -> dict[str, object]:
    raw_reports, data_sources, raw_risk_decisions = await asyncio.gather(
        _dashboard_selection_reports(limit=FINAL_SELECTION_REPORT_LIMIT),
        runtime_data_source_status(),
        _dashboard_risk_decisions(limit=FINAL_SELECTION_REPORT_LIMIT),
    )
    reports = _active_cycle_reports(raw_reports)
    risk_decisions = _risk_decisions_for_reports(raw_risk_decisions, reports)
    readiness = build_live_readiness(
        source_health=data_sources,
        selection_reports=reports,
        risk_decisions=risk_decisions,
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
        data_load_status=load_data_load_status(),
        data_refresh_progress=load_data_refresh_progress(),
    )

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
    return await _lifecycle_events_for_reports(
        reports,
        readiness,
        event_type="HUMAN_REVIEW",
        limit_per_ticker=50,
    )

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
    from agency.views.candidates import _review_progress_detail, _review_progress_status_class, _review_progress_status_label
    total_count = len(review_queue)
    pending_count = sum(1 for row in review_queue if row["human_review_decision"] == "Pending")
    approve_count = sum(1 for row in review_queue if row["human_review_decision"] == "Approve")
    defer_count = sum(1 for row in review_queue if row["human_review_decision"] == "Defer")
    reject_count = sum(1 for row in review_queue if row["human_review_decision"] == "Reject")
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

def policy_sections() -> list[dict[str, object]]:
    policy = PortfolioPolicy.from_env()
    return [
        {
            "title": "Targets and Discipline",
            "items": [
                {"label": "Weekly planning target", "value": "3.0%"},
                {
                    "label": "Minimum final conviction",
                    "value": f"{policy.min_final_conviction:.2f}",
                },
                {"label": "Maximum weekly drawdown", "value": "6.0%"},
                {"label": "Minimum hold", "value": "2 days"},
            ],
        },
        {
            "title": "Capacity",
            "items": [
                {"label": "Maximum positions", "value": "10"},
                {
                    "label": "Maximum new per cycle",
                    "value": str(policy.max_new_positions_per_cycle),
                },
                {"label": "Maximum single name", "value": "25%"},
                {"label": "Maximum sector exposure", "value": "30%"},
                {"label": "Cash reserve", "value": "10%"},
                {
                    "label": "Maximum gross exposure",
                    "value": f"{policy.max_gross_exposure_pct:.0f}%",
                },
            ],
        },
        {
            "title": "Trade Defaults",
            "items": [
                {"label": "Default stop", "value": f"{policy.stop_loss_pct:.1f}%"},
                {
                    "label": "Default take profit",
                    "value": f"{policy.take_profit_pct:.1f}%",
                },
                {"label": "Trailing stop", "value": f"{policy.trailing_stop_pct:.1f}%"},
                {
                    "label": "Hourly loss alert",
                    "value": f"{policy.hourly_loss_alert_pct:.1f}%",
                },
                {
                    "label": "Default position size",
                    "value": f"{policy.default_position_pct:.0f}%",
                },
                {"label": "Bracket orders", "value": "Enabled for preview design"},
            ],
        },
        {
            "title": "Permissions",
            "items": [
                {"label": "Shorts", "value": "Disabled"},
                {"label": "Live trading", "value": "Disabled"},
                {
                    "label": "Broker submission",
                    "value": "Enabled" if policy.broker_submit_enabled else "Disabled",
                },
                {"label": "Policy source", "value": "Env plus optional local JSON"},
            ],
        },
    ]

def policy_summary() -> dict[str, str]:
    policy = PortfolioPolicy.from_env()
    state = "enabled" if policy.broker_submit_enabled else "disabled"
    return {
        "headline": "Portfolio policy is loaded from local controls.",
        "detail": (
            f"Broker submission is {state}; policy values are visible before every paper run."
        ),
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
    return "warn" if _source_is_degraded(source) else "pass"

def _readiness_status_class(verdict: str) -> str:
    if verdict == "ready_for_paper_validation":
        return "pass"
    if verdict == "context_only_source_health":
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
                "reason": str(payload["reason"]),
                "status_class": "warn" if kind == "source_health" else "block",
            }
        )
    return rows

def _provider_readiness_row(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "label": str(row["label"]),
        "category": _label_text(str(row["category"])),
        "purpose": str(row["purpose"]),
        "required_label": "Required now" if row["required_now"] is True else "Planned",
        "status": str(row["status"]),
        "status_class": str(row["status_class"]),
        "key_label": str(row["key_label"]),
        "detail": str(row["detail"]),
    }

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
