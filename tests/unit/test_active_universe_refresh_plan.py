from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from data_refresh.active_universe_plan import (
    ActiveUniversePlanRequest,
    build_active_universe_refresh_plan,
    write_active_universe_refresh_plan,
)

EXPECTED_ACTIVE_UNIVERSE_COUNT = 3
EXPECTED_PLANNED_PRICES = 2
EXPECTED_STOCK_DEFERRED = 2
EXPECTED_STOCK_BATCHES = 2


def test_active_universe_plan_allocates_massive_budget_to_missing_prices(
    tmp_path: Path,
) -> None:
    _write_universe(tmp_path)
    _write_dataset(tmp_path, "prices_daily", ["AAPL"])
    config_path = _write_config(tmp_path)

    plan = build_active_universe_refresh_plan(
        ActiveUniversePlanRequest(
            repo_root=tmp_path,
            config_path=config_path,
            as_of=date(2026, 5, 8),
            batch_size=2,
            massive_requests_remaining=2,
        )
    )

    assert plan["active_universe_count"] == EXPECTED_ACTIVE_UNIVERSE_COUNT
    assert plan["coverage"]["prices_daily"]["covered_count"] == 1
    assert plan["coverage"]["prices_daily"]["planned_count"] == EXPECTED_PLANNED_PRICES
    assert plan["coverage"]["stock_trades"]["planned_count"] == 1
    assert plan["coverage"]["stock_trades"]["deferred_count"] == EXPECTED_STOCK_DEFERRED
    assert plan["massive_requests_remaining_after_plan"] == 0
    assert plan["coverage"]["prices_daily"]["estimated_massive_requests"] == 1
    price_batch = next(batch for batch in plan["batches"] if batch["dataset"] == "prices_daily")
    assert price_batch["lane_id"] == "massive_daily_bars"
    assert "research\\scripts\\pull_massive_grouped_daily.py" in price_batch["command_text"]
    assert "--date 2026-05-08" in price_batch["command_text"]


def test_active_universe_plan_writes_stock_trade_batches_with_live_window(
    tmp_path: Path,
) -> None:
    _write_universe(tmp_path)
    config_path = _write_config(tmp_path)
    output_root = tmp_path / "results"

    plan = build_active_universe_refresh_plan(
        ActiveUniversePlanRequest(
            repo_root=tmp_path,
            config_path=config_path,
            output_root=output_root,
            as_of=date(2026, 5, 8),
            datasets=("stock_trades",),
            batch_size=2,
            massive_requests_remaining=3,
        )
    )
    write_active_universe_refresh_plan(plan, output_root)

    commands = [batch["command_text"] for batch in plan["batches"]]
    assert len(commands) == EXPECTED_STOCK_BATCHES
    assert "research\\scripts\\backfill_massive_stock_trades.py" in commands[0]
    assert "--lane-id massive_backtest_trade_tape" in commands[0]
    assert "--start 2026-05-08" in commands[0]
    assert "--end 2026-05-08" in commands[0]
    assert "--no-market-aware" not in commands[0]
    assert (output_root / "active-universe-refresh-plan.json").is_file()
    assert (output_root / "active-universe-refresh-plan.md").is_file()


def test_active_universe_plan_advances_stale_stock_trade_window_to_as_of(
    tmp_path: Path,
) -> None:
    _write_universe(tmp_path)
    config_path = _write_config(tmp_path)

    plan = build_active_universe_refresh_plan(
        ActiveUniversePlanRequest(
            repo_root=tmp_path,
            config_path=config_path,
            as_of=date(2026, 5, 11),
            datasets=("stock_trades",),
            batch_size=3,
            massive_requests_remaining=3,
        )
    )

    assert plan["stock_trades_window"]["start"] == "2026-05-11"
    assert plan["stock_trades_window"]["end"] == "2026-05-11"
    assert "--start 2026-05-11" in plan["batches"][0]["command_text"]
    assert "--lane-id massive_backtest_trade_tape" in plan["batches"][0]["command_text"]


def test_active_universe_plan_does_not_treat_stale_price_manifest_as_covered(
    tmp_path: Path,
) -> None:
    _write_universe(tmp_path)
    _write_manifest(
        tmp_path,
        "prices_daily",
        tickers=["AAPL", "MSFT", "NVDA"],
        max_as_of="2026-05-07T00:00:00+00:00",
    )
    config_path = _write_config(tmp_path)

    plan = build_active_universe_refresh_plan(
        ActiveUniversePlanRequest(
            repo_root=tmp_path,
            config_path=config_path,
            as_of=date(2026, 5, 8),
            datasets=("prices_daily",),
            massive_requests_remaining=3,
        )
    )

    assert plan["coverage"]["prices_daily"]["covered_count"] == 0
    assert plan["coverage"]["prices_daily"]["planned_count"] == EXPECTED_ACTIVE_UNIVERSE_COUNT
    assert plan["coverage"]["prices_daily"]["estimated_massive_requests"] == 1


def test_active_universe_plan_uses_one_grouped_daily_request_for_all_missing_prices(
    tmp_path: Path,
) -> None:
    _write_universe(tmp_path)
    config_path = _write_config(tmp_path)

    plan = build_active_universe_refresh_plan(
        ActiveUniversePlanRequest(
            repo_root=tmp_path,
            config_path=config_path,
            as_of=date(2026, 5, 8),
            datasets=("prices_daily",),
            massive_requests_remaining=1,
        )
    )

    assert plan["coverage"]["prices_daily"]["planned_count"] == EXPECTED_ACTIVE_UNIVERSE_COUNT
    assert plan["coverage"]["prices_daily"]["deferred_count"] == 0
    assert plan["coverage"]["prices_daily"]["estimated_massive_requests"] == 1
    assert plan["massive_requests_remaining_after_plan"] == 0


def test_active_universe_plan_estimates_stock_trades_by_trading_days(
    tmp_path: Path,
) -> None:
    _write_universe(tmp_path)
    config_path = _write_config(
        tmp_path,
        stock_trades_start="2026-05-08",
        stock_trades_end="2026-05-11",
    )

    plan = build_active_universe_refresh_plan(
        ActiveUniversePlanRequest(
            repo_root=tmp_path,
            config_path=config_path,
            as_of=date(2026, 5, 11),
            datasets=("stock_trades",),
            batch_size=3,
            massive_requests_remaining=6,
        )
    )

    assert plan["stock_trades_window"]["trading_days"] == 2
    assert plan["coverage"]["stock_trades"]["estimated_massive_requests"] == 6
    assert plan["coverage"]["stock_trades"]["planned_count"] == EXPECTED_ACTIVE_UNIVERSE_COUNT


def test_active_universe_plan_repairs_partial_stock_trade_coverage(
    tmp_path: Path,
) -> None:
    _write_universe(tmp_path)
    _write_stock_trade_manifest(
        tmp_path,
        tickers=["AAPL", "MSFT", "NVDA"],
        start="2026-05-08",
        end="2026-05-08",
    )
    _write_stock_trade_coverage(
        tmp_path,
        {
            "AAPL|2026-05-08": "complete",
            "MSFT|2026-05-08": "partial",
        },
    )
    config_path = _write_config(tmp_path)

    plan = build_active_universe_refresh_plan(
        ActiveUniversePlanRequest(
            repo_root=tmp_path,
            config_path=config_path,
            as_of=date(2026, 5, 8),
            datasets=("stock_trades",),
            massive_requests_remaining=3,
        )
    )

    assert plan["coverage"]["stock_trades"]["covered_count"] == 1
    assert plan["coverage"]["stock_trades"]["planned_count"] == 2
    assert plan["batches"][0]["tickers"] == ["MSFT", "NVDA"]


def test_active_universe_plan_rejects_unknown_dataset(tmp_path: Path) -> None:
    _write_universe(tmp_path)
    config_path = _write_config(tmp_path)

    try:
        build_active_universe_refresh_plan(
            ActiveUniversePlanRequest(
                repo_root=tmp_path,
                config_path=config_path,
                datasets=("stock_trade",),
            )
        )
    except ValueError as exc:
        assert "stock_trade" in str(exc)
    else:
        raise AssertionError("unknown dataset should raise")


def test_active_universe_runner_rejects_stale_direct_stock_trades_batch(
    tmp_path: Path,
) -> None:
    runner = _load_active_universe_runner()
    stale_batch = {
        "batch_id": 4,
        "dataset": "stock_trades",
        "ticker_count": 168,
        "command": [
            "python",
            "research/scripts/run_data_refresh_batch.py",
            "--dataset",
            "stock_trades",
            "--no-market-aware",
        ],
    }

    with pytest.raises(ValueError, match="lane-owned plan"):
        runner._run_batch(
            stale_batch,
            status_path=tmp_path / "status.json",
            completed=[],
        )


def _write_universe(tmp_path: Path) -> None:
    parquet_root = tmp_path / "research" / "data" / "parquet"
    parquet_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {"ticker": "AAPL", "start_date": date(2020, 1, 1), "end_date": None},
            {"ticker": "MSFT", "start_date": date(2020, 1, 1), "end_date": None},
            {"ticker": "NVDA", "start_date": date(2020, 1, 1), "end_date": None},
            {"ticker": "OLD", "start_date": date(2020, 1, 1), "end_date": date(2021, 1, 1)},
        ]
    ).to_parquet(parquet_root / "universe_membership.parquet", index=False)


def _write_dataset(tmp_path: Path, dataset: str, tickers: list[str]) -> None:
    path = tmp_path / "research" / "data" / "parquet" / dataset
    path.mkdir(parents=True)
    pd.DataFrame({"ticker": tickers}).to_parquet(path / "rows.parquet", index=False)


def _write_manifest(
    tmp_path: Path,
    dataset: str,
    *,
    tickers: list[str],
    max_as_of: str,
) -> None:
    path = tmp_path / "research" / "data" / "manifests"
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{dataset}.json").write_text(
        json.dumps(
            {
                "dataset": dataset,
                "tickers": tickers,
                "row_count": len(tickers),
                "max_timestamp_as_of": max_as_of,
            }
        ),
        encoding="utf-8",
    )


def _write_stock_trade_manifest(
    tmp_path: Path,
    *,
    tickers: list[str],
    start: str,
    end: str,
) -> None:
    path = tmp_path / "research" / "data" / "manifests"
    path.mkdir(parents=True, exist_ok=True)
    (path / "stock_trades.json").write_text(
        json.dumps(
            {
                "dataset": "stock_trades",
                "tickers": tickers,
                "row_count": len(tickers),
                "date_range": {"start": start, "end": end},
            }
        ),
        encoding="utf-8",
    )


def _write_stock_trade_coverage(
    tmp_path: Path,
    statuses: dict[str, str],
) -> None:
    path = tmp_path / "research" / "data" / "parquet" / "stock_trades"
    path.mkdir(parents=True, exist_ok=True)
    ticker_days = {}
    for key, status in statuses.items():
        ticker, trade_date = key.split("|", 1)
        ticker_days[key] = {
            "ticker": ticker,
            "trade_date": trade_date,
            "coverage_status": status,
        }
    (path / "_coverage.json").write_text(
        json.dumps({"schema_version": "0.1.0", "ticker_days": ticker_days}),
        encoding="utf-8",
    )


def _write_config(
    tmp_path: Path,
    *,
    stock_trades_start: str = "2026-05-08",
    stock_trades_end: str = "2026-05-08",
) -> Path:
    path = tmp_path / "live-refresh.json"
    path.write_text(
        json.dumps(
            {
                "end": "2026-05-08",
                "market_data_provider": "massive",
                "stock_trades_start": stock_trades_start,
                "stock_trades_end": stock_trades_end,
                "stock_trades_max_pages_per_day": 1,
            }
        ),
        encoding="utf-8",
    )
    return path


def _load_active_universe_runner():
    path = (
        Path(__file__).resolve().parents[2]
        / "research"
        / "scripts"
        / "run_active_universe_refresh_plan.py"
    )
    spec = importlib.util.spec_from_file_location("run_active_universe_refresh_plan", path)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load active-universe plan runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
