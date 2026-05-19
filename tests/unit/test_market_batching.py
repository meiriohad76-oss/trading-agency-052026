from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from data_refresh.market_batching import build_market_aware_batch_plan
from data_refresh.market_calendar import EASTERN
from data_refresh.types import RefreshBatchConfig

FAST_CADENCE_MINUTES = 5


def test_regular_market_batching_prioritizes_trade_prints_and_context(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    plan = build_market_aware_batch_plan(
        config,
        lanes=(
            "block_trade_pressure",
            "buy_sell_pressure",
            "subscription_thesis",
            "fundamentals",
            "technical_analysis",
        ),
        now=datetime(2026, 5, 11, 10, 0, tzinfo=EASTERN),
    )

    assert plan["market_session"]["phase"] == "regular_market"
    assert _dataset(plan, "stock_trades")["batch_action"] == "run_now"
    assert _dataset(plan, "stock_trades")["cadence_minutes"] == FAST_CADENCE_MINUTES
    assert _dataset(plan, "stock_trades")["tickers"] == ["AAPL", "MSFT"]
    assert _dataset(plan, "sec_company_facts")["batch_action"] == "defer"
    assert _lane(plan, "block_trade_pressure")["batch_action"] == "run_now"
    assert _lane(plan, "technical_analysis")["batch_action"] == "defer"


def test_after_hours_batching_allows_daily_bar_and_technical_refresh(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    plan = build_market_aware_batch_plan(
        config,
        lanes=("technical_analysis", "abnormal_volume", "fundamentals"),
        now=datetime(2026, 5, 11, 17, 30, tzinfo=EASTERN),
    )

    assert plan["market_session"]["phase"] == "after_hours"
    assert _dataset(plan, "prices_daily")["batch_action"] == "run_now"
    assert _lane(plan, "technical_analysis")["batch_action"] == "run_now"
    assert _lane(plan, "fundamentals")["batch_action"] == "defer"


def test_before_pre_market_targets_previous_completed_trade_day(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    plan = build_market_aware_batch_plan(
        config,
        lanes=("block_trade_pressure", "technical_analysis"),
        now=datetime(2026, 5, 14, 2, 30, tzinfo=EASTERN),
    )

    assert plan["market_session"]["phase"] == "overnight_before_pre_market"
    assert plan["effective_window"]["end"] == "2026-05-13"
    assert plan["effective_window"]["stock_trades_start"] == "2026-05-13"
    assert plan["effective_window"]["stock_trades_end"] == "2026-05-13"
    assert _dataset(plan, "stock_trades")["batch_action"] == "run_now"
    assert _dataset(plan, "stock_trades")["start"] == "2026-05-13"
    assert _dataset(plan, "stock_trades")["end"] == "2026-05-13"
    assert _dataset(plan, "prices_daily")["batch_action"] == "run_now"
    assert _dataset(plan, "prices_daily")["end"] == "2026-05-13"


def test_closed_weekend_batching_repairs_latest_available_trade_slices(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    plan = build_market_aware_batch_plan(
        config,
        lanes=("block_trade_pressure", "fundamentals", "institutional"),
        now=datetime(2026, 5, 9, 10, 0, tzinfo=EASTERN),
    )

    assert plan["market_session"]["phase"] == "closed_weekend"
    assert _dataset(plan, "stock_trades")["batch_action"] == "run_now"
    assert _dataset(plan, "stock_trades")["max_tickers_per_batch"] == 50
    assert _dataset(plan, "sec_company_facts")["batch_action"] == "run_now"
    assert _lane(plan, "fundamentals")["batch_action"] == "run_now"
    assert _lane(plan, "block_trade_pressure")["batch_action"] == "run_now"


def test_regular_market_defers_form4_baseline_repair(tmp_path: Path) -> None:
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2021, 1, 1),
        end=date(2026, 5, 11),
        datasets=("sec_form4",),
        tickers=("AAPL",),
        sec_user_agent="Trading Agency admin@example.com",
    )

    plan = build_market_aware_batch_plan(
        config,
        lanes=("insider",),
        now=datetime(2026, 5, 11, 10, 0, tzinfo=EASTERN),
    )

    assert _dataset(plan, "sec_form4")["extraction_action"] == "baseline"
    assert _dataset(plan, "sec_form4")["batch_action"] == "defer"
    assert "off-hours baseline repair" in str(_dataset(plan, "sec_form4")["reason"])


def _config(tmp_path: Path) -> RefreshBatchConfig:
    return RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 1),
        end=date(2026, 5, 11),
        datasets=(
            "stock_trades",
            "prices_daily",
            "sec_company_facts",
            "news_rss",
            "subscription_emails",
        ),
        tickers=("AAPL", "MSFT"),
        rss_feeds=("Example,https://example.test/rss",),
        subscription_email_config=tmp_path / "subscription-email.local.json",
        sec_user_agent="Trading Agency admin@example.com",
        market_data_provider="massive",
        massive_credentials_present=True,
    )


def _dataset(plan: dict[str, object], name: str) -> dict[str, object]:
    rows = plan["datasets"]
    if not isinstance(rows, list):
        raise TypeError("datasets must be a list")
    for row in rows:
        if isinstance(row, dict) and row.get("dataset") == name:
            return row
    raise AssertionError(f"missing dataset {name}")


def _lane(plan: dict[str, object], name: str) -> dict[str, object]:
    rows = plan["signal_lanes"]
    if not isinstance(rows, list):
        raise TypeError("signal_lanes must be a list")
    for row in rows:
        if isinstance(row, dict) and row.get("lane") == name:
            return row
    raise AssertionError(f"missing lane {name}")
