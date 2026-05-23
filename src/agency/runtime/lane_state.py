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
    "abnormal_volume": ("massive_live_trade_slices",),
    "buy_sell_pressure": ("massive_live_trade_slices",),
    "block_trade_pressure": ("massive_live_trade_slices", "massive_block_trade_feed"),
    "unusual_trade_activity": ("massive_live_trade_slices",),
    "pre_market_unusual_activity": ("massive_premarket_trade_slices",),
    "market_flow_trend": ("massive_live_trade_slices",),
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
        if str(row.get("source") or "")
    }
    states = [
        _raw_lane_state(row, source_by_name=source_by_name, now=current)
        for row in _sequence_mappings(data_refresh.get("massive_lanes"))
    ]
    states.extend(
        _derived_lane_state(
            row,
            dataset_by_name=dataset_by_name,
            source_by_name=source_by_name,
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


def _raw_lane_state(
    row: Mapping[str, object],
    *,
    source_by_name: Mapping[str, Mapping[str, object]],
    now: datetime,
) -> dict[str, object]:
    lane_id = _text(row.get("lane_id"), "unknown_raw_lane")
    label = _text(row.get("label"), _title(lane_id))
    required_now = _bool(row.get("required_now"), True)
    blocks_execution = _bool(row.get("blocks_execution"), lane_id in RAW_EXECUTION_LANES)
    raw_state = _state_text(row)
    source_row = source_by_name.get(_source_for_raw_lane(lane_id), {})
    state = _raw_state(row, raw_state, required_now=required_now, blocks_execution=blocks_execution)
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
        latest_as_of=_text(row.get("latest_as_of") or row.get("fetched_at"), ""),
        checked_at=now.isoformat(),
        freshness_seconds=_int_or_none(row.get("freshness_seconds")),
        eta_seconds=_int(row.get("eta_seconds"), 0),
        eta_label=_text(row.get("eta_label"), "not available"),
        progress_label=_text(row.get("progress_label"), "not tracked"),
        issues=_strings(row.get("issues")),
        reason_code=_text(row.get("reason_code"), raw_state),
        source_status=_text(source_row.get("status") or row.get("source_status"), ""),
        source_freshness=_text(source_row.get("freshness") or row.get("source_freshness"), ""),
        detail=_text(row.get("detail"), ""),
        original_status_class=_text(row.get("status_class"), ""),
    )


def _derived_lane_state(
    row: Mapping[str, object],
    *,
    dataset_by_name: Mapping[str, Mapping[str, object]],
    source_by_name: Mapping[str, Mapping[str, object]],
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
    return _state_payload(
        lane_id=lane_id,
        lane_kind="derived_signal",
        label=label,
        state=state,
        source_dataset=source_dataset,
        raw_lanes_required=RAW_LANE_REQUIREMENTS.get(lane_id, ()),
        required_now=required_now,
        blocks_execution=blocks_execution,
        analysis_state=_text(row.get("analysis_state"), _analysis_state_for_state(state)),
        latest_as_of=_text(
            row.get("latest_as_of")
            or dataset.get("max_as_of")
            or dataset.get("source_last_success_at"),
            "",
        ),
        checked_at=now.isoformat(),
        freshness_seconds=_int_or_none(row.get("freshness_seconds")),
        eta_seconds=_int(row.get("eta_seconds"), 0),
        eta_label=_text(row.get("eta_label"), "not available"),
        progress_label=_derived_progress_label(row),
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
        detail=_text(row.get("detail"), ""),
        original_status_class=_text(row.get("status_class"), ""),
    )


def _raw_state(
    row: Mapping[str, object],
    raw_state: str,
    *,
    required_now: bool,
    blocks_execution: bool,
) -> str:
    if not required_now or raw_state == "disabled":
        return "disabled_optional"
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
    if analysis_state == "loading" or row_status == "loading":
        return "loading"
    if _source_unavailable(row, dataset, source_row):
        return "provider_unavailable"
    if _source_needs_refresh(row, dataset, source_row):
        return "needs_refresh"
    if analysis_state == "loaded_unanalyzed":
        return "loaded_unanalyzed"
    produced = _int(row.get("produced_count"), 0)
    expected = _int_or_none(row.get("expected_count"))
    if produced <= 0 and (expected is None or expected > 0) and _source_available(row, dataset):
        return "loaded_unanalyzed"
    if analysis_state == "analyzed_needs_refresh" or row_status == "warning":
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
    issues: Sequence[str],
    reason_code: str,
    source_status: str,
    source_freshness: str,
    detail: str,
    original_status_class: str,
) -> dict[str, object]:
    blocker = blocks_execution and required_now and state in {
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
        label=label,
        detail=detail,
        issues=issues,
        progress_label=progress_label,
    )
    return {
        "lane_id": lane_id,
        "lane_kind": lane_kind,
        "label": label,
        "state": state,
        "status_label": STATE_LABELS[state],
        "status_class": status_class,
        "operator_message": operator_message,
        "recommended_action": _recommended_action(state, label=label, lane_kind=lane_kind),
        "analysis_state": analysis_state,
        "required_now": required_now,
        "blocks_execution": blocks_execution,
        "blocker": blocker,
        "ready_for_review": ready_for_review,
        "ready_for_paper_execution": ready_for_execution,
        "source_dataset": source_dataset,
        "raw_lanes_required": list(raw_lanes_required),
        "freshness_seconds": freshness_seconds,
        "latest_as_of": latest_as_of or "not recorded",
        "checked_at": checked_at,
        "eta_seconds": eta_seconds,
        "eta_label": eta_label,
        "progress_label": progress_label,
        "issues": list(issues),
        "reason_code": reason_code,
        "source_status": source_status or "UNKNOWN",
        "source_freshness": source_freshness or "UNKNOWN",
    }


def _lane_status_class(
    state: str,
    *,
    blocker: bool,
    original_status_class: str,
) -> str:
    if blocker:
        return "block"
    if state == "ready_for_paper_execution":
        return "pass"
    if state == "ready_for_review":
        return "warn" if original_status_class == "warn" else "pass"
    if state in {"loading", "loaded_unanalyzed", "needs_refresh"}:
        return "warn"
    if state == "disabled_optional":
        return "neutral"
    return "block"


def _operator_message(
    state: str,
    *,
    label: str,
    detail: str,
    issues: Sequence[str],
    progress_label: str,
) -> str:
    evidence = detail or (issues[0] if issues else "")
    if state == "loading":
        return (
            f"{label} data is still loading"
            + (f" ({progress_label})." if progress_label and progress_label != "not tracked" else ".")
        )
    if state == "loaded_unanalyzed":
        return f"{label} source data exists, but the agent has not produced current analysis."
    if state == "needs_refresh":
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


def _source_for_raw_lane(lane_id: str) -> str:
    if lane_id == "massive_daily_bars":
        return "daily-market-bars"
    return "massive-stock-trades"


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
