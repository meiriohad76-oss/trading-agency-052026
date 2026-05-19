from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from data_refresh.stock_trade_safety import stock_trade_safety_reasons
from market_flow.backfill import (
    StockTradeBackfillRequest,
    backfill_status,
    build_stock_trade_backfill_plan,
    stock_trade_coverage,
    write_stock_trade_backfill_plan,
)
from market_flow.storage import load_stock_trade_coverage_metadata, update_stock_trade_coverage_metadata
from research.scripts.backfill_massive_stock_trades import (
    _coverage_issues,
    _validate_lane_invocation,
)

EXPECTED_TRADING_DAYS = 3
EXPECTED_MISSING_TICKER_DAYS = 5
EXPECTED_PLANNED_BATCHES = 3
EXPECTED_SELECTED_BATCHES = 2
EXPECTED_AAPL_APRIL_1_ROWS = 2


def test_stock_trade_backfill_plan_batches_missing_ticker_days(tmp_path: Path) -> None:
    trade_root = tmp_path / "stock_trades"
    _write_trade_partition(trade_root, "AAPL", [date(2026, 4, 6)])

    plan = build_stock_trade_backfill_plan(
        StockTradeBackfillRequest(
            tickers=("AAPL", "MSFT"),
            start=date(2026, 4, 6),
            end=date(2026, 4, 8),
            trade_root=trade_root,
            batch_size=2,
            max_batches=2,
            max_pages_per_day=1,
        )
    )

    assert plan["summary"]["trading_day_count"] == EXPECTED_TRADING_DAYS
    assert plan["summary"]["partial_ticker_days"] == 0
    assert plan["summary"]["missing_ticker_days"] == EXPECTED_MISSING_TICKER_DAYS
    assert plan["summary"]["planned_batch_count"] == EXPECTED_SELECTED_BATCHES
    assert len(plan["deferred_batches"]) == EXPECTED_PLANNED_BATCHES - EXPECTED_SELECTED_BATCHES
    assert plan["batches"][0]["trade_date"] == "2026-04-06"
    assert plan["batches"][0]["tickers"] == ["MSFT"]


def test_stock_trade_backfill_plan_retries_partial_ticker_days(tmp_path: Path) -> None:
    trade_root = tmp_path / "stock_trades"
    _write_trade_partition(trade_root, "AAPL", [date(2026, 4, 6)], mark_complete=False)

    plan = build_stock_trade_backfill_plan(
        StockTradeBackfillRequest(
            tickers=("AAPL",),
            start=date(2026, 4, 6),
            end=date(2026, 4, 6),
            trade_root=trade_root,
            max_batches=1,
        )
    )

    assert plan["summary"]["partial_ticker_days"] == 1
    assert plan["summary"]["missing_ticker_days"] == 0
    assert plan["batches"][0]["tickers"] == ["AAPL"]
    assert "partial" in plan["batches"][0]["reason"]


def test_stock_trade_backfill_recent_first_prioritizes_latest_date(tmp_path: Path) -> None:
    plan = build_stock_trade_backfill_plan(
        StockTradeBackfillRequest(
            tickers=("AAPL",),
            start=date(2026, 4, 6),
            end=date(2026, 4, 8),
            trade_root=tmp_path / "stock_trades",
            recent_first=True,
            max_batches=1,
        )
    )

    assert plan["batches"][0]["trade_date"] == "2026-04-08"


def test_stock_trade_coverage_counts_rows_by_ticker_date(tmp_path: Path) -> None:
    trade_root = tmp_path / "stock_trades"
    _write_trade_partition(
        trade_root,
        "AAPL",
        [date(2026, 4, 1), date(2026, 4, 1), date(2026, 4, 2)],
    )

    coverage = stock_trade_coverage(
        trade_root,
        tickers=("AAPL",),
        start=date(2026, 4, 1),
        end=date(2026, 4, 3),
    )

    assert coverage[("AAPL", date(2026, 4, 1))] == EXPECTED_AAPL_APRIL_1_ROWS
    assert coverage[("AAPL", date(2026, 4, 2))] == 1


def test_stock_trade_backfill_plan_writes_review_artifacts(tmp_path: Path) -> None:
    plan = build_stock_trade_backfill_plan(
        StockTradeBackfillRequest(
            tickers=("AAPL",),
            start=date(2026, 4, 1),
            end=date(2026, 4, 1),
            trade_root=tmp_path / "stock_trades",
        )
    )
    output_root = tmp_path / "results"

    write_stock_trade_backfill_plan(plan, output_root)

    assert (output_root / "stock-trade-backfill-plan.json").is_file()
    assert "T137 Massive Stock-Trade Backfill Plan" in (
        output_root / "stock-trade-backfill-plan.md"
    ).read_text(encoding="utf-8")


def test_backfill_status_remains_partial_when_deferred_backlog_exists(
    tmp_path: Path,
) -> None:
    plan = build_stock_trade_backfill_plan(
        StockTradeBackfillRequest(
            tickers=("AAPL", "MSFT"),
            start=date(2026, 4, 1),
            end=date(2026, 4, 1),
            trade_root=tmp_path / "stock_trades",
            batch_size=1,
            max_batches=1,
        )
    )

    status = backfill_status(
        plan=plan,
        started_at=datetime(2026, 4, 1, tzinfo=UTC),
        finished_at=datetime(2026, 4, 1, tzinfo=UTC),
        batch_results=[
            {
                "batch_id": 1,
                "status": "passed",
                "ticker_day_count": 1,
                "rows_written": 10,
                "issue_count": 0,
            }
        ],
    )

    assert status["verdict"] == "partial"
    assert status["summary"]["deferred_batch_count"] == 1
    assert status["summary"]["estimated_remaining_ticker_days"] == 1


def test_latest_slice_update_does_not_downgrade_complete_coverage(tmp_path: Path) -> None:
    trade_root = tmp_path / "stock_trades"
    update_stock_trade_coverage_metadata(
        trade_root,
        [
            {
                "ticker": "AAPL",
                "trade_date": "2026-04-06",
                "coverage_status": "complete",
                "complete": True,
                "downloaded_row_count": 5000,
                "pages_downloaded": 5,
                "row_count_verified": True,
            }
        ],
    )

    update_stock_trade_coverage_metadata(
        trade_root,
        [
            {
                "ticker": "AAPL",
                "trade_date": "2026-04-06",
                "coverage_status": "partial",
                "complete": False,
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
                "stop_reason": "max_pages_per_day",
            }
        ],
    )

    row = load_stock_trade_coverage_metadata(trade_root)["AAPL|2026-04-06"]

    assert row["coverage_status"] == "complete"
    assert row["complete"] is True
    assert row["downloaded_row_count"] == 5000
    assert row["pages_downloaded"] == 5
    assert row["latest_slice_coverage_status"] == "partial"
    assert row["latest_slice_order"] == "desc"


def test_backfill_status_surfaces_provider_failure_from_coverage() -> None:
    issues = _coverage_issues(
        [
            {
                "ticker": "AAPL",
                "trade_date": "2026-05-15",
                "coverage_status": "partial",
                "stop_reason": (
                    "request_failed_in_window: 403 for "
                    "https://api.polygon.io/v3/trades/AAPL?apiKey=secret-token"
                ),
            }
        ]
    )

    assert issues == [
        {
            "ticker": "AAPL",
            "trade_date": "2026-05-15",
            "reason": (
                "request_failed_in_window: 403 for "
                "https://api.polygon.io/v3/trades/AAPL?apiKey=<redacted>"
            ),
        }
    ]


def test_backfill_script_rejects_non_backtest_lane_id() -> None:
    class Args:
        lane_id = "massive_live_trade_slices"

    try:
        _validate_lane_invocation(Args())
    except SystemExit:
        pass
    else:
        raise AssertionError("backfill script should not write live lane manifests")


def test_t137_direct_stock_trade_guard_blocks_large_live_refresh() -> None:
    reasons = stock_trade_safety_reasons(
        tickers=("AAPL", "MSFT"),
        start=date(2021, 1, 1),
        end=date(2021, 2, 28),
    )

    assert any("direct live refresh spans" in reason for reason in reasons)
    assert any("backfill_massive_stock_trades.py" in reason for reason in reasons)


def test_t137_direct_stock_trade_guard_blocks_uncapped_full_universe_pull() -> None:
    tickers = tuple(f"T{i}" for i in range(40))

    reasons = stock_trade_safety_reasons(
        tickers=tickers,
        start=date(2026, 5, 13),
        end=date(2026, 5, 13),
        unbounded_pages=True,
    )

    assert any("uncapped" in reason for reason in reasons)
    assert any("page-capped live refresh" in reason for reason in reasons)


def _write_trade_partition(
    trade_root: Path,
    ticker: str,
    trade_dates: list[date],
    *,
    mark_complete: bool = True,
) -> None:
    path = trade_root / f"ticker={ticker}" / "year=2026" / "trades.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "ticker": [ticker for _ in trade_dates],
            "trade_date": trade_dates,
        }
    ).to_parquet(path, index=False)
    if mark_complete:
        update_stock_trade_coverage_metadata(
            trade_root,
            [
                {
                    "ticker": ticker,
                    "trade_date": trade_date.isoformat(),
                    "coverage_status": "complete",
                    "complete": True,
                    "downloaded_row_count": trade_dates.count(trade_date),
                    "pages_downloaded": 1,
                }
                for trade_date in sorted(set(trade_dates))
            ],
        )
