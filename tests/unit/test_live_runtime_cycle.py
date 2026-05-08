from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
from live_runtime.cycle import build_live_pit_runtime_cycle
from live_runtime.summary import build_live_runtime_summary, summary_to_markdown
from pit.manifest import DatasetName
from pit_fixtures import loader_with, price

GENERATED_AT = datetime(2026, 5, 6, 0, 1, tzinfo=UTC)
EXPECTED_PRICE_SIGNAL_COUNT = 2


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
        lanes=("fundamentals",),
        generated_at=GENERATED_AT,
    )

    summary = build_live_runtime_summary(cycle, persisted=False)
    markdown = summary_to_markdown(summary)

    assert summary["verdict"] == "blocked_or_context_only_due_to_source_health"
    assert summary["source_status_counts"] == {"UNAVAILABLE": 1}
    assert "| UNAVAILABLE | 1 |" in markdown
