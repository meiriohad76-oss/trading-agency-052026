from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pandas as pd
from news.consumption import load_news_consumption_entries

from agency.runtime.data_refresh_progress import load_data_refresh_progress
from agency.runtime.live_config_readiness import load_live_config_readiness

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "research" / "config" / "live-refresh.local.json"
DEFAULT_UNIVERSE_PATH = REPO_ROOT / "research" / "data" / "parquet" / "universe_membership.parquet"
DEFAULT_MANIFEST_ROOT = REPO_ROOT / "research" / "data" / "manifests"
DEFAULT_PARQUET_ROOT = REPO_ROOT / "research" / "data" / "parquet"
DEFAULT_MASSIVE_LANE_MANIFEST_ROOT = DEFAULT_MANIFEST_ROOT / "massive_lanes"
DEFAULT_RUNTIME_SUMMARY_PATH = (
    REPO_ROOT
    / "research"
    / "results"
    / "latest-live-runtime-cycle"
    / "live-runtime-cycle-summary.json"
)
DEFAULT_SOURCE_HEALTH_PATH = (
    REPO_ROOT / "research" / "results" / "latest-live-runtime-cycle" / "source-health.json"
)
DEFAULT_NEWS_CONSUMPTION_LEDGER_PATH = (
    REPO_ROOT / "research" / "data" / "state" / "news_rss_consumed.json"
)

CORE_DATASETS = ("prices_daily", "stock_trades")
SUPPORT_DATASETS = ("sec_company_facts", "sec_form4", "sec_13f")
CONTEXT_DATASETS = ("news_rss", "subscription_emails")
CORE_REFRESH_DATASETS = {
    "prices_daily",
    "stock_trades",
    "massive_daily_bars",
    "massive_live_trade_slices",
    "massive_premarket_trade_slices",
}
NON_BLOCKING_REFRESH_DATASETS = {
    *SUPPORT_DATASETS,
    *CONTEXT_DATASETS,
    "massive_backtest_trade_tape",
    "massive_block_trade_feed",
    "massive_options_flow",
    "massive_reference",
}
DATASET_LABELS = {
    "prices_daily": "Daily OHLCV bars",
    "stock_trades": "Massive trade prints",
    "sec_company_facts": "SEC company facts",
    "sec_form4": "SEC Form 4 insider filings",
    "sec_13f": "SEC 13F holdings",
    "news_rss": "RSS/news headlines",
    "subscription_emails": "Subscription email thesis",
}
DATASET_SOURCE = {
    "prices_daily": "daily-market-bars",
    "stock_trades": "massive-stock-trades",
    "sec_company_facts": "sec-company-facts",
    "sec_form4": "sec-form4",
    "sec_13f": "sec-13f",
    "news_rss": "rss-news",
    "subscription_emails": "subscription-email-thesis",
}
CONTEXT_SOURCE_TIERS = {
    "news_rss": "RSS_HEADLINE",
    "subscription_emails": "PAID_SUB_EMAIL",
}
CRITICAL_LANES = {
    "abnormal_volume",
    "technical_analysis",
    "buy_sell_pressure",
    "block_trade_pressure",
    "unusual_trade_activity",
    "pre_market_unusual_activity",
    "market_flow_trend",
}
MARKET_FLOW_LANES = {
    "buy_sell_pressure",
    "block_trade_pressure",
    "unusual_trade_activity",
    "pre_market_unusual_activity",
    "market_flow_trend",
}
SUPPORT_LANES = {"fundamentals", "insider", "institutional"}
CONTEXT_LANES = {"news", "subscription_thesis", "sector_momentum"}
PER_TICKER_SUPPORT_LANES = {"fundamentals"}
SPARSE_SUPPORT_LANES = {"insider", "institutional"}
TOP_DOWN_CONTEXT_LANES = {"sector_momentum"}
LANE_DATASET = {
    "abnormal_volume": "prices_daily",
    "technical_analysis": "prices_daily",
    "sector_momentum": "prices_daily",
    "buy_sell_pressure": "stock_trades",
    "block_trade_pressure": "stock_trades",
    "unusual_trade_activity": "stock_trades",
    "pre_market_unusual_activity": "stock_trades",
    "market_flow_trend": "stock_trades",
    "fundamentals": "sec_company_facts",
    "insider": "sec_form4",
    "institutional": "sec_13f",
    "news": "news_rss",
    "subscription_thesis": "subscription_emails",
}
SOURCE_BLOCKING_STATUSES = {"UNAVAILABLE", "STALE", "RATE_LIMITED"}
SOURCE_WARNING_STATUSES = {"DEGRADED", "AGING", "UNKNOWN"}
CRITICAL_SOURCE_NAMES = {"daily-market-bars", "massive-stock-trades"}
TRACKED_SOURCE_NAMES = set(DATASET_SOURCE.values())
TRADE_PULL_BLOCKING_STATES = {"failed", "blocked", "stale", "unverified"}
MASSIVE_DAILY_BARS_LANE_ID = "massive_daily_bars"
MASSIVE_LIVE_TRADE_LANE_ID = "massive_live_trade_slices"
MASSIVE_PREMARKET_TRADE_LANE_ID = "massive_premarket_trade_slices"
PRE_MARKET_UNUSUAL_ACTIVITY_LANE = "pre_market_unusual_activity"
MASSIVE_DAILY_BARS_SLA_SECONDS = 24 * 60 * 60
# Dashboard/latest-slice freshness allows a bounded full-universe sweep to finish.
# Execution submission still applies a stricter just-in-time broker/evidence gate.
MASSIVE_LIVE_TRADE_SLA_SECONDS = 10 * 60
MASSIVE_LIVE_TRADE_SWEEP_GRACE_SECONDS = 2 * MASSIVE_LIVE_TRADE_SLA_SECONDS
MIN_SUPPORT_LANE_COVERAGE = 0.6
PERCENT_SCALE = 100
SOURCE_HEALTH_MAX_AGE_SECONDS = 30 * 60
HEALTH_MONITOR_MAX_AGE_SECONDS = SOURCE_HEALTH_MAX_AGE_SECONDS
SOURCE_HEALTH_MAX_AGE_BY_SOURCE = {
    "massive-stock-trades": MASSIVE_LIVE_TRADE_SLA_SECONDS,
    "sec-company-facts": 7 * 24 * 60 * 60,
    "sec-form4": 3 * 24 * 60 * 60,
    "sec-13f": 30 * 24 * 60 * 60,
    "rss-news": SOURCE_HEALTH_MAX_AGE_SECONDS,
    "subscription-email-thesis": SOURCE_HEALTH_MAX_AGE_SECONDS,
}
EASTERN = ZoneInfo("America/New_York")
WEEKEND_START = 5


def load_data_load_status(
    *,
    config_path: Path | None = None,
    universe_path: Path | None = None,
    manifest_root: Path | None = None,
    parquet_root: Path | None = None,
    runtime_summary_path: Path | None = None,
    source_health_path: Path | None = None,
    source_health_rows: Sequence[Mapping[str, object]] | None = None,
    source_health_origin: str | None = None,
    news_consumption_ledger_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    config_file = config_path or DEFAULT_CONFIG_PATH
    universe_file = universe_path or DEFAULT_UNIVERSE_PATH
    manifest_dir = manifest_root or DEFAULT_MANIFEST_ROOT
    parquet_dir = parquet_root or DEFAULT_PARQUET_ROOT
    runtime_file = runtime_summary_path or DEFAULT_RUNTIME_SUMMARY_PATH
    source_file = source_health_path or DEFAULT_SOURCE_HEALTH_PATH
    news_ledger_file = news_consumption_ledger_path or DEFAULT_NEWS_CONSUMPTION_LEDGER_PATH
    config = _read_json_object(config_file)
    config_as_of_verified = _config_date_valid(config, "end")
    configured_as_of = _config_date(config, "end", fallback=date.today())
    as_of = _effective_as_of(
        configured_as_of,
        now=now or datetime.now(UTC),
        dynamic=config_path is None,
    )
    active_tickers = _active_universe_tickers(as_of, universe_file)
    if not active_tickers:
        active_tickers = _configured_tickers(config)
    expected = len(active_tickers)
    data_refresh = load_data_refresh_progress()
    live_config = load_live_config_readiness(config_file if config_file.is_file() else None)
    runtime_summary = _read_json_object(runtime_file)
    current = now or datetime.now(UTC)
    news_manifest = _read_json_object(manifest_dir / "news_rss.json")
    news_resolved_source_ids = _news_resolved_source_ids(news_manifest, parquet_dir)
    if source_health_rows is None:
        source_health = _read_json_list(source_file)
        source_origin = (
            source_health_origin
            or (
                "latest runtime source-health artifact"
                if source_file.is_file()
                else "missing source-health artifact"
            )
        )
        source_file_for_monitor: Path | None = source_file
    else:
        source_health = [
            row
            for row in source_health_rows
            if isinstance(row, Mapping)
        ]
        source_origin = source_health_origin or "live runtime source-health reader"
        source_file_for_monitor = None
    market_session = _current_market_session(current)
    stock_trade_health_as_of = _dataset_coverage_as_of(
        "stock_trades",
        as_of=as_of,
        now=current,
        dynamic=config_path is None,
    )
    source_health = _source_health_with_massive_lanes(
        source_health,
        data_refresh=data_refresh,
        manifest_root=manifest_dir,
        parquet_root=parquet_dir,
        active_tickers=active_tickers,
        as_of=stock_trade_health_as_of,
        daily_as_of=as_of,
        now=current,
    )
    monitored_source_health = _monitored_source_health(source_health)
    health_monitor = _health_monitor_summary(
        monitored_source_health,
        origin=source_origin,
        now=current,
        source_file=source_file_for_monitor,
    )
    dataset_rows = _dataset_rows(
        config=config,
        active_tickers=active_tickers,
        manifest_root=manifest_dir,
        parquet_root=parquet_dir,
        data_refresh=data_refresh,
        source_health=source_health,
        as_of=as_of,
        now=current,
        dynamic_as_of=config_path is None,
        news_consumption_ledger_path=news_ledger_file,
        news_resolved_source_ids=news_resolved_source_ids,
    )
    lane_rows = _lane_rows(
        runtime_summary=runtime_summary,
        runtime_signals=_runtime_signals(config),
        dataset_rows=dataset_rows,
        expected=expected,
        manifest_root=manifest_dir,
        data_refresh=data_refresh,
        market_session=market_session,
        now=current,
    )
    market_flow = _market_flow_summary(dataset_rows, lane_rows, expected)
    blockers = _blockers(dataset_rows, lane_rows, expected)
    if not config_as_of_verified:
        blockers.append(
            _issue(
                "live_config",
                "end",
                (
                    "Config end date is missing or invalid. Readiness date is a "
                    "derived target, not a source-backed configured as-of date."
                ),
            )
        )
    blockers.extend(_data_refresh_blockers(data_refresh, market_flow=market_flow))
    warnings = _warnings(dataset_rows, lane_rows, runtime_summary)
    warnings.extend(_data_refresh_warnings(data_refresh, market_flow=market_flow))
    data_refresh_state = _effective_data_refresh_state(data_refresh, market_flow=market_flow)
    warnings.extend(_support_refresh_warnings(data_refresh, effective_state=data_refresh_state))
    state = _state(data_refresh_state, blockers, warnings)
    tradable_ready = not blockers and str(market_flow["status"]) == "ready"
    review_operational_ready = state in {"ready", "attention"} and (
        _int_value(market_flow["usable_ticker_count"]) > 0
        or _critical_non_market_lanes_ready(lane_rows)
    )
    mode = _mode(state, tradable_ready, review_operational_ready, market_flow)
    percent = _overall_percent(dataset_rows, lane_rows)
    return {
        "schema_version": "0.1.0",
        "generated_at": current.isoformat(),
        "status_checked_at": current.isoformat(),
        "ready": review_operational_ready,
        "review_operational_ready": review_operational_ready,
        "tradable_ready": tradable_ready,
        "mode": mode,
        "mode_label": _mode_label(mode),
        "state": state,
        "status_label": _status_label(state),
        "status_class": _status_class(state),
        "headline": _headline(state),
        "detail": _detail(state, blockers, warnings),
        "as_of": (
            as_of.isoformat()
            if config_as_of_verified
            else f"target {as_of.isoformat()} (config end missing)"
        ),
        "as_of_source_backed": config_as_of_verified,
        "cycle_id": str(runtime_summary.get("cycle_id") or "None"),
        "expected_ticker_count": expected,
        "evidence_pack_count": _int_value(runtime_summary.get("evidence_pack_count")),
        "signal_count": _int_value(runtime_summary.get("signal_count")),
        "overall_percent": percent,
        "core_dataset_percent": _row_group_percent(dataset_rows, "core"),
        "critical_lane_percent": _critical_lane_percent(lane_rows),
        "market_flow_summary": market_flow,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "blockers": blockers,
        "warnings": warnings,
        "news_resolution": _news_resolution_summary(
            news_manifest,
            news_consumption_ledger_path=news_ledger_file,
            current_source_ids=news_resolved_source_ids,
        ),
        "source_summary": _source_summary(monitored_source_health, now=current),
        "health_monitor": health_monitor,
        "dataset_summary": _dataset_summary(dataset_rows),
        "agent_summary": _agent_summary(lane_rows),
        "freshness_rows": _freshness_rows(monitored_source_health, now=current),
        "datasets": dataset_rows,
        "lanes": lane_rows,
        "data_refresh": data_refresh,
        "live_config": live_config,
        "is_loading": data_refresh.get("state") == "running",
        "progress": {
            "percent_complete": data_refresh.get("percent_complete", 0),
            "current_dataset": data_refresh.get("current_dataset", "None"),
            "eta_label": data_refresh.get("eta_label", "not available"),
            "updated_at": data_refresh.get("updated_at", "Not recorded"),
        },
    }


def _dataset_rows(
    *,
    config: Mapping[str, object],
    active_tickers: set[str],
    manifest_root: Path,
    parquet_root: Path,
    data_refresh: Mapping[str, object],
    source_health: list[Mapping[str, object]],
    as_of: date,
    now: datetime,
    dynamic_as_of: bool,
    news_consumption_ledger_path: Path,
    news_resolved_source_ids: set[str] | None,
) -> list[dict[str, object]]:
    configured = set(_strings(config, "datasets"))
    datasets = [
        *CORE_DATASETS,
        *(dataset for dataset in SUPPORT_DATASETS if not configured or dataset in configured),
        *(dataset for dataset in CONTEXT_DATASETS if not configured or dataset in configured),
    ]
    health_by_source = {
        str(row.get("source")): row
        for row in source_health
        if isinstance(row.get("source"), str)
    }
    rows: list[dict[str, object]] = []
    for dataset in datasets:
        manifest = _read_json_object(manifest_root / f"{dataset}.json")
        dataset_as_of = _dataset_coverage_as_of(
            dataset,
            as_of=as_of,
            now=now,
            dynamic=dynamic_as_of,
        )
        live_trade_lane = (
            _stock_trade_live_lane_snapshot(
                data_refresh,
                manifest_root=manifest_root,
                parquet_root=parquet_root,
                active_tickers=active_tickers,
                as_of=dataset_as_of,
                now=now,
            )
            if dataset == "stock_trades"
            else {}
        )
        daily_bar_lane = (
            _daily_bar_lane_snapshot(
                manifest_root=manifest_root,
                as_of=dataset_as_of,
                active_tickers=active_tickers,
            )
            if dataset == "prices_daily"
            else {}
        )
        manifest_for_status = (
            _stock_trade_status_manifest(manifest, live_trade_lane)
            if dataset == "stock_trades"
            else (
                _daily_bar_status_manifest(manifest, daily_bar_lane)
                if dataset == "prices_daily"
                else manifest
            )
        )
        tickers = (
            _stock_trade_lane_tickers(live_trade_lane)
            if live_trade_lane
            else (
                _daily_bar_lane_tickers(daily_bar_lane)
                if daily_bar_lane
                else _dataset_tickers(dataset, manifest, parquet_root, as_of=dataset_as_of)
            )
        )
        usable_tickers = (
            _stock_trade_lane_usable_tickers(live_trade_lane)
            if live_trade_lane
            else (
                _stock_trade_usable_tickers(manifest, parquet_root, as_of=dataset_as_of)
                if dataset == "stock_trades"
                else tickers
            )
        )
        loaded_count = (
            len(active_tickers.intersection(tickers))
            if active_tickers and tickers
            else len(tickers)
        )
        usable_count = (
            len(active_tickers.intersection(usable_tickers))
            if active_tickers and usable_tickers
            else len(usable_tickers)
        )
        expected = _dataset_expected_count(dataset, active_tickers, tickers)
        coverage = _coverage(loaded_count, expected)
        usable_coverage = _coverage(usable_count, expected)
        expected_count = _int_value(expected) or max(loaded_count, usable_count)
        partial_ticker_count = (
            _stock_trade_lane_partial_count(live_trade_lane)
            if live_trade_lane
            else (
                _stock_trade_partial_count(manifest, parquet_root, as_of=dataset_as_of)
                if dataset == "stock_trades"
                else 0
            )
        )
        issues = _list_field(manifest_for_status, "issues")
        health = (
            _stock_trade_lane_source_health(live_trade_lane, now=now)
            if live_trade_lane
            else (
                _daily_bar_lane_source_health(daily_bar_lane, now=now)
                if daily_bar_lane
                else health_by_source.get(DATASET_SOURCE[dataset], {})
            )
        )
        massive_lane = live_trade_lane or daily_bar_lane
        group = _dataset_group(dataset)
        status = _dataset_status(
            dataset=dataset,
            group=group,
            manifest=manifest_for_status,
            coverage=coverage,
            usable_coverage=usable_coverage,
            issues=issues,
            health=health,
            as_of=dataset_as_of,
            now=now,
            partial_ticker_count=partial_ticker_count,
        )
        rows.append(
            {
                "dataset": dataset,
                "label": DATASET_LABELS[dataset],
                "group": group,
                "status": status,
                "status_label": _row_status_label(status),
                "status_class": _status_class(status),
                "analysis_state": _row_analysis_state(status),
                "loaded_ticker_count": loaded_count if tickers else None,
                "usable_ticker_count": usable_count if usable_tickers else None,
                "expected_ticker_count": expected,
                "coverage_pct": round(coverage * PERCENT_SCALE),
                "usable_coverage_pct": round(usable_coverage * PERCENT_SCALE),
                "coverage_as_of": dataset_as_of.isoformat(),
                "partial_ticker_count": partial_ticker_count,
                "row_count": _int_value(manifest_for_status.get("row_count")),
                **_dataset_news_resolution_fields(
                    dataset,
                    manifest_for_status,
                    news_consumption_ledger_path=news_consumption_ledger_path,
                    current_source_ids=news_resolved_source_ids,
                ),
                "max_as_of": str(manifest.get("max_timestamp_as_of") or "not loaded"),
                "issue_count": len(issues),
                "source_status": str(health.get("status") or "UNKNOWN"),
                "source_freshness": str(health.get("freshness") or "UNKNOWN"),
                "source_checked_at": str(health.get("checked_at") or "not checked"),
                "source_last_success_at": str(health.get("last_success_at") or "not recorded"),
                "massive_lane_id": str(massive_lane.get("lane_id") or "")
                if massive_lane
                else "",
                "massive_lane_status": str(massive_lane.get("status") or "")
                if massive_lane
                else "",
                "massive_lane_coverage_pct": _int_value(massive_lane.get("coverage_pct"))
                if massive_lane
                else None,
                "missing_active_tickers": [
                    str(ticker).upper()
                    for ticker in _list_field(massive_lane, "missing_active_tickers")
                    if str(ticker).strip()
                ]
                if massive_lane
                else [],
                "detail": _dataset_detail(
                    dataset,
                    group,
                    coverage,
                    usable_coverage,
                    issues,
                    health,
                    manifest=manifest_for_status,
                    as_of=dataset_as_of,
                    now=now,
                    partial_ticker_count=partial_ticker_count,
                    expected_ticker_count=expected_count,
                    usable_ticker_count=usable_count,
                    known_ticker_coverage=bool(tickers),
                    live_trade_lane=live_trade_lane,
                    daily_bar_lane=daily_bar_lane,
                    news_consumption_ledger_path=news_consumption_ledger_path,
                    news_resolved_source_ids=news_resolved_source_ids,
                ),
            }
        )
    return rows


def _lane_rows(
    *,
    runtime_summary: Mapping[str, object],
    runtime_signals: tuple[str, ...],
    dataset_rows: Sequence[Mapping[str, object]],
    expected: int,
    manifest_root: Path,
    data_refresh: Mapping[str, object],
    market_session: object,
    now: datetime,
) -> list[dict[str, object]]:
    lane_counts = _mapping(runtime_summary.get("lane_counts"))
    dataset_by_name = {str(row.get("dataset")): row for row in dataset_rows}
    rows: list[dict[str, object]] = []
    for lane in runtime_signals:
        count = _int_value(lane_counts.get(lane))
        group = _lane_group(lane)
        source_dataset = LANE_DATASET.get(lane)
        dataset_row = dataset_by_name.get(source_dataset or "", {})
        required_count = _lane_expected_count(
            lane,
            group,
            expected,
            market_session=market_session,
        )
        coverage = _coverage(count, required_count)
        session_readiness = _session_aware_lane_readiness(
            lane=lane,
            count=count,
            coverage=coverage,
            required_count=required_count,
            dataset_row=dataset_row,
            manifest_root=manifest_root,
            data_refresh=data_refresh,
            market_session=market_session,
            now=now,
        )
        status = str(
            session_readiness.get("status")
            or _lane_status(
                lane=lane,
                group=group,
                count=count,
                coverage=coverage,
                dataset_status=str(dataset_row.get("status") or ""),
            )
        )
        rows.append(
            {
                "lane": lane,
                "label": lane.replace("_", " ").title(),
                "group": group,
                "source_dataset": source_dataset or "unknown",
                "source_freshness": str(
                    session_readiness.get("source_freshness")
                    or dataset_row.get("source_freshness")
                    or "UNKNOWN"
                ),
                "source_status": str(
                    session_readiness.get("source_status")
                    or dataset_row.get("source_status")
                    or "UNKNOWN"
                ),
                "status": status,
                "status_label": _row_status_label(status),
                "status_class": _status_class(status),
                "analysis_state": _row_analysis_state(status),
                "produced_count": count,
                "expected_count": required_count,
                "coverage_pct": round(coverage * PERCENT_SCALE),
                "required_now": bool(session_readiness.get("required_now", True)),
                "detail": str(
                    session_readiness.get("detail")
                    or _lane_detail(
                        lane,
                        group,
                        count,
                        required_count,
                        coverage,
                        dataset_row=dataset_row,
                    )
                ),
            }
        )
    return rows


def _blockers(
    dataset_rows: Sequence[Mapping[str, object]],
    lane_rows: Sequence[Mapping[str, object]],
    expected: int,
) -> list[dict[str, object]]:
    blockers: list[dict[str, object]] = []
    if expected <= 0:
        blockers.append(
            _issue(
                "runtime_universe",
                "active tickers",
                (
                    "No active or configured runtime tickers were found; readiness "
                    "cannot treat zero expected tickers as complete."
                ),
            )
        )
    blockers.extend(
        _issue("dataset", str(row["dataset"]), str(row["detail"]))
        for row in dataset_rows
        if row.get("group") == "core" and row.get("status") == "blocked"
    )
    blockers.extend(
        _issue("agent_lane", str(row["lane"]), str(row["detail"]))
        for row in lane_rows
        if row.get("group") == "critical" and row.get("status") == "blocked"
        and row.get("required_now") is not False
    )
    evidence_rows = [
        row
        for row in lane_rows
        if row.get("group") == "critical" and row.get("required_now") is not False
    ]
    if (
        expected > 0
        and evidence_rows
        and all(_int_value(row.get("produced_count")) == 0 for row in evidence_rows)
    ):
        blockers.append(
            _issue("runtime_cycle", "signals", "No critical agent lane produced rows.")
        )
    return blockers


def _warnings(
    dataset_rows: Sequence[Mapping[str, object]],
    lane_rows: Sequence[Mapping[str, object]],
    runtime_summary: Mapping[str, object],
) -> list[dict[str, object]]:
    warnings = [
        _issue("dataset", str(row["dataset"]), str(row["detail"]))
        for row in dataset_rows
        if row.get("status") == "warning"
    ]
    warnings.extend(
        _issue("agent_lane", str(row["lane"]), str(row["detail"]))
        for row in lane_rows
        if row.get("status") == "warning"
    )
    if _int_value(runtime_summary.get("prompt_audit_count")) == 0:
        warnings.append(_issue("llm_review", "openai", "No LLM prompt audits in latest cycle."))
    return warnings


def _data_refresh_blockers(
    data_refresh: Mapping[str, object],
    *,
    market_flow: Mapping[str, object],
) -> list[dict[str, object]]:
    trade_pull = data_refresh.get("trade_pull")
    if not isinstance(trade_pull, Mapping):
        return []
    state = str(trade_pull.get("state") or "").lower()
    market_flow_usable = _int_value(market_flow.get("usable_ticker_count"))
    market_flow_signals = _int_value(market_flow.get("signal_ticker_count"))
    if state == "partial":
        usable = max(
            _int_value(trade_pull.get("pipeline_ready_count")),
            _int_value(trade_pull.get("pipeline_usable_count")),
            market_flow_usable,
        )
        failed = _int_value(trade_pull.get("pipeline_failed_count"))
        if usable > 0 and market_flow_signals > 0 and failed == 0:
            return []
        detail = str(
            trade_pull.get("detail")
            or trade_pull.get("pipeline_detail")
            or "Massive stock-trade pull is partial with no verified ticker coverage ready for review."
        )
        return [_issue("data_refresh", "stock_trades", detail)]
    if state == "unverified" and market_flow_usable > 0 and market_flow_signals > 0:
        return []
    if state == "stale" and max(
        _int_value(trade_pull.get("pipeline_ready_count")),
        _int_value(trade_pull.get("pipeline_usable_count")),
        market_flow_usable,
    ) > 0:
        detail = str(
            trade_pull.get("detail")
            or (
                "Massive stock-trade pull needs refresh; usable prior slices cannot "
                "satisfy live execution freshness."
            )
        )
        return [_issue("data_refresh", "stock_trades", detail)]
    if state not in TRADE_PULL_BLOCKING_STATES:
        return []
    detail = str(
        trade_pull.get("detail")
        or "Massive stock-trade pull did not complete verified ticker-day coverage."
    )
    return [_issue("data_refresh", "stock_trades", detail)]


def _data_refresh_warnings(
    data_refresh: Mapping[str, object],
    *,
    market_flow: Mapping[str, object],
) -> list[dict[str, object]]:
    trade_pull = data_refresh.get("trade_pull")
    if not isinstance(trade_pull, Mapping):
        return []
    state = str(trade_pull.get("state") or "").lower()
    if state not in {"partial", "unverified"}:
        return []
    usable = max(
        _int_value(trade_pull.get("pipeline_ready_count")),
        _int_value(trade_pull.get("pipeline_usable_count")),
        _int_value(market_flow.get("usable_ticker_count")),
    )
    failed = _int_value(trade_pull.get("pipeline_failed_count"))
    if usable <= 0 or failed > 0:
        return []
    return [
        _issue(
            "data_refresh",
            "stock_trades",
            str(
                trade_pull.get("pipeline_detail")
                or trade_pull.get("detail")
                or (
                    "Massive stock-trade lane status is not full-universe complete; "
                    "usable ticker slices can continue through the pipeline."
                )
            ),
        )
    ]


def _effective_data_refresh_state(
    data_refresh: Mapping[str, object],
    *,
    market_flow: Mapping[str, object],
) -> str:
    state = str(data_refresh.get("state", "idle"))
    if state not in {"stale", "failed", "blocked"}:
        return state
    affected = _affected_refresh_datasets(data_refresh)
    if (
        affected
        and all(not _refresh_dataset_blocks(dataset) for dataset in affected)
        and str(market_flow.get("status") or "") == "ready"
    ):
        return f"{state}_support"
    return state


def _support_refresh_warnings(
    data_refresh: Mapping[str, object],
    *,
    effective_state: str,
) -> list[dict[str, object]]:
    if effective_state not in {"stale_support", "failed_support", "blocked_support"}:
        return []
    affected = _affected_refresh_datasets(data_refresh)
    current_dataset = ", ".join(affected) if affected else "support_dataset"
    state = effective_state.split("_", maxsplit=1)[0].replace("_", " ")
    return [
        _issue(
            "data_refresh",
            current_dataset,
            (
                f"A {state} support-data refresh was found, but core market-data lanes "
                "are current. Treat this as a repair warning, not a paper-trading "
                "blocker."
            ),
        )
    ]


def _affected_refresh_datasets(data_refresh: Mapping[str, object]) -> list[str]:
    values = [
        str(dataset).strip().lower()
        for dataset in _list_field(data_refresh, "failed_datasets")
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


def _market_flow_summary(
    dataset_rows: Sequence[Mapping[str, object]],
    lane_rows: Sequence[Mapping[str, object]],
    expected: int,
) -> dict[str, object]:
    rows = [
        row
        for row in lane_rows
        if str(row.get("lane")) in MARKET_FLOW_LANES
        and row.get("required_now") is not False
    ]
    stock_trades = next(
        (row for row in dataset_rows if str(row.get("dataset")) == "stock_trades"),
        {},
    )
    complete_tickers = _int_value(stock_trades.get("loaded_ticker_count"))
    usable_trade_tickers = _int_value(stock_trades.get("usable_ticker_count")) or complete_tickers
    partial_tickers = _int_value(stock_trades.get("partial_ticker_count"))
    source_missing_or_failed = max(0, expected - complete_tickers - partial_tickers)
    if not rows:
        return {
            "status": "not_configured",
            "status_label": "Not Configured",
            "status_class": "neutral",
            "lane_count": 0,
            "ready_lane_count": 0,
            "warning_lane_count": 0,
            "blocked_lane_count": 0,
            "usable_ticker_count": complete_tickers,
            "source_usable_ticker_count": complete_tickers,
            "partial_ticker_count": partial_tickers,
            "missing_or_failed_ticker_count": max(0, expected - complete_tickers),
            "source_missing_or_failed_ticker_count": source_missing_or_failed,
            "expected_ticker_count": expected,
            "coverage_pct": 0,
            "source_coverage_pct": round(_coverage(complete_tickers, expected) * PERCENT_SCALE),
            "detail": "No market-flow lanes are configured for this cycle.",
        }
    counts = [_int_value(row.get("produced_count")) for row in rows]
    produced = max(counts) if counts else 0
    source_usable = usable_trade_tickers if stock_trades else produced
    signal_usable = min(source_usable, produced) if stock_trades else produced
    signal_missing_or_failed = max(0, expected - signal_usable)
    coverage_pct = round(_coverage(signal_usable, expected) * PERCENT_SCALE)
    source_coverage_pct = round(_coverage(source_usable, expected) * PERCENT_SCALE)
    ready_count = _count_rows(rows, "status", "ready")
    warning_count = _count_rows(rows, "status", "warning")
    blocked_count = _count_rows(rows, "status", "blocked")
    if blocked_count and source_usable <= 0:
        status = "blocked"
    elif signal_usable >= expected and source_missing_or_failed == 0:
        status = "ready"
    elif signal_usable > 0:
        status = "partial"
    else:
        status = "blocked"
    return {
        "status": status,
        "status_label": {
            "ready": "Live Market Flow Ready",
            "partial": "Partial Market Flow",
            "blocked": "Market Flow Blocked",
            "not_configured": "Not Configured",
        }.get(status, status.title()),
        "status_class": _status_class("warning" if status == "partial" else status),
        "lane_count": len(rows),
        "ready_lane_count": ready_count,
        "warning_lane_count": warning_count,
        "blocked_lane_count": blocked_count,
        "usable_ticker_count": signal_usable,
        "source_usable_ticker_count": source_usable,
        "signal_ticker_count": signal_usable,
        "complete_ticker_count": complete_tickers,
        "partial_ticker_count": partial_tickers,
        "missing_or_failed_ticker_count": signal_missing_or_failed,
        "source_missing_or_failed_ticker_count": source_missing_or_failed,
        "expected_ticker_count": expected,
        "coverage_pct": coverage_pct,
        "source_coverage_pct": source_coverage_pct,
        "detail": _market_flow_detail(
            status,
            signal_usable,
            expected,
            rows,
            signal_ticker_count=signal_usable,
            complete_ticker_count=complete_tickers,
            partial_ticker_count=partial_tickers,
            missing_or_failed_ticker_count=signal_missing_or_failed,
        ),
    }


def _market_flow_detail(
    status: str,
    usable: int,
    expected: int,
    rows: Sequence[Mapping[str, object]],
    *,
    signal_ticker_count: int = 0,
    complete_ticker_count: int = 0,
    partial_ticker_count: int = 0,
    missing_or_failed_ticker_count: int = 0,
) -> str:
    if status == "ready":
        if partial_ticker_count:
            return (
                f"Market-flow has live latest-slice coverage for {usable}/{expected} "
                f"active ticker(s), and emitted market-flow signals for "
                f"{signal_ticker_count}/{expected}. {complete_ticker_count} ticker(s) "
                "also have full-depth requested-window coverage. Full-depth repair is "
                "a research/backfill task now, not a live trading blocker."
            )
        return "Market-flow lanes have full latest-slice coverage for the active universe."
    if status == "partial":
        return (
            f"Market-flow has live latest-slice coverage for {usable}/{expected} "
            "active ticker(s). Tickers with coverage can be reviewed now; missing "
            f"live slices still block full-universe trading for "
            f"{missing_or_failed_ticker_count} ticker(s)."
        )
    if not rows:
        return "No market-flow lanes are configured."
    return "Market-flow lanes produced no usable rows in the latest cycle."


def _critical_non_market_lanes_ready(lane_rows: Sequence[Mapping[str, object]]) -> bool:
    return any(
        row.get("group") == "critical"
        and str(row.get("lane")) not in MARKET_FLOW_LANES
        and row.get("status") == "ready"
        for row in lane_rows
    )


def _mode(
    state: str,
    tradable_ready: bool,
    review_operational_ready: bool,
    market_flow: Mapping[str, object],
) -> str:
    if state == "loading":
        return "loading"
    if tradable_ready:
        return "full_universe_tradable"
    if review_operational_ready:
        if str(market_flow.get("status")) == "partial":
            return "review_subset"
        return "review_operational"
    return "blocked"


def _mode_label(mode: str) -> str:
    return {
        "full_universe_tradable": "Full-Universe Tradable",
        "review_subset": "Review Subset",
        "review_operational": "Review Operational",
        "loading": "Loading",
        "blocked": "Blocked",
    }.get(mode, mode.replace("_", " ").title())


def _news_resolution_summary(
    manifest: Mapping[str, object],
    *,
    news_consumption_ledger_path: Path | None = None,
    current_source_ids: set[str] | None = None,
) -> dict[str, object]:
    resolved = _int_value(manifest.get("resolved_row_count"))
    unresolved = _int_value(manifest.get("unresolved_row_count"))
    ambiguous = _int_value(manifest.get("ambiguous_row_count"))
    ticker_count = _int_value(manifest.get("ticker_count"))
    row_count = _int_value(manifest.get("row_count"))
    min_confidence = _number_value(manifest.get("resolution_min_confidence"))
    has_metadata = _has_news_resolution_metadata(manifest)
    consumed = _news_consumed_count(
        news_consumption_ledger_path,
        current_source_ids=current_source_ids,
    )
    consumed_for_current_manifest = (
        consumed if current_source_ids is not None else min(consumed, resolved)
    )
    unused_resolved = max(0, resolved - consumed_for_current_manifest)
    return {
        "row_count": row_count,
        "resolved_row_count": resolved,
        "unresolved_row_count": unresolved,
        "ambiguous_row_count": ambiguous,
        "consumed_row_count": consumed_for_current_manifest,
        "unused_resolved_row_count": unused_resolved,
        "resolved_ticker_count": ticker_count,
        "resolution_min_confidence": min_confidence,
        "fetched_at": str(manifest.get("fetched_at") or "not recorded"),
        "has_resolution_metadata": has_metadata,
        "coverage_label": (
            f"{resolved} resolved / {unresolved} unresolved / {ambiguous} ambiguous"
            if has_metadata
            else "resolution coverage not recorded"
        ),
        "consumption_label": (
            f"{unused_resolved} unused resolved / {consumed_for_current_manifest} already used"
            if has_metadata
            else "RSS/news consumption not available"
        ),
    }


def _dataset_news_resolution_fields(
    dataset: str,
    manifest: Mapping[str, object],
    *,
    news_consumption_ledger_path: Path,
    current_source_ids: set[str] | None,
) -> dict[str, object]:
    if dataset != "news_rss":
        return {}
    summary = _news_resolution_summary(
        manifest,
        news_consumption_ledger_path=news_consumption_ledger_path,
        current_source_ids=current_source_ids,
    )
    return {
        "resolved_row_count": summary["resolved_row_count"],
        "unresolved_row_count": summary["unresolved_row_count"],
        "ambiguous_row_count": summary["ambiguous_row_count"],
        "consumed_row_count": summary["consumed_row_count"],
        "unused_resolved_row_count": summary["unused_resolved_row_count"],
        "resolved_ticker_count": summary["resolved_ticker_count"],
        "news_resolution_coverage_label": summary["coverage_label"],
        "news_consumption_label": summary["consumption_label"],
    }


def _news_resolution_gap(dataset: str, manifest: Mapping[str, object]) -> bool:
    return (
        dataset == "news_rss"
        and _has_news_resolution_metadata(manifest)
        and _int_value(manifest.get("row_count")) > 0
        and _int_value(manifest.get("resolved_row_count")) == 0
    )


def _has_news_resolution_metadata(manifest: Mapping[str, object]) -> bool:
    return any(
        key in manifest
        for key in (
            "resolved_row_count",
            "unresolved_row_count",
            "ambiguous_row_count",
            "ticker_count",
        )
    )


def _news_resolution_detail(
    manifest: Mapping[str, object],
    *,
    news_consumption_ledger_path: Path | None = None,
    current_source_ids: set[str] | None = None,
) -> str:
    summary = _news_resolution_summary(
        manifest,
        news_consumption_ledger_path=news_consumption_ledger_path,
        current_source_ids=current_source_ids,
    )
    row_count = _int_value(summary["row_count"])
    resolved = _int_value(summary["resolved_row_count"])
    unresolved = _int_value(summary["unresolved_row_count"])
    ambiguous = _int_value(summary["ambiguous_row_count"])
    ticker_count = _int_value(summary["resolved_ticker_count"])
    consumed = _int_value(summary["consumed_row_count"])
    unused = _int_value(summary["unused_resolved_row_count"])
    confidence = _number_value(summary["resolution_min_confidence"])
    fetched_at = str(summary["fetched_at"])
    if not summary["has_resolution_metadata"]:
        return (
            f"RSS/news has {row_count} row(s). Ticker-resolution coverage is not "
            "recorded in this manifest yet; refresh news with the current RSS "
            "resolver to show resolved, unresolved, and ambiguous counts."
        )
    if row_count > 0 and resolved == 0:
        return (
            "No ticker-resolved RSS rows are ready. Generic RSS headlines were "
            "fetched, but none passed ticker resolution; refresh news with ticker "
            "aliases or review the alias registry."
        )
    return (
        f"RSS/news has {resolved} ticker-resolved RSS row(s), {unresolved} "
        f"unresolved generic row(s), and {ambiguous} ambiguous row(s) across "
        f"{ticker_count} ticker(s). Last RSS fetch: {fetched_at}. Minimum "
        f"match confidence is {confidence:.2f}. Single-use ledger: {unused} "
        f"resolved row(s) remain unused; {consumed} already used by prior live cycle(s)."
    )


def _news_consumed_count(
    path: Path | None,
    *,
    current_source_ids: set[str] | None = None,
) -> int:
    if path is None:
        return 0
    consumed_ids = set(load_news_consumption_entries(path))
    if current_source_ids is not None:
        return len(consumed_ids.intersection(current_source_ids))
    return len(consumed_ids)


def _news_resolved_source_ids(
    manifest: Mapping[str, object],
    parquet_root: Path,
) -> set[str] | None:
    path_value = manifest.get("path")
    path = parquet_root / (path_value if isinstance(path_value, str) and path_value else "news_rss")
    if not path.exists():
        return None
    try:
        frame = pd.read_parquet(path)
    except (FileNotFoundError, OSError, ValueError):
        return None
    if "source_id" not in frame.columns:
        return None
    if "ticker_match_status" in frame.columns:
        statuses = frame["ticker_match_status"].fillna("").astype(str).str.lower()
        frame = frame[statuses.isin({"resolved", "feed_ticker"})]
    return {
        str(source_id).strip()
        for source_id in frame["source_id"].to_list()
        if str(source_id).strip()
    }


def _dataset_status(
    *,
    dataset: str,
    group: str,
    manifest: Mapping[str, object],
    coverage: float,
    usable_coverage: float | None = None,
    issues: list[object],
    health: Mapping[str, object],
    as_of: date,
    now: datetime,
    partial_ticker_count: int = 0,
) -> str:
    if not manifest:
        return "blocked" if group == "core" else "warning"
    if not health and dataset in CORE_DATASETS:
        return "blocked"
    source_state = _source_issue_status(health, now=now)
    effective_coverage = coverage if usable_coverage is None else usable_coverage
    blocking_issues = _readiness_blocking_issues(
        dataset,
        issues,
        manifest=manifest,
        as_of=as_of,
    )
    support_warning = group == "support" and (
        0.0 < coverage < MIN_SUPPORT_LANE_COVERAGE
        or (coverage == 0.0 and _int_value(manifest.get("row_count")) == 0)
        or bool(blocking_issues)
    )
    context_warning = group == "context" and (
        issues
        or _int_value(manifest.get("row_count")) == 0
        or _news_resolution_gap(dataset, manifest)
    )
    status = "ready"
    if source_state == "blocked":
        status = "blocked" if dataset in CORE_DATASETS else "warning"
    elif group == "core" and _manifest_stale_for_as_of(manifest, as_of) or group == "core" and dataset != "stock_trades" and coverage < 1.0:
        status = "blocked"
    elif source_state == "warning" or dataset == "stock_trades" and 0.0 < effective_coverage < 1.0:
        status = "warning"
    elif group == "core" and (
        effective_coverage if dataset == "stock_trades" else coverage
    ) < 1.0:
        status = "blocked"
    elif dataset == "stock_trades" and partial_ticker_count > 0 or support_warning or context_warning:
        status = "warning"
    return status


def _lane_status(
    *,
    lane: str,
    group: str,
    count: int,
    coverage: float,
    dataset_status: str,
) -> str:
    status = "ready"
    if lane in MARKET_FLOW_LANES:
        if dataset_status == "blocked" or count <= 0:
            status = "blocked"
        elif dataset_status == "warning" or coverage < 1.0:
            status = "warning"
        return status
    if group == "critical" and dataset_status == "blocked":
        status = "blocked"
    elif dataset_status in {"blocked", "warning"} and group != "critical":
        status = "warning"
    elif lane in TOP_DOWN_CONTEXT_LANES:
        status = "ready"
    elif group == "critical":
        status = "ready" if coverage >= 1.0 else "blocked"
    elif lane in SPARSE_SUPPORT_LANES:
        status = "ready"
    elif group == "support":
        status = "ready" if coverage >= MIN_SUPPORT_LANE_COVERAGE else "warning"
    elif count == 0:
        status = "warning"
    return status


def _session_aware_lane_readiness(
    *,
    lane: str,
    count: int,
    coverage: float,
    required_count: int | None,
    dataset_row: Mapping[str, object],
    manifest_root: Path,
    data_refresh: Mapping[str, object],
    market_session: object,
    now: datetime,
) -> Mapping[str, object]:
    if lane != PRE_MARKET_UNUSUAL_ACTIVITY_LANE:
        return {}
    phase = _market_session_phase(market_session)
    if phase != "pre_market":
        return {
            "status": "ready",
            "source_status": "DEFERRED",
            "source_freshness": "NOT_REQUIRED",
            "required_now": False,
            "detail": (
                "Pre-market unusual activity is only required during the 04:00-09:30 ET "
                f"pre-market window. Current phase is {phase}; the next pre-market "
                f"refresh starts at {_next_pre_market_label(now)}."
            ),
        }

    snapshot = _stock_trade_raw_lane_snapshot(
        MASSIVE_PREMARKET_TRADE_LANE_ID,
        label="Massive Pre-Market Trade Slices",
        data_refresh=data_refresh,
        manifest_root=manifest_root,
        as_of=_market_session_date(market_session),
        now=now,
        missing_is_snapshot=False,
    )
    if not snapshot:
        if count > 0:
            return {"required_now": True}
        return {
            "status": "blocked",
            "source_status": str(dataset_row.get("source_status") or "UNKNOWN"),
            "source_freshness": str(dataset_row.get("source_freshness") or "UNKNOWN"),
            "required_now": True,
            "detail": (
                "pre market unusual activity is required now, but no runtime rows "
                "were produced and no massive_premarket_trade_slices lane manifest "
                "is available."
            ),
        }
    health = _stock_trade_lane_source_health(snapshot, now=now)
    source_state = _source_issue_status(health, now=now) if health else "blocked"
    source_status = str(health.get("status") or "UNAVAILABLE")
    source_freshness = str(health.get("freshness") or "UNAVAILABLE")
    if source_state == "blocked":
        detail = str(health.get("detail") or "").strip()
        if not detail:
            detail = "massive_premarket_trade_slices has no usable lane manifest."
        return {
            "status": "blocked",
            "source_status": source_status,
            "source_freshness": source_freshness,
            "required_now": True,
            "detail": (
                "pre market unusual activity is blocked because the pre-market raw "
                f"trade lane is not current: {detail}"
            ),
        }
    dataset_status = str(dataset_row.get("status") or "")
    if dataset_status == "blocked":
        reason = str(dataset_row.get("detail") or "stock-trade source data is not ready.")
        return {
            "status": "blocked",
            "source_status": source_status,
            "source_freshness": source_freshness,
            "required_now": True,
            "detail": f"pre market unusual activity is blocked because {reason}",
        }
    if count <= 0:
        return {
            "status": "blocked",
            "source_status": source_status,
            "source_freshness": source_freshness,
            "required_now": True,
            "detail": (
                "pre market unusual activity is required now, but the latest runtime "
                "cycle produced 0 rows from massive_premarket_trade_slices."
            ),
        }
    status = "warning" if source_state == "warning" or coverage < 1.0 else "ready"
    return {
        "status": status,
        "source_status": source_status,
        "source_freshness": source_freshness,
        "required_now": True,
    }


def _state(data_refresh_state: str, blockers: Sequence[object], warnings: Sequence[object]) -> str:
    if blockers:
        return "blocked"
    if data_refresh_state in {"stale", "blocked", "failed", "planned", "unavailable"}:
        return "blocked"
    if data_refresh_state in {
        "running",
        "stale_support",
        "failed_support",
        "blocked_support",
    }:
        return "attention"
    if warnings:
        return "attention"
    return "ready"


def _overall_percent(
    dataset_rows: Sequence[Mapping[str, object]],
    lane_rows: Sequence[Mapping[str, object]],
) -> int:
    core = _row_group_percent(dataset_rows, "core")
    support = _row_group_percent(dataset_rows, "support")
    critical = _critical_lane_percent(lane_rows)
    context = _row_group_percent(lane_rows, "context")
    return round(core * 0.45 + critical * 0.35 + support * 0.10 + context * 0.10)


def _row_group_percent(rows: Sequence[Mapping[str, object]], group: str) -> int:
    values = [
        _int_value(row.get("coverage_pct"))
        for row in rows
        if row.get("group") == group and isinstance(row.get("coverage_pct"), int)
    ]
    if not values:
        return PERCENT_SCALE
    return round(sum(values) / len(values))


def _critical_lane_percent(lane_rows: Sequence[Mapping[str, object]]) -> int:
    return _row_group_percent(lane_rows, "critical")


def _dataset_detail(
    dataset: str,
    group: str,
    coverage: float,
    usable_coverage: float | None,
    issues: list[object],
    health: Mapping[str, object],
    *,
    manifest: Mapping[str, object],
    as_of: date,
    now: datetime,
    partial_ticker_count: int,
    expected_ticker_count: int,
    usable_ticker_count: int,
    known_ticker_coverage: bool,
    live_trade_lane: Mapping[str, object],
    daily_bar_lane: Mapping[str, object],
    news_consumption_ledger_path: Path | None = None,
    news_resolved_source_ids: set[str] | None = None,
) -> str:
    if not health:
        return (
            f"{DATASET_LABELS[dataset]} has no source-health row; run a live runtime "
            "cycle to verify freshness."
        )
    source_state = _source_issue_status(health, now=now)
    if source_state != "ready":
        return (
            f"{DATASET_LABELS[dataset]} source needs attention: "
            f"{_source_detail(health, now=now)}"
        )
    if dataset == "news_rss":
        return _news_resolution_detail(
            manifest,
            news_consumption_ledger_path=news_consumption_ledger_path,
            current_source_ids=news_resolved_source_ids,
        )
    if group == "core":
        percent = round(coverage * PERCENT_SCALE)
        usable_percent = round((coverage if usable_coverage is None else usable_coverage) * PERCENT_SCALE)
        freshness = str(health.get("freshness") or "UNKNOWN")
        if _manifest_stale_for_as_of(manifest, as_of):
            latest = str(manifest.get("max_timestamp_as_of") or "not loaded")
            return (
                f"{DATASET_LABELS[dataset]} is loaded through {latest}, "
                f"but the current readiness date is {as_of.isoformat()}."
            )
        if dataset == "prices_daily" and daily_bar_lane:
            lane_label = str(daily_bar_lane.get("label") or "Massive daily bars")
            status = str(daily_bar_lane.get("status") or "unknown")
            fetched_at = str(daily_bar_lane.get("fetched_at") or "not recorded")
            fetched_at_dt = _parse_datetime(fetched_at)
            missing_active_tickers = [
                str(ticker).upper()
                for ticker in _list_field(daily_bar_lane, "missing_active_tickers")
                if str(ticker).strip()
            ]
            missing_note = (
                f" Missing active ticker(s): {_ticker_list_preview(missing_active_tickers)}."
                if missing_active_tickers
                else ""
            )
            closed_market_note = (
                " Closed-market freshness uses the latest completed trading session."
                if fetched_at_dt is not None
                and _daily_bar_lane_current_for_latest_completed_session(fetched_at_dt, now)
                else ""
            )
            return (
                f"{lane_label} has verified OHLCV coverage for "
                f"{usable_ticker_count}/{expected_ticker_count} active ticker(s) "
                f"through {as_of.isoformat()} ({usable_percent}%). Lane status is "
                f"{status}; fetched at {fetched_at}. Daily bars feed technical "
                "analysis, abnormal-volume baselines, and sector regime."
                f"{missing_note}"
                f"{closed_market_note}"
            )
        if dataset == "stock_trades" and live_trade_lane:
            lane_label = str(live_trade_lane.get("label") or "Massive live trade slices")
            status = str(live_trade_lane.get("status") or "unknown")
            fetched_at = str(live_trade_lane.get("fetched_at") or "not recorded")
            fetched_at_dt = _parse_datetime(fetched_at)
            proof_detail = str(live_trade_lane.get("proof_detail") or "")
            proof_note = f" {proof_detail}" if proof_detail else ""
            closed_market_note = (
                " Closed-market freshness uses the latest completed trading session."
                if fetched_at_dt is not None
                and _closed_market_live_trade_lane_current(fetched_at_dt, now)
                else ""
            )
            return (
                f"{lane_label} has usable current-day latest-slice trade coverage for "
                f"{usable_ticker_count}/{expected_ticker_count} active ticker(s) "
                f"for {as_of.isoformat()} ({usable_percent}%). Lane status is "
                f"{status}; fetched at {fetched_at}. Full-depth historical tape "
                "repair is tracked separately by massive_backtest_trade_tape and is "
                "not a live-decision blocker."
                f"{proof_note}"
                f"{closed_market_note}"
            )
        if dataset == "stock_trades" and 0.0 < (usable_coverage or coverage) < 1.0:
            if usable_ticker_count > 0:
                return (
                    f"{DATASET_LABELS[dataset]} has usable latest-slice coverage for "
                    f"{usable_ticker_count}/{expected_ticker_count} active tickers for "
                    f"{as_of.isoformat()} ({usable_percent}%). Bounded live slices can "
                    "continue through review while off-hours repair finishes."
                )
            return (
                f"{DATASET_LABELS[dataset]} has verified latest-slice coverage for "
                f"{usable_percent}% of active tickers for {as_of.isoformat()}. Market-flow "
                "analysis can review that ticker subset now; full-universe trading "
                "remains gated until all active ticker slices complete."
            )
        if coverage < 1.0:
            return (
                f"{DATASET_LABELS[dataset]} latest-slice coverage is {percent}% "
                f"of active tickers for {as_of.isoformat()}."
            )
        if dataset == "stock_trades" and partial_ticker_count > 0:
            return (
                f"{DATASET_LABELS[dataset]} has a latest trade slice for all active "
                f"tickers, but {partial_ticker_count} ticker(s) still need requested-window "
                "off-hours repair."
            )
        return (
            f"{DATASET_LABELS[dataset]} covers {percent}% of active tickers; "
            f"source freshness {freshness}."
        )
    blocking_issues = _readiness_blocking_issues(
        dataset,
        issues,
        manifest=manifest,
        as_of=as_of,
    )
    if issues and not blocking_issues:
        return (
            f"{DATASET_LABELS[dataset]} is current for {as_of.isoformat()}; "
            f"{len(issues)} historical repair issue(s) remain queued but do not "
            "degrade current filing freshness."
        )
    if blocking_issues:
        return f"{DATASET_LABELS[dataset]} loaded with {len(issues)} issue(s)."
    if group == "support" and not known_ticker_coverage:
        return f"{DATASET_LABELS[dataset]} loaded; ticker coverage is not a row-by-row requirement."
    freshness = str(health.get("freshness") or "UNKNOWN")
    return f"{DATASET_LABELS[dataset]} available; source freshness {freshness}."


def _lane_detail(
    lane: str,
    group: str,
    count: int,
    expected: int | None,
    coverage: float,
    *,
    dataset_row: Mapping[str, object],
) -> str:
    dataset_status = str(dataset_row.get("status") or "")
    if dataset_status == "blocked":
        reason = str(dataset_row.get("detail") or "its source dataset is not ready.")
        return f"{lane.replace('_', ' ')} is blocked because {reason}"
    if dataset_status == "warning":
        source_dataset = str(dataset_row.get("label") or dataset_row.get("dataset") or "source")
        source_freshness = str(dataset_row.get("source_freshness") or "UNKNOWN")
        if lane in MARKET_FLOW_LANES and count > 0:
            return (
                f"{lane.replace('_', ' ')} produced {count}/{expected} row(s) from "
                f"the verified trade-print subset. Use it for review on covered "
                f"tickers only; {source_dataset} still needs repair before full "
                "universe trading."
            )
        return (
            f"{lane.replace('_', ' ')} has a warning because {source_dataset} "
            f"freshness is {source_freshness}."
        )
    if lane in TOP_DOWN_CONTEXT_LANES:
        return (
            "Sector momentum is analyzed in the Universe & Market Regime view; "
            "it is not emitted as one signal row per stock."
        )
    if lane == "insider" and count == 0:
        return (
            "Insider monitoring found no current insider Form 4 events for the "
            "active universe; the SEC Form 4 source dataset is current."
        )
    if expected is not None:
        return (
            f"{lane.replace('_', ' ')} produced {count}/{expected} rows "
            f"({round(coverage * PERCENT_SCALE)}%)."
        )
    if group == "context":
        return f"{lane.replace('_', ' ')} produced {count} context signal row(s)."
    return f"{lane.replace('_', ' ')} produced {count} row(s)."


def _headline(state: str) -> str:
    return {
        "ready": "All configured data and agent lanes are loaded.",
        "attention": "Agency is review-operational; some data lanes need attention.",
        "blocked": "A required data or agent lane is not ready.",
        "loading": "Data is currently loading.",
    }.get(state, "Data-load status is unknown.")


def _detail(
    state: str,
    blockers: Sequence[Mapping[str, object]],
    warnings: Sequence[Mapping[str, object]],
) -> str:
    if state == "ready":
        return "The latest runtime cycle has complete core coverage and usable context."
    if state == "attention" and warnings:
        return str(warnings[0]["reason"])
    if state == "blocked" and blockers:
        return str(blockers[0]["reason"])
    if state == "blocked":
        return "The latest data refresh needs attention: it failed, is blocked, or is unavailable."
    if state == "loading":
        return "A refresh worker is still loading datasets; wait for completion before review."
    return "No data-load detail is available."


def _status_label(state: str) -> str:
    return {
        "ready": "Loaded",
        "attention": "Loaded With Gaps",
        "blocked": "Blocked",
        "loading": "Loading",
    }.get(state, state.title())


def _row_status_label(status: str) -> str:
    return {"ready": "Ready", "warning": "Attention", "blocked": "Blocked"}.get(
        status,
        status.title(),
    )


def _status_class(status: str) -> str:
    if status in {"ready", "pass"}:
        return "pass"
    if status in {"attention", "warning", "warn", "loading"}:
        return "warn"
    return "block"


def _row_analysis_state(status: str) -> str:
    if status in {"ready", "pass"}:
        return "analyzed_current"
    if status in {"attention", "warning", "warn"}:
        return "analyzed_needs_refresh"
    if status == "loading":
        return "loading"
    if status in {"blocked", "failed", "unavailable"}:
        return "data_void"
    return "loaded_unanalyzed"


def _issue(kind: str, item: str, reason: str) -> dict[str, object]:
    return {"kind": kind, "item": item, "reason": reason}


def _health_monitor_summary(
    source_health: Sequence[Mapping[str, object]],
    *,
    origin: str,
    now: datetime,
    source_file: Path | None,
) -> dict[str, object]:
    normalized_origin = origin.strip() or "unknown source-health origin"
    artifact_updated_at = _file_updated_at(source_file)
    checked_values = [
        parsed
        for parsed in (_parse_datetime(row.get("checked_at")) for row in source_health)
        if parsed is not None
    ]
    missing_checked_count = sum(
        1
        for row in source_health
        if _parse_datetime(row.get("checked_at")) is None
        and str(row.get("status") or "").upper() != "UNAVAILABLE"
        and str(row.get("freshness") or "").upper() != "UNAVAILABLE"
    )
    latest_checked = max(checked_values) if checked_values else None
    oldest_checked = min(checked_values) if checked_values else None
    max_age_seconds = (
        int((_ensure_utc(now) - oldest_checked).total_seconds())
        if oldest_checked is not None
        else None
    )
    stale_rows = _stale_health_monitor_rows(source_health, now=now)
    origin_lower = normalized_origin.lower()
    live = "live" in origin_lower and "artifact" not in origin_lower and "unavailable" not in origin_lower
    unavailable_monitor = any(
        str(row.get("source") or "") == "source-health-monitor"
        for row in source_health
    )
    if not source_health:
        status = "missing"
        status_class = "block"
        label = "Health Monitor Missing"
        detail = (
            "No source-health rows were available. The dashboard cannot prove that "
            "its health badges are current."
        )
        reliable = False
    elif unavailable_monitor:
        status = "unavailable"
        status_class = "block"
        label = "Health Monitor Unavailable"
        detail = (
            "The live source-health reader did not return monitored provider rows. "
            "Displayed health state is unavailable for trading decisions."
        )
        reliable = False
    elif missing_checked_count > 0:
        status = "unverified"
        status_class = "block"
        label = "Health Monitor Unverified"
        detail = (
            f"{missing_checked_count} source-health row(s) are missing checked_at. "
            "Refresh source monitoring before trusting the dashboard."
        )
        reliable = False
    elif stale_rows:
        critical_stale_rows = [
            row
            for row in stale_rows
            if str(row.get("source") or "") in CRITICAL_SOURCE_NAMES
        ]
        row = critical_stale_rows[0] if critical_stale_rows else stale_rows[0]
        source = str(row.get("source") or "unknown source")
        checked_at = _parse_datetime(row.get("checked_at"))
        row_age = (
            int((_ensure_utc(now) - checked_at).total_seconds())
            if checked_at is not None
            else None
        )
        row_sla = _source_max_age_seconds(row)
        critical_stale = bool(critical_stale_rows)
        status = "stale" if critical_stale else "context_stale"
        status_class = "block" if critical_stale else "warn"
        label = "Health Monitor Needs Refresh" if critical_stale else "Context Health Needs Refresh"
        detail = (
            f"{source} source-health is older than its SLA"
            + (f" ({row_age}s > {row_sla}s)." if row_age is not None else ".")
            + (
                " Refresh critical source monitoring before relying on execution readiness."
                if critical_stale
                else " Refresh context monitoring; execution-critical lanes are evaluated separately."
            )
        )
        reliable = not critical_stale
    elif not live:
        status = "cached"
        status_class = "warn"
        label = "Cached Health Snapshot"
        detail = (
            "Health rows came from a cached runtime artifact, not a live monitor "
            "read. Treat this dashboard as review context until live monitoring is available."
        )
        reliable = True
    else:
        status = "live"
        status_class = "pass"
        label = "Live Health Monitor"
        detail = "Source-health rows came from the live runtime monitor and are recent."
        reliable = True
    return {
        "status": status,
        "status_label": label,
        "status_class": status_class,
        "origin": normalized_origin,
        "live": live and reliable,
        "reliable": reliable,
        "row_count": len(source_health),
        "missing_checked_count": missing_checked_count,
        "latest_checked_at": latest_checked.isoformat() if latest_checked is not None else "not checked",
        "oldest_checked_at": oldest_checked.isoformat() if oldest_checked is not None else "not checked",
        "max_age_seconds": max_age_seconds,
        "artifact_updated_at": artifact_updated_at,
        "detail": detail,
    }


def _stale_health_monitor_rows(
    source_health: Sequence[Mapping[str, object]],
    *,
    now: datetime,
) -> list[Mapping[str, object]]:
    stale: list[Mapping[str, object]] = []
    current = _ensure_utc(now)
    for row in source_health:
        checked_at = _parse_datetime(row.get("checked_at"))
        if checked_at is None:
            continue
        age_seconds = (current - checked_at).total_seconds()
        if age_seconds <= _source_max_age_seconds(row):
            continue
        if _source_age_is_market_closed_current(row, checked_at=checked_at, now=current):
            continue
        stale.append(row)
    return stale


def _file_updated_at(path: Path | None) -> str:
    if path is None:
        return "not an artifact"
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    except OSError:
        return "not found"


def _monitored_source_health(
    source_health: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    seen: set[str] = set()
    for row in source_health:
        source = str(row.get("source") or "")
        if source not in TRACKED_SOURCE_NAMES and source != "source-health-monitor":
            continue
        if source in seen:
            continue
        seen.add(source)
        rows.append(row)
    return rows


def _source_summary(
    source_health: Sequence[Mapping[str, object]],
    *,
    now: datetime,
) -> dict[str, object]:
    rows = _freshness_rows(source_health, now=now)
    critical = [row for row in rows if row["critical"] is True]
    return {
        "source_count": len(rows),
        "fresh_count": _count_rows(rows, "status_class", "pass"),
        "warning_count": _count_rows(rows, "status_class", "warn"),
        "blocked_count": _count_rows(rows, "status_class", "block"),
        "critical_blocker_count": _count_rows(critical, "status_class", "block"),
        "critical_warning_count": _count_rows(critical, "status_class", "warn"),
        "headline": _source_summary_headline(rows),
    }


def _dataset_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    total = len(rows)
    ready = _count_rows(rows, "status", "ready")
    return {
        "ready_count": ready,
        "warning_count": _count_rows(rows, "status", "warning"),
        "blocked_count": _count_rows(rows, "status", "blocked"),
        "total_count": total,
        "ready_label": f"{ready}/{total} datasets",
    }


def _agent_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    critical = [row for row in rows if row.get("group") == "critical"]
    critical_ready = _count_rows(critical, "status", "ready")
    total_critical = len(critical)
    return {
        "ready_count": _count_rows(rows, "status", "ready"),
        "warning_count": _count_rows(rows, "status", "warning"),
        "blocked_count": _count_rows(rows, "status", "blocked"),
        "total_count": len(rows),
        "critical_ready_count": critical_ready,
        "critical_total_count": total_critical,
        "critical_ready_label": f"{critical_ready}/{total_critical} critical lanes",
    }


def _freshness_rows(
    source_health: Sequence[Mapping[str, object]],
    *,
    now: datetime,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen_sources: set[str] = set()
    for row in source_health:
        source = str(row.get("source") or "unknown")
        seen_sources.add(source)
        issue_status = _source_issue_status(row, now=now)
        rows.append(
            {
                "source": source,
                "label": source.replace("-", " ").title(),
                "status": str(row.get("status") or "UNKNOWN"),
                "freshness": str(row.get("freshness") or "UNKNOWN"),
                "status_class": _status_class(issue_status),
                "last_success_at": str(row.get("last_success_at") or "not recorded"),
                "checked_at": str(row.get("checked_at") or "not checked"),
                "critical": source in CRITICAL_SOURCE_NAMES,
                "missing_active_tickers": [
                    str(ticker).upper()
                    for ticker in _list_field(row, "missing_active_tickers")
                    if str(ticker).strip()
                ],
                "active_usable_ticker_count": _int_value(
                    row.get("active_usable_ticker_count")
                ),
                "active_expected_ticker_count": _int_value(
                    row.get("active_expected_ticker_count")
                ),
                "active_coverage_pct": _int_value(row.get("active_coverage_pct")),
                "detail": _source_detail(row, now=now),
            }
        )
    for source in sorted(TRACKED_SOURCE_NAMES.difference(seen_sources)):
        critical = source in CRITICAL_SOURCE_NAMES
        rows.append(
            {
                "source": source,
                "label": source.replace("-", " ").title(),
                "status": "UNAVAILABLE",
                "freshness": "UNAVAILABLE",
                "status_class": "block" if critical else "warn",
                "last_success_at": "not recorded",
                "checked_at": "not checked",
                "critical": critical,
                "detail": (
                    f"{source} has no source-health row; run a live runtime cycle "
                    "before treating the system as tradable."
                ),
            }
        )
    return rows


def _source_issue_status(
    row: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> str:
    if not row:
        return "warning"
    source = str(row.get("source") or "")
    critical = source in CRITICAL_SOURCE_NAMES
    checked_at = _parse_datetime(row.get("checked_at"))
    if checked_at is None:
        return "blocked" if critical else "warning"
    current = _ensure_utc(now or datetime.now(UTC))
    age_seconds = (current - checked_at).total_seconds()
    max_age_seconds = _source_max_age_seconds(row)
    if age_seconds > max_age_seconds and not _source_age_is_market_closed_current(
        row,
        checked_at=checked_at,
        now=current,
    ):
        return "blocked" if critical else "warning"
    freshness = str(row.get("freshness") or "UNKNOWN").upper()
    status = str(row.get("status") or "UNKNOWN").upper()
    if freshness in SOURCE_BLOCKING_STATUSES or status in SOURCE_BLOCKING_STATUSES:
        return "blocked"
    if freshness in SOURCE_WARNING_STATUSES or status in SOURCE_WARNING_STATUSES:
        return "warning"
    return "ready"


def _source_detail(row: Mapping[str, object], *, now: datetime) -> str:
    source = str(row.get("source") or "unknown source")
    freshness = str(row.get("freshness") or "UNKNOWN")
    status = str(row.get("status") or "UNKNOWN")
    detail = row.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail
    last_success = str(row.get("last_success_at") or "not recorded")
    checked_at = _parse_datetime(row.get("checked_at"))
    if checked_at is None:
        return (
            f"{source} is {status} with {freshness} freshness; checked_at is missing, "
            "so current health is unverified."
        )
    age_seconds = int((_ensure_utc(now) - checked_at).total_seconds())
    max_age_seconds = _source_max_age_seconds(row)
    if age_seconds > max_age_seconds and not _source_age_is_market_closed_current(
        row,
        checked_at=checked_at,
        now=now,
    ):
        return (
            f"{source} is {status} with {freshness} freshness; source-health row is "
            f"{age_seconds}s old; last success {last_success}."
        )
    return f"{source} is {status} with {freshness} freshness; last success {last_success}."


def _source_max_age_seconds(row: Mapping[str, object]) -> int:
    value = row.get("max_age_seconds")
    if isinstance(value, bool):
        value = None
    if isinstance(value, int | float) and value > 0:
        return round(value)
    source = str(row.get("source") or "")
    return SOURCE_HEALTH_MAX_AGE_BY_SOURCE.get(source, SOURCE_HEALTH_MAX_AGE_SECONDS)


def _source_age_is_market_closed_current(
    row: Mapping[str, object],
    *,
    checked_at: datetime,
    now: datetime,
) -> bool:
    source = str(row.get("source") or "")
    if source == "massive-stock-trades":
        return _closed_market_live_trade_lane_current(checked_at, now)
    if source == "daily-market-bars":
        if _source_max_age_seconds(row) < MASSIVE_DAILY_BARS_SLA_SECONDS:
            return False
        return _daily_bar_lane_current_for_latest_completed_session(checked_at, now)
    return False


def _source_summary_headline(rows: Sequence[Mapping[str, object]]) -> str:
    critical_blockers = [
        row
        for row in rows
        if row.get("critical") is True and row.get("status_class") == "block"
    ]
    if critical_blockers:
        row = critical_blockers[0]
        status = str(row.get("status") or "").upper()
        freshness = str(row.get("freshness") or "").upper()
        label = str(row.get("label") or "source")
        if status == "UNAVAILABLE" or freshness == "UNAVAILABLE":
            return f"Critical source unavailable: {label}"
        if status in {"HEALTHY", "FRESH"} and freshness == "FRESH":
            return f"Critical health proof needs refresh: {label}"
        return f"Critical source needs refresh: {label}"
    blocked = _count_rows(rows, "status_class", "block")
    warned = _count_rows(rows, "status_class", "warn")
    if blocked:
        return f"{blocked} source(s) blocked."
    if warned:
        return f"{warned} source(s) need attention."
    return "All tracked sources are fresh."


def _manifest_stale_for_as_of(manifest: Mapping[str, object], as_of: date) -> bool:
    value = str(manifest.get("max_timestamp_as_of") or "")
    if not value:
        return True
    try:
        observed = pd.to_datetime(value, utc=True).date()
    except (TypeError, ValueError):
        return True
    return observed < as_of


def _readiness_blocking_issues(
    dataset: str,
    issues: Sequence[object],
    *,
    manifest: Mapping[str, object],
    as_of: date,
) -> list[object]:
    return [
        issue
        for issue in issues
        if not _nonblocking_historical_repair_issue(
            dataset,
            issue,
            manifest=manifest,
            as_of=as_of,
        )
    ]


def _nonblocking_historical_repair_issue(
    dataset: str,
    issue: object,
    *,
    manifest: Mapping[str, object],
    as_of: date,
) -> bool:
    if dataset != "sec_form4" or _manifest_stale_for_as_of(manifest, as_of):
        return False
    if _int_value(manifest.get("row_count")) <= 0 or not isinstance(issue, Mapping):
        return False
    reason = str(issue.get("reason") or issue.get("detail") or "").casefold()
    if "rate limit" not in reason and "429" not in reason:
        return False
    accession_year = _sec_accession_year(issue.get("accession_number"))
    return accession_year is not None and accession_year < as_of.year


def _sec_accession_year(value: object) -> int | None:
    text = str(value or "").strip()
    parts = text.split("-")
    if len(parts) < 2 or len(parts[1]) != 2 or not parts[1].isdigit():
        return None
    return 2000 + int(parts[1])


def _count_rows(rows: Sequence[Mapping[str, object]], key: str, value: object) -> int:
    return sum(1 for row in rows if row.get(key) == value)


def _dataset_group(dataset: str) -> str:
    if dataset in CORE_DATASETS:
        return "core"
    if dataset in SUPPORT_DATASETS:
        return "support"
    return "context"


def _lane_group(lane: str) -> str:
    if lane in CRITICAL_LANES:
        return "critical"
    if lane in SUPPORT_LANES:
        return "support"
    if lane in CONTEXT_LANES:
        return "context"
    return "support"


def _dataset_expected_count(
    dataset: str,
    active_tickers: set[str],
    known_tickers: set[str],
) -> int | None:
    if dataset in CORE_DATASETS:
        return len(active_tickers) if active_tickers else len(known_tickers)
    if dataset == "sec_company_facts" and known_tickers:
        return len(active_tickers) if active_tickers else len(known_tickers)
    return None


def _lane_expected_count(
    lane: str,
    group: str,
    expected: int,
    *,
    market_session: object | None = None,
) -> int | None:
    if lane == PRE_MARKET_UNUSUAL_ACTIVITY_LANE and not _premarket_lane_required_now(
        market_session
    ):
        return None
    if group == "critical":
        return expected if expected > 0 else 1
    if lane in PER_TICKER_SUPPORT_LANES:
        return expected if expected > 0 else 1
    return None


def _coverage(count: int, expected: int | None) -> float:
    if expected is None or expected == 0:
        return 1.0
    return max(0.0, min(1.0, count / expected))


def _ticker_list_preview(tickers: Sequence[str], *, limit: int = 12) -> str:
    values = [ticker.upper() for ticker in tickers if ticker.strip()]
    if not values:
        return "none"
    preview = ", ".join(values[:limit])
    remaining = len(values) - limit
    if remaining > 0:
        return f"{preview}, and {remaining} more"
    return preview


def _runtime_signals(config: Mapping[str, object]) -> tuple[str, ...]:
    values = _strings(config, "runtime_signals")
    return values or (
        "abnormal_volume",
        "technical_analysis",
        "buy_sell_pressure",
        "block_trade_pressure",
        "unusual_trade_activity",
        "pre_market_unusual_activity",
        "market_flow_trend",
        "sector_momentum",
    )


def _active_universe_tickers(as_of: date, path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        frame = pd.read_parquet(path, columns=["ticker", "start_date", "end_date"])
    except (OSError, ValueError, KeyError):
        return set()
    if frame.empty:
        return set()
    start = pd.to_datetime(frame["start_date"], errors="coerce")
    end = pd.to_datetime(frame["end_date"], errors="coerce")
    as_of_timestamp = pd.Timestamp(as_of)
    active = frame[(start <= as_of_timestamp) & (end.isna() | (end > as_of_timestamp))]
    return {str(ticker).upper() for ticker in active["ticker"].dropna().unique()}


def _configured_tickers(config: Mapping[str, object]) -> set[str]:
    return {ticker.upper() for ticker in _strings(config, "tickers") if ticker.strip()}


def _source_health_with_massive_lanes(
    rows: Sequence[Mapping[str, object]],
    *,
    data_refresh: Mapping[str, object],
    manifest_root: Path,
    parquet_root: Path,
    active_tickers: set[str],
    as_of: date,
    daily_as_of: date,
    now: datetime,
) -> list[Mapping[str, object]]:
    source_rows: list[Mapping[str, object]] = [dict(row) for row in rows]
    daily_snapshot = _daily_bar_lane_snapshot(
        manifest_root=manifest_root,
        as_of=daily_as_of,
        active_tickers=active_tickers,
    )
    source_rows = _merge_lane_source_health(
        source_rows,
        _daily_bar_lane_source_health(daily_snapshot, now=now),
        now=now,
        note=f"source-health overridden by {MASSIVE_DAILY_BARS_LANE_ID} lane manifest",
    )
    for dataset in CONTEXT_DATASETS:
        source_rows = _merge_lane_source_health(
            source_rows,
            _context_manifest_source_health(dataset, manifest_root=manifest_root, now=now),
            now=now,
            note=f"source-health overridden by latest {dataset} manifest",
        )
    market_session = _current_market_session(now)
    if _premarket_lane_required_now(market_session):
        trade_lane_id = MASSIVE_PREMARKET_TRADE_LANE_ID
        live_snapshot = _stock_trade_raw_lane_snapshot(
            trade_lane_id,
            label="Massive Pre-Market Trade Slices",
            data_refresh=data_refresh,
            manifest_root=manifest_root,
            as_of=_market_session_date(market_session),
            now=now,
            missing_is_snapshot=True,
        )
    else:
        trade_lane_id = MASSIVE_LIVE_TRADE_LANE_ID
        live_snapshot = _stock_trade_live_lane_snapshot(
            data_refresh,
            manifest_root=manifest_root,
            parquet_root=parquet_root,
            active_tickers=active_tickers,
            as_of=as_of,
            now=now,
        )
    return _merge_lane_source_health(
        source_rows,
        _stock_trade_lane_source_health(live_snapshot, now=now),
        now=now,
        note=f"source-health overridden by {trade_lane_id} lane manifest",
    )


def _merge_lane_source_health(
    source_rows: list[Mapping[str, object]],
    lane_health: Mapping[str, object],
    *,
    now: datetime,
    note: str,
) -> list[Mapping[str, object]]:
    if not lane_health:
        return source_rows
    source_name = str(lane_health.get("source") or "")
    replaced = False
    for index, row in enumerate(source_rows):
        if str(row.get("source") or "") != source_name:
            continue
        merged = dict(row)
        merged.update(lane_health)
        merged["notes"] = [
            *[str(item) for item in _list_field(row, "notes")],
            note,
        ]
        source_rows[index] = merged
        replaced = True
        break
    if not replaced:
        source_rows.append(dict(lane_health))
    return source_rows


def _source_state_rank(state: str) -> int:
    return {"ready": 0, "warning": 1, "blocked": 2}.get(state, 2)


def _daily_bar_lane_snapshot(
    *,
    manifest_root: Path,
    as_of: date,
    active_tickers: set[str] | None = None,
) -> Mapping[str, object]:
    lane_id = MASSIVE_DAILY_BARS_LANE_ID
    manifest = _read_json_object(
        manifest_root / "massive_lanes" / f"{lane_id}.json"
    )
    if not manifest:
        if (manifest_root / "massive_lanes").exists():
            return _missing_lane_snapshot(lane_id, label="Massive Daily Bars")
        return {}
    if not _lane_manifest_reaches_as_of(manifest, as_of):
        return _out_of_window_lane_snapshot(
            lane_id,
            label="Massive Daily Bars",
            manifest=manifest,
            as_of=as_of,
        )
    tickers = sorted(
        {
            str(ticker).upper()
            for ticker in _list_field(manifest, "tickers")
            if str(ticker).strip()
        }
    )
    coverage = [
        row
        for row in _sequence_mappings(manifest.get("coverage"))
        if str(row.get("ticker") or "").strip()
    ]
    complete = sorted(
        {
            str(row.get("ticker")).upper()
            for row in coverage
            if row.get("complete") is True
            or str(row.get("coverage_status") or row.get("status") or "").lower()
            == "complete"
        }
    )
    if not coverage and tickers and str(manifest.get("status") or "").lower() == "complete":
        complete = tickers
    missing_active_tickers: list[str] = []
    active_usable_ticker_count: int | None = None
    active_expected_ticker_count: int | None = None
    active_coverage_pct: int | None = None
    issues = _list_field(manifest, "issues")
    status = str(manifest.get("status") or "unknown")
    if active_tickers:
        expected = {ticker.upper() for ticker in active_tickers if ticker.strip()}
        usable = expected.intersection(complete)
        missing_active_tickers = sorted(expected.difference(usable))
        active_usable_ticker_count = len(usable)
        active_expected_ticker_count = len(expected)
        active_coverage_pct = round(_coverage(len(usable), len(expected)) * PERCENT_SCALE)
        if missing_active_tickers:
            status = "partial_active_universe"
            issues = [
                *issues,
                (
                    f"{lane_id} covers {len(usable)}/{len(expected)} active ticker(s); "
                    f"missing {_ticker_list_preview(missing_active_tickers)}"
                ),
            ]
    return {
        "lane_id": lane_id,
        "label": "Massive Daily Bars",
        "manifest": manifest,
        "status": status,
        "fetched_at": str(manifest.get("fetched_at") or ""),
        "coverage_pct": _int_value(manifest.get("coverage_pct")),
        "tickers": tickers,
        "usable_tickers": complete,
        "missing_active_tickers": missing_active_tickers,
        "active_usable_ticker_count": active_usable_ticker_count,
        "active_expected_ticker_count": active_expected_ticker_count,
        "active_coverage_pct": active_coverage_pct,
        "issues": issues,
        "row_count": _int_value(manifest.get("row_count")),
    }


def _stock_trade_live_lane_snapshot(
    data_refresh: Mapping[str, object],
    *,
    manifest_root: Path,
    parquet_root: Path | None = None,
    active_tickers: set[str] | None = None,
    as_of: date,
    now: datetime,
) -> Mapping[str, object]:
    lane_id = MASSIVE_LIVE_TRADE_LANE_ID
    manifest = _read_json_object(
        manifest_root / "massive_lanes" / f"{lane_id}.json"
    )
    if not manifest:
        if not (manifest_root / "massive_lanes").exists():
            return {}
        return _missing_lane_snapshot(lane_id, label="Massive Live Trade Slices")
    if not _lane_manifest_covers_as_of(manifest, as_of):
        coverage_snapshot = _stock_trade_coverage_metadata_lane_snapshot(
            manifest_root=manifest_root,
            parquet_root=parquet_root,
            active_tickers=active_tickers,
            superseded_manifest=manifest,
            as_of=as_of,
        )
        if coverage_snapshot:
            return coverage_snapshot
        return _out_of_window_lane_snapshot(
            lane_id,
            label="Massive Live Trade Slices",
            manifest=manifest,
            as_of=as_of,
        )
    progress_row = next(
        (
            row
            for row in _sequence_mappings(data_refresh.get("massive_lanes"))
            if str(row.get("lane_id")) == MASSIVE_LIVE_TRADE_LANE_ID
        ),
        {},
    )
    progress = _mapping(data_refresh.get("trade_pull"))
    if str(progress.get("lane_id") or "") != MASSIVE_LIVE_TRADE_LANE_ID:
        progress = {}
    tickers = sorted(
        {
            str(ticker).upper()
            for ticker in _list_field(manifest, "tickers")
            if str(ticker).strip()
        }
    )
    coverage = [
        row
        for row in _sequence_mappings(manifest.get("coverage"))
        if str(row.get("ticker") or "").strip()
    ]
    fallback_checked_at = _parse_datetime(manifest.get("fetched_at"))
    usable = sorted(
        {
            str(row.get("ticker")).upper()
            for row in coverage
            if _stock_trade_live_coverage_row_usable(row)
            and _stock_trade_live_coverage_row_fresh(
                row,
                now=now,
                fallback_checked_at=fallback_checked_at,
            )
        }
    )
    if not coverage and tickers and str(manifest.get("status") or "").lower() == "complete":
        usable = tickers
    failed = sorted(
        {
            str(row.get("ticker")).upper()
            for row in coverage
            if str(row.get("coverage_status") or row.get("status") or "").lower()
            == "failed"
        }
    )
    partial_source = sorted(
        {
            str(row.get("ticker")).upper()
            for row in coverage
            if _stock_trade_live_coverage_row_usable(row)
            and not _stock_trade_live_coverage_row_complete(row)
        }
    )
    partial = sorted(set(tickers).difference(usable).difference(failed))
    fetched_at = str(manifest.get("fetched_at") or progress_row.get("updated_at") or "")
    return {
        "lane_id": lane_id,
        "label": "Massive Live Trade Slices",
        "manifest": manifest,
        "progress": progress,
        "progress_row": progress_row,
        "status": str(manifest.get("status") or progress_row.get("state") or "unknown"),
        "fetched_at": fetched_at,
        "coverage_pct": _int_value(manifest.get("coverage_pct")),
        "tickers": tickers,
        "usable_tickers": usable,
        "failed_tickers": failed,
        "partial_tickers": partial,
        "partial_source_tickers": partial_source,
        "issues": _list_field(manifest, "issues"),
        "row_count": _int_value(manifest.get("row_count")),
    }


def _stock_trade_coverage_metadata_lane_snapshot(
    *,
    manifest_root: Path,
    parquet_root: Path | None,
    active_tickers: set[str] | None,
    superseded_manifest: Mapping[str, object],
    as_of: date,
) -> Mapping[str, object]:
    if parquet_root is None:
        return {}
    stock_manifest = _read_json_object(manifest_root / "stock_trades.json")
    if not stock_manifest or not _stock_trade_manifest_covers_as_of(stock_manifest, as_of):
        return {}
    path_value = stock_manifest.get("path")
    root = parquet_root / str(path_value or "stock_trades")
    coverage = _load_stock_trade_coverage_metadata(root)
    manifest_tickers = _manifest_tickers(stock_manifest) or _partition_tickers(root)
    expected_tickers = sorted(
        {
            str(ticker).upper()
            for ticker in (active_tickers or manifest_tickers)
            if str(ticker).strip()
        }
    )
    if not expected_tickers:
        return {}
    coverage_rows: list[dict[str, object]] = []
    issues: list[str] = []
    checked_values: list[datetime] = []
    missing_tickers: list[str] = []
    for ticker in expected_tickers:
        row = coverage.get(_coverage_key(ticker, as_of))
        if row and _stock_trade_coverage_row_usable(row):
            normalized = dict(row)
            normalized["ticker"] = ticker
            normalized.setdefault("trade_date", as_of.isoformat())
            coverage_rows.append(normalized)
            checked_at = _parse_datetime(
                normalized.get("updated_at") or normalized.get("fetched_at")
            )
            if checked_at is not None:
                checked_values.append(_ensure_utc(checked_at))
            continue
        if row and str(row.get("coverage_status") or row.get("status") or "").lower() == "failed":
            failed = dict(row)
            failed["ticker"] = ticker
            failed.setdefault("trade_date", as_of.isoformat())
            coverage_rows.append(failed)
            issues.append(f"{ticker} has failed stock-trade coverage for {as_of.isoformat()}")
            continue
        missing_tickers.append(ticker)
    parquet_counts = _stock_trade_parquet_row_counts(root, missing_tickers, as_of=as_of)
    parquet_checked_at = (
        _parse_datetime(stock_manifest.get("fetched_at"))
        or _parse_datetime(stock_manifest.get("max_timestamp_as_of"))
    )
    for ticker in missing_tickers:
        row_count = parquet_counts.get(ticker, 0)
        if row_count > 0:
            normalized = {
                "ticker": ticker,
                "trade_date": as_of.isoformat(),
                "coverage_status": "partial_usable",
                "downloaded_row_count": row_count,
                "pages_downloaded": 1,
                "order": "desc",
                "row_count_verified": False,
                "proof_source": "stock_trades_parquet_rows",
                "updated_at": parquet_checked_at.isoformat()
                if parquet_checked_at is not None
                else "",
            }
            coverage_rows.append(normalized)
            if parquet_checked_at is not None:
                checked_values.append(_ensure_utc(parquet_checked_at))
            continue
        issues.append(f"{ticker} has no usable stock-trade coverage for {as_of.isoformat()}")
    if not coverage_rows:
        return {}
    checked_at = (
        max(checked_values)
        if checked_values
        else _parse_datetime(stock_manifest.get("fetched_at"))
        or _parse_datetime(stock_manifest.get("max_timestamp_as_of"))
    )
    if checked_at is None:
        return {}
    usable_tickers = sorted(
        {
            str(row.get("ticker")).upper()
            for row in coverage_rows
            if _stock_trade_live_coverage_row_usable(row)
            and _stock_trade_live_coverage_row_fresh(
                row,
                now=checked_at,
                fallback_checked_at=checked_at,
            )
        }
    )
    failed_tickers = sorted(
        {
            str(row.get("ticker")).upper()
            for row in coverage_rows
            if str(row.get("coverage_status") or row.get("status") or "").lower()
            == "failed"
        }
    )
    partial_tickers = sorted(
        set(expected_tickers).difference(usable_tickers).difference(failed_tickers)
    )
    coverage_pct = round(_coverage(len(usable_tickers), len(expected_tickers)) * PERCENT_SCALE)
    lane_window = _mapping(superseded_manifest.get("window"))
    lane_window_text = (
        f"{lane_window.get('start', 'unknown')} to {lane_window.get('end', 'unknown')}"
    )
    parquet_proof_count = sum(
        1
        for row in coverage_rows
        if str(row.get("proof_source") or "") == "stock_trades_parquet_rows"
    )
    proof_detail = (
        "Proof came from stock_trades coverage metadata because the latest "
        f"massive_live_trade_slices lane manifest covers {lane_window_text}, "
        f"not {as_of.isoformat()}."
    )
    if parquet_proof_count:
        proof_detail += (
            f" {parquet_proof_count} ticker(s) used parquet row proof because "
            "the coverage metadata was also older than the readiness date."
        )
    status = "partial_usable" if usable_tickers else "partial"
    if not partial_tickers and not failed_tickers:
        status = "partial_usable"
    return {
        "lane_id": MASSIVE_LIVE_TRADE_LANE_ID,
        "label": "Massive Live Trade Slices",
        "manifest": {
            **dict(stock_manifest),
            "status": status,
            "coverage_pct": coverage_pct,
            "coverage": coverage_rows,
            "issues": issues,
            "proof_source": "stock_trades_coverage_metadata",
            "proof_detail": proof_detail,
        },
        "progress": {},
        "progress_row": {},
        "status": status,
        "fetched_at": checked_at.isoformat(),
        "coverage_pct": coverage_pct,
        "tickers": expected_tickers,
        "usable_tickers": usable_tickers,
        "failed_tickers": failed_tickers,
        "partial_tickers": partial_tickers,
        "partial_source_tickers": sorted(
            {
                str(row.get("ticker")).upper()
                for row in coverage_rows
                if _stock_trade_live_coverage_row_usable(row)
                and not _stock_trade_live_coverage_row_complete(row)
            }
        ),
        "issues": issues,
        "row_count": _int_value(stock_manifest.get("row_count")),
        "proof_source": "stock_trades_coverage_metadata",
        "proof_detail": proof_detail,
    }


def _stock_trade_raw_lane_snapshot(
    lane_id: str,
    *,
    label: str,
    data_refresh: Mapping[str, object],
    manifest_root: Path,
    parquet_root: Path | None = None,
    active_tickers: set[str] | None = None,
    as_of: date,
    now: datetime,
    missing_is_snapshot: bool = False,
) -> Mapping[str, object]:
    if lane_id == MASSIVE_LIVE_TRADE_LANE_ID:
        return _stock_trade_live_lane_snapshot(
            data_refresh,
            manifest_root=manifest_root,
            parquet_root=parquet_root,
            active_tickers=active_tickers,
            as_of=as_of,
            now=now,
        )
    manifest = _read_json_object(manifest_root / "massive_lanes" / f"{lane_id}.json")
    if not manifest:
        if missing_is_snapshot or (manifest_root / "massive_lanes").exists():
            return _missing_lane_snapshot(lane_id, label=label)
        return {}
    if not _lane_manifest_covers_as_of(manifest, as_of):
        return _out_of_window_lane_snapshot(
            lane_id,
            label=label,
            manifest=manifest,
            as_of=as_of,
        )
    progress_row = next(
        (
            row
            for row in _sequence_mappings(data_refresh.get("massive_lanes"))
            if str(row.get("lane_id")) == lane_id
        ),
        {},
    )
    tickers = sorted(
        {
            str(ticker).upper()
            for ticker in _list_field(manifest, "tickers")
            if str(ticker).strip()
        }
    )
    coverage = [
        row
        for row in _sequence_mappings(manifest.get("coverage"))
        if str(row.get("ticker") or "").strip()
    ]
    fallback_checked_at = _parse_datetime(manifest.get("fetched_at"))
    usable = sorted(
        {
            str(row.get("ticker")).upper()
            for row in coverage
            if _stock_trade_live_coverage_row_usable(row)
            and _stock_trade_live_coverage_row_fresh(
                row,
                now=now,
                fallback_checked_at=fallback_checked_at,
            )
        }
    )
    if not coverage and tickers and str(manifest.get("status") or "").lower() == "complete":
        usable = tickers
    failed = sorted(
        {
            str(row.get("ticker")).upper()
            for row in coverage
            if str(row.get("coverage_status") or row.get("status") or "").lower()
            == "failed"
        }
    )
    partial_source = sorted(
        {
            str(row.get("ticker")).upper()
            for row in coverage
            if _stock_trade_live_coverage_row_usable(row)
            and not _stock_trade_live_coverage_row_complete(row)
        }
    )
    partial = sorted(set(tickers).difference(usable).difference(failed))
    fetched_at = str(manifest.get("fetched_at") or progress_row.get("updated_at") or "")
    return {
        "lane_id": lane_id,
        "label": label,
        "manifest": manifest,
        "progress": {},
        "progress_row": progress_row,
        "status": str(manifest.get("status") or progress_row.get("state") or "unknown"),
        "fetched_at": fetched_at,
        "coverage_pct": _int_value(manifest.get("coverage_pct")),
        "tickers": tickers,
        "usable_tickers": usable,
        "failed_tickers": failed,
        "partial_tickers": partial,
        "partial_source_tickers": partial_source,
        "issues": _list_field(manifest, "issues"),
        "row_count": _int_value(manifest.get("row_count")),
    }


def _missing_lane_snapshot(lane_id: str, *, label: str) -> Mapping[str, object]:
    return {
        "lane_id": lane_id,
        "label": label,
        "manifest": {},
        "status": "missing_manifest",
        "fetched_at": "",
        "coverage_pct": 0,
        "tickers": [],
        "usable_tickers": [],
        "failed_tickers": [],
        "partial_tickers": [],
        "partial_source_tickers": [],
        "issues": [f"{lane_id} lane manifest is missing"],
        "row_count": 0,
    }


def _out_of_window_lane_snapshot(
    lane_id: str,
    *,
    label: str,
    manifest: Mapping[str, object],
    as_of: date,
) -> Mapping[str, object]:
    return {
        "lane_id": lane_id,
        "label": label,
        "manifest": manifest,
        "status": "out_of_window",
        "fetched_at": str(manifest.get("fetched_at") or ""),
        "coverage_pct": _int_value(manifest.get("coverage_pct")),
        "tickers": _list_field(manifest, "tickers"),
        "usable_tickers": [],
        "failed_tickers": [],
        "partial_tickers": [],
        "partial_source_tickers": [],
        "issues": [f"{lane_id} lane manifest does not cover {as_of.isoformat()}"],
        "row_count": _int_value(manifest.get("row_count")),
    }


def _daily_bar_status_manifest(
    manifest: Mapping[str, object],
    daily_bar_lane: Mapping[str, object],
) -> Mapping[str, object]:
    if not daily_bar_lane:
        return manifest
    lane_manifest = _mapping(daily_bar_lane.get("manifest"))
    window = _mapping(lane_manifest.get("window"))
    window_end = str(window.get("end") or "")
    status_manifest = dict(manifest)
    if window_end:
        status_manifest["max_timestamp_as_of"] = f"{window_end}T00:00:00+00:00"
    status_manifest["row_count"] = _int_value(
        lane_manifest.get("row_count"),
    ) or _int_value(manifest.get("row_count"))
    status_manifest["issues"] = _list_field(lane_manifest, "issues")
    status_manifest["tickers"] = list(_daily_bar_lane_tickers(daily_bar_lane))
    return status_manifest


def _stock_trade_status_manifest(
    manifest: Mapping[str, object],
    live_trade_lane: Mapping[str, object],
) -> Mapping[str, object]:
    if not live_trade_lane:
        return manifest
    lane_manifest = _mapping(live_trade_lane.get("manifest"))
    fetched_at = str(live_trade_lane.get("fetched_at") or "")
    status_manifest = dict(manifest)
    status_manifest["max_timestamp_as_of"] = fetched_at or manifest.get("max_timestamp_as_of")
    status_manifest["row_count"] = _int_value(
        lane_manifest.get("row_count"),
    ) or _int_value(manifest.get("row_count"))
    status_manifest["issues"] = _list_field(lane_manifest, "issues")
    status_manifest["tickers"] = list(_stock_trade_lane_tickers(live_trade_lane))
    return status_manifest


def _daily_bar_lane_source_health(
    daily_bar_lane: Mapping[str, object],
    *,
    now: datetime,
) -> Mapping[str, object]:
    if not daily_bar_lane:
        return {}
    lane_status = str(daily_bar_lane.get("status") or "").lower()
    if lane_status in {"missing_manifest", "out_of_window"}:
        return {
            "source": "daily-market-bars",
            "status": "UNAVAILABLE" if lane_status == "missing_manifest" else "STALE",
            "freshness": "UNAVAILABLE" if lane_status == "missing_manifest" else "STALE",
            "checked_at": "not checked",
            "last_success_at": "not recorded",
            "max_age_seconds": MASSIVE_DAILY_BARS_SLA_SECONDS,
            "detail": "; ".join(str(item) for item in _list_field(daily_bar_lane, "issues"))
            or f"{MASSIVE_DAILY_BARS_LANE_ID} lane manifest is not usable.",
        }
    checked_at = _parse_datetime(daily_bar_lane.get("fetched_at"))
    if checked_at is None:
        return {
            "source": "daily-market-bars",
            "status": "STALE",
            "freshness": "UNKNOWN",
            "checked_at": "not checked",
            "last_success_at": "not recorded",
            "max_age_seconds": MASSIVE_DAILY_BARS_SLA_SECONDS,
        }
    age_seconds = int((_ensure_utc(now) - checked_at).total_seconds())
    if age_seconds > MASSIVE_DAILY_BARS_SLA_SECONDS and not (
        _daily_bar_lane_current_for_latest_completed_session(checked_at, now)
    ):
        freshness = "STALE"
        status = "STALE"
    else:
        freshness = "FRESH"
        status = "HEALTHY"
    missing_active_tickers = [
        str(ticker).upper()
        for ticker in _list_field(daily_bar_lane, "missing_active_tickers")
        if str(ticker).strip()
    ]
    active_usable = _int_value(daily_bar_lane.get("active_usable_ticker_count"))
    active_expected = _int_value(daily_bar_lane.get("active_expected_ticker_count"))
    active_coverage_pct = _int_value(daily_bar_lane.get("active_coverage_pct"))
    active_coverage_detail = ""
    if missing_active_tickers and status == "HEALTHY":
        status = "DEGRADED"
        active_coverage_detail = (
            f" Active-universe coverage is {active_usable}/{active_expected} "
            f"active ticker(s) ({active_coverage_pct}%); missing "
            f"{_ticker_list_preview(missing_active_tickers)}."
        )
    checked = checked_at.isoformat()
    return {
        "source": "daily-market-bars",
        "status": status,
        "freshness": freshness,
        "checked_at": checked,
        "last_success_at": checked,
        "max_age_seconds": MASSIVE_DAILY_BARS_SLA_SECONDS,
        "missing_active_tickers": missing_active_tickers,
        "active_usable_ticker_count": active_usable,
        "active_expected_ticker_count": active_expected,
        "active_coverage_pct": active_coverage_pct,
        "detail": (
            f"{MASSIVE_DAILY_BARS_LANE_ID} lane is {status} / {freshness}; "
            "manifest checked "
            f"{age_seconds}s ago."
            f"{active_coverage_detail}"
        ),
    }


def _stock_trade_lane_source_health(
    live_trade_lane: Mapping[str, object],
    *,
    now: datetime,
) -> Mapping[str, object]:
    if not live_trade_lane:
        return {}
    lane_id = str(live_trade_lane.get("lane_id") or MASSIVE_LIVE_TRADE_LANE_ID)
    lane_status = str(live_trade_lane.get("status") or "").lower()
    if lane_status in {"missing_manifest", "out_of_window"}:
        return {
            "source": "massive-stock-trades",
            "status": "UNAVAILABLE" if lane_status == "missing_manifest" else "STALE",
            "freshness": "UNAVAILABLE" if lane_status == "missing_manifest" else "STALE",
            "checked_at": "not checked",
            "last_success_at": "not recorded",
            "max_age_seconds": MASSIVE_LIVE_TRADE_SLA_SECONDS,
            "detail": "; ".join(str(item) for item in _list_field(live_trade_lane, "issues"))
            or f"{lane_id} lane manifest is not usable.",
        }
    checked_at = _parse_datetime(live_trade_lane.get("fetched_at"))
    if checked_at is None:
        return {
            "source": "massive-stock-trades",
            "status": "STALE",
            "freshness": "UNKNOWN",
            "checked_at": "not checked",
            "last_success_at": "not recorded",
        }
    age_seconds = int((_ensure_utc(now) - checked_at).total_seconds())
    partial_ticker_count = len(_list_field(live_trade_lane, "partial_tickers"))
    partial_source_count = len(_list_field(live_trade_lane, "partial_source_tickers"))
    failed_ticker_count = len(_list_field(live_trade_lane, "failed_tickers"))
    usable_ticker_count = len(_list_field(live_trade_lane, "usable_tickers"))
    ticker_count = len(_list_field(live_trade_lane, "tickers"))
    closed_market_current = _closed_market_live_trade_lane_current(checked_at, now)
    latest_slice_ready = (
        ticker_count > 0
        and usable_ticker_count >= ticker_count
        and partial_ticker_count == 0
        and failed_ticker_count == 0
    )
    if age_seconds > MASSIVE_LIVE_TRADE_SLA_SECONDS and not closed_market_current:
        freshness = "STALE"
        status = "STALE"
    elif latest_slice_ready:
        freshness = "FRESH"
        status = "HEALTHY"
    elif partial_ticker_count or partial_source_count or failed_ticker_count:
        freshness = "PARTIAL"
        status = "DEGRADED"
    else:
        freshness = "FRESH"
        status = "HEALTHY"
    checked = checked_at.isoformat()
    proof_detail = str(live_trade_lane.get("proof_detail") or "")
    return {
        "source": "massive-stock-trades",
        "status": status,
        "freshness": freshness,
        "checked_at": checked,
        "last_success_at": checked,
        "max_age_seconds": MASSIVE_LIVE_TRADE_SLA_SECONDS,
        "detail": (
            f"{lane_id} lane is {status} / {freshness}; "
            f"manifest checked {age_seconds}s ago; "
            f"{usable_ticker_count}/{ticker_count} ticker(s) usable, "
            f"{partial_ticker_count} missing/partial, {partial_source_count} partial slices, "
            f"{failed_ticker_count} failed."
            + (
                " Partial slices are acceptable for the live latest-slice lane when "
                "every active ticker has a usable descending page; full-depth tape "
                "repair is owned by massive_backtest_trade_tape."
                if latest_slice_ready and partial_source_count
                else ""
            )
            + (
                " Closed-market freshness uses the latest completed trading session."
                if closed_market_current
                else ""
            )
            + (f" {proof_detail}" if proof_detail else "")
        ),
    }


def _context_manifest_source_health(
    dataset: str,
    *,
    manifest_root: Path,
    now: datetime,
) -> Mapping[str, object]:
    manifest = _read_json_object(manifest_root / f"{dataset}.json")
    if not manifest:
        return {}
    source = DATASET_SOURCE.get(dataset)
    if source is None:
        return {}
    checked_at = _parse_datetime(manifest.get("fetched_at"))
    source_tier = CONTEXT_SOURCE_TIERS.get(dataset, "CONTEXT")
    if checked_at is None:
        return {}
    current = _ensure_utc(now)
    last_success = _parse_datetime(manifest.get("max_timestamp_as_of")) or checked_at
    stale_after = _parse_datetime(manifest.get("stale_after"))
    max_age_seconds = SOURCE_HEALTH_MAX_AGE_BY_SOURCE.get(
        source,
        SOURCE_HEALTH_MAX_AGE_SECONDS,
    )
    stale_deadline = stale_after or checked_at + timedelta(seconds=max_age_seconds)
    age_seconds = max(int((current - checked_at).total_seconds()), 0)
    lag_seconds = max(int((current - last_success).total_seconds()), 0)
    fresh = current <= stale_deadline
    status = "HEALTHY" if fresh else "DEGRADED"
    freshness = "FRESH" if fresh else "AGING"
    return {
        "source": source,
        "source_tier": source_tier,
        "status": status,
        "freshness": freshness,
        "checked_at": checked_at.isoformat(),
        "last_success_at": last_success.isoformat(),
        "observed_lag_seconds": lag_seconds,
        "error_count": 0,
        "reliability_score": 1.0 if fresh else 0.75,
        "rate_limit_reset_at": None,
        "max_age_seconds": max_age_seconds,
        "notes": [
            f"{dataset}: {_int_value(manifest.get('row_count'))} rows",
            f"manifest checked {age_seconds}s ago",
        ],
        "detail": (
            f"{dataset} manifest is {status} / {freshness}; "
            f"manifest checked {age_seconds}s ago."
        ),
    }


def _daily_bar_lane_tickers(daily_bar_lane: Mapping[str, object]) -> set[str]:
    return {
        str(ticker).upper()
        for ticker in _list_field(daily_bar_lane, "tickers")
        if str(ticker).strip()
    }


def _stock_trade_lane_tickers(live_trade_lane: Mapping[str, object]) -> set[str]:
    return {
        str(ticker).upper()
        for ticker in _list_field(live_trade_lane, "tickers")
        if str(ticker).strip()
    }


def _stock_trade_lane_usable_tickers(live_trade_lane: Mapping[str, object]) -> set[str]:
    return {
        str(ticker).upper()
        for ticker in _list_field(live_trade_lane, "usable_tickers")
        if str(ticker).strip()
    }


def _stock_trade_lane_partial_count(live_trade_lane: Mapping[str, object]) -> int:
    return len(_list_field(live_trade_lane, "partial_tickers"))


def _stock_trade_live_coverage_row_usable(row: Mapping[str, object]) -> bool:
    status = str(row.get("coverage_status") or row.get("status") or "").lower()
    if _stock_trade_live_coverage_row_complete(row):
        return True
    if status not in {"complete", "partial", "partial_usable", "ready", "usable"}:
        return False
    if status == "partial_usable":
        return True
    if status == "complete" and (
        row.get("resume_cursor") not in {None, ""}
        or row.get("stop_reason") not in {None, ""}
    ):
        return False
    rows = max(
        _int_value(row.get("downloaded_row_count")),
        _int_value(row.get("rows_written")),
    )
    pages = _int_value(row.get("pages_downloaded"))
    order = str(row.get("order") or "").lower()
    return rows > 0 and pages > 0 and order == "desc"


def _stock_trade_live_coverage_row_complete(row: Mapping[str, object]) -> bool:
    status = str(row.get("coverage_status") or row.get("status") or "").lower()
    return (
        row.get("complete") is True or status == "complete"
    ) and row.get("row_count_verified") is not False and _stock_trade_live_row_has_prints(row)


def _stock_trade_live_row_has_prints(row: Mapping[str, object]) -> bool:
    count_fields = (
        "downloaded_row_count",
        "rows_written",
        "last_page_results_count",
        "row_count",
    )
    if not any(field in row for field in count_fields):
        return True
    return max(_int_value(row.get(field)) for field in count_fields) > 0


def _stock_trade_live_coverage_row_fresh(
    row: Mapping[str, object],
    *,
    now: datetime,
    fallback_checked_at: datetime | None,
) -> bool:
    row_checked_at = _parse_datetime(row.get("updated_at") or row.get("fetched_at"))
    checked_at = row_checked_at or fallback_checked_at
    if checked_at is None:
        return False
    current = _ensure_utc(now)
    checked_at = _ensure_utc(checked_at)
    age_seconds = (current - checked_at).total_seconds()
    if age_seconds <= MASSIVE_LIVE_TRADE_SLA_SECONDS:
        return True
    if _closed_market_live_trade_lane_current(checked_at, current):
        return True
    if row_checked_at is None or fallback_checked_at is None:
        return False
    row_checked_at = _ensure_utc(row_checked_at)
    fallback_checked_at = _ensure_utc(fallback_checked_at)
    sweep_seconds = (fallback_checked_at - row_checked_at).total_seconds()
    fallback_age_seconds = (current - fallback_checked_at).total_seconds()
    return (
        0 <= sweep_seconds <= MASSIVE_LIVE_TRADE_SWEEP_GRACE_SECONDS
        and fallback_age_seconds <= MASSIVE_LIVE_TRADE_SLA_SECONDS
    )


def _closed_market_live_trade_lane_current(checked_at: datetime, now: datetime) -> bool:
    """Treat the last completed session as current when no tape updates are expected."""
    session = _current_market_session(_ensure_utc(now))
    if bool(getattr(session, "is_open_for_extended", False)):
        return False
    return checked_at.date() >= _latest_completed_market_date(_ensure_utc(now))


def _daily_bar_lane_current_for_latest_completed_session(
    checked_at: datetime,
    now: datetime,
) -> bool:
    """Treat daily bars as current until the next completed session can exist."""
    return checked_at.date() >= _latest_completed_market_date(_ensure_utc(now))


def _current_market_session(now: datetime) -> object:
    try:
        from data_refresh.market_calendar import classify_market_session
    except ModuleNotFoundError:
        return _FallbackMarketSession(now)
    return classify_market_session(now)


def _market_session_phase(session: object | None) -> str:
    return str(getattr(session, "phase", "unknown") or "unknown")


def _market_session_date(session: object | None) -> date:
    value = getattr(session, "market_date", None)
    return value if isinstance(value, date) else date.today()


def _premarket_lane_required_now(session: object | None) -> bool:
    return _market_session_phase(session) == "pre_market"


def _next_pre_market_label(now: datetime) -> str:
    try:
        from data_refresh.market_calendar import next_pre_market_start
    except ModuleNotFoundError:
        return "the next 04:00 ET session"
    return next_pre_market_start(now).isoformat()


class _FallbackMarketSession:
    phase = "unknown"
    is_open_for_extended = False

    def __init__(self, now: datetime) -> None:
        self.market_date = _as_eastern(now).date()


def _lane_manifest_covers_as_of(manifest: Mapping[str, object], as_of: date) -> bool:
    window = _mapping(manifest.get("window"))
    start = _parse_date(window.get("start"))
    end = _parse_date(window.get("end"))
    if start is None or end is None:
        return False
    return start <= as_of <= end


def _stock_trade_manifest_covers_as_of(
    manifest: Mapping[str, object],
    as_of: date,
) -> bool:
    date_range = _mapping(manifest.get("date_range"))
    start = _parse_date(date_range.get("start"))
    end = _parse_date(date_range.get("end"))
    if start is not None and end is not None:
        return start <= as_of <= end
    max_timestamp = _parse_datetime(manifest.get("max_timestamp_as_of"))
    return max_timestamp is not None and _ensure_utc(max_timestamp).date() >= as_of


def _lane_manifest_reaches_as_of(manifest: Mapping[str, object], as_of: date) -> bool:
    window = _mapping(manifest.get("window"))
    end = _parse_date(window.get("end"))
    return end is not None and end >= as_of


def _dataset_tickers(
    dataset: str,
    manifest: Mapping[str, object],
    parquet_root: Path,
    *,
    as_of: date,
) -> set[str]:
    if dataset == "stock_trades":
        coverage_tickers = _stock_trade_complete_tickers(manifest, parquet_root, as_of=as_of)
        if coverage_tickers is not None:
            return coverage_tickers
    tickers = _manifest_tickers(manifest)
    if tickers:
        return tickers
    path_value = manifest.get("path")
    if not isinstance(path_value, str) or not path_value.strip():
        return set()
    return _partition_tickers(parquet_root / path_value)


def _dataset_coverage_as_of(
    dataset: str,
    *,
    as_of: date,
    now: datetime,
    dynamic: bool,
) -> date:
    if dataset != "stock_trades" or not dynamic:
        return as_of
    try:
        from data_refresh.market_calendar import classify_market_session
    except ModuleNotFoundError:
        return as_of
    session = classify_market_session(now)
    if session.is_trading_day and session.phase != "overnight_before_pre_market":
        return session.market_date
    return as_of


def _stock_trade_complete_tickers(
    manifest: Mapping[str, object],
    parquet_root: Path,
    *,
    as_of: date,
) -> set[str] | None:
    path_value = manifest.get("path")
    root = parquet_root / str(path_value or "stock_trades")
    coverage = _load_stock_trade_coverage_metadata(root)
    if not coverage:
        return None
    tickers = _manifest_tickers(manifest) or _partition_tickers(root)
    complete: set[str] = set()
    for ticker in tickers:
        row = coverage.get(_coverage_key(ticker, as_of))
        if row and str(row.get("coverage_status")) == "complete":
            complete.add(ticker)
    return complete


def _stock_trade_usable_tickers(
    manifest: Mapping[str, object],
    parquet_root: Path,
    *,
    as_of: date,
) -> set[str]:
    path_value = manifest.get("path")
    root = parquet_root / str(path_value or "stock_trades")
    coverage = _load_stock_trade_coverage_metadata(root)
    if not coverage:
        return _manifest_tickers(manifest) or _partition_tickers(root)
    tickers = _manifest_tickers(manifest) or _partition_tickers(root)
    usable: set[str] = set()
    for ticker in tickers:
        row = coverage.get(_coverage_key(ticker, as_of), {})
        if _stock_trade_coverage_row_usable(row):
            usable.add(ticker)
    return usable


def _stock_trade_parquet_row_counts(
    root: Path,
    tickers: Sequence[str],
    *,
    as_of: date,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not tickers:
        return counts
    try:
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ImportError:
        pc = None
        pq = None
    for ticker in tickers:
        normalized_ticker = str(ticker).upper()
        path = root / f"ticker={normalized_ticker}" / f"year={as_of.year}" / "trades.parquet"
        if not path.exists():
            continue
        try:
            if pc is not None and pq is not None:
                table = pq.ParquetFile(path).read(columns=["trade_date"])
                row_count = int(pc.sum(pc.equal(table["trade_date"], as_of)).as_py() or 0)
            else:
                frame = pd.read_parquet(path, columns=["trade_date"])
                if "trade_date" not in frame:
                    continue
                trade_dates = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date
                row_count = int((trade_dates == as_of).sum())
        except Exception:
            continue
        if row_count > 0:
            counts[normalized_ticker] = row_count
    return counts


def _stock_trade_coverage_row_usable(row: Mapping[str, object]) -> bool:
    if not row:
        return False
    status = str(row.get("coverage_status") or row.get("status") or "").lower()
    if status in {"complete", "partial_usable"} or row.get("complete") is True:
        return True
    downloaded = _int_value(row.get("downloaded_row_count"))
    pages = _int_value(row.get("pages_downloaded"))
    order = str(row.get("order") or "").lower()
    return downloaded > 0 and pages > 0 and order == "desc"


def _stock_trade_partial_count(
    manifest: Mapping[str, object],
    parquet_root: Path,
    *,
    as_of: date,
) -> int:
    path_value = manifest.get("path")
    root = parquet_root / str(path_value or "stock_trades")
    coverage = _load_stock_trade_coverage_metadata(root)
    if not coverage:
        return 0
    tickers = _manifest_tickers(manifest) or _partition_tickers(root)
    return sum(
        1
        for ticker in tickers
        if str(
            coverage.get(_coverage_key(ticker, as_of), {}).get("coverage_status")
        )
        == "partial"
    )


def _load_stock_trade_coverage_metadata(root: Path) -> Mapping[str, Mapping[str, object]]:
    path = root / "_coverage.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    rows = payload.get("ticker_days")
    if not isinstance(rows, Mapping):
        return {}
    return {
        str(key): cast(Mapping[str, object], value)
        for key, value in rows.items()
        if isinstance(value, Mapping)
    }


def _coverage_key(ticker: str, trade_date: date) -> str:
    return f"{ticker.upper()}|{trade_date.isoformat()}"


def _manifest_tickers(manifest: Mapping[str, object]) -> set[str]:
    values = manifest.get("tickers")
    if not isinstance(values, list):
        return set()
    return {str(value).upper() for value in values if str(value).strip()}


def _partition_tickers(path: Path) -> set[str]:
    if not path.is_dir():
        return set()
    tickers: set[str] = set()
    for item in path.iterdir():
        if not item.is_dir():
            continue
        name = item.name
        if not name.startswith("ticker="):
            continue
        ticker = name.split("=", 1)[1].strip().upper()
        if ticker:
            tickers.add(ticker)
    return tickers


def _config_date(config: Mapping[str, object], key: str, *, fallback: date) -> date:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError:
        return fallback


def _config_date_valid(config: Mapping[str, object], key: str) -> bool:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _effective_as_of(configured_as_of: date, *, now: datetime, dynamic: bool) -> date:
    if not dynamic:
        return configured_as_of
    completed = _latest_completed_market_date(now)
    return max(configured_as_of, completed)


def _latest_completed_market_date(now: datetime) -> date:
    try:
        from data_refresh.market_calendar import (
            classify_market_session,
            previous_trading_day,
        )
    except ModuleNotFoundError:
        eastern = _as_eastern(now)
        if eastern.time().hour < 16:
            return _previous_weekday(eastern.date())
        return eastern.date() if eastern.date().weekday() < WEEKEND_START else _previous_weekday(eastern.date())
    session = classify_market_session(now)
    if not session.is_trading_day:
        return previous_trading_day(session.market_date)
    if session.phase in {"pre_market", "regular_market", "overnight_before_pre_market"}:
        return previous_trading_day(session.market_date)
    return session.market_date


def _previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= WEEKEND_START:
        candidate -= timedelta(days=1)
    return candidate


def _as_eastern(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(EASTERN)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _read_json_object(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return cast(Mapping[str, object], payload) if isinstance(payload, Mapping) else {}


def _read_json_list(path: Path) -> list[Mapping[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [cast(Mapping[str, object], item) for item in payload if isinstance(item, Mapping)]


def _strings(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    values = payload.get(key)
    if not isinstance(values, list):
        return ()
    return tuple(str(item) for item in values if isinstance(item, str) and item.strip())


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence_mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]


def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return 0


def _number_value(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return 0.0
