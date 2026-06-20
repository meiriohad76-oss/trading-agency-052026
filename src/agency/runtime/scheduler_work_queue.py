from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast

import pandas as pd
from dotenv import load_dotenv


def _resolve_repo_root(candidates: Sequence[Path] | None = None) -> Path:
    env_root = os.environ.get("AGENCY_REPO_ROOT")
    probe_roots = list(candidates or [])
    if env_root:
        probe_roots.append(Path(env_root))
    probe_roots.extend([Path.cwd(), Path("/app"), Path(__file__).resolve().parents[3]])
    for root in probe_roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if (resolved / "research" / "scripts").exists() and (resolved / "src").exists():
            return resolved
        if (resolved / "research" / "scripts").exists() and (resolved / "schemas").exists():
            return resolved
    return Path(__file__).resolve().parents[3]


REPO_ROOT = _resolve_repo_root()
RESEARCH_SRC = REPO_ROOT / "research" / "src"
if str(RESEARCH_SRC) not in sys.path:
    sys.path.insert(0, str(RESEARCH_SRC))

from data_refresh.live_config import RefreshConfigOverrides, load_refresh_config  # noqa: E402
from data_refresh.market_batching import build_market_aware_batch_plan  # noqa: E402
from data_refresh.massive_lane_manifest import (  # noqa: E402
    manifest_path_for_lane,
    read_lane_manifest,
)
from data_refresh.types import DATASETS, RefreshBatchConfig  # noqa: E402

from agency.runtime.scheduler_status import load_scheduler_runtime_status  # noqa: E402

DEFAULT_CONFIG_PATH = REPO_ROOT / "research" / "config" / "live-refresh.local.json"
DEFAULT_PARQUET_ROOT = REPO_ROOT / "research" / "data" / "parquet"
DEFAULT_UNIVERSE_PATH = DEFAULT_PARQUET_ROOT / "universe_membership.parquet"
PARTIAL_RUNTIME_OUTPUT_ROOT = REPO_ROOT / "research" / "results" / "latest-partial-runtime-cycle"
MINI_RUNTIME_OUTPUT_ROOT = REPO_ROOT / "research" / "results" / "latest-mini-runtime-cycle"
CRITICAL_EXECUTION_SOURCES = {"daily-market-bars", "massive-stock-trades"}
CRITICAL_REFRESH_DATASETS = {
    "daily-market-bars",
    "massive-stock-trades",
    "prices_daily",
    "prices-daily",
    "stock_trades",
    "stock-trades",
}
ACTIVE_MARKET_PHASES = {"pre_market", "regular_market", "after_hours"}
OFF_HOURS_PHASES = {
    "overnight_after_hours",
    "overnight_before_pre_market",
    "closed",
    "closed_weekend",
    "closed_holiday",
}
EVENT_LANE_MAP = {
    "subscription_email": ("subscription_thesis", "news"),
    "news_rss": ("news",),
    "sec_form4": ("insider",),
    "stock_trades": (
        "abnormal_volume",
        "buy_sell_pressure",
        "block_trade_pressure",
        "unusual_trade_activity",
        "pre_market_unusual_activity",
        "market_flow_trend",
        "technical_analysis",
    ),
    "massive_spike": (
        "abnormal_volume",
        "buy_sell_pressure",
        "block_trade_pressure",
        "unusual_trade_activity",
        "market_flow_trend",
    ),
}
HIGH_CONVICTION_SCORE = 0.75
HIGH_CONVICTION_PERCENT = 75.0
SECONDS_PER_MINUTE = 60
EXPLICIT_COMMAND_TICKER_LIMIT = 20
DEFAULT_MAX_SOURCE_HEALTH_AGE_SECONDS = 15 * SECONDS_PER_MINUTE
TEST_FRESHNESS_MODE_ENV = "AGENCY_EXECUTION_FRESHNESS_TEST_MODE"
TEST_SOURCE_MAX_AGE_SECONDS_ENV = "AGENCY_TEST_STOCK_SOURCE_MAX_AGE_SECONDS"
MASSIVE_LIVE_SLICE_ROW_LIMIT = 1_000
LOCAL_DERIVATION_COMMAND_PROFILES = {"derive_block_trades_from_live_slices"}
MASSIVE_COMMAND_PROFILES_WITH_RUNNERS = {
    "stock_trades_live",
    "stock_trades_premarket",
    "stock_trades_backfill",
    "prices_daily",
    "derive_block_trades_from_live_slices",
}


@dataclass(frozen=True)
class TickerTiers:
    t0: tuple[str, ...]
    t1: tuple[str, ...]
    t2: tuple[str, ...]
    t3: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "0.1.0",
            "tiers": {
                "T0": _tier_payload(
                    "T0",
                    self.t0,
                    "Open positions, open broker orders, or human-approved review rows.",
                ),
                "T1": _tier_payload(
                    "T1",
                    self.t1,
                    "Current review queue, watchlist, and high-conviction candidates.",
                ),
                "T2": _tier_payload(
                    "T2",
                    self.t2,
                    "Remaining active universe that should stay live-market current.",
                ),
                "T3": _tier_payload(
                    "T3",
                    self.t3,
                    "Research and backfill universe for quiet maintenance windows.",
                ),
            },
            "counts": {
                "T0": len(self.t0),
                "T1": len(self.t1),
                "T2": len(self.t2),
                "T3": len(self.t3),
            },
        }


def scheduler_work_queue_context(
    *,
    reports: Sequence[Mapping[str, object]] = (),
    review_queue: Sequence[Mapping[str, object]] = (),
    source_health: Sequence[Mapping[str, object]] = (),
    broker: Mapping[str, object] | None = None,
    data_load_status: Mapping[str, object] | None = None,
    data_refresh_progress: Mapping[str, object] | None = None,
    scheduler_runtime: Mapping[str, object] | None = None,
    config_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    current = _utc(now)
    config_file = config_path or DEFAULT_CONFIG_PATH
    overrides = _load_overrides(config_file)
    config = _batch_config(overrides)
    lanes = overrides.runtime_signals or _runtime_lanes_from_config(config_file)
    plan = build_market_aware_batch_plan(config, lanes=lanes, now=current)
    resolved_source_health = _resolved_source_health(
        source_health,
        data_load_status or {},
    )
    active = _configured_or_active_tickers(overrides, config.end)
    research = _research_tickers(config)
    tiers = build_ticker_tiers(
        positions=_broker_positions(broker),
        open_orders=_broker_orders(broker),
        review_queue=review_queue,
        selection_reports=reports,
        active_universe=active,
        research_universe=research,
        max_t2=overrides.runtime_max_tickers,
    )
    return build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_refresh_progress=data_refresh_progress or {},
        scheduler_runtime=scheduler_runtime,
        data_load_status=data_load_status or {},
        source_health=resolved_source_health,
        broker=broker or {},
        config_path=config_file,
        now=current,
    )


def build_ticker_tiers(
    *,
    positions: Sequence[Mapping[str, object]] = (),
    open_orders: Sequence[Mapping[str, object]] = (),
    review_queue: Sequence[Mapping[str, object]] = (),
    selection_reports: Sequence[Mapping[str, object]] = (),
    watchlist: Sequence[str] = (),
    active_universe: Sequence[str] = (),
    research_universe: Sequence[str] = (),
    max_t2: int | None = None,
) -> TickerTiers:
    approved_rows = [
        row
        for row in review_queue
        if str(row.get("human_review_decision", "")).upper() == "APPROVE"
    ]
    t0 = _ordered_unique_tickers(
        [
            *_ordered_mapping_tickers(positions),
            *_ordered_mapping_tickers(open_orders),
            *_ordered_mapping_tickers(approved_rows),
        ]
    )

    high_conviction_rows = [
        row
        for row in selection_reports
        if _number(row.get("final_conviction")) >= HIGH_CONVICTION_SCORE
        or _number(row.get("conviction_pct")) >= HIGH_CONVICTION_PERCENT
    ]
    high_conviction_rows = sorted(high_conviction_rows, key=_conviction_sort_key)
    t1 = _ordered_unique_tickers(
        [
            *_ordered_mapping_tickers(review_queue),
            *_ordered_mapping_tickers(high_conviction_rows),
            *_ordered_string_tickers(watchlist),
        ],
        exclude=set(t0),
    )

    active = _string_tickers(active_universe) - set(t0) - set(t1)
    t2_values = _sorted_tickers(active)
    if max_t2 is not None and max_t2 > 0:
        t2_values = t2_values[:max_t2]

    research = _string_tickers(research_universe) - set(t0) - set(t1) - set(t2_values)
    return TickerTiers(
        t0=tuple(t0),
        t1=tuple(t1),
        t2=tuple(t2_values),
        t3=tuple(_sorted_tickers(research)),
    )


def build_scheduler_work_queue(
    market_plan: Mapping[str, object],
    *,
    tiers: TickerTiers,
    data_refresh_progress: Mapping[str, object] | None = None,
    scheduler_runtime: Mapping[str, object] | None = None,
    data_load_status: Mapping[str, object] | None = None,
    source_health: Sequence[Mapping[str, object]] = (),
    broker: Mapping[str, object] | None = None,
    config_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    current = _utc(now)
    refresh_progress = {} if data_refresh_progress is None else data_refresh_progress
    runtime_status = (
        dict(scheduler_runtime)
        if scheduler_runtime is not None
        else load_scheduler_runtime_status(now=current)
    )
    load_status = {} if data_load_status is None else data_load_status
    broker_snapshot = {} if broker is None else broker
    session = _mapping(market_plan.get("market_session"))
    phase = str(session.get("phase", "unknown"))
    config_file = config_path or DEFAULT_CONFIG_PATH
    massive_orchestrator = _massive_orchestrator_status(
        _mapping(market_plan.get("massive_orchestrator")),
        tiers=tiers,
        progress=refresh_progress,
        source_health=source_health,
        session=session,
        config_path=config_file,
        now=current,
    )
    dataset_jobs = [
        _dataset_job(
            row,
            tiers=tiers,
            progress=refresh_progress,
            scheduler_runtime=runtime_status,
            session=session,
            config_path=config_file,
            massive_orchestrator=massive_orchestrator,
            now=current,
        )
        for row in _mapping_rows(market_plan, "datasets")
    ]
    signal_jobs = [
        _signal_job(
            row,
            tiers=tiers,
            progress=refresh_progress,
            scheduler_runtime=runtime_status,
            phase=phase,
            config_path=config_file,
            massive_orchestrator=massive_orchestrator,
            now=current,
        )
        for row in _mapping_rows(market_plan, "signal_lanes")
    ]
    repair = build_off_hours_baseline_repair_plan(
        market_plan,
        tiers=tiers,
        config_path=config_file,
        now=current,
    )
    jobs = sorted([*dataset_jobs, *signal_jobs], key=_job_sort_key)
    gate = execution_freshness_gate(
        broker_snapshot,
        source_health,
        now=current,
        market_phase=phase,
    )
    stale = _stale_dataset_rows(load_status, source_health)
    tradability = _tradability(
        data_load_status=load_status,
        data_refresh_progress=refresh_progress,
        execution_gate=gate,
        jobs=jobs,
        stale_datasets=stale,
    )
    return {
        "schema_version": "0.1.0",
        "generated_at": current.isoformat(),
        "scheduler_runtime": runtime_status,
        "market_phase": phase,
        "market_reason": str(session.get("reason", "Market phase unavailable.")),
        "market_session": dict(session),
        "ticker_tiers": tiers.as_dict(),
        "jobs": jobs,
        "running_jobs": [job for job in jobs if job["status"] == "RUNNING"],
        "next_jobs": [job for job in jobs if job["status"] == "DUE_NOW"][:6],
        "stale_datasets": stale,
        "massive_orchestrator": massive_orchestrator,
        "repair_plan": repair,
        "execution_freshness_gate": gate,
        "tradability": tradability,
        "summary": _queue_summary(jobs, stale, repair, tradability, massive_orchestrator),
    }


def build_affected_ticker_mini_cycle_plan(
    events: Sequence[Mapping[str, object]],
    *,
    tiers: TickerTiers,
    config_path: Path | None = None,
    now: datetime | None = None,
    max_events: int = 10,
) -> dict[str, object]:
    current = _utc(now)
    config_file = config_path or DEFAULT_CONFIG_PATH
    unique_events = _event_rows(events, max_events=max_events)
    jobs = [
        _mini_cycle_job(event, tiers=tiers, config_path=config_file, now=current)
        for event in unique_events
    ]
    affected = _sorted_tickers({_ticker(event) for event in unique_events})
    return {
        "schema_version": "0.1.0",
        "generated_at": current.isoformat(),
        "affected_tickers": affected,
        "job_count": len(jobs),
        "jobs": jobs,
        "detail": _mini_cycle_detail(affected),
    }


def build_off_hours_baseline_repair_plan(
    market_plan: Mapping[str, object],
    *,
    tiers: TickerTiers,
    config_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    current = _utc(now)
    session = _mapping(market_plan.get("market_session"))
    phase = str(session.get("phase", "unknown"))
    is_off_hours = phase in OFF_HOURS_PHASES
    rows = [
        _repair_job(
            row,
            tiers=tiers,
            off_hours=is_off_hours,
            config_path=config_path or DEFAULT_CONFIG_PATH,
        )
        for row in _mapping_rows(market_plan, "datasets")
        if _is_repair_dataset_row(row)
        and str(row.get("dataset")) not in {"news_rss", "subscription_emails"}
    ]
    status_label = "Ready Off-Hours" if is_off_hours and rows else "Deferred" if rows else "Clear"
    return {
        "schema_version": "0.1.0",
        "generated_at": current.isoformat(),
        "state": "active" if is_off_hours and rows else "deferred" if rows else "clear",
        "status_label": status_label,
        "status_class": "pass" if is_off_hours or not rows else "warn",
        "market_phase": phase,
        "job_count": len(rows),
        "jobs": rows,
        "detail": _repair_detail(rows, is_off_hours=is_off_hours),
    }


def execution_freshness_gate(
    broker: Mapping[str, object],
    source_health: Sequence[Mapping[str, object]],
    *,
    now: datetime | None = None,
    max_broker_age_seconds: int = 60,
    max_source_age_seconds: int | None = None,
    market_phase: str | None = None,
) -> dict[str, object]:
    current = _utc(now)
    phase = str(market_phase or "unspecified")
    closed_market_source_policy = market_phase is not None and phase in OFF_HOURS_PHASES
    test_freshness_mode = _env_bool(os.environ.get(TEST_FRESHNESS_MODE_ENV))
    effective_max_source_age_seconds = _effective_source_max_age_seconds(
        max_source_age_seconds,
        test_freshness_mode=test_freshness_mode,
    )
    broker_checked_at = _parse_datetime(broker.get("checked_at"))
    broker_age = (
        None if broker_checked_at is None else int((current - broker_checked_at).total_seconds())
    )
    checks = [
        _broker_freshness_check(
            broker,
            broker_age=broker_age,
            max_broker_age_seconds=max_broker_age_seconds,
        )
    ]
    critical_by_source = {
        str(row.get("source")): row
        for row in source_health
        if str(row.get("source")) in CRITICAL_EXECUTION_SOURCES
    }
    missing_sources = sorted(CRITICAL_EXECUTION_SOURCES.difference(critical_by_source))
    checks.extend(
        _source_freshness_check(
            row,
            now=current,
            max_source_age_seconds=effective_max_source_age_seconds,
            market_phase=phase,
        )
        for row in critical_by_source.values()
    )
    for source in missing_sources:
        checks.append(
            {
                "label": source.replace("-", " ").title(),
                "status": "BLOCK",
                "status_class": "block",
                "detail": (
                    f"{source} has no source-health row; execution is closed until "
                    "freshness is verified."
                ),
            }
        )
    blocked = [check for check in checks if check["status"] == "BLOCK"]
    warned = [check for check in checks if check["status"] == "WARN"]
    state = "blocked" if blocked else "warning" if warned else "pass"
    status_label = (
        "Fresh" if state == "pass" else "Review Freshness" if state == "warning" else "Blocked"
    )
    return {
        "schema_version": "0.1.0",
        "ready": not blocked,
        "state": state,
        "status_label": status_label,
        "status_class": _status_class(state),
        "max_broker_age_seconds": max_broker_age_seconds,
        "max_source_age_seconds": effective_max_source_age_seconds,
        "market_phase": phase,
        "closed_market_source_policy": closed_market_source_policy,
        "test_freshness_mode": test_freshness_mode,
        "source_max_age_policy_label": _source_max_age_policy_label(
            effective_max_source_age_seconds,
            test_freshness_mode=test_freshness_mode,
            closed_market_source_policy=closed_market_source_policy,
        ),
        "broker_age_seconds": broker_age,
        "checks": checks,
        "blocker_count": len(blocked),
        "warning_count": len(warned),
        "detail": str(blocked[0]["detail"] if blocked else checks[0]["detail"]),
    }


def _dataset_job(
    row: Mapping[str, object],
    *,
    tiers: TickerTiers,
    progress: Mapping[str, object],
    scheduler_runtime: Mapping[str, object],
    session: Mapping[str, object],
    config_path: Path,
    massive_orchestrator: Mapping[str, object],
    now: datetime,
) -> dict[str, object]:
    dataset = str(row.get("dataset", "unknown"))
    phase = str(session.get("phase", "unknown"))
    ticker_tier = _dataset_ticker_tier(dataset, phase)
    tickers = _dataset_job_tickers(row, tiers=tiers, ticker_tier=ticker_tier)
    ticker_count = len(tickers) or _int_value(row.get("ticker_count"), 0)
    max_batch = _int_or_none(row.get("max_tickers_per_batch"))
    status = _job_status(
        name=dataset,
        batch_action=str(row.get("batch_action", "")),
        extraction_action=str(row.get("extraction_action", "")),
        progress=progress,
    )
    reason = _combined_reason(row)
    status, reason = _apply_cadence_gate(
        status,
        reason,
        job_id=f"dataset:{dataset}",
        cadence_minutes=_int_or_none(row.get("cadence_minutes")),
        scheduler_runtime=scheduler_runtime,
        now=now,
    )
    massive_owner = _massive_dataset_owner(dataset, massive_orchestrator)
    if (dataset == "stock_trades" or massive_owner) and status not in {"SKIPPED", "DISABLED"}:
        status = "SKIPPED"
        ticker_count = len(tickers)
        if massive_owner:
            reason = (
                f"{reason} Massive Lane Orchestrator owns this raw endpoint via "
                f"{massive_owner}; generic dataset command suppressed to avoid duplicate "
                "Massive pulls."
            )
        else:
            reason = (
                f"{reason} stock_trades is lane-owned; generic dataset command "
                "suppressed until a Massive lane declaration is present."
            )
    if (
        dataset == "subscription_emails"
        and status in {"DUE_NOW", "RUNNING"}
        and _dataset_requires_interactive_user_action(dataset, config_path)
    ):
        status = "WAITING"
        reason = (
            f"{reason} User login is required before the subscription email agent "
            "can open protected article links. Use the app/manual email-login flow; "
            "the automatic scheduler will not run this interactive job headlessly."
        )
    if _dataset_requires_tickers(dataset) and not tickers and status in {"DUE_NOW", "WAITING"}:
        status = "SKIPPED"
        ticker_count = 0
        reason = (
            f"{reason} No tickers are present in tier {ticker_tier}; scheduler skipped "
            "the job instead of falling back to the configured universe."
        )
    return {
        "job_id": f"dataset:{dataset}",
        "kind": "dataset",
        "name": dataset,
        "dataset": dataset,
        "signal_lane": None,
        "status": status,
        "status_class": _job_status_class(status),
        "priority": _int_value(row.get("priority"), 0),
        "cadence_minutes": row.get("cadence_minutes"),
        "ticker_tier": ticker_tier,
        "ticker_count": ticker_count,
        "ticker_sample": tickers[:8],
        "eta_seconds": _dataset_eta_seconds(dataset, ticker_count, status),
        "eta_label": _eta_label(_dataset_eta_seconds(dataset, ticker_count, status)),
        "command": _dataset_command(
            dataset,
            row=row,
            tickers=tickers,
            max_tickers=max_batch,
            status=status,
            config_path=config_path,
            market_date=str(session.get("market_date") or ""),
        ),
        "reason": reason,
    }


def _dataset_requires_interactive_user_action(dataset: str, config_path: Path) -> bool:
    if dataset != "subscription_emails":
        return False
    try:
        overrides = load_refresh_config(config_path, repo_root=REPO_ROOT)
    except OSError, ValueError, TypeError, json.JSONDecodeError:
        return True
    config_file = overrides.subscription_email_config
    if config_file is None:
        return True
    path = config_file if config_file.is_absolute() else REPO_ROOT / config_file
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError, json.JSONDecodeError:
        return True
    if not isinstance(payload, Mapping):
        return True
    if payload.get("article_login_preflight_required") is True:
        return True
    if payload.get("follow_article_links") is not True:
        return False
    enabled_services = {
        str(service).strip().lower()
        for service in _sequence(payload.get("enabled_services"))
        if str(service).strip()
    }
    article_domains = {
        str(domain).strip().lower()
        for domain in _sequence(payload.get("article_link_domains"))
        if str(domain).strip()
    }
    protected_services = {"seeking_alpha"}
    protected_domains = {"seekingalpha.com", "email.seekingalpha.com"}
    return bool(
        protected_services.intersection(enabled_services)
        or protected_domains.intersection(article_domains)
    )


def _signal_job(
    row: Mapping[str, object],
    *,
    tiers: TickerTiers,
    progress: Mapping[str, object],
    scheduler_runtime: Mapping[str, object],
    phase: str,
    config_path: Path,
    now: datetime,
    massive_orchestrator: Mapping[str, object] | None = None,
) -> dict[str, object]:
    lane = str(row.get("lane", "unknown"))
    dataset = str(row.get("dataset", "unknown"))
    ticker_tier = _dataset_ticker_tier(dataset, phase)
    tickers = _tier_tickers(tiers, ticker_tier)
    status = _job_status(
        name=lane,
        batch_action=str(row.get("batch_action", "")),
        extraction_action=str(row.get("cadence", "")),
        progress=progress,
    )
    reason = str(row.get("reason", "No scheduler rationale recorded."))
    status, reason = _apply_cadence_gate(
        status,
        reason,
        job_id=f"signal:{lane}",
        cadence_minutes=_int_or_none(row.get("cadence_minutes")),
        scheduler_runtime=scheduler_runtime,
        now=now,
    )
    raw_requirements = [
        str(value)
        for value in _sequence(row.get("requires_massive_raw_lanes"))
        if str(value).strip()
    ]
    raw_gate = _raw_requirement_gate(raw_requirements, massive_orchestrator or {})
    if raw_gate["state"] == "blocked":
        status = "BLOCKED"
        reason = f"{reason} {raw_gate['detail']}"
    elif raw_gate["state"] == "waiting" and status not in {"DISABLED", "SKIPPED"}:
        status = "WAITING"
        reason = f"{reason} {raw_gate['detail']}"
    raw_gate_allows_partial_handoff = raw_gate["state"] in {
        "not_required",
        "ready",
    } or (
        raw_gate["state"] == "waiting"
        and all(
            lane in {"massive_live_trade_slices", "massive_premarket_trade_slices"}
            for lane in raw_requirements
        )
    )
    ready_tickers = _pipeline_ready_tickers(progress, dataset)
    usable_tickers = _pipeline_usable_tickers(progress, dataset)
    pass_forward_tickers = ready_tickers or usable_tickers
    if pass_forward_tickers:
        tier_set = set(tickers)
        tickers = [ticker for ticker in pass_forward_tickers if tier_set and ticker in tier_set]
        pass_forward_label = "fully complete" if ready_tickers else "usable live"
        if tickers:
            reason = (
                f"{reason} Massive ticker slices pass forward immediately; "
                f"scoping this signal job to {len(tickers)} {pass_forward_label} "
                "ticker(s)."
            )
            if status in {"WAITING", "SKIPPED"} and raw_gate_allows_partial_handoff:
                status = "DUE_NOW"
        else:
            reason = (
                f"{reason} Pass-forward stock-trade slices exist, but none are in "
                f"active tier {ticker_tier}; scheduler will not fall back to lower "
                "priority tickers during this phase."
            )
            if raw_gate["state"] == "waiting":
                status = "WAITING"
            else:
                status = "WAITING" if _trade_pull_running(progress) else "SKIPPED"
    elif dataset == "stock_trades" and _trade_pull_running(progress):
        tickers = []
        status = "WAITING" if status not in {"DISABLED", "SKIPPED"} else status
        reason = (
            f"{reason} Waiting for the first fully completed stock-trade ticker before "
            "running market-flow signal jobs."
        )
    if (
        not tickers
        and status in {"DUE_NOW", "WAITING"}
        and not (dataset == "stock_trades" and _trade_pull_running(progress))
        and raw_gate["state"] != "waiting"
    ):
        status = "SKIPPED"
        reason = (
            f"{reason} No tickers are present in tier {ticker_tier}; scheduler skipped "
            "the partial signal refresh instead of falling back to the configured universe."
        )
    eta = _signal_eta_seconds(lane, len(tickers), status)
    return {
        "job_id": f"signal:{lane}",
        "kind": "signal_lane",
        "name": lane,
        "dataset": dataset,
        "signal_lane": lane,
        "status": status,
        "status_class": _job_status_class(status),
        "priority": _int_value(row.get("priority"), 0),
        "cadence_minutes": row.get("cadence_minutes"),
        "ticker_tier": ticker_tier,
        "ticker_count": len(tickers),
        "ticker_sample": tickers[:8],
        "eta_seconds": eta,
        "eta_label": _eta_label(eta),
        "requires_massive_raw_lanes": raw_requirements,
        "raw_requirement_status": raw_gate["status"],
        "raw_requirement_detail": raw_gate["detail"],
        "command": _signal_command(
            lane,
            tickers=tickers,
            status=status,
            config_path=config_path,
        ),
        "reason": reason,
    }


def _pipeline_ready_tickers(progress: Mapping[str, object], dataset: str) -> list[str]:
    if dataset != "stock_trades":
        return []
    trade_pull = _mapping(progress.get("trade_pull"))
    values = _sequence(trade_pull.get("pipeline_ready_tickers"))
    return _sorted_tickers({str(ticker).upper() for ticker in values if str(ticker).strip()})


def _pipeline_usable_tickers(progress: Mapping[str, object], dataset: str) -> list[str]:
    if dataset != "stock_trades":
        return []
    trade_pull = _mapping(progress.get("trade_pull"))
    values = _sequence(trade_pull.get("pipeline_usable_tickers"))
    return _sorted_tickers({str(ticker).upper() for ticker in values if str(ticker).strip()})


def _trade_pull_running(
    progress: Mapping[str, object],
    *,
    lane_id: str | None = None,
    row: Mapping[str, object] | None = None,
) -> bool:
    trade_pull = _mapping(progress.get("trade_pull"))
    if lane_id:
        lane_rows = _mapping_rows(progress, "massive_lanes")
        if lane_rows and any(
            str(lane_row.get("lane_id") or "") == lane_id
            and str(lane_row.get("state") or "").lower() == "running"
            and _progress_window_matches_lane(row, lane_row)
            for lane_row in lane_rows
        ):
            return True
        running_lane = str(trade_pull.get("lane_id") or "")
        if running_lane and running_lane != lane_id:
            return False
    running = (
        progress.get("state") == "running"
        and str(progress.get("current_dataset")) in {"stock_trades", "stock-trades"}
    ) or trade_pull.get("state") == "running"
    if not running:
        return False
    return _progress_window_matches_lane(row, trade_pull) if row is not None else True


def _massive_lane_progress_running(
    progress: Mapping[str, object],
    lane_id: str,
    row: Mapping[str, object] | None = None,
) -> bool:
    if not lane_id:
        return False
    for lane_row in _mapping_rows(progress, "massive_lanes"):
        if str(lane_row.get("lane_id") or "") != lane_id:
            continue
        return str(
            lane_row.get("state") or ""
        ).lower() == "running" and _progress_window_matches_lane(row, lane_row)
    return False


def _progress_window_matches_lane(
    lane_row: Mapping[str, object] | None,
    progress_row: Mapping[str, object],
) -> bool:
    if lane_row is None:
        return True
    expected_start = _row_date_text(lane_row.get("start"))
    expected_end = _row_date_text(lane_row.get("end")) or expected_start
    if not expected_start or not expected_end:
        return True
    actual_start = _progress_date_text(progress_row.get("start"))
    actual_end = _progress_date_text(progress_row.get("end")) or actual_start
    if not actual_start or not actual_end:
        window = _mapping(progress_row.get("window"))
        actual_start = _progress_date_text(window.get("start"))
        actual_end = _progress_date_text(window.get("end")) or actual_start
    if not actual_start or not actual_end:
        return False
    return actual_start == expected_start and actual_end == expected_end


def _progress_date_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text[:10] if len(text) >= 10 else text


def _repair_job(
    row: Mapping[str, object],
    *,
    tiers: TickerTiers,
    off_hours: bool,
    config_path: Path,
) -> dict[str, object]:
    dataset = str(row.get("dataset", "unknown"))
    ticker_tier = "T3" if dataset in {"sec_company_facts", "sec_13f"} else "T2"
    tickers = _massive_lane_tickers(row, tiers=tiers, ticker_tier=ticker_tier)
    ticker_count = len(tickers) or _int_value(row.get("ticker_count"), 0)
    status = "DUE_NOW" if off_hours else "DEFERRED"
    eta = _dataset_eta_seconds(dataset, ticker_count, status)
    return {
        "job_id": f"repair:{dataset}",
        "dataset": dataset,
        "status": status,
        "status_class": _job_status_class(status),
        "priority": _int_value(row.get("priority"), 0),
        "ticker_tier": ticker_tier,
        "ticker_count": ticker_count,
        "ticker_sample": tickers[:8],
        "eta_seconds": eta,
        "eta_label": _eta_label(eta),
        "command": _repair_command(
            row,
            tickers=tickers,
            config_path=config_path,
            status=status,
        ),
        "reason": str(row.get("extraction_reason") or row.get("reason") or "Baseline repair due."),
    }


def _mini_cycle_job(
    event: Mapping[str, object],
    *,
    tiers: TickerTiers,
    config_path: Path,
    now: datetime,
) -> dict[str, object]:
    ticker = _ticker(event)
    event_type = str(event.get("event_type") or event.get("source") or "unknown")
    lanes = EVENT_LANE_MAP.get(event_type, ("news", "subscription_thesis"))
    tier = _ticker_tier_for_ticker(ticker, tiers)
    event_slug = _slug(event_type)
    cycle_id = f"mini-{ticker.lower()}-{event_slug}-{now.strftime('%Y%m%dT%H%M%SZ')}"
    command = [
        ".\\.venv\\Scripts\\python",
        "scripts\\run_live_runtime_cycle.py",
        "--config",
        _display_repo_path(config_path),
        "--ticker",
        ticker,
        "--cycle-id",
        cycle_id,
        "--audit-trigger",
        "SCHEDULED",
        "--no-persist",
        "--output-root",
        _display_repo_path(MINI_RUNTIME_OUTPUT_ROOT / event_slug / ticker.lower()),
    ]
    for lane in lanes:
        command.extend(["--signal", lane])
    return {
        "job_id": f"mini-cycle:{ticker}:{event_type}",
        "ticker": ticker,
        "ticker_tier": tier,
        "status": "DUE_NOW",
        "status_class": "warn",
        "priority": _mini_cycle_priority(tier),
        "trigger": event_type,
        "lanes": list(lanes),
        "eta_seconds": 45 + 8 * len(lanes),
        "eta_label": _eta_label(45 + 8 * len(lanes)),
        "command": command,
        "reason": f"{ticker} changed because of {event_type}; recompute only this ticker.",
    }


def _broker_freshness_check(
    broker: Mapping[str, object],
    *,
    broker_age: int | None,
    max_broker_age_seconds: int,
) -> dict[str, object]:
    if "connected" not in broker:
        return {
            "label": "Broker state",
            "status": "WARN",
            "status_class": "warn",
            "detail": (
                "Broker freshness has not been checked in this scheduler view; "
                "execution submit will refresh it before any paper order."
            ),
        }
    if _broker_connection_not_confirmed(broker):
        status_label = str(broker.get("status_label") or "Broker check pending")
        detail = str(broker.get("detail") or "").strip()
        return {
            "label": "Broker state",
            "status": "WARN",
            "status_class": "warn",
            "detail": (
                f"{status_label}: broker connection is not confirmed yet. "
                "Execution submit still performs a strict fresh Alpaca paper check "
                "before any order can be submitted." + (f" {detail}" if detail else "")
            ),
        }
    if broker.get("connected") is not True:
        return {
            "label": "Broker state",
            "status": "BLOCK",
            "status_class": "block",
            "detail": "Broker is not connected; paper order submission is closed.",
        }
    if str(broker.get("mode", "paper")).lower() != "paper":
        return {
            "label": "Broker state",
            "status": "BLOCK",
            "status_class": "block",
            "detail": "Broker snapshot is not from the Alpaca paper endpoint.",
        }
    if broker_age is None:
        return {
            "label": "Broker state",
            "status": "BLOCK",
            "status_class": "block",
            "detail": "Broker snapshot has no checked_at timestamp.",
        }
    if broker_age > max_broker_age_seconds:
        return {
            "label": "Broker state",
            "status": "BLOCK",
            "status_class": "block",
            "detail": f"Broker snapshot is {broker_age}s old; refresh before submitting.",
        }
    return {
        "label": "Broker state",
        "status": "PASS",
        "status_class": "pass",
        "detail": f"Broker snapshot is fresh ({broker_age}s old).",
    }


def _broker_connection_not_confirmed(broker: Mapping[str, object]) -> bool:
    if broker.get("connected") is True:
        return False
    status_label = str(broker.get("status_label") or "").strip().lower()
    return status_label in {"broker check pending", "broker check delayed"}


def _source_freshness_check(
    row: Mapping[str, object],
    *,
    now: datetime,
    max_source_age_seconds: int,
    market_phase: str,
) -> dict[str, object]:
    source = str(row.get("source", "unknown"))
    freshness = str(row.get("freshness", "UNAVAILABLE"))
    status = str(row.get("status", "UNKNOWN"))
    checked_at = _parse_datetime(row.get("checked_at"))
    age_seconds = None if checked_at is None else int((now - checked_at).total_seconds())
    closed_market_current = (
        checked_at is not None
        and market_phase in OFF_HOURS_PHASES
        and _closed_market_source_current(source, checked_at=checked_at, now=now)
    )
    latest_completed_daily_bar_current = (
        checked_at is not None
        and source == "daily-market-bars"
        and _closed_market_source_current(source, checked_at=checked_at, now=now)
    )
    blocked = freshness in {"STALE", "UNAVAILABLE"} or status in {
        "STALE",
        "UNAVAILABLE",
        "RATE_LIMITED",
    }
    warned = not blocked and (
        status in {"DEGRADED", "UNKNOWN"} or freshness in {"AGING", "PARTIAL", "UNKNOWN"}
    )
    if checked_at is None:
        blocked = True
        warned = False
        detail = f"{source} has no checked_at timestamp; execution freshness is unverified."
    elif (
        age_seconds is not None
        and age_seconds > max_source_age_seconds
        and not closed_market_current
        and not latest_completed_daily_bar_current
    ):
        blocked = True
        warned = False
        detail = (
            f"{source} source-health row is {age_seconds}s old; refresh critical "
            "evidence before submitting."
        )
    elif latest_completed_daily_bar_current and age_seconds is not None:
        detail = (
            f"{source} freshness is {freshness}; source status is {status}; "
            f"checked {age_seconds}s ago. Daily bars are current through the "
            "latest completed session; intraday daily bars do not update "
            "until the market closes."
        )
    elif closed_market_current and age_seconds is not None:
        detail = (
            f"{source} freshness is {freshness}; source status is {status}; "
            f"checked {age_seconds}s ago. Closed-market validation accepts the "
            "latest completed session because no new tape is expected until the "
            "next trading session."
        )
    else:
        detail = (
            f"{source} freshness is {freshness}; source status is {status}; "
            f"checked {age_seconds}s ago."
        )
    result_status = "BLOCK" if blocked else "WARN" if warned else "PASS"
    return {
        "label": source.replace("-", " ").title(),
        "status": result_status,
        "status_class": "block" if blocked else "warn" if warned else "pass",
        "detail": detail,
    }


def _effective_source_max_age_seconds(
    explicit_value: int | None,
    *,
    test_freshness_mode: bool,
) -> int:
    if explicit_value is not None:
        return explicit_value
    if not test_freshness_mode:
        return DEFAULT_MAX_SOURCE_HEALTH_AGE_SECONDS
    return _positive_int_env(
        TEST_SOURCE_MAX_AGE_SECONDS_ENV,
        default=DEFAULT_MAX_SOURCE_HEALTH_AGE_SECONDS,
    )


def _source_max_age_policy_label(
    max_age_seconds: int,
    *,
    test_freshness_mode: bool,
    closed_market_source_policy: bool,
) -> str:
    if closed_market_source_policy and not test_freshness_mode:
        return "closed-market latest completed session"
    label = _eta_label(max_age_seconds)
    if test_freshness_mode:
        return f"test rehearsal source-health window: {label}"
    return f"production source-health window: {label}"


def _closed_market_source_current(
    source: str,
    *,
    checked_at: datetime,
    now: datetime,
) -> bool:
    if source not in CRITICAL_EXECUTION_SOURCES:
        return False
    return checked_at.date() >= _latest_completed_market_date(now)


def _latest_completed_market_date(now: datetime) -> date:
    try:
        from data_refresh.market_calendar import (
            classify_market_session,
            previous_trading_day,
        )
    except ModuleNotFoundError:
        return _previous_weekday(now.date()) if now.weekday() >= 5 else now.date()
    session = classify_market_session(now)
    if not session.is_trading_day:
        return previous_trading_day(session.market_date)
    if session.phase in {"pre_market", "regular_market", "overnight_before_pre_market"}:
        return previous_trading_day(session.market_date)
    return session.market_date


def _previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _positive_int_env(name: str, *, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _env_bool(value: str | None) -> bool:
    if value is None or not value.strip():
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _tradability(
    *,
    data_load_status: Mapping[str, object],
    data_refresh_progress: Mapping[str, object],
    execution_gate: Mapping[str, object],
    jobs: Sequence[Mapping[str, object]],
    stale_datasets: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    refresh_state = str(data_refresh_progress.get("state", "idle"))
    if execution_gate.get("ready") is not True:
        state = "context_only"
        detail = str(execution_gate.get("detail", "Execution freshness gate is closed."))
    elif refresh_state in {"stale", "blocked", "failed", "unavailable"}:
        state = "context_only"
        detail = str(
            data_refresh_progress.get(
                "detail",
                "Data refresh progress is not in a tradable state.",
            )
        )
    elif refresh_state == "running" and _running_refresh_blocks_tradability(data_refresh_progress):
        state = "context_only"
        detail = str(
            data_refresh_progress.get(
                "detail",
                "Execution-critical data refresh is still running.",
            )
        )
    elif _execution_blocking_lane_state_rows(stale_datasets):
        state = "context_only"
        lane = _execution_blocking_lane_state_rows(stale_datasets)[0]
        detail = str(
            lane.get("reason") or "A required lane is not fresh enough for paper execution."
        )
    elif data_load_status.get("state") in {"blocked", "loading"}:
        state = "context_only"
        detail = str(data_load_status.get("detail", "Data load is not tradable yet."))
    elif (
        any(job["status"] == "DUE_NOW" and job["kind"] == "dataset" for job in jobs)
        and data_load_status.get("review_operational_ready") is not True
    ):
        state = "context_only"
        detail = "One or more market-moving data jobs are due; refresh before new orders."
    elif stale_datasets and data_load_status.get("review_operational_ready") is not True:
        state = "context_only"
        detail = "Some datasets need refresh or attention; keep decisions in review mode."
    else:
        state = "tradable"
        if _execution_gate_has_unconfirmed_broker_warning(execution_gate):
            detail = (
                "Critical evidence is fresh; broker status is not confirmed in this "
                "dashboard check. Paper submit remains protected by a strict live "
                "Alpaca broker check before any order can be sent: "
                f"{execution_gate.get('detail', 'broker check pending.')}"
            )
        elif execution_gate.get("state") == "warning":
            detail = (
                "Broker and critical evidence are fresh enough for paper orders "
                f"with caution: {execution_gate.get('detail', 'review freshness warnings.')}"
            )
        else:
            detail = (
                "Broker, critical evidence, and scheduler queue are fresh enough for paper orders."
            )
    tradable_with_warning = state == "tradable" and execution_gate.get("state") == "warning"
    return {
        "state": state,
        "status_label": (
            "Tradable With Caution"
            if tradable_with_warning
            else "Tradable"
            if state == "tradable"
            else "Context Only"
        ),
        "status_class": "warn"
        if tradable_with_warning
        else "pass"
        if state == "tradable"
        else "warn",
        "detail": detail,
    }


def _execution_gate_has_unconfirmed_broker_warning(
    execution_gate: Mapping[str, object],
) -> bool:
    for check in _mapping_rows(execution_gate, "checks"):
        if (
            str(check.get("label")) == "Broker state"
            and str(check.get("status")) == "WARN"
            and "not confirmed" in str(check.get("detail", "")).lower()
        ):
            return True
    return False


def _running_refresh_blocks_tradability(
    data_refresh_progress: Mapping[str, object],
) -> bool:
    current_dataset = (
        str(
            data_refresh_progress.get("current_dataset")
            or data_refresh_progress.get("running_dataset")
            or ""
        )
        .strip()
        .lower()
    )
    if not current_dataset:
        return True
    if current_dataset in CRITICAL_REFRESH_DATASETS:
        return True
    return _trade_pull_running(data_refresh_progress)


def _massive_orchestrator_status(
    orchestrator: Mapping[str, object],
    *,
    tiers: TickerTiers,
    progress: Mapping[str, object],
    source_health: Sequence[Mapping[str, object]],
    session: Mapping[str, object],
    config_path: Path,
    now: datetime,
) -> dict[str, object]:
    rows = _mapping_rows(orchestrator, "raw_lanes") or _mapping_rows(orchestrator, "lanes")
    source_index = {
        str(row.get("source") or ""): row for row in source_health if str(row.get("source") or "")
    }
    lane_rows = [
        _massive_lane_row(
            row,
            tiers=tiers,
            progress=progress,
            source_index=source_index,
            session=session,
            config_path=config_path,
            now=now,
        )
        for row in rows
    ]
    derived_rows = [
        _massive_signal_requirement_row(row, lane_rows)
        for row in _mapping_rows(orchestrator, "derived_signal_lanes")
    ]
    counts = {
        "running": _count_status(lane_rows, "RUNNING"),
        "due_now": _count_status(lane_rows, "DUE_NOW"),
        "deferred": _count_status(lane_rows, "DEFERRED"),
        "skipped": _count_status(lane_rows, "SKIPPED"),
        "blocked": _count_status(lane_rows, "BLOCKED"),
        "disabled": _count_status(lane_rows, "DISABLED"),
        "ready_from_raw": _count_status(lane_rows, "READY_FROM_RAW"),
        "health_blocked": sum(
            1
            for row in lane_rows
            if row.get("health_status_class") == "block"
            and row.get("blocks_execution") is True
            and row.get("status") not in {"DISABLED", "DEFERRED", "DUE_NOW", "RUNNING", "WAITING"}
        ),
    }
    state = _massive_orchestrator_state(counts)
    return {
        "schema_version": "0.1.0",
        "generated_at": now.isoformat(),
        "provider": str(orchestrator.get("provider") or "massive"),
        "market_phase": str(orchestrator.get("market_phase") or session.get("phase") or "unknown"),
        "state": state,
        "status_label": _massive_orchestrator_status_label(state),
        "status_class": _massive_orchestrator_status_class(state),
        "lane_count": len(lane_rows),
        "raw_lane_count": len(lane_rows),
        "derived_signal_lane_count": len(derived_rows),
        "due_now_count": counts["due_now"],
        "running_count": counts["running"],
        "blocked_count": counts["blocked"] + counts["health_blocked"],
        "deferred_count": counts["deferred"],
        "counts": counts,
        "lanes": sorted(lane_rows, key=_job_sort_key),
        "raw_lanes": sorted(lane_rows, key=_job_sort_key),
        "derived_signal_lanes": sorted(derived_rows, key=_job_sort_key),
        "detail": _massive_orchestrator_detail(counts, lane_rows),
    }


def _massive_lane_row(
    row: Mapping[str, object],
    *,
    tiers: TickerTiers,
    progress: Mapping[str, object],
    source_index: Mapping[str, Mapping[str, object]],
    session: Mapping[str, object],
    config_path: Path,
    now: datetime,
) -> dict[str, object]:
    dataset = str(row.get("dataset") or "unknown")
    raw_source_dataset = str(row.get("raw_source_dataset") or dataset)
    lane_id = str(row.get("lane_id") or "unknown")
    status = _massive_lane_status(row, progress)
    reason = str(row.get("reason") or "No Massive lane rationale recorded.")
    ticker_tier = str(
        row.get("ticker_tier")
        or _dataset_ticker_tier(raw_source_dataset, str(session.get("phase") or ""))
    )
    tickers = _massive_lane_tickers(row, tiers=tiers, ticker_tier=ticker_tier)
    max_batch = _int_or_none(row.get("max_tickers_per_batch"))
    if _massive_lane_requires_tickers(row) and not tickers and status in {"DUE_NOW", "RUNNING"}:
        status = "SKIPPED"
    manifest = _massive_lane_manifest(row)
    if status == "READY_FROM_RAW":
        status = _local_derivation_lane_status(
            row,
            manifest=manifest,
            progress=progress,
            now=now,
        )
    source_name = _massive_lane_source(raw_source_dataset)
    source = source_index.get(source_name, {})
    health = _massive_lane_health(
        source_name,
        source,
        row=row,
        manifest=manifest,
        now=now,
    )
    fresh_tickers = set(tickers).intersection(_fresh_massive_lane_tickers(row, manifest, now=now))
    if _daily_bar_active_repair_due(
        row,
        status=status,
        tickers=tickers,
        fresh_tickers=fresh_tickers,
        manifest=manifest,
        now=now,
    ):
        missing_count = max(len(tickers) - len(fresh_tickers), 0)
        status = "DUE_NOW"
        reason = (
            f"{reason} Massive Daily Bars lane coverage is incomplete for the active "
            f"universe: missing {missing_count} active ticker(s)."
        )
    command_tickers = _command_scope_tickers(
        row,
        tickers=tickers,
        fresh_tickers=fresh_tickers,
        failed_tickers=_failed_massive_lane_tickers(row, manifest),
        status=status,
    )
    if (
        _massive_lane_requires_tickers(row)
        and status in {"DUE_NOW", "RUNNING"}
        and not command_tickers
    ):
        status = "SKIPPED"
    if _unsupported_massive_api_lane_due(row, status):
        status = "BLOCKED"
        reason = (
            f"{reason} No lane runner is registered for Massive command profile "
            f"{row.get('command_profile') or 'unknown'}; generic data-refresh "
            "batch fallback is disabled so Massive pulls remain lane-owned."
        )
    eta = _massive_lane_eta_seconds(row, len(tickers), status)
    command = _massive_lane_command(
        row,
        tickers=command_tickers,
        max_tickers=max_batch,
        status=status,
        config_path=config_path,
        market_date=str(session.get("market_date") or ""),
    )
    command_ticker_count = _command_ticker_count(command)
    return {
        "job_id": f"massive:{lane_id}",
        "kind": "massive_lane",
        "name": lane_id,
        "lane_id": lane_id,
        "label": str(row.get("label") or lane_id.replace("_", " ").title()),
        "purpose": str(row.get("purpose") or "No lane purpose recorded."),
        "dataset": dataset,
        "raw_source_dataset": raw_source_dataset,
        "endpoint_family": str(row.get("endpoint_family") or "unknown"),
        "acquisition_mode": str(row.get("acquisition_mode") or "unknown"),
        "command_profile": str(row.get("command_profile") or "unknown"),
        "consumer_signal_lanes": _sequence(
            row.get("consumer_signal_lanes") or row.get("signal_lanes")
        ),
        "signal_lanes": _sequence(row.get("signal_lanes")),
        "requires_raw_lanes": _sequence(row.get("requires_raw_lanes")),
        "creates_massive_request": row.get("creates_massive_request") is True,
        "request_budget_label": str(row.get("request_budget_label") or "not recorded"),
        "max_requests_per_cycle": row.get("max_requests_per_cycle"),
        "storage_manifest": str(row.get("storage_manifest") or ""),
        "status": status,
        "status_class": _job_status_class(status),
        "batch_action": str(row.get("batch_action") or ""),
        "priority": _int_value(row.get("priority"), 0),
        "cadence_minutes": row.get("cadence_minutes"),
        "ticker_tier": ticker_tier,
        "ticker_count": len(tickers),
        "fresh_ticker_count": len(fresh_tickers),
        "fresh_tickers": sorted(fresh_tickers),
        "pending_ticker_count": max(len(tickers) - len(fresh_tickers), 0),
        "batch_ticker_count": command_ticker_count,
        "command_ticker_count": command_ticker_count,
        "ticker_sample": tickers[:8],
        "eta_seconds": eta,
        "eta_label": _eta_label(eta),
        "window_label": str(row.get("window_label") or "not recorded"),
        "freshness_requirement_seconds": row.get("freshness_requirement_seconds"),
        "freshness_requirement_label": _freshness_requirement_label(
            row.get("freshness_requirement_seconds")
        ),
        "blocks_execution": row.get("blocks_execution") is True,
        "health_source": source_name,
        "health_status": health["status"],
        "health_freshness": health["freshness"],
        "health_status_class": health["status_class"],
        "health_checked_at": health["checked_at"],
        "health_detail": health["detail"],
        "manifest_status": str(manifest.get("status") or "missing"),
        "manifest_fetched_at": str(manifest.get("fetched_at") or "not recorded"),
        "manifest_coverage_pct": _int_value(manifest.get("coverage_pct"), 0),
        "manifest_issue_count": _int_value(manifest.get("issue_count"), 0),
        "command": command,
        "reason": reason,
    }


def _massive_signal_requirement_row(
    row: Mapping[str, object],
    raw_lanes: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    lane = str(row.get("signal_lane") or row.get("lane") or "unknown")
    required = [
        str(value) for value in _sequence(row.get("requires_raw_lanes")) if str(value).strip()
    ]
    gate = _raw_requirement_gate(required, {"lanes": list(raw_lanes)})
    status = gate["status"]
    return {
        "job_id": f"massive-signal:{lane}",
        "kind": "massive_signal_requirement",
        "name": lane,
        "signal_lane": lane,
        "label": str(row.get("label") or lane.replace("_", " ").title()),
        "requires_raw_lanes": required,
        "status": status,
        "status_class": _job_status_class(status),
        "priority": 0,
        "eta_seconds": 0,
        "eta_label": "n/a",
        "reason": gate["detail"] if required else str(row.get("reason") or gate["detail"]),
    }


def _command_scope_tickers(
    row: Mapping[str, object],
    *,
    tickers: Sequence[str],
    fresh_tickers: set[str],
    failed_tickers: set[str] | None = None,
    status: str,
) -> list[str]:
    if status not in {"DUE_NOW", "RUNNING"}:
        return list(tickers)
    profile = str(row.get("command_profile") or "")
    if profile not in {
        "stock_trades_live",
        "stock_trades_premarket",
        "prices_daily",
    }:
        return list(tickers)
    batch_action = str(row.get("batch_action") or "")
    if profile == "prices_daily" and (
        batch_action == "run_now" or (batch_action != "skip" and not fresh_tickers)
    ):
        return list(tickers)
    attempted_failures = set() if failed_tickers is None else failed_tickers
    pending = [
        ticker
        for ticker in tickers
        if ticker not in fresh_tickers and ticker not in attempted_failures
    ]
    if pending:
        return pending
    return []


def _massive_lane_tickers(
    row: Mapping[str, object],
    *,
    tiers: TickerTiers,
    ticker_tier: str,
) -> list[str]:
    row_tickers = _row_tickers(row)
    tier_tickers = _tier_tickers(tiers, ticker_tier)
    profile = str(row.get("command_profile") or "")
    if (
        profile in {"stock_trades_live", "stock_trades_premarket"}
        and tier_tickers
    ):
        return tier_tickers
    if row_tickers and tier_tickers:
        allowed = set(row_tickers)
        scoped = [ticker for ticker in tier_tickers if ticker in allowed]
        if scoped:
            return scoped
    if tier_tickers:
        return tier_tickers
    if profile in {"stock_trades_live", "stock_trades_premarket"}:
        active_scope = _tier_tickers(tiers, "T0/T1/T2")
        if active_scope:
            return active_scope
    return row_tickers


def _fresh_massive_lane_tickers(
    row: Mapping[str, object],
    manifest: Mapping[str, object],
    *,
    now: datetime,
) -> set[str]:
    profile = str(row.get("command_profile") or "")
    if profile == "prices_daily":
        return _fresh_daily_bar_lane_tickers(row, manifest, now=now)
    if profile not in {"stock_trades_live", "stock_trades_premarket"}:
        return set()
    if not manifest or not _manifest_window_matches_row(row, manifest):
        return set()
    required_seconds = _int_or_none(row.get("freshness_requirement_seconds")) or 0
    closed_market_current = _closed_market_lane_manifest_current(row, manifest, now=now)
    fresh: set[str] = set()
    fallback = _parse_datetime(manifest.get("fetched_at"))
    for item in _sequence(manifest.get("coverage")):
        coverage = _mapping(item)
        ticker = str(coverage.get("ticker") or "").upper().strip()
        if not ticker or not _live_lane_coverage_usable(coverage):
            continue
        observed_at = (
            _parse_datetime(coverage.get("updated_at") or coverage.get("fetched_at")) or fallback
        )
        if observed_at is None:
            continue
        if (
            required_seconds > 0
            and (now - observed_at).total_seconds() > required_seconds
            and not closed_market_current
        ):
            continue
        fresh.add(ticker)
    return fresh


def _failed_massive_lane_tickers(
    row: Mapping[str, object],
    manifest: Mapping[str, object],
) -> set[str]:
    if str(row.get("command_profile") or "") not in {
        "stock_trades_live",
        "stock_trades_premarket",
    }:
        return set()
    if not manifest or not _manifest_window_matches_row(row, manifest):
        return set()
    failed: set[str] = set()
    for item in _sequence(manifest.get("coverage")):
        coverage = _mapping(item)
        status = str(coverage.get("coverage_status") or coverage.get("status") or "").lower()
        if status != "failed":
            continue
        ticker = str(coverage.get("ticker") or "").upper().strip()
        if ticker:
            failed.add(ticker)
    return failed


def _fresh_daily_bar_lane_tickers(
    row: Mapping[str, object],
    manifest: Mapping[str, object],
    *,
    now: datetime,
) -> set[str]:
    if not manifest or not _daily_bar_manifest_covers_row(row, manifest):
        return set()
    required_seconds = _int_or_none(row.get("freshness_requirement_seconds")) or 0
    fetched_at = _parse_datetime(manifest.get("fetched_at"))
    if required_seconds > 0 and fetched_at is not None:
        age_seconds = (now - fetched_at).total_seconds()
        if age_seconds > required_seconds and not _closed_market_lane_manifest_current(
            row, manifest, now=now
        ):
            return set()
    coverage = [
        _mapping(item)
        for item in _sequence(manifest.get("coverage"))
        if str(_mapping(item).get("ticker") or "").strip()
    ]
    complete = {
        str(item.get("ticker") or "").upper().strip()
        for item in coverage
        if item.get("complete") is True
        or str(item.get("coverage_status") or item.get("status") or "").lower() == "complete"
    }
    if complete:
        return {ticker for ticker in complete if ticker}
    if str(manifest.get("status") or "").lower() != "complete":
        return set()
    return {
        str(ticker).upper().strip()
        for ticker in _sequence(manifest.get("tickers"))
        if str(ticker).strip()
    }


def _daily_bar_active_repair_due(
    row: Mapping[str, object],
    *,
    status: str,
    tickers: Sequence[str],
    fresh_tickers: set[str],
    manifest: Mapping[str, object],
    now: datetime,
) -> bool:
    if str(row.get("command_profile") or "") != "prices_daily":
        return False
    if status not in {"SKIPPED", "READY", "DEFERRED"}:
        return False
    if not tickers or len(fresh_tickers) >= len(tickers):
        return False
    return not _daily_bar_missing_confirmed_current(
        row,
        manifest,
        tickers=tickers,
        fresh_tickers=fresh_tickers,
        now=now,
    )


def _daily_bar_missing_confirmed_current(
    row: Mapping[str, object],
    manifest: Mapping[str, object],
    *,
    tickers: Sequence[str],
    fresh_tickers: set[str],
    now: datetime,
) -> bool:
    if not manifest or not _daily_bar_manifest_covers_row(row, manifest):
        return False
    fetched_at = _parse_datetime(manifest.get("fetched_at"))
    if fetched_at is None:
        return False
    required_seconds = _int_or_none(row.get("freshness_requirement_seconds")) or 0
    if required_seconds > 0 and (now - fetched_at).total_seconds() > required_seconds:
        return False
    pending = {ticker for ticker in tickers if ticker not in fresh_tickers}
    if not pending:
        return False
    for item in _sequence(manifest.get("coverage")):
        coverage = _mapping(item)
        ticker = str(coverage.get("ticker") or "").upper().strip()
        if ticker not in pending:
            continue
        status = str(coverage.get("coverage_status") or coverage.get("status") or "").lower()
        if status in {"missing", "no_data", "unavailable"}:
            return True
    return False


def _daily_bar_manifest_covers_row(
    row: Mapping[str, object],
    manifest: Mapping[str, object],
) -> bool:
    requested = _row_date_text(row.get("end")) or _row_date_text(row.get("start"))
    if not requested:
        return True
    manifest_end = _manifest_window_end_date(manifest) or _manifest_fetched_date(manifest)
    if manifest_end is None:
        return False
    try:
        requested_date = date.fromisoformat(requested)
    except ValueError:
        return False
    window = _mapping(manifest.get("window"))
    manifest_start = None
    value = window.get("start")
    if isinstance(value, str) and value.strip():
        try:
            manifest_start = date.fromisoformat(value.strip())
        except ValueError:
            manifest_start = None
    if manifest_start is None:
        manifest_start = manifest_end
    return manifest_start <= requested_date <= manifest_end


def _manifest_window_matches_row(
    row: Mapping[str, object],
    manifest: Mapping[str, object],
) -> bool:
    window = _mapping(manifest.get("window"))
    start = str(row.get("start") or "")
    end = str(row.get("end") or start)
    if not start or not end:
        return False
    return str(window.get("start") or "") == start and str(window.get("end") or "") == end


def _live_lane_coverage_usable(row: Mapping[str, object]) -> bool:
    status = str(row.get("coverage_status") or row.get("status") or "").lower()
    if row.get("complete") is True or status == "complete":
        return True
    if status not in {"partial", "partial_usable", "ready", "usable"}:
        return False
    if status == "partial_usable":
        return True
    rows = max(
        _int_value(row.get("downloaded_row_count"), 0), _int_value(row.get("rows_written"), 0)
    )
    pages = _int_value(row.get("pages_downloaded"), 0)
    return rows > 0 and pages > 0 and str(row.get("order") or "").lower() == "desc"


def _massive_lane_manifest(row: Mapping[str, object]) -> Mapping[str, object]:
    path_text = str(row.get("storage_manifest") or "")
    if not path_text:
        return {}
    path = Path(path_text)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return read_lane_manifest(path)


def _massive_lane_requires_tickers(row: Mapping[str, object]) -> bool:
    dataset = str(row.get("raw_source_dataset") or row.get("dataset") or "")
    if dataset not in {"stock_trades", "prices_daily", "options_chains"}:
        return False
    return str(row.get("command_profile") or "") != "reference_data"


def _massive_lane_status(
    row: Mapping[str, object],
    progress: Mapping[str, object],
) -> str:
    action = str(row.get("batch_action") or "")
    dataset = str(row.get("dataset") or "")
    lane_id = str(row.get("lane_id") or "")
    if action == "blocked":
        return "BLOCKED"
    if action == "disabled":
        return "DISABLED"
    if action == "skip":
        return "SKIPPED"
    if action == "defer":
        return "DEFERRED"
    if action == "derive_from_raw":
        return "READY_FROM_RAW"
    if action == "waiting_on_raw":
        return "WAITING"
    if action == "ready":
        return "READY"
    if action == "run_now":
        if _massive_lane_progress_running(progress, lane_id, row):
            return "RUNNING"
        current_dataset = str(progress.get("current_dataset") or "")
        if current_dataset in {dataset, dataset.replace("_", "-")}:
            if dataset != "stock_trades" or not lane_id:
                return "RUNNING"
            if _trade_pull_running(progress, lane_id=lane_id, row=row):
                return "RUNNING"
        if dataset == "stock_trades" and _trade_pull_running(progress, lane_id=lane_id, row=row):
            return "RUNNING"
        return "DUE_NOW"
    return "WAITING"


def _local_derivation_lane_status(
    row: Mapping[str, object],
    *,
    manifest: Mapping[str, object],
    progress: Mapping[str, object],
    now: datetime,
) -> str:
    del now
    lane_id = str(row.get("lane_id") or "")
    if _massive_lane_progress_running(progress, lane_id, row):
        return "RUNNING"
    if str(row.get("command_profile") or "") not in LOCAL_DERIVATION_COMMAND_PROFILES:
        return "READY_FROM_RAW"
    source_manifests = _required_raw_lane_manifests(row)
    if not source_manifests:
        return "WAITING"
    if any(_lane_manifest_blocked(source_manifest) for source_manifest in source_manifests):
        return "BLOCKED"
    if any(
        not source_manifest
        or not _manifest_window_matches_row(row, source_manifest)
        or not _lane_manifest_usable(source_manifest)
        for source_manifest in source_manifests
    ):
        return "WAITING"
    if not manifest or not _manifest_window_matches_row(row, manifest):
        return "DUE_NOW"
    if _lane_manifest_blocked(manifest):
        return "DUE_NOW"
    latest_source_fetched_at = max(
        (
            parsed
            for parsed in (
                _parse_datetime(source_manifest.get("fetched_at"))
                for source_manifest in source_manifests
            )
            if parsed is not None
        ),
        default=None,
    )
    derived_fetched_at = _parse_datetime(manifest.get("fetched_at"))
    if latest_source_fetched_at is not None and (
        derived_fetched_at is None or derived_fetched_at < latest_source_fetched_at
    ):
        return "DUE_NOW"
    return "READY_FROM_RAW"


def _required_raw_lane_manifests(
    row: Mapping[str, object],
) -> list[Mapping[str, object]]:
    manifests: list[Mapping[str, object]] = []
    explicit_paths = _mapping(row.get("source_lane_manifests") or row.get("raw_lane_manifests"))
    for lane_id in _sequence(row.get("requires_raw_lanes")):
        lane_text = str(lane_id).strip()
        if not lane_text:
            continue
        explicit_path = explicit_paths.get(lane_text)
        path = (
            Path(str(explicit_path))
            if isinstance(explicit_path, str) and explicit_path.strip()
            else manifest_path_for_lane(REPO_ROOT, lane_text)
        )
        manifests.append(read_lane_manifest(path))
    return manifests


def _lane_manifest_blocked(manifest: Mapping[str, object]) -> bool:
    status = _lane_manifest_effective_status(manifest)
    return status in {"blocked", "failed", "error"}


def _lane_manifest_usable(manifest: Mapping[str, object]) -> bool:
    status = _lane_manifest_effective_status(manifest)
    if status not in {"complete", "partial_usable", "ready", "usable"}:
        return False
    return (
        _int_value(manifest.get("coverage_pct"), 0) > 0
        or _int_value(
            manifest.get("row_count"),
            0,
        )
        > 0
    )


def _lane_manifest_effective_status(manifest: Mapping[str, object]) -> str:
    status = str(manifest.get("status") or "").lower()
    if status != "complete":
        return status
    if _lane_manifest_has_incomplete_coverage(manifest):
        return "partial_usable" if _lane_manifest_has_usable_rows(manifest) else "partial"
    return status


def _lane_manifest_has_incomplete_coverage(manifest: Mapping[str, object]) -> bool:
    complete_pct = manifest.get("complete_coverage_pct")
    if isinstance(complete_pct, int | float) and complete_pct < 100:
        return True
    coverage = manifest.get("coverage")
    if not isinstance(coverage, list) or not coverage:
        return False
    return any(
        not isinstance(row, Mapping)
        or str(row.get("coverage_status") or row.get("status") or "").lower() != "complete"
        or row.get("complete") is False
        or row.get("row_count_verified") is False
        for row in coverage
    )


def _lane_manifest_has_usable_rows(manifest: Mapping[str, object]) -> bool:
    if _int_value(manifest.get("usable_coverage_pct"), 0) > 0:
        return True
    if _int_value(manifest.get("coverage_pct"), 0) > 0:
        return True
    return _int_value(manifest.get("row_count"), 0) > 0


def _massive_lane_command(
    row: Mapping[str, object],
    *,
    tickers: Sequence[str],
    max_tickers: int | None,
    status: str,
    config_path: Path,
    market_date: str,
) -> list[str]:
    if status in {
        "SKIPPED",
        "DISABLED",
        "WAITING",
        "DEFERRED",
        "BLOCKED",
        "READY",
        "READY_FROM_RAW",
        "RUNNING",
    }:
        return []
    profile = str(row.get("command_profile") or "")
    if profile in {"stock_trades_live", "stock_trades_premarket"}:
        return _stock_trade_live_command(
            row,
            tickers=tickers,
            max_tickers=max_tickers,
            status=status,
        )
    if profile == "stock_trades_backfill":
        return _stock_trade_backfill_command(
            row,
            tickers=tickers,
            max_tickers=max_tickers,
            status=status,
        )
    if profile == "prices_daily":
        return _massive_grouped_daily_command(
            row,
            tickers=tickers,
            max_tickers=max_tickers,
            status=status,
        )
    if profile == "derive_block_trades_from_live_slices":
        return _derive_block_trades_command(
            row,
            tickers=tickers,
            max_tickers=max_tickers,
            status=status,
        )
    return []


def _command_ticker_count(command: Sequence[str]) -> int:
    count = sum(1 for item in command if item == "--ticker")
    if "--tickers" not in command:
        return count
    start = command.index("--tickers") + 1
    for item in command[start:]:
        if str(item).startswith("--"):
            break
        count += 1
    return count


def _unsupported_massive_api_lane_due(row: Mapping[str, object], status: str) -> bool:
    if status not in {"DUE_NOW", "RUNNING"}:
        return False
    if str(row.get("acquisition_mode") or "") != "massive_api":
        return False
    return str(row.get("command_profile") or "") not in MASSIVE_COMMAND_PROFILES_WITH_RUNNERS


def _stock_trade_live_command(
    row: Mapping[str, object],
    *,
    tickers: Sequence[str],
    max_tickers: int | None,
    status: str,
) -> list[str]:
    if status not in {"DUE_NOW", "RUNNING"}:
        return []
    start = _row_date_text(row.get("start"))
    end = _row_date_text(row.get("end")) or start
    if not start or not end:
        return []
    limit = max_tickers if max_tickers is not None and max_tickers > 0 else len(tickers)
    lane_id = str(row.get("lane_id") or "massive_live_trade_slices")
    command = [
        ".\\.venv\\Scripts\\python",
        "research\\scripts\\pull_massive_stock_trades.py",
        "--start",
        start,
        "--end",
        end,
        "--order",
        "desc",
        "--limit",
        str(MASSIVE_LIVE_SLICE_ROW_LIMIT),
        "--max-pages-per-day",
        "1",
        "--lane-id",
        lane_id,
        "--progress-path",
        _display_repo_path(
            REPO_ROOT / "research" / "results" / "latest-data-refresh" / f"{lane_id}-progress.json"
        ),
    ]
    if str(row.get("command_profile") or "") == "stock_trades_premarket":
        command.extend(["--trade-session", "pre_market"])
    manifest_path = str(row.get("storage_manifest") or "")
    if manifest_path:
        command.extend(["--lane-manifest-path", manifest_path])
    for ticker in list(tickers)[:limit]:
        command.extend(["--ticker", ticker])
    return command


def _massive_grouped_daily_command(
    row: Mapping[str, object],
    *,
    tickers: Sequence[str],
    max_tickers: int | None,
    status: str,
) -> list[str]:
    if status not in {"DUE_NOW", "RUNNING"}:
        return []
    date_text = _row_date_text(row.get("end")) or _row_date_text(row.get("start"))
    if not date_text:
        return []
    lane_id = str(row.get("lane_id") or "massive_daily_bars")
    command = [
        ".\\.venv\\Scripts\\python",
        "research\\scripts\\pull_massive_grouped_daily.py",
        "--date",
        date_text,
        "--lane-id",
        lane_id,
    ]
    manifest_path = str(row.get("storage_manifest") or "")
    if manifest_path:
        command.extend(["--lane-manifest-path", manifest_path])
    selected = list(tickers)
    if selected:
        command.append("--tickers")
        command.extend(selected)
    return command


def _derive_block_trades_command(
    row: Mapping[str, object],
    *,
    tickers: Sequence[str],
    max_tickers: int | None,
    status: str,
) -> list[str]:
    if status not in {"DUE_NOW", "RUNNING"}:
        return []
    start = _row_date_text(row.get("start"))
    end = _row_date_text(row.get("end")) or start
    if not start or not end:
        return []
    limit = max_tickers if max_tickers is not None and max_tickers > 0 else len(tickers)
    lane_id = str(row.get("lane_id") or "massive_block_trade_feed")
    source_manifest = _local_derivation_source_manifest_path(row, "massive_live_trade_slices")
    command = [
        ".\\.venv\\Scripts\\python",
        "research\\scripts\\derive_massive_block_trade_feed.py",
        "--start",
        start,
        "--end",
        end,
        "--lane-id",
        lane_id,
        "--progress-path",
        _display_repo_path(
            REPO_ROOT / "research" / "results" / "latest-data-refresh" / f"{lane_id}-progress.json"
        ),
        "--source-lane-manifest",
        _display_repo_path(source_manifest),
    ]
    manifest_path = str(row.get("storage_manifest") or "")
    if manifest_path:
        command.extend(["--lane-manifest-path", manifest_path])
    for ticker in list(tickers)[:limit]:
        command.extend(["--ticker", ticker])
    return command


def _local_derivation_source_manifest_path(row: Mapping[str, object], lane_id: str) -> Path:
    explicit_paths = _mapping(row.get("source_lane_manifests") or row.get("raw_lane_manifests"))
    explicit_path = explicit_paths.get(lane_id)
    if isinstance(explicit_path, str) and explicit_path.strip():
        return Path(explicit_path)
    return manifest_path_for_lane(REPO_ROOT, lane_id)


def _stock_trade_backfill_command(
    row: Mapping[str, object],
    *,
    tickers: Sequence[str],
    max_tickers: int | None,
    status: str,
) -> list[str]:
    if status not in {"DUE_NOW", "RUNNING"}:
        return []
    start = _row_date_text(row.get("start"))
    end = _row_date_text(row.get("end")) or start
    if not start or not end:
        return []
    limit = max_tickers if max_tickers is not None and max_tickers > 0 else len(tickers)
    command = [
        ".\\.venv\\Scripts\\python",
        "research\\scripts\\backfill_massive_stock_trades.py",
        "--start",
        start,
        "--end",
        end,
        "--batch-size",
        "1",
        "--recent-first",
        "--max-batches",
        str(max(limit, 1)),
    ]
    lane_id = str(row.get("lane_id") or "massive_backtest_trade_tape")
    command.extend(["--lane-id", lane_id])
    manifest_path = str(row.get("storage_manifest") or "")
    if manifest_path:
        command.extend(["--lane-manifest-path", manifest_path])
    for ticker in list(tickers)[:limit]:
        command.extend(["--ticker", ticker])
    return command


def _massive_lane_source(dataset: str) -> str:
    if dataset == "prices_daily":
        return "daily-market-bars"
    if dataset == "stock_trades":
        return "massive-stock-trades"
    if dataset == "options_chains":
        return "massive-options-flow"
    if dataset == "reference_data":
        return "massive-reference"
    return dataset


def _massive_lane_health(
    source_name: str,
    source: Mapping[str, object],
    *,
    row: Mapping[str, object],
    manifest: Mapping[str, object],
    now: datetime,
) -> dict[str, str]:
    manifest_health = _massive_manifest_health(row, manifest, now=now)
    if manifest_health:
        return manifest_health
    if not source:
        return {
            "status": "UNAVAILABLE",
            "freshness": "UNAVAILABLE",
            "status_class": "block",
            "checked_at": "not checked",
            "detail": f"{source_name} has no live source-health row.",
        }
    status = str(source.get("status") or "UNKNOWN")
    freshness = str(source.get("freshness") or "UNKNOWN")
    status_class = str(source.get("status_class") or "")
    if not status_class:
        status_class = _massive_source_status_class(status, freshness)
    return {
        "status": status,
        "freshness": freshness,
        "status_class": status_class,
        "checked_at": str(source.get("checked_at") or "not checked"),
        "detail": str(source.get("detail") or f"{source_name} reports {freshness}."),
    }


def _massive_manifest_health(
    row: Mapping[str, object],
    manifest: Mapping[str, object],
    *,
    now: datetime,
) -> dict[str, str] | None:
    lane_id = str(row.get("lane_id") or "unknown")
    blocks_execution = row.get("blocks_execution") is True
    if not manifest:
        return {
            "status": "UNAVAILABLE",
            "freshness": "UNAVAILABLE",
            "status_class": "block" if blocks_execution else "warn",
            "checked_at": "not checked",
            "detail": (
                f"{lane_id} lane manifest is missing; generic source-health "
                "cannot prove lane-level readiness."
            ),
        }
    raw_status = str(manifest.get("status") or "UNKNOWN").upper()
    effective_status = _lane_manifest_effective_status(manifest).upper()
    status = effective_status or raw_status
    fetched_at = _parse_datetime(manifest.get("fetched_at"))
    checked_at = "not checked" if fetched_at is None else fetched_at.isoformat()
    age_seconds = None if fetched_at is None else int((now - fetched_at).total_seconds())
    required_seconds = _int_or_none(row.get("freshness_requirement_seconds"))
    coverage_pct = _int_value(manifest.get("coverage_pct"), 0)
    issue_count = _int_value(manifest.get("issue_count"), 0)
    if required_seconds is not None and age_seconds is None:
        return {
            "status": "STALE",
            "freshness": "UNKNOWN",
            "status_class": "block" if blocks_execution else "warn",
            "checked_at": checked_at,
            "detail": (
                f"{lane_id} lane manifest has no valid fetched_at timestamp; "
                "freshness cannot be trusted."
            ),
        }
    if status == "COMPLETE" and (
        required_seconds is None or (age_seconds is not None and age_seconds <= required_seconds)
    ):
        freshness = "FRESH" if required_seconds is not None else "CURRENT"
        return {
            "status": "HEALTHY",
            "freshness": freshness,
            "status_class": "pass",
            "checked_at": checked_at,
            "detail": (
                f"{lane_id} lane manifest is {status.lower()} with {coverage_pct}% coverage."
            ),
        }
    if (
        required_seconds is not None
        and age_seconds is not None
        and age_seconds > required_seconds
        and not _closed_market_lane_manifest_current(row, manifest, now=now)
    ):
        return {
            "status": "STALE",
            "freshness": "STALE",
            "status_class": "block" if blocks_execution else "warn",
            "checked_at": checked_at,
            "detail": (
                f"{lane_id} lane manifest is {age_seconds}s old, beyond the "
                f"{required_seconds}s freshness SLA."
            ),
        }
    if status in {"FAILED", "BLOCKED"}:
        return {
            "status": status,
            "freshness": "UNAVAILABLE",
            "status_class": "block" if blocks_execution else "warn",
            "checked_at": checked_at,
            "detail": (
                f"{lane_id} lane manifest reports {status.lower()} with {issue_count} issue(s)."
            ),
        }
    if status == "PARTIAL_USABLE" and _live_lane_manifest_full_usable(row, manifest):
        freshness = "FRESH" if required_seconds is not None else "CURRENT"
        return {
            "status": "PARTIAL_USABLE",
            "freshness": freshness,
            "status_class": "pass",
            "checked_at": checked_at,
            "detail": (
                f"{lane_id} lane manifest has {coverage_pct}% usable live coverage. "
                "Live signal lanes may proceed; full-depth historical repair remains "
                "assigned to massive_backtest_trade_tape."
            ),
        }
    return {
        "status": status,
        "freshness": "PARTIAL" if status in {"PARTIAL", "PARTIAL_USABLE"} else "UNKNOWN",
        "status_class": "warn",
        "checked_at": checked_at,
        "detail": (
            f"{lane_id} lane manifest is {status.lower()} with {coverage_pct}% "
            "coverage; downstream signals should wait or treat it as partial."
        ),
    }


def _live_lane_manifest_full_usable(
    row: Mapping[str, object],
    manifest: Mapping[str, object],
) -> bool:
    if str(row.get("command_profile") or "") not in {
        "stock_trades_live",
        "stock_trades_premarket",
    }:
        return False
    usable_pct = _int_value(
        manifest.get("usable_coverage_pct"),
        _int_value(manifest.get("coverage_pct"), 0),
    )
    return usable_pct >= 100


def _closed_market_lane_manifest_current(
    row: Mapping[str, object],
    manifest: Mapping[str, object],
    *,
    now: datetime,
) -> bool:
    if str(row.get("raw_source_dataset") or row.get("dataset") or "") not in {
        "stock_trades",
        "prices_daily",
        "options_chains",
    }:
        return False
    try:
        from data_refresh.market_calendar import (
            classify_market_session,
            previous_trading_day,
        )
    except ModuleNotFoundError:
        return False
    session = classify_market_session(now)
    if session.is_open_for_extended:
        return False
    if session.is_trading_day:
        latest_completed = (
            previous_trading_day(session.market_date)
            if session.phase in {"overnight_before_pre_market", "pre_market", "regular_market"}
            else session.market_date
        )
    else:
        latest_completed = previous_trading_day(session.market_date)
    manifest_date = _manifest_window_end_date(manifest) or _manifest_fetched_date(manifest)
    return manifest_date is not None and manifest_date >= latest_completed


def _manifest_window_end_date(manifest: Mapping[str, object]) -> date | None:
    window = _mapping(manifest.get("window"))
    value = window.get("end")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _manifest_fetched_date(manifest: Mapping[str, object]) -> date | None:
    fetched_at = _parse_datetime(manifest.get("fetched_at"))
    return None if fetched_at is None else fetched_at.date()


def _massive_source_status_class(status: str, freshness: str) -> str:
    tokens = {status.upper(), freshness.upper()}
    if tokens.intersection({"UNAVAILABLE", "STALE", "RATE_LIMITED", "BLOCK"}):
        return "block"
    if tokens.intersection({"DEGRADED", "AGING", "UNKNOWN", "WARN"}):
        return "warn"
    return "pass"


def _massive_lane_eta_seconds(
    row: Mapping[str, object],
    ticker_count: int,
    status: str,
) -> int:
    if status in {
        "SKIPPED",
        "DISABLED",
        "DEFERRED",
        "BLOCKED",
        "WAITING",
        "READY",
        "READY_FROM_RAW",
    }:
        return 0
    profile = str(row.get("command_profile") or "")
    per_ticker = 25 if profile == "stock_trades_backfill" else 9
    if str(row.get("dataset") or "") == "prices_daily":
        return 30
    return min(20 + per_ticker * max(ticker_count, 1), 45 * 60)


def _freshness_requirement_label(value: object) -> str:
    seconds = _int_or_none(value)
    if seconds is None or seconds <= 0:
        return "research/off-hours"
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds}s"
    if seconds < 60 * SECONDS_PER_MINUTE:
        return f"{round(seconds / SECONDS_PER_MINUTE)}m"
    return f"{round(seconds / (60 * SECONDS_PER_MINUTE))}h"


def _massive_orchestrator_state(counts: Mapping[str, int]) -> str:
    if counts.get("blocked", 0) or counts.get("health_blocked", 0):
        return "blocked"
    if counts.get("running", 0):
        return "running"
    if counts.get("due_now", 0):
        return "due_now"
    if counts.get("deferred", 0):
        return "scheduled"
    if counts.get("ready_from_raw", 0):
        return "fresh"
    if counts.get("skipped", 0):
        return "fresh"
    return "idle"


def _massive_orchestrator_status_label(state: str) -> str:
    return {
        "blocked": "Blocked",
        "running": "Running",
        "due_now": "Due Now",
        "scheduled": "Scheduled",
        "fresh": "Fresh",
        "idle": "Idle",
    }.get(state, state.replace("_", " ").title())


def _massive_orchestrator_status_class(state: str) -> str:
    if state == "blocked":
        return "block"
    if state in {"running", "due_now", "scheduled"}:
        return "warn"
    if state == "fresh":
        return "pass"
    return "neutral"


def _massive_orchestrator_detail(
    counts: Mapping[str, int],
    lanes: Sequence[Mapping[str, object]],
) -> str:
    if counts.get("blocked", 0):
        return f"{counts['blocked']} Massive lane(s) are blocked before data can be pulled."
    if counts.get("health_blocked", 0):
        return (
            f"{counts['health_blocked']} Massive lane(s) lack fresh source-health. "
            "Treat order submission as gated until health is verified."
        )
    if counts.get("running", 0):
        return f"{counts['running']} Massive lane(s) are actively refreshing."
    if counts.get("due_now", 0):
        due = [
            str(row.get("label") or row.get("lane_id"))
            for row in lanes
            if row.get("status") == "DUE_NOW"
        ]
        return f"Run due Massive raw acquisition lane(s): {', '.join(due[:3])}."
    if counts.get("ready_from_raw", 0):
        return "Local derived Massive lanes are ready to read current raw slices without extra API calls."
    return "Massive data-source lanes are either fresh, deferred to their proper window, or disabled."


def _queue_summary(
    jobs: Sequence[Mapping[str, object]],
    stale: Sequence[Mapping[str, object]],
    repair: Mapping[str, object],
    tradability: Mapping[str, object],
    massive_orchestrator: Mapping[str, object],
) -> dict[str, object]:
    counts = {
        "running": _count_status(jobs, "RUNNING"),
        "due_now": _count_status(jobs, "DUE_NOW"),
        "waiting": _count_status(jobs, "WAITING"),
        "deferred": _count_status(jobs, "DEFERRED"),
        "skipped": _count_status(jobs, "SKIPPED"),
        "blocked": _count_status(jobs, "BLOCKED"),
    }
    return {
        "job_count": len(jobs),
        "counts": counts,
        "stale_dataset_count": len(stale),
        "repair_job_count": _int_value(repair.get("job_count"), 0),
        "massive_lane_count": _int_value(massive_orchestrator.get("lane_count"), 0),
        "massive_due_lane_count": _int_value(massive_orchestrator.get("due_now_count"), 0),
        "massive_blocked_lane_count": _int_value(
            massive_orchestrator.get("blocked_count"),
            0,
        ),
        "tradability_state": str(tradability["state"]),
        "headline": _queue_headline(counts, tradability),
    }


def _job_status(
    *,
    name: str,
    batch_action: str,
    extraction_action: str,
    progress: Mapping[str, object],
) -> str:
    if progress.get("state") == "running" and str(progress.get("current_dataset")) in {
        name,
        name.replace("_", "-"),
    }:
        return "RUNNING"
    if batch_action == "disabled":
        return "DISABLED"
    if extraction_action == "skip" or batch_action == "skip":
        return "SKIPPED"
    if batch_action == "defer":
        return "DEFERRED"
    if batch_action == "run_now":
        return "DUE_NOW"
    return "WAITING"


def _apply_cadence_gate(
    status: str,
    reason: str,
    *,
    job_id: str,
    cadence_minutes: int | None,
    scheduler_runtime: Mapping[str, object],
    now: datetime,
) -> tuple[str, str]:
    if status != "DUE_NOW" or cadence_minutes is None or cadence_minutes <= 0:
        return status, reason
    last_success = _last_job_success_at(scheduler_runtime, job_id)
    if last_success is None:
        return status, reason
    due_at = last_success + timedelta(minutes=cadence_minutes)
    if now >= due_at:
        return status, reason
    remaining = max(0, int((due_at - now).total_seconds()))
    return (
        "WAITING",
        (
            f"{reason} Last successful run was {_age_label(int((now - last_success).total_seconds()))} "
            f"ago; next due in {_eta_label(remaining)}."
        ),
    )


def _last_job_success_at(
    scheduler_runtime: Mapping[str, object],
    job_id: str,
) -> datetime | None:
    successes = scheduler_runtime.get("job_last_success_at")
    if isinstance(successes, Mapping):
        parsed = _parse_datetime(successes.get(job_id))
        if parsed is not None:
            return parsed
    for command in _sequence_mappings(scheduler_runtime.get("last_tick_commands")):
        if str(command.get("job_id") or "") != job_id:
            continue
        if _int_value(command.get("exit_code"), -1) != 0:
            continue
        fallback = (
            _parse_datetime(command.get("finished_at"))
            or _parse_datetime(scheduler_runtime.get("last_tick_finished_at"))
            or _parse_datetime(scheduler_runtime.get("generated_at"))
        )
        if fallback is not None:
            return fallback
    return None


def _age_label(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    return f"{hours}h"


def _dataset_ticker_tier(dataset: str, phase: str) -> str:
    if dataset == "stock_trades" and phase in ACTIVE_MARKET_PHASES:
        return "T0/T1/T2"
    if dataset in {"news_rss", "subscription_emails"}:
        return "T0/T1"
    if dataset in {"sec_form4", "prices_daily"}:
        return "T0/T1/T2"
    if dataset in {"sec_company_facts", "sec_13f"}:
        return "T3"
    return "T2"


def _tier_tickers(tiers: TickerTiers, tier: str) -> list[str]:
    if tier == "T0/T1/T2/T3":
        return [*tiers.t0, *tiers.t1, *tiers.t2, *tiers.t3]
    if tier == "T0/T1/T2":
        return [*tiers.t0, *tiers.t1, *tiers.t2]
    if tier == "T0/T1":
        return [*tiers.t0, *tiers.t1]
    if tier == "T0":
        return list(tiers.t0)
    if tier == "T1":
        return list(tiers.t1)
    if tier == "T2":
        return list(tiers.t2)
    if tier == "T3":
        return list(tiers.t3)
    return []


def _dataset_job_tickers(
    row: Mapping[str, object],
    *,
    tiers: TickerTiers,
    ticker_tier: str,
) -> list[str]:
    row_tickers = _row_tickers(row)
    tier_tickers = _tier_tickers(tiers, ticker_tier)
    if not row_tickers:
        return tier_tickers
    if not tier_tickers:
        return row_tickers
    row_set = set(row_tickers)
    prioritized = [ticker for ticker in tier_tickers if ticker in row_set]
    if ticker_tier == "T0/T1" and prioritized:
        return prioritized
    prioritized_set = set(prioritized)
    remaining = [ticker for ticker in row_tickers if ticker not in prioritized_set]
    return [*prioritized, *remaining]


def _is_repair_dataset_row(row: Mapping[str, object]) -> bool:
    action = str(row.get("extraction_action") or "")
    if action in {"baseline", "force"}:
        return True
    if str(row.get("dataset")) != "stock_trades":
        return False
    reason = (f"{row.get('extraction_reason') or ''} {row.get('reason') or ''}").lower()
    return any(token in reason for token in ("partial", "failed", "missing"))


def _ticker_tier_for_ticker(ticker: str, tiers: TickerTiers) -> str:
    if ticker in tiers.t0:
        return "T0"
    if ticker in tiers.t1:
        return "T1"
    if ticker in tiers.t2:
        return "T2"
    if ticker in tiers.t3:
        return "T3"
    return "T1"


def _dataset_eta_seconds(dataset: str, ticker_count: int, status: str) -> int:
    if status in {"SKIPPED", "DISABLED"}:
        return 0
    per_ticker = {
        "stock_trades": 9,
        "prices_daily": 2,
        "sec_form4": 4,
        "sec_company_facts": 7,
        "sec_13f": 1,
        "news_rss": 45,
        "subscription_emails": 60,
    }.get(dataset, 4)
    base = 20 if dataset not in {"news_rss", "subscription_emails"} else 0
    count = max(ticker_count, 1)
    return min(base + per_ticker * count, 45 * 60)


def _dataset_command(
    dataset: str,
    *,
    row: Mapping[str, object],
    tickers: Sequence[str],
    max_tickers: int | None,
    status: str,
    config_path: Path,
    market_date: str,
) -> list[str]:
    if status in {"SKIPPED", "DISABLED", "WAITING", "DEFERRED", "BLOCKED"}:
        return []
    if dataset == "stock_trades":
        return []
    command = [
        ".\\.venv\\Scripts\\python",
        "research\\scripts\\run_data_refresh_batch.py",
        "--config",
        _display_repo_path(config_path),
        "--dataset",
        dataset,
        "--no-market-aware",
        "--extraction-mode",
        _extraction_mode(row),
    ]
    _extend_command_window(command, dataset, row=row, market_date=market_date)
    if dataset in {"news_rss", "subscription_emails", "sec_13f"}:
        return command
    limit = max_tickers if max_tickers is not None and max_tickers > 0 else len(tickers)
    for ticker in list(tickers)[:limit]:
        command.extend(["--ticker", ticker])
    return command


def _repair_command(
    row: Mapping[str, object],
    *,
    tickers: Sequence[str],
    config_path: Path,
    status: str,
) -> list[str]:
    if status != "DUE_NOW":
        return []
    dataset = str(row.get("dataset", "unknown"))
    if dataset == "stock_trades":
        return _stock_trade_backfill_command(
            row,
            tickers=tickers,
            max_tickers=len(tickers),
            status=status,
        )
    command = [
        ".\\.venv\\Scripts\\python",
        "research\\scripts\\run_data_refresh_batch.py",
        "--config",
        _display_repo_path(config_path),
        "--dataset",
        dataset,
        "--no-market-aware",
        "--extraction-mode",
        str(row.get("extraction_action") or "baseline"),
    ]
    _extend_command_window(command, dataset, row=row, market_date="")
    for ticker in tickers:
        command.extend(["--ticker", ticker])
    return command


def _extend_command_window(
    command: list[str],
    dataset: str,
    *,
    row: Mapping[str, object],
    market_date: str,
) -> None:
    start = _row_date_text(row.get("start")) or market_date
    end = _row_date_text(row.get("end")) or start
    if not start or not end:
        return
    if dataset == "stock_trades":
        command.extend(["--stock-trades-start", start, "--stock-trades-end", end])
        return
    if dataset in {"prices_daily", "sec_form4", "sec_company_facts"}:
        command.extend(["--start", start, "--end", end])


def _extraction_mode(row: Mapping[str, object]) -> str:
    value = str(row.get("extraction_action") or "incremental")
    if value in {"baseline", "incremental", "force"}:
        return value
    return "incremental"


def _signal_command(
    lane: str,
    *,
    tickers: Sequence[str],
    status: str,
    config_path: Path,
) -> list[str]:
    if status in {"SKIPPED", "DISABLED", "WAITING", "BLOCKED"}:
        return []
    lane_slug = _slug(lane)
    command = [
        ".\\.venv\\Scripts\\python",
        "scripts\\run_live_runtime_cycle.py",
        "--config",
        _display_repo_path(config_path),
        "--signal",
        lane,
        "--audit-trigger",
        "SCHEDULED",
        "--cycle-id",
        f"partial-signal-{lane_slug}",
        "--no-persist",
        "--output-root",
        _display_repo_path(PARTIAL_RUNTIME_OUTPUT_ROOT / lane_slug),
    ]
    for ticker in tickers:
        command.extend(["--ticker", ticker])
    return command


def _dataset_requires_tickers(dataset: str) -> bool:
    return dataset not in {"news_rss", "subscription_emails", "sec_13f"}


def _slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value.strip())
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "unknown"


def _signal_eta_seconds(lane: str, ticker_count: int, status: str) -> int:
    if status in {"SKIPPED", "DISABLED"}:
        return 0
    heavy_lanes = {"technical_analysis", "market_flow_trend", "buy_sell_pressure"}
    per_ticker = 4 if lane in heavy_lanes else 2
    return min(20 + per_ticker * max(ticker_count, 1), 20 * 60)


def _eta_label(seconds: int) -> str:
    if seconds <= 0:
        return "complete"
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds}s"
    minutes = round(seconds / SECONDS_PER_MINUTE)
    return f"{minutes}m"


def _stale_dataset_rows(
    data_load_status: Mapping[str, object],
    source_health: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in _sequence_mappings(data_load_status.get("lane_states")):
        if row.get("blocker") is not True:
            continue
        lane_id = str(row.get("lane_id") or "unknown")
        label = str(row.get("label") or lane_id.replace("_", " ").title())
        reason = str(
            row.get("operator_message")
            or row.get("recommended_action")
            or "Lane needs attention before paper execution."
        )
        rows.append(
            {
                "kind": "lane_state",
                "dataset": lane_id,
                "status": str(row.get("status_label") or row.get("state") or "ATTENTION"),
                "status_class": str(row.get("status_class") or "block"),
                "reason": f"{label}: {reason}",
                "blocks_execution": row.get("blocks_execution") is True,
            }
        )
    for row in _sequence_mappings(data_load_status.get("datasets")):
        status = str(row.get("status", ""))
        if status in {"blocked", "warning"}:
            rows.append(
                {
                    "dataset": str(row.get("dataset", "unknown")),
                    "status": status.upper(),
                    "status_class": _status_class(status),
                    "reason": str(row.get("detail", "Dataset needs scheduler attention.")),
                }
            )
    known = {str(item["dataset"]) for item in rows}
    for row in source_health:
        source = str(row.get("source", ""))
        freshness = str(row.get("freshness", ""))
        status = str(row.get("status", ""))
        dataset = _source_to_dataset(source)
        blocked_state = next(
            (
                token
                for token in (freshness, status)
                if token in {"STALE", "UNAVAILABLE", "RATE_LIMITED"}
            ),
            "",
        )
        if dataset and dataset not in known and blocked_state:
            status_class = "warn" if blocked_state == "STALE" else "block"
            rows.append(
                {
                    "dataset": dataset,
                    "status": blocked_state,
                    "status_class": status_class,
                    "reason": (
                        f"{source} reports freshness {freshness or 'UNKNOWN'} "
                        f"and status {status or 'UNKNOWN'}."
                    ),
                }
            )
    return rows


def _execution_blocking_lane_state_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    return [
        row
        for row in rows
        if row.get("kind") == "lane_state" and row.get("blocks_execution") is True
    ]


def _source_to_dataset(source: str) -> str | None:
    mapping = {
        "daily-market-bars": "prices_daily",
        "massive-stock-trades": "stock_trades",
        "sec-company-facts": "sec_company_facts",
        "sec-form4": "sec_form4",
        "sec-13f": "sec_13f",
        "rss-news": "news_rss",
        "subscription-email-thesis": "subscription_emails",
    }
    return mapping.get(source)


def _massive_dataset_owner(
    dataset: str,
    massive_orchestrator: Mapping[str, object],
) -> str:
    for row in _mapping_rows(massive_orchestrator, "lanes"):
        raw_dataset = str(row.get("raw_source_dataset") or row.get("dataset") or "")
        if raw_dataset != dataset:
            continue
        if row.get("creates_massive_request") is not True:
            continue
        status = str(row.get("status") or "")
        if status in {"DISABLED"}:
            continue
        lane_id = str(row.get("lane_id") or row.get("name") or "")
        if lane_id:
            return lane_id
    return ""


def _resolved_source_health(
    source_health: Sequence[Mapping[str, object]],
    data_load_status: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    rows = [dict(row) for row in source_health]
    known = {str(row.get("source")) for row in rows}
    for row in _sequence_mappings(data_load_status.get("freshness_rows")):
        source = str(row.get("source") or "")
        if source and source not in known:
            rows.append(dict(row))
            known.add(source)
    return tuple(rows)


def _load_overrides(path: Path) -> RefreshConfigOverrides:
    try:
        return load_refresh_config(path, repo_root=REPO_ROOT)
    except OSError, ValueError, TypeError, json.JSONDecodeError:
        return RefreshConfigOverrides()


def _batch_config(overrides: RefreshConfigOverrides) -> RefreshBatchConfig:
    load_dotenv(REPO_ROOT / ".env")
    end = overrides.end or date.today()
    return RefreshBatchConfig(
        repo_root=REPO_ROOT,
        output_root=REPO_ROOT / "research" / "results" / "latest-data-refresh",
        start=overrides.start or date(2021, 1, 1),
        end=end,
        datasets=overrides.datasets or DATASETS,
        tickers=overrides.tickers,
        rss_feeds=overrides.rss_feeds,
        filer_ciks=overrides.filer_ciks,
        cusip_map=overrides.cusip_map,
        activity_alerts_csv=overrides.activity_alerts_csv,
        subscription_email_config=overrides.subscription_email_config,
        sec_user_agent=overrides.sec_user_agent or os.environ.get("SEC_USER_AGENT"),
        workers=overrides.workers or 1,
        include_etfs=True if overrides.include_etfs is None else overrides.include_etfs,
        refresh=False if overrides.refresh is None else overrides.refresh,
        dry_run=False if overrides.dry_run is None else overrides.dry_run,
        market_data_provider=overrides.market_data_provider or "massive",
        market_data_feed=overrides.market_data_feed or os.environ.get("ALPACA_DATA_FEED", "iex"),
        market_data_adjustment=overrides.market_data_adjustment
        or os.environ.get("ALPACA_DATA_ADJUSTMENT", "all"),
        market_data_base_url=overrides.market_data_base_url
        or os.environ.get("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets"),
        market_data_credentials_present=_alpaca_credentials_present(),
        massive_base_url=overrides.massive_base_url
        or os.environ.get("MASSIVE_BASE_URL", "https://api.polygon.io"),
        massive_credentials_present=_massive_credentials_present(),
        stock_trades_start=overrides.stock_trades_start or end,
        stock_trades_end=overrides.stock_trades_end or end,
        stock_trades_limit=overrides.stock_trades_limit or 50_000,
        stock_trades_max_pages_per_day=overrides.stock_trades_max_pages_per_day,
        stock_trades_order=overrides.stock_trades_order or "desc",
        extraction_mode=overrides.extraction_mode or "auto",
        sec_company_facts_max_age_days=overrides.sec_company_facts_max_age_days or 7,
        sec_form4_max_age_days=overrides.sec_form4_max_age_days or 1,
        sec_13f_max_age_days=overrides.sec_13f_max_age_days or 45,
        news_rss_max_age_minutes=overrides.news_rss_max_age_minutes or 30,
        subscription_email_max_age_minutes=overrides.subscription_email_max_age_minutes or 10,
        python_executable=".\\.venv\\Scripts\\python",
    )


def _configured_or_active_tickers(
    overrides: RefreshConfigOverrides,
    as_of: date,
) -> tuple[str, ...]:
    if overrides.tickers:
        return tuple(_sorted_tickers(set(overrides.tickers)))
    return tuple(_active_universe_tickers(as_of, DEFAULT_UNIVERSE_PATH))


def _research_tickers(config: RefreshBatchConfig) -> tuple[str, ...]:
    tickers = set(config.tickers) | set(_manifest_tickers())
    if not tickers:
        tickers = set(_active_universe_tickers(config.end, DEFAULT_UNIVERSE_PATH))
    return tuple(_sorted_tickers(tickers))


def _active_universe_tickers(as_of: date, path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        frame = pd.read_parquet(path, columns=["ticker", "start_date", "end_date"])
    except OSError, ValueError, KeyError:
        return []
    if frame.empty:
        return []
    start = pd.to_datetime(frame["start_date"], errors="coerce")
    end = pd.to_datetime(frame["end_date"], errors="coerce")
    current = pd.Timestamp(as_of)
    active = frame[(start <= current) & (end.isna() | (end > current))]
    return _sorted_tickers({str(ticker) for ticker in active["ticker"].dropna().unique()})


def _manifest_tickers() -> set[str]:
    root = REPO_ROOT / "research" / "data" / "manifests"
    tickers: set[str] = set()
    for path in root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        if not isinstance(payload, Mapping):
            continue
        values = payload.get("tickers")
        if isinstance(values, list):
            tickers.update(str(value).upper() for value in values if str(value).strip())
    return tickers


def _runtime_lanes_from_config(path: Path) -> tuple[str, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return ()
    if not isinstance(payload, Mapping):
        return ()
    values = payload.get("runtime_signals")
    if not isinstance(values, list):
        return ()
    return tuple(str(value) for value in values if str(value).strip())


def _event_rows(
    events: Sequence[Mapping[str, object]],
    *,
    max_events: int,
) -> list[Mapping[str, object]]:
    seen: set[tuple[str, str]] = set()
    rows: list[Mapping[str, object]] = []
    for event in events:
        ticker = _ticker(event)
        if not ticker:
            continue
        event_type = str(event.get("event_type") or event.get("source") or "unknown")
        key = (ticker, event_type)
        if key in seen:
            continue
        seen.add(key)
        rows.append(event)
        if len(rows) >= max_events:
            break
    return rows


def _mapping_rows(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    return _sequence_mappings(payload.get(key))


def _sequence_mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, list) else []


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def _broker_positions(broker: Mapping[str, object] | None) -> list[Mapping[str, object]]:
    if broker is None:
        return []
    return _sequence_mappings(broker.get("positions"))


def _broker_orders(broker: Mapping[str, object] | None) -> list[Mapping[str, object]]:
    if broker is None:
        return []
    return _sequence_mappings(broker.get("orders"))


def _mapping_tickers(rows: Sequence[Mapping[str, object]]) -> set[str]:
    return {_ticker(row) for row in rows if _ticker(row)}


def _ordered_mapping_tickers(rows: Sequence[Mapping[str, object]]) -> list[str]:
    return [_ticker(row) for row in rows if _ticker(row)]


def _string_tickers(values: Sequence[str]) -> set[str]:
    return {str(value).upper().strip() for value in values if str(value).strip()}


def _ordered_string_tickers(values: Sequence[str]) -> list[str]:
    return [str(value).upper().strip() for value in values if str(value).strip()]


def _row_tickers(row: Mapping[str, object]) -> list[str]:
    values = row.get("tickers")
    if not isinstance(values, list):
        return []
    return _sorted_tickers([str(value) for value in values if str(value).strip()])


def _sorted_tickers(values: set[str] | Sequence[str]) -> list[str]:
    return sorted({str(value).upper().strip() for value in values if str(value).strip()})


def _ticker(row: Mapping[str, object]) -> str:
    for key in ("ticker", "symbol", "underlying"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return ""


def _ordered_unique_tickers(
    values: Sequence[str],
    *,
    exclude: set[str] | None = None,
) -> list[str]:
    skipped = set() if exclude is None else {item.upper() for item in exclude}
    seen: set[str] = set()
    tickers: list[str] = []
    for value in values:
        ticker = str(value).upper().strip()
        if not ticker or ticker in skipped or ticker in seen:
            continue
        seen.add(ticker)
        tickers.append(ticker)
    return tickers


def _conviction_sort_key(row: Mapping[str, object]) -> tuple[float, str]:
    conviction = max(
        _number(row.get("final_conviction")),
        _number(row.get("conviction_pct")) / 100.0,
    )
    return (-conviction, _ticker(row))


def _number(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _int_value(value: object, fallback: int) -> int:
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
    return None


def _row_date_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text if text else ""


def _display_repo_path(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(REPO_ROOT.resolve(strict=False)).as_posix()
    except ValueError:
        return path.as_posix()


def _combined_reason(row: Mapping[str, object]) -> str:
    reason = str(row.get("reason", "No scheduler rationale recorded."))
    extraction = str(row.get("extraction_reason", ""))
    if extraction and extraction != reason:
        return f"{reason} Extraction: {extraction}"
    return reason


def _job_sort_key(row: Mapping[str, object]) -> tuple[int, int, str]:
    status_priority = {
        "RUNNING": 0,
        "DUE_NOW": 1,
        "WAITING": 2,
        "DEFERRED": 3,
        "BLOCKED": 4,
        "SKIPPED": 5,
        "READY": 6,
        "READY_FROM_RAW": 6,
        "DISABLED": 7,
    }.get(str(row.get("status")), 8)
    return (status_priority, -_int_value(row.get("priority"), 0), str(row.get("name", "")))


def _count_status(rows: Sequence[Mapping[str, object]], status: str) -> int:
    return sum(1 for row in rows if row.get("status") == status)


def _job_status_class(status: str) -> str:
    if status in {"RUNNING", "DUE_NOW"}:
        return "warn"
    if status in {"READY", "READY_FROM_RAW"}:
        return "pass"
    if status in {"WAITING", "SKIPPED", "DISABLED"}:
        return "neutral"
    if status == "DEFERRED":
        return "warn"
    return "block"


def _status_class(state: str) -> str:
    if state in {"pass", "ready"}:
        return "pass"
    if state in {"warning", "warn", "loading", "deferred", "blocked"}:
        return "warn" if state != "blocked" else "block"
    return "neutral"


def _queue_headline(
    counts: Mapping[str, int],
    tradability: Mapping[str, object],
) -> str:
    if str(tradability["state"]) != "tradable":
        return f"Scheduler is context-only: {tradability['detail']}"
    due = counts.get("due_now", 0)
    if due:
        return f"{due} market-aware job(s) should run before the next paper order."
    return "Scheduler queue is clear enough for paper trading."


def _repair_detail(rows: Sequence[Mapping[str, object]], *, is_off_hours: bool) -> str:
    if not rows:
        return "No baseline repair jobs are due."
    if is_off_hours:
        return "Quiet-market window is suitable for missing coverage repair."
    return "Baseline repair is queued for off-hours so live decisions keep capacity."


def _mini_cycle_detail(affected: Sequence[str]) -> str:
    if not affected:
        return "No event-driven ticker updates are waiting."
    return f"Queued mini-cycle recompute for {len(affected)} affected ticker(s)."


def _raw_requirement_gate(
    required_lanes: Sequence[str],
    massive_orchestrator: Mapping[str, object],
) -> dict[str, str]:
    if not required_lanes:
        return {
            "state": "not_required",
            "status": "NOT_REQUIRED",
            "detail": "No Massive data-source lane requirement is declared.",
        }
    lane_index = {
        str(row.get("lane_id")): row for row in _mapping_rows(massive_orchestrator, "lanes")
    }
    missing = [lane for lane in required_lanes if lane not in lane_index]
    if missing:
        return {
            "state": "blocked",
            "status": "BLOCKED",
            "detail": (f"Missing Massive data-source lane declaration(s): {', '.join(missing)}."),
        }
    waiting = [
        lane
        for lane in required_lanes
        if not _raw_lane_requirement_satisfied(lane_index[lane])
        and str(lane_index[lane].get("status"))
        in {"DUE_NOW", "RUNNING", "DEFERRED", "WAITING", "SKIPPED"}
    ]
    if waiting:
        return {
            "state": "waiting",
            "status": "WAITING",
            "detail": (
                "Waiting for Massive data-source lane(s) before this signal reads data: "
                f"{', '.join(waiting)}."
            ),
        }
    blocked = [
        lane
        for lane in required_lanes
        if str(lane_index[lane].get("status")) in {"BLOCKED", "DISABLED"}
        or str(lane_index[lane].get("health_status_class")) == "block"
    ]
    if blocked:
        return {
            "state": "blocked",
            "status": "BLOCKED",
            "detail": (
                f"Required Massive data-source lane(s) are blocked or unverified: {', '.join(blocked)}."
            ),
        }
    return {
        "state": "ready",
        "status": "READY",
        "detail": (f"Massive data-source lane requirement is satisfied: {', '.join(required_lanes)}."),
    }


def _raw_lane_requirement_satisfied(row: Mapping[str, object]) -> bool:
    status = str(row.get("status") or "")
    if status in {"READY", "READY_FROM_RAW"}:
        return True
    if status != "SKIPPED":
        return False
    if str(row.get("batch_action") or "") == "skip":
        return True
    ticker_count = _int_value(row.get("ticker_count"), 0)
    fresh_count = _int_value(row.get("fresh_ticker_count"), 0)
    pending_count = _int_value(row.get("pending_ticker_count"), ticker_count)
    if _live_lane_row_has_full_usable_coverage(row):
        return ticker_count > 0 and fresh_count >= ticker_count and pending_count == 0
    return (
        ticker_count > 0
        and fresh_count >= ticker_count
        and pending_count == 0
        and str(row.get("health_status_class") or "") == "pass"
    )


def _live_lane_row_has_full_usable_coverage(row: Mapping[str, object]) -> bool:
    if str(row.get("command_profile") or "") not in {
        "stock_trades_live",
        "stock_trades_premarket",
    }:
        return False
    manifest_status = str(row.get("manifest_status") or "").lower()
    health_status = str(row.get("health_status") or "").lower()
    if manifest_status != "partial_usable" and health_status != "partial_usable":
        return False
    coverage_pct = _int_value(row.get("manifest_coverage_pct"), 0)
    return coverage_pct >= 100


def _mini_cycle_priority(tier: str) -> int:
    return {"T0": 110, "T1": 100, "T2": 80, "T3": 40}.get(tier, 70)


def _tier_payload(name: str, tickers: Sequence[str], detail: str) -> dict[str, object]:
    return {
        "name": name,
        "count": len(tickers),
        "sample": list(tickers[:10]),
        "detail": detail,
    }


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _alpaca_credentials_present() -> bool:
    return bool(
        os.environ.get("ALPACA_API_KEY", "").strip()
        and os.environ.get("ALPACA_SECRET_KEY", "").strip()
    )


def _massive_credentials_present() -> bool:
    return bool(
        os.environ.get("MASSIVE_API_KEY", "").strip()
        or os.environ.get("POLYGON_API_KEY", "").strip()
    )
