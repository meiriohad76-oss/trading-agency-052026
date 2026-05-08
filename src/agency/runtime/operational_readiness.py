from __future__ import annotations

from collections.abc import Mapping, Sequence

from agency.runtime.operational_keys import load_key_statuses

PASS = "PASS"
WARN = "WARN"
BLOCK = "BLOCK"

BLOCKING_DATA_REFRESH_STATES = {"blocked", "failed", "unavailable"}
READY_DATA_REFRESH_STATES = {"complete", "planned"}


def build_operational_readiness(
    *,
    health: Mapping[str, object],
    live_config: Mapping[str, object],
    data_refresh: Mapping[str, object],
    live_readiness: Mapping[str, object],
    paper_review: Mapping[str, object],
    key_statuses: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    keys = list(key_statuses if key_statuses is not None else load_key_statuses(live_config))
    checks = [
        _health_check(health),
        _live_config_check(live_config),
        _data_refresh_check(data_refresh),
        _live_readiness_check(live_readiness),
        _paper_review_check(paper_review),
        _human_review_progress_check(paper_review),
        _paper_mode_check(),
    ]
    blocker_count = _count_status(checks, BLOCK) + _missing_key_count(keys, required=True)
    warning_count = _count_status(checks, WARN) + _missing_key_count(keys, required=False)
    state = _state(blocker_count, warning_count)
    return {
        "schema_version": "0.1.0",
        "ready": blocker_count == 0,
        "state": state,
        "status_label": _status_label(state),
        "status_class": _status_class(state),
        "mode": "paper",
        "broker_execution_enabled": False,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "checks": checks,
        "keys": keys,
        "next_actions": _next_actions(checks, keys),
        "health": dict(health),
        "live_config": dict(live_config),
        "data_refresh": dict(data_refresh),
        "live_readiness": dict(live_readiness),
        "paper_review": dict(paper_review),
    }


def _health_check(health: Mapping[str, object]) -> dict[str, object]:
    if health.get("status") == "ok":
        return _check("API health", PASS, "FastAPI health endpoint reports ok.")
    return _check("API health", BLOCK, "FastAPI health endpoint did not report ok.")


def _live_config_check(live_config: Mapping[str, object]) -> dict[str, object]:
    blockers = _int_field(live_config, "blocker_count")
    warnings = _int_field(live_config, "warning_count")
    if blockers > 0:
        return _check("Live config", BLOCK, f"{blockers} configuration blocker(s).")
    if warnings > 0:
        return _check("Live config", WARN, f"{warnings} configuration warning(s).")
    return _check("Live config", PASS, "Live refresh inputs are configured.")


def _data_refresh_check(data_refresh: Mapping[str, object]) -> dict[str, object]:
    state = str(data_refresh.get("state", "unknown"))
    label = str(data_refresh.get("status_label", state.title()))
    if state in BLOCKING_DATA_REFRESH_STATES:
        return _check("Data refresh", BLOCK, f"Latest data refresh is {label}.")
    if state == "running":
        eta = str(data_refresh.get("eta_label", "unknown"))
        return _check("Data refresh", WARN, f"Data is still loading; ETA {eta}.")
    if state in READY_DATA_REFRESH_STATES:
        return _check("Data refresh", PASS, f"Latest data refresh is {label}.")
    return _check("Data refresh", WARN, f"No complete latest refresh status: {label}.")


def _live_readiness_check(live_readiness: Mapping[str, object]) -> dict[str, object]:
    verdict = str(live_readiness.get("verdict", "unknown"))
    if live_readiness.get("ready") is True:
        return _check("Runtime cycle", PASS, f"Latest cycle is {verdict}.")
    detail = str(live_readiness.get("detail", "Latest cycle is not reviewable."))
    return _check("Runtime cycle", BLOCK, detail)


def _paper_review_check(paper_review: Mapping[str, object]) -> dict[str, object]:
    progress = _mapping_field(paper_review, "progress")
    total_count = _int_field(progress, "total_count")
    if total_count > 0:
        return _check("Paper review queue", PASS, f"{total_count} candidate(s) queued.")
    return _check("Paper review queue", BLOCK, "No paper-review candidates are queued.")


def _human_review_progress_check(paper_review: Mapping[str, object]) -> dict[str, object]:
    progress = _mapping_field(paper_review, "progress")
    pending_count = _int_field(progress, "pending_count")
    reviewed_count = _int_field(progress, "reviewed_count")
    if pending_count == 0 and reviewed_count > 0:
        return _check("Human review progress", PASS, "All queued candidates are reviewed.")
    if pending_count > 0:
        return _check("Human review progress", WARN, f"{pending_count} candidate(s) pending.")
    return _check("Human review progress", WARN, "No human review decisions recorded yet.")


def _paper_mode_check() -> dict[str, object]:
    return _check("Broker execution", PASS, "Paper-only mode; broker order submission is off.")


def _next_actions(
    checks: Sequence[Mapping[str, object]],
    keys: Sequence[Mapping[str, object]],
) -> list[str]:
    missing_required = [
        f"Add {key['name']} to {key['file']}."
        for key in keys
        if key.get("required") is True and key.get("present") is not True
    ]
    blockers = [
        f"Fix {check['label']}: {check['detail']}"
        for check in checks
        if check.get("status") == BLOCK
    ]
    warnings = [
        f"Review {check['label']}: {check['detail']}"
        for check in checks
        if check.get("status") == WARN
    ]
    actions = [*missing_required, *blockers, *warnings]
    if actions:
        return actions
    return ["Open the Command page and begin paper review."]


def _check(label: str, status: str, detail: str) -> dict[str, object]:
    return {
        "label": label,
        "status": status,
        "status_class": _status_class(status.lower()),
        "detail": detail,
    }


def _state(blocker_count: int, warning_count: int) -> str:
    if blocker_count > 0:
        return "blocked"
    if warning_count > 0:
        return "attention"
    return "ready"


def _status_label(state: str) -> str:
    labels = {"ready": "Operational", "attention": "Operational With Attention",
              "blocked": "Blocked"}
    return labels.get(state, state.title())


def _status_class(state: str) -> str:
    if state in {"ready", "pass"}:
        return "pass"
    if state in {"attention", "warn", "warning"}:
        return "warn"
    return "block"


def _count_status(checks: Sequence[Mapping[str, object]], status: str) -> int:
    return sum(1 for check in checks if check.get("status") == status)


def _missing_key_count(keys: Sequence[Mapping[str, object]], *, required: bool) -> int:
    return sum(
        1
        for key in keys
        if key.get("required") is required and key.get("present") is not True
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    return _mapping(payload.get(key))


def _int_field(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0
