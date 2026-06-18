from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy.exc import SQLAlchemyError

from agency.api.reports import RuntimeSelectionReportsUnavailable, runtime_selection_reports
from agency.api.risk import RuntimeRiskDecisionsUnavailable, runtime_risk_decisions
from agency.contracts import (
    ContractName,
    contract_names,
    load_contract_schema,
    validate_contract,
)
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import build_live_readiness, list_source_health, runtime_metrics_text
from agency.runtime.artifact_fallbacks import (
    artifact_fallback_enabled,
    runtime_source_health_artifacts,
)
from agency.runtime.data_load_status import load_data_load_status
from agency.runtime.data_refresh_progress import (
    data_refresh_status_path,
    load_data_refresh_progress,
)
from agency.runtime.full_live_readiness import load_full_live_readiness
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.runtime.operational_filters import is_non_operational_payload
from agency.runtime.provider_readiness import load_provider_readiness

router = APIRouter()
SourceHealthReader = Callable[[Any], Awaitable[list[dict[str, object]]]]
SessionProvider = Callable[[], AbstractAsyncContextManager[Any]]
MetricsPayloadProvider = Callable[[], Awaitable[list[dict[str, object]]]]
SOURCE_HEALTH_TIMEOUT_SECONDS = 4.0
STATUS_SNAPSHOT_TIMEOUT_SECONDS = 8.0
STATUS_SNAPSHOT_CACHE_TTL_SECONDS = 15.0
STATUS_SNAPSHOT_TIMEOUT_CACHE_TTL_SECONDS = 1.0
DATA_SOURCE_STATUSES = {"HEALTHY", "DEGRADED", "STALE", "UNAVAILABLE", "RATE_LIMITED"}
FRESHNESS_STATUSES = {"FRESH", "AGING", "STALE", "UNAVAILABLE"}

CONTRACT_NAMES: tuple[ContractName, ...] = contract_names()
_status_snapshot_cache: dict[str, object] = {
    "expires_at": 0.0,
    "payload": None,
    "builder_id": 0,
}
_status_snapshot_inflight: asyncio.Task[dict[str, object]] | None = None
_status_snapshot_cache_lock = asyncio.Lock()
REPO_ROOT = Path(__file__).resolve().parents[3]
STATUS_DATA_PROOF_FILES = (
    REPO_ROOT
    / "research"
    / "results"
    / "latest-live-runtime-cycle"
    / "live-runtime-cycle-summary.json",
    REPO_ROOT / "research" / "results" / "latest-live-runtime-cycle" / "source-health.json",
)
STATUS_MASSIVE_LANE_MANIFEST_ROOT = (
    REPO_ROOT / "research" / "data" / "manifests" / "massive_lanes"
)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "trading-agency-v3"}


@router.get("/contracts")
def contracts() -> list[dict[str, str]]:
    return contract_summaries()


@router.get("/contracts/{contract_name}")
def contract_schema(contract_name: str) -> dict[str, Any]:
    if contract_name not in CONTRACT_NAMES:
        raise HTTPException(status_code=404, detail="unknown contract")
    return load_contract_schema(contract_name)


@router.get("/status/data-sources")
async def data_source_status() -> list[dict[str, object]]:
    snapshot = await runtime_status_snapshot_with_timeout()
    return [dict(row) for row in _mapping_rows(snapshot.get("data_sources"))]


@router.get("/status/live-readiness")
async def live_readiness_status() -> dict[str, object]:
    return await runtime_live_readiness()


@router.get("/status/data-refresh")
def data_refresh_progress() -> dict[str, object]:
    return load_data_refresh_progress()


@router.get("/status/data-load")
async def data_load_status() -> dict[str, object]:
    snapshot = await runtime_status_snapshot_with_timeout()
    return _compact_data_load_status(_mapping(snapshot.get("data_load_status")))


@router.get("/status/full-live-readiness")
async def full_live_readiness() -> dict[str, object]:
    snapshot = await runtime_status_snapshot_with_timeout()
    return _compact_full_live_readiness_status(_mapping(snapshot.get("full_live_readiness")))


@router.get("/status/live-config")
def live_config_readiness() -> dict[str, object]:
    return load_live_config_readiness()


@router.get("/status/provider-readiness")
def provider_readiness() -> dict[str, object]:
    return load_provider_readiness()


@router.get("/metrics")
async def metrics() -> Response:
    return Response(
        content=await runtime_metrics(),
        media_type="text/plain; version=0.0.4",
    )


def contract_summaries() -> list[dict[str, str]]:
    return [_contract_summary(name) for name in CONTRACT_NAMES]


def unavailable_data_source_status(reason: str) -> list[dict[str, object]]:
    checked_at = datetime.now(UTC).isoformat()
    payload: dict[str, object] = {
        "schema_version": "0.1.0",
        "source": "source-health-monitor",
        "source_tier": "MARKET_DATA",
        "status": "UNAVAILABLE",
        "checked_at": checked_at,
        "freshness": "UNAVAILABLE",
        "last_success_at": None,
        "observed_lag_seconds": None,
        "error_count": 0,
        "reliability_score": 0.0,
        "rate_limit_reset_at": None,
        "notes": [reason, "no_live_source_health_rows"],
    }
    validate_contract("data-source-health", payload)
    return [payload]


def _source_health_origin_label(source_health: list[dict[str, object]]) -> str:
    if any(str(row.get("source") or "") == "source-health-monitor" for row in source_health):
        return "source-health monitor unavailable"
    if any(_has_artifact_fallback_note(row) for row in source_health):
        return "runtime artifact fallback"
    return "live runtime source-health reader"


async def runtime_data_source_status(
    *,
    session_provider: SessionProvider = get_session,
    reader: SourceHealthReader = list_source_health,
    artifact_root: Path | None = None,
) -> list[dict[str, object]]:
    payload = await runtime_data_source_status_with_load_status(
        session_provider=session_provider,
        reader=reader,
        artifact_root=artifact_root,
    )
    return [dict(row) for row in _mapping_rows(payload.get("data_sources"))]


async def runtime_data_source_status_with_load_status(
    *,
    session_provider: SessionProvider = get_session,
    reader: SourceHealthReader = list_source_health,
    artifact_root: Path | None = None,
) -> dict[str, object]:
    payloads = await _runtime_data_source_payloads(
        session_provider=session_provider,
        reader=reader,
        artifact_root=artifact_root,
    )
    load_status = await _load_data_load_status_async(
        source_health_rows=payloads,
        source_health_origin=_source_health_origin_label(payloads),
    )
    data_sources = _with_unified_readiness_overlay(payloads, load_status=load_status)
    for payload in data_sources:
        validate_contract("data-source-health", payload)
    return {
        "data_sources": data_sources,
        "data_load_status": load_status,
    }


async def runtime_status_snapshot_with_timeout(
    *,
    timeout_seconds: float = STATUS_SNAPSHOT_TIMEOUT_SECONDS,
) -> dict[str, object]:
    global _status_snapshot_inflight

    cached = _status_snapshot_cache_payload()
    if cached is not None:
        return cached
    async with _status_snapshot_cache_lock:
        cached = _status_snapshot_cache_payload()
        if cached is not None:
            return cached
        task = _status_snapshot_inflight
        if task is None or task.done():
            task = asyncio.create_task(_build_runtime_status_snapshot())
            _status_snapshot_inflight = task
            task.add_done_callback(_store_status_snapshot_task_result)
    try:
        snapshot = await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
    except TimeoutError:
        snapshot = _timeout_status_snapshot("runtime status snapshot timed out")
        _store_status_snapshot(
            snapshot,
            ttl_seconds=STATUS_SNAPSHOT_TIMEOUT_CACHE_TTL_SECONDS,
        )
        return _copy_mapping(snapshot)
    _store_status_snapshot(
        snapshot,
        ttl_seconds=STATUS_SNAPSHOT_CACHE_TTL_SECONDS,
    )
    return _copy_mapping(snapshot)


async def warm_runtime_status_snapshot_cache(
    *,
    timeout_seconds: float = 45.0,
) -> bool:
    """Prime the runtime status cache so the first operator screen has proof."""

    try:
        await runtime_status_snapshot_with_timeout(timeout_seconds=timeout_seconds)
    except Exception:
        return False
    return True


def _store_status_snapshot_task_result(
    task: asyncio.Task[dict[str, object]],
) -> None:
    global _status_snapshot_inflight

    try:
        snapshot = task.result()
    except BaseException:
        if _status_snapshot_inflight is task:
            _status_snapshot_inflight = None
        return
    _store_status_snapshot(
        snapshot,
        ttl_seconds=STATUS_SNAPSHOT_CACHE_TTL_SECONDS,
    )
    if _status_snapshot_inflight is task:
        _status_snapshot_inflight = None


async def _build_runtime_status_snapshot() -> dict[str, object]:
    payloads = await _runtime_data_source_payloads(
        session_provider=get_session,
        reader=list_source_health,
        artifact_root=None,
    )
    source_origin = _source_health_origin_label(payloads)
    load_status = await _load_data_load_status_async(
        source_health_rows=payloads,
        source_health_origin=source_origin,
    )
    data_sources = _with_unified_readiness_overlay(payloads, load_status=load_status)
    for payload in data_sources:
        validate_contract("data-source-health", payload)
    data_refresh = await asyncio.to_thread(load_data_refresh_progress)
    full_live = await asyncio.to_thread(
        load_full_live_readiness,
        data_refresh=data_refresh,
        data_load_status=load_status,
    )
    generated_at = datetime.now(UTC).isoformat()
    return {
        "schema_version": "0.1.0",
        "generated_at": generated_at,
        "status_class": "pass",
        "detail": "Runtime status snapshot loaded from live source health and lane-state proof.",
        "data_sources": data_sources,
        "data_load_status": load_status,
        "full_live_readiness": full_live,
    }


def _status_snapshot_cache_payload() -> dict[str, object] | None:
    payload = _status_snapshot_cache.get("payload")
    expires_at = _status_snapshot_cache.get("expires_at", 0.0)
    if (
        isinstance(payload, Mapping)
        and isinstance(expires_at, float)
        and expires_at > time.monotonic()
        and _status_snapshot_cache.get("builder_id") == _status_snapshot_builder_id()
    ):
        return _copy_mapping(payload)
    return None


def _store_status_snapshot(
    snapshot: Mapping[str, object],
    *,
    ttl_seconds: float,
) -> None:
    _status_snapshot_cache["payload"] = _copy_mapping(snapshot)
    _status_snapshot_cache["expires_at"] = time.monotonic() + ttl_seconds
    _status_snapshot_cache["builder_id"] = _status_snapshot_builder_id()


def _status_snapshot_builder_id() -> int:
    return hash(
        (
            id(list_source_health),
            id(load_data_load_status),
            id(load_full_live_readiness),
            runtime_status_data_proof_version(),
        )
    )


def runtime_status_data_proof_version() -> int:
    """Return a cheap version for files that prove current runtime/data state."""

    paths = [*STATUS_DATA_PROOF_FILES, data_refresh_status_path()]
    if STATUS_MASSIVE_LANE_MANIFEST_ROOT.is_dir():
        paths.extend(sorted(STATUS_MASSIVE_LANE_MANIFEST_ROOT.glob("*.json")))
    return hash(tuple(_path_version(path) for path in paths))


def _path_version(path: Path) -> tuple[str, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), 0, 0)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _timeout_status_snapshot(reason: str) -> dict[str, object]:
    checked_at = datetime.now(UTC).isoformat()
    data_refresh = load_data_refresh_progress()
    data_sources = unavailable_data_source_status(
        "live status snapshot did not finish inside the operator budget"
    )
    data_load = _timeout_data_load_status(
        checked_at=checked_at,
        data_refresh=data_refresh,
    )
    full_live = {
        "schema_version": "0.1.0",
        "ready": False,
        "review_operational_ready": False,
        "tradable_ready": False,
        "full_universe_tradable": False,
        "readiness_scope": "status_delayed",
        "readiness_scope_label": "Status Delayed",
        "verdict": "status_timeout",
        "state": "loading",
        "status_label": "Status delayed",
        "status_class": "warn",
        "headline": "Agency status proof is still loading.",
        "detail": (
            "The readiness reader exceeded the operator budget. Refresh the status "
            "panel after the runtime cache warms before using paper-trade controls."
        ),
        "blocker_count": 0,
        "warning_count": 1,
        "blockers": [],
        "warnings": [
            {
                "kind": "status",
                "item": "full-live readiness",
                "reason": "Status generation exceeded the operator budget.",
            }
        ],
        "data_refresh": data_refresh,
        "data_load_status": data_load,
        "active_refresh": _timeout_active_refresh(data_refresh),
        "provider_usage": [],
        "coverage": {
            "overall_percent": 0,
            "core_dataset_percent": 0,
            "critical_lane_percent": 0,
            "expected_ticker_count": 0,
            "market_flow_status_label": "Status delayed",
            "critical_agent_ready_label": "Status delayed",
        },
        "next_actions": [
            "Refresh the status panel after the runtime cache warms; do not submit paper orders from delayed status."
        ],
    }
    return {
        "schema_version": "0.1.0",
        "generated_at": checked_at,
        "status_class": "warn",
        "detail": reason,
        "data_sources": data_sources,
        "data_load_status": data_load,
        "full_live_readiness": full_live,
    }


def _timeout_data_load_status(
    *,
    checked_at: str,
    data_refresh: Mapping[str, object],
) -> dict[str, object]:
    is_loading = data_refresh.get("state") == "running"
    detail = str(
        data_refresh.get("detail")
        or (
            "The data-load proof is still being generated. Do not treat this as "
            "ready or unavailable until the status refresh completes."
        )
    )
    lane_states = _timeout_lane_states(data_refresh)
    status_label = "Data is still loading" if is_loading else "Status delayed"
    status = "loading" if is_loading else "status_delayed"
    return {
        "schema_version": "0.1.0",
        "ready": False,
        "tradable_ready": False,
        "review_operational_ready": False,
        "full_universe_tradable": False,
        "status": status,
        "state": status,
        "status_label": status_label,
        "status_class": "warn",
        "headline": status_label,
        "detail": detail,
        "generated_at": checked_at,
        "status_checked_at": checked_at,
        "source_read_origin": "status snapshot timeout with live refresh progress",
        "progress": {
            "percent_complete": data_refresh.get("percent_complete", 0),
            "eta_label": data_refresh.get("eta_label", "not available"),
            "updated_at": data_refresh.get("updated_at", "not recorded"),
        },
        "market_flow_summary": {
            "usable_ticker_count": 0,
            "expected_ticker_count": 0,
            "status_label": status_label,
            "status_class": "warn",
        },
        "source_summary": {
            "total_count": 0,
            "verified_current_count": 0,
            "warning_count": 1,
            "critical_warning_count": 0,
            "status_label": status_label,
            "status_class": "warn",
        },
        "lane_states": lane_states,
        "freshness_rows": [],
        "blockers": [],
        "warnings": [
            {
                "kind": "status",
                "item": "data-load proof",
                "reason": detail,
            }
        ],
        "blocker_count": 0,
        "warning_count": 1,
    }


def _timeout_active_refresh(data_refresh: Mapping[str, object]) -> dict[str, object]:
    return {
        "state": data_refresh.get("state", "unknown"),
        "status_label": data_refresh.get("status_label", "Status delayed"),
        "status_class": data_refresh.get("status_class", "warn"),
        "eta_label": data_refresh.get("eta_label", "checking"),
        "percent_complete": data_refresh.get("percent_complete", 0),
        "dataset_rows": [],
        "detail": data_refresh.get("detail")
        or "Refresh proof is not available inside the status budget.",
    }


def _timeout_lane_states(data_refresh: Mapping[str, object]) -> list[dict[str, object]]:
    rows = _mapping_rows(data_refresh.get("massive_lanes"))
    lane_states: list[dict[str, object]] = []
    for row in rows:
        state = str(row.get("state") or "")
        if state != "running":
            continue
        label = str(row.get("label") or row.get("lane_id") or "Data lane")
        progress = str(row.get("progress_label") or "not tracked")
        detail = str(row.get("detail") or data_refresh.get("detail") or "")
        lane_states.append(
            {
                "lane_id": row.get("lane_id"),
                "label": label,
                "lane_kind": "raw_acquisition",
                "state": "loading",
                "analysis_state": "loading",
                "required_now": row.get("required_now", True),
                "blocks_execution": row.get("blocks_execution", True),
                "effective_blocks_execution": row.get("blocks_execution", True),
                "blocker": True,
                "ready_for_review": False,
                "ready_for_paper_execution": False,
                "source_dataset": row.get("raw_source_dataset") or row.get("dataset"),
                "status_label": "Data is still loading",
                "status_class": "warn",
                "progress_label": progress,
                "progress_percent": row.get("percent_complete", data_refresh.get("percent_complete", 0)),
                "eta_label": row.get("eta_label", data_refresh.get("eta_label", "not available")),
                "latest_as_of": row.get("latest_as_of"),
                "checked_at": row.get("updated_at") or data_refresh.get("updated_at"),
                "operator_message": f"{label} data is still loading ({progress}). {detail}".strip(),
                "recommended_action": f"Wait for {label} to finish, then refresh the dashboard.",
            }
        )
    return lane_states


def _compact_full_live_readiness_status(readiness: Mapping[str, object]) -> dict[str, object]:
    coverage = _mapping(readiness.get("coverage"))
    active_refresh = _mapping(readiness.get("active_refresh"))
    data_refresh = _mapping(readiness.get("data_refresh"))
    data_load = _mapping(readiness.get("data_load_status"))
    return {
        "schema_version": str(readiness.get("schema_version") or "0.1.0"),
        "generated_at": readiness.get("generated_at"),
        "ready": readiness.get("ready") is True,
        "review_operational_ready": readiness.get("review_operational_ready") is True,
        "tradable_ready": readiness.get("tradable_ready") is True,
        "full_universe_tradable": readiness.get("full_universe_tradable") is True,
        "readiness_scope": readiness.get("readiness_scope"),
        "readiness_scope_label": readiness.get("readiness_scope_label"),
        "verdict": readiness.get("verdict"),
        "state": readiness.get("state"),
        "status_label": readiness.get("status_label"),
        "status_class": readiness.get("status_class"),
        "headline": readiness.get("headline"),
        "detail": readiness.get("detail"),
        "blocker_count": readiness.get("blocker_count"),
        "warning_count": readiness.get("warning_count"),
        "coverage": dict(coverage),
        "active_refresh": _compact_active_refresh(active_refresh),
        "data_refresh": _compact_status_document(data_refresh),
        "data_load_status": _compact_status_document(data_load),
        "provider_usage": _mapping_rows(readiness.get("provider_usage"))[:5],
        "blockers": _mapping_rows(readiness.get("blockers"))[:8],
        "warnings": _mapping_rows(readiness.get("warnings"))[:8],
        "next_actions": list(readiness.get("next_actions") or [])[:5]
        if isinstance(readiness.get("next_actions"), list)
        else [],
    }


def _compact_data_load_status(status: Mapping[str, object]) -> dict[str, object]:
    scalar_keys = (
        "schema_version",
        "generated_at",
        "status_checked_at",
        "source_read_origin",
        "ready",
        "tradable_ready",
        "review_operational_ready",
        "full_universe_tradable",
        "state",
        "status",
        "status_label",
        "status_class",
        "headline",
        "detail",
        "mode_label",
        "overall_percent",
        "core_dataset_percent",
        "critical_lane_percent",
        "expected_ticker_count",
        "cycle_id",
        "signal_count",
        "as_of",
        "blocker_count",
        "warning_count",
    )
    output = {key: status[key] for key in scalar_keys if key in status}
    output["progress"] = _compact_status_document(_mapping(status.get("progress")))
    for key in (
        "source_summary",
        "dataset_summary",
        "agent_summary",
        "market_flow_summary",
        "health_monitor",
    ):
        output[key] = _compact_summary(_mapping(status.get(key)))
    output["datasets"] = [
        _compact_data_load_dataset_row(row)
        for row in _mapping_rows(status.get("datasets"))
    ]
    output["lanes"] = [
        _compact_data_load_lane_row(row)
        for row in _mapping_rows(status.get("lanes"))
    ]
    output["lane_states"] = [
        _compact_data_load_lane_row(row)
        for row in _mapping_rows(status.get("lane_states"))
    ]
    output["freshness_rows"] = [
        _compact_data_load_freshness_row(row)
        for row in _mapping_rows(status.get("freshness_rows"))
    ]
    output["blockers"] = [
        _compact_issue_row(row)
        for row in _mapping_rows(status.get("blockers"))[:12]
    ]
    output["warnings"] = [
        _compact_issue_row(row)
        for row in _mapping_rows(status.get("warnings"))[:12]
    ]
    output["subscription_email_status"] = _compact_subscription_email_status(
        _mapping(status.get("subscription_email_status"))
    )
    return output


def _compact_summary(row: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "status",
        "status_label",
        "status_class",
        "headline",
        "detail",
        "fresh_count",
        "blocked_count",
        "warning_count",
        "ready_label",
        "critical_ready_label",
        "usable_ticker_count",
        "expected_ticker_count",
    )
    return {key: row[key] for key in keys if key in row}


def _compact_data_load_dataset_row(row: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "dataset",
        "label",
        "status",
        "status_label",
        "status_class",
        "detail",
        "coverage_pct",
        "loaded_ticker_count",
        "expected_ticker_count",
        "produced_count",
        "expected_count",
        "row_count",
        "max_as_of",
        "source_status",
        "source_freshness",
    )
    return {key: row[key] for key in keys if key in row}


def _compact_data_load_lane_row(row: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "lane",
        "lane_id",
        "label",
        "group",
        "lane_kind",
        "raw_lanes_required",
        "state",
        "analysis_state",
        "required_now",
        "blocks_execution",
        "effective_blocks_execution",
        "blocker",
        "ready_for_review",
        "ready_for_paper_execution",
        "source_dataset",
        "status",
        "status_label",
        "status_class",
        "detail",
        "coverage_pct",
        "produced_count",
        "expected_count",
        "loaded_ticker_count",
        "expected_ticker_count",
        "row_count",
        "progress_label",
        "progress_percent",
        "eta_label",
        "latest_as_of",
        "checked_at",
        "source_status",
        "source_freshness",
        "source_proof_label",
        "window_label",
        "manifest_path",
        "refresh_action_available",
        "refresh_action_label",
        "refresh_action_url",
        "refresh_action_method",
        "refresh_action_detail",
        "refresh_action_disabled_reason",
        "operator_message",
        "recommended_action",
    )
    return {key: row[key] for key in keys if key in row}


def _compact_data_load_freshness_row(row: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "source",
        "label",
        "critical",
        "status",
        "status_class",
        "freshness",
        "last_success_at",
        "checked_at",
        "detail",
    )
    return {key: row[key] for key in keys if key in row}


def _compact_issue_row(row: Mapping[str, object]) -> dict[str, object]:
    keys = ("kind", "item", "reason", "detail", "status_class")
    return {key: row[key] for key in keys if key in row}


def _compact_subscription_email_status(row: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "status",
        "status_label",
        "status_class",
        "detail",
        "progress_label",
        "progress_percent",
        "processed_email_count",
        "article_links_found",
        "linked_content_attempted",
        "linked_content_succeeded",
        "linked_content_failed",
        "linked_content_processing",
        "linked_content_skipped",
        "login_required",
        "summary_count",
        "updated_at",
        "current_action_label",
        "current_article_url",
        "affected_tickers_label",
        "mini_cycle_status_label",
        "mini_cycle_ticker_rows",
        "next_action",
        "continue_action_url",
        "continue_button_label",
    )
    output = {key: row[key] for key in keys if key in row}
    mini_rows = output.get("mini_cycle_ticker_rows")
    if isinstance(mini_rows, list):
        output["mini_cycle_ticker_rows"] = [
            dict(item) for item in mini_rows[:12] if isinstance(item, Mapping)
        ]
    return output


def _compact_active_refresh(active_refresh: Mapping[str, object]) -> dict[str, object]:
    dataset_rows = _mapping_rows(active_refresh.get("dataset_rows"))
    output = _compact_status_document(active_refresh)
    output["dataset_rows"] = dataset_rows[:8]
    output["dataset_row_count"] = len(dataset_rows)
    output["dataset_rows_truncated_count"] = max(0, len(dataset_rows) - 8)
    return output


def _compact_status_document(payload: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "schema_version",
        "generated_at",
        "updated_at",
        "state",
        "status",
        "status_label",
        "status_class",
        "headline",
        "detail",
        "ready",
        "tradable_ready",
        "review_operational_ready",
        "full_universe_tradable",
        "eta_label",
        "percent_complete",
        "progress_label",
        "source_read_origin",
    )
    return {key: payload[key] for key in keys if key in payload}


async def _load_data_load_status_async(**kwargs: object) -> dict[str, object]:
    started = time.perf_counter()
    status = await asyncio.to_thread(load_data_load_status, **kwargs)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    output = dict(status)
    output.setdefault("status_generation_ms", elapsed_ms)
    if "source_health_origin" in kwargs:
        output.setdefault("source_read_origin", str(kwargs["source_health_origin"]))
    return output


async def _runtime_data_source_payloads(
    *,
    session_provider: SessionProvider,
    reader: SourceHealthReader,
    artifact_root: Path | None,
) -> list[dict[str, object]]:
    try:
        async with session_provider() as session:
            payloads = await reader(session)
    except (MissingDatabaseConfigurationError, OSError, SQLAlchemyError):
        payloads = _artifact_source_health(artifact_root=artifact_root)
        if not payloads:
            return unavailable_data_source_status(
                "live source-health reader failed or database is unavailable"
            )
    payloads = [
        payload
        for payload in payloads
        if not _non_operational_source_health_row(payload)
    ]
    if not payloads:
        payloads = _artifact_source_health(artifact_root=artifact_root)
    if not payloads:
        return unavailable_data_source_status("live source-health reader returned no rows")
    return payloads


def _with_unified_readiness_overlay(
    payloads: list[dict[str, object]],
    *,
    load_status: Mapping[str, object] | None = None,
) -> list[dict[str, object]]:
    if load_status is None:
        load_status = load_data_load_status(
            source_health_rows=payloads,
            source_health_origin=_source_health_origin_label(payloads),
        )
    readiness_by_source = {
        str(row.get("source") or ""): row
        for row in _mapping_rows(load_status.get("freshness_rows"))
        if str(row.get("source") or "")
    }
    output: list[dict[str, object]] = []
    for payload in payloads:
        source = str(payload.get("source") or "")
        readiness = readiness_by_source.get(source)
        if not readiness:
            output.append(payload)
            continue
        merged = dict(payload)
        readiness_can_override = _readiness_row_can_overlay_source(
            payload,
            readiness,
        )
        status = str(readiness.get("status") or "").upper()
        if readiness_can_override and status in DATA_SOURCE_STATUSES:
            merged["status"] = status
        freshness = str(readiness.get("freshness") or "").upper()
        if readiness_can_override and freshness in FRESHNESS_STATUSES:
            merged["freshness"] = freshness
        checked_at = _latest_iso_datetime(
            _valid_iso_datetime(merged.get("checked_at")),
            _valid_iso_datetime(readiness.get("checked_at")),
        )
        if checked_at:
            merged["checked_at"] = checked_at
        last_success_at = _valid_iso_datetime(readiness.get("last_success_at"))
        if readiness_can_override and last_success_at:
            merged["last_success_at"] = last_success_at
        detail = str(readiness.get("detail") or "").strip()
        if detail:
            notes_value = merged.get("notes")
            note_values = notes_value if isinstance(notes_value, list) else []
            notes = [
                str(note)
                for note in note_values
                if str(note).strip()
            ]
            note = f"unified_readiness_override: {detail}"
            if note not in notes:
                notes.append(note)
            merged["notes"] = notes
        output.append(merged)
    return output


def _readiness_row_can_overlay_source(
    payload: Mapping[str, object],
    readiness: Mapping[str, object],
) -> bool:
    payload_lane = str(payload.get("lane_id") or "").strip()
    readiness_lane = str(readiness.get("lane_id") or "").strip()
    if payload_lane and readiness_lane and payload_lane == readiness_lane:
        return True
    payload_checked = _valid_iso_datetime(payload.get("checked_at"))
    readiness_checked = _valid_iso_datetime(readiness.get("checked_at"))
    if payload_checked is None:
        return True
    if readiness_checked is None:
        return False
    latest = _latest_iso_datetime(payload_checked, readiness_checked)
    return latest == readiness_checked


def _valid_iso_datetime(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"not checked", "not recorded"}:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return text


def _latest_iso_datetime(left: str | None, right: str | None) -> str | None:
    if left is None:
        return right
    if right is None:
        return left
    left_dt = datetime.fromisoformat(left.replace("Z", "+00:00"))
    right_dt = datetime.fromisoformat(right.replace("Z", "+00:00"))
    return right if right_dt > left_dt else left


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _artifact_source_health(
    *,
    artifact_root: Path | None,
) -> list[dict[str, object]]:
    if not artifact_fallback_enabled():
        return []
    return [
        _with_artifact_fallback_note(payload)
        for payload in runtime_source_health_artifacts(artifact_root=artifact_root)
        if not _non_operational_source_health_row(payload)
    ]


def _with_artifact_fallback_note(payload: dict[str, object]) -> dict[str, object]:
    output = dict(payload)
    notes = output.get("notes", [])
    normalized_notes = [
        str(note)
        for note in (notes if isinstance(notes, list) else [])
        if str(note).strip()
    ]
    if "runtime_artifact_fallback" not in normalized_notes:
        normalized_notes.append("runtime_artifact_fallback")
    output["notes"] = normalized_notes
    return output


def _has_artifact_fallback_note(payload: Mapping[str, object]) -> bool:
    notes = payload.get("notes", [])
    if not isinstance(notes, list):
        return False
    return "runtime_artifact_fallback" in {str(note) for note in notes}


async def runtime_data_source_status_with_timeout(
    *,
    timeout_seconds: float = SOURCE_HEALTH_TIMEOUT_SECONDS,
) -> list[dict[str, object]]:
    snapshot = await runtime_status_snapshot_with_timeout(timeout_seconds=timeout_seconds)
    return [dict(row) for row in _mapping_rows(snapshot.get("data_sources"))]


def _non_operational_source_health_row(payload: dict[str, object]) -> bool:
    return is_non_operational_payload(payload)


async def runtime_metrics(
    *,
    source_status_provider: MetricsPayloadProvider | None = None,
    selection_report_provider: MetricsPayloadProvider | None = None,
    risk_decision_provider: MetricsPayloadProvider | None = None,
) -> str:
    source_provider = (
        _default_source_status if source_status_provider is None else source_status_provider
    )
    selection_provider = (
        _default_selection_reports
        if selection_report_provider is None
        else selection_report_provider
    )
    risk_provider = (
        _default_risk_decisions
        if risk_decision_provider is None
        else risk_decision_provider
    )
    return runtime_metrics_text(
        source_health=await source_provider(),
        selection_reports=await selection_provider(),
        risk_decisions=await risk_provider(),
    )


async def runtime_live_readiness(
    *,
    source_status_provider: MetricsPayloadProvider | None = None,
    selection_report_provider: MetricsPayloadProvider | None = None,
    risk_decision_provider: MetricsPayloadProvider | None = None,
) -> dict[str, object]:
    source_provider = (
        _default_source_status if source_status_provider is None else source_status_provider
    )
    selection_provider = (
        _default_selection_reports
        if selection_report_provider is None
        else selection_report_provider
    )
    risk_provider = (
        _default_risk_decisions
        if risk_decision_provider is None
        else risk_decision_provider
    )
    source_health = await source_provider()
    data_load = await asyncio.to_thread(
        load_data_load_status,
        source_health_rows=source_health,
        source_health_origin=_source_health_origin_label(source_health),
    )
    return build_live_readiness(
        source_health=source_health,
        selection_reports=await selection_provider(),
        risk_decisions=await risk_provider(),
        lane_states=_mapping_list(data_load.get("lane_states")),
    )


def _mapping_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _copy_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return copy.deepcopy(dict(value))


async def _default_source_status() -> list[dict[str, object]]:
    return await runtime_data_source_status()


async def _default_selection_reports() -> list[dict[str, object]]:
    try:
        return await runtime_selection_reports(
            limit=200,
            prefer_latest_artifact=True,
        )
    except RuntimeSelectionReportsUnavailable:
        return []


async def _default_risk_decisions() -> list[dict[str, object]]:
    try:
        return await runtime_risk_decisions(
            limit=200,
            prefer_latest_artifact=True,
        )
    except RuntimeRiskDecisionsUnavailable:
        return []


def _contract_summary(contract: ContractName) -> dict[str, str]:
    schema = load_contract_schema(contract)
    return {
        "name": contract,
        "schema_id": str(schema["$id"]),
        "version": str(schema.get("x-version", "unversioned")),
        "title": str(schema["title"]),
    }
