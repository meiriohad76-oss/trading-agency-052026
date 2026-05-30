from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from data_refresh.extraction_plan import ExtractionDecision
from data_refresh.market_calendar import MarketSession, previous_trading_day
from data_refresh.types import RefreshBatchConfig

ACTIVE_TRADE_PHASES = ("pre_market", "regular_market", "after_hours")
PREMARKET_PHASES = ("pre_market",)
REGULAR_MARKET_PHASES = ("regular_market",)
MARKET_HOURS_PHASES = ("pre_market", "regular_market")
QUIET_REPAIR_PHASES = (
    "overnight_after_hours",
    "overnight_before_pre_market",
    "closed",
    "closed_weekend",
    "closed_holiday",
)
DAILY_BAR_PHASES = (
    "after_hours",
    "overnight_after_hours",
    "overnight_before_pre_market",
    "closed",
    "closed_weekend",
    "closed_holiday",
)
REQUESTING_ACQUISITION_MODES = {"massive_api"}
LIVE_OPERATIONAL_FRESHNESS_REQUIREMENT_SECONDS = 30 * 60


@dataclass(frozen=True)
class MassiveRawLanePolicy:
    lane_id: str
    label: str
    purpose: str
    dataset: str
    raw_source_dataset: str
    endpoint_family: str
    acquisition_mode: str
    command_profile: str
    consumer_signal_lanes: tuple[str, ...]
    active_phases: tuple[str, ...]
    ticker_tier_active: str
    ticker_tier_quiet: str
    freshness_requirement_seconds: int | None
    blocks_execution: bool
    default_priority: int
    default_cadence_minutes: int | None
    default_max_tickers_per_batch: int | None
    quiet_priority: int
    quiet_cadence_minutes: int | None
    quiet_max_tickers_per_batch: int | None
    request_budget_label: str
    max_requests_per_cycle: int | None
    storage_manifest: str
    requires_raw_lanes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MassiveRawLaneDecision:
    lane_id: str
    label: str
    purpose: str
    dataset: str
    raw_source_dataset: str
    endpoint_family: str
    acquisition_mode: str
    command_profile: str
    consumer_signal_lanes: tuple[str, ...]
    tickers: tuple[str, ...]
    batch_action: str
    priority: int
    cadence_minutes: int | None
    max_tickers_per_batch: int | None
    ticker_tier: str
    start: str | None
    end: str | None
    window_label: str
    extraction_action: str
    extraction_reason: str
    freshness_requirement_seconds: int | None
    blocks_execution: bool
    required: bool
    status_hint: str
    status_class: str
    reason: str
    request_budget_label: str
    max_requests_per_cycle: int | None
    storage_manifest: str
    requires_raw_lanes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "lane_kind": "raw_acquisition",
            "lane_id": self.lane_id,
            "label": self.label,
            "purpose": self.purpose,
            "dataset": self.dataset,
            "raw_source_dataset": self.raw_source_dataset,
            "endpoint_family": self.endpoint_family,
            "acquisition_mode": self.acquisition_mode,
            "command_profile": self.command_profile,
            "consumer_signal_lanes": list(self.consumer_signal_lanes),
            "signal_lanes": list(self.consumer_signal_lanes),
            "tickers": list(self.tickers),
            "ticker_count": len(self.tickers),
            "batch_action": self.batch_action,
            "priority": self.priority,
            "cadence_minutes": self.cadence_minutes,
            "max_tickers_per_batch": self.max_tickers_per_batch,
            "ticker_tier": self.ticker_tier,
            "start": self.start,
            "end": self.end,
            "window_label": self.window_label,
            "extraction_action": self.extraction_action,
            "extraction_reason": self.extraction_reason,
            "freshness_requirement_seconds": self.freshness_requirement_seconds,
            "blocks_execution": self.blocks_execution,
            "required": self.required,
            "status_hint": self.status_hint,
            "status_class": self.status_class,
            "reason": self.reason,
            "request_budget_label": self.request_budget_label,
            "max_requests_per_cycle": self.max_requests_per_cycle,
            "storage_manifest": self.storage_manifest,
            "requires_raw_lanes": list(self.requires_raw_lanes),
            "creates_massive_request": self.acquisition_mode in REQUESTING_ACQUISITION_MODES,
        }


@dataclass(frozen=True)
class DerivedSignalLaneDecision:
    signal_lane: str
    label: str
    requires_raw_lanes: tuple[str, ...]
    batch_action: str
    status_hint: str
    status_class: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "lane_kind": "derived_signal",
            "signal_lane": self.signal_lane,
            "lane": self.signal_lane,
            "label": self.label,
            "requires_raw_lanes": list(self.requires_raw_lanes),
            "batch_action": self.batch_action,
            "status_hint": self.status_hint,
            "status_class": self.status_class,
            "reason": self.reason,
        }


MASSIVE_RAW_LANE_POLICIES: tuple[MassiveRawLanePolicy, ...] = (
    MassiveRawLanePolicy(
        lane_id="massive_daily_bars",
        label="Massive Daily Bars",
        purpose="Daily OHLCV baseline for returns, technical analysis, and sector regime.",
        dataset="prices_daily",
        raw_source_dataset="prices_daily",
        endpoint_family="grouped_daily_or_aggs",
        acquisition_mode="massive_api",
        command_profile="prices_daily",
        consumer_signal_lanes=("technical_analysis", "abnormal_volume", "sector_momentum"),
        active_phases=DAILY_BAR_PHASES,
        ticker_tier_active="T0/T1/T2",
        ticker_tier_quiet="T0/T1/T2",
        freshness_requirement_seconds=24 * 60 * 60,
        blocks_execution=True,
        default_priority=80,
        default_cadence_minutes=60,
        default_max_tickers_per_batch=None,
        quiet_priority=80,
        quiet_cadence_minutes=60,
        quiet_max_tickers_per_batch=None,
        request_budget_label="1 grouped-daily request per market date",
        max_requests_per_cycle=1,
        storage_manifest="research/data/manifests/massive_lanes/massive_daily_bars.json",
    ),
    MassiveRawLanePolicy(
        lane_id="massive_live_trade_slices",
        label="Massive Live Trade Slices",
        purpose="Current-day latest trade prints for live pressure, trend, and execution gates.",
        dataset="stock_trades",
        raw_source_dataset="stock_trades",
        endpoint_family="trades",
        acquisition_mode="massive_api",
        command_profile="stock_trades_live",
        consumer_signal_lanes=(
            "buy_sell_pressure",
            "block_trade_pressure",
            "unusual_trade_activity",
            "market_flow_trend",
        ),
        active_phases=ACTIVE_TRADE_PHASES,
        ticker_tier_active="T0/T1",
        ticker_tier_quiet="T0/T1/T2",
        freshness_requirement_seconds=LIVE_OPERATIONAL_FRESHNESS_REQUIREMENT_SECONDS,
        blocks_execution=True,
        default_priority=100,
        default_cadence_minutes=5,
        default_max_tickers_per_batch=30,
        quiet_priority=70,
        quiet_cadence_minutes=60,
        quiet_max_tickers_per_batch=50,
        request_budget_label="bounded latest-print pages for active tiers",
        max_requests_per_cycle=30,
        storage_manifest="research/data/manifests/massive_lanes/massive_live_trade_slices.json",
    ),
    MassiveRawLanePolicy(
        lane_id="massive_premarket_trade_slices",
        label="Massive Pre-Market Trade Slices",
        purpose="04:00-09:30 ET activity for pre-market volume, gap, and velocity signals.",
        dataset="stock_trades",
        raw_source_dataset="stock_trades",
        endpoint_family="trades",
        acquisition_mode="massive_api",
        command_profile="stock_trades_premarket",
        consumer_signal_lanes=("pre_market_unusual_activity",),
        active_phases=PREMARKET_PHASES,
        ticker_tier_active="T0/T1",
        ticker_tier_quiet="T0/T1",
        freshness_requirement_seconds=LIVE_OPERATIONAL_FRESHNESS_REQUIREMENT_SECONDS,
        blocks_execution=True,
        default_priority=105,
        default_cadence_minutes=5,
        default_max_tickers_per_batch=30,
        quiet_priority=30,
        quiet_cadence_minutes=240,
        quiet_max_tickers_per_batch=50,
        request_budget_label="bounded latest-print pages during pre-market only",
        max_requests_per_cycle=30,
        storage_manifest="research/data/manifests/massive_lanes/massive_premarket_trade_slices.json",
    ),
    MassiveRawLanePolicy(
        lane_id="massive_block_trade_feed",
        label="Massive Block Trade Feed",
        purpose="Local large-print/off-exchange candidate feed derived from live trade slices.",
        dataset="stock_trades",
        raw_source_dataset="stock_trades",
        endpoint_family="local_trade_derivation",
        acquisition_mode="local_derivation",
        command_profile="derive_block_trades_from_live_slices",
        consumer_signal_lanes=("block_trade_pressure",),
        active_phases=REGULAR_MARKET_PHASES,
        ticker_tier_active="T0/T1",
        ticker_tier_quiet="T0/T1/T2",
        freshness_requirement_seconds=LIVE_OPERATIONAL_FRESHNESS_REQUIREMENT_SECONDS,
        blocks_execution=True,
        default_priority=98,
        default_cadence_minutes=5,
        default_max_tickers_per_batch=15,
        quiet_priority=65,
        quiet_cadence_minutes=60,
        quiet_max_tickers_per_batch=50,
        request_budget_label="0 Massive requests; consumes massive_live_trade_slices",
        max_requests_per_cycle=0,
        storage_manifest="research/data/manifests/massive_lanes/massive_block_trade_feed.json",
        requires_raw_lanes=("massive_live_trade_slices",),
    ),
    MassiveRawLanePolicy(
        lane_id="massive_backtest_trade_tape",
        label="Massive Backtest Trade Tape",
        purpose="Full-depth historical trades for research features and backtesting only.",
        dataset="stock_trades",
        raw_source_dataset="stock_trades",
        endpoint_family="trades",
        acquisition_mode="massive_api",
        command_profile="stock_trades_backfill",
        consumer_signal_lanes=("backtest_feature_builder",),
        active_phases=QUIET_REPAIR_PHASES,
        ticker_tier_active="T3",
        ticker_tier_quiet="T0/T1/T2/T3",
        freshness_requirement_seconds=None,
        blocks_execution=False,
        default_priority=40,
        default_cadence_minutes=None,
        default_max_tickers_per_batch=1,
        quiet_priority=45,
        quiet_cadence_minutes=240,
        quiet_max_tickers_per_batch=1,
        request_budget_label="off-hours full-depth pagination; one ticker batch at a time",
        max_requests_per_cycle=None,
        storage_manifest="research/data/manifests/massive_lanes/massive_backtest_trade_tape.json",
    ),
    MassiveRawLanePolicy(
        lane_id="massive_reference",
        label="Massive Reference",
        purpose="Ticker reference, splits, and corporate actions for symbol hygiene.",
        dataset="reference_data",
        raw_source_dataset="reference_data",
        endpoint_family="reference",
        acquisition_mode="massive_api",
        command_profile="reference_data",
        consumer_signal_lanes=("technical_analysis", "backtest_feature_builder"),
        active_phases=QUIET_REPAIR_PHASES,
        ticker_tier_active="T0/T1/T2/T3",
        ticker_tier_quiet="T0/T1/T2/T3",
        freshness_requirement_seconds=7 * 24 * 60 * 60,
        blocks_execution=False,
        default_priority=35,
        default_cadence_minutes=None,
        default_max_tickers_per_batch=None,
        quiet_priority=35,
        quiet_cadence_minutes=24 * 60,
        quiet_max_tickers_per_batch=None,
        request_budget_label="daily/weekly low-frequency reference pull",
        max_requests_per_cycle=3,
        storage_manifest="research/data/manifests/massive_lanes/massive_reference.json",
    ),
    MassiveRawLanePolicy(
        lane_id="massive_options_flow",
        label="Massive Options Flow",
        purpose="Options volume, open interest, and implied-volatility flow when enabled.",
        dataset="options_chains",
        raw_source_dataset="options_chains",
        endpoint_family="options",
        acquisition_mode="massive_api",
        command_profile="options_flow",
        consumer_signal_lanes=("options_flow", "options_anomaly"),
        active_phases=MARKET_HOURS_PHASES,
        ticker_tier_active="T0/T1",
        ticker_tier_quiet="T0/T1/T2",
        freshness_requirement_seconds=LIVE_OPERATIONAL_FRESHNESS_REQUIREMENT_SECONDS,
        blocks_execution=False,
        default_priority=75,
        default_cadence_minutes=10,
        default_max_tickers_per_batch=10,
        quiet_priority=30,
        quiet_cadence_minutes=None,
        quiet_max_tickers_per_batch=None,
        request_budget_label="options endpoint budget; disabled until provider entitlement is verified",
        max_requests_per_cycle=10,
        storage_manifest="research/data/manifests/massive_lanes/massive_options_flow.json",
    ),
)


DERIVED_SIGNAL_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "buy_sell_pressure": ("massive_live_trade_slices",),
    "block_trade_pressure": ("massive_block_trade_feed", "massive_live_trade_slices"),
    "unusual_trade_activity": ("massive_live_trade_slices",),
    "pre_market_unusual_activity": ("massive_premarket_trade_slices",),
    "market_flow_trend": ("massive_live_trade_slices",),
    "technical_analysis": ("massive_daily_bars",),
    "backtest_feature_builder": ("massive_daily_bars", "massive_backtest_trade_tape"),
    "abnormal_volume": ("massive_daily_bars",),
    "sector_momentum": ("massive_daily_bars",),
    "options_flow": ("massive_options_flow",),
    "options_anomaly": ("massive_options_flow",),
}


def build_massive_orchestration_plan(
    config: RefreshBatchConfig,
    *,
    session: MarketSession,
    extraction_decisions: Sequence[ExtractionDecision],
    runtime_lanes: Sequence[str] = (),
) -> dict[str, object]:
    decision_by_dataset = {decision.dataset: decision for decision in extraction_decisions}
    raw_rows = [
        _raw_lane_decision(
            policy,
            config=config,
            session=session,
            extraction_decision=decision_by_dataset.get(policy.raw_source_dataset),
            runtime_lanes=runtime_lanes,
        ).as_dict()
        for policy in MASSIVE_RAW_LANE_POLICIES
    ]
    derived_rows = [
        _derived_signal_decision(lane, raw_rows).as_dict()
        for lane in sorted(_runtime_derived_lanes(runtime_lanes))
    ]
    return {
        "schema_version": "0.2.0",
        "provider": "massive",
        "market_phase": session.phase,
        "raw_lane_count": len(raw_rows),
        "lane_count": len(raw_rows),
        "derived_signal_lane_count": len(derived_rows),
        "run_now_count": _count_action(raw_rows, "run_now"),
        "deferred_count": _count_action(raw_rows, "defer"),
        "blocked_count": _count_action(raw_rows, "blocked"),
        "disabled_count": _count_action(raw_rows, "disabled"),
        "local_derivation_count": _count_action(raw_rows, "derive_from_raw"),
        "execution_blocking_lane_count": sum(
            1
            for row in raw_rows
            if row.get("blocks_execution") is True
            and row.get("batch_action") in {"run_now", "blocked", "derive_from_raw"}
        ),
        "raw_lanes": sorted(raw_rows, key=_sort_key),
        "lanes": sorted(raw_rows, key=_sort_key),
        "derived_signal_lanes": derived_rows,
        "derived_signal_requirements": {
            lane: list(requirements)
            for lane, requirements in sorted(DERIVED_SIGNAL_REQUIREMENTS.items())
        },
        "detail": _plan_detail(raw_rows, session.phase),
    }


def raw_lanes_for_signal(signal_lane: str) -> tuple[str, ...]:
    return DERIVED_SIGNAL_REQUIREMENTS.get(signal_lane, ())


def _raw_lane_decision(
    policy: MassiveRawLanePolicy,
    *,
    config: RefreshBatchConfig,
    session: MarketSession,
    extraction_decision: ExtractionDecision | None,
    runtime_lanes: Sequence[str],
) -> MassiveRawLaneDecision:
    required = _policy_required(policy, config=config, runtime_lanes=runtime_lanes)
    action, reason = _batch_action_and_reason(
        policy,
        config=config,
        session=session,
        extraction_decision=extraction_decision,
        required=required,
    )
    priority, cadence, batch_size, tier = _lane_cadence(policy, session.phase, action)
    start, end = _lane_window(policy, config, session, extraction_decision)
    return MassiveRawLaneDecision(
        lane_id=policy.lane_id,
        label=policy.label,
        purpose=policy.purpose,
        dataset=policy.dataset,
        raw_source_dataset=policy.raw_source_dataset,
        endpoint_family=policy.endpoint_family,
        acquisition_mode=policy.acquisition_mode,
        command_profile=policy.command_profile,
        consumer_signal_lanes=policy.consumer_signal_lanes,
        tickers=_lane_tickers(policy, config=config, extraction_decision=extraction_decision),
        batch_action=action,
        priority=priority,
        cadence_minutes=cadence,
        max_tickers_per_batch=batch_size,
        ticker_tier=tier,
        start=None if start is None else start.isoformat(),
        end=None if end is None else end.isoformat(),
        window_label=_window_label(start, end),
        extraction_action=(
            extraction_decision.action if extraction_decision is not None else "skip"
        ),
        extraction_reason=(
            extraction_decision.reason
            if extraction_decision is not None
            else f"{policy.raw_source_dataset} is not part of the current extraction plan"
        ),
        freshness_requirement_seconds=policy.freshness_requirement_seconds,
        blocks_execution=policy.blocks_execution,
        required=required,
        status_hint=_status_hint(action),
        status_class=_status_class(action),
        reason=reason,
        request_budget_label=policy.request_budget_label,
        max_requests_per_cycle=policy.max_requests_per_cycle,
        storage_manifest=policy.storage_manifest,
        requires_raw_lanes=policy.requires_raw_lanes,
    )


def _derived_signal_decision(
    signal_lane: str,
    raw_rows: Sequence[Mapping[str, object]],
) -> DerivedSignalLaneDecision:
    requirements = DERIVED_SIGNAL_REQUIREMENTS.get(signal_lane, ())
    raw_by_id = {str(row.get("lane_id")): row for row in raw_rows}
    required_rows = [raw_by_id.get(lane_id, {}) for lane_id in requirements]
    actions = {str(row.get("batch_action") or "") for row in required_rows}
    missing = [lane_id for lane_id, row in zip(requirements, required_rows, strict=True) if not row]
    if missing:
        action = "blocked"
        reason = f"{signal_lane} cannot run because raw lane(s) are missing: {', '.join(missing)}."
    elif actions.intersection({"blocked", "disabled"}):
        action = "blocked"
        reason = (
            f"{signal_lane} waits for raw Massive lane(s): {', '.join(requirements)}. "
            "At least one required raw lane is blocked or disabled."
        )
    elif actions.intersection({"run_now", "defer"}):
        action = "waiting_on_raw"
        reason = (
            f"{signal_lane} should read local data only after raw lane(s) are current: "
            f"{', '.join(requirements)}."
        )
    else:
        action = "ready"
        reason = f"{signal_lane} can read local raw lane(s): {', '.join(requirements)}."
    return DerivedSignalLaneDecision(
        signal_lane=signal_lane,
        label=signal_lane.replace("_", " ").title(),
        requires_raw_lanes=requirements,
        batch_action=action,
        status_hint=_status_hint(action),
        status_class=_status_class(action),
        reason=reason,
    )


def _runtime_derived_lanes(runtime_lanes: Sequence[str]) -> set[str]:
    configured = {str(lane) for lane in runtime_lanes if str(lane).strip()}
    if not configured:
        return set(DERIVED_SIGNAL_REQUIREMENTS)
    return configured.intersection(DERIVED_SIGNAL_REQUIREMENTS)


def _lane_tickers(
    policy: MassiveRawLanePolicy,
    *,
    config: RefreshBatchConfig,
    extraction_decision: ExtractionDecision | None,
) -> tuple[str, ...]:
    if policy.raw_source_dataset == "stock_trades":
        if (
            policy.lane_id == "massive_backtest_trade_tape"
            and extraction_decision is not None
            and extraction_decision.tickers
        ):
            return tuple(sorted({ticker.upper() for ticker in extraction_decision.tickers}))
        return tuple(sorted({ticker.upper() for ticker in config.tickers}))
    if extraction_decision is not None and extraction_decision.tickers:
        return tuple(sorted({ticker.upper() for ticker in extraction_decision.tickers}))
    if policy.raw_source_dataset in {"prices_daily", "options_chains"}:
        return tuple(sorted({ticker.upper() for ticker in config.tickers}))
    return ()


def _policy_required(
    policy: MassiveRawLanePolicy,
    *,
    config: RefreshBatchConfig,
    runtime_lanes: Sequence[str],
) -> bool:
    configured_lanes = {str(lane) for lane in runtime_lanes if str(lane).strip()}
    if configured_lanes and not configured_lanes.intersection(policy.consumer_signal_lanes):
        return False
    if policy.dataset == "prices_daily" and config.market_data_provider != "massive":
        return False
    if policy.dataset in {"reference_data"}:
        return (
            bool(configured_lanes.intersection(policy.consumer_signal_lanes))
            if configured_lanes
            else True
        )
    return policy.dataset in set(config.datasets)


def _batch_action_and_reason(
    policy: MassiveRawLanePolicy,
    *,
    config: RefreshBatchConfig,
    session: MarketSession,
    extraction_decision: ExtractionDecision | None,
    required: bool,
) -> tuple[str, str]:
    if not required:
        return "disabled", _disabled_reason(policy, config)
    if not config.massive_credentials_present and policy.acquisition_mode == "massive_api":
        return "blocked", "Massive credentials are missing; this lane cannot pull data."
    if policy.acquisition_mode == "local_derivation":
        return _local_derivation_action(policy, session)
    if policy.lane_id == "massive_reference":
        return _reference_action(policy, session)
    if policy.lane_id == "massive_options_flow":
        return _options_action(policy, config, session)
    if extraction_decision is None:
        return "disabled", f"{policy.raw_source_dataset} has no extraction decision in this plan."
    if policy.lane_id == "massive_backtest_trade_tape":
        return _backtest_action(policy, session, extraction_decision)
    if session.phase not in policy.active_phases:
        if policy.lane_id == "massive_premarket_trade_slices":
            return (
                "defer",
                (
                    f"{policy.label} is session-specific. It refreshes during the "
                    "next 04:00 ET to 09:30 ET pre-market window, then feeds "
                    "pre_market_unusual_activity without consuming quiet-window "
                    "repair capacity."
                ),
            )
        if session.phase in QUIET_REPAIR_PHASES and policy.quiet_cadence_minutes is not None:
            return (
                "run_now",
                (
                    f"{policy.label} should complete latest available coverage during "
                    f"{session.phase}. Extraction: {extraction_decision.reason}"
                ),
            )
        return (
            "defer",
            (
                f"{policy.label} is not useful in {session.phase}; keep capacity for "
                "lanes that can affect the next decision now."
            ),
        )
    if extraction_decision.action == "skip":
        return (
            "skip",
            (
                f"{policy.label} already has local coverage for {_decision_window(extraction_decision)}; "
                "no Massive request is due."
            ),
        )
    return (
        "run_now",
        (
            f"{policy.label} needs a Massive {policy.endpoint_family} update for "
            f"{_decision_window(extraction_decision)}. Extraction: {extraction_decision.reason}"
        ),
    )


def _local_derivation_action(
    policy: MassiveRawLanePolicy,
    session: MarketSession,
) -> tuple[str, str]:
    if session.phase not in policy.active_phases:
        if session.phase in QUIET_REPAIR_PHASES and policy.quiet_cadence_minutes is not None:
            return (
                "derive_from_raw",
                (
                    f"{policy.label} makes no Massive request; during {session.phase} "
                    f"it derives from {', '.join(policy.requires_raw_lanes)} when the "
                    "latest completed session is current."
                ),
            )
        return (
            "defer",
            (
                f"{policy.label} is derived during {', '.join(policy.active_phases)}; "
                f"{session.phase} does not need a fresh local derivation."
            ),
        )
    return (
        "derive_from_raw",
        (
            f"{policy.label} makes no Massive request; it derives from "
            f"{', '.join(policy.requires_raw_lanes)} after live trade slices are current."
        ),
    )


def _reference_action(
    policy: MassiveRawLanePolicy,
    session: MarketSession,
) -> tuple[str, str]:
    if session.phase not in policy.active_phases:
        return (
            "defer",
            "Massive reference data is low-frequency; defer to off-hours maintenance.",
        )
    return (
        "defer",
        (
            f"{policy.label} is modeled as a separate lane, but no reference puller "
            "is scheduled in the live decision loop yet."
        ),
    )


def _options_action(
    policy: MassiveRawLanePolicy,
    config: RefreshBatchConfig,
    session: MarketSession,
) -> tuple[str, str]:
    if policy.dataset not in set(config.datasets):
        return "disabled", "options_chains is not enabled in the live refresh config."
    if session.phase not in policy.active_phases:
        return (
            "defer",
            "Options flow is only useful during pre-market or regular market windows.",
        )
    return (
        "blocked",
        (
            "Massive options flow is declared as its own lane, but the entitlement and "
            "puller must be verified before it can feed recommendations."
        ),
    )


def _backtest_action(
    policy: MassiveRawLanePolicy,
    session: MarketSession,
    extraction_decision: ExtractionDecision,
) -> tuple[str, str]:
    if extraction_decision.action == "skip":
        return (
            "skip",
            "Full-depth trade tape coverage is already complete for the requested window.",
        )
    if session.phase in policy.active_phases:
        return (
            "run_now",
            (
                "Quiet-market window is active; run the resumable full-depth repair "
                f"for {_decision_window(extraction_decision)}."
            ),
        )
    return (
        "defer",
        (
            "Full-depth trade-tape repair is deferred so live slices, email, news, "
            "and review decisions keep capacity during active trading."
        ),
    )


def _lane_cadence(
    policy: MassiveRawLanePolicy,
    phase: str,
    action: str,
) -> tuple[int, int | None, int | None, str]:
    if action in {"blocked", "disabled"}:
        return 0, None, None, policy.ticker_tier_active
    if phase in policy.active_phases:
        return (
            policy.default_priority,
            policy.default_cadence_minutes,
            policy.default_max_tickers_per_batch,
            policy.ticker_tier_active,
        )
    return (
        policy.quiet_priority,
        policy.quiet_cadence_minutes,
        policy.quiet_max_tickers_per_batch,
        policy.ticker_tier_quiet,
    )


def _lane_window(
    policy: MassiveRawLanePolicy,
    config: RefreshBatchConfig,
    session: MarketSession,
    extraction_decision: ExtractionDecision | None,
) -> tuple[date | None, date | None]:
    if policy.command_profile in {"stock_trades_live", "stock_trades_premarket"}:
        target = _operational_trade_slice_date(session)
        return target, target
    if policy.raw_source_dataset == "prices_daily":
        if session.phase in {"pre_market", "regular_market"}:
            completed = previous_trading_day(session.market_date)
            return completed, completed
        if extraction_decision is not None and (
            extraction_decision.start is not None or extraction_decision.end is not None
        ):
            start = extraction_decision.start or extraction_decision.end
            end = extraction_decision.end or extraction_decision.start
            return start, end
        return config.start, config.end
    if extraction_decision is not None and (
        extraction_decision.start is not None or extraction_decision.end is not None
    ):
        start = extraction_decision.start or extraction_decision.end
        end = extraction_decision.end or extraction_decision.start
        return start, end
    if policy.raw_source_dataset == "stock_trades":
        start = config.stock_trades_start or config.stock_trades_end or session.market_date
        end = config.stock_trades_end or config.stock_trades_start or session.market_date
        return start, end
    return None, None


def _operational_trade_slice_date(session: MarketSession) -> date:
    if session.is_trading_day and session.phase != "overnight_before_pre_market":
        return session.market_date
    return previous_trading_day(session.market_date)


def _disabled_reason(policy: MassiveRawLanePolicy, config: RefreshBatchConfig) -> str:
    if policy.dataset == "prices_daily" and config.market_data_provider != "massive":
        return (
            "Daily bars are configured for "
            f"{config.market_data_provider}; this Massive lane is disabled."
        )
    if policy.dataset not in set(config.datasets) and policy.dataset not in {"reference_data"}:
        return f"{policy.dataset} is not enabled in the live refresh config."
    return "No configured runtime signal currently consumes this Massive raw lane."


def _decision_window(decision: ExtractionDecision) -> str:
    return _window_label(decision.start, decision.end)


def _window_label(start: date | None, end: date | None) -> str:
    if start is None and end is None:
        return "not recorded"
    if start == end:
        return start.isoformat() if start is not None else str(end)
    start_text = "unknown" if start is None else start.isoformat()
    end_text = "unknown" if end is None else end.isoformat()
    return f"{start_text} to {end_text}"


def _status_hint(action: str) -> str:
    labels = {
        "run_now": "due now",
        "defer": "deferred",
        "skip": "fresh",
        "blocked": "blocked",
        "disabled": "disabled",
        "derive_from_raw": "ready from raw",
        "waiting_on_raw": "waiting on raw",
        "ready": "ready",
    }
    return labels.get(action, action.replace("_", " "))


def _status_class(action: str) -> str:
    if action in {"skip", "ready", "derive_from_raw"}:
        return "pass"
    if action in {"run_now", "defer", "waiting_on_raw"}:
        return "warn"
    if action == "blocked":
        return "block"
    return "neutral"


def _count_action(rows: Sequence[Mapping[str, object]], action: str) -> int:
    return sum(1 for row in rows if row.get("batch_action") == action)


def _sort_key(row: Mapping[str, object]) -> tuple[int, str]:
    priority = row.get("priority")
    value = priority if isinstance(priority, int) else 0
    return (-value, str(row.get("lane_id") or ""))


def _plan_detail(rows: Sequence[Mapping[str, object]], phase: str) -> str:
    due = _count_action(rows, "run_now")
    blocked = _count_action(rows, "blocked")
    derived = _count_action(rows, "derive_from_raw")
    if blocked:
        return f"{blocked} Massive raw lane(s) are blocked; fix provider credentials or entitlement first."
    if due:
        return f"{due} Massive raw acquisition lane(s) are due in {phase}; run API lanes before derived signals."
    if derived:
        return f"{derived} local derived raw lane(s) can read current Massive live slices without extra API calls."
    return f"No Massive raw acquisition lane needs an immediate pull in {phase}."
