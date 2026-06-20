from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

RAW_EXECUTION_LANES = {
    "massive_daily_bars",
    "massive_live_trade_slices",
    "massive_premarket_trade_slices",
    "massive_block_trade_feed",
}
DERIVED_EXECUTION_LANES = {
    "abnormal_volume",
    "technical_analysis",
    "buy_sell_pressure",
    "block_trade_pressure",
    "unusual_trade_activity",
    "pre_market_unusual_activity",
    "market_flow_trend",
}
RAW_LANE_REQUIREMENTS = {
    "technical_analysis": ("massive_daily_bars",),
    "abnormal_volume": ("massive_daily_bars",),
    "buy_sell_pressure": ("massive_live_trade_slices",),
    "block_trade_pressure": ("massive_live_trade_slices", "massive_block_trade_feed"),
    "unusual_trade_activity": ("massive_live_trade_slices",),
    "pre_market_unusual_activity": ("massive_premarket_trade_slices",),
    "market_flow_trend": ("massive_live_trade_slices",),
    "backtest_feature_builder": ("massive_daily_bars", "massive_backtest_trade_tape"),
    "sector_momentum": ("massive_daily_bars",),
    "options_flow": ("massive_options_flow",),
    "options_anomaly": ("massive_options_flow",),
}
RAW_LANE_SOURCE_MAP = {
    "massive_daily_bars": "daily-market-bars",
    "massive_live_trade_slices": "massive-stock-trades",
    "massive_premarket_trade_slices": "massive-stock-trades",
    "massive_block_trade_feed": "massive-stock-trades",
    "massive_backtest_trade_tape": "massive-stock-trades",
    "massive_options_flow": "massive-options-flow",
}
FOUNDATIONAL_RAW_PROOF_LANES = {
    "massive_daily_bars",
    "massive_live_trade_slices",
    "massive_premarket_trade_slices",
}

LOADING_STATES = {"loading", "pending", "planned", "running"}
REFRESH_STATES = {"stale", "needs_refresh", "unverified", "expired"}
UNAVAILABLE_STATES = {
    "blocked",
    "failed",
    "missing",
    "missing_manifest",
    "provider_unavailable",
    "rate_limited",
    "unavailable",
}
PARTIAL_USABLE_STATES = {"partial", "partial_usable", "ready_with_gaps"}
READY_STATES = {"complete", "pass", "ready", "skipped"}
REFRESHABLE_RAW_LANES = {
    "massive_daily_bars": "Refresh Daily Bars",
    "massive_live_trade_slices": "Refresh Live Trade Slices",
    "massive_premarket_trade_slices": "Refresh Premarket Trade Slices",
    "massive_block_trade_feed": "Refresh Block Trade Feed",
    "massive_backtest_trade_tape": "Refresh Backtest Trade Tape",
    "massive_reference": "Refresh Massive Reference",
    "massive_options_flow": "Refresh Options Flow",
}
RUNNABLE_RAW_LANES = {
    "massive_daily_bars",
    "massive_live_trade_slices",
    "massive_premarket_trade_slices",
    "massive_block_trade_feed",
    "massive_backtest_trade_tape",
}

STATE_LABELS = {
    "loading": "Data is still loading",
    "loaded_unanalyzed": "Data exists but agent has not analyzed it",
    "needs_refresh": "Analysis exists but needs refresh",
    "provider_unavailable": "Provider unavailable",
    "ready_for_review": "Ready for review",
    "ready_for_paper_execution": "Ready for paper execution",
    "disabled_optional": "Not required for current workflow",
}


def build_lane_states(
    *,
    data_refresh: Mapping[str, object],
    dataset_rows: Sequence[Mapping[str, object]],
    lane_rows: Sequence[Mapping[str, object]],
    source_health_rows: Sequence[Mapping[str, object]] = (),
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Normalize raw acquisition and derived signal lane readiness."""

    current = _utc(now)
    dataset_by_name = {
        str(row.get("dataset") or ""): row
        for row in dataset_rows
        if str(row.get("dataset") or "")
    }
    source_by_name = {
        str(row.get("source") or ""): row
        for row in source_health_rows
        if str(row.get("source") or "") and not str(row.get("lane_id") or "")
    }
    for row in source_health_rows:
        source = str(row.get("source") or "")
        if source and source not in source_by_name:
            source_by_name[source] = row
    source_by_lane = {
        str(row.get("lane_id") or ""): row
        for row in source_health_rows
        if str(row.get("lane_id") or "")
    }
    raw_states = [
        _raw_lane_state(row, source_by_name=source_by_name, source_by_lane=source_by_lane, now=current)
        for row in _sequence_mappings(data_refresh.get("massive_lanes"))
    ]
    raw_state_by_id = {
        str(row.get("lane_id") or ""): row
        for row in raw_states
        if str(row.get("lane_id") or "")
    }
    states = list(raw_states)
    states.extend(
        _derived_lane_state(
            row,
            dataset_by_name=dataset_by_name,
            source_by_name=source_by_name,
            raw_state_by_id=raw_state_by_id,
            now=current,
        )
        for row in lane_rows
    )
    return states


def lane_state_blockers(
    lane_states: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "kind": str(row.get("lane_kind") or "lane_state"),
            "item": str(row.get("lane_id") or "unknown"),
            "reason": str(
                row.get("operator_message")
                or row.get("recommended_action")
                or "Lane is not ready for execution."
            ),
            "status_class": str(row.get("status_class") or "block"),
        }
        for row in lane_states
        if row.get("blocker") is True
    ]


def lane_state_review_blockers(
    lane_states: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    review_blocking_states = {"loading", "loaded_unanalyzed", "provider_unavailable"}
    return [
        {
            "kind": str(row.get("lane_kind") or "lane_state"),
            "item": str(row.get("lane_id") or "unknown"),
            "reason": str(
                row.get("operator_message")
                or row.get("recommended_action")
                or "Lane is not ready for review."
            ),
            "status_class": str(row.get("status_class") or "block"),
        }
        for row in lane_states
        if row.get("required_now") is not False
        and (
            row.get("blocker") is True
            or row.get("blocks_execution") is True
        )
        and str(row.get("state") or "") in review_blocking_states
        and row.get("ready_for_review") is not True
    ]


def _raw_lane_state(
    row: Mapping[str, object],
    *,
    source_by_name: Mapping[str, Mapping[str, object]],
    source_by_lane: Mapping[str, Mapping[str, object]],
    now: datetime,
) -> dict[str, object]:
    lane_id = _text(row.get("lane_id"), "unknown_raw_lane")
    label = _text(row.get("label"), _title(lane_id))
    required_now = _bool(row.get("required_now"), True)
    blocks_execution = _bool(row.get("blocks_execution"), lane_id in RAW_EXECUTION_LANES)
    raw_state = _state_text(row)
    source_row = source_by_lane.get(lane_id) or source_by_name.get(_source_for_raw_lane(lane_id), {})
    raw_source_row = source_row if _raw_source_row_applies(lane_id, source_row) else {}
    state = _raw_state(
        row,
        raw_state,
        source_row=raw_source_row,
        required_now=required_now,
        blocks_execution=blocks_execution,
    )
    latest_as_of = _text(row.get("latest_as_of") or row.get("fetched_at"), "")
    detail = _text(row.get("detail") or raw_source_row.get("detail"), "")
    source_detail = _text(raw_source_row.get("detail"), "")
    if state == "provider_unavailable" and source_detail:
        detail = source_detail
    issue_detail = _provider_issue_detail(row)
    if (
        state == "provider_unavailable"
        and issue_detail
        and issue_detail not in detail
        and not _has_provider_access_evidence(detail)
    ):
        detail = f"{detail} {issue_detail}".strip()
    return _state_payload(
        lane_id=lane_id,
        lane_kind="raw_acquisition",
        label=label,
        state=state,
        source_dataset=_text(
            row.get("raw_source_dataset") or row.get("dataset"),
            _source_dataset_for_raw_lane(lane_id),
        ),
        raw_lanes_required=(),
        required_now=required_now,
        blocks_execution=blocks_execution,
        analysis_state=_analysis_state_for_state(state, raw=True),
        latest_as_of=latest_as_of,
        checked_at=_proof_timestamp(row, raw_source_row, fallback=latest_as_of or now.isoformat()),
        freshness_seconds=_int_or_none(row.get("freshness_seconds")),
        eta_seconds=_int(row.get("eta_seconds"), 0),
        eta_label=_text(row.get("eta_label"), "not available"),
        progress_label=_text(row.get("progress_label"), "not tracked"),
        progress_percent=_progress_percent(row),
        issues=_strings(row.get("issues")),
        reason_code=_text(row.get("reason_code"), raw_state),
        source_status=_text(raw_source_row.get("status") or row.get("source_status"), ""),
        source_freshness=_text(
            raw_source_row.get("freshness") or row.get("source_freshness"),
            "",
        ),
        detail=detail,
        original_status_class=_text(row.get("status_class"), ""),
        window_label=_text(row.get("window_label"), ""),
        manifest_path=_text(row.get("manifest_path"), ""),
    )


def _derived_lane_state(
    row: Mapping[str, object],
    *,
    dataset_by_name: Mapping[str, Mapping[str, object]],
    source_by_name: Mapping[str, Mapping[str, object]],
    raw_state_by_id: Mapping[str, Mapping[str, object]],
    now: datetime,
) -> dict[str, object]:
    lane_id = _text(row.get("lane"), "unknown_signal_lane")
    label = _text(row.get("label"), _title(lane_id))
    source_dataset = _text(row.get("source_dataset"), "unknown")
    dataset = dataset_by_name.get(source_dataset, {})
    source_row = source_by_name.get(_source_for_dataset(source_dataset), {})
    required_now = _bool(row.get("required_now"), True)
    blocks_execution = _bool(row.get("blocks_execution"), lane_id in DERIVED_EXECUTION_LANES)
    state = _derived_state(row, dataset, source_row, required_now=required_now)
    raw_requirements = RAW_LANE_REQUIREMENTS.get(lane_id, ())
    state, raw_requirement_detail, blocking_raw_row = _apply_raw_requirement_state(
        state,
        raw_requirements=raw_requirements,
        raw_state_by_id=raw_state_by_id,
        produced_count=_int(row.get("produced_count"), 0),
        source_freshness=_text(
            row.get("source_freshness")
            or dataset.get("source_freshness")
            or source_row.get("freshness"),
            "",
        ),
    )
    raw_blocked = bool(blocking_raw_row)
    latest_as_of = _text(
        row.get("latest_as_of")
        or dataset.get("max_as_of")
        or dataset.get("source_last_success_at"),
        "",
    )
    progress_row = blocking_raw_row if raw_blocked else row
    payload = _state_payload(
        lane_id=lane_id,
        lane_kind="derived_signal",
        label=label,
        state=state,
        source_dataset=source_dataset,
        raw_lanes_required=raw_requirements,
        required_now=required_now,
        blocks_execution=blocks_execution,
        analysis_state=_analysis_state_for_state(state)
        if raw_blocked
        else _text(row.get("analysis_state"), _analysis_state_for_state(state)),
        latest_as_of=latest_as_of,
        checked_at=_proof_timestamp(
            progress_row,
            source_row,
            dataset,
            fallback=latest_as_of or now.isoformat(),
        ),
        freshness_seconds=_int_or_none(progress_row.get("freshness_seconds")),
        eta_seconds=_int(progress_row.get("eta_seconds"), 0),
        eta_label=_text(progress_row.get("eta_label"), "not available"),
        progress_label=_derived_progress_label(row)
        if not raw_blocked
        else _text(progress_row.get("progress_label"), "not tracked"),
        progress_percent=_progress_percent(progress_row),
        issues=_strings(row.get("issues")),
        reason_code=_text(row.get("reason_code"), _text(row.get("status"), "")),
        source_status=_text(
            row.get("source_status") or dataset.get("source_status") or source_row.get("status"),
            "",
        ),
        source_freshness=_text(
            row.get("source_freshness")
            or dataset.get("source_freshness")
            or source_row.get("freshness"),
            "",
        ),
        detail=_combine_details(_text(row.get("detail"), ""), raw_requirement_detail),
        original_status_class=_text(row.get("status_class"), ""),
        window_label=_text(row.get("window_label"), ""),
        manifest_path=_text(row.get("manifest_path"), ""),
    )
    payload["produced_count"] = _int(row.get("produced_count"), 0)
    expected_count = _int_or_none(row.get("expected_count"))
    if expected_count is not None:
        payload["expected_count"] = expected_count
    if raw_blocked:
        payload["blocking_raw_lane_id"] = _text(blocking_raw_row.get("lane_id"), "")
    return payload


def _raw_state(
    row: Mapping[str, object],
    raw_state: str,
    *,
    source_row: Mapping[str, object],
    required_now: bool,
    blocks_execution: bool,
) -> str:
    if _provider_access_unavailable(row):
        return "provider_unavailable"
    if not required_now or raw_state == "disabled":
        return "disabled_optional"
    if _source_unavailable(row, {}, source_row):
        return "provider_unavailable"
    if raw_state in LOADING_STATES:
        return "loading"
    if raw_state in REFRESH_STATES:
        return "needs_refresh"
    if raw_state in UNAVAILABLE_STATES:
        return "provider_unavailable"
    if raw_state in PARTIAL_USABLE_STATES:
        return "ready_for_review"
    if raw_state in READY_STATES:
        return "ready_for_paper_execution" if blocks_execution else "ready_for_review"
    status_class = _text(row.get("status_class"), "")
    if status_class == "pass":
        return "ready_for_paper_execution" if blocks_execution else "ready_for_review"
    if status_class == "warn" and _has_usable_progress(row):
        return "ready_for_review"
    if status_class == "warn":
        return "needs_refresh"
    if status_class == "block":
        return "provider_unavailable"
    return "loaded_unanalyzed"


def _raw_source_row_applies(
    lane_id: str,
    source_row: Mapping[str, object],
) -> bool:
    source_lane_id = _text(source_row.get("lane_id"), "")
    if not source_lane_id:
        return True
    return source_lane_id == lane_id


def _provider_access_unavailable(row: Mapping[str, object]) -> bool:
    haystack = " ".join(
        [
            _text(row.get("detail"), ""),
            _text(row.get("reason"), ""),
            " ".join(_strings(row.get("issues"))),
        ]
    ).casefold()
    return any(
        marker in haystack
        for marker in (
            "403 forbidden",
            "401 unauthorized",
            "provider returned 403",
            "provider returned 401",
            "api key",
            "account plan",
            "endpoint entitlement",
            "access denied",
            "permission",
        )
    )


def _provider_issue_detail(row: Mapping[str, object]) -> str:
    reasons = [
        _text(issue.get("reason") or issue.get("detail"), "")
        for issue in _sequence_mappings(row.get("issues"))
    ]
    reasons = [reason for reason in reasons if reason]
    if not reasons:
        return ""
    preview = "; ".join(reasons[:3])
    if len(reasons) > 3:
        preview = f"{preview}; and {len(reasons) - 3} more issue(s)"
    return f"Provider issue proof: {preview}."


def _has_provider_access_evidence(value: object) -> bool:
    text = str(value or "").casefold()
    return any(
        marker in text
        for marker in (
            "403 forbidden",
            "401 unauthorized",
            "api key",
            "account plan",
            "endpoint entitlement",
            "access denied",
        )
    )


def _derived_state(
    row: Mapping[str, object],
    dataset: Mapping[str, object],
    source_row: Mapping[str, object],
    *,
    required_now: bool,
) -> str:
    if not required_now:
        return "disabled_optional"
    analysis_state = _text(row.get("analysis_state"), "")
    row_status = _text(row.get("status"), "")
    if _source_unavailable(row, dataset, source_row):
        return "provider_unavailable"
    if _source_needs_refresh(row, dataset, source_row):
        return "needs_refresh"
    if analysis_state == "loading" or row_status == "loading":
        return "loading"
    if analysis_state == "loaded_unanalyzed":
        return "loaded_unanalyzed"
    produced = _int(row.get("produced_count"), 0)
    expected = _int_or_none(row.get("expected_count"))
    if produced <= 0 and (expected is None or expected > 0) and _source_available(row, dataset):
        return "loaded_unanalyzed"
    if analysis_state == "analyzed_needs_refresh":
        return "needs_refresh"
    partial_output = expected is not None and 0 < produced < expected
    if partial_output and _source_available(row, dataset):
        return "ready_for_review"
    if row_status == "warning":
        return "needs_refresh"
    if row_status == "blocked":
        return "provider_unavailable"
    if analysis_state == "analyzed_current" or row_status == "ready":
        return (
            "ready_for_paper_execution"
            if _text(row.get("group"), "") == "critical"
            else "ready_for_review"
        )
    return "loaded_unanalyzed"


def _state_payload(
    *,
    lane_id: str,
    lane_kind: str,
    label: str,
    state: str,
    source_dataset: str,
    raw_lanes_required: Sequence[str],
    required_now: bool,
    blocks_execution: bool,
    analysis_state: str,
    latest_as_of: str,
    checked_at: str,
    freshness_seconds: int | None,
    eta_seconds: int,
    eta_label: str,
    progress_label: str,
    progress_percent: int,
    issues: Sequence[str],
    reason_code: str,
    source_status: str,
    source_freshness: str,
    detail: str,
    original_status_class: str,
    window_label: str,
    manifest_path: str,
) -> dict[str, object]:
    effective_blocks_execution = blocks_execution and required_now
    blocker = effective_blocks_execution and state in {
        "loading",
        "loaded_unanalyzed",
        "needs_refresh",
        "provider_unavailable",
    }
    ready_for_review = state in {"ready_for_review", "ready_for_paper_execution"}
    ready_for_execution = state == "ready_for_paper_execution"
    status_class = _lane_status_class(
        state,
        blocker=blocker,
        original_status_class=original_status_class,
    )
    operator_message = _operator_message(
        state,
        lane_kind=lane_kind,
        label=label,
        detail=detail,
        issues=issues,
        progress_label=progress_label,
    )
    refresh_action = _refresh_action_payload(
        lane_id=lane_id,
        lane_kind=lane_kind,
        raw_lanes_required=raw_lanes_required,
        source_dataset=source_dataset,
    )
    source_proof_label = _source_proof_label(
        source_status=source_status,
        source_freshness=source_freshness,
        checked_at=checked_at,
        manifest_path=manifest_path,
    )
    return {
        "lane_id": lane_id,
        "lane_kind": lane_kind,
        "label": label,
        "state": state,
        "status_label": _status_label_for_lane(state, lane_kind),
        "status_class": status_class,
        "original_status_class": original_status_class,
        "operator_message": operator_message,
        "recommended_action": _recommended_action(state, label=label, lane_kind=lane_kind),
        "analysis_state": analysis_state,
        "required_now": required_now,
        "blocks_execution": blocks_execution,
        "effective_blocks_execution": effective_blocks_execution,
        "blocker": blocker,
        "ready_for_review": ready_for_review,
        "ready_for_paper_execution": ready_for_execution,
        "source_dataset": source_dataset,
        "raw_lanes_required": list(raw_lanes_required),
        "freshness_seconds": freshness_seconds,
        "latest_as_of": _latest_as_of_label(state, latest_as_of),
        "checked_at": checked_at or "checked during current request",
        "eta_seconds": eta_seconds,
        "eta_label": eta_label,
        "progress_label": progress_label,
        "progress_percent": progress_percent,
        "issues": list(issues),
        "reason_code": reason_code,
        "source_status": source_status or "UNKNOWN",
        "source_freshness": source_freshness or "UNKNOWN",
        "source_proof_label": source_proof_label,
        "window_label": window_label or "not recorded",
        "manifest_path": manifest_path or "not recorded",
        **refresh_action,
    }


def _lane_status_class(
    state: str,
    *,
    blocker: bool,
    original_status_class: str,
) -> str:
    if state in {"loading", "loaded_unanalyzed", "needs_refresh"}:
        return "warn"
    if state == "ready_for_paper_execution":
        return "pass"
    if state == "ready_for_review":
        return "warn" if original_status_class == "warn" else "pass"
    if state == "disabled_optional":
        return "neutral"
    if blocker:
        return "block"
    return "block"


def _operator_message(
    state: str,
    *,
    lane_kind: str,
    label: str,
    detail: str,
    issues: Sequence[str],
    progress_label: str,
) -> str:
    evidence = detail or (issues[0] if issues else "")
    if state == "loading":
        message = (
            f"{label} data is still loading"
            + (f" ({progress_label})." if progress_label and progress_label != "not tracked" else ".")
        )
        return f"{message} {evidence}".strip()
    if state == "loaded_unanalyzed":
        return f"{label} source data exists, but the agent has not produced current analysis."
    if state == "needs_refresh":
        if lane_kind == "raw_acquisition":
            return f"{label} lane proof needs refresh. {evidence}".strip()
        return f"{label} analysis exists but needs refresh. {evidence}".strip()
    if state == "provider_unavailable":
        return f"{label} provider or proof is unavailable. {evidence}".strip()
    if state == "ready_for_paper_execution":
        return f"{label} is ready for paper execution."
    if state == "ready_for_review":
        suffix = f" {evidence}" if evidence else ""
        if issues:
            return f"{label} is partial but usable for review.{suffix}".strip()
        return f"{label} is usable for review{suffix}".strip()
    return f"{label} is optional for the current workflow."


def _status_label_for_lane(state: str, lane_kind: str) -> str:
    if state == "needs_refresh" and lane_kind == "raw_acquisition":
        return "Lane proof needs refresh"
    return STATE_LABELS.get(state, state.replace("_", " ").title())


def _recommended_action(state: str, *, label: str, lane_kind: str) -> str:
    if state == "loading":
        return f"Wait for {label} to finish, then refresh the dashboard."
    if state == "loaded_unanalyzed":
        agent = "agent" if lane_kind == "derived_signal" else "lane analyzer"
        return f"Run the {label} {agent} before paper execution."
    if state == "needs_refresh":
        return f"Refresh {label} using the lane refresh action."
    if state == "provider_unavailable":
        return f"Check the provider credentials or manifest for {label}, then retry refresh."
    if state == "ready_for_paper_execution":
        return "No lane action required before paper execution."
    if state == "ready_for_review":
        return "Use for review with the displayed caution before paper execution."
    return "No action required unless this lane becomes part of today's workflow."


def _latest_as_of_label(state: str, latest_as_of: str) -> str:
    if latest_as_of:
        return latest_as_of
    if state == "disabled_optional":
        return "not required for current workflow"
    if state == "loading":
        return "loading now"
    if state == "loaded_unanalyzed":
        return "source loaded; analysis pending"
    if state == "needs_refresh":
        return "latest proof needs refresh"
    if state == "provider_unavailable":
        return "provider proof unavailable"
    return "proof checked; latest data time unavailable"


def _refresh_action_payload(
    *,
    lane_id: str,
    lane_kind: str,
    raw_lanes_required: Sequence[str],
    source_dataset: str,
) -> dict[str, object]:
    target_lane = _refresh_target_lane(
        lane_id=lane_id,
        lane_kind=lane_kind,
        raw_lanes_required=raw_lanes_required,
        source_dataset=source_dataset,
    )
    if target_lane in RUNNABLE_RAW_LANES:
        return {
            "refresh_action_available": True,
            "refresh_action_label": REFRESHABLE_RAW_LANES.get(target_lane, "Refresh data lane"),
            "refresh_action_url": f"/scheduler/massive-lanes/{target_lane}/refresh",
            "refresh_action_method": "post",
            "refresh_action_detail": (
                "Runs this data lane through the scheduler's trade-aware policy."
            ),
            "refresh_action_disabled_reason": "",
        }
    if target_lane in REFRESHABLE_RAW_LANES:
        return {
            "refresh_action_available": False,
            "refresh_action_label": "Refresh not exposed",
            "refresh_action_url": "",
            "refresh_action_method": "post",
            "refresh_action_detail": (
                "This lane is tracked for health, but the scheduler has no runnable "
                "manual refresh job for it yet."
            ),
            "refresh_action_disabled_reason": (
                f"{REFRESHABLE_RAW_LANES[target_lane]} is not enabled as a manual lane refresh."
            ),
        }
    return {
        "refresh_action_available": False,
        "refresh_action_label": "No direct refresh",
        "refresh_action_url": "",
        "refresh_action_method": "post",
        "refresh_action_detail": "Use the Command refresh queue to inspect available jobs.",
        "refresh_action_disabled_reason": "No scheduler refresh action is attached to this lane.",
    }


def _refresh_target_lane(
    *,
    lane_id: str,
    lane_kind: str,
    raw_lanes_required: Sequence[str],
    source_dataset: str,
) -> str:
    if lane_id in REFRESHABLE_RAW_LANES:
        return lane_id
    if lane_kind == "derived_signal":
        for raw_lane in raw_lanes_required:
            if raw_lane in REFRESHABLE_RAW_LANES:
                return raw_lane
    dataset_map = {
        "prices_daily": "massive_daily_bars",
        "stock_trades": "massive_live_trade_slices",
        "daily-market-bars": "massive_daily_bars",
        "massive-stock-trades": "massive_live_trade_slices",
    }
    return dataset_map.get(source_dataset, "")


def _source_proof_label(
    *,
    source_status: str,
    source_freshness: str,
    checked_at: str,
    manifest_path: str,
) -> str:
    status = _plain_source_status(source_status)
    freshness = "Needs refresh" if source_freshness.upper() == "STALE" else source_freshness
    proof = checked_at or "not checked"
    manifest = manifest_path if manifest_path else "manifest path unavailable"
    return f"Provider {status}; freshness {freshness or 'UNKNOWN'}; checked {proof}; {manifest}"


def _plain_source_status(value: object) -> str:
    status = str(value or "UNKNOWN").strip().upper()
    if status == "STALE":
        return "Needs refresh"
    if status == "AGING":
        return "Aging"
    return status or "UNKNOWN"


def _analysis_state_for_state(state: str, *, raw: bool = False) -> str:
    if state == "loading":
        return "loading"
    if state == "loaded_unanalyzed":
        return "loaded_unanalyzed"
    if state == "needs_refresh":
        return "analyzed_needs_refresh"
    if state == "provider_unavailable":
        return "data_void"
    if state in {"ready_for_review", "ready_for_paper_execution"}:
        return "raw_ready" if raw else "analyzed_current"
    return "not_required"


def _source_unavailable(
    row: Mapping[str, object],
    dataset: Mapping[str, object],
    source_row: Mapping[str, object],
) -> bool:
    values = {
        _text(row.get("source_status"), "").upper(),
        _text(dataset.get("source_status"), "").upper(),
        _text(source_row.get("status"), "").upper(),
    }
    return bool(values.intersection({"UNAVAILABLE", "RATE_LIMITED", "FAILED"}))


def _source_needs_refresh(
    row: Mapping[str, object],
    dataset: Mapping[str, object],
    source_row: Mapping[str, object],
) -> bool:
    values = {
        _text(row.get("source_status"), "").upper(),
        _text(row.get("source_freshness"), "").upper(),
        _text(dataset.get("source_status"), "").upper(),
        _text(dataset.get("source_freshness"), "").upper(),
        _text(source_row.get("status"), "").upper(),
        _text(source_row.get("freshness"), "").upper(),
    }
    return "STALE" in values or "AGING" in values


def _apply_raw_requirement_state(
    state: str,
    *,
    raw_requirements: Sequence[str],
    raw_state_by_id: Mapping[str, Mapping[str, object]],
    produced_count: int,
    source_freshness: str,
) -> tuple[str, str, Mapping[str, object]]:
    raw_rows = [
        raw_state_by_id[lane_id]
        for lane_id in raw_requirements
        if lane_id in raw_state_by_id
        and raw_state_by_id[lane_id].get("required_now") is not False
        and _raw_requirement_can_gate(
            raw_state_by_id[lane_id],
            source_freshness=source_freshness,
        )
    ]
    if not raw_rows or state == "disabled_optional":
        return state, "", {}
    provider_row = _first_raw_state(raw_rows, "provider_unavailable")
    if provider_row:
        return "provider_unavailable", _raw_requirement_detail(provider_row), provider_row
    loading_row = _first_raw_state(raw_rows, "loading")
    if loading_row:
        if produced_count <= 0 or state in {"loaded_unanalyzed", "provider_unavailable"}:
            return "loading", _raw_requirement_detail(loading_row), loading_row
        return "needs_refresh", _raw_requirement_detail(loading_row), loading_row
    refresh_row = _first_raw_state(raw_rows, "needs_refresh")
    if refresh_row and state in {
        "loaded_unanalyzed",
        "ready_for_review",
        "ready_for_paper_execution",
        "needs_refresh",
    }:
        return "needs_refresh", _raw_requirement_detail(refresh_row), refresh_row
    return state, "", {}


def _raw_requirement_can_gate(
    row: Mapping[str, object],
    *,
    source_freshness: str,
) -> bool:
    state = _text(row.get("state"), "")
    reason_code = _text(row.get("reason_code"), "").lower()
    lane_id = _text(row.get("lane_id"), "")
    if state != "provider_unavailable" or reason_code not in {
        "manifest_missing",
        "missing_manifest",
    }:
        return True
    if lane_id not in FOUNDATIONAL_RAW_PROOF_LANES:
        return False
    return source_freshness.upper() not in {"FRESH", "PARTIAL"}


def _first_raw_state(
    rows: Sequence[Mapping[str, object]],
    state: str,
) -> Mapping[str, object]:
    return next((row for row in rows if _text(row.get("state"), "") == state), {})


def _raw_requirement_detail(row: Mapping[str, object]) -> str:
    label = _text(row.get("label"), _text(row.get("lane_id"), "Required data source"))
    status = _text(row.get("status_label"), "not ready")
    progress = _text(row.get("progress_label"), "")
    eta = _text(row.get("eta_label"), "")
    message = _text(row.get("operator_message"), "")
    parts = [f"Required data source {label} is {status.lower()}"]
    if progress and progress != "not tracked":
        parts.append(f"progress {progress}")
    if eta and eta != "not available":
        parts.append(f"ETA {eta}")
    if message:
        parts.append(message)
    return "; ".join(parts) + "."


def _combine_details(*values: str) -> str:
    parts: list[str] = []
    for value in values:
        text = value.strip()
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts)


def _source_available(row: Mapping[str, object], dataset: Mapping[str, object]) -> bool:
    values = {
        _text(row.get("source_status"), "").upper(),
        _text(row.get("source_freshness"), "").upper(),
        _text(dataset.get("status"), "").lower(),
        _text(dataset.get("source_status"), "").upper(),
        _text(dataset.get("source_freshness"), "").upper(),
    }
    blocked_values = {"UNAVAILABLE", "RATE_LIMITED", "FAILED", "STALE", "blocked"}
    positive_values = {
        "HEALTHY",
        "FRESH",
        "DEGRADED",
        "PARTIAL",
        "ready",
        "warning",
        "attention",
    }
    return not values.intersection(blocked_values) and bool(values.intersection(positive_values))


def _state_text(row: Mapping[str, object]) -> str:
    for key in ("state", "manifest_status", "health_status", "status"):
        value = _text(row.get(key), "")
        if value:
            return value.lower()
    return ""


def _has_usable_progress(row: Mapping[str, object]) -> bool:
    if _int(row.get("row_count"), 0) > 0:
        return True
    if _int(row.get("ticker_count"), 0) > 0:
        return True
    progress_label = _text(row.get("progress_label"), "")
    return bool(progress_label and progress_label != "not tracked" and not progress_label.startswith("0/"))


def _derived_progress_label(row: Mapping[str, object]) -> str:
    produced = _int(row.get("produced_count"), 0)
    expected = _int_or_none(row.get("expected_count"))
    if expected is None:
        return f"{produced} row(s)"
    return f"{produced}/{expected} row(s)"


def _progress_percent(row: Mapping[str, object]) -> int:
    for key in ("progress_percent", "percent_complete", "coverage_pct", "manifest_coverage_pct"):
        value = _int_or_none(row.get(key))
        if value is not None:
            return max(0, min(100, value))
    produced = _int(row.get("produced_count"), 0)
    expected = _int_or_none(row.get("expected_count"))
    if expected and expected > 0:
        return max(0, min(100, round(produced / expected * 100)))
    fresh = _int(row.get("fresh_ticker_count"), 0)
    pending = _int(row.get("pending_ticker_count"), 0)
    total = fresh + pending
    if total > 0:
        return max(0, min(100, round(fresh / total * 100)))
    return 0


def _proof_timestamp(
    *rows: Mapping[str, object],
    fallback: str = "",
) -> str:
    for row in rows:
        for key in (
            "checked_at",
            "fetched_at",
            "latest_checked_at",
            "last_success_at",
            "source_last_success_at",
            "updated_at",
            "generated_at",
        ):
            value = _text(row.get(key), "")
            if value:
                return value
    return fallback


def _source_for_raw_lane(lane_id: str) -> str:
    return RAW_LANE_SOURCE_MAP.get(lane_id, "massive-stock-trades")


def _source_dataset_for_raw_lane(lane_id: str) -> str:
    if lane_id == "massive_daily_bars":
        return "prices_daily"
    return "stock_trades"


def _source_for_dataset(dataset: str) -> str:
    return {
        "prices_daily": "daily-market-bars",
        "stock_trades": "massive-stock-trades",
        "sec_company_facts": "sec-company-facts",
        "sec_form4": "sec-form4",
        "sec_13f": "sec-13f",
        "news_rss": "rss-news",
        "subscription_emails": "subscription-email-thesis",
    }.get(dataset, "")


def _sequence_mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _text(value: object, fallback: str) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _bool(value: object, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _int(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return fallback


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return None


def _title(value: str) -> str:
    return value.replace("_", " ").title()


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
