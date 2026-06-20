from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from live_runtime.config import DEFAULT_RUNTIME_SIGNALS
from live_runtime.cycle import (
    LlmEnhancedCycleResult,
    build_live_pit_runtime_cycle,
    required_runtime_datasets,
)
from live_runtime.summary import build_live_runtime_summary, summary_to_markdown
from pit.manifest import DatasetName
from pit_fixtures import loader_with, price, write_manifest

from agency.services import LlmReviewBatchResult, RuntimeCycleResult

GENERATED_AT = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)  # 22:00 UTC = after bar publication window
EXPECTED_PRICE_SIGNAL_COUNT = 2
EXPECTED_MARKET_FLOW_SIGNAL_COUNT = 8
MIDDAY_GENERATED_AT = datetime(2026, 5, 6, 14, 30, tzinfo=UTC)
WEEKEND_GENERATED_AT = datetime(2026, 5, 9, 10, 30, tzinfo=UTC)
TECHNICAL_PRICE_ROWS = 60
TECHNICAL_PRICE_STEP = 0.8


@pytest.fixture(autouse=True)
def _disable_llm_review_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENCY_ENABLE_LLM_REVIEW", raising=False)


def test_build_live_pit_runtime_cycle_from_price_manifest(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 5), 100.0, date(2026, 5, 5), "a1"),
                    price("AAPL", date(2026, 5, 6), 110.0, date(2026, 5, 6), "a2"),
                    price("MSFT", date(2026, 5, 5), 100.0, date(2026, 5, 5), "m1"),
                    price("MSFT", date(2026, 5, 6), 90.0, date(2026, 5, 6), "m2"),
                ]
            )
        },
    )
    # Set manifest timestamp to today's date (same as generated_at date) so that
    # effective_freshness_timestamp returns checked_at (after bar publication window).
    _set_manifest_max_as_of(
        loader.manifest_root,
        DatasetName.PRICES_DAILY,
        "2026-05-06T22:00:00+00:00",
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-live",
        as_of=date(2026, 5, 6),
        tickers={"AAPL", "MSFT"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )

    assert [report["ticker"] for report in cycle.selection_reports] == ["AAPL", "MSFT"]
    assert cycle.source_health[0]["status"] == "HEALTHY"
    assert (
        build_live_runtime_summary(cycle, persisted=False)["signal_count"]
        == EXPECTED_PRICE_SIGNAL_COUNT
    )
    summary = build_live_runtime_summary(cycle, persisted=False)
    summary["persistence_error"] = "TimeoutError: database unavailable"
    assert "Persistence error: `TimeoutError: database unavailable`" in summary_to_markdown(
        summary
    )


def test_current_date_daily_price_manifest_becomes_healthy_after_bar_publication(
    tmp_path: Path,
) -> None:
    """After 21:15 UTC, today's bars are published and source health becomes HEALTHY."""
    after_close = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)  # 22:00 UTC, after bar publication
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 5), 100.0, date(2026, 5, 5), "a1"),
                    price("AAPL", date(2026, 5, 6), 110.0, date(2026, 5, 6), "a2"),
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-live",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=after_close,
    )
    signals = [
        signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    ]

    assert cycle.source_health[0]["status"] == "HEALTHY"
    assert cycle.source_health[0]["observed_lag_seconds"] == 79200.0
    assert signals
    assert {signal["freshness"] for signal in signals} == {"FRESH"}


def test_recent_daily_price_manifest_stays_fresh_across_weekend(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 7), 100.0, date(2026, 5, 7), "a1"),
                    price("AAPL", date(2026, 5, 8), 110.0, date(2026, 5, 8), "a2"),
                ]
            )
        },
    )
    _set_manifest_max_as_of(
        loader.manifest_root,
        DatasetName.PRICES_DAILY,
        "2026-05-08T00:00:00+00:00",
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-weekend",
        as_of=date(2026, 5, 8),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=WEEKEND_GENERATED_AT,
    )
    signals = [
        signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    ]

    assert cycle.source_health[0]["status"] == "HEALTHY"
    assert signals
    assert {signal["freshness"] for signal in signals} == {"FRESH"}


def test_daily_price_manifest_stays_fresh_across_market_holiday_weekend(
    tmp_path: Path,
) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 6, 17), 100.0, date(2026, 6, 17), "a1"),
                    price("AAPL", date(2026, 6, 18), 110.0, date(2026, 6, 18), "a2"),
                ]
            )
        },
    )
    _set_manifest_max_as_of(
        loader.manifest_root,
        DatasetName.PRICES_DAILY,
        "2026-06-18T00:00:00+00:00",
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-juneteenth-weekend",
        as_of=date(2026, 6, 20),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=datetime(2026, 6, 20, 10, 30, tzinfo=UTC),
    )
    signals = [
        signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    ]

    assert cycle.source_health[0]["status"] == "HEALTHY"
    assert signals
    assert {signal["freshness"] for signal in signals} == {"FRESH"}


def test_old_daily_price_manifest_still_goes_stale(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 1), 100.0, date(2026, 5, 1), "a1"),
                    price("AAPL", date(2026, 5, 2), 110.0, date(2026, 5, 2), "a2"),
                ]
            )
        },
    )
    _set_manifest_max_as_of(
        loader.manifest_root,
        DatasetName.PRICES_DAILY,
        "2026-05-02T00:00:00+00:00",
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-old-prices",
        as_of=date(2026, 5, 2),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=WEEKEND_GENERATED_AT,
    )

    assert cycle.source_health[0]["status"] == "STALE"


def test_weekday_stale_daily_price_manifest_does_not_get_intraday_freshness(
    tmp_path: Path,
) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 8), 100.0, date(2026, 5, 8), "a1"),
                    price("AAPL", date(2026, 5, 11), 110.0, date(2026, 5, 11), "a2"),
                ]
            )
        },
    )
    _set_manifest_max_as_of(
        loader.manifest_root,
        DatasetName.PRICES_DAILY,
        "2026-05-11T00:00:00+00:00",
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-weekday-stale-prices",
        as_of=date(2026, 5, 11),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=datetime(2026, 5, 13, 14, 30, tzinfo=UTC),
    )

    assert cycle.source_health[0]["status"] == "STALE"


def test_live_pit_runtime_cycle_does_not_add_sector_etfs_as_candidates(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("SPY", date(2026, 5, 5), 100.0, date(2026, 5, 5), "s1"),
                    price("SPY", date(2026, 5, 6), 101.0, date(2026, 5, 6), "s2"),
                    price("XLK", date(2026, 5, 5), 100.0, date(2026, 5, 5), "x1"),
                    price("XLK", date(2026, 5, 6), 102.0, date(2026, 5, 6), "x2"),
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-live",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("sector_momentum",),
        generated_at=GENERATED_AT,
    )

    assert [report["ticker"] for report in cycle.selection_reports] == ["AAPL"]
    assert build_live_runtime_summary(cycle, persisted=False)["signal_count"] == 0


def test_live_runtime_summary_marks_unhealthy_sources_blocked() -> None:
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-live",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=Path("missing-manifests"),
        parquet_root=Path("missing-parquet"),
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )

    summary = build_live_runtime_summary(cycle, persisted=False)
    markdown = summary_to_markdown(summary)

    assert summary["verdict"] == "blocked_or_context_only_due_to_source_health"
    assert summary["source_status_counts"] == {"UNAVAILABLE": 1}
    assert "| UNAVAILABLE | 1 |" in markdown


def test_live_runtime_summary_source_health_masks_watch_verdict(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [price("AAPL", date(2026, 5, 6), 100.0, date(2026, 5, 6), "a1")]
            )
        },
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-stale-watch",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )
    cycle = replace(
        cycle,
        source_health=[{**cycle.source_health[0], "status": "STALE"}],
        selection_reports=[
            {
                **cycle.selection_reports[0],
                "final_action": "WATCH",
                "llm_review": {"action": "WATCH"},
            }
        ],
    )

    summary = build_live_runtime_summary(cycle, persisted=False)

    assert summary["verdict"] == "blocked_or_context_only_due_to_source_health"


def test_live_runtime_summary_warns_on_degraded_critical_source_status(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [price("AAPL", date(2026, 5, 6), 100.0, date(2026, 5, 6), "a1")]
            )
        },
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-degraded-watch",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )
    cycle = replace(
        cycle,
        source_health=[{**cycle.source_health[0], "status": "DEGRADED"}],
        selection_reports=[
            {
                **cycle.selection_reports[0],
                "final_action": "WATCH",
                "llm_review": {"action": "WATCH"},
            }
        ],
    )

    summary = build_live_runtime_summary(cycle, persisted=False)

    assert summary["verdict"] == "watch_candidates_available_with_source_warnings"


def test_live_runtime_summary_warns_on_noncritical_stale_sources_with_watch(
    tmp_path: Path,
) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [price("AAPL", date(2026, 5, 6), 100.0, date(2026, 5, 6), "a1")]
            )
        },
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-noncritical-stale-watch",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )
    cycle = replace(
        cycle,
        source_health=[
            cycle.source_health[0],
            {
                **cycle.source_health[0],
                "source": "rss-news",
                "status": "STALE",
                "freshness": "STALE",
            },
        ],
        selection_reports=[
            {
                **cycle.selection_reports[0],
                "final_action": "WATCH",
                "llm_review": {"action": "WATCH"},
            }
        ],
    )

    summary = build_live_runtime_summary(cycle, persisted=False)

    assert summary["verdict"] == "watch_candidates_available_with_source_warnings"


def test_live_runtime_summary_counts_missing_llm_action_as_unknown(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [price("AAPL", date(2026, 5, 6), 100.0, date(2026, 5, 6), "a1")]
            )
        },
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-llm-missing-action",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )
    cycle = replace(
        cycle,
        selection_reports=[
            {
                **cycle.selection_reports[0],
                "llm_review": {"reason": "stubbed or failed review"},
            }
        ],
    )

    summary = build_live_runtime_summary(cycle, persisted=False)

    assert summary["llm_review_counts"] == {"UNKNOWN": 1}


def test_live_runtime_summary_does_not_mark_blocked_cycle_watchable(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [price("AAPL", date(2026, 5, 6), 100.0, date(2026, 5, 6), "a1")]
            )
        },
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-risk-blocked-watch",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )
    cycle = replace(
        cycle,
        selection_reports=[{**cycle.selection_reports[0], "final_action": "WATCH"}],
        risk_decisions=[
            {**cycle.risk_decisions[0], "decision": "BLOCK", "final_action": "WATCH"}
        ],
        execution_previews=[{**cycle.execution_previews[0], "preview_state": "BLOCKED"}],
    )

    summary = build_live_runtime_summary(cycle, persisted=False)

    assert summary["verdict"] == "cycle_blocked_by_risk"


def test_live_runtime_summary_counts_prompt_audit_payloads(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [price("AAPL", date(2026, 5, 6), 100.0, date(2026, 5, 6), "a1")]
            )
        },
    )
    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-llm-audit",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("abnormal_volume",),
        generated_at=GENERATED_AT,
    )
    cycle = replace(
        cycle,
        prompt_audits=[
            {
                "payload": {
                    "response_status": "succeeded",
                    "llm_action": "AGREE",
                }
            }
        ],
    )

    summary = build_live_runtime_summary(cycle, persisted=False)
    markdown = summary_to_markdown(summary)

    assert summary["llm_prompt_status_counts"] == {"succeeded": 1}
    assert summary["llm_prompt_action_counts"] == {"AGREE": 1}
    assert "| succeeded | 1 |" in markdown
    assert "| AGREE | 1 |" in markdown


def test_default_runtime_signals_are_stocks_only() -> None:
    datasets = required_runtime_datasets(DEFAULT_RUNTIME_SIGNALS)

    assert DatasetName.UNUSUAL_ACTIVITY_ALERTS not in datasets
    assert DatasetName.OPTIONS_CHAINS not in datasets


def test_optional_options_lanes_require_options_chain_dataset() -> None:
    datasets = required_runtime_datasets(("options_anomaly", "options_flow"))

    assert datasets == {DatasetName.OPTIONS_CHAINS}


def test_options_signal_freshness_uses_ticker_snapshot_timestamp(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.OPTIONS_CHAINS: pl.DataFrame(
                [
                    option_chain("AAPL", "call", 100, "2026-05-06T13:31:00+00:00"),
                    option_chain("AAPL", "put", 20, "2026-05-06T13:31:00+00:00"),
                    option_chain("MSFT", "call", 20, "2026-05-06T13:45:00+00:00"),
                    option_chain("MSFT", "put", 100, "2026-05-06T13:45:00+00:00"),
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-options",
        as_of=date(2026, 5, 6),
        tickers={"AAPL", "MSFT"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("options_flow",),
        generated_at=MIDDAY_GENERATED_AT,
    )
    signals = {
        signal["ticker"]: signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    }

    assert signals["AAPL"]["provenance"]["timestamp_as_of"] == "2026-05-06T13:31:00+00:00"
    assert signals["MSFT"]["provenance"]["timestamp_as_of"] == "2026-05-06T13:45:00+00:00"


def test_optional_market_flow_lanes_require_stock_trades_dataset() -> None:
    datasets = required_runtime_datasets(
        (
            "buy_sell_pressure",
            "block_trade_pressure",
            "unusual_trade_activity",
            "pre_market_unusual_activity",
            "market_flow_trend",
        )
    )

    assert datasets == {DatasetName.STOCK_TRADES}


def test_optional_subscription_thesis_lane_requires_subscription_email_dataset() -> None:
    datasets = required_runtime_datasets(("subscription_thesis",))

    assert datasets == {DatasetName.SUBSCRIPTION_EMAILS}


def test_live_pit_runtime_cycle_can_emit_technical_analysis_signals(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price(
                        "AAPL",
                        date(2026, 5, 6) - timedelta(days=TECHNICAL_PRICE_ROWS - offset),
                        100.0 + TECHNICAL_PRICE_STEP * offset,
                        date(2026, 5, 6),
                        f"aapl-technical-{offset}",
                    )
                    for offset in range(TECHNICAL_PRICE_ROWS)
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-technical",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("technical_analysis",),
        generated_at=GENERATED_AT,
    )
    signals = [
        signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    ]

    assert signals[0]["lane"] == "technical_analysis"
    assert "Technical analysis: AAPL" in str(signals[0]["summary"])
    assert "technical_analysis_bullish" in signals[0]["reason_codes"]
    sources = {str(row["source"]): row for row in cycle.source_health}
    assert "daily-market-bars" in sources
    assert sources["technical-analysis-worker"]["status"] == sources["daily-market-bars"]["status"]
    assert "technical_analysis: derived from daily-market-bars" in sources[
        "technical-analysis-worker"
    ]["notes"]


def test_live_pit_runtime_cycle_can_emit_market_flow_signals(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    _write_stock_trade_partitions(
        parquet_root,
        manifest_root,
        [
            stock_trade("AAPL", 100_000.0, 1, True),
            stock_trade("MSFT", 100_000.0, -1, True),
        ],
        coverage_status="complete",
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-flow",
        as_of=date(2026, 5, 6),
        tickers={"AAPL", "MSFT"},
        manifest_root=manifest_root,
        parquet_root=parquet_root,
        lanes=(
            "buy_sell_pressure",
            "unusual_trade_activity",
            "pre_market_unusual_activity",
            "market_flow_trend",
        ),
        generated_at=GENERATED_AT,
    )
    summary = build_live_runtime_summary(cycle, persisted=False)

    assert cycle.source_health[0]["source"] == "massive-stock-trades"
    assert summary["signal_count"] == EXPECTED_MARKET_FLOW_SIGNAL_COUNT


def test_live_pit_runtime_cycle_emits_market_flow_for_complete_tickers_only(
    tmp_path: Path,
) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    _write_stock_trade_partitions(
        parquet_root,
        manifest_root,
        [
            stock_trade("AAPL", 100_000.0, 1, True),
            stock_trade("MSFT", 100_000.0, -1, True),
        ],
        coverage_status="complete",
    )
    coverage_path = parquet_root / "stock_trades" / "_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["ticker_days"].pop("MSFT|2026-05-06")
    coverage_path.write_text(json.dumps(coverage), encoding="utf-8")

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-flow-complete-only",
        as_of=date(2026, 5, 6),
        tickers={"AAPL", "MSFT"},
        manifest_root=manifest_root,
        parquet_root=parquet_root,
        lanes=(
            "buy_sell_pressure",
            "unusual_trade_activity",
            "pre_market_unusual_activity",
            "market_flow_trend",
        ),
        generated_at=GENERATED_AT,
    )
    signals = [
        signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    ]

    assert {signal["ticker"] for signal in signals} == {"AAPL"}
    assert {signal["lane"] for signal in signals} == {
        "buy_sell_pressure",
        "unusual_trade_activity",
        "pre_market_unusual_activity",
        "market_flow_trend",
    }


def test_live_pit_runtime_cycle_uses_current_day_market_flow_snapshot_when_full_lookback_missing(
    tmp_path: Path,
) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    _write_stock_trade_partitions(
        parquet_root,
        manifest_root,
        [stock_trade("AAPL", 100_000.0, 1, True)],
        coverage_status="complete",
    )
    coverage_path = parquet_root / "stock_trades" / "_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["ticker_days"].pop("AAPL|2026-05-04")
    coverage["ticker_days"].pop("AAPL|2026-05-05")
    coverage_path.write_text(json.dumps(coverage), encoding="utf-8")

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-flow-current-day-snapshot",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=manifest_root,
        parquet_root=parquet_root,
        lanes=(
            "buy_sell_pressure",
            "block_trade_pressure",
            "unusual_trade_activity",
            "market_flow_trend",
        ),
        generated_at=GENERATED_AT,
    )
    signals = [
        signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    ]

    assert {signal["ticker"] for signal in signals} == {"AAPL"}
    assert {signal["lane"] for signal in signals} == {
        "buy_sell_pressure",
        "block_trade_pressure",
        "unusual_trade_activity",
        "market_flow_trend",
    }


def test_live_pit_runtime_cycle_blocks_stock_trades_without_coverage_metadata(
    tmp_path: Path,
) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    _write_stock_trade_partitions(
        parquet_root,
        manifest_root,
        [stock_trade("AAPL", 100_000.0, 1, True)],
        write_coverage=False,
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-flow-no-coverage",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=manifest_root,
        parquet_root=parquet_root,
        lanes=("buy_sell_pressure", "unusual_trade_activity"),
        generated_at=GENERATED_AT,
    )
    signals = [
        signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    ]

    assert signals == []


def test_live_pit_runtime_cycle_ignores_partial_market_flow_latest_slice(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    trade_root = parquet_root / "stock_trades"
    trade_path = trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet"
    trade_path.parent.mkdir(parents=True)
    manifest_root.mkdir()
    pl.DataFrame([stock_trade("AAPL", 100_000.0, 1, True)]).write_parquet(trade_path)
    (trade_root / "_coverage.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "ticker_days": {
                    "AAPL|2026-05-06": {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-06",
                        "coverage_status": "partial",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    write_manifest(manifest_root, DatasetName.STOCK_TRADES, "stock_trades", 1)

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-flow-partial",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=manifest_root,
        parquet_root=parquet_root,
        lanes=("buy_sell_pressure", "unusual_trade_activity"),
        generated_at=GENERATED_AT,
    )
    signals = [
        signal
        for pack in cycle.evidence_packs
        for bucket in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in pack[bucket]
    ]

    assert signals == []


def test_live_pit_runtime_cycle_keeps_subscription_thesis_context_only(
    tmp_path: Path,
) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.SUBSCRIPTION_EMAILS: pl.DataFrame(
                [
                    subscription_email(
                        "AAPL",
                        "BULLISH",
                        "Linked content thesis: constructive context for AAPL.",
                    )
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-thesis",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("subscription_thesis",),
        generated_at=GENERATED_AT,
    )
    pack = cycle.evidence_packs[0]
    report = cycle.selection_reports[0]

    assert len(pack["context_signals"]) == 1
    assert pack["actionable_signals"] == []
    assert pack["data_quality"]["source_count"] == 0
    assert report["final_action"] == "NO_TRADE"
    assert "Subscription article thesis" in str(pack["context_signals"][0]["summary"])


def test_live_pit_runtime_cycle_reads_stale_subscription_manifest_as_context(
    tmp_path: Path,
) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    parquet_root.mkdir()
    manifest_root.mkdir()
    frame = pl.DataFrame(
        [
            subscription_email(
                "META",
                "BULLISH",
                "Linked content thesis: stale manifest but relevant analyzed article.",
            )
        ]
    )
    parquet_path = parquet_root / "subscription_emails.parquet"
    frame.write_parquet(parquet_path)
    write_manifest(
        manifest_root,
        DatasetName.SUBSCRIPTION_EMAILS,
        parquet_path.name,
        frame.height,
        stale_after="2026-05-06T00:01:00+00:00",
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-stale-thesis",
        as_of=date(2026, 5, 6),
        tickers={"META"},
        manifest_root=manifest_root,
        parquet_root=parquet_root,
        lanes=("subscription_thesis",),
        generated_at=GENERATED_AT,
    )

    pack = cycle.evidence_packs[0]
    assert len(pack["context_signals"]) == 1
    assert pack["context_signals"][0]["lane"] == "subscription_thesis"
    assert "relevant analyzed article" in str(pack["context_signals"][0]["summary"])


def test_live_pit_runtime_cycle_filters_already_consumed_news_rows(tmp_path: Path) -> None:
    ledger_path = tmp_path / "state" / "news_rss_consumed.json"
    ledger_path.parent.mkdir()
    ledger_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": {
                    "news:aapl:old": {
                        "source_id": "news:aapl:old",
                        "cycle_id": "older-cycle",
                        "ticker": "AAPL",
                        "as_of": "2026-05-05T00:00:00+00:00",
                        "used_at": "2026-05-05T13:30:00+00:00",
                        "lane": "news",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    loader = loader_with(
        tmp_path,
        {
            DatasetName.NEWS_RSS: pl.DataFrame(
                [
                    news_row("AAPL", "AAPL upgrade", "news:aapl:old"),
                    news_row("AAPL", "AAPL downgrade after probe", "news:aapl:new"),
                    news_row("MSFT", "MSFT upgrade", "news:msft:new"),
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-news-consumption",
        as_of=date(2026, 5, 6),
        tickers={"AAPL", "MSFT"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("news",),
        generated_at=GENERATED_AT,
        news_consumption_ledger_path=ledger_path,
    )

    by_ticker = {str(item["ticker"]): item for item in cycle.news_consumption_items}
    assert by_ticker == {
        "AAPL": {
            "ticker": "AAPL",
            "source_ids": ["news:aapl:new"],
            "raw_source_ids": ["raw:news:aapl:new"],
        },
        "MSFT": {
            "ticker": "MSFT",
            "source_ids": ["news:msft:new"],
            "raw_source_ids": ["raw:news:msft:new"],
        },
    }


def test_replay_freshness_caps_future_manifest_timestamps(tmp_path: Path) -> None:
    loader = loader_with(
        tmp_path,
        {
            DatasetName.SEC_FORM4: pl.DataFrame(
                [
                    {
                        "ticker": "AAPL",
                        "transaction_date": date(2026, 1, 1),
                        "security_title": "Common Stock",
                        "transaction_code": "P",
                        "shares": 10.0,
                        "price": 100.0,
                        "filing_url": "https://sec.test/form4",
                        "source": "sec",
                        "source_tier": "OFFICIAL_FILING",
                        "source_id": "form4-a",
                        "source_url": "https://sec.test",
                        "timestamp_observed": GENERATED_AT,
                        "timestamp_as_of": date(2026, 1, 1),
                        "freshness": "FRESH",
                        "confidence": 1.0,
                        "verification_level": "CONFIRMED",
                    }
                ]
            )
        },
    )

    cycle = build_live_pit_runtime_cycle(
        cycle_id="cycle-replay",
        as_of=date(2025, 12, 31),
        tickers={"AAPL"},
        manifest_root=loader.manifest_root,
        parquet_root=loader.parquet_root,
        lanes=("insider",),
        generated_at=GENERATED_AT,
        freshness_checked_at=datetime(2025, 12, 31, tzinfo=UTC),
    )

    assert cycle.source_health[0]["status"] == "HEALTHY"


def stock_trade(
    ticker: str,
    notional: float,
    direction: int,
    block: bool,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "trade_date": date(2026, 5, 6),
        "trade_ts": "2026-05-06T13:30:00Z",
        "price": 100.0,
        "size": notional / 100.0,
        "notional": notional,
        "direction": direction,
        "signed_volume": direction * notional / 100.0,
        "signed_notional": direction * notional,
        "session": "REGULAR",
        "is_block_trade": block,
        "is_off_exchange": block,
        "sequence_number": 1,
        "source_id": f"{ticker}-flow",
        "timestamp_as_of": date(2026, 5, 6),
    }


def _write_stock_trade_partitions(
    parquet_root: Path,
    manifest_root: Path,
    rows: list[dict[str, object]],
    *,
    coverage_status: str = "complete",
    write_coverage: bool = True,
) -> None:
    trade_root = parquet_root / "stock_trades"
    manifest_root.mkdir(parents=True, exist_ok=True)
    by_ticker: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_ticker.setdefault(str(row["ticker"]), []).append(row)
    for ticker, ticker_rows in by_ticker.items():
        trade_path = trade_root / f"ticker={ticker}" / "year=2026" / "trades.parquet"
        trade_path.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(ticker_rows).write_parquet(trade_path)
    if write_coverage:
        ticker_days = {}
        for row in rows:
            trade_date = row["trade_date"]
            if not isinstance(trade_date, date):
                continue
            current = trade_date - timedelta(days=2)
            while current <= trade_date:
                if current.weekday() < 5:
                    ticker_days[f"{row['ticker']}|{current}"] = {
                        "ticker": row["ticker"],
                        "trade_date": str(current),
                        "coverage_status": coverage_status,
                    }
                current += timedelta(days=1)
        (trade_root / "_coverage.json").write_text(
            json.dumps({"schema_version": "0.1.0", "ticker_days": ticker_days}),
            encoding="utf-8",
        )
    write_manifest(manifest_root, DatasetName.STOCK_TRADES, "stock_trades", len(rows))


def option_chain(
    ticker: str,
    option_type: str,
    volume: int,
    timestamp_as_of: str,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "snapshot_date": date(2026, 5, 6),
        "expiration": date(2026, 6, 19),
        "option_type": option_type,
        "strike": 100.0,
        "volume": volume,
        "open_interest": volume * 2,
        "implied_volatility": 0.30,
        "source": "fixture",
        "source_tier": "MARKET_DATA",
        "source_id": f"{ticker}-{option_type}",
        "source_url": None,
        "timestamp_observed": GENERATED_AT,
        "timestamp_as_of": timestamp_as_of,
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "INFERRED",
    }


def subscription_email(ticker: str, direction: str, summary: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "service": "seeking_alpha",
        "services": ["seeking_alpha"],
        "event_type": "sa_analyst_article",
        "event_types": ["sa_analyst_article"],
        "direction": direction,
        "title": "Safe hashed title only",
        "source_refs": [],
        "source": "seeking_alpha-email",
        "source_tier": "PAID_SUB_EMAIL",
        "source_id": f"{ticker}-subscription-thesis",
        "source_url": "https://seekingalpha.com/article/fixture",
        "message_id_hash": f"{ticker}-message",
        "sender_domain": "email.seekingalpha.com",
        "received_at": date(2026, 5, 6),
        "linked_content_status": "article_analyzed",
        "linked_content_url": "https://seekingalpha.com/article/fixture",
        "linked_content_title_hash": "titlehash",
        "linked_content_summary": summary,
        "timestamp_observed": GENERATED_AT,
        "timestamp_as_of": date(2026, 5, 6),
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }


def news_row(ticker: str, title: str, source_id: str) -> dict[str, object]:
    return {
        "ticker": ticker,
        "title": title,
        "summary": "",
        "feed_name": "Fixture RSS",
        "url": f"https://news.example.test/{source_id}",
        "raw_source_id": f"raw:{source_id}",
        "ticker_match_status": "resolved",
        "ticker_match_method": "fixture",
        "ticker_match_confidence": 0.95,
        "ticker_match_reason": "fixture row",
        "source": "fixture-rss",
        "source_tier": "RSS_HEADLINE",
        "source_id": source_id,
        "source_url": f"https://news.example.test/{source_id}",
        "timestamp_observed": GENERATED_AT,
        "timestamp_as_of": date(2026, 5, 6),
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }


def _set_manifest_max_as_of(
    manifest_root: Path,
    dataset: DatasetName,
    timestamp: str,
) -> None:
    manifest_path = manifest_root / f"{dataset.value}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["max_timestamp_as_of"] = timestamp
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


# ---------------------------------------------------------------------------
# T137 — structured JSON logging for cycle runs
# ---------------------------------------------------------------------------


def test_cycle_start_log_is_emitted(capsys: pytest.CaptureFixture[str]) -> None:
    """build_live_pit_runtime_cycle prints a JSON cycle_start event on stdout."""
    build_live_pit_runtime_cycle(
        cycle_id="cycle-log-start",
        as_of=date(2026, 5, 6),
        tickers={"AAPL"},
        manifest_root=Path("missing-manifests"),
        parquet_root=Path("missing-parquet"),
        lanes=("fundamentals",),
        generated_at=GENERATED_AT,
    )

    captured = capsys.readouterr()
    start_events = []
    for line in captured.out.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if obj.get("event") == "cycle_start":
                start_events.append(obj)
        except (json.JSONDecodeError, AttributeError):
            pass

    assert start_events, f"No cycle_start log line found in stdout. Got:\n{captured.out!r}"
    evt = start_events[0]
    assert evt["cycle_id"] == "cycle-log-start"
    assert evt["ticker_count"] == 1
    assert "as_of" in evt
    assert "lanes" in evt
    assert "ts" in evt


def test_cycle_complete_log_is_emitted(capsys: pytest.CaptureFixture[str]) -> None:
    """build_live_pit_runtime_cycle prints a JSON cycle_complete event on stdout."""
    build_live_pit_runtime_cycle(
        cycle_id="cycle-log-complete",
        as_of=date(2026, 5, 6),
        tickers={"AAPL", "MSFT"},
        manifest_root=Path("missing-manifests"),
        parquet_root=Path("missing-parquet"),
        lanes=("fundamentals",),
        generated_at=GENERATED_AT,
    )

    captured = capsys.readouterr()
    complete_events = []
    for line in captured.out.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if obj.get("event") == "cycle_complete":
                complete_events.append(obj)
        except (json.JSONDecodeError, AttributeError):
            pass

    assert complete_events, f"No cycle_complete log line found in stdout. Got:\n{captured.out!r}"
    evt = complete_events[0]
    assert evt["cycle_id"] == "cycle-log-complete"
    assert evt["ticker_count"] == 2
    assert "as_of" in evt
    assert "candidate_count" in evt
    assert "ts" in evt


# ---------------------------------------------------------------------------
# T129 — LLM reviewer wiring
# ---------------------------------------------------------------------------


def test_llm_review_is_skipped_when_env_not_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When AGENCY_ENABLE_LLM_REVIEW is absent, the base RuntimeCycleResult is returned
    and review_evidence_packs is never called."""
    monkeypatch.delenv("AGENCY_ENABLE_LLM_REVIEW", raising=False)
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 5), 100.0, date(2026, 5, 5), "a1"),
                    price("AAPL", date(2026, 5, 6), 110.0, date(2026, 5, 6), "a2"),
                    price("MSFT", date(2026, 5, 5), 100.0, date(2026, 5, 5), "m1"),
                    price("MSFT", date(2026, 5, 6), 90.0, date(2026, 5, 6), "m2"),
                ]
            )
        },
    )

    with patch(
        "live_runtime.cycle.review_evidence_packs",
        side_effect=AssertionError("review_evidence_packs must not be called when LLM review is disabled"),
    ):
        result = build_live_pit_runtime_cycle(
            cycle_id="cycle-no-llm",
            as_of=date(2026, 5, 6),
            tickers={"AAPL"},
            manifest_root=loader.manifest_root,
            parquet_root=loader.parquet_root,
            lanes=("abnormal_volume",),
            generated_at=GENERATED_AT,
        )

    assert isinstance(result, RuntimeCycleResult)
    assert not isinstance(result, LlmEnhancedCycleResult)


def test_llm_review_runs_on_watch_candidates_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When AGENCY_ENABLE_LLM_REVIEW=true, review_evidence_packs is called and the result
    is wrapped in LlmEnhancedCycleResult with the batch attached."""
    monkeypatch.setenv("AGENCY_ENABLE_LLM_REVIEW", "true")
    loader = loader_with(
        tmp_path,
        {
            DatasetName.PRICES_DAILY: pl.DataFrame(
                [
                    price("AAPL", date(2026, 5, 5), 100.0, date(2026, 5, 5), "a1"),
                    price("AAPL", date(2026, 5, 6), 110.0, date(2026, 5, 6), "a2"),
                    price("MSFT", date(2026, 5, 5), 100.0, date(2026, 5, 5), "m1"),
                    price("MSFT", date(2026, 5, 6), 90.0, date(2026, 5, 6), "m2"),
                ]
            )
        },
    )

    fake_batch = LlmReviewBatchResult(
        reviews_by_ticker={"AAPL": {"action": "NEEDS_MORE_EVIDENCE", "confidence": 0.8, "rationale": "not enough confirmation", "supporting_factors": [], "concerns": []}},
        lifecycle_events=[],
        prompt_audits=[],
        reviewed_tickers=["AAPL"],
    )

    async def _fake_review_evidence_packs(evidence_packs, *, provider, **kwargs):  # noqa: ANN001
        return fake_batch

    with patch(
        "live_runtime.cycle.review_evidence_packs",
        side_effect=_fake_review_evidence_packs,
    ):
        result = build_live_pit_runtime_cycle(
            cycle_id="cycle-llm-enabled",
            as_of=date(2026, 5, 6),
            tickers={"AAPL", "MSFT"},
            manifest_root=loader.manifest_root,
            parquet_root=loader.parquet_root,
            lanes=("abnormal_volume",),
            generated_at=GENERATED_AT,
        )

    assert isinstance(result, LlmEnhancedCycleResult)
    assert isinstance(result.cycle, RuntimeCycleResult)
    assert result.llm_batch is fake_batch
    assert result.llm_batch.reviewed_tickers == ["AAPL"]
    assert result.cycle.selection_reports[0]["llm_review"]["action"] == "NEEDS_MORE_EVIDENCE"
