from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

from agency.runtime.lane_state import lane_state_review_blockers
from agency.runtime.readiness_sources import relevant_source_health, used_sources

DEGRADED_SOURCE_STATUSES = {"DEGRADED", "STALE", "UNAVAILABLE", "RATE_LIMITED"}
DEGRADED_FRESHNESS = {"AGING", "STALE", "UNAVAILABLE"}
BLOCKING_SOURCE_STATUSES = {"STALE", "UNAVAILABLE", "RATE_LIMITED"}
BLOCKING_FRESHNESS = {"STALE", "UNAVAILABLE"}
REVIEWABLE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER", "WATCH", "HOLD"}
LIVE_CYCLE_PREFIXES = ("live-pit-", "live-ready-")
NON_OPERATIONAL_CYCLE_TOKENS = ("demo", "mock", "fake", "fixture", "manual-smoke")
CRITICAL_SOURCE_NAMES = {"daily-market-bars", "massive-stock-trades"}
SOURCE_HEALTH_MAX_AGE_SECONDS = 30 * 60


def build_live_readiness(
    *,
    source_health: Sequence[Mapping[str, object]],
    selection_reports: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
    lane_states: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Summarize whether the latest runtime cycle is usable for paper review."""
    cycle_id = _latest_cycle_id(selection_reports, risk_decisions)
    cycle_reports = _filter_cycle(selection_reports, cycle_id)
    cycle_risks = _filter_cycle(risk_decisions, cycle_id)
    active_source_health = relevant_source_health(
        source_health,
        used_sources=used_sources(cycle_reports),
    )
    blockers = _blockers(
        source_health=active_source_health,
        selection_reports=cycle_reports,
        risk_decisions=cycle_risks,
        lane_states=lane_states,
        cycle_id=cycle_id,
    )
    verdict = _verdict(blockers)
    ready = verdict == "ready_for_paper_validation"
    return {
        "schema_version": "0.1.0",
        "ready": ready,
        "verdict": verdict,
        "cycle_id": cycle_id,
        "source_count": len(active_source_health),
        "degraded_source_count": len(_degraded_sources(active_source_health)),
        "selection_report_count": len(cycle_reports),
        "risk_decision_count": len(cycle_risks),
        "reviewable_candidate_count": _reviewable_count(cycle_reports),
        "open_risk_decision_count": _open_risk_count(cycle_risks),
        "blocked_risk_decision_count": _blocked_risk_count(cycle_risks),
        "lane_state_blocker_count": len(lane_state_review_blockers(lane_states)),
        "source_status_counts": _counter(active_source_health, "status"),
        "final_action_counts": _counter(cycle_reports, "final_action"),
        "risk_decision_counts": _counter(cycle_risks, "decision"),
        "blockers": blockers,
        "headline": _headline(verdict),
        "detail": _detail(verdict, blockers),
    }


def _blockers(
    *,
    source_health: Sequence[Mapping[str, object]],
    selection_reports: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
    lane_states: Sequence[Mapping[str, object]],
    cycle_id: str | None,
) -> list[dict[str, object]]:
    blockers: list[dict[str, object]] = []
    if cycle_id is None:
        blockers.append(_blocker("no_runtime_cycle", "runtime", "No runtime cycle found."))
    if not source_health:
        blockers.append(_blocker("source_health_missing", "sources", "No source-health rows."))
    blockers.extend(_source_blockers(source_health, lane_states=lane_states))
    blockers.extend(lane_state_review_blockers(lane_states))
    if cycle_id is not None and not selection_reports:
        blockers.append(_blocker("selection_missing", cycle_id, "No selection reports."))
    if selection_reports and _reviewable_count(selection_reports) == 0:
        blockers.append(_blocker("no_reviewable_candidates", cycle_id, "No WATCH/BUY rows."))
    if selection_reports and not risk_decisions:
        blockers.append(_blocker("risk_missing", cycle_id or "runtime", "No risk decisions."))
    if risk_decisions and _open_risk_count(risk_decisions) == 0:
        blockers.append(_blocker("risk_blocked", cycle_id, "All risk decisions are BLOCK."))
    return blockers


def _source_blockers(
    source_health: Sequence[Mapping[str, object]],
    *,
    lane_states: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    review_ready_sources = _review_ready_sources(lane_states)
    for source in source_health:
        source_name = str(source.get("source", "unknown"))
        status = str(source.get("status", "UNKNOWN"))
        freshness = str(source.get("freshness", "UNKNOWN"))
        critical_or_unidentified = (
            source_name in CRITICAL_SOURCE_NAMES
            or source_name in {"unknown", "source-health-monitor"}
        )
        if status in BLOCKING_SOURCE_STATUSES or freshness in BLOCKING_FRESHNESS:
            if critical_or_unidentified:
                rows.append(
                    _blocker(
                        "source_health",
                        source_name,
                        f"{status} / {freshness}; {_first_note(source)}",
                    )
                )
            continue
        if source_name not in CRITICAL_SOURCE_NAMES:
            continue
        if source_name in review_ready_sources:
            continue
        age_seconds = _source_health_age_seconds(source)
        if age_seconds is None:
            rows.append(
                _blocker(
                    "source_health",
                    source_name,
                    "missing checked_at; source-health freshness is unverified",
                )
            )
        elif age_seconds > SOURCE_HEALTH_MAX_AGE_SECONDS:
            rows.append(
                _blocker(
                    "source_health",
                    source_name,
                    f"checked_at is {age_seconds}s old; refresh source-health before review",
                )
            )
    return rows


def _review_ready_sources(
    lane_states: Sequence[Mapping[str, object]],
) -> set[str]:
    sources: set[str] = set()
    for row in lane_states:
        if row.get("ready_for_review") is not True:
            continue
        lane_id = str(row.get("lane_id") or "")
        if lane_id == "massive_daily_bars":
            sources.add("daily-market-bars")
        elif lane_id.startswith("massive_"):
            sources.add("massive-stock-trades")
    return sources


def _degraded_sources(source_health: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [
        source
        for source in source_health
        if str(source.get("status", "UNKNOWN")) in DEGRADED_SOURCE_STATUSES
        or str(source.get("freshness", "UNKNOWN")) in DEGRADED_FRESHNESS
        or _source_health_age_seconds(source) is None
        or (
            (_source_health_age_seconds(source) or 0)
            > SOURCE_HEALTH_MAX_AGE_SECONDS
        )
    ]


def _source_health_age_seconds(source: Mapping[str, object]) -> int | None:
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


def _blocker(kind: str, item: str | None, reason: str) -> dict[str, object]:
    return {"kind": kind, "item": item or "runtime", "reason": reason}


def _verdict(blockers: Sequence[Mapping[str, object]]) -> str:
    kinds = {str(blocker["kind"]) for blocker in blockers}
    if "no_runtime_cycle" in kinds:
        return "no_runtime_cycle"
    if "source_health_missing" in kinds or "source_health" in kinds:
        return "context_only_source_health"
    if "raw_acquisition" in kinds or "derived_signal" in kinds or "lane_state" in kinds:
        return "context_only_lane_state"
    if "selection_missing" in kinds or "no_reviewable_candidates" in kinds:
        return "cycle_waiting_for_candidates"
    if "risk_missing" in kinds:
        return "cycle_waiting_for_risk"
    if "risk_blocked" in kinds:
        return "cycle_blocked_by_risk"
    return "ready_for_paper_validation"


def _headline(verdict: str) -> str:
    headlines = {
        "ready_for_paper_validation": "Live paper cycle is ready for review.",
        "context_only_source_health": "Live paper cycle is context-only.",
        "context_only_lane_state": "Live paper cycle needs lane refresh.",
        "cycle_waiting_for_candidates": "Latest cycle has no reviewable candidates.",
        "cycle_waiting_for_risk": "Latest cycle is waiting for risk decisions.",
        "cycle_blocked_by_risk": "Latest cycle is blocked by risk.",
        "no_runtime_cycle": "No live paper cycle is persisted yet.",
    }
    return headlines.get(verdict, "Live readiness is unknown.")


def _detail(verdict: str, blockers: Sequence[Mapping[str, object]]) -> str:
    if verdict == "ready_for_paper_validation":
        return "Sources, selection reports, and risk decisions are aligned."
    if not blockers:
        return "No blockers were reported."
    return str(blockers[0]["reason"])


def _latest_cycle_id(
    selection_reports: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
) -> str | None:
    cycle_ids: list[str] = []
    seen: set[str] = set()
    for payload in (*selection_reports, *risk_decisions):
        cycle_id = payload.get("cycle_id")
        if isinstance(cycle_id, str) and cycle_id and cycle_id not in seen:
            cycle_ids.append(cycle_id)
            seen.add(cycle_id)
    if not cycle_ids:
        return None
    return max(
        enumerate(cycle_ids),
        key=lambda item: _cycle_sort_key(item[1], index=item[0]),
    )[1]


def _cycle_sort_key(cycle_id: str, *, index: int) -> tuple[int, int, int, int]:
    return (
        _cycle_operational_rank(cycle_id),
        _cycle_timestamp_rank(cycle_id),
        1 if cycle_id.startswith(LIVE_CYCLE_PREFIXES) else 0,
        -index,
    )


def _cycle_operational_rank(cycle_id: str) -> int:
    normalized = cycle_id.casefold()
    return 0 if any(token in normalized for token in NON_OPERATIONAL_CYCLE_TOKENS) else 1


def _cycle_timestamp_rank(cycle_id: str) -> int:
    compact = re.findall(r"(?<!\d)(\d{8})T(\d{4,6})(?:Z)?(?!\d)", cycle_id)
    if compact:
        day, raw_time = compact[-1]
        time_text = raw_time.ljust(6, "0")[:6]
        return int(f"{day}{time_text}")
    dashed = re.findall(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", cycle_id)
    if dashed:
        year, month, day = dashed[-1]
        return int(f"{year}{month}{day}000000")
    date_only = re.findall(r"(?<!\d)(\d{8})(?!\d)", cycle_id)
    if date_only:
        return int(f"{date_only[-1]}000000")
    return -1


def _filter_cycle(
    payloads: Sequence[Mapping[str, object]],
    cycle_id: str | None,
) -> list[Mapping[str, object]]:
    if cycle_id is None:
        return []
    return [payload for payload in payloads if payload.get("cycle_id") == cycle_id]


def _reviewable_count(selection_reports: Sequence[Mapping[str, object]]) -> int:
    return sum(
        1
        for report in selection_reports
        if str(report.get("final_action")) in REVIEWABLE_ACTIONS
    )


def _open_risk_count(risk_decisions: Sequence[Mapping[str, object]]) -> int:
    return sum(1 for decision in risk_decisions if str(decision.get("decision")) != "BLOCK")


def _blocked_risk_count(risk_decisions: Sequence[Mapping[str, object]]) -> int:
    return sum(1 for decision in risk_decisions if str(decision.get("decision")) == "BLOCK")


def _counter(payloads: Sequence[Mapping[str, object]], key: str) -> dict[str, int]:
    counts = Counter(str(payload[key]) for payload in payloads if key in payload)
    return dict(sorted(counts.items()))


def _first_note(source: Mapping[str, object]) -> str:
    notes = source.get("notes", [])
    if not isinstance(notes, list) or not notes:
        return "no note"
    return str(cast(object, notes[0]))
