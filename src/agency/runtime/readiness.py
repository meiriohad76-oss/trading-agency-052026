from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import cast

from agency.runtime.readiness_sources import relevant_source_health, used_sources

DEGRADED_SOURCE_STATUSES = {"DEGRADED", "STALE", "UNAVAILABLE", "RATE_LIMITED"}
DEGRADED_FRESHNESS = {"AGING", "STALE", "UNAVAILABLE"}
REVIEWABLE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER", "WATCH", "HOLD"}
LIVE_PIT_CYCLE_PREFIX = "live-pit-"


def build_live_readiness(
    *,
    source_health: Sequence[Mapping[str, object]],
    selection_reports: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
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
        "degraded_source_count": len(_source_blockers(active_source_health)),
        "selection_report_count": len(cycle_reports),
        "risk_decision_count": len(cycle_risks),
        "reviewable_candidate_count": _reviewable_count(cycle_reports),
        "open_risk_decision_count": _open_risk_count(cycle_risks),
        "blocked_risk_decision_count": _blocked_risk_count(cycle_risks),
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
    cycle_id: str | None,
) -> list[dict[str, object]]:
    blockers: list[dict[str, object]] = []
    if cycle_id is None:
        blockers.append(_blocker("no_runtime_cycle", "runtime", "No runtime cycle found."))
    if not source_health:
        blockers.append(_blocker("source_health_missing", "sources", "No source-health rows."))
    blockers.extend(_source_blockers(source_health))
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
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in source_health:
        status = str(source.get("status", "UNKNOWN"))
        freshness = str(source.get("freshness", "UNKNOWN"))
        if status in DEGRADED_SOURCE_STATUSES or freshness in DEGRADED_FRESHNESS:
            rows.append(
                _blocker(
                    "source_health",
                    str(source.get("source", "unknown")),
                    f"{status} / {freshness}; {_first_note(source)}",
                )
            )
    return rows


def _blocker(kind: str, item: str | None, reason: str) -> dict[str, object]:
    return {"kind": kind, "item": item or "runtime", "reason": reason}


def _verdict(blockers: Sequence[Mapping[str, object]]) -> str:
    kinds = {str(blocker["kind"]) for blocker in blockers}
    if "no_runtime_cycle" in kinds:
        return "no_runtime_cycle"
    if "source_health_missing" in kinds or "source_health" in kinds:
        return "context_only_source_health"
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
    live_cycle_id = _first_cycle_id(selection_reports, risk_decisions, live_pit_only=True)
    if live_cycle_id is not None:
        return live_cycle_id
    return _first_cycle_id(selection_reports, risk_decisions, live_pit_only=False)


def _first_cycle_id(
    selection_reports: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
    *,
    live_pit_only: bool,
) -> str | None:
    for payload in (*selection_reports, *risk_decisions):
        cycle_id = payload.get("cycle_id")
        if (
            isinstance(cycle_id, str)
            and cycle_id
            and (not live_pit_only or cycle_id.startswith(LIVE_PIT_CYCLE_PREFIX))
        ):
            return cycle_id
    return None


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
