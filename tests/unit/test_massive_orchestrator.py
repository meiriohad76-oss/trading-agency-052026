from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from data_refresh.extraction_plan import ExtractionDecision
from data_refresh.market_calendar import EASTERN, classify_market_session
from data_refresh.massive_lane_manifest import (
    read_lane_manifest,
    write_lane_manifest,
)
from data_refresh.massive_orchestrator import (
    DERIVED_SIGNAL_REQUIREMENTS,
    MASSIVE_RAW_LANE_POLICIES,
    build_massive_orchestration_plan,
)
from data_refresh.types import RefreshBatchConfig

RAW_LANE_IDS = {
    "massive_daily_bars",
    "massive_live_trade_slices",
    "massive_premarket_trade_slices",
    "massive_block_trade_feed",
    "massive_backtest_trade_tape",
    "massive_reference",
    "massive_options_flow",
}


def test_raw_lane_registry_is_complete_unique_and_referenced() -> None:
    policies = list(MASSIVE_RAW_LANE_POLICIES)
    lane_ids = [policy.lane_id for policy in policies]
    manifests = [policy.storage_manifest for policy in policies]

    assert set(lane_ids) == RAW_LANE_IDS
    assert len(lane_ids) == len(set(lane_ids))
    assert len(manifests) == len(set(manifests))
    assert all(manifest.startswith("research/data/manifests/massive_lanes/") for manifest in manifests)
    declared = set(lane_ids)
    for signal_lane, required_lanes in DERIVED_SIGNAL_REQUIREMENTS.items():
        assert required_lanes, signal_lane
        assert set(required_lanes).issubset(declared), signal_lane


def test_premarket_orchestrator_splits_raw_and_derived_massive_lanes(
    tmp_path: Path,
) -> None:
    plan = build_massive_orchestration_plan(
        _config(tmp_path),
        session=classify_market_session(datetime(2026, 5, 11, 8, 0, tzinfo=EASTERN)),
        extraction_decisions=_decisions(),
        runtime_lanes=(
            "pre_market_unusual_activity",
            "buy_sell_pressure",
            "block_trade_pressure",
            "unusual_trade_activity",
            "market_flow_trend",
            "technical_analysis",
        ),
    )

    assert plan["market_phase"] == "pre_market"
    assert {row["lane_id"] for row in _rows(plan, "raw_lanes")} == RAW_LANE_IDS
    assert _lane(plan, "massive_premarket_trade_slices")["batch_action"] == "run_now"
    assert _lane(plan, "massive_live_trade_slices")["batch_action"] == "run_now"
    assert _lane(plan, "massive_live_trade_slices")["tickers"] == ["AAPL", "MSFT"]
    assert _lane(plan, "massive_live_trade_slices")["ticker_count"] == 2
    assert _lane(plan, "massive_block_trade_feed")["batch_action"] == "defer"
    assert _lane(plan, "massive_daily_bars")["batch_action"] == "defer"
    assert _lane(plan, "massive_backtest_trade_tape")["batch_action"] == "disabled"
    assert _lane(plan, "massive_block_trade_feed")["creates_massive_request"] is False
    assert plan["execution_blocking_lane_count"] == 2
    assert _signal(plan, "buy_sell_pressure")["requires_raw_lanes"] == [
        "massive_live_trade_slices"
    ]
    assert _signal(plan, "block_trade_pressure")["requires_raw_lanes"] == [
        "massive_block_trade_feed",
        "massive_live_trade_slices",
    ]


def test_regular_market_does_not_duplicate_live_trade_endpoint_for_derived_signals(
    tmp_path: Path,
) -> None:
    plan = build_massive_orchestration_plan(
        _config(tmp_path),
        session=classify_market_session(datetime(2026, 5, 11, 10, 0, tzinfo=EASTERN)),
        extraction_decisions=_decisions(),
        runtime_lanes=(
            "buy_sell_pressure",
            "block_trade_pressure",
            "unusual_trade_activity",
            "market_flow_trend",
        ),
    )

    api_trade_lanes = [
        row["lane_id"]
        for row in _rows(plan, "raw_lanes")
        if row["creates_massive_request"] is True
        and row["raw_source_dataset"] == "stock_trades"
        and row["command_profile"] == "stock_trades_live"
    ]

    assert api_trade_lanes == ["massive_live_trade_slices"]
    assert _lane(plan, "massive_block_trade_feed")["batch_action"] == "derive_from_raw"
    assert _lane(plan, "massive_block_trade_feed")["request_budget_label"].startswith("0 Massive")
    assert _lane(plan, "massive_premarket_trade_slices")["batch_action"] == "disabled"


def test_orchestrator_runs_backtest_repair_only_in_quiet_windows(tmp_path: Path) -> None:
    plan = build_massive_orchestration_plan(
        _config(tmp_path),
        session=classify_market_session(datetime(2026, 5, 9, 10, 0, tzinfo=EASTERN)),
        extraction_decisions=_decisions(),
        runtime_lanes=("backtest_feature_builder", "technical_analysis"),
    )

    assert plan["market_phase"] == "closed_weekend"
    assert _lane(plan, "massive_live_trade_slices")["batch_action"] == "disabled"
    assert _lane(plan, "massive_daily_bars")["batch_action"] == "run_now"
    assert _lane(plan, "massive_backtest_trade_tape")["batch_action"] == "run_now"
    assert _lane(plan, "massive_backtest_trade_tape")["blocks_execution"] is False


def test_orchestrator_repairs_live_slices_in_closed_market_when_required(
    tmp_path: Path,
) -> None:
    plan = build_massive_orchestration_plan(
        _config(tmp_path),
        session=classify_market_session(datetime(2026, 5, 9, 10, 0, tzinfo=EASTERN)),
        extraction_decisions=_decisions(),
        runtime_lanes=(
            "buy_sell_pressure",
            "block_trade_pressure",
            "pre_market_unusual_activity",
        ),
    )

    assert plan["market_phase"] == "closed_weekend"
    assert _lane(plan, "massive_live_trade_slices")["batch_action"] == "run_now"
    assert _lane(plan, "massive_premarket_trade_slices")["batch_action"] == "defer"
    assert "04:00 ET" in _lane(plan, "massive_premarket_trade_slices")["reason"]
    assert _lane(plan, "massive_block_trade_feed")["batch_action"] == "derive_from_raw"
    assert _lane(plan, "massive_live_trade_slices")["max_tickers_per_batch"] == 50
    assert _lane(plan, "massive_premarket_trade_slices")["max_tickers_per_batch"] == 50
    assert plan["execution_blocking_lane_count"] == 2


def test_live_trade_lanes_target_active_universe_not_full_depth_gap_subset(
    tmp_path: Path,
) -> None:
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
        datasets=("stock_trades", "prices_daily"),
        tickers=("AAPL", "MSFT", "NVDA"),
        market_data_provider="massive",
        massive_credentials_present=True,
        stock_trades_start=date(2026, 5, 11),
        stock_trades_end=date(2026, 5, 11),
    )
    stock_trade_repair_decision = ExtractionDecision(
        "stock_trades",
        "incremental",
        "Massive trade coverage has partial full-depth slices for 1 ticker(s)",
        tickers=("MSFT",),
        start=date(2026, 5, 11),
        end=date(2026, 5, 11),
    )

    plan = build_massive_orchestration_plan(
        config,
        session=classify_market_session(datetime(2026, 5, 9, 10, 0, tzinfo=EASTERN)),
        extraction_decisions=(
            stock_trade_repair_decision,
            ExtractionDecision(
                "prices_daily",
                "skip",
                "daily price baseline already covers the requested window",
            ),
        ),
        runtime_lanes=(
            "buy_sell_pressure",
            "pre_market_unusual_activity",
            "backtest_feature_builder",
        ),
    )

    assert _lane(plan, "massive_live_trade_slices")["tickers"] == [
        "AAPL",
        "MSFT",
        "NVDA",
    ]
    assert _lane(plan, "massive_premarket_trade_slices")["tickers"] == [
        "AAPL",
        "MSFT",
        "NVDA",
    ]
    assert _lane(plan, "massive_backtest_trade_tape")["tickers"] == ["MSFT"]


def test_reference_and_options_lanes_are_explicit_not_generic_run_now(
    tmp_path: Path,
) -> None:
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
        datasets=("prices_daily", "stock_trades", "options_chains"),
        tickers=("AAPL", "MSFT"),
        market_data_provider="massive",
        massive_credentials_present=True,
        stock_trades_start=date(2026, 5, 11),
        stock_trades_end=date(2026, 5, 11),
    )

    market_hours = build_massive_orchestration_plan(
        config,
        session=classify_market_session(datetime(2026, 5, 11, 10, 0, tzinfo=EASTERN)),
        extraction_decisions=_decisions(),
        runtime_lanes=("options_flow", "technical_analysis"),
    )
    quiet_hours = build_massive_orchestration_plan(
        config,
        session=classify_market_session(datetime(2026, 5, 9, 10, 0, tzinfo=EASTERN)),
        extraction_decisions=_decisions(),
        runtime_lanes=("options_flow", "technical_analysis"),
    )

    assert _lane(market_hours, "massive_options_flow")["batch_action"] == "blocked"
    assert _lane(market_hours, "massive_reference")["batch_action"] == "defer"
    assert _lane(quiet_hours, "massive_options_flow")["batch_action"] == "defer"
    assert _lane(quiet_hours, "massive_reference")["batch_action"] == "defer"


def test_orchestrator_blocks_required_lanes_without_massive_credentials(
    tmp_path: Path,
) -> None:
    plan = build_massive_orchestration_plan(
        _config(tmp_path, massive_credentials_present=False),
        session=classify_market_session(datetime(2026, 5, 11, 10, 0, tzinfo=EASTERN)),
        extraction_decisions=_decisions(),
        runtime_lanes=("buy_sell_pressure", "technical_analysis"),
    )

    assert _lane(plan, "massive_live_trade_slices")["batch_action"] == "blocked"
    assert _lane(plan, "massive_daily_bars")["batch_action"] == "blocked"
    assert _signal(plan, "buy_sell_pressure")["batch_action"] == "blocked"
    assert plan["blocked_count"] >= 2


def test_market_batching_payload_includes_raw_lanes_and_signal_requirements(
    tmp_path: Path,
) -> None:
    from data_refresh.market_batching import build_market_aware_batch_plan

    plan = build_market_aware_batch_plan(
        _config(tmp_path),
        lanes=("buy_sell_pressure", "block_trade_pressure", "technical_analysis"),
        now=datetime(2026, 5, 11, 10, 0, tzinfo=EASTERN),
    )

    assert "massive_lanes" in plan
    assert "massive_orchestrator" in plan
    assert _lane(plan, "massive_live_trade_slices")["batch_action"] == "run_now"
    signal_row = next(
        row
        for row in plan["signal_lanes"]
        if isinstance(row, dict) and row["lane"] == "block_trade_pressure"
    )
    assert signal_row["requires_massive_raw_lanes"] == [
        "massive_block_trade_feed",
        "massive_live_trade_slices",
    ]
    assert plan["summary"]["run_now_massive_lane_count"] >= 1


def test_lane_manifest_writer_records_lane_level_coverage(tmp_path: Path) -> None:
    path = tmp_path / "massive_lanes" / "massive_live_trade_slices.json"

    payload = write_lane_manifest(
        path,
        lane_id="massive_live_trade_slices",
        dataset="stock_trades",
        raw_source_dataset="stock_trades",
        fetched_at=datetime(2026, 5, 11, 14, 0),
        requested_start=date(2026, 5, 11),
        requested_end=date(2026, 5, 11),
        tickers=("aapl", "MSFT"),
        row_count=10,
        source_manifest="stock_trades.json",
        status="partial",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete"},
            {"ticker": "MSFT", "coverage_status": "partial"},
        ],
        coverage_pct=42,
    )

    assert payload["coverage_pct"] == 42
    assert payload["state"] == "partial"
    assert payload["progress"]["percent_complete"] == 42
    assert payload["progress"]["eta_seconds"] is None
    assert payload["progress"]["eta_label"] == "not available"
    assert payload["reason_code"] == "partial"
    assert payload["last_attempt_at"] == payload["fetched_at"]
    assert payload["next_due_at"] == ""
    assert payload["required_now"] is True
    assert payload["analysis_state"] == "analyzed_needs_refresh"
    assert read_lane_manifest(path)["tickers"] == ["AAPL", "MSFT"]
    assert json.loads(path.read_text(encoding="utf-8"))["lane_id"] == "massive_live_trade_slices"


def test_lane_manifest_writer_can_merge_same_window_batches(tmp_path: Path) -> None:
    path = tmp_path / "massive_lanes" / "massive_daily_bars.json"
    common = {
        "lane_id": "massive_daily_bars",
        "dataset": "prices_daily",
        "raw_source_dataset": "prices_daily",
        "requested_start": date(2026, 5, 19),
        "requested_end": date(2026, 5, 19),
        "source_manifest": "prices_daily.json",
        "status": "complete",
        "merge_existing": True,
    }

    write_lane_manifest(
        path,
        fetched_at=datetime(2026, 5, 20, 3, 0, tzinfo=UTC),
        tickers=("AAPL",),
        row_count=1,
        coverage=[{"ticker": "AAPL", "coverage_status": "complete", "complete": True}],
        **common,
    )
    payload = write_lane_manifest(
        path,
        fetched_at=datetime(2026, 5, 20, 3, 30, tzinfo=UTC),
        tickers=("MSFT",),
        row_count=1,
        coverage=[{"ticker": "MSFT", "coverage_status": "complete", "complete": True}],
        **common,
    )

    assert payload["tickers"] == ["AAPL", "MSFT"]
    assert payload["row_count"] == 2
    assert payload["coverage_pct"] == 100
    assert [row["ticker"] for row in payload["coverage"]] == ["AAPL", "MSFT"]


def test_lane_manifest_writer_preserves_newer_operational_window(tmp_path: Path) -> None:
    path = tmp_path / "massive_lanes" / "massive_live_trade_slices.json"

    current_payload = write_lane_manifest(
        path,
        lane_id="massive_live_trade_slices",
        dataset="stock_trades",
        raw_source_dataset="stock_trades",
        fetched_at=datetime(2026, 5, 22, 13, 25, tzinfo=UTC),
        requested_start=date(2026, 5, 22),
        requested_end=date(2026, 5, 22),
        tickers=("AAPL", "MSFT"),
        row_count=200,
        source_manifest="stock_trades.json",
        status="partial_usable",
        coverage=[
            {"ticker": "AAPL", "trade_date": "2026-05-22", "coverage_status": "partial"},
            {"ticker": "MSFT", "trade_date": "2026-05-22", "coverage_status": "partial"},
        ],
        coverage_pct=100,
    )

    attempted_old_payload = write_lane_manifest(
        path,
        lane_id="massive_live_trade_slices",
        dataset="stock_trades",
        raw_source_dataset="stock_trades",
        fetched_at=datetime(2026, 5, 23, 1, 0, tzinfo=UTC),
        requested_start=date(2026, 5, 15),
        requested_end=date(2026, 5, 15),
        tickers=("AAPL",),
        row_count=10,
        source_manifest="stock_trades.json",
        status="complete",
        coverage=[
            {"ticker": "AAPL", "trade_date": "2026-05-15", "coverage_status": "complete"}
        ],
        coverage_pct=100,
    )

    persisted = read_lane_manifest(path)
    assert persisted["window"] == {"start": "2026-05-22", "end": "2026-05-22"}
    assert persisted["fetched_at"] == current_payload["fetched_at"]
    assert persisted["row_count"] == current_payload["row_count"]
    assert attempted_old_payload["window"] == current_payload["window"]
    superseded_paths = list((path.parent / "_superseded" / path.stem).glob("*.json"))
    assert len(superseded_paths) == 1
    superseded = json.loads(superseded_paths[0].read_text(encoding="utf-8"))
    assert superseded["window"] == {"start": "2026-05-15", "end": "2026-05-15"}
    assert superseded["preserved_window"] == {"start": "2026-05-22", "end": "2026-05-22"}


def _config(
    tmp_path: Path,
    *,
    massive_credentials_present: bool = True,
) -> RefreshBatchConfig:
    return RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
        datasets=("stock_trades", "prices_daily"),
        tickers=("AAPL", "MSFT"),
        market_data_provider="massive",
        massive_credentials_present=massive_credentials_present,
        stock_trades_start=date(2026, 5, 11),
        stock_trades_end=date(2026, 5, 11),
    )


def _decisions() -> tuple[ExtractionDecision, ...]:
    return (
        ExtractionDecision(
            "stock_trades",
            "incremental",
            "current trading-day trade prints need an update",
            tickers=("AAPL", "MSFT"),
            start=date(2026, 5, 11),
            end=date(2026, 5, 11),
        ),
        ExtractionDecision(
            "prices_daily",
            "incremental",
            "daily prices need an update",
            tickers=("AAPL", "MSFT"),
            start=date(2026, 5, 10),
            end=date(2026, 5, 11),
        ),
    )


def _rows(plan: dict[str, object], key: str) -> list[dict[str, object]]:
    rows = plan[key]
    if not isinstance(rows, list):
        raise TypeError(f"{key} must be a list")
    return [row for row in rows if isinstance(row, dict)]


def _lane(plan: dict[str, object], lane_id: str) -> dict[str, object]:
    rows = plan["massive_lanes"] if "massive_lanes" in plan else plan["lanes"]
    if not isinstance(rows, list):
        raise TypeError("massive lanes must be a list")
    for row in rows:
        if isinstance(row, dict) and row.get("lane_id") == lane_id:
            return row
    raise AssertionError(f"missing Massive lane {lane_id}")


def _signal(plan: dict[str, object], signal_lane: str) -> dict[str, object]:
    rows = plan["derived_signal_lanes"]
    if not isinstance(rows, list):
        raise TypeError("derived signal lanes must be a list")
    for row in rows:
        if isinstance(row, dict) and row.get("signal_lane") == signal_lane:
            return row
    raise AssertionError(f"missing derived signal lane {signal_lane}")
