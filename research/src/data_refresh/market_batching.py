from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from data_refresh.extraction_plan import ExtractionDecision, build_extraction_plan
from data_refresh.market_calendar import (
    MarketSession,
    classify_market_session,
    previous_trading_day,
)
from data_refresh.massive_orchestrator import (
    build_massive_orchestration_plan,
    raw_lanes_for_signal,
)
from data_refresh.signal_lane_policy import SignalLanePolicy, policies_for_lanes
from data_refresh.types import RefreshBatchConfig


@dataclass(frozen=True)
class DatasetBatchDecision:
    dataset: str
    extraction_action: str
    batch_action: str
    priority: int
    cadence_minutes: int | None
    max_tickers_per_batch: int | None
    reason: str
    extraction_reason: str
    tickers: tuple[str, ...]
    ticker_count: int
    start: str | None
    end: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset": self.dataset,
            "extraction_action": self.extraction_action,
            "batch_action": self.batch_action,
            "priority": self.priority,
            "cadence_minutes": self.cadence_minutes,
            "max_tickers_per_batch": self.max_tickers_per_batch,
            "reason": self.reason,
            "extraction_reason": self.extraction_reason,
            "tickers": list(self.tickers),
            "ticker_count": self.ticker_count,
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True)
class SignalLaneBatchDecision:
    lane: str
    dataset: str
    cadence: str
    batch_action: str
    priority: int
    cadence_minutes: int | None
    reason: str
    requires_massive_raw_lanes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "lane": self.lane,
            "dataset": self.dataset,
            "cadence": self.cadence,
            "batch_action": self.batch_action,
            "priority": self.priority,
            "cadence_minutes": self.cadence_minutes,
            "reason": self.reason,
            "requires_massive_raw_lanes": list(self.requires_massive_raw_lanes),
        }


def build_market_aware_batch_plan(
    config: RefreshBatchConfig,
    *,
    lanes: tuple[str, ...],
    now: datetime | None = None,
) -> dict[str, object]:
    current = now or datetime.now(UTC)
    session = classify_market_session(current)
    effective_config = _session_adjusted_config(config, session)
    extraction_decisions = build_extraction_plan(effective_config, now=current)
    dataset_rows = [
        _dataset_batch_decision(session, decision).as_dict()
        for decision in extraction_decisions
    ]
    signal_rows = [
        _signal_lane_decision(session, policy).as_dict()
        for policy in policies_for_lanes(lanes)
    ]
    massive_plan = build_massive_orchestration_plan(
        effective_config,
        session=session,
        extraction_decisions=extraction_decisions,
        runtime_lanes=lanes,
    )
    return {
        "schema_version": "0.1.0",
        "generated_at": current.isoformat(),
        "market_session": session.as_dict(),
        "effective_window": {
            "start": effective_config.start.isoformat(),
            "end": effective_config.end.isoformat(),
            "stock_trades_start": (
                None
                if effective_config.stock_trades_start is None
                else effective_config.stock_trades_start.isoformat()
            ),
            "stock_trades_end": (
                None
                if effective_config.stock_trades_end is None
                else effective_config.stock_trades_end.isoformat()
            ),
        },
        "summary": _summary(dataset_rows, signal_rows, massive_plan),
        "datasets": sorted(dataset_rows, key=_plan_sort_key),
        "signal_lanes": sorted(signal_rows, key=_plan_sort_key),
        "massive_lanes": massive_plan["lanes"],
        "massive_orchestrator": massive_plan,
    }


def _session_adjusted_config(
    config: RefreshBatchConfig,
    session: MarketSession,
) -> RefreshBatchConfig:
    if not session.is_trading_day:
        latest_complete_day = previous_trading_day(session.market_date)
        return replace(config, end=max(config.end, latest_complete_day))
    if session.phase == "overnight_before_pre_market":
        latest_complete_day = previous_trading_day(session.market_date)
        return replace(
            config,
            end=max(config.end, latest_complete_day),
            stock_trades_start=latest_complete_day,
            stock_trades_end=latest_complete_day,
        )
    if session.phase in {"pre_market", "regular_market"}:
        return replace(
            config,
            stock_trades_start=session.market_date,
            stock_trades_end=session.market_date,
        )
    if session.phase in {"after_hours", "overnight_after_hours"}:
        return replace(
            config,
            end=max(config.end, session.market_date),
            stock_trades_start=session.market_date,
            stock_trades_end=session.market_date,
        )
    return config


def _dataset_batch_decision(
    session: MarketSession,
    decision: ExtractionDecision,
) -> DatasetBatchDecision:
    dataset = decision.dataset
    if decision.action == "skip":
        action = "skip"
        priority = 0
        cadence = None
        batch_size = None
        reason = decision.reason
    elif dataset == "stock_trades":
        action, priority, cadence, batch_size, reason = _stock_trades_rule(session)
    elif dataset == "prices_daily":
        action, priority, cadence, batch_size, reason = _prices_rule(session)
    elif dataset in {"news_rss", "subscription_emails"}:
        action, priority, cadence, batch_size, reason = _context_feed_rule(session, dataset)
    elif dataset == "sec_form4":
        action, priority, cadence, batch_size, reason = _form4_rule(session)
    elif dataset in {"sec_company_facts", "sec_13f"}:
        action, priority, cadence, batch_size, reason = _slow_filing_rule(session, dataset)
    else:
        action = "defer"
        priority = 20
        cadence = None
        batch_size = None
        reason = f"{dataset} has no market-aware batching rule yet"
    if _should_defer_heavy_repair(session, decision):
        action = "defer"
        priority = min(priority, 20)
        cadence = None
        batch_size = None
        reason = (
            f"{dataset} needs {decision.action} repair; queue it for an "
            "off-hours baseline repair window"
        )
    elif decision.action in {"baseline", "force"} and action == "defer":
        reason = f"{reason}; heavy {decision.action} extraction is safer off-hours"
    return DatasetBatchDecision(
        dataset=dataset,
        extraction_action=decision.action,
        batch_action=action,
        priority=priority,
        cadence_minutes=cadence,
        max_tickers_per_batch=batch_size,
        reason=reason,
        extraction_reason=decision.reason,
        tickers=decision.tickers,
        ticker_count=len(decision.tickers),
        start=None if decision.start is None else decision.start.isoformat(),
        end=None if decision.end is None else decision.end.isoformat(),
    )


def _stock_trades_rule(
    session: MarketSession,
) -> tuple[str, int, int | None, int | None, str]:
    if session.phase == "pre_market":
        return (
            "run_now",
            100,
            5,
            20,
            "pre-market is active; prioritize current-day Massive trade batches",
        )
    if session.phase == "regular_market":
        return (
            "run_now",
            95,
            5,
            15,
            "regular session is open; keep market-flow batches small and frequent",
        )
    if session.phase == "after_hours":
        return (
            "run_now",
            85,
            15,
            35,
            "after-hours is active; reconcile late prints without full historical re-pulls",
        )
    if session.phase == "overnight_after_hours":
        return (
            "run_now",
            70,
            60,
            50,
            "extended hours ended; run catch-up market-flow batches before next session",
        )
    if session.phase == "overnight_before_pre_market":
        return (
            "run_now",
            80,
            60,
            50,
            "before pre-market; repair the previous completed session before live trading starts",
        )
    if session.phase in {"closed_weekend", "closed_holiday", "closed"}:
        return (
            "run_now",
            60,
            120,
            50,
            "market is closed; complete the latest available trade-slice coverage without blocking live capacity",
        )
    return (
        "defer",
        30,
        None,
        None,
        "market is closed or before pre-market; defer trade-print polling",
    )


def _should_defer_heavy_repair(
    session: MarketSession,
    decision: ExtractionDecision,
) -> bool:
    if decision.action not in {"baseline", "force"}:
        return False
    if decision.dataset in {"stock_trades", "news_rss", "subscription_emails"}:
        return False
    if session.phase in {"pre_market", "regular_market"}:
        return True
    return session.phase == "after_hours" and decision.dataset in {
        "sec_company_facts",
        "sec_13f",
        "sec_form4",
    }


def _prices_rule(session: MarketSession) -> tuple[str, int, int | None, int | None, str]:
    quiet_phases = {
        "after_hours",
        "overnight_after_hours",
        "overnight_before_pre_market",
        "closed_weekend",
        "closed_holiday",
    }
    if session.phase in quiet_phases:
        return (
            "run_now",
            80,
            60,
            100,
            "daily bars should refresh after the regular close or during closed-market windows",
        )
    return (
        "defer",
        35,
        None,
        None,
        "daily OHLCV bars are not final during pre-market or regular trading",
    )


def _context_feed_rule(
    session: MarketSession,
    dataset: str,
) -> tuple[str, int, int | None, int | None, str]:
    del dataset
    if session.phase in {"pre_market", "regular_market"}:
        return (
            "run_now",
            90,
            10,
            None,
            "headline/email context can change candidate judgement during active trading windows",
        )
    if session.phase == "after_hours":
        return (
            "run_now",
            75,
            15,
            None,
            "after-hours headlines and subscription alerts should be captured quickly",
        )
    return (
        "run_now",
        55,
        30,
        None,
        "closed-market polling should be slower but still append new context",
    )


def _form4_rule(session: MarketSession) -> tuple[str, int, int | None, int | None, str]:
    if session.phase in {"regular_market", "after_hours", "overnight_after_hours"}:
        return (
            "run_now",
            65,
            60,
            50,
            "Form 4 events are event-driven; use hourly incremental checks",
        )
    return (
        "run_now",
        50,
        120,
        75,
        "Form 4 checks can run at a slower cadence outside market-moving windows",
    )


def _slow_filing_rule(
    session: MarketSession,
    dataset: str,
) -> tuple[str, int, int | None, int | None, str]:
    if session.phase in {"closed_weekend", "closed_holiday", "overnight_after_hours"}:
        return (
            "run_now",
            45,
            240,
            100,
            f"{dataset} is low-frequency; run it during quiet maintenance windows",
        )
    return (
        "defer",
        15,
        None,
        None,
        f"{dataset} is low-frequency; avoid spending active-session capacity on it",
    )


def _signal_lane_decision(
    session: MarketSession,
    policy: SignalLanePolicy,
) -> SignalLaneBatchDecision:
    if policy.cadence == "backlog":
        action = "disabled"
        priority = 0
        cadence = None
        reason = policy.operational_note
    elif policy.dataset == "stock_trades":
        action, priority, cadence, _batch_size, reason = _stock_trades_rule(session)
    elif policy.dataset == "prices_daily":
        action, priority, cadence, _batch_size, reason = _prices_rule(session)
    elif policy.dataset in {"news_rss", "subscription_emails"}:
        action, priority, cadence, _batch_size, reason = _context_feed_rule(
            session,
            policy.dataset,
        )
    elif policy.dataset == "sec_form4":
        action, priority, cadence, _batch_size, reason = _form4_rule(session)
    elif policy.dataset in {"sec_company_facts", "sec_13f"}:
        action, priority, cadence, _batch_size, reason = _slow_filing_rule(
            session,
            policy.dataset,
        )
    else:
        action = "defer"
        priority = 10
        cadence = None
        reason = policy.operational_note
    return SignalLaneBatchDecision(
        lane=policy.lane,
        dataset=policy.dataset,
        cadence=policy.cadence,
        batch_action=action,
        priority=priority,
        cadence_minutes=cadence,
        reason=reason,
        requires_massive_raw_lanes=raw_lanes_for_signal(policy.lane),
    )


def _summary(
    dataset_rows: list[dict[str, object]],
    signal_rows: list[dict[str, object]],
    massive_plan: Mapping[str, object],
) -> dict[str, object]:
    return {
        "run_now_dataset_count": _count_action(dataset_rows, "run_now"),
        "deferred_dataset_count": _count_action(dataset_rows, "defer"),
        "skipped_dataset_count": _count_action(dataset_rows, "skip"),
        "run_now_signal_lane_count": _count_action(signal_rows, "run_now"),
        "deferred_signal_lane_count": _count_action(signal_rows, "defer"),
        "disabled_signal_lane_count": _count_action(signal_rows, "disabled"),
        "run_now_massive_lane_count": _int_value(
            massive_plan.get("run_now_count"),
            0,
        ),
        "deferred_massive_lane_count": _int_value(
            massive_plan.get("deferred_count"),
            0,
        ),
        "blocked_massive_lane_count": _int_value(
            massive_plan.get("blocked_count"),
            0,
        ),
    }


def _count_action(rows: list[dict[str, object]], action: str) -> int:
    return sum(1 for row in rows if row.get("batch_action") == action)


def _int_value(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value
    return fallback


def _plan_sort_key(row: Mapping[str, object]) -> tuple[int, str]:
    priority = row.get("priority")
    name = row.get("dataset") or row.get("lane")
    return (-(priority if isinstance(priority, int) else 0), str(name))
