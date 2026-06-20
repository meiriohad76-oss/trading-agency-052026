from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agency.runtime.scheduler_work_queue import (
    _resolve_repo_root,
    build_affected_ticker_mini_cycle_plan,
    build_off_hours_baseline_repair_plan,
    build_scheduler_work_queue,
    build_ticker_tiers,
    execution_freshness_gate,
    scheduler_work_queue_context,
)

NOW = datetime(2026, 5, 11, 14, 0, tzinfo=UTC)
EXPECTED_DUE_JOBS = 1
EXPECTED_MINI_CYCLE_JOBS = 2
COMMAND_SCRIPT_INDEX = 1


def test_ticker_tier_manager_prioritizes_positions_reviews_and_active_universe() -> None:
    tiers = build_ticker_tiers(
        positions=[{"ticker": "AAPL"}],
        open_orders=[{"symbol": "MSFT"}],
        review_queue=[
            {"ticker": "NVDA", "human_review_decision": "Approve"},
            {"ticker": "AMZN", "human_review_decision": "Pending"},
        ],
        selection_reports=[
            {"ticker": "GOOGL", "final_conviction": 0.91},
            {"ticker": "META", "final_conviction": 0.40},
        ],
        active_universe=["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"],
        research_universe=["AAPL", "MSFT", "IBM"],
    )

    assert tiers.t0 == ("AAPL", "MSFT", "NVDA")
    assert tiers.t1 == ("AMZN", "GOOGL")
    assert tiers.t2 == ("META",)
    assert tiers.t3 == ("IBM",)


def test_scheduler_work_queue_adds_due_jobs_eta_tiers_and_tradability() -> None:
    tiers = build_ticker_tiers(
        review_queue=[{"ticker": "AAPL", "human_review_decision": "Pending"}],
        active_universe=["AAPL", "MSFT"],
    )

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={
            "connected": True,
            "mode": "paper",
            "checked_at": NOW.isoformat(),
        },
        now=NOW,
    )

    assert queue["market_phase"] == "regular_market"
    assert queue["summary"]["counts"]["due_now"] == EXPECTED_DUE_JOBS
    assert queue["tradability"]["state"] == "tradable"
    dataset_job = next(job for job in queue["jobs"] if job["job_id"] == "dataset:stock_trades")
    assert dataset_job["status"] == "SKIPPED"
    assert dataset_job["command"] == []
    assert "stock_trades is lane-owned" in str(dataset_job["reason"])
    assert queue["next_jobs"][0]["kind"] == "signal_lane"
    assert queue["next_jobs"][0]["eta_seconds"] > 0


def test_scheduler_work_queue_respects_recent_dataset_cadence() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])
    recent = (NOW - timedelta(minutes=2)).isoformat()

    queue = build_scheduler_work_queue(
        _market_plan("overnight_after_hours", dataset="sec_form4"),
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        scheduler_runtime={"job_last_success_at": {"dataset:sec_form4": recent}},
        now=NOW,
    )

    job = next(row for row in queue["jobs"] if row["job_id"] == "dataset:sec_form4")
    assert job["status"] == "WAITING"
    assert job["command"] == []
    assert "next due" in str(job["reason"]).lower()


def test_scheduler_stock_trade_command_is_bounded_to_market_window() -> None:
    tiers = build_ticker_tiers(
        review_queue=[{"ticker": "AAPL", "human_review_decision": "Pending"}],
        active_universe=["AAPL", "MSFT"],
    )

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    dataset_job = next(job for job in queue["jobs"] if job["job_id"] == "dataset:stock_trades")
    command = dataset_job["command"]

    assert dataset_job["status"] == "SKIPPED"
    assert command == []
    assert "generic dataset command suppressed" in str(dataset_job["reason"])


def test_scheduler_tradability_allows_review_operational_repair_warnings() -> None:
    tiers = build_ticker_tiers(
        review_queue=[{"ticker": "AAPL", "human_review_decision": "Pending"}],
        active_universe=["AAPL", "MSFT"],
    )

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_load_status={
            "state": "attention",
            "review_operational_ready": True,
            "datasets": [
                {
                    "dataset": "stock_trades",
                    "status": "warning",
                    "detail": "Partial trade-print coverage remains under repair.",
                }
            ],
        },
        source_health=_fresh_sources(),
        broker={
            "connected": True,
            "mode": "paper",
            "checked_at": NOW.isoformat(),
        },
        now=NOW,
    )

    assert queue["tradability"]["state"] == "tradable"


def test_scheduler_dataset_command_prefers_extraction_tickers_over_tier() -> None:
    tiers = build_ticker_tiers(
        review_queue=[{"ticker": "AAPL", "human_review_decision": "Pending"}],
        active_universe=["AAPL", "MSFT", "NVDA"],
    )

    queue = build_scheduler_work_queue(
        _market_plan("regular_market", tickers=("MSFT", "NVDA")),
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    dataset_job = next(job for job in queue["jobs"] if job["job_id"] == "dataset:stock_trades")
    command = dataset_job["command"]

    assert dataset_job["ticker_sample"] == ["MSFT", "NVDA"]
    assert command == []
    assert "stock_trades is lane-owned" in str(dataset_job["reason"])


def test_scheduler_market_stock_trade_job_includes_full_active_universe_tier() -> None:
    tiers = build_ticker_tiers(
        review_queue=[
            {"ticker": "XOM", "human_review_decision": "Pending"},
            {"ticker": "AAPL", "human_review_decision": "Pending"},
        ],
        active_universe=["AAPL", "MSFT", "XOM"],
    )

    queue = build_scheduler_work_queue(
        _market_plan("regular_market", tickers=("AAPL", "MSFT", "XOM")),
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    command = queue["next_jobs"][0]["command"]

    assert queue["next_jobs"][0]["ticker_sample"] == ["XOM", "AAPL", "MSFT"]
    assert command[-6:] == [
        "--ticker",
        "XOM",
        "--ticker",
        "AAPL",
        "--ticker",
        "MSFT",
    ]


def test_active_stock_trade_dataset_job_runs_planned_universe_when_t0_t1_empty() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT", "NVDA"])

    queue = build_scheduler_work_queue(
        _market_plan("regular_market", tickers=("AAPL", "MSFT", "NVDA")),
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    dataset_job = next(job for job in queue["jobs"] if job["kind"] == "dataset")

    assert dataset_job["ticker_tier"] == "T0/T1/T2"
    assert dataset_job["status"] == "SKIPPED"
    assert dataset_job["ticker_sample"] == ["AAPL", "MSFT", "NVDA"]
    assert dataset_job["command"] == []


def test_scheduler_broad_dataset_preserves_planned_tickers_by_tier_order() -> None:
    tiers = build_ticker_tiers(
        review_queue=[{"ticker": "AAPL", "human_review_decision": "Pending"}],
        active_universe=["AAPL", "MSFT", "NVDA"],
    )

    queue = build_scheduler_work_queue(
        _market_plan(
            "after_hours",
            dataset="prices_daily",
            tickers=("AAPL", "MSFT", "NVDA"),
        ),
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    dataset_job = next(job for job in queue["jobs"] if job["kind"] == "dataset")
    command = dataset_job["command"]

    assert dataset_job["ticker_tier"] == "T0/T1/T2"
    assert dataset_job["ticker_sample"] == ["AAPL", "MSFT", "NVDA"]
    assert command[-6:] == [
        "--ticker",
        "AAPL",
        "--ticker",
        "MSFT",
        "--ticker",
        "NVDA",
    ]


def test_scheduler_dataset_command_uses_planned_extraction_action() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL"])

    queue = build_scheduler_work_queue(
        _market_plan("after_hours", extraction_action="force", dataset="prices_daily"),
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    command = next(job for job in queue["jobs"] if job["kind"] == "dataset")["command"]

    assert command[command.index("--extraction-mode") + 1] == "force"


def test_affected_ticker_mini_cycle_recomputes_only_triggered_ticker() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])

    plan = build_affected_ticker_mini_cycle_plan(
        [
            {"ticker": "AAPL", "event_type": "stock_trades"},
            {"ticker": "AAPL", "event_type": "stock_trades"},
            {"ticker": "MSFT", "event_type": "sec_form4"},
        ],
        tiers=tiers,
        now=NOW,
    )

    assert plan["affected_tickers"] == ["AAPL", "MSFT"]
    assert plan["job_count"] == EXPECTED_MINI_CYCLE_JOBS
    first_job = plan["jobs"][0]
    assert first_job["ticker"] == "AAPL"
    assert "abnormal_volume" in first_job["lanes"]
    assert "--config" in first_job["command"]
    assert "--no-persist" in first_job["command"]
    assert "--output-root" in first_job["command"]
    assert first_job["command"].count("--signal") == len(first_job["lanes"])
    assert (
        "mini-aapl-stock-trades-"
        in first_job["command"][first_job["command"].index("--cycle-id") + 1]
    )
    ticker_index = first_job["command"].index("--ticker")
    assert first_job["command"][ticker_index : ticker_index + 2] == ["--ticker", "AAPL"]


def test_affected_ticker_mini_cycle_keeps_distinct_event_cycle_ids() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL"])

    plan = build_affected_ticker_mini_cycle_plan(
        [
            {"ticker": "AAPL", "event_type": "stock_trades"},
            {"ticker": "AAPL", "event_type": "news_rss"},
        ],
        tiers=tiers,
        now=NOW,
    )

    cycle_ids = [job["command"][job["command"].index("--cycle-id") + 1] for job in plan["jobs"]]

    assert len(cycle_ids) == 2
    assert len(set(cycle_ids)) == 2
    assert any("stock-trades" in cycle_id for cycle_id in cycle_ids)
    assert any("news-rss" in cycle_id for cycle_id in cycle_ids)


def test_off_hours_baseline_repair_defers_during_regular_market() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL"])

    regular = build_off_hours_baseline_repair_plan(
        _market_plan("regular_market", extraction_action="baseline"),
        tiers=tiers,
        now=NOW,
    )
    quiet = build_off_hours_baseline_repair_plan(
        _market_plan("overnight_after_hours", extraction_action="baseline"),
        tiers=tiers,
        now=NOW,
    )

    assert regular["state"] == "deferred"
    assert regular["jobs"][0]["status"] == "DEFERRED"
    assert quiet["state"] == "active"
    assert quiet["jobs"][0]["status"] == "DUE_NOW"


def test_scheduler_repair_plan_includes_partial_stock_trade_incremental() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])

    repair = build_off_hours_baseline_repair_plan(
        _market_plan(
            "regular_market",
            tickers=("AAPL",),
            extraction_reason="Massive trade coverage has partial full-depth slices for 1 ticker(s)",
        ),
        tiers=tiers,
        now=NOW,
    )

    assert repair["state"] == "deferred"
    assert repair["jobs"][0]["dataset"] == "stock_trades"
    assert repair["jobs"][0]["ticker_sample"] == ["AAPL"]


def test_execution_freshness_gate_blocks_stale_broker_or_critical_sources() -> None:
    fresh = execution_freshness_gate(
        {"connected": True, "checked_at": NOW.isoformat()},
        _fresh_sources(),
        now=NOW,
    )
    stale_broker = execution_freshness_gate(
        {"connected": True, "checked_at": (NOW - timedelta(minutes=2)).isoformat()},
        _fresh_sources(),
        now=NOW,
    )
    stale_source = execution_freshness_gate(
        {"connected": True, "checked_at": NOW.isoformat()},
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="STALE", status="STALE"),
        ],
        now=NOW,
    )

    assert fresh["ready"] is True
    assert stale_broker["ready"] is False
    assert stale_source["ready"] is False


def test_execution_freshness_gate_warns_for_dashboard_broker_check_pending() -> None:
    gate = execution_freshness_gate(
        {
            "connected": False,
            "checked_at": NOW.isoformat(),
            "status_label": "Broker Check Pending",
            "status_class": "warn",
        },
        _fresh_sources(),
        now=NOW,
    )

    assert gate["ready"] is True
    assert gate["state"] == "warning"
    assert any(
        check["label"] == "Broker state"
        and check["status"] == "WARN"
        and "not confirmed yet" in check["detail"]
        for check in gate["checks"]
    )


def test_execution_freshness_gate_warns_for_dashboard_broker_check_delayed() -> None:
    gate = execution_freshness_gate(
        {
            "connected": False,
            "checked_at": NOW.isoformat(),
            "status_label": "Broker Check Delayed",
            "status_class": "warn",
        },
        _fresh_sources(),
        now=NOW,
    )

    assert gate["ready"] is True
    assert gate["state"] == "warning"
    assert any(
        check["label"] == "Broker state" and check["status"] == "WARN" for check in gate["checks"]
    )


def test_execution_freshness_gate_accepts_closed_market_latest_session_sources() -> None:
    overnight = datetime(2026, 5, 12, 2, 30, tzinfo=UTC)
    latest_session_checked = datetime(2026, 5, 11, 22, 0, tzinfo=UTC)
    sources = [
        {
            **_source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            "checked_at": latest_session_checked.isoformat(),
        },
        {
            **_source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
            "checked_at": latest_session_checked.isoformat(),
        },
    ]

    gate = execution_freshness_gate(
        {"connected": True, "checked_at": overnight.isoformat()},
        sources,
        now=overnight,
        market_phase="overnight_after_hours",
    )

    assert gate["ready"] is True
    assert gate["state"] == "pass"
    assert gate["source_max_age_policy_label"] == "closed-market latest completed session"
    assert all(
        "latest completed session" in str(check["detail"])
        for check in gate["checks"]
        if check["label"] != "Broker state"
    )


def test_execution_freshness_gate_keeps_broker_strict_when_market_closed() -> None:
    overnight = datetime(2026, 5, 12, 2, 30, tzinfo=UTC)
    latest_session_checked = datetime(2026, 5, 11, 22, 0, tzinfo=UTC)
    sources = [
        {
            **_source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            "checked_at": latest_session_checked.isoformat(),
        },
        {
            **_source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
            "checked_at": latest_session_checked.isoformat(),
        },
    ]

    gate = execution_freshness_gate(
        {"connected": True, "checked_at": (overnight - timedelta(minutes=2)).isoformat()},
        sources,
        now=overnight,
        market_phase="overnight_after_hours",
    )

    assert gate["ready"] is False
    assert any(
        check["label"] == "Broker state" and check["status"] == "BLOCK" for check in gate["checks"]
    )


def test_execution_freshness_gate_still_blocks_stale_sources_during_regular_market() -> None:
    stale_checked_at = NOW - timedelta(minutes=45)
    sources = [
        {
            **_source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            "checked_at": stale_checked_at.isoformat(),
        },
        {
            **_source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
            "checked_at": stale_checked_at.isoformat(),
        },
    ]

    gate = execution_freshness_gate(
        {"connected": True, "checked_at": NOW.isoformat()},
        sources,
        now=NOW,
        market_phase="regular_market",
    )

    assert gate["ready"] is False
    assert gate["state"] == "blocked"


def test_execution_freshness_gate_accepts_daily_bars_latest_completed_session_intraday() -> None:
    now = datetime(2026, 5, 21, 14, 0, tzinfo=UTC)
    previous_close_daily_bar_check = datetime(2026, 5, 20, 20, 12, tzinfo=UTC)

    gate = execution_freshness_gate(
        {"connected": True, "checked_at": now.isoformat()},
        [
            {
                **_source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
                "checked_at": previous_close_daily_bar_check.isoformat(),
            },
            {
                **_source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
                "checked_at": now.isoformat(),
            },
        ],
        now=now,
        market_phase="regular_market",
    )

    assert gate["ready"] is True
    assert gate["state"] == "pass"
    daily_check = next(check for check in gate["checks"] if check["label"] == "Daily Market Bars")
    assert daily_check["status"] == "PASS"
    assert "latest completed" in str(daily_check["detail"])


def test_scheduler_queue_uses_closed_market_source_freshness_semantics() -> None:
    overnight = datetime(2026, 5, 12, 2, 30, tzinfo=UTC)
    latest_session_checked = datetime(2026, 5, 11, 22, 0, tzinfo=UTC)
    queue = build_scheduler_work_queue(
        _market_plan("overnight_after_hours"),
        tiers=build_ticker_tiers(active_universe=["AAPL", "MSFT"]),
        data_load_status={"state": "ready", "datasets": []},
        source_health=[
            {
                **_source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
                "checked_at": latest_session_checked.isoformat(),
            },
            {
                **_source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
                "checked_at": latest_session_checked.isoformat(),
            },
        ],
        broker={"connected": True, "mode": "paper", "checked_at": overnight.isoformat()},
        now=overnight,
    )

    assert queue["execution_freshness_gate"]["ready"] is True
    assert queue["tradability"]["state"] == "tradable"


def test_execution_freshness_gate_test_mode_extends_source_age_only(monkeypatch) -> None:
    monkeypatch.setenv("AGENCY_EXECUTION_FRESHNESS_TEST_MODE", "true")
    monkeypatch.setenv("AGENCY_TEST_STOCK_SOURCE_MAX_AGE_SECONDS", "3600")
    stale_sources = [
        {
            **_source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            "checked_at": (NOW - timedelta(minutes=45)).isoformat(),
        },
        {
            **_source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
            "checked_at": (NOW - timedelta(minutes=45)).isoformat(),
        },
    ]

    gate = execution_freshness_gate(
        {"connected": True, "checked_at": NOW.isoformat()},
        stale_sources,
        now=NOW,
    )
    stale_broker = execution_freshness_gate(
        {"connected": True, "checked_at": (NOW - timedelta(minutes=2)).isoformat()},
        stale_sources,
        now=NOW,
    )

    assert gate["ready"] is True
    assert gate["test_freshness_mode"] is True
    assert gate["max_source_age_seconds"] == 3600
    assert stale_broker["ready"] is False
    assert any(
        check["label"] == "Broker state" and check["status"] == "BLOCK"
        for check in stale_broker["checks"]
    )


def test_execution_freshness_gate_production_ignores_test_window_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("AGENCY_EXECUTION_FRESHNESS_TEST_MODE", raising=False)
    monkeypatch.setenv("AGENCY_TEST_STOCK_SOURCE_MAX_AGE_SECONDS", "3600")
    stale_sources = [
        {
            **_source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            "checked_at": (NOW - timedelta(minutes=45)).isoformat(),
        },
        {
            **_source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
            "checked_at": (NOW - timedelta(minutes=45)).isoformat(),
        },
    ]

    gate = execution_freshness_gate(
        {"connected": True, "checked_at": NOW.isoformat()},
        stale_sources,
        now=NOW,
    )

    assert gate["ready"] is False
    assert gate["test_freshness_mode"] is False
    assert gate["max_source_age_seconds"] == 15 * 60


def test_execution_freshness_gate_warns_for_fresh_degraded_trade_lane() -> None:
    gate = execution_freshness_gate(
        {"connected": True, "checked_at": NOW.isoformat()},
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="DEGRADED"),
        ],
        now=NOW,
    )

    assert gate["ready"] is True
    assert gate["state"] == "warning"
    assert gate["blocker_count"] == 0
    assert gate["warning_count"] == 1


def test_scheduler_queue_stays_tradable_for_fresh_degraded_trade_lane() -> None:
    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=build_ticker_tiers(active_universe=["AAPL", "MSFT"]),
        data_load_status={"state": "attention", "review_operational_ready": True, "datasets": []},
        source_health=[
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="DEGRADED"),
        ],
        broker={"connected": True, "mode": "paper", "checked_at": NOW.isoformat()},
        now=NOW,
    )

    assert queue["execution_freshness_gate"]["ready"] is True
    assert queue["execution_freshness_gate"]["state"] == "warning"
    assert queue["tradability"]["state"] == "tradable"
    assert queue["tradability"]["status_class"] == "warn"


def test_scheduler_tradability_uses_lane_states_for_execution_blockers() -> None:
    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=build_ticker_tiers(active_universe=["AAPL", "MSFT"]),
        data_load_status={
            "state": "ready",
            "review_operational_ready": True,
            "datasets": [],
            "lane_states": [
                {
                    "lane_id": "massive_live_trade_slices",
                    "status_label": "Analysis exists but needs refresh",
                    "state": "needs_refresh",
                    "status_class": "block",
                    "blocks_execution": True,
                    "blocker": True,
                    "operator_message": (
                        "Live trade slices were analyzed but the proof is older than policy."
                    ),
                    "recommended_action": "Refresh Massive Live Trade Slices.",
                }
            ],
        },
        source_health=_fresh_sources(),
        broker={"connected": True, "mode": "paper", "checked_at": NOW.isoformat()},
        now=NOW,
    )

    assert queue["tradability"]["state"] == "context_only"
    assert "Massive Live Trade Slices" in str(queue["tradability"]["detail"])
    assert queue["stale_datasets"][0]["dataset"] == "massive_live_trade_slices"


def test_scheduler_tradability_warning_wording_does_not_expose_stale_label() -> None:
    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=build_ticker_tiers(active_universe=["AAPL", "MSFT"]),
        data_load_status={
            "state": "attention",
            "review_operational_ready": False,
            "datasets": [
                {
                    "dataset": "news",
                    "status": "warning",
                    "status_label": "Analysis exists but needs refresh",
                    "detail": "News analysis exists but needs refresh.",
                }
            ],
        },
        source_health=_fresh_sources(),
        broker={"connected": True, "mode": "paper", "checked_at": NOW.isoformat()},
        now=NOW,
    )

    detail = str(queue["tradability"]["detail"]).lower()
    assert queue["tradability"]["state"] == "context_only"
    assert "need refresh or attention" in detail
    assert "stale" not in detail


def test_scheduler_queue_explains_pending_broker_without_claiming_it_is_fresh() -> None:
    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=build_ticker_tiers(active_universe=["AAPL", "MSFT"]),
        data_load_status={"state": "attention", "review_operational_ready": True, "datasets": []},
        source_health=_fresh_sources(),
        broker={
            "connected": False,
            "mode": "paper",
            "checked_at": NOW.isoformat(),
            "status_label": "Broker Check Delayed",
            "status_class": "warn",
        },
        now=NOW,
    )

    assert queue["execution_freshness_gate"]["state"] == "warning"
    assert queue["tradability"]["state"] == "tradable"
    assert "Critical evidence is fresh" in str(queue["tradability"]["detail"])
    assert "broker status is not confirmed" in str(queue["tradability"]["detail"])
    assert "Broker and critical evidence are fresh enough" not in str(
        queue["tradability"]["detail"]
    )


def test_execution_freshness_gate_blocks_missing_critical_source() -> None:
    gate = execution_freshness_gate(
        {"connected": True, "checked_at": NOW.isoformat()},
        [_source("daily-market-bars", freshness="FRESH", status="HEALTHY")],
        now=NOW,
    )

    assert gate["ready"] is False
    assert any(
        "massive-stock-trades has no source-health row" in str(check["detail"])
        for check in gate["checks"]
    )


def test_signal_command_keeps_explicit_tickers_above_display_limit() -> None:
    tickers = [f"T{i:02d}" for i in range(25)]
    tiers = build_ticker_tiers(review_queue=[{"ticker": ticker} for ticker in tickers])

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    signal_job = next(job for job in queue["jobs"] if job["kind"] == "signal_lane")

    assert "--max-tickers" not in signal_job["command"]
    assert "--config" in signal_job["command"]
    assert "--no-persist" in signal_job["command"]
    assert "--output-root" in signal_job["command"]
    assert "live-pit" not in signal_job["command"][signal_job["command"].index("--cycle-id") + 1]
    assert signal_job["command"].count("--ticker") == 25


def test_stock_trade_signal_job_uses_pipeline_ready_tickers_during_pull() -> None:
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}, {"ticker": "MSFT"}])

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_refresh_progress={
            "state": "running",
            "current_dataset": "stock_trades",
            "trade_pull": {
                "state": "running",
                "pipeline_ready_tickers": ["AAPL"],
                "pipeline_pending_tickers": ["MSFT"],
            },
        },
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    signal_job = next(job for job in queue["jobs"] if job["kind"] == "signal_lane")

    assert signal_job["status"] == "DUE_NOW"
    assert signal_job["ticker_sample"] == ["AAPL"]
    assert signal_job["command"].count("--ticker") == 1
    assert signal_job["command"][-2:] == ["--ticker", "AAPL"]
    assert "fully complete" in signal_job["reason"]


def test_stock_trade_signal_does_not_bypass_waiting_massive_raw_lanes() -> None:
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}])
    plan = _market_plan("regular_market")
    plan["signal_lanes"] = [
        {
            "lane": "block_trade_pressure",
            "dataset": "stock_trades",
            "batch_action": "run_now",
            "priority": 95,
            "cadence_minutes": 5,
            "requires_massive_raw_lanes": [
                "massive_block_trade_feed",
                "massive_live_trade_slices",
            ],
            "reason": "block pressure waits for raw lanes",
        }
    ]
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_block_trade_feed",
                "status": "DUE_NOW",
                "health_status_class": "warn",
            },
            {
                "lane_id": "massive_live_trade_slices",
                "status": "READY",
                "health_status_class": "pass",
            },
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_refresh_progress={
            "state": "running",
            "current_dataset": "stock_trades",
            "trade_pull": {
                "state": "running",
                "pipeline_ready_tickers": ["AAPL"],
            },
        },
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    signal_job = next(job for job in queue["jobs"] if job["kind"] == "signal_lane")
    assert signal_job["status"] == "WAITING"
    assert signal_job["command"] == []
    assert "Waiting for Massive data-source lane" in str(signal_job["reason"])


def test_raw_requirement_gate_does_not_treat_empty_skipped_lane_as_ready() -> None:
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}])
    plan = _market_plan("regular_market")
    plan["signal_lanes"] = [
        {
            "lane": "buy_sell_pressure",
            "dataset": "stock_trades",
            "batch_action": "run_now",
            "priority": 95,
            "cadence_minutes": 5,
            "requires_massive_raw_lanes": ["massive_live_trade_slices"],
            "reason": "buy/sell pressure waits for live slices",
        }
    ]
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "status": "SKIPPED",
                "batch_action": "run_now",
                "ticker_count": 0,
                "fresh_ticker_count": 0,
                "pending_ticker_count": 0,
                "health_status_class": "pass",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    signal_job = next(job for job in queue["jobs"] if job["kind"] == "signal_lane")
    assert signal_job["status"] == "WAITING"
    assert signal_job["command"] == []
    assert "Waiting for Massive data-source lane" in str(signal_job["reason"])


def test_stock_trade_signal_ready_tickers_in_t2_active_universe_are_handed_off() -> None:
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}], active_universe=["AAPL", "MSFT"])

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_refresh_progress={
            "state": "running",
            "current_dataset": "stock_trades",
            "trade_pull": {
                "state": "running",
                "pipeline_ready_tickers": ["MSFT"],
                "pipeline_pending_tickers": ["AAPL"],
            },
        },
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    signal_job = next(job for job in queue["jobs"] if job["kind"] == "signal_lane")

    assert signal_job["status"] == "DUE_NOW"
    assert signal_job["ticker_sample"] == ["MSFT"]
    assert signal_job["command"]
    assert "fully complete" in signal_job["reason"]


def test_stock_trade_signal_job_passes_partial_usable_tickers_during_pull() -> None:
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}, {"ticker": "MSFT"}])

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_refresh_progress={
            "state": "running",
            "current_dataset": "stock_trades",
            "trade_pull": {
                "state": "running",
                "pipeline_ready_tickers": [],
                "pipeline_usable_tickers": ["MSFT"],
                "pipeline_pending_tickers": ["AAPL", "MSFT"],
            },
        },
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    signal_job = next(job for job in queue["jobs"] if job["kind"] == "signal_lane")

    assert signal_job["status"] == "DUE_NOW"
    assert signal_job["ticker_sample"] == ["MSFT"]
    assert signal_job["command"]
    assert "usable live" in signal_job["reason"]


def test_stock_trade_signal_job_waits_for_first_complete_ticker() -> None:
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}])

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_refresh_progress={
            "state": "running",
            "current_dataset": "stock_trades",
            "trade_pull": {"state": "running", "pipeline_ready_tickers": []},
        },
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    signal_job = next(job for job in queue["jobs"] if job["kind"] == "signal_lane")

    assert signal_job["status"] == "WAITING"
    assert signal_job["command"] == []
    assert "first fully completed" in signal_job["reason"]


def test_signal_lane_uses_full_active_universe_when_review_tiers_are_empty() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    signal_job = next(job for job in queue["jobs"] if job["kind"] == "signal_lane")
    dataset_job = next(job for job in queue["jobs"] if job["kind"] == "dataset")

    assert signal_job["status"] == "DUE_NOW"
    assert signal_job["ticker_sample"] == ["AAPL", "MSFT"]
    assert signal_job["command"][-4:] == ["--ticker", "AAPL", "--ticker", "MSFT"]
    assert dataset_job["status"] == "SKIPPED"
    assert dataset_job["command"] == []


def test_scheduler_tradability_blocks_stale_refresh_progress() -> None:
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}])

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_refresh_progress={"state": "stale", "detail": "Refresh heartbeat is stale."},
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    assert queue["tradability"]["state"] == "context_only"
    assert "Refresh heartbeat is stale" in str(queue["tradability"]["detail"])


def test_scheduler_tradability_allows_running_support_refresh_when_execution_inputs_are_fresh() -> (
    None
):
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}])

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_refresh_progress={
            "state": "running",
            "current_dataset": "sec_form4",
            "detail": "Data refresh is loading source datasets.",
        },
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "mode": "paper", "checked_at": NOW.isoformat()},
        now=NOW,
    )

    assert queue["tradability"]["state"] == "tradable"
    assert "fresh enough" in str(queue["tradability"]["detail"])


def test_scheduler_tradability_blocks_running_execution_critical_refresh() -> None:
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}])

    queue = build_scheduler_work_queue(
        _market_plan("regular_market"),
        tiers=tiers,
        data_refresh_progress={
            "state": "running",
            "current_dataset": "stock_trades",
            "detail": "Data refresh is loading stock trades.",
        },
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "mode": "paper", "checked_at": NOW.isoformat()},
        now=NOW,
    )

    assert queue["tradability"]["state"] == "context_only"
    assert "stock trades" in str(queue["tradability"]["detail"])


def test_scheduler_context_uses_data_load_freshness_when_source_rows_are_missing() -> None:
    queue = scheduler_work_queue_context(
        source_health=[],
        data_load_status={
            "state": "ready",
            "datasets": [],
            "freshness_rows": [
                _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
                _source("massive-stock-trades", freshness="STALE", status="STALE"),
            ],
        },
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    gate = queue["execution_freshness_gate"]

    assert gate["ready"] is False
    assert any("massive-stock-trades" in str(check["detail"]) for check in gate["checks"])


def test_scheduler_context_exposes_refresh_rows_for_blocking_source_status() -> None:
    queue = scheduler_work_queue_context(
        source_health=[
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="UNKNOWN", status="STALE"),
        ],
        data_load_status={"state": "ready", "datasets": []},
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    stale_rows = queue["stale_datasets"]

    assert any(row["dataset"] == "stock_trades" for row in stale_rows)
    stock_trade = next(row for row in stale_rows if row["dataset"] == "stock_trades")
    assert stock_trade["status"] == "STALE"
    assert stock_trade["status_class"] == "warn"
    assert "status STALE" in stock_trade["reason"]


def test_scheduler_exposes_massive_orchestrator_lane_status_and_command(
    tmp_path: Path,
) -> None:
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}])
    plan = _market_plan("regular_market")
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep today's Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "signal_lanes": ["buy_sell_pressure", "market_flow_trend"],
                "consumer_signal_lanes": ["buy_sell_pressure", "market_flow_trend"],
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 5,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1",
                "window_label": "2026-05-11",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": str(tmp_path / "massive_live_trade_slices.json"),
                "creates_massive_request": True,
                "reason": "current trading-day trade prints need an update",
            }
        ],
        "derived_signal_lanes": [
            {
                "signal_lane": "buy_sell_pressure",
                "label": "Buy Sell Pressure",
                "requires_raw_lanes": ["massive_live_trade_slices"],
                "batch_action": "waiting_on_raw",
                "reason": "requires raw data",
            }
        ],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    orchestrator = queue["massive_orchestrator"]
    assert isinstance(orchestrator, dict)
    assert orchestrator["lane_count"] == 1
    assert orchestrator["due_now_count"] == 1
    lane = orchestrator["lanes"][0]
    assert lane["status"] == "DUE_NOW"
    assert lane["health_status_class"] == "block"
    assert lane["health_status"] == "UNAVAILABLE"
    assert (
        lane["command"][COMMAND_SCRIPT_INDEX] == "research\\scripts\\pull_massive_stock_trades.py"
    )
    assert lane["command"][lane["command"].index("--lane-id") + 1] == "massive_live_trade_slices"
    assert lane["command"][lane["command"].index("--limit") + 1] == "1000"
    assert lane["batch_ticker_count"] == 1
    assert lane["command_ticker_count"] == 1
    assert lane["command"][-2:] == ["--ticker", "AAPL"]
    assert orchestrator["derived_signal_lanes"][0]["status"] == "WAITING"


def test_scheduler_daily_bars_lane_command_is_lane_owned_and_scoped() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])
    plan = _market_plan("overnight_after_hours", dataset="prices_daily", tickers=("AAPL", "MSFT"))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "overnight_after_hours",
        "lanes": [
            {
                "lane_id": "massive_daily_bars",
                "label": "Daily Bars",
                "purpose": "Load daily OHLCV.",
                "dataset": "prices_daily",
                "raw_source_dataset": "prices_daily",
                "endpoint_family": "grouped_daily_or_aggs",
                "acquisition_mode": "massive_api",
                "command_profile": "prices_daily",
                "batch_action": "run_now",
                "priority": 80,
                "cadence_minutes": 60,
                "max_tickers_per_batch": 1,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 86400,
                "blocks_execution": True,
                "request_budget_label": "1 grouped-daily request per market date",
                "storage_manifest": "research/data/manifests/massive_lanes/massive_daily_bars.json",
                "creates_massive_request": True,
                "reason": "daily bars need an update",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    command = lane["command"]
    assert command[COMMAND_SCRIPT_INDEX] == "research\\scripts\\pull_massive_grouped_daily.py"
    assert "research\\scripts\\run_data_refresh_batch.py" not in command
    assert command[command.index("--lane-id") + 1] == "massive_daily_bars"
    assert command[command.index("--lane-manifest-path") + 1].endswith("massive_daily_bars.json")
    assert command[command.index("--tickers") + 1 :] == ["AAPL", "MSFT"]
    assert lane["batch_ticker_count"] == 2


def test_scheduler_grouped_daily_ignores_ticker_cap_for_full_universe_request() -> None:
    active = [f"T{i:03d}" for i in range(168)]
    tiers = build_ticker_tiers(active_universe=active)
    plan = _market_plan("overnight_after_hours", dataset="prices_daily", tickers=tuple(active))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "overnight_after_hours",
        "lanes": [
            {
                "lane_id": "massive_daily_bars",
                "label": "Daily Bars",
                "purpose": "Load daily OHLCV.",
                "dataset": "prices_daily",
                "raw_source_dataset": "prices_daily",
                "endpoint_family": "grouped_daily_or_aggs",
                "acquisition_mode": "massive_api",
                "command_profile": "prices_daily",
                "batch_action": "run_now",
                "priority": 80,
                "cadence_minutes": 60,
                "max_tickers_per_batch": 100,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 86400,
                "blocks_execution": True,
                "request_budget_label": "1 grouped-daily request per market date",
                "storage_manifest": "research/data/manifests/massive_lanes/massive_daily_bars.json",
                "creates_massive_request": True,
                "reason": "daily bars need an update",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    command = lane["command"]
    selected = command[command.index("--tickers") + 1 :]
    assert selected == active
    assert lane["batch_ticker_count"] == 168


def test_scheduler_daily_bars_repairs_partial_active_universe_even_when_plan_skips(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "massive_daily_bars.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lane_id": "massive_daily_bars",
                "status": "complete",
                "fetched_at": NOW.isoformat(),
                "window": {"start": "2026-05-11", "end": "2026-05-11"},
                "coverage_pct": 100,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "coverage_status": "complete",
                        "complete": True,
                    }
                ],
                "tickers": ["AAPL"],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])
    plan = _market_plan("overnight_after_hours", dataset="prices_daily", tickers=("AAPL", "MSFT"))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "overnight_after_hours",
        "lanes": [
            {
                "lane_id": "massive_daily_bars",
                "label": "Daily Bars",
                "purpose": "Load daily OHLCV.",
                "dataset": "prices_daily",
                "raw_source_dataset": "prices_daily",
                "endpoint_family": "grouped_daily_or_aggs",
                "acquisition_mode": "massive_api",
                "command_profile": "prices_daily",
                "batch_action": "skip",
                "priority": 80,
                "cadence_minutes": 60,
                "max_tickers_per_batch": 100,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 86400,
                "blocks_execution": True,
                "request_budget_label": "1 grouped-daily request per market date",
                "storage_manifest": str(manifest_path),
                "creates_massive_request": True,
                "reason": "daily price manifest covers the requested window",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    command = lane["command"]
    assert lane["status"] == "DUE_NOW"
    assert lane["fresh_ticker_count"] == 1
    assert lane["pending_ticker_count"] == 1
    assert lane["batch_ticker_count"] == 1
    assert "missing 1 active ticker" in lane["reason"]
    assert command[COMMAND_SCRIPT_INDEX] == "research\\scripts\\pull_massive_grouped_daily.py"
    assert command[command.index("--tickers") + 1 :] == ["MSFT"]


def test_scheduler_daily_bars_ignores_bad_current_day_manifest_for_completed_session(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "massive_daily_bars.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lane_id": "massive_daily_bars",
                "status": "partial",
                "fetched_at": NOW.isoformat(),
                "window": {"start": "2026-05-12", "end": "2026-05-12"},
                "coverage_pct": 50,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "coverage_status": "complete",
                        "complete": True,
                    },
                    {
                        "ticker": "MSFT",
                        "coverage_status": "missing",
                        "complete": False,
                    },
                ],
                "tickers": ["AAPL", "MSFT"],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])
    plan = _market_plan("regular_market", dataset="prices_daily", tickers=("AAPL", "MSFT"))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_daily_bars",
                "label": "Daily Bars",
                "purpose": "Load daily OHLCV.",
                "dataset": "prices_daily",
                "raw_source_dataset": "prices_daily",
                "endpoint_family": "grouped_daily_or_aggs",
                "acquisition_mode": "massive_api",
                "command_profile": "prices_daily",
                "batch_action": "defer",
                "priority": 80,
                "cadence_minutes": 60,
                "max_tickers_per_batch": 100,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 86400,
                "blocks_execution": True,
                "request_budget_label": "1 grouped-daily request per market date",
                "storage_manifest": str(manifest_path),
                "creates_massive_request": True,
                "reason": "regular market would normally defer daily bars",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "attention", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    command = lane["command"]
    assert lane["status"] == "DUE_NOW"
    assert lane["fresh_ticker_count"] == 0
    assert command[command.index("--tickers") + 1 :] == ["AAPL", "MSFT"]


def test_scheduler_daily_bars_repairs_partial_active_universe_even_when_deferred(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "massive_daily_bars.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lane_id": "massive_daily_bars",
                "status": "partial_active_universe",
                "fetched_at": NOW.isoformat(),
                "window": {"start": "2026-05-10", "end": "2026-05-10"},
                "coverage_pct": 99,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "coverage_status": "complete",
                        "complete": True,
                    }
                ],
                "tickers": ["AAPL"],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL", "BK"])
    plan = _market_plan("regular_market", dataset="prices_daily", tickers=("AAPL", "BK"))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_daily_bars",
                "label": "Daily Bars",
                "purpose": "Load daily OHLCV.",
                "dataset": "prices_daily",
                "raw_source_dataset": "prices_daily",
                "endpoint_family": "grouped_daily_or_aggs",
                "acquisition_mode": "massive_api",
                "command_profile": "prices_daily",
                "batch_action": "defer",
                "priority": 80,
                "cadence_minutes": 60,
                "max_tickers_per_batch": 100,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-10",
                "end": "2026-05-10",
                "freshness_requirement_seconds": 86400,
                "blocks_execution": True,
                "request_budget_label": "1 grouped-daily request per market date",
                "storage_manifest": str(manifest_path),
                "creates_massive_request": True,
                "reason": "regular market would normally defer daily bars",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "attention", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    command = lane["command"]
    assert lane["status"] == "DUE_NOW"
    assert lane["fresh_ticker_count"] == 1
    assert lane["pending_ticker_count"] == 1
    assert "missing 1 active ticker" in lane["reason"]
    assert command[COMMAND_SCRIPT_INDEX] == "research\\scripts\\pull_massive_grouped_daily.py"
    assert command[command.index("--tickers") + 1 :] == ["BK"]


def test_scheduler_daily_bars_does_not_loop_on_fresh_provider_missing_bar(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "massive_daily_bars.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lane_id": "massive_daily_bars",
                "status": "partial",
                "fetched_at": NOW.isoformat(),
                "window": {"start": "2026-05-10", "end": "2026-05-10"},
                "coverage_pct": 50,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "coverage_status": "complete",
                        "complete": True,
                        "bar_date": "2026-05-10",
                        "requested_date": "2026-05-10",
                    },
                    {
                        "ticker": "BK",
                        "coverage_status": "missing",
                        "complete": False,
                        "requested_date": "2026-05-10",
                    },
                ],
                "issues": [{"ticker": "BK", "reason": "no_daily_bar_available"}],
                "tickers": ["AAPL", "BK"],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL", "BK"])
    plan = _market_plan("regular_market", dataset="prices_daily", tickers=("AAPL", "BK"))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_daily_bars",
                "label": "Daily Bars",
                "purpose": "Load daily OHLCV.",
                "dataset": "prices_daily",
                "raw_source_dataset": "prices_daily",
                "endpoint_family": "grouped_daily_or_aggs",
                "acquisition_mode": "massive_api",
                "command_profile": "prices_daily",
                "batch_action": "defer",
                "priority": 80,
                "cadence_minutes": 60,
                "max_tickers_per_batch": 100,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-10",
                "end": "2026-05-10",
                "freshness_requirement_seconds": 86400,
                "blocks_execution": True,
                "request_budget_label": "1 grouped-daily request per market date",
                "storage_manifest": str(manifest_path),
                "creates_massive_request": True,
                "reason": "regular market would normally defer daily bars",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "attention", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["status"] == "DEFERRED"
    assert lane["fresh_ticker_count"] == 1
    assert lane["pending_ticker_count"] == 1
    assert lane["command"] == []


def test_scheduler_massive_lane_missing_manifest_overrides_generic_source_health() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL"])
    plan = _market_plan("regular_market", tickers=("AAPL",))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep today's Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 5,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": "research/data/manifests/massive_lanes/missing.json",
                "creates_massive_request": True,
                "reason": "current trading-day trade prints need an update",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["health_status"] == "UNAVAILABLE"
    assert lane["health_status_class"] == "block"
    assert "lane manifest is missing" in str(lane["health_detail"])


def test_scheduler_premarket_lane_command_uses_premarket_session() -> None:
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}])
    plan = _market_plan("pre_market")
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "pre_market",
        "lanes": [
            {
                "lane_id": "massive_premarket_trade_slices",
                "label": "Pre-Market Trade Slices",
                "purpose": "Load 04:00-09:30 ET trade activity.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_premarket",
                "batch_action": "run_now",
                "priority": 105,
                "cadence_minutes": 5,
                "max_tickers_per_batch": 30,
                "ticker_tier": "T0/T1",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded pre-market pages",
                "storage_manifest": "research/data/manifests/massive_lanes/massive_premarket_trade_slices.json",
                "creates_massive_request": True,
                "reason": "pre-market trade prints need an update",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    command = queue["massive_orchestrator"]["lanes"][0]["command"]
    assert command[command.index("--lane-id") + 1] == "massive_premarket_trade_slices"
    assert command[command.index("--trade-session") + 1] == "pre_market"


def test_scheduler_suppresses_generic_dataset_pull_when_massive_lane_owns_endpoint() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])
    plan = _market_plan("regular_market", tickers=("AAPL", "MSFT"))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep today's Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 5,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": "research/data/manifests/massive_lanes/massive_live_trade_slices.json",
                "creates_massive_request": True,
                "reason": "current trading-day trade prints need an update",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    dataset_job = next(job for job in queue["jobs"] if job["job_id"] == "dataset:stock_trades")
    massive_job = queue["massive_orchestrator"]["lanes"][0]
    assert dataset_job["status"] == "SKIPPED"
    assert dataset_job["command"] == []
    assert "generic dataset command suppressed" in str(dataset_job["reason"])
    assert massive_job["status"] == "DUE_NOW"
    assert (
        massive_job["command"][COMMAND_SCRIPT_INDEX]
        == "research\\scripts\\pull_massive_stock_trades.py"
    )


def test_scheduler_live_lane_falls_back_to_active_universe_when_t0_t1_empty(
    tmp_path: Path,
) -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT", "NVDA"])
    plan = _market_plan("after_hours")
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "after_hours",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep latest Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 30,
                "max_tickers_per_batch": 2,
                "ticker_tier": "T0/T1",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 1800,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": str(tmp_path / "massive_live_trade_slices.json"),
                "creates_massive_request": True,
                "reason": "Massive trade coverage is missing for the active universe.",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "blocked", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["status"] == "DUE_NOW"
    assert lane["ticker_tier"] == "T0/T1"
    assert lane["ticker_count"] == 3
    assert lane["ticker_sample"] == ["AAPL", "MSFT", "NVDA"]
    assert lane["batch_ticker_count"] == 2
    assert lane["command"][-4:] == ["--ticker", "AAPL", "--ticker", "MSFT"]


def test_scheduler_live_lane_uses_full_active_universe_when_policy_unbounded(
    tmp_path: Path,
) -> None:
    active = [f"T{i:03d}" for i in range(168)]
    tiers = build_ticker_tiers(active_universe=active)
    plan = _market_plan("regular_market", tickers=tuple(active))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep latest Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 5,
                "max_tickers_per_batch": None,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 1800,
                "blocks_execution": True,
                "request_budget_label": "one latest-print page per active ticker",
                "storage_manifest": str(tmp_path / "massive_live_trade_slices.json"),
                "creates_massive_request": True,
                "reason": "Massive trade coverage is missing for the active universe.",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "blocked", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    selected = [
        lane["command"][index + 1]
        for index, token in enumerate(lane["command"])
        if token == "--ticker"
    ]
    assert selected == active
    assert lane["ticker_count"] == 168
    assert lane["batch_ticker_count"] == 168
    assert lane["command_ticker_count"] == 168


def test_scheduler_massive_lane_prioritizes_tier_before_broad_extraction_order() -> None:
    tiers = build_ticker_tiers(
        review_queue=[{"ticker": "NVDA", "human_review_decision": "Pending"}],
        active_universe=["AAPL", "AMZN", "MSFT", "NVDA"],
    )
    plan = _market_plan("regular_market", tickers=("AAPL", "AMZN", "MSFT", "NVDA"))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep today's Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 5,
                "max_tickers_per_batch": 1,
                "ticker_tier": "T0/T1",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": "research/data/manifests/massive_lanes/massive_live_trade_slices.json",
                "creates_massive_request": True,
                "reason": "current trading-day trade prints need an update",
                "tickers": ["AAPL", "AMZN", "MSFT", "NVDA"],
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["ticker_sample"] == ["NVDA"]
    assert lane["command"][-2:] == ["--ticker", "NVDA"]


def test_scheduler_live_lane_command_skips_fresh_manifest_tickers(tmp_path: Path) -> None:
    manifest_path = tmp_path / "massive_live_trade_slices.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "complete",
                "fetched_at": NOW.isoformat(),
                "window": {"start": "2026-05-11", "end": "2026-05-11"},
                "coverage_pct": 50,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-11",
                        "coverage_status": "partial",
                        "downloaded_row_count": 1000,
                        "pages_downloaded": 1,
                        "order": "desc",
                        "updated_at": NOW.isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])
    plan = _market_plan("regular_market")
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep today's Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 5,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": str(manifest_path),
                "creates_massive_request": True,
                "reason": "current trading-day trade prints need an update",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["fresh_ticker_count"] == 1
    assert lane["pending_ticker_count"] == 1
    assert lane["batch_ticker_count"] == 1
    assert lane["command"][-2:] == ["--ticker", "MSFT"]


def test_scheduler_ignores_running_progress_from_old_live_lane_window(
    tmp_path: Path,
) -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])
    plan = _market_plan("closed_weekend", tickers=("AAPL", "MSFT"))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "closed_weekend",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep latest Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 60,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-22",
                "end": "2026-05-22",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": str(tmp_path / "massive_live_trade_slices.json"),
                "creates_massive_request": True,
                "reason": "latest completed session needs coverage",
            }
        ],
        "derived_signal_lanes": [],
    }
    progress = {
        "massive_lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "state": "running",
                "start": "2026-05-15",
                "end": "2026-05-15",
            }
        ],
        "trade_pull": {
            "lane_id": "massive_live_trade_slices",
            "state": "running",
            "start": "2026-05-15",
            "end": "2026-05-15",
        },
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_refresh_progress=progress,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["status"] == "DUE_NOW"
    assert lane["command"][lane["command"].index("--start") + 1] == "2026-05-22"
    assert lane["command"][lane["command"].index("--end") + 1] == "2026-05-22"


def test_scheduler_ignores_running_progress_without_live_lane_window(
    tmp_path: Path,
) -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])
    plan = _market_plan("closed_weekend", tickers=("AAPL", "MSFT"))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "closed_weekend",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep latest Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 60,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-22",
                "end": "2026-05-22",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": str(tmp_path / "massive_live_trade_slices.json"),
                "creates_massive_request": True,
                "reason": "latest completed session needs coverage",
            }
        ],
        "derived_signal_lanes": [],
    }
    progress = {
        "massive_lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "state": "running",
                "ticker_days_processed": 1,
                "ticker_days_total": 2,
            }
        ],
        "trade_pull": {
            "lane_id": "massive_live_trade_slices",
            "state": "running",
            "ticker_days_processed": 1,
            "ticker_days_total": 2,
        },
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_refresh_progress=progress,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["status"] == "DUE_NOW"
    assert lane["command"][lane["command"].index("--start") + 1] == "2026-05-22"
    assert lane["command"][lane["command"].index("--end") + 1] == "2026-05-22"


def test_scheduler_falls_back_to_matching_trade_pull_when_lane_rows_do_not_match(
    tmp_path: Path,
) -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])
    plan = _market_plan("closed_weekend", tickers=("AAPL", "MSFT"))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "closed_weekend",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep latest Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 60,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-22",
                "end": "2026-05-22",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": str(tmp_path / "massive_live_trade_slices.json"),
                "creates_massive_request": True,
                "reason": "latest completed session needs coverage",
            }
        ],
        "derived_signal_lanes": [],
    }
    progress = {
        "massive_lanes": [
            {
                "lane_id": "massive_premarket_trade_slices",
                "state": "running",
                "start": "2026-05-22",
                "end": "2026-05-22",
            }
        ],
        "trade_pull": {
            "lane_id": "massive_live_trade_slices",
            "state": "running",
            "start": "2026-05-22",
            "end": "2026-05-22",
        },
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_refresh_progress=progress,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["status"] == "RUNNING"
    assert lane["command"] == []


def test_scheduler_does_not_repeat_live_lane_failed_tickers_same_window(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "massive_live_trade_slices.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "partial",
                "fetched_at": NOW.isoformat(),
                "window": {"start": "2026-05-22", "end": "2026-05-22"},
                "coverage_pct": 99,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-22",
                        "coverage_status": "partial",
                        "downloaded_row_count": 1000,
                        "pages_downloaded": 1,
                        "order": "desc",
                    },
                    {
                        "ticker": "HON",
                        "trade_date": "2026-05-22",
                        "coverage_status": "failed",
                        "error": "provider returned no readable data",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL", "HON"])
    plan = _market_plan("closed_weekend", tickers=("AAPL", "HON"))
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "closed_weekend",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep latest Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 60,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-22",
                "end": "2026-05-22",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": str(manifest_path),
                "creates_massive_request": True,
                "reason": "latest completed session needs coverage",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=datetime(2026, 5, 24, 14, 0, tzinfo=UTC),
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["fresh_ticker_count"] == 1
    assert lane["pending_ticker_count"] == 1
    assert lane["status"] == "SKIPPED"
    assert lane["command"] == []


def test_scheduler_live_lane_uses_active_tier_when_plan_tickers_are_repair_subset(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "massive_live_trade_slices.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "partial_usable",
                "fetched_at": NOW.isoformat(),
                "window": {"start": "2026-05-11", "end": "2026-05-11"},
                "coverage_pct": 100,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-11",
                        "coverage_status": "partial",
                        "downloaded_row_count": 1000,
                        "pages_downloaded": 1,
                        "order": "desc",
                        "updated_at": NOW.isoformat(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])
    plan = _market_plan("regular_market")
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep today's Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 5,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": str(manifest_path),
                "creates_massive_request": True,
                "reason": "full-depth repair only identified AAPL as partial",
                "tickers": ["AAPL"],
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["ticker_count"] == 2
    assert lane["fresh_ticker_count"] == 1
    assert lane["pending_ticker_count"] == 1
    assert lane["command"][-2:] == ["--ticker", "MSFT"]


def test_scheduler_live_lane_treats_latest_closed_market_partial_slice_as_fresh(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "massive_live_trade_slices.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "partial_usable",
                "fetched_at": "2026-05-15T22:00:00+00:00",
                "window": {"start": "2026-05-15", "end": "2026-05-15"},
                "coverage_pct": 50,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-15",
                        "coverage_status": "partial",
                        "downloaded_row_count": 1000,
                        "pages_downloaded": 1,
                        "order": "desc",
                        "updated_at": "2026-05-15T22:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL", "MSFT"])
    plan = _market_plan(
        "closed_weekend",
        tickers=("AAPL", "MSFT"),
    )
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "closed_weekend",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep latest Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 120,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1/T2",
                "start": "2026-05-15",
                "end": "2026-05-15",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": str(manifest_path),
                "creates_massive_request": True,
                "reason": "latest completed session needs coverage",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["fresh_ticker_count"] == 1
    assert lane["health_status_class"] == "warn"
    assert lane["health_freshness"] == "PARTIAL"
    assert lane["batch_ticker_count"] == 1
    assert lane["command"][-2:] == ["--ticker", "MSFT"]


def test_scheduler_satisfies_live_signal_requirement_with_full_partial_usable_lane(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "massive_live_trade_slices.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "partial_usable",
                "fetched_at": NOW.isoformat(),
                "window": {"start": "2026-05-11", "end": "2026-05-11"},
                "coverage_pct": 100,
                "usable_coverage_pct": 100,
                "complete_coverage_pct": 40,
                "row_count": 2000,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-11",
                        "coverage_status": "partial_usable",
                        "usable_for_live_pipeline": True,
                        "updated_at": NOW.isoformat(),
                    },
                    {
                        "ticker": "MSFT",
                        "trade_date": "2026-05-11",
                        "coverage_status": "partial_usable",
                        "usable_for_live_pipeline": True,
                        "updated_at": NOW.isoformat(),
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(
        review_queue=[{"ticker": "AAPL"}, {"ticker": "MSFT"}],
        active_universe=["AAPL", "MSFT"],
    )
    plan = _market_plan("regular_market")
    plan["signal_lanes"] = [
        {
            "lane": "buy_sell_pressure",
            "dataset": "stock_trades",
            "batch_action": "run_now",
            "priority": 95,
            "cadence_minutes": 5,
            "requires_massive_raw_lanes": ["massive_live_trade_slices"],
            "reason": "buy/sell pressure reads live slices",
        }
    ]
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_live_trade_slices",
                "label": "Live Trade Slices",
                "purpose": "Keep today's Massive trade tape current.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_live",
                "consumer_signal_lanes": ["buy_sell_pressure"],
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 5,
                "max_tickers_per_batch": 30,
                "ticker_tier": "T0/T1",
                "window_label": "2026-05-11",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 300,
                "blocks_execution": True,
                "request_budget_label": "bounded latest-print pages for active tiers",
                "storage_manifest": str(manifest_path),
                "creates_massive_request": True,
                "reason": "current trading-day trade prints need an update",
            }
        ],
        "derived_signal_lanes": [
            {
                "signal_lane": "buy_sell_pressure",
                "label": "Buy Sell Pressure",
                "requires_raw_lanes": ["massive_live_trade_slices"],
                "batch_action": "waiting_on_raw",
                "reason": "requires live slices",
            }
        ],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    live_lane = queue["massive_orchestrator"]["lanes"][0]
    signal_job = next(job for job in queue["jobs"] if job["kind"] == "signal_lane")
    signal_gate = queue["massive_orchestrator"]["derived_signal_lanes"][0]
    assert live_lane["status"] == "SKIPPED"
    assert live_lane["health_status"] == "PARTIAL_USABLE"
    assert live_lane["health_status_class"] == "pass"
    assert live_lane["fresh_ticker_count"] == 2
    assert live_lane["pending_ticker_count"] == 0
    assert live_lane["command"] == []
    assert signal_gate["status"] == "READY"
    assert signal_job["status"] == "DUE_NOW"
    assert signal_job["raw_requirement_status"] == "READY"
    assert signal_job["command"][-4:] == ["--ticker", "AAPL", "--ticker", "MSFT"]


def test_scheduler_backtest_lane_command_writes_lane_manifest() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL"], research_universe=["AAPL"])
    plan = _market_plan("closed_weekend")
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "closed_weekend",
        "lanes": [
            {
                "lane_id": "massive_backtest_trade_tape",
                "label": "Backtest Tape",
                "purpose": "Full-depth historical trades for research.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "trades",
                "acquisition_mode": "massive_api",
                "command_profile": "stock_trades_backfill",
                "batch_action": "run_now",
                "priority": 45,
                "cadence_minutes": 240,
                "max_tickers_per_batch": 1,
                "ticker_tier": "T0/T1/T2/T3",
                "start": "2026-05-08",
                "end": "2026-05-11",
                "storage_manifest": "research/data/manifests/massive_lanes/massive_backtest_trade_tape.json",
                "creates_massive_request": True,
                "reason": "quiet-market repair",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )
    lane = queue["massive_orchestrator"]["lanes"][0]
    command = lane["command"]

    assert command[COMMAND_SCRIPT_INDEX] == "research\\scripts\\backfill_massive_stock_trades.py"
    assert command[command.index("--lane-id") + 1] == "massive_backtest_trade_tape"
    assert command[command.index("--lane-manifest-path") + 1].endswith(
        "massive_backtest_trade_tape.json"
    )
    assert command.count("--ticker") == 1


def test_scheduler_runs_local_block_trade_derivation_when_source_lane_is_newer(
    tmp_path: Path,
) -> None:
    source_manifest = tmp_path / "massive_live_trade_slices.json"
    block_manifest = tmp_path / "massive_block_trade_feed.json"
    source_manifest.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "complete",
                "fetched_at": NOW.isoformat(),
                "window": {"start": "2026-05-11", "end": "2026-05-11"},
                "coverage_pct": 100,
                "row_count": 100,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-11",
                        "coverage_status": "partial",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}])
    plan = _market_plan("regular_market")
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_block_trade_feed",
                "label": "Block Trade Feed",
                "purpose": "Derived block-trade lane.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "local_trade_derivation",
                "acquisition_mode": "local_derivation",
                "command_profile": "derive_block_trades_from_live_slices",
                "batch_action": "derive_from_raw",
                "priority": 98,
                "cadence_minutes": 5,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 600,
                "blocks_execution": True,
                "request_budget_label": "0 Massive requests; consumes live slices",
                "storage_manifest": str(block_manifest),
                "requires_raw_lanes": ["massive_live_trade_slices"],
                "source_lane_manifests": {
                    "massive_live_trade_slices": str(source_manifest),
                },
                "creates_massive_request": False,
                "reason": "derive block feed from current live slices",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    command = lane["command"]
    assert lane["status"] == "DUE_NOW"
    assert lane["creates_massive_request"] is False
    assert command[COMMAND_SCRIPT_INDEX] == "research\\scripts\\derive_massive_block_trade_feed.py"
    assert Path(command[command.index("--source-lane-manifest") + 1]) == source_manifest
    assert Path(command[command.index("--lane-manifest-path") + 1]) == block_manifest
    assert command[-2:] == ["--ticker", "AAPL"]


def test_scheduler_blocks_unsupported_massive_api_lane_without_generic_batch() -> None:
    tiers = build_ticker_tiers(active_universe=["AAPL"])
    plan = _market_plan("regular_market")
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_reference",
                "label": "Reference Lane",
                "purpose": "Pull reference data.",
                "dataset": "reference_data",
                "raw_source_dataset": "reference_data",
                "endpoint_family": "reference",
                "acquisition_mode": "massive_api",
                "command_profile": "reference_data",
                "batch_action": "run_now",
                "priority": 35,
                "cadence_minutes": 1440,
                "max_tickers_per_batch": None,
                "ticker_tier": "T0/T1/T2/T3",
                "start": None,
                "end": None,
                "freshness_requirement_seconds": 604800,
                "blocks_execution": False,
                "request_budget_label": "daily/weekly low-frequency reference pull",
                "storage_manifest": "research/data/manifests/massive_lanes/massive_reference.json",
                "creates_massive_request": True,
                "reason": "reference data needs an update",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=[
            *_fresh_sources(),
            _source("massive-reference", freshness="FRESH", status="HEALTHY"),
        ],
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["status"] == "BLOCKED"
    assert lane["command"] == []
    assert "generic data-refresh batch fallback is disabled" in str(lane["reason"])


def test_scheduler_keeps_local_block_trade_derivation_ready_when_manifest_is_current(
    tmp_path: Path,
) -> None:
    source_manifest = tmp_path / "massive_live_trade_slices.json"
    block_manifest = tmp_path / "massive_block_trade_feed.json"
    source_manifest.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "complete",
                "fetched_at": NOW.isoformat(),
                "window": {"start": "2026-05-11", "end": "2026-05-11"},
                "coverage_pct": 100,
                "row_count": 100,
                "coverage": [{"ticker": "AAPL", "trade_date": "2026-05-11"}],
            }
        ),
        encoding="utf-8",
    )
    block_manifest.write_text(
        json.dumps(
            {
                "lane_id": "massive_block_trade_feed",
                "status": "complete",
                "fetched_at": (NOW + timedelta(seconds=5)).isoformat(),
                "window": {"start": "2026-05-11", "end": "2026-05-11"},
                "coverage_pct": 100,
                "row_count": 3,
                "coverage": [{"ticker": "AAPL", "trade_date": "2026-05-11"}],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}])
    plan = _market_plan("regular_market")
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_block_trade_feed",
                "label": "Block Trade Feed",
                "purpose": "Derived block-trade lane.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "local_trade_derivation",
                "acquisition_mode": "local_derivation",
                "command_profile": "derive_block_trades_from_live_slices",
                "batch_action": "derive_from_raw",
                "priority": 98,
                "cadence_minutes": 5,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 600,
                "blocks_execution": True,
                "request_budget_label": "0 Massive requests; consumes live slices",
                "storage_manifest": str(block_manifest),
                "requires_raw_lanes": ["massive_live_trade_slices"],
                "source_lane_manifests": {
                    "massive_live_trade_slices": str(source_manifest),
                },
                "creates_massive_request": False,
                "reason": "derive block feed from current live slices",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["status"] == "READY_FROM_RAW"
    assert lane["command"] == []
    assert lane["eta_seconds"] == 0


def test_scheduler_runs_local_derivation_from_partial_usable_source_lane(
    tmp_path: Path,
) -> None:
    source_manifest = tmp_path / "massive_live_trade_slices.json"
    block_manifest = tmp_path / "massive_block_trade_feed.json"
    source_manifest.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "status": "partial_usable",
                "fetched_at": NOW.isoformat(),
                "window": {"start": "2026-05-11", "end": "2026-05-11"},
                "coverage_pct": 100,
                "row_count": 100,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-11",
                        "coverage_status": "partial_usable",
                        "usable_for_live_pipeline": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(review_queue=[{"ticker": "AAPL"}])
    plan = _market_plan("regular_market")
    plan["massive_orchestrator"] = {
        "provider": "massive",
        "market_phase": "regular_market",
        "lanes": [
            {
                "lane_id": "massive_block_trade_feed",
                "label": "Block Trade Feed",
                "purpose": "Derived block-trade lane.",
                "dataset": "stock_trades",
                "raw_source_dataset": "stock_trades",
                "endpoint_family": "local_trade_derivation",
                "acquisition_mode": "local_derivation",
                "command_profile": "derive_block_trades_from_live_slices",
                "batch_action": "derive_from_raw",
                "priority": 98,
                "cadence_minutes": 5,
                "max_tickers_per_batch": 15,
                "ticker_tier": "T0/T1",
                "start": "2026-05-11",
                "end": "2026-05-11",
                "freshness_requirement_seconds": 600,
                "blocks_execution": True,
                "request_budget_label": "0 Massive requests; consumes live slices",
                "storage_manifest": str(block_manifest),
                "requires_raw_lanes": ["massive_live_trade_slices"],
                "source_lane_manifests": {
                    "massive_live_trade_slices": str(source_manifest),
                },
                "creates_massive_request": False,
                "reason": "derive block feed from current live slices",
            }
        ],
        "derived_signal_lanes": [],
    }

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        now=NOW,
    )

    lane = queue["massive_orchestrator"]["lanes"][0]
    assert lane["status"] == "DUE_NOW"
    assert (
        lane["command"][COMMAND_SCRIPT_INDEX]
        == "research\\scripts\\derive_massive_block_trade_feed.py"
    )
    assert lane["command"][-2:] == ["--ticker", "AAPL"]


def test_scheduler_does_not_run_interactive_subscription_email_login_headlessly(
    tmp_path: Path,
) -> None:
    email_config = tmp_path / "subscription-email.local.json"
    live_config = tmp_path / "live-refresh.local.json"
    email_config.write_text(
        json.dumps({"article_login_preflight_required": True}),
        encoding="utf-8",
    )
    live_config.write_text(
        json.dumps({"subscription_email_config": str(email_config)}),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL"])
    plan = _market_plan("regular_market", dataset="subscription_emails")

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        config_path=live_config,
        now=NOW,
    )

    job = next(item for item in queue["jobs"] if item["job_id"] == "dataset:subscription_emails")
    assert job["status"] == "WAITING"
    assert job["command"] == []
    assert "User login is required" in str(job["reason"])


def test_scheduler_infers_subscription_email_login_gate_from_protected_links(
    tmp_path: Path,
) -> None:
    email_config = tmp_path / "subscription-email.local.json"
    live_config = tmp_path / "live-refresh.local.json"
    email_config.write_text(
        json.dumps(
            {
                "follow_article_links": True,
                "enabled_services": ["seeking_alpha"],
                "article_link_domains": ["seekingalpha.com"],
            },
        ),
        encoding="utf-8",
    )
    live_config.write_text(
        json.dumps({"subscription_email_config": str(email_config)}),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL"])
    plan = _market_plan("regular_market", dataset="subscription_emails")

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        config_path=live_config,
        now=NOW,
    )

    job = next(item for item in queue["jobs"] if item["job_id"] == "dataset:subscription_emails")
    assert job["status"] == "WAITING"
    assert job["command"] == []
    assert all(
        item["job_id"] != "dataset:subscription_emails"
        for item in queue["next_jobs"]
    )


def test_scheduler_treats_missing_subscription_email_config_as_manual_only(
    tmp_path: Path,
) -> None:
    live_config = tmp_path / "live-refresh.local.json"
    live_config.write_text(
        json.dumps({"subscription_email_config": str(tmp_path / "missing-email-config.json")}),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL"])
    plan = _market_plan("regular_market", dataset="subscription_emails")

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        config_path=live_config,
        now=NOW,
    )

    job = next(item for item in queue["jobs"] if item["job_id"] == "dataset:subscription_emails")
    assert job["status"] == "WAITING"
    assert job["command"] == []


def test_scheduler_treats_omitted_subscription_email_config_as_manual_only(
    tmp_path: Path,
) -> None:
    live_config = tmp_path / "live-refresh.local.json"
    live_config.write_text(json.dumps({}), encoding="utf-8")
    tiers = build_ticker_tiers(active_universe=["AAPL"])
    plan = _market_plan("regular_market", dataset="subscription_emails")

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        config_path=live_config,
        now=NOW,
    )

    job = next(item for item in queue["jobs"] if item["job_id"] == "dataset:subscription_emails")
    assert job["status"] == "WAITING"
    assert job["command"] == []


def test_scheduler_treats_unreadable_refresh_config_as_manual_email_only(
    tmp_path: Path,
) -> None:
    live_config = tmp_path / "bad-live-refresh.local.json"
    live_config.write_text("{not-json", encoding="utf-8")
    tiers = build_ticker_tiers(active_universe=["AAPL"])
    plan = _market_plan("regular_market", dataset="subscription_emails")

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        config_path=live_config,
        now=NOW,
    )

    job = next(item for item in queue["jobs"] if item["job_id"] == "dataset:subscription_emails")
    assert job["status"] == "WAITING"
    assert job["command"] == []


def test_scheduler_treats_string_subscription_email_login_flag_as_manual_only(
    tmp_path: Path,
) -> None:
    email_config = tmp_path / "subscription-email.local.json"
    live_config = tmp_path / "live-refresh.local.json"
    email_config.write_text(
        json.dumps(
            {
                "follow_article_links": True,
                "article_login_preflight_required": "true",
                "article_link_domains": ["seekingalpha.com"],
            },
        ),
        encoding="utf-8",
    )
    live_config.write_text(
        json.dumps({"subscription_email_config": str(email_config)}),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL"])
    plan = _market_plan("regular_market", dataset="subscription_emails")

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        config_path=live_config,
        now=NOW,
    )

    job = next(item for item in queue["jobs"] if item["job_id"] == "dataset:subscription_emails")
    assert job["status"] == "WAITING"
    assert job["command"] == []


def test_scheduler_can_run_non_interactive_subscription_email_refresh(
    tmp_path: Path,
) -> None:
    email_config = tmp_path / "subscription-email.local.json"
    live_config = tmp_path / "live-refresh.local.json"
    email_config.write_text(
        json.dumps(
            {
                "mode": "local_eml",
                "follow_article_links": False,
                "enabled_services": ["zacks"],
            },
        ),
        encoding="utf-8",
    )
    live_config.write_text(
        json.dumps({"subscription_email_config": str(email_config)}),
        encoding="utf-8",
    )
    tiers = build_ticker_tiers(active_universe=["AAPL"])
    plan = _market_plan("regular_market", dataset="subscription_emails")

    queue = build_scheduler_work_queue(
        plan,
        tiers=tiers,
        data_load_status={"state": "ready", "datasets": []},
        source_health=_fresh_sources(),
        broker={"connected": True, "checked_at": NOW.isoformat()},
        config_path=live_config,
        now=NOW,
    )

    job = next(item for item in queue["jobs"] if item["job_id"] == "dataset:subscription_emails")
    assert job["status"] == "DUE_NOW"
    assert job["command"]
    assert queue["next_jobs"][0]["job_id"] == "dataset:subscription_emails"


def test_scheduler_work_queue_repo_root_prefers_container_app_mount(tmp_path: Path) -> None:
    installed_root = tmp_path / "usr" / "local" / "lib" / "python3.14" / "site-packages"
    app_root = tmp_path / "app"
    (installed_root / "research" / "scripts").mkdir(parents=True)
    (app_root / "research" / "scripts").mkdir(parents=True)
    (app_root / "schemas").mkdir()

    assert _resolve_repo_root([installed_root, app_root]) == app_root.resolve()


def _market_plan(
    phase: str,
    *,
    dataset: str = "stock_trades",
    extraction_action: str = "incremental",
    tickers: tuple[str, ...] = (),
    extraction_reason: str = "test extraction",
) -> dict[str, object]:
    return {
        "market_session": {
            "phase": phase,
            "market_date": "2026-05-11",
            "reason": "test phase",
        },
        "datasets": [
            {
                "dataset": dataset,
                "extraction_action": extraction_action,
                "batch_action": "run_now",
                "priority": 100,
                "cadence_minutes": 5,
                "ticker_count": 1,
                "tickers": list(tickers),
                "reason": "test market-flow refresh",
                "extraction_reason": extraction_reason,
            }
        ],
        "signal_lanes": [
            {
                "lane": "abnormal_volume",
                "dataset": "stock_trades",
                "batch_action": "run_now",
                "priority": 95,
                "cadence_minutes": 5,
                "reason": "test signal lane refresh",
            }
        ],
    }


def _fresh_sources() -> list[dict[str, object]]:
    return [
        _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
        _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
    ]


def _source(source: str, *, freshness: str, status: str) -> dict[str, object]:
    return {
        "source": source,
        "freshness": freshness,
        "status": status,
        "checked_at": NOW.isoformat(),
    }
