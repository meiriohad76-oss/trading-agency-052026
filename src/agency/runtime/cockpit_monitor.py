"""Cockpit monitor view helpers.

The cockpit consumes these helpers so user-facing health rows describe what is
known, when it was proven, and what the operator can do next.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

MONITOR_LIVE_WINDOW_SECONDS = 180


def source_health_rows(
    sources: Sequence[object],
    *,
    proof_timestamp: str = "",
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in sources:
        item = _mapping(raw)
        state = source_state(item)
        lane_id = _first_text(item.get("lane_id"), item.get("lane"))
        refresh_url = (
            f"/scheduler/massive-lanes/{lane_id}/refresh"
            if lane_id
            else _first_text(item.get("refresh_url"), item.get("action_url"))
        )
        refresh_action = (
            {"label": "Refresh lane", "url": refresh_url}
            if refresh_url
            else {"label": "No manual lane refresh", "url": ""}
        )
        source_timestamp = _first_text(
            item.get("last_update"),
            item.get("checked_at"),
            item.get("latest_checked_at"),
            item.get("source_timestamp"),
            item.get("source_last_success_at"),
            item.get("updated_at"),
        )
        analysis_timestamp = _first_text(
            item.get("analysis_timestamp"),
            item.get("analyzed_at"),
            item.get("agent_analyzed_at"),
        )
        rows.append(
            {
                "name": _first_text(item.get("name"), item.get("source"), default="Data source"),
                "tier": source_tier(item),
                "state": state["state"],
                "state_label": state["label"],
                "last_pull": source_timestamp or "not reported",
                "proof_timestamp": proof_timestamp or "not reported",
                "source_timestamp": source_timestamp or "not reported",
                "analysis_timestamp": analysis_timestamp or "not reported separately",
                "coverage": _first_text(item.get("coverage_label"), default="coverage not reported"),
                "note": _first_text(item.get("detail"), default="No source note reported."),
                "next_action": state["next_action"],
                "refresh_action": refresh_action,
            }
        )
    return rows


def source_state(source: Mapping[str, object]) -> dict[str, str]:
    status_class = _first_text(source.get("status_class")).lower()
    status_label = _first_text(source.get("status"), source.get("status_label")).lower()
    freshness = _first_text(source.get("freshness"), source.get("freshness_label")).lower()
    has_proof_timestamp = bool(
        _first_text(
            source.get("last_update"),
            source.get("checked_at"),
            source.get("latest_checked_at"),
            source.get("source_timestamp"),
            source.get("source_last_success_at"),
            source.get("updated_at"),
        )
    )
    if (
        status_class == "pass"
        or status_label in {"healthy", "ok", "loaded", "pass"}
        or freshness == "fresh"
    ) and has_proof_timestamp:
        return {
            "state": "ready",
            "label": "Usable with proof timestamp",
            "next_action": "No action needed unless the policy window expires.",
        }
    status_text = " ".join(
        _first_text(source.get(key))
        for key in ("status_class", "status_label", "freshness_label", "detail")
    ).lower()
    if any(token in status_text for token in ("block", "down", "unavailable", "void", "failed", "access")):
        return {
            "state": "unavailable",
            "label": "Source unavailable or access problem",
            "next_action": "Check credentials or provider status, then refresh this lane.",
        }
    if any(token in status_text for token in ("stale", "expired", "needs", "delayed", "not current")):
        return {
            "state": "needs_refresh",
            "label": "Analyzed result needs refresh",
            "next_action": "Refresh this lane, then rerun the agent analysis.",
        }
    if not _first_text(source.get("last_update"), source.get("source_timestamp"), source.get("updated_at")):
        return {
            "state": "not_analyzed",
            "label": "Data access exists; no pull timestamp yet",
            "next_action": "Run the lane refresh so the agent can analyze current data.",
        }
    return {
        "state": "ready",
        "label": "Usable with proof timestamp",
        "next_action": "No action needed unless the policy window expires.",
    }


def monitor_events_from_scheduler(scheduler: Mapping[str, object]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for raw in _list(scheduler.get("running_jobs")):
        item = _mapping(raw)
        lane = _first_text(item.get("lane"), item.get("lane_id"), default="runtime")
        events.append(
            {
                "kind": "running",
                "topic": lane,
                "message": _first_text(item.get("label"), item.get("name"), default="Job running"),
                "timestamp": _first_text(item.get("started_at"), item.get("eta_label"), default="now"),
                "action": "Open lane refresh",
                "action_url": _first_text(
                    item.get("action_url"),
                    default=f"/scheduler/massive-lanes/{lane}/refresh",
                ),
            }
        )
    for raw in _list(scheduler.get("next_jobs")):
        item = _mapping(raw)
        lane = _first_text(item.get("lane"), item.get("lane_id"), default="scheduled")
        events.append(
            {
                "kind": "next",
                "topic": lane,
                "message": _first_text(item.get("label"), item.get("name"), default="Next job"),
                "timestamp": _first_text(item.get("eta_label"), item.get("scheduled_for"), default="scheduled"),
                "action": "Wait for scheduled lane policy",
                "action_url": "",
            }
        )
    return events


def monitor_status_from_scheduler(
    scheduler: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    timestamp = _first_text(
        scheduler.get("latest_event_at"),
        scheduler.get("updated_at"),
        scheduler.get("last_update"),
    )
    parsed = _parse_datetime(timestamp)
    current = now or datetime.now(UTC)
    live = parsed is not None and (current - parsed).total_seconds() <= MONITOR_LIVE_WINDOW_SECONDS
    return {
        "live": live,
        "last_update": timestamp or "not reported",
        "label": (
            "Receiving current monitor updates"
            if live
            else "Monitor updates not observed in the live window"
        ),
        "poll_url": "/api/monitor/status",
    }


def source_tier(source: Mapping[str, object]) -> str:
    name = _first_text(source.get("name"), source.get("source")).lower()
    if "alpaca" in name or "broker" in name:
        return "broker"
    if "massive" in name or "price" in name or "trade" in name:
        return "market"
    if "sec" in name or "edgar" in name:
        return "official"
    if "email" in name or "subscription" in name or "seeking alpha" in name:
        return "paid-sub"
    if "llm" in name:
        return "llm"
    return "operational"


def _parse_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _first_text(*values: object, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default
