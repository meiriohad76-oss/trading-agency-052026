from __future__ import annotations

import json
import os
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from dotenv import load_dotenv

from agency.paths import REPO_ROOT
from agency.runtime.data_load_status import load_data_load_status
from agency.runtime.data_refresh_progress import (
    data_refresh_status_path,
    load_data_refresh_progress,
)
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.runtime.provider_readiness import load_provider_readiness

RESEARCH_SRC = REPO_ROOT / "research" / "src"
if str(RESEARCH_SRC) not in sys.path:
    sys.path.insert(0, str(RESEARCH_SRC))

try:
    from providers.massive_limits import current_usage
except ModuleNotFoundError:  # pragma: no cover - defensive for packaged API-only use
    current_usage = None  # type: ignore[assignment]

DEFAULT_EMAIL_INGEST_PATH = (
    REPO_ROOT
    / "research"
    / "results"
    / "latest-subscription-emails"
    / "subscription-email-ingest.json"
)
FULL_LIVE_READY_STATES = {"ready", "attention"}
REFRESH_BLOCKING_STATES = {"failed", "blocked", "planned", "stale", "unavailable"}
REFRESH_ISSUE_STATES = {"failed", "blocked"}
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
CONTEXT_WARNING_ITEMS = {
    "news_rss",
    "subscription_emails",
    "news",
    "subscription_thesis",
}
CONTEXT_PROVIDER_USAGE_ITEMS = {
    "Subscription Email Agents",
}


def load_full_live_readiness(
    *,
    live_config: Mapping[str, object] | None = None,
    data_refresh: Mapping[str, object] | None = None,
    data_load_status: Mapping[str, object] | None = None,
    provider_readiness: Mapping[str, object] | None = None,
    refresh_status_path: Path | None = None,
    email_ingest_path: Path | None = None,
) -> dict[str, object]:
    """Combine config, data-load, refresh, and provider state into one full-live gate."""
    load_dotenv(REPO_ROOT / ".env")
    config = dict(live_config or load_live_config_readiness())
    refresh = dict(data_refresh or load_data_refresh_progress())
    load_status = dict(data_load_status or load_data_load_status())
    providers = dict(provider_readiness or load_provider_readiness(config))
    status_path = refresh_status_path or data_refresh_status_path()
    refresh_payload = _read_json_object(status_path)
    email_payload = _read_json_object(email_ingest_path or DEFAULT_EMAIL_INGEST_PATH)
    active_refresh = _active_refresh(refresh, refresh_payload, status_path)
    provider_usage = _provider_usage(
        config,
        refresh,
        load_status,
        email_payload,
        active_refresh,
    )
    verdict = _verdict(
        live_config=config,
        data_refresh=refresh,
        data_load_status=load_status,
        provider_readiness=providers,
        active_refresh=active_refresh,
    )
    blockers = _blockers(config, refresh, load_status, providers, active_refresh)
    warnings = _warnings(refresh, load_status, providers, active_refresh, provider_usage)
    if verdict == "ready_for_full_live_cycle" and _warnings_degrade_full_live(
        warnings,
        load_status,
    ):
        verdict = "ready_with_partial_lanes"
    tradable_ready = verdict == "ready_for_full_live_cycle"
    review_operational_ready = tradable_ready or (
        verdict == "ready_with_partial_lanes"
        and _load_review_operational(load_status)
    )
    readiness_scope = _readiness_scope(verdict, load_status)
    return {
        "schema_version": "0.1.0",
        "ready": tradable_ready,
        "review_operational_ready": review_operational_ready,
        "tradable_ready": tradable_ready,
        "full_universe_tradable": tradable_ready,
        "readiness_scope": readiness_scope,
        "readiness_scope_label": readiness_scope.replace("_", " ").title(),
        "verdict": verdict,
        "state": _state(verdict),
        "status_label": _status_label(verdict),
        "status_class": _status_class(verdict),
        "headline": _headline(verdict),
        "detail": _detail(verdict, blockers, warnings, load_status),
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "blockers": blockers,
        "warnings": warnings,
        "live_config": config,
        "data_refresh": refresh,
        "data_load_status": load_status,
        "provider_readiness": providers,
        "active_refresh": active_refresh,
        "provider_usage": provider_usage,
        "coverage": _coverage_summary(load_status),
        "next_actions": _next_actions(verdict, blockers, warnings, active_refresh),
    }


def _active_refresh(
    progress: Mapping[str, object],
    payload: Mapping[str, object],
    status_path: Path,
) -> dict[str, object]:
    jobs = _mapping_rows(payload.get("jobs"))
    status_counts = Counter(str(job.get("status", "unknown")) for job in jobs)
    config = _mapping(payload.get("config"))
    tickers = _sequence(config.get("tickers"))
    current_dataset = str(progress.get("current_dataset") or "None")
    running = str(progress.get("state")) == "running"
    stale = str(progress.get("state")) == "stale"
    return {
        "state": str(progress.get("state", "idle")),
        "status_label": str(progress.get("status_label", "Idle")),
        "status_class": str(progress.get("status_class", "neutral")),
        "status_path": _display_path(status_path),
        "batch_id": status_path.parent.name,
        "running_dataset": current_dataset if running or stale else "None",
        "running_batch_id": status_path.parent.name if running or stale else "None",
        "eta_label": str(progress.get("eta_label", "not available")),
        "percent_complete": _int(progress.get("percent_complete")),
        "total_jobs": _int(progress.get("total_jobs")),
        "completed_jobs": _int(progress.get("completed_jobs")),
        "job_status_counts": dict(status_counts),
        "planned_job_count": status_counts.get("planned", 0),
        "passed_job_count": status_counts.get("passed", 0),
        "failed_job_count": status_counts.get("failed", 0),
        "blocked_job_count": status_counts.get("blocked", 0),
        "deferred_job_count": status_counts.get("deferred", 0) + status_counts.get("skipped", 0),
        "configured_ticker_count": len(tickers),
        "dataset_rows": [_refresh_job_row(job) for job in jobs],
        "long_running_warning": stale,
        "detail": str(progress.get("detail", "No data refresh detail is available.")),
    }


def _provider_usage(
    live_config: Mapping[str, object],
    data_refresh: Mapping[str, object],
    data_load_status: Mapping[str, object],
    email_ingest: Mapping[str, object],
    active_refresh: Mapping[str, object],
) -> list[dict[str, object]]:
    return [
        _massive_usage_row(live_config),
        _sec_usage_row(data_load_status),
        _email_usage_row(email_ingest),
        _refresh_usage_row(data_refresh, data_load_status, active_refresh),
    ]


def _massive_usage_row(live_config: Mapping[str, object]) -> dict[str, object]:
    if current_usage is None:
        return _usage_row(
            "massive_polygon",
            "Massive / Polygon",
            "UNKNOWN",
            "neutral",
            "Massive usage module is unavailable.",
        )
    usage = current_usage()
    enabled = usage.get("enabled") is True
    provider = str(live_config.get("provider", "")).lower()
    required = provider == "massive"
    status = "PASS" if not required or _massive_key_present() else "BLOCK"
    if enabled and usage.get("requests_remaining") == 0:
        status = "WARN"
    detail = (
        f"{usage['requests_made']} request(s) today; "
        f"remaining {usage['requests_remaining_label']}; "
        f"pace {usage['max_requests_per_minute_label']} per minute."
    )
    if not enabled:
        detail += " Local request ledger is disabled."
    return _usage_row(
        "massive_polygon",
        "Massive / Polygon",
        status,
        _status_class(status),
        detail,
        payload=usage,
    )


def _sec_usage_row(data_load_status: Mapping[str, object]) -> dict[str, object]:
    datasets = _mapping_rows(data_load_status.get("datasets"))
    sec_rows = [
        row
        for row in datasets
        if str(row.get("dataset")) in {"sec_company_facts", "sec_form4", "sec_13f"}
    ]
    blocked = [row for row in sec_rows if row.get("status") == "blocked"]
    warned = [row for row in sec_rows if row.get("status") == "warning"]
    status = "BLOCK" if blocked else "WARN" if warned else "PASS"
    detail = (
        "SEC datasets ready."
        if status == "PASS"
        else str((blocked or warned)[0].get("detail", "SEC data needs review."))
    )
    return _usage_row("sec_edgar", "SEC EDGAR", status, _status_class(status), detail)


def _email_usage_row(email_ingest: Mapping[str, object]) -> dict[str, object]:
    if not email_ingest:
        return _usage_row(
            "subscription_email",
            "Subscription Email Agents",
            "WARN",
            "warn",
            "No latest subscription-email ingest summary was found.",
        )
    linked = _mapping(email_ingest.get("linked_content"))
    mailbox = _mapping(email_ingest.get("mailbox_sync"))
    failed = _int(linked.get("failed"))
    needs_login = _int(linked.get("login_required"))
    unavailable = _int(linked.get("unavailable"))
    status = "WARN" if failed or needs_login or unavailable else "PASS"
    issue_detail = ""
    if needs_login:
        issue_detail = f"; {needs_login} article link(s) need login confirmation"
    elif unavailable:
        issue_detail = f"; {unavailable} article link(s) unavailable"
    detail = (
        f"{email_ingest.get('processed_emails', 0)} email(s) processed; "
        f"{linked.get('succeeded', 0)} article link(s) analyzed; "
        f"{failed} failed{issue_detail}; "
        f"mailbox mode {mailbox.get('mode', email_ingest.get('mode', 'unknown'))}."
    )
    return _usage_row(
        "subscription_email",
        "Subscription Email Agents",
        status,
        _status_class(status),
        detail,
        payload={
            "verdict": email_ingest.get("verdict"),
            "processed_emails": email_ingest.get("processed_emails", 0),
            "linked_content": dict(linked),
            "mailbox_sync": dict(mailbox),
        },
    )


def _refresh_usage_row(
    data_refresh: Mapping[str, object],
    data_load_status: Mapping[str, object],
    active_refresh: Mapping[str, object],
) -> dict[str, object]:
    state = str(data_refresh.get("state", "idle"))
    if _refresh_blocks_live_readiness(data_refresh, data_load_status, active_refresh):
        status = "BLOCK"
    elif state in {"failed", "blocked", "planned", "stale"} or _nonblocking_refresh_issue_jobs(
        active_refresh
    ):
        status = "WARN"
    elif state == "running" and _nonblocking_current_refresh_dataset(
        data_refresh,
        data_load_status,
    ):
        status = "PASS"
    elif state == "running":
        status = "WARN"
    else:
        status = "PASS"
    return _usage_row(
        "data_refresh",
        "Refresh Worker",
        status,
        _status_class(status),
        str(data_refresh.get("detail", "No data refresh detail available.")),
    )


def _verdict(
    *,
    live_config: Mapping[str, object],
    data_refresh: Mapping[str, object],
    data_load_status: Mapping[str, object],
    provider_readiness: Mapping[str, object],
    active_refresh: Mapping[str, object],
) -> str:
    refresh_state = str(data_refresh.get("state", "idle"))
    if (
        _refresh_blocks_live_readiness(data_refresh, data_load_status, active_refresh)
        or _trade_pull_blocked(data_refresh, data_load_status)
    ):
        return "blocked"
    if (
        live_config.get("ready") is not True
        or provider_readiness.get("ready") is not True
        or (
            active_refresh.get("long_running_warning") is True
            and not _nonblocking_current_refresh_dataset(data_refresh, data_load_status)
        )
    ):
        return "blocked"
    load_state = str(data_load_status.get("state"))
    if load_state == "blocked":
        return "blocked"
    if (
        load_state == "attention"
        and not _load_review_operational(data_load_status)
    ):
        return "blocked"
    if refresh_state == "running":
        if (
            _load_tradable(data_load_status)
            and _nonblocking_current_refresh_dataset(data_refresh, data_load_status)
        ):
            return "ready_for_full_live_cycle"
        if _load_review_operational(data_load_status):
            return "ready_with_partial_lanes"
        return "loading"
    if (
        _load_tradable(data_load_status)
        and load_state in FULL_LIVE_READY_STATES
    ):
        return "ready_for_full_live_cycle"
    if (
        load_state == "attention"
        or _int(provider_readiness.get("warning_count")) > 0
        or _int(data_load_status.get("warning_count")) > 0
    ):
        return "ready_with_partial_lanes"
    return "ready_with_partial_lanes"


def _blockers(
    live_config: Mapping[str, object],
    data_refresh: Mapping[str, object],
    data_load_status: Mapping[str, object],
    provider_readiness: Mapping[str, object],
    active_refresh: Mapping[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if live_config.get("ready") is not True:
        rows.append(
            _issue(
                "Live config",
                "config",
                str(live_config.get("status_label", "Blocked")),
            )
        )
    rows.extend(_issue_rows(data_load_status.get("blockers"), label="Data"))
    if provider_readiness.get("ready") is not True:
        rows.append(
            _issue(
                "Providers",
                "provider keys",
                f"{provider_readiness.get('blocker_count', 0)} provider blocker(s).",
            )
        )
    if _trade_pull_blocked(data_refresh, data_load_status):
        trade_pull = data_refresh.get("trade_pull")
        detail = (
            str(trade_pull.get("detail"))
            if isinstance(trade_pull, Mapping)
            else "Massive stock-trade pull did not complete verified ticker-day coverage."
        )
        rows.append(_issue("Refresh", "stock_trades", detail))
    if active_refresh.get("long_running_warning") is True:
        if _nonblocking_current_refresh_dataset(data_refresh, data_load_status):
            pass
        else:
            rows.append(
                _issue(
                    "Refresh",
                    "stale worker",
                    "Latest data-refresh status stopped updating while marked running.",
                )
            )
    if (
        str(active_refresh.get("state")) in REFRESH_BLOCKING_STATES
        and _refresh_blocks_live_readiness(data_refresh, data_load_status, active_refresh)
    ):
        rows.append(
            _issue(
                "Refresh",
                str(active_refresh.get("state")),
                str(active_refresh.get("detail", "Latest data refresh is blocked.")),
            )
        )
    failed_jobs = _core_refresh_issue_jobs(active_refresh, status="failed")
    if failed_jobs or (
        _int(active_refresh.get("failed_job_count")) > 0
        and not _load_review_operational(data_load_status)
    ):
        rows.append(
            _issue(
                "Refresh",
                "failed jobs",
                f"{len(failed_jobs) or active_refresh.get('failed_job_count')} refresh job(s) failed.",
            )
        )
    blocked_jobs = _core_refresh_issue_jobs(active_refresh, status="blocked")
    if blocked_jobs or (
        _int(active_refresh.get("blocked_job_count")) > 0
        and not _load_review_operational(data_load_status)
    ):
        rows.append(
            _issue(
                "Refresh",
                "blocked jobs",
                f"{len(blocked_jobs) or active_refresh.get('blocked_job_count')} refresh job(s) are blocked.",
            )
        )
    return rows


def _trade_pull_blocked(
    data_refresh: Mapping[str, object],
    data_load_status: Mapping[str, object],
) -> bool:
    trade_pull = data_refresh.get("trade_pull")
    if not isinstance(trade_pull, Mapping):
        return False
    state = str(trade_pull.get("state") or "").lower()
    if state == "blocked":
        return True
    usable = max(
        _int(trade_pull.get("pipeline_ready_count")),
        _int(trade_pull.get("pipeline_usable_count")),
        _market_flow_usable_ticker_count(data_load_status),
    )
    failed = _int(trade_pull.get("pipeline_failed_count"))
    if state == "unverified":
        return usable <= 0
    if state == "stale":
        return True
    if state == "failed":
        return usable <= 0
    if state != "partial":
        return False
    return usable <= 0 or failed > 0


def _load_tradable(data_load_status: Mapping[str, object]) -> bool:
    value = data_load_status.get("tradable_ready")
    if isinstance(value, bool):
        return value
    return (
        data_load_status.get("ready") is True
        and str(data_load_status.get("state")) == "ready"
    )


def _load_review_operational(data_load_status: Mapping[str, object]) -> bool:
    value = data_load_status.get("review_operational_ready")
    if isinstance(value, bool):
        return value
    return (
        data_load_status.get("ready") is True
        and str(data_load_status.get("state")) in FULL_LIVE_READY_STATES
    )


def _market_flow_usable_ticker_count(data_load_status: Mapping[str, object]) -> int:
    market_flow = _mapping(data_load_status.get("market_flow_summary"))
    return _int(market_flow.get("usable_ticker_count"))


def _readiness_scope(verdict: str, data_load_status: Mapping[str, object]) -> str:
    if verdict == "ready_for_full_live_cycle":
        return "full_universe"
    if verdict == "loading":
        return "loading"
    if verdict == "blocked":
        return "blocked"
    mode = str(data_load_status.get("mode") or "")
    if mode == "review_subset":
        return "review_subset"
    return "review_operational"


def _warnings(
    data_refresh: Mapping[str, object],
    data_load_status: Mapping[str, object],
    provider_readiness: Mapping[str, object],
    active_refresh: Mapping[str, object],
    provider_usage: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    rows = _issue_rows(data_load_status.get("warnings"), label="Data")
    if _int(provider_readiness.get("warning_count")) > 0:
        rows.append(
            _issue(
                "Providers",
                "optional providers",
                f"{provider_readiness.get('warning_count', 0)} provider warning(s).",
            )
        )
    if str(active_refresh.get("state")) == "running":
        rows.append(
            _issue(
                "Refresh",
                str(active_refresh.get("running_dataset", "dataset")),
                f"Refresh is still loading; ETA {active_refresh.get('eta_label', 'unknown')}.",
            )
        )
    if (
        active_refresh.get("long_running_warning") is True
        and _nonblocking_current_refresh_dataset(data_refresh, data_load_status)
    ):
        rows.append(
            _issue(
                "Refresh",
                str(active_refresh.get("running_dataset") or data_refresh.get("current_dataset") or "support dataset"),
                (
                    "A support refresh stopped updating, but the latest core market "
                    "lanes remain reviewable."
                ),
            )
        )
    for job in _nonblocking_refresh_issue_jobs(active_refresh):
        rows.append(
            _issue(
                "Refresh",
                str(job.get("dataset", "support dataset")),
                (
                    f"Support refresh job {job.get('status', 'failed')}: "
                    f"{job.get('reason', 'No reason recorded.')}. Core market data "
                    "remains reviewable."
                ),
            )
        )
    trade_pull = _trade_pull_status(data_refresh, data_load_status)
    trade_pull_state = str(trade_pull.get("state") or "").lower() if trade_pull else ""
    if isinstance(trade_pull, Mapping) and trade_pull_state in {"partial", "unverified"}:
        rows.append(
            _issue(
                "Refresh",
                "stock_trades",
                str(
                    trade_pull.get("pipeline_detail")
                    or trade_pull.get("detail")
                    or "Massive stock-trade pull is partially complete; usable ticker slices can continue through the pipeline."
                ),
            )
        )
    for row in provider_usage:
        if row.get("status") == "WARN":
            rows.append(_issue("Provider usage", str(row["label"]), str(row["detail"])))
    return rows


def _warnings_degrade_full_live(
    warnings: Sequence[Mapping[str, object]],
    data_load_status: Mapping[str, object],
) -> bool:
    return any(
        _warning_degrades_full_live(warning, data_load_status)
        for warning in warnings
    )


def _warning_degrades_full_live(
    warning: Mapping[str, object],
    data_load_status: Mapping[str, object],
) -> bool:
    if _context_only_warning(warning):
        return False
    if _nonblocking_trade_progress_warning(warning, data_load_status):
        return False
    if str(warning.get("kind")) != "Refresh":
        return True
    item = str(warning.get("item") or "")
    reason = str(warning.get("reason") or "")
    return not (
        not _refresh_dataset_blocks(item)
        and reason.startswith("Refresh is still loading")
    )


def _context_only_warning(warning: Mapping[str, object]) -> bool:
    kind = str(warning.get("kind") or "")
    item = str(warning.get("item") or "")
    if kind == "Data" and item in CONTEXT_WARNING_ITEMS:
        return True
    return kind == "Provider usage" and item in CONTEXT_PROVIDER_USAGE_ITEMS


def _nonblocking_trade_progress_warning(
    warning: Mapping[str, object],
    data_load_status: Mapping[str, object],
) -> bool:
    if str(warning.get("item") or "") != "stock_trades":
        return False
    if str(warning.get("kind") or "") not in {"Data", "Refresh"}:
        return False
    if data_load_status.get("tradable_ready") is not True:
        return False
    market_flow = _mapping(data_load_status.get("market_flow_summary"))
    expected = _int(market_flow.get("expected_ticker_count"))
    usable = _int(market_flow.get("usable_ticker_count"))
    signals = _int(market_flow.get("signal_ticker_count"))
    return (
        str(market_flow.get("status") or "") == "ready"
        and expected > 0
        and usable >= expected
        and signals >= expected
    )


def _refresh_blocks_live_readiness(
    data_refresh: Mapping[str, object],
    data_load_status: Mapping[str, object],
    active_refresh: Mapping[str, object],
) -> bool:
    state = str(data_refresh.get("state", "idle"))
    if state not in REFRESH_BLOCKING_STATES:
        return bool(_core_refresh_issue_jobs(active_refresh))
    if state == "planned":
        return True
    if _core_refresh_issue_jobs(active_refresh):
        return True
    if _nonblocking_refresh_issue_jobs(active_refresh):
        return not _load_review_operational(data_load_status)
    return not _nonblocking_current_refresh_dataset(data_refresh, data_load_status)


def _core_refresh_issue_jobs(
    active_refresh: Mapping[str, object],
    *,
    status: str | None = None,
) -> list[Mapping[str, object]]:
    return [
        job
        for job in _refresh_issue_jobs(active_refresh, status=status)
        if _refresh_dataset_blocks(str(job.get("dataset", "")))
    ]


def _nonblocking_refresh_issue_jobs(
    active_refresh: Mapping[str, object],
    *,
    status: str | None = None,
) -> list[Mapping[str, object]]:
    return [
        job
        for job in _refresh_issue_jobs(active_refresh, status=status)
        if not _refresh_dataset_blocks(str(job.get("dataset", "")))
    ]


def _refresh_issue_jobs(
    active_refresh: Mapping[str, object],
    *,
    status: str | None = None,
) -> list[Mapping[str, object]]:
    rows = _mapping_rows(active_refresh.get("dataset_rows"))
    allowed = {status} if status else REFRESH_ISSUE_STATES
    return [job for job in rows if str(job.get("status", "unknown")) in allowed]


def _nonblocking_current_refresh_dataset(
    data_refresh: Mapping[str, object],
    data_load_status: Mapping[str, object],
) -> bool:
    if not _load_review_operational(data_load_status):
        return False
    dataset = str(data_refresh.get("current_dataset") or data_refresh.get("dataset") or "")
    return bool(dataset) and not _refresh_dataset_blocks(dataset)


def _refresh_dataset_blocks(dataset: str) -> bool:
    normalized = dataset.strip().lower()
    if normalized in CORE_REFRESH_DATASETS:
        return True
    return normalized not in NON_BLOCKING_REFRESH_DATASETS


def _trade_pull_status(
    data_refresh: Mapping[str, object],
    data_load_status: Mapping[str, object],
) -> Mapping[str, object]:
    trade_pull = data_refresh.get("trade_pull")
    if isinstance(trade_pull, Mapping):
        return trade_pull
    nested_refresh = data_load_status.get("data_refresh")
    if isinstance(nested_refresh, Mapping):
        nested_trade_pull = nested_refresh.get("trade_pull")
        if isinstance(nested_trade_pull, Mapping):
            return nested_trade_pull
    return {}


def _coverage_summary(data_load_status: Mapping[str, object]) -> dict[str, object]:
    source_summary = _mapping(data_load_status.get("source_summary"))
    agent_summary = _mapping(data_load_status.get("agent_summary"))
    dataset_summary = _mapping(data_load_status.get("dataset_summary"))
    market_flow = _mapping(data_load_status.get("market_flow_summary"))
    return {
        "overall_percent": _int(data_load_status.get("overall_percent")),
        "core_dataset_percent": _int(data_load_status.get("core_dataset_percent")),
        "critical_lane_percent": _int(data_load_status.get("critical_lane_percent")),
        "expected_ticker_count": _int(data_load_status.get("expected_ticker_count")),
        "evidence_pack_count": _int(data_load_status.get("evidence_pack_count")),
        "signal_count": _int(data_load_status.get("signal_count")),
        "cycle_id": str(data_load_status.get("cycle_id", "None")),
        "as_of": str(data_load_status.get("as_of", "unknown")),
        "source_count": _int(source_summary.get("source_count")),
        "fresh_source_count": _int(source_summary.get("fresh_count")),
        "stale_source_count": _int(source_summary.get("blocked_count")),
        "source_warning_count": _int(source_summary.get("warning_count")),
        "critical_source_blocker_count": _int(source_summary.get("critical_blocker_count")),
        "source_headline": str(source_summary.get("headline", "Source freshness unknown.")),
        "dataset_ready_label": str(dataset_summary.get("ready_label", "datasets unknown")),
        "dataset_blocked_count": _int(dataset_summary.get("blocked_count")),
        "agent_ready_count": _int(agent_summary.get("ready_count")),
        "agent_warning_count": _int(agent_summary.get("warning_count")),
        "agent_blocked_count": _int(agent_summary.get("blocked_count")),
        "agent_total_count": _int(agent_summary.get("total_count")),
        "critical_agent_ready_label": str(
            agent_summary.get("critical_ready_label", "critical lanes unknown")
        ),
        "market_flow_status": str(market_flow.get("status", "unknown")),
        "market_flow_status_label": str(market_flow.get("status_label", "Unknown")),
        "market_flow_usable_ticker_count": _int(market_flow.get("usable_ticker_count")),
        "market_flow_expected_ticker_count": _int(market_flow.get("expected_ticker_count")),
        "market_flow_coverage_pct": _int(market_flow.get("coverage_pct")),
        "market_flow_detail": str(market_flow.get("detail", "Market-flow status unknown.")),
    }


def _next_actions(
    verdict: str,
    blockers: Sequence[Mapping[str, object]],
    warnings: Sequence[Mapping[str, object]],
    active_refresh: Mapping[str, object],
) -> list[str]:
    if verdict == "ready_for_full_live_cycle":
        return ["Run or inspect the latest full active-universe paper cycle."]
    if verdict == "ready_with_partial_lanes":
        return [
            (
                "Review covered ticker candidates now; keep trade-slice repair queued "
                "and do not treat this as full-universe tradable."
            )
        ]
    if verdict == "loading":
        return [
            (
                f"Wait for {active_refresh.get('running_dataset', 'the refresh job')} "
                f"to finish; ETA {active_refresh.get('eta_label', 'unknown')}."
            )
        ]
    if blockers:
        return [f"Fix {blockers[0]['kind']}: {blockers[0]['reason']}"]
    if warnings:
        return [f"Review {warnings[0]['kind']}: {warnings[0]['reason']}"]
    return ["Review partial-lane gaps before running a full paper cycle."]


def _refresh_job_row(job: Mapping[str, object]) -> dict[str, object]:
    return {
        "dataset": str(job.get("dataset", "unknown")),
        "status": str(job.get("status", "unknown")),
        "reason": str(job.get("reason", "No reason recorded.")),
        "duration_seconds": job.get("duration_seconds"),
        "extraction_action": job.get("extraction_action"),
    }


def _issue_rows(value: object, *, label: str) -> list[dict[str, object]]:
    return [
        _issue(label, str(row.get("item", "unknown")), str(row.get("reason", "No detail.")))
        for row in _mapping_rows(value)
    ]


def _issue(kind: str, item: str, reason: str) -> dict[str, object]:
    return {"kind": kind, "item": item, "reason": reason}


def _usage_row(
    provider_id: str,
    label: str,
    status: str,
    status_class: str,
    detail: str,
    *,
    payload: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": provider_id,
        "label": label,
        "status": status,
        "status_class": status_class,
        "detail": detail,
        "payload": dict(payload or {}),
    }


def _state(verdict: str) -> str:
    if verdict == "ready_for_full_live_cycle":
        return "ready"
    if verdict == "loading":
        return "loading"
    if verdict == "blocked":
        return "blocked"
    return "attention"


def _status_label(verdict: str) -> str:
    return {
        "ready_for_full_live_cycle": "Ready For Full Live Cycle",
        "ready_with_partial_lanes": "Ready With Partial Lanes",
        "loading": "Loading",
        "blocked": "Blocked",
    }.get(verdict, verdict.replace("_", " ").title())


def _status_class(value: str) -> str:
    normalized = value.lower()
    if normalized in {"ready_for_full_live_cycle", "ready", "pass"}:
        return "pass"
    if normalized in {"ready_with_partial_lanes", "loading", "warning", "warn"}:
        return "warn"
    return "block"


def _headline(verdict: str) -> str:
    return {
        "ready_for_full_live_cycle": "Full active-universe cycle is ready to run or inspect.",
        "ready_with_partial_lanes": "Core data is usable, but some lanes need review.",
        "loading": "Full-live data is still loading.",
        "blocked": "Full-live cycle is blocked by data, config, or provider state.",
    }.get(verdict, "Full-live readiness is unknown.")


def _detail(
    verdict: str,
    blockers: Sequence[Mapping[str, object]],
    warnings: Sequence[Mapping[str, object]],
    data_load_status: Mapping[str, object],
) -> str:
    if verdict == "ready_for_full_live_cycle":
        coverage = _coverage_summary(data_load_status)
        return (
            f"Core data {coverage['core_dataset_percent']}%, critical agents "
            f"{coverage['critical_lane_percent']}%, sources "
            f"{coverage['fresh_source_count']}/{coverage['source_count']} fresh, universe "
            f"{coverage['expected_ticker_count']} tickers."
        )
    if verdict == "blocked" and blockers:
        return str(blockers[0]["reason"])
    if warnings:
        return str(warnings[0]["reason"])
    return str(data_load_status.get("detail", "No full-live readiness detail is available."))


def _massive_key_present() -> bool:
    return bool(
        os.environ.get("MASSIVE_API_KEY", "").strip()
        or os.environ.get("POLYGON_API_KEY", "").strip()
    )


def _read_json_object(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return cast(Mapping[str, object], payload) if isinstance(payload, Mapping) else {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, list) else ()


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return 0


def _display_path(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()
