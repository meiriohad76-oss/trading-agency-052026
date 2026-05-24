from __future__ import annotations

from collections.abc import Mapping, Sequence

from agency.runtime.operational_keys import load_key_statuses

PASS = "PASS"
WARN = "WARN"
BLOCK = "BLOCK"

BLOCKING_DATA_REFRESH_STATES = {
    "blocked",
    "failed",
    "planned",
    "running",
    "stale",
    "unavailable",
}
READY_DATA_REFRESH_STATES = {"complete"}
CORE_REFRESH_DATASETS = {
    "prices_daily",
    "stock_trades",
    "massive_daily_bars",
    "massive_live_trade_slices",
    "massive_premarket_trade_slices",
}
NON_BLOCKING_REFRESH_DATASETS = {
    "sec_company_facts",
    "sec_form4",
    "sec_13f",
    "news_rss",
    "subscription_emails",
    "massive_backtest_trade_tape",
    "massive_block_trade_feed",
    "massive_options_flow",
    "massive_reference",
}
FULL_COVERAGE_PERCENT = 100


def build_operational_readiness(
    *,
    health: Mapping[str, object],
    live_config: Mapping[str, object],
    data_refresh: Mapping[str, object],
    data_load_status: Mapping[str, object] | None = None,
    live_readiness: Mapping[str, object],
    paper_review: Mapping[str, object],
    key_statuses: Sequence[Mapping[str, object]] | None = None,
    broker_execution_enabled: bool = False,
) -> dict[str, object]:
    keys = list(key_statuses if key_statuses is not None else load_key_statuses(live_config))
    checks = [
        _health_check(health),
        _live_config_check(live_config),
        _data_refresh_check(data_refresh, data_load_status=data_load_status),
        *(_data_load_checks(data_load_status) if data_load_status is not None else []),
        _live_readiness_check(live_readiness, data_load_status),
        _paper_review_check(paper_review),
        _human_review_progress_check(paper_review),
        _paper_mode_check(broker_execution_enabled),
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
        "broker_execution_enabled": broker_execution_enabled,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "checks": checks,
        "keys": keys,
        "next_actions": _next_actions(checks, keys),
        "health": dict(health),
        "live_config": dict(live_config),
        "data_refresh": dict(data_refresh),
        "data_load_status": dict(data_load_status or {}),
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


def _data_refresh_check(
    data_refresh: Mapping[str, object],
    *,
    data_load_status: Mapping[str, object] | None,
) -> dict[str, object]:
    state = str(data_refresh.get("state", "unknown"))
    label = str(data_refresh.get("status_label", state.title()))
    if state == "running":
        eta = str(data_refresh.get("eta_label", "unknown"))
        if _data_load_review_operational(data_load_status):
            return _check(
                "Data refresh",
                WARN,
                f"Background refresh is still loading; covered tickers remain reviewable. ETA {eta}.",
            )
        return _check("Data refresh", BLOCK, f"Data is still loading; ETA {eta}.")
    if state in BLOCKING_DATA_REFRESH_STATES:
        if _support_refresh_issue_is_nonblocking(data_refresh, data_load_status):
            affected = _affected_refresh_datasets(data_refresh)
            dataset = ", ".join(affected) if affected else "support dataset"
            return _check(
                "Data refresh",
                WARN,
                (
                    f"Latest support refresh failed for {dataset}; core market-data "
                    "lanes remain reviewable."
                ),
            )
        return _check("Data refresh", BLOCK, f"Latest data refresh is {label}.")
    if state in READY_DATA_REFRESH_STATES:
        return _check("Data refresh", PASS, f"Latest data refresh is {label}.")
    return _check("Data refresh", WARN, f"No complete latest refresh status: {label}.")


def _data_load_checks(data_load_status: Mapping[str, object]) -> list[dict[str, object]]:
    state = str(data_load_status.get("state", "unknown"))
    label = str(data_load_status.get("status_label", state.title()))
    blockers = _int_field(data_load_status, "blocker_count")
    warnings = _int_field(data_load_status, "warning_count")
    overall = _int_field(data_load_status, "overall_percent")
    core = _int_field(data_load_status, "core_dataset_percent")
    lanes = _int_field(data_load_status, "critical_lane_percent")
    if state == "loading":
        return [
            _check(
                "Data loaded and analyzed",
                BLOCK,
                f"Data is still loading; {overall}% complete.",
            )
        ]
    if data_load_status.get("ready") is not True or blockers > 0:
        return [
            _check(
                "Data loaded and analyzed",
                BLOCK,
                f"{label}: {blockers} data blocker(s), {warnings} warning(s).",
            )
        ]
    if warnings > 0 or state == "attention":
        return [
            _check(
                "Data loaded and analyzed",
                WARN,
                f"{label}: core {core}%, critical agents {lanes}%, {warnings} warning(s).",
            )
        ]
    return [
        _check(
            "Data loaded and analyzed",
            PASS,
            f"Core data {core}% and critical agents {lanes}% for the latest cycle.",
        )
    ]


def _live_readiness_check(
    live_readiness: Mapping[str, object],
    data_load_status: Mapping[str, object] | None,
) -> dict[str, object]:
    verdict = str(live_readiness.get("verdict", "unknown"))
    if live_readiness.get("ready") is True:
        return _check("Runtime cycle", PASS, f"Latest cycle is {verdict}.")
    if live_readiness.get("review_operational_ready") is True:
        scope = str(live_readiness.get("readiness_scope_label") or "review operational")
        return _check(
            "Runtime cycle",
            WARN,
            f"Latest cycle is {verdict}; scope is {scope}.",
        )
    if verdict in {"context_only_source_health", "context_only_lane_state"} and _data_load_ready_enough(data_load_status):
        return _check(
            "Runtime cycle",
            WARN,
            "Runtime lane proof needs review, but data-load coverage is complete.",
        )
    if verdict in {"context_only_source_health", "context_only_lane_state"} and _data_load_review_operational(data_load_status):
        return _check(
            "Runtime cycle",
            WARN,
            (
                "Runtime lane proof needs review, but data-load confirms "
                "review-subset coverage. Review covered tickers only."
            ),
        )
    detail = str(live_readiness.get("detail", "Latest cycle is not reviewable."))
    return _check("Runtime cycle", BLOCK, detail)


def _data_load_ready_enough(data_load_status: Mapping[str, object] | None) -> bool:
    if data_load_status is None:
        return False
    if (
        data_load_status.get("tradable_ready") is True
        and _int_field(data_load_status, "blocker_count") == 0
    ):
        return True
    return (
        data_load_status.get("ready") is True
        and _int_field(data_load_status, "blocker_count") == 0
        and _int_field(data_load_status, "core_dataset_percent") >= FULL_COVERAGE_PERCENT
        and _int_field(data_load_status, "critical_lane_percent") >= FULL_COVERAGE_PERCENT
    )


def _data_load_review_operational(data_load_status: Mapping[str, object] | None) -> bool:
    if data_load_status is None:
        return False
    if data_load_status.get("review_operational_ready") is True:
        return True
    return data_load_status.get("ready") is True and _int_field(data_load_status, "blocker_count") == 0


def _support_refresh_issue_is_nonblocking(
    data_refresh: Mapping[str, object],
    data_load_status: Mapping[str, object] | None,
) -> bool:
    state = str(data_refresh.get("state", "unknown"))
    if state == "planned" or state not in BLOCKING_DATA_REFRESH_STATES:
        return False
    datasets = _affected_refresh_datasets(data_refresh)
    if not datasets or any(_refresh_dataset_blocks(dataset) for dataset in datasets):
        return False
    return _data_load_review_operational(data_load_status)


def _affected_refresh_datasets(data_refresh: Mapping[str, object]) -> list[str]:
    values = [
        str(dataset).strip().lower()
        for dataset in _sequence_field(data_refresh, "failed_datasets")
        if str(dataset).strip()
    ]
    current_dataset = str(data_refresh.get("current_dataset") or "").strip().lower()
    if current_dataset and current_dataset != "none":
        values.append(current_dataset)
    dataset = str(data_refresh.get("dataset") or "").strip().lower()
    if dataset and dataset != "none":
        values.append(dataset)
    return list(dict.fromkeys(values))


def _refresh_dataset_blocks(dataset: str) -> bool:
    normalized = dataset.strip().lower()
    if normalized in CORE_REFRESH_DATASETS:
        return True
    return normalized not in NON_BLOCKING_REFRESH_DATASETS


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


def _paper_mode_check(broker_execution_enabled: bool) -> dict[str, object]:
    if broker_execution_enabled:
        return _check(
            "Broker execution",
            PASS,
            "Paper-only mode; approved READY previews can be submitted.",
        )
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


def _sequence_field(payload: Mapping[str, object], key: str) -> Sequence[object]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _int_field(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0
