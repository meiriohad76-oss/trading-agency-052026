from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from data_refresh.extraction_plan import build_extraction_plan
from data_refresh.signal_lane_policy import lanes_by_cadence, policies_for_lanes
from data_refresh.types import RefreshBatchConfig


def test_extraction_plan_classifies_fast_and_slow_dataset_actions(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "news_rss", fetched_at=datetime(2026, 5, 8, 11, tzinfo=UTC))
    _write_manifest(
        tmp_path,
        "sec_company_facts",
        fetched_at=datetime(2026, 5, 8, 11, tzinfo=UTC),
    )
    _write_ticker_frame(tmp_path, "sec_company_facts", "AAPL")
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2021, 1, 1),
        end=date(2026, 5, 8),
        datasets=("news_rss", "sec_company_facts"),
        tickers=("AAPL",),
        rss_feeds=("Example,AAPL,https://example.test/rss",),
        sec_user_agent="Trading Agency admin@example.com",
    )

    decisions = {
        decision.dataset: decision
        for decision in build_extraction_plan(
            config,
            now=datetime(2026, 5, 8, 12, tzinfo=UTC),
        )
    }

    assert decisions["news_rss"].action == "incremental"
    assert decisions["sec_company_facts"].action == "skip"


def test_signal_lane_policy_marks_market_flow_and_email_as_continuous() -> None:
    lanes = ("subscription_thesis", "block_trade_pressure", "fundamentals")

    grouped = lanes_by_cadence(lanes)
    policies = {policy.lane: policy for policy in policies_for_lanes(lanes)}

    assert grouped["continuous"] == ["subscription_thesis", "block_trade_pressure"]
    assert grouped["scheduled"] == ["fundamentals"]
    assert policies["block_trade_pressure"].dataset == "stock_trades"
    assert policies["fundamentals"].dataset == "sec_company_facts"


def test_stock_trades_updates_same_day_when_intraday_partition_is_stale(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        "stock_trades",
        fetched_at=datetime(2026, 5, 11, 13, 0, tzinfo=UTC),
        max_as_of=datetime(2026, 5, 11, 13, 0, tzinfo=UTC),
        tickers=["AAPL"],
        date_range_end=date(2026, 5, 11),
    )
    _write_stock_trade_coverage(tmp_path, {"AAPL|2026-05-11": "complete"})
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 11),
        end=date(2026, 5, 11),
        stock_trades_start=date(2026, 5, 11),
        stock_trades_end=date(2026, 5, 11),
        datasets=("stock_trades",),
        tickers=("AAPL",),
        massive_credentials_present=True,
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-11T14:00:00+00:00"),
    )[0]

    assert decision.action == "incremental"
    assert decision.start == date(2026, 5, 11)
    assert decision.end == date(2026, 5, 11)
    assert "intraday freshness" in decision.reason


def test_extraction_plan_uses_active_universe_for_implicit_tickers(
    tmp_path: Path,
) -> None:
    _write_universe_membership(
        tmp_path,
        [
            {"ticker": "AAPL", "start_date": date(2019, 1, 1), "end_date": None},
            {"ticker": "MSFT", "start_date": date(2019, 1, 1), "end_date": None},
            {"ticker": "ALXN", "start_date": date(2019, 1, 1), "end_date": date(2021, 7, 21)},
        ],
    )
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 12),
        end=date(2026, 5, 12),
        stock_trades_start=date(2026, 5, 12),
        stock_trades_end=date(2026, 5, 12),
        datasets=("stock_trades",),
        tickers=(),
        massive_credentials_present=True,
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-12T14:00:00+00:00"),
    )[0]

    assert decision.tickers == ("AAPL", "MSFT")


def test_sec_form4_does_not_treat_no_filing_tickers_as_missing_baseline(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        "sec_form4",
        fetched_at=datetime(2026, 5, 17, 10, 0, tzinfo=UTC),
        max_as_of=datetime(2026, 5, 15, 0, 0, tzinfo=UTC),
    )
    _write_ticker_frame(tmp_path, "sec_form4", "HON")
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2021, 1, 1),
        end=date(2026, 5, 15),
        datasets=("sec_form4",),
        tickers=("HON", "NOFILINGS"),
        sec_user_agent="Trading Agency admin@example.com",
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-17T14:00:00+00:00"),
    )[0]

    assert decision.action == "skip"
    assert "fresh enough" in decision.reason
    assert "missing baseline coverage" not in decision.reason


def test_ticker_baseline_coverage_uses_partition_directories(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "stock_trades",
        fetched_at=datetime(2026, 5, 11, 13, 0, tzinfo=UTC),
        max_as_of=datetime(2026, 5, 11, 13, 0, tzinfo=UTC),
    )
    partition = tmp_path / "research" / "data" / "parquet" / "stock_trades" / "ticker=AAPL"
    partition.mkdir(parents=True)
    (partition / "not-a-parquet.parquet").write_text("invalid", encoding="utf-8")
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 11),
        end=date(2026, 5, 12),
        stock_trades_start=date(2026, 5, 12),
        stock_trades_end=date(2026, 5, 12),
        datasets=("stock_trades",),
        tickers=("AAPL",),
        massive_credentials_present=True,
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-12T14:00:00+00:00"),
    )[0]

    assert decision.action == "incremental"
    assert "missing baseline coverage" not in decision.reason


def test_stock_trades_incremental_uses_manifest_range_before_partition_scan(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        "stock_trades",
        fetched_at=datetime(2026, 5, 11, 13, 0, tzinfo=UTC),
        max_as_of=datetime(2026, 5, 11, 13, 0, tzinfo=UTC),
        date_range_end=date(2026, 5, 11),
    )
    partition = tmp_path / "research" / "data" / "parquet" / "stock_trades" / "ticker=AAPL"
    partition.mkdir(parents=True)
    (partition / "huge-invalid-file.parquet").write_text("invalid", encoding="utf-8")
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 11),
        end=date(2026, 5, 12),
        stock_trades_start=date(2026, 5, 11),
        stock_trades_end=date(2026, 5, 12),
        datasets=("stock_trades",),
        tickers=("AAPL",),
        massive_credentials_present=True,
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-12T14:00:00+00:00"),
    )[0]

    assert decision.action == "incremental"
    assert decision.tickers == ("AAPL",)
    assert decision.start == date(2026, 5, 12)


def test_stock_trades_skips_from_manifest_range_without_date_scan(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "stock_trades",
        fetched_at=datetime(2026, 5, 11, 13, 0, tzinfo=UTC),
        max_as_of=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
        date_range_end=date(2026, 5, 12),
    )
    partition = tmp_path / "research" / "data" / "parquet" / "stock_trades" / "ticker=AAPL"
    partition.mkdir(parents=True)
    (partition / "huge-invalid-file.parquet").write_text("invalid", encoding="utf-8")
    _write_stock_trade_coverage(tmp_path, {"AAPL|2026-05-11": "complete", "AAPL|2026-05-12": "complete"})
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 11),
        end=date(2026, 5, 12),
        stock_trades_start=date(2026, 5, 11),
        stock_trades_end=date(2026, 5, 12),
        datasets=("stock_trades",),
        tickers=("AAPL",),
        massive_credentials_present=True,
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-16T14:00:00+00:00"),
    )[0]

    assert decision.action == "skip"
    assert "manifest covers" in decision.reason


def test_stock_trades_manifest_range_without_coverage_metadata_does_not_skip(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        "stock_trades",
        fetched_at=datetime(2026, 5, 11, 13, 0, tzinfo=UTC),
        max_as_of=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
        date_range_end=date(2026, 5, 12),
    )
    partition = tmp_path / "research" / "data" / "parquet" / "stock_trades" / "ticker=AAPL"
    partition.mkdir(parents=True)
    (partition / "huge-invalid-file.parquet").write_text("invalid", encoding="utf-8")
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 11),
        end=date(2026, 5, 12),
        stock_trades_start=date(2026, 5, 11),
        stock_trades_end=date(2026, 5, 12),
        datasets=("stock_trades",),
        tickers=("AAPL",),
        massive_credentials_present=True,
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-16T14:00:00+00:00"),
    )[0]

    assert decision.action == "incremental"
    assert decision.tickers == ("AAPL",)
    assert "missing or failed" in decision.reason


def test_stock_trades_manifest_range_does_not_mask_partial_coverage(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "stock_trades",
        fetched_at=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
        max_as_of=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
        tickers=["AAPL", "MSFT"],
        date_range_end=date(2026, 5, 12),
    )
    _write_stock_trade_coverage(
        tmp_path,
        {
            "AAPL|2026-05-12": "complete",
            "MSFT|2026-05-12": "partial",
        },
    )
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 12),
        end=date(2026, 5, 12),
        stock_trades_start=date(2026, 5, 12),
        stock_trades_end=date(2026, 5, 12),
        datasets=("stock_trades",),
        tickers=("AAPL", "MSFT"),
        massive_credentials_present=True,
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-16T14:00:00+00:00"),
    )[0]

    assert decision.action == "incremental"
    assert decision.tickers == ("MSFT",)
    assert "partial full-depth" in decision.reason


def test_active_stock_trade_repair_prioritizes_missing_over_partial(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        "stock_trades",
        fetched_at=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
        max_as_of=datetime(2026, 5, 12, 13, 58, tzinfo=UTC),
        tickers=["AAPL", "MSFT"],
        date_range_end=date(2026, 5, 12),
    )
    _write_stock_trade_coverage(
        tmp_path,
        {
            "AAPL|2026-05-12": "partial",
        },
    )
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 12),
        end=date(2026, 5, 12),
        stock_trades_start=date(2026, 5, 12),
        stock_trades_end=date(2026, 5, 12),
        datasets=("stock_trades",),
        tickers=("AAPL", "MSFT"),
        massive_credentials_present=True,
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-12T14:00:00+00:00"),
    )[0]

    assert decision.action == "incremental"
    assert decision.tickers == ("MSFT",)
    assert "missing or failed" in decision.reason


def test_active_stock_trade_partial_only_repair_is_deferred(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        "stock_trades",
        fetched_at=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
        max_as_of=datetime(2026, 5, 12, 13, 58, tzinfo=UTC),
        tickers=["AAPL"],
        date_range_end=date(2026, 5, 12),
    )
    _write_stock_trade_coverage(tmp_path, {"AAPL|2026-05-12": "partial"})
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 12),
        end=date(2026, 5, 12),
        stock_trades_start=date(2026, 5, 12),
        stock_trades_end=date(2026, 5, 12),
        datasets=("stock_trades",),
        tickers=("AAPL",),
        massive_credentials_present=True,
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-12T14:00:00+00:00"),
    )[0]

    assert decision.action == "incremental"
    assert decision.tickers == ("AAPL",)
    assert "partial full-depth" in decision.reason


def test_active_stale_stock_trade_refresh_includes_partial_tickers_for_repair(
    tmp_path: Path,
) -> None:
    _write_manifest(
        tmp_path,
        "stock_trades",
        fetched_at=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
        max_as_of=datetime(2026, 5, 12, 13, 58, tzinfo=UTC),
        tickers=["AAPL", "MSFT"],
        date_range_end=date(2026, 5, 12),
    )
    _write_stock_trade_coverage(
        tmp_path,
        {
            "AAPL|2026-05-12": "partial",
            "MSFT|2026-05-12": "complete",
        },
    )
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 12),
        end=date(2026, 5, 12),
        stock_trades_start=date(2026, 5, 12),
        stock_trades_end=date(2026, 5, 12),
        datasets=("stock_trades",),
        tickers=("AAPL", "MSFT"),
        massive_credentials_present=True,
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-12T14:05:00+00:00"),
    )[0]

    assert decision.action == "incremental"
    assert decision.tickers == ("AAPL", "MSFT")
    assert "intraday freshness" in decision.reason


def test_prices_daily_skips_from_manifest_range_without_date_scan(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path,
        "prices_daily",
        fetched_at=datetime(2026, 5, 12, 22, 0, tzinfo=UTC),
        max_as_of=datetime(2026, 5, 12, 0, 0, tzinfo=UTC),
        tickers=["AAPL"],
        date_range_end=date(2026, 5, 12),
    )
    partition = tmp_path / "research" / "data" / "parquet" / "prices_daily" / "ticker=AAPL"
    partition.mkdir(parents=True)
    (partition / "huge-invalid-file.parquet").write_text("invalid", encoding="utf-8")
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 11),
        end=date(2026, 5, 12),
        datasets=("prices_daily",),
        tickers=("AAPL",),
    )

    decision = build_extraction_plan(
        config,
        now=datetime.fromisoformat("2026-05-13T14:00:00+00:00"),
    )[0]

    assert decision.action == "skip"
    assert "manifest covers" in decision.reason


def _write_manifest(
    tmp_path: Path,
    dataset: str,
    *,
    fetched_at: datetime,
    max_as_of: datetime | None = None,
    tickers: list[str] | None = None,
    date_range_end: date | None = None,
) -> None:
    ticker_payload = "" if tickers is None else f', "tickers": {tickers!r}'.replace("'", '"')
    date_range_payload = (
        ""
        if date_range_end is None
        else f', "date_range": {{"start": "2026-05-01", "end": "{date_range_end.isoformat()}"}}'
    )
    manifest_path = tmp_path / "research" / "data" / "manifests" / f"{dataset}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        (
            "{"
            f'"dataset": "{dataset}", '
            '"row_count": 1, '
            f'"fetched_at": "{fetched_at.isoformat()}", '
            f'"max_timestamp_as_of": "{(max_as_of or fetched_at).isoformat()}", '
            '"issues": []'
            f"{ticker_payload}"
            f"{date_range_payload}"
            "}"
        ),
        encoding="utf-8",
    )


def _write_ticker_frame(tmp_path: Path, dataset: str, ticker: str) -> None:
    root = tmp_path / "research" / "data" / "parquet" / dataset / f"ticker={ticker}"
    root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"ticker": [ticker], "period_end": [date(2026, 3, 31)]}).to_parquet(
        root / "rows.parquet",
        index=False,
    )


def _write_universe_membership(
    tmp_path: Path,
    rows: list[dict[str, object]],
) -> None:
    path = tmp_path / "research" / "data" / "parquet" / "universe_membership.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_stock_trade_coverage(
    tmp_path: Path,
    statuses: dict[str, str],
) -> None:
    root = tmp_path / "research" / "data" / "parquet" / "stock_trades"
    root.mkdir(parents=True, exist_ok=True)
    ticker_days = {}
    for key, status in statuses.items():
        ticker, trade_date = key.split("|", 1)
        ticker_days[key] = {
            "ticker": ticker,
            "trade_date": trade_date,
            "coverage_status": status,
        }
    (root / "_coverage.json").write_text(
        (
            '{"schema_version": "0.1.0", "ticker_days": '
            f"{ticker_days!r}".replace("'", '"')
            + "}"
        ),
        encoding="utf-8",
    )
