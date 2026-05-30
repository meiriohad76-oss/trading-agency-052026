from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import agency.api.health as health_module
import agency.runtime.data_load_status as data_load_status_module
from agency.app import create_app
from agency.runtime.data_load_status import load_data_load_status

HTTP_OK = 200
FULL_PERCENT = 100


def test_data_load_status_is_ready_with_full_core_and_sparse_context(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "sec_company_facts",
        row_count=100,
        path="sec_company_facts",
    )
    _partition(paths["parquet_root"], "sec_company_facts", "AAPL")
    _partition(paths["parquet_root"], "sec_company_facts", "MSFT")
    _write_manifest(paths["manifest_root"], "sec_form4", row_count=12, path="sec_form4")
    _partition(paths["parquet_root"], "sec_form4", "AAPL")
    _write_manifest(paths["manifest_root"], "sec_13f", row_count=4, path="sec_13f")
    _write_manifest(paths["manifest_root"], "news_rss", row_count=2)
    _write_manifest(paths["manifest_root"], "subscription_emails", row_count=1)
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
            "fundamentals": 2,
            "insider": 2,
            "institutional": 1,
            "news": 1,
            "subscription_thesis": 1,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
            _source("sec-company-facts", freshness="FRESH", status="HEALTHY"),
            _source("sec-form4", freshness="FRESH", status="HEALTHY"),
            _source("sec-13f", freshness="FRESH", status="HEALTHY"),
            _source("rss-news", freshness="FRESH", status="HEALTHY"),
            _source("subscription-email-thesis", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["state"] == "ready"
    assert status["ready"] is True
    assert status["review_operational_ready"] is True
    assert status["tradable_ready"] is True
    assert status["mode"] == "full_universe_tradable"
    assert status["core_dataset_percent"] == FULL_PERCENT
    assert status["critical_lane_percent"] == FULL_PERCENT
    assert status["blockers"] == []
    assert _lane(status, "sector_momentum")["status"] == "ready"
    assert _lane(status, "sector_momentum")["expected_count"] is None
    assert _lane(status, "sector_momentum")["analysis_state"] == "analyzed_current"
    assert _dataset(status, "sec_company_facts")["coverage_pct"] == FULL_PERCENT
    assert _dataset(status, "sec_form4")["status"] == "ready"
    assert _dataset(status, "sec_form4")["analysis_state"] == "analyzed_current"
    assert _lane_state(status, "technical_analysis")["status_label"] == (
        "Ready for paper execution"
    )


def test_forward_fundamentals_health_warns_without_blocking_core_readiness(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    monkeypatch.setattr(
        data_load_status_module,
        "DEFAULT_FORWARD_FUNDAMENTALS_STATE_ROOT",
        tmp_path / "forward_state",
    )
    _write_manifest(paths["manifest_root"], "prices_daily", row_count=20, tickers=["AAPL", "MSFT"])
    _write_manifest(paths["manifest_root"], "stock_trades", row_count=200, tickers=["AAPL", "MSFT"])
    _write_manifest(paths["manifest_root"], "sec_company_facts", row_count=100, path="sec_company_facts")
    _partition(paths["parquet_root"], "sec_company_facts", "AAPL")
    _partition(paths["parquet_root"], "sec_company_facts", "MSFT")
    _write_manifest(paths["manifest_root"], "sec_form4", row_count=12, path="sec_form4")
    _partition(paths["parquet_root"], "sec_form4", "AAPL")
    _write_manifest(paths["manifest_root"], "sec_13f", row_count=4, path="sec_13f")
    _write_manifest(paths["manifest_root"], "news_rss", row_count=2)
    _write_manifest(paths["manifest_root"], "subscription_emails", row_count=1)
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
            "fundamentals": 2,
            "insider": 2,
            "institutional": 1,
            "news": 1,
            "subscription_thesis": 1,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
            _source("sec-company-facts", freshness="FRESH", status="HEALTHY"),
            _source("sec-form4", freshness="FRESH", status="HEALTHY"),
            _source("sec-13f", freshness="FRESH", status="HEALTHY"),
            _source("rss-news", freshness="FRESH", status="HEALTHY"),
            _source("subscription-email-thesis", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    forward = _source_row(status, "forward-fundamentals")
    assert status["state"] == "ready"
    assert status["blockers"] == []
    assert forward["status_class"] == "warn"
    assert "Forward fundamentals" in str(forward["detail"])


def test_dynamic_readiness_uses_latest_completed_session_before_premarket(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    config["end"] = "2026-05-27"
    paths["config"].write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(data_load_status_module, "DEFAULT_CONFIG_PATH", paths["config"])
    monkeypatch.setattr(data_load_status_module, "DEFAULT_UNIVERSE_PATH", paths["universe"])
    monkeypatch.setattr(data_load_status_module, "DEFAULT_MANIFEST_ROOT", paths["manifest_root"])
    monkeypatch.setattr(data_load_status_module, "DEFAULT_PARQUET_ROOT", paths["parquet_root"])
    monkeypatch.setattr(
        data_load_status_module,
        "DEFAULT_RUNTIME_SUMMARY_PATH",
        paths["runtime_summary"],
    )
    monkeypatch.setattr(
        data_load_status_module, "DEFAULT_SOURCE_HEALTH_PATH", paths["source_health"]
    )
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
        max_timestamp_as_of="2026-05-26T00:00:00+00:00",
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
        max_timestamp_as_of="2026-05-26T21:00:00+00:00",
        date_range={"start": "2026-05-26", "end": "2026-05-26"},
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-26T21:05:00+00:00",
        window_start="2026-05-26",
        window_end="2026-05-26",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-26T21:05:00+00:00",
        window_start="2026-05-26",
        window_end="2026-05-26",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(now=datetime(2026, 5, 27, 7, 15, tzinfo=UTC))

    assert status["as_of"] == "2026-05-26"
    assert _dataset(status, "prices_daily")["coverage_as_of"] == "2026-05-26"
    assert _dataset(status, "stock_trades")["coverage_as_of"] == "2026-05-26"
    assert not [
        blocker
        for blocker in status["blockers"]
        if blocker["item"] in {"prices_daily", "stock_trades"}
    ]


def test_data_load_status_reports_news_resolution_coverage(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "news_rss",
        row_count=10,
        fetched_at="2026-05-11T14:55:00+00:00",
        stale_after="2026-05-11T15:25:00+00:00",
        resolved_row_count=6,
        unresolved_row_count=2,
        ambiguous_row_count=1,
        ticker_count=4,
        resolution_min_confidence=0.7,
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    news = _dataset(status, "news_rss")
    assert news["resolved_row_count"] == 6
    assert news["unresolved_row_count"] == 2
    assert news["ambiguous_row_count"] == 1
    assert news["resolved_ticker_count"] == 4
    assert "6 ticker-linked row(s)" in str(news["detail"])
    assert "6 came from generic headline resolution" in str(news["detail"])
    assert (
        status["news_resolution"]["coverage_label"]
        == "6 ticker-linked / 6 generic-resolved / 0 feed-tagged / 2 unresolved / 1 ambiguous"
    )


def test_data_load_status_reports_news_consumption_ledger(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    ledger_path = tmp_path / "state" / "news_rss_consumed.json"
    ledger_path.parent.mkdir()
    ledger_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "items": {
                    "rss:aapl:1": {
                        "source_id": "rss:aapl:1",
                        "cycle_id": "cycle-1",
                        "ticker": "AAPL",
                        "as_of": "2026-05-11T00:00:00+00:00",
                        "used_at": "2026-05-11T14:58:00+00:00",
                        "lane": "news",
                    },
                    "rss:msft:1": {
                        "source_id": "rss:msft:1",
                        "cycle_id": "cycle-2",
                        "ticker": "MSFT",
                        "as_of": "2026-05-11T00:00:00+00:00",
                        "used_at": "2026-05-11T14:59:00+00:00",
                        "lane": "news",
                    },
                    "rss:older:1": {
                        "source_id": "rss:older:1",
                        "cycle_id": "older-cycle",
                        "ticker": "AAPL",
                        "as_of": "2026-05-10T00:00:00+00:00",
                        "used_at": "2026-05-10T14:59:00+00:00",
                        "lane": "news",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "source_id": "rss:aapl:1",
                "ticker_match_status": "resolved",
            },
            {
                "source_id": "rss:msft:1",
                "ticker_match_status": "feed_ticker",
            },
            {
                "source_id": "rss:unresolved:1",
                "ticker_match_status": "unresolved",
            },
        ]
    ).to_parquet(paths["parquet_root"] / "news_rss")
    _write_manifest(
        paths["manifest_root"],
        "news_rss",
        row_count=10,
        fetched_at="2026-05-11T14:55:00+00:00",
        stale_after="2026-05-11T15:25:00+00:00",
        resolved_row_count=6,
        unresolved_row_count=2,
        ambiguous_row_count=1,
        ticker_count=4,
        resolution_min_confidence=0.7,
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        news_consumption_ledger_path=ledger_path,
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    news = _dataset(status, "news_rss")
    assert status["news_resolution"]["consumed_row_count"] == 2
    assert status["news_resolution"]["unused_resolved_row_count"] == 4
    assert "2 already used by prior live cycle(s)" in str(news["detail"])
    assert news["news_consumption_label"] == "4 unused resolved / 2 already used"


def test_news_health_copy_names_resolution_gap(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "news_rss",
        row_count=5,
        fetched_at="2026-05-11T14:55:00+00:00",
        stale_after="2026-05-11T15:25:00+00:00",
        resolved_row_count=0,
        unresolved_row_count=5,
        ambiguous_row_count=0,
        ticker_count=0,
        resolution_min_confidence=0.7,
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    news = _dataset(status, "news_rss")
    assert news["status"] == "warning"
    assert "No ticker-resolved RSS rows are ready" in str(news["detail"])
    assert "refresh news with ticker aliases" in str(news["detail"])


def test_data_load_status_warns_when_support_source_health_is_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(paths["manifest_root"], "sec_form4", row_count=12, path="sec_form4")
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 1,
            "block_trade_pressure": 1,
            "unusual_trade_activity": 1,
            "pre_market_unusual_activity": 1,
            "market_flow_trend": 1,
            "insider": 1,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["state"] == "attention"
    assert status["ready"] is True
    assert _dataset(status, "sec_form4")["status"] == "warning"
    assert status["source_summary"]["warning_count"] >= 1


def test_data_load_status_blocks_partial_core_market_data(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=10,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=100,
        tickers=["AAPL"],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 1,
            "block_trade_pressure": 1,
            "unusual_trade_activity": 1,
            "pre_market_unusual_activity": 1,
            "market_flow_trend": 1,
            "sector_momentum": 1,
        },
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["state"] == "blocked"
    assert status["ready"] is False
    assert _dataset(status, "stock_trades")["status"] == "blocked"
    assert status["blocker_count"] >= 1


def test_data_load_status_uses_stock_trade_complete_coverage_metadata(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_stock_trade_coverage(
        paths["parquet_root"],
        {
            "AAPL|2026-05-11": "complete",
            "MSFT|2026-05-11": "partial",
        },
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 1,
            "block_trade_pressure": 1,
            "unusual_trade_activity": 1,
            "pre_market_unusual_activity": 1,
            "market_flow_trend": 1,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    row = _dataset(status, "stock_trades")
    assert row["loaded_ticker_count"] == 1
    assert row["coverage_pct"] == 50
    assert row["partial_ticker_count"] == 1
    assert row["status"] == "warning"
    assert status["state"] == "attention"
    assert status["review_operational_ready"] is True
    assert status["tradable_ready"] is False
    assert status["mode"] == "review_subset"
    assert status["market_flow_summary"]["usable_ticker_count"] == 1
    assert _lane(status, "buy_sell_pressure")["status"] == "warning"


def test_data_load_status_counts_desc_partial_stock_trade_slice_as_live_usable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_stock_trade_coverage(
        paths["parquet_root"],
        {
            "AAPL|2026-05-11": "complete",
            "MSFT|2026-05-11": {
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
            },
        },
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    row = _dataset(status, "stock_trades")
    assert row["loaded_ticker_count"] == 1
    assert row["usable_ticker_count"] == 2
    assert row["coverage_pct"] == 50
    assert row["usable_coverage_pct"] == 100
    assert status["market_flow_summary"]["usable_ticker_count"] == 2
    assert status["review_operational_ready"] is True


def test_data_load_status_keeps_fresh_daily_bar_subset_review_operational(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 1,
            "technical_analysis": 1,
            "buy_sell_pressure": 1,
            "block_trade_pressure": 1,
            "unusual_trade_activity": 1,
            "pre_market_unusual_activity": 1,
            "market_flow_trend": 1,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="DEGRADED"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    abnormal_volume = _lane(status, "abnormal_volume")
    technical_analysis = _lane(status, "technical_analysis")
    sector_momentum = _lane(status, "sector_momentum")

    assert status["state"] == "attention"
    assert status["ready"] is True
    assert status["review_operational_ready"] is True
    assert status["tradable_ready"] is False
    assert status["blockers"] == []
    assert status["mode"] == "review_subset"
    assert abnormal_volume["status"] == "warning"
    assert technical_analysis["status"] == "warning"
    assert "covered ticker" in str(abnormal_volume["detail"]).lower()
    assert "freshness is FRESH" not in str(abnormal_volume["detail"])
    assert sector_momentum["status"] == "warning"
    assert "freshness is FRESH" not in str(sector_momentum["detail"])
    assert "available daily ohlcv bars" in str(sector_momentum["detail"]).lower()


def test_data_load_status_marks_market_flow_partial_when_signals_miss_ticker(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_stock_trade_coverage(
        paths["parquet_root"],
        {
            "AAPL|2026-05-11": "complete",
            "MSFT|2026-05-11": {
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
            },
        },
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 1,
            "block_trade_pressure": 1,
            "unusual_trade_activity": 1,
            "pre_market_unusual_activity": 1,
            "market_flow_trend": 1,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    market_flow = status["market_flow_summary"]
    assert market_flow["status"] == "partial"
    assert market_flow["status_label"] == "Partial Market Flow"
    assert market_flow["usable_ticker_count"] == 1
    assert market_flow["source_usable_ticker_count"] == 2
    assert market_flow["missing_or_failed_ticker_count"] == 1
    assert market_flow["coverage_pct"] == 50
    assert "1 ticker" in str(market_flow["detail"])
    assert status["tradable_ready"] is False
    assert status["mode"] == "review_subset"


def test_data_load_status_does_not_count_zero_row_live_trade_slice_as_usable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=100,
        tickers=["AAPL", "MSFT"],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {
                "ticker": "AAPL",
                "coverage_status": "complete",
                "complete": True,
                "downloaded_row_count": 100,
                "rows_written": 100,
                "pages_downloaded": 1,
                "order": "desc",
            },
            {
                "ticker": "MSFT",
                "coverage_status": "complete",
                "complete": True,
                "downloaded_row_count": 0,
                "rows_written": 0,
                "pages_downloaded": 1,
                "order": "desc",
            },
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 1,
            "block_trade_pressure": 1,
            "unusual_trade_activity": 1,
            "pre_market_unusual_activity": 1,
            "market_flow_trend": 1,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    stock_trades = _dataset(status, "stock_trades")
    assert stock_trades["usable_ticker_count"] == 1
    assert stock_trades["partial_ticker_count"] == 1
    assert status["market_flow_summary"]["source_usable_ticker_count"] == 1
    assert status["market_flow_summary"]["missing_or_failed_ticker_count"] == 1


def test_data_load_status_counts_verified_zero_print_live_trade_slice_as_usable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    pd.DataFrame(
        [
            _member("AAPL", date(2019, 1, 1), None),
            _member("BK", date(2019, 1, 1), None),
        ]
    ).to_parquet(paths["universe"], index=False)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "BK"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=100,
        tickers=["AAPL", "BK"],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "BK"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "BK", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "BK"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {
                "ticker": "AAPL",
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
            },
            {
                "ticker": "BK",
                "coverage_status": "complete",
                "complete": True,
                "downloaded_row_count": 0,
                "rows_written": 0,
                "last_page_results_count": 0,
                "pages_downloaded": 1,
                "order": "desc",
                "row_count_verified": True,
            },
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [_source("daily-market-bars", freshness="FRESH", status="HEALTHY")],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    stock_trades = _dataset(status, "stock_trades")
    assert stock_trades["source_status"] == "HEALTHY"
    assert stock_trades["source_freshness"] == "FRESH"
    assert stock_trades["usable_ticker_count"] == 2
    assert stock_trades["partial_ticker_count"] == 0
    assert status["market_flow_summary"]["source_usable_ticker_count"] == 2
    assert status["market_flow_summary"]["missing_or_failed_ticker_count"] == 0


def test_data_load_status_prefers_massive_live_slice_lane_for_stock_trade_readiness(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=999,
        tickers=["AAPL", "MSFT"],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {
                "ticker": "AAPL",
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
            }
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 1,
            "block_trade_pressure": 1,
            "unusual_trade_activity": 1,
            "pre_market_unusual_activity": 1,
            "market_flow_trend": 1,
        },
    )
    _write_source_health(
        paths["source_health"],
        [_source("daily-market-bars", freshness="FRESH", status="HEALTHY")],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    row = _dataset(status, "stock_trades")
    assert row["massive_lane_id"] == "massive_live_trade_slices"
    assert row["source_status"] == "HEALTHY"
    assert row["source_freshness"] == "FRESH"
    assert row["loaded_ticker_count"] == 1
    assert row["usable_ticker_count"] == 1
    assert row["coverage_pct"] == 50
    assert row["status"] == "warning"
    assert status["mode"] == "review_subset"
    assert "usable current-day" in str(row["detail"])


def test_data_load_status_treats_full_universe_latest_trade_slices_as_tradable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=999,
        tickers=["AAPL", "MSFT"],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {
                "ticker": "AAPL",
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
            },
            {
                "ticker": "MSFT",
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
            },
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [_source("daily-market-bars", freshness="FRESH", status="HEALTHY")],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    row = _dataset(status, "stock_trades")
    assert row["source_status"] == "HEALTHY"
    assert row["source_freshness"] == "FRESH"
    assert row["usable_ticker_count"] == 2
    assert row["partial_ticker_count"] == 0
    assert row["status"] == "ready"
    assert status["market_flow_summary"]["status"] == "ready"
    assert status["tradable_ready"] is True
    assert "latest-slice" in str(row["detail"])


def test_data_load_status_uses_stock_trade_coverage_when_live_lane_manifest_is_older(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    config["end"] = "2026-05-12"
    paths["config"].write_text(json.dumps(config), encoding="utf-8")
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
        max_timestamp_as_of="2026-05-12T00:00:00+00:00",
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=999,
        tickers=["AAPL", "MSFT"],
        max_timestamp_as_of="2026-05-12T21:00:00+00:00",
        fetched_at="2026-05-12T21:05:00+00:00",
        date_range={"start": "2026-05-12", "end": "2026-05-12"},
    )
    _write_stock_trade_coverage(
        paths["parquet_root"],
        {
            "AAPL|2026-05-12": {
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
                "updated_at": "2026-05-12T21:01:00+00:00",
            },
            "MSFT|2026-05-12": {
                "coverage_status": "complete",
                "complete": True,
                "downloaded_row_count": 250,
                "pages_downloaded": 1,
                "order": "asc",
                "row_count_verified": True,
                "updated_at": "2026-05-12T21:02:00+00:00",
            },
        },
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-12T21:00:00+00:00",
        window_start="2026-05-12",
        window_end="2026-05-12",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL"],
        fetched_at="2026-05-11T21:00:00+00:00",
        window_start="2026-05-11",
        window_end="2026-05-11",
        coverage=[
            {
                "ticker": "AAPL",
                "coverage_status": "complete",
                "complete": True,
                "downloaded_row_count": 100,
                "pages_downloaded": 1,
                "order": "desc",
            }
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 13, 2, 0, tzinfo=UTC),
    )

    row = _dataset(status, "stock_trades")
    assert row["status"] == "ready"
    assert row["source_status"] == "HEALTHY"
    assert row["usable_ticker_count"] == 2
    assert row["partial_ticker_count"] == 0
    assert row["massive_lane_id"] == "massive_live_trade_slices"
    assert "coverage metadata" in str(row["detail"])
    assert "lane manifest does not cover" not in str(status["blockers"])
    assert status["health_monitor"]["reliable"] is True
    assert status["review_operational_ready"] is True
    assert status["tradable_ready"] is True


def test_data_load_status_uses_stock_trade_parquet_rows_when_lane_and_coverage_metadata_are_older(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    config["end"] = "2026-05-12"
    paths["config"].write_text(json.dumps(config), encoding="utf-8")
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
        max_timestamp_as_of="2026-05-12T00:00:00+00:00",
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=999,
        tickers=["AAPL", "MSFT"],
        max_timestamp_as_of="2026-05-12T21:00:00+00:00",
        fetched_at="2026-05-12T21:05:00+00:00",
        date_range={"start": "2026-05-12", "end": "2026-05-12"},
    )
    _write_stock_trade_coverage(
        paths["parquet_root"],
        {
            "AAPL|2026-05-11": {
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
                "updated_at": "2026-05-12T20:00:00+00:00",
            },
            "MSFT|2026-05-11": {
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
                "updated_at": "2026-05-12T20:00:00+00:00",
            },
        },
    )
    _write_stock_trade_parquet(
        paths["parquet_root"],
        "AAPL",
        [
            {"ticker": "AAPL", "year": 2026, "trade_date": date(2026, 5, 12)},
            {"ticker": "AAPL", "year": 2026, "trade_date": date(2026, 5, 12)},
        ],
    )
    _write_stock_trade_parquet(
        paths["parquet_root"],
        "MSFT",
        [
            {"ticker": "MSFT", "year": 2026, "trade_date": date(2026, 5, 11)},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-12T21:00:00+00:00",
        window_start="2026-05-12",
        window_end="2026-05-12",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T21:00:00+00:00",
        window_start="2026-05-11",
        window_end="2026-05-11",
        coverage=[
            {
                "ticker": "AAPL",
                "coverage_status": "complete",
                "complete": True,
                "downloaded_row_count": 100,
                "pages_downloaded": 1,
                "order": "desc",
            }
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 1,
            "block_trade_pressure": 1,
            "unusual_trade_activity": 1,
            "pre_market_unusual_activity": 1,
            "market_flow_trend": 1,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 13, 2, 0, tzinfo=UTC),
    )

    row = _dataset(status, "stock_trades")
    assert row["status"] == "warning"
    assert row["source_status"] == "DEGRADED"
    assert row["usable_ticker_count"] == 1
    assert row["partial_ticker_count"] == 1
    assert row["massive_lane_id"] == "massive_live_trade_slices"
    assert "parquet row proof" in str(row["detail"])
    assert "lane manifest does not cover" not in str(status["blockers"])
    assert not status["blockers"]
    assert status["review_operational_ready"] is True
    assert status["tradable_ready"] is False


def test_data_load_status_does_not_treat_full_parquet_row_proof_as_tradable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    config["end"] = "2026-05-12"
    paths["config"].write_text(json.dumps(config), encoding="utf-8")
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
        max_timestamp_as_of="2026-05-12T00:00:00+00:00",
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=999,
        tickers=["AAPL", "MSFT"],
        max_timestamp_as_of="2026-05-12T21:00:00+00:00",
        fetched_at="2026-05-12T21:05:00+00:00",
        date_range={"start": "2026-05-12", "end": "2026-05-12"},
    )
    _write_stock_trade_coverage(
        paths["parquet_root"],
        {
            "AAPL|2026-05-11": {
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
                "updated_at": "2026-05-12T20:00:00+00:00",
            },
            "MSFT|2026-05-11": {
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
                "updated_at": "2026-05-12T20:00:00+00:00",
            },
        },
    )
    _write_stock_trade_parquet(
        paths["parquet_root"],
        "AAPL",
        [{"ticker": "AAPL", "year": 2026, "trade_date": date(2026, 5, 12)}],
    )
    _write_stock_trade_parquet(
        paths["parquet_root"],
        "MSFT",
        [{"ticker": "MSFT", "year": 2026, "trade_date": date(2026, 5, 12)}],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-12T21:00:00+00:00",
        window_start="2026-05-12",
        window_end="2026-05-12",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T21:00:00+00:00",
        window_start="2026-05-11",
        window_end="2026-05-11",
        coverage=[],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 13, 2, 0, tzinfo=UTC),
    )

    row = _dataset(status, "stock_trades")
    assert row["usable_ticker_count"] == 2
    assert row["source_status"] == "DEGRADED"
    assert row["source_freshness"] == "PARTIAL"
    assert row["status"] == "warning"
    assert "parquet row proof" in str(row["detail"])
    assert status["review_operational_ready"] is True
    assert status["tradable_ready"] is False


def test_data_load_status_treats_unverified_desc_complete_live_slice_as_usable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=999,
        tickers=["AAPL", "MSFT"],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {
                "ticker": "AAPL",
                "coverage_status": "complete",
                "complete": True,
                "row_count_verified": False,
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
                "resume_cursor": None,
                "stop_reason": None,
            },
            {
                "ticker": "MSFT",
                "coverage_status": "complete",
                "complete": True,
                "row_count_verified": True,
            },
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [_source("daily-market-bars", freshness="FRESH", status="HEALTHY")],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    row = _dataset(status, "stock_trades")
    assert row["usable_ticker_count"] == 2
    assert row["loaded_ticker_count"] == 2
    assert row["partial_ticker_count"] == 0
    assert row["status"] == "ready"
    assert status["tradable_ready"] is True


def test_data_load_status_accepts_rows_from_fresh_live_trade_sweep(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=999,
        tickers=["AAPL", "MSFT"],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:04:30+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:04:30+00:00",
        coverage=[
            {
                "ticker": "AAPL",
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
                "updated_at": "2026-05-11T14:59:30+00:00",
                "fetched_at": "2026-05-11T14:59:30+00:00",
            },
            {
                "ticker": "MSFT",
                "coverage_status": "complete",
                "complete": True,
                "updated_at": "2026-05-11T15:04:30+00:00",
                "fetched_at": "2026-05-11T15:04:30+00:00",
            },
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [_source("daily-market-bars", freshness="FRESH", status="HEALTHY")],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 5, tzinfo=UTC),
    )

    row = _dataset(status, "stock_trades")
    assert row["usable_ticker_count"] == 2
    assert row["status"] == "ready"
    assert status["tradable_ready"] is True


def test_data_load_status_keeps_completed_live_trade_sweep_fresh_for_dashboard_sla(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=999,
        tickers=["AAPL", "MSFT"],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:04:30+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:04:30+00:00",
        coverage=[
            {
                "ticker": "AAPL",
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
                "updated_at": "2026-05-11T15:00:00+00:00",
                "fetched_at": "2026-05-11T15:00:00+00:00",
            },
            {
                "ticker": "MSFT",
                "coverage_status": "complete",
                "complete": True,
                "updated_at": "2026-05-11T15:04:30+00:00",
                "fetched_at": "2026-05-11T15:04:30+00:00",
            },
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [_source("daily-market-bars", freshness="FRESH", status="HEALTHY")],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 13, tzinfo=UTC),
    )

    row = _dataset(status, "stock_trades")
    assert row["source_status"] == "HEALTHY"
    assert row["usable_ticker_count"] == 2
    assert row["status"] == "ready"


def test_data_load_status_treats_last_completed_live_trade_lane_current_when_market_closed(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    config["end"] = "2026-05-15"
    paths["config"].write_text(json.dumps(config), encoding="utf-8")
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=999,
        tickers=["AAPL", "MSFT"],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-15T22:00:00+00:00",
        window_start="2026-05-15",
        window_end="2026-05-15",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-15T22:00:00+00:00",
        window_start="2026-05-15",
        window_end="2026-05-15",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 16, 12, 0, tzinfo=UTC),
    )

    row = _dataset(status, "stock_trades")
    assert row["source_status"] == "HEALTHY"
    assert row["source_freshness"] == "FRESH"
    assert row["status"] == "ready"
    assert "Closed-market freshness" in str(row["detail"])


def test_data_load_status_treats_last_completed_daily_bars_current_when_market_closed(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    config["end"] = "2026-05-15"
    paths["config"].write_text(json.dumps(config), encoding="utf-8")
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
        max_timestamp_as_of="2026-05-15T00:00:00+00:00",
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=999,
        tickers=["AAPL", "MSFT"],
        max_timestamp_as_of="2026-05-15T00:00:00+00:00",
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-15T22:00:00+00:00",
        window_start="2026-05-15",
        window_end="2026-05-15",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-15T22:00:00+00:00",
        window_start="2026-05-15",
        window_end="2026-05-15",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 17, 12, 0, tzinfo=UTC),
    )

    row = _dataset(status, "prices_daily")
    assert row["source_status"] == "HEALTHY"
    assert row["source_freshness"] == "FRESH"
    assert row["status"] == "ready"
    assert _lane(status, "abnormal_volume")["status"] == "ready"
    assert _lane(status, "technical_analysis")["status"] == "ready"
    assert "Closed-market freshness" in str(row["detail"])


def test_data_load_status_blocks_stale_critical_source_health(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="STALE", status="STALE"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["state"] == "blocked"
    assert status["ready"] is False
    assert _dataset(status, "stock_trades")["status"] == "blocked"
    assert _lane(status, "buy_sell_pressure")["status"] == "blocked"
    market_flow_detail = str(_lane(status, "market_flow_trend")["detail"])
    assert "stale" not in market_flow_detail.lower()
    assert "needs refresh" in market_flow_detail
    source_summary = status["source_summary"]
    assert isinstance(source_summary, dict)
    assert source_summary["critical_blocker_count"] == 1


def test_data_load_status_labels_missing_critical_source_as_unavailable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_source_health(
        paths["source_health"],
        [_source("daily-market-bars", freshness="FRESH", status="HEALTHY")],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    source_summary = status["source_summary"]
    assert isinstance(source_summary, dict)
    assert "unavailable" in str(source_summary["headline"]).lower()
    assert "stale" not in str(source_summary["headline"]).lower()


def test_data_load_status_blocks_old_critical_source_health_row(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    old_source = _source("daily-market-bars", freshness="FRESH", status="HEALTHY")
    old_source["checked_at"] = "2026-05-12T12:00:00+00:00"
    _write_source_health(
        paths["source_health"],
        [
            old_source,
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
    )

    assert status["state"] == "blocked"
    assert _dataset(status, "prices_daily")["status"] == "blocked"
    daily_detail = str(_dataset(status, "prices_daily")["detail"])
    assert "source-health row" not in daily_detail
    assert "health proof is 3600s old" in daily_detail


def test_data_load_status_uses_fresh_massive_daily_lane_manifest(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    now = datetime(2026, 5, 12, 13, 0, tzinfo=UTC)
    old_source = _source("daily-market-bars", freshness="FRESH", status="HEALTHY")
    old_source["checked_at"] = "2026-05-12T12:00:00+00:00"
    _write_source_health(
        paths["source_health"],
        [
            old_source,
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )
    lane_root = paths["manifest_root"] / "massive_lanes"
    lane_root.mkdir(parents=True, exist_ok=True)
    (lane_root / "massive_daily_bars.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1.0",
                "lane_id": "massive_daily_bars",
                "dataset": "prices_daily",
                "raw_source_dataset": "prices_daily",
                "fetched_at": "2026-05-12T12:00:00+00:00",
                "window": {"start": "2026-05-12", "end": "2026-05-12"},
                "ticker_count": 2,
                "tickers": ["AAPL", "MSFT"],
                "row_count": 2,
                "source_manifest": "prices_daily.json",
                "status": "complete",
                "coverage_pct": 100,
                "coverage": [
                    {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
                    {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
                ],
                "issues": [],
                "issue_count": 0,
            }
        ),
        encoding="utf-8",
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=now,
    )

    daily = _dataset(status, "prices_daily")
    assert daily["status"] == "ready"
    assert daily["massive_lane_id"] == "massive_daily_bars"
    assert "Massive Daily Bars has verified OHLCV coverage" in str(daily["detail"])


def test_data_load_status_blocks_missing_massive_lane_manifest_even_with_healthy_generic_source(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_source_health(
        paths["source_health"],
        [_source("massive-stock-trades", freshness="FRESH", status="HEALTHY")],
    )
    (paths["manifest_root"] / "massive_lanes").mkdir(parents=True, exist_ok=True)

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
    )
    freshness_rows = {
        str(row["source"]): row for row in status["freshness_rows"] if isinstance(row, dict)
    }

    assert freshness_rows["massive-stock-trades"]["status_class"] == "block"
    assert freshness_rows["massive-stock-trades"]["status"] == "UNAVAILABLE"
    assert "lane manifest is missing" in str(freshness_rows["massive-stock-trades"]["detail"])


def test_data_load_status_blocks_missing_daily_bars_lane_manifest_even_with_healthy_generic_source(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_source_health(
        paths["source_health"],
        [_source("daily-market-bars", freshness="FRESH", status="HEALTHY")],
    )
    (paths["manifest_root"] / "massive_lanes").mkdir(parents=True, exist_ok=True)

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
    )
    freshness_rows = {
        str(row["source"]): row for row in status["freshness_rows"] if isinstance(row, dict)
    }

    assert freshness_rows["daily-market-bars"]["status_class"] == "block"
    assert freshness_rows["daily-market-bars"]["status"] == "UNAVAILABLE"
    assert "lane manifest is missing" in str(freshness_rows["daily-market-bars"]["detail"])


def test_data_load_status_blocks_missing_critical_source_health(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["state"] == "blocked"
    assert status["source_summary"]["critical_blocker_count"] == 2
    assert "no source-health row" in _dataset(status, "prices_daily")["detail"]


def test_data_load_status_blocks_stale_refresh_progress(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )
    status_path = Path(str(paths["manifest_root"].parent / "stale-refresh.json"))
    status_path.write_text(
        json.dumps(
            {
                "progress": {
                    "state": "running",
                    "total_jobs": 2,
                    "completed_jobs": 1,
                    "percent_complete": 50,
                },
                "jobs": [{"dataset": "prices_daily", "status": "running"}],
            }
        ),
        encoding="utf-8",
    )
    old_time = 1_700_000_000
    os.utime(status_path, (old_time, old_time))
    monkeypatch.setenv("DATA_REFRESH_STATUS_PATH", str(status_path))

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["state"] == "blocked"
    assert status["ready"] is False
    assert status["data_refresh"]["state"] == "stale"


def test_data_load_status_does_not_block_trading_for_stale_support_refresh_when_core_lanes_ready(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )
    status_path = Path(str(paths["manifest_root"].parent / "stale-support-refresh.json"))
    status_path.write_text(
        json.dumps(
            {
                "progress": {
                    "state": "running",
                    "total_jobs": 1,
                    "completed_jobs": 0,
                    "percent_complete": 0,
                    "current_dataset": "sec_form4",
                },
                "jobs": [{"dataset": "sec_form4", "status": "running"}],
            }
        ),
        encoding="utf-8",
    )
    old_time = 1_700_000_000
    os.utime(status_path, (old_time, old_time))
    monkeypatch.setenv("DATA_REFRESH_STATUS_PATH", str(status_path))

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["data_refresh"]["state"] == "stale"
    assert status["state"] == "attention"
    assert status["ready"] is True
    assert status["tradable_ready"] is True
    assert any(
        warning["kind"] == "data_refresh" and warning["item"] == "sec_form4"
        for warning in status["warnings"]
    )


def test_data_load_status_warns_for_failed_support_refresh_when_core_lanes_ready(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_ready_core_market_lanes(paths)
    status_path = Path(str(paths["manifest_root"].parent / "failed-support-refresh.json"))
    status_path.write_text(
        json.dumps(
            {
                "failed": True,
                "has_failures": True,
                "failed_datasets": ["sec_form4"],
                "progress": {
                    "state": "failed",
                    "total_jobs": 1,
                    "completed_jobs": 1,
                    "percent_complete": 100,
                },
                "jobs": [
                    {
                        "dataset": "sec_form4",
                        "status": "failed",
                        "reason": "SEC support refresh failed after core lanes completed.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_REFRESH_STATUS_PATH", str(status_path))

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["data_refresh"]["state"] == "failed"
    assert status["state"] == "attention"
    assert status["ready"] is True
    assert status["review_operational_ready"] is True
    assert status["tradable_ready"] is True
    assert not status["blockers"]
    assert any(
        warning["kind"] == "data_refresh" and warning["item"] == "sec_form4"
        for warning in status["warnings"]
    )


def test_data_load_status_keeps_block_trade_refresh_execution_blocking(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_ready_core_market_lanes(paths)
    status_path = Path(str(paths["manifest_root"].parent / "failed-block-trade-refresh.json"))
    status_path.write_text(
        json.dumps(
            {
                "failed": True,
                "has_failures": True,
                "current_dataset": "massive_block_trade_feed",
                "failed_datasets": ["massive_block_trade_feed"],
                "progress": {
                    "state": "failed",
                    "total_jobs": 1,
                    "completed_jobs": 1,
                    "percent_complete": 100,
                },
                "jobs": [
                    {
                        "dataset": "massive_block_trade_feed",
                        "status": "failed",
                        "reason": "Block-trade derivation failed.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_REFRESH_STATUS_PATH", str(status_path))

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["market_flow_summary"]["status"] == "ready"
    assert status["data_refresh"]["state"] == "failed"
    assert status["state"] == "blocked"
    assert status["tradable_ready"] is False
    assert any(
        blocker["kind"] == "data_refresh" and blocker["item"] == "massive_block_trade_feed"
        for blocker in status["blockers"]
    )


def test_market_flow_summary_does_not_mask_blocked_lane_with_ready_lane(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_ready_core_market_lanes(paths)
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 0,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert _lane(status, "block_trade_pressure")["status"] == "blocked"
    assert status["market_flow_summary"]["status"] == "blocked"
    assert status["market_flow_summary"]["blocked_lane_count"] == 1
    assert status["tradable_ready"] is False


def test_data_load_status_blocks_failed_core_refresh_even_when_old_lanes_exist(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_ready_core_market_lanes(paths)
    status_path = Path(str(paths["manifest_root"].parent / "failed-core-refresh.json"))
    status_path.write_text(
        json.dumps(
            {
                "failed": True,
                "has_failures": True,
                "failed_datasets": ["stock_trades"],
                "progress": {
                    "state": "failed",
                    "total_jobs": 1,
                    "completed_jobs": 1,
                    "percent_complete": 100,
                },
                "jobs": [
                    {
                        "dataset": "stock_trades",
                        "status": "failed",
                        "reason": "Massive live trade lane failed.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DATA_REFRESH_STATUS_PATH", str(status_path))

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["data_refresh"]["state"] == "failed"
    assert status["state"] == "blocked"
    assert status["ready"] is False


def test_data_load_status_keeps_review_subset_when_latest_partial_pull_has_market_flow_rows(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )
    (tmp_path / "stock-trades-progress.json").write_text(
        json.dumps(
            {
                "state": "partial",
                "percent_complete": 75,
                "ticker_days_completed": 3,
                "ticker_days_total": 4,
            }
        ),
        encoding="utf-8",
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["state"] == "attention"
    assert status["ready"] is True
    assert status["review_operational_ready"] is True
    assert status["tradable_ready"] is True
    assert status["data_refresh"]["trade_pull"]["state"] == "partial"
    assert not status["blockers"]
    assert any(warning["item"] == "stock_trades" for warning in status["warnings"])


def test_data_load_status_keeps_review_subset_when_latest_batch_did_not_verify_trades(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )
    paths["refresh_status"].write_text(
        json.dumps(
            {
                "progress": {
                    "state": "complete",
                    "total_jobs": 1,
                    "completed_jobs": 1,
                    "percent_complete": 100,
                },
                "jobs": [{"dataset": "sec_company_facts", "status": "passed"}],
            }
        ),
        encoding="utf-8",
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["state"] == "attention"
    assert status["ready"] is True
    assert status["data_refresh"]["trade_pull"]["state"] == "unverified"
    assert not status["blockers"]
    assert any(warning["item"] == "stock_trades" for warning in status["warnings"])


def test_data_load_status_blocks_partial_stock_trade_pull_without_usable_market_flow(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 0,
            "block_trade_pressure": 0,
            "unusual_trade_activity": 0,
            "pre_market_unusual_activity": 0,
            "market_flow_trend": 0,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )
    (tmp_path / "stock-trades-progress.json").write_text(
        json.dumps(
            {
                "state": "partial",
                "percent_complete": 75,
                "ticker_days_completed": 3,
                "ticker_days_total": 4,
            }
        ),
        encoding="utf-8",
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["state"] == "blocked"
    assert status["ready"] is False
    assert status["data_refresh"]["trade_pull"]["state"] == "partial"
    assert any(blocker["item"] == "stock_trades" for blocker in status["blockers"])


def test_data_load_status_uses_configured_tickers_when_universe_is_missing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    paths["universe"].unlink()
    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    config["tickers"] = ["AAPL", "MSFT"]
    paths["config"].write_text(json.dumps(config), encoding="utf-8")
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["expected_ticker_count"] == 2
    assert _dataset(status, "prices_daily")["status"] == "ready"
    assert _lane(status, "market_flow_trend")["status"] == "ready"


def test_data_load_status_endpoint_returns_payload(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        health_module,
        "load_data_load_status",
        lambda **_kwargs: {"schema_version": "0.1.0", "state": "ready", "ready": True},
    )
    client = TestClient(create_app())

    response = client.get("/status/data-load")

    assert response.status_code == HTTP_OK
    assert response.json()["state"] == "ready"


def test_data_load_status_marks_live_health_monitor_reliable(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    source_rows = [
        _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
        _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
    ]

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        source_health_rows=source_rows,
        source_health_origin="live runtime source-health reader",
    )

    monitor = status["health_monitor"]
    assert isinstance(monitor, dict)
    assert monitor["status_label"] == "Live Health Monitor"
    assert monitor["status_class"] == "pass"
    assert monitor["live"] is True
    assert monitor["reliable"] is True


def test_data_load_status_health_monitor_ignores_untracked_stale_rows(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    stale_optional = _source("yfinance-daily", freshness="FRESH", status="HEALTHY")
    stale_optional["checked_at"] = "2026-05-07T14:31:00+00:00"
    source_rows = [
        _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
        _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        stale_optional,
    ]

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        source_health_rows=source_rows,
        source_health_origin="live runtime source-health reader",
    )

    monitor = status["health_monitor"]
    assert isinstance(monitor, dict)
    assert monitor["status_label"] == "Live Health Monitor"
    assert monitor["row_count"] == 2
    assert {row["source"] for row in status["freshness_rows"] if isinstance(row, dict)}.isdisjoint(
        {"yfinance-daily"}
    )


def test_data_load_status_health_monitor_uses_source_specific_sla(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    daily = _source("daily-market-bars", freshness="FRESH", status="HEALTHY")
    daily["checked_at"] = "2026-05-12T12:00:00+00:00"
    daily["max_age_seconds"] = 24 * 60 * 60

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        source_health_rows=[daily],
        source_health_origin="live runtime source-health reader",
        now=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
    )

    monitor = status["health_monitor"]
    assert isinstance(monitor, dict)
    assert monitor["status_label"] == "Live Health Monitor"
    assert monitor["status_class"] == "pass"


def test_data_load_status_prefers_massive_lane_manifest_over_stale_generic_health(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    old_generic = _source("daily-market-bars", freshness="FRESH", status="HEALTHY")
    old_generic["checked_at"] = "2026-05-12T12:00:00+00:00"
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-15T21:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        source_health_rows=[old_generic],
        source_health_origin="live runtime source-health reader",
        now=datetime(2026, 5, 17, 13, 0, tzinfo=UTC),
    )
    freshness_rows = {
        str(row["source"]): row for row in status["freshness_rows"] if isinstance(row, dict)
    }

    assert freshness_rows["daily-market-bars"]["status_class"] == "pass"
    assert "massive_daily_bars lane is HEALTHY / FRESH" in str(
        freshness_rows["daily-market-bars"]["detail"]
    )


def test_data_load_status_degrades_daily_bar_source_health_for_partial_active_universe(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=10,
        tickers=["AAPL"],
    )
    old_generic = _source("daily-market-bars", freshness="FRESH", status="HEALTHY")
    old_generic["checked_at"] = "2026-05-12T12:00:00+00:00"
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL"],
        fetched_at="2026-05-15T21:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
        ],
        issues=[{"ticker": "MSFT", "reason": "no_daily_bar_available"}],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        source_health_rows=[old_generic],
        source_health_origin="live runtime source-health reader",
        now=datetime(2026, 5, 17, 13, 0, tzinfo=UTC),
    )
    freshness_rows = {
        str(row["source"]): row for row in status["freshness_rows"] if isinstance(row, dict)
    }
    daily_source = freshness_rows["daily-market-bars"]
    daily_dataset = _dataset(status, "prices_daily")

    assert daily_source["status"] == "DEGRADED"
    assert daily_source["status_class"] == "warn"
    assert daily_source["missing_active_tickers"] == ["MSFT"]
    assert "1/2 active ticker(s)" in str(daily_source["detail"])
    assert "MSFT" in str(daily_source["detail"])
    assert "provider returned no daily bar for MSFT" in str(daily_source["detail"])
    assert "retry is not currently useful" in str(daily_source["detail"])
    assert daily_dataset["status"] == "blocked"
    assert daily_dataset["missing_active_tickers"] == ["MSFT"]
    assert "1/2 active ticker(s)" in str(daily_dataset["detail"])
    assert "MSFT" in str(daily_dataset["detail"])


def test_data_load_status_treats_slow_moving_sec_health_proof_as_current(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    source_rows = [
        _source("sec-company-facts", freshness="FRESH", status="HEALTHY"),
        _source("sec-form4", freshness="FRESH", status="HEALTHY"),
        _source("sec-13f", freshness="FRESH", status="HEALTHY"),
    ]
    for row in source_rows:
        row["checked_at"] = "2026-05-16T09:00:00+00:00"

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        source_health_rows=source_rows,
        source_health_origin="live runtime source-health reader",
        now=datetime(2026, 5, 17, 13, 0, tzinfo=UTC),
    )
    freshness_rows = {
        str(row["source"]): row for row in status["freshness_rows"] if isinstance(row, dict)
    }

    assert freshness_rows["sec-company-facts"]["status_class"] == "pass"
    assert freshness_rows["sec-form4"]["status_class"] == "pass"
    assert freshness_rows["sec-13f"]["status_class"] == "pass"


def test_data_load_status_does_not_degrade_current_form4_for_old_repair_issue(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_ready_core_market_lanes(paths)
    _write_manifest(
        paths["manifest_root"],
        "sec_form4",
        row_count=12,
        path="sec_form4",
        issues=[
            {
                "ticker": "HON",
                "accession_number": "0001209191-21-048390",
                "reason": "SEC request rate limited",
                "detail": "HTTP 429",
            }
        ],
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
            _source("sec-form4", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    row = _dataset(status, "sec_form4")
    assert row["issue_count"] == 1
    assert row["status"] == "ready"
    assert status["tradable_ready"] is True
    assert "historical repair issue" in str(row["detail"])


def test_data_load_status_treats_empty_current_insider_lane_as_neutral(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_ready_core_market_lanes(paths)
    _write_manifest(paths["manifest_root"], "sec_form4", row_count=12, path="sec_form4")
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
            "insider": 0,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
            _source("sec-form4", freshness="FRESH", status="HEALTHY"),
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    row = _lane(status, "insider")
    assert row["expected_count"] is None
    assert row["status"] == "ready"
    assert "no current insider Form 4 events" in str(row["detail"])
    assert status["tradable_ready"] is True


def test_data_load_status_health_monitor_warns_for_context_only_stale_proof(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    daily = _source("daily-market-bars", freshness="FRESH", status="HEALTHY")
    stock_trades = _source("massive-stock-trades", freshness="FRESH", status="HEALTHY")
    news = _source("rss-news", freshness="FRESH", status="HEALTHY")
    news["checked_at"] = "2026-05-16T09:00:00+00:00"

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        source_health_rows=[daily, stock_trades, news],
        source_health_origin="live runtime source-health reader",
        now=datetime(2026, 5, 17, 13, 0, tzinfo=UTC),
    )

    monitor = status["health_monitor"]
    assert isinstance(monitor, dict)
    assert monitor["status_label"] == "Context Health Needs Refresh"
    assert monitor["status_class"] == "warn"
    assert "rss-news" in str(monitor["detail"])


def test_data_load_status_uses_context_manifests_as_source_health_proof(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_manifest(paths["manifest_root"], "prices_daily", row_count=20, tickers=["AAPL", "MSFT"])
    _write_manifest(paths["manifest_root"], "stock_trades", row_count=200, tickers=["AAPL", "MSFT"])
    _write_manifest(
        paths["manifest_root"], "sec_company_facts", row_count=100, path="sec_company_facts"
    )
    _partition(paths["parquet_root"], "sec_company_facts", "AAPL")
    _partition(paths["parquet_root"], "sec_company_facts", "MSFT")
    _write_manifest(paths["manifest_root"], "sec_form4", row_count=12, path="sec_form4")
    _partition(paths["parquet_root"], "sec_form4", "AAPL")
    _write_manifest(paths["manifest_root"], "sec_13f", row_count=4, path="sec_13f")
    _write_manifest(
        paths["manifest_root"],
        "news_rss",
        row_count=2,
        fetched_at="2026-05-18T03:00:00+00:00",
        stale_after="2026-05-18T04:00:00+00:00",
    )
    _write_manifest(
        paths["manifest_root"],
        "subscription_emails",
        row_count=1,
        fetched_at="2026-05-18T03:00:00+00:00",
        stale_after="2026-05-18T07:00:00+00:00",
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
            "fundamentals": 2,
            "insider": 2,
            "institutional": 1,
            "news": 1,
            "subscription_thesis": 1,
        },
    )
    old_context = "2026-05-17T14:00:00+00:00"
    old_news = _source("rss-news", freshness="FRESH", status="HEALTHY")
    old_news["checked_at"] = old_context
    old_subscription = _source("subscription-email-thesis", freshness="FRESH", status="HEALTHY")
    old_subscription["checked_at"] = old_context
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
            _source("sec-company-facts", freshness="FRESH", status="HEALTHY"),
            _source("sec-form4", freshness="FRESH", status="HEALTHY"),
            _source("sec-13f", freshness="FRESH", status="HEALTHY"),
            old_news,
            old_subscription,
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 18, 3, 10, tzinfo=UTC),
    )

    warning_items = {str(row["item"]) for row in status["warnings"]}
    freshness = {str(row["source"]): row for row in status["freshness_rows"]}
    assert "news_rss" not in warning_items
    assert "subscription_emails" not in warning_items
    assert "news" not in warning_items
    assert "subscription_thesis" not in warning_items
    assert freshness["rss-news"]["checked_at"] == "2026-05-18T03:00:00+00:00"
    assert freshness["subscription-email-thesis"]["checked_at"] == "2026-05-18T03:00:00+00:00"
    assert status["tradable_ready"] is True


def test_subscription_email_detail_prompts_operator_login_when_articles_need_sa(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    summary_path = tmp_path / "subscription-email-ingest.json"
    summary_path.write_text(
        json.dumps(
            {
                "verdict": "needs_article_login",
                "fetched_at": "2026-05-19T10:10:28+00:00",
                "processed_emails": 10,
                "event_rows": 42,
                "linked_content": {"login_required": 10, "succeeded": 0},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        data_load_status_module,
        "DEFAULT_SUBSCRIPTION_EMAIL_SUMMARY_PATH",
        summary_path,
    )
    _write_manifest(
        paths["manifest_root"],
        "subscription_emails",
        row_count=645,
        fetched_at="2026-05-19T10:10:28+00:00",
        stale_after="2026-05-19T14:10:28+00:00",
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 19, 15, 0, tzinfo=UTC),
    )

    detail = str(_dataset(status, "subscription_emails")["detail"])
    assert "operator login" in detail
    assert "10 protected article link(s) required login" in detail
    assert "Click Open Seeking Alpha login refresh" in detail
    assert "stale" not in detail.lower()


def test_subscription_email_status_reports_article_progress(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    summary_path = tmp_path / "subscription-email-ingest.json"
    progress_path = tmp_path / "subscription-email-progress.json"
    summary_path.write_text(
        json.dumps(
            {
                "verdict": "ok",
                "fetched_at": "2026-05-19T10:10:28+00:00",
                "processed_emails": 5,
                "event_rows": 12,
                "linked_content": {
                    "attempted": 4,
                    "succeeded": 3,
                    "failed": 1,
                    "skipped": 1,
                    "cache_hits": 0,
                    "login_required": 0,
                    "unavailable": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    progress_path.write_text(
        json.dumps(
            {
                "state": "complete",
                "updated_at": "2026-05-19T10:12:28+00:00",
                "selected_email_count": 5,
                "article_links_found": 4,
                "linked_content_attempted": 4,
                "linked_content_succeeded": 3,
                "linked_content_failed": 1,
                "linked_content_skipped": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        data_load_status_module,
        "DEFAULT_SUBSCRIPTION_EMAIL_SUMMARY_PATH",
        summary_path,
    )
    monkeypatch.setattr(
        data_load_status_module,
        "DEFAULT_SUBSCRIPTION_EMAIL_PROGRESS_PATH",
        progress_path,
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 19, 15, 0, tzinfo=UTC),
    )

    email_status = status["subscription_email_status"]
    assert email_status["status_label"] == "Analyzed 3/4 article links"
    assert email_status["processed_email_count"] == 5
    assert email_status["article_links_found"] == 4
    assert email_status["next_action"] == "Use analyzed email evidence where it matches a ticker."


def test_subscription_email_status_active_progress_does_not_inherit_old_counts(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    summary_path = tmp_path / "subscription-email-ingest.json"
    progress_path = tmp_path / "subscription-email-progress.json"
    summary_path.write_text(
        json.dumps(
            {
                "verdict": "needs_article_login",
                "fetched_at": "2026-05-19T10:10:28+00:00",
                "processed_emails": 10,
                "linked_content": {"login_required": 10, "skipped": 10, "succeeded": 0},
            }
        ),
        encoding="utf-8",
    )
    progress_path.write_text(
        json.dumps(
            {
                "state": "waiting_for_login_confirmation",
                "updated_at": "2026-05-27T12:39:54+00:00",
                "selected_email_count": 1,
                "article_links_found": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        data_load_status_module,
        "DEFAULT_SUBSCRIPTION_EMAIL_SUMMARY_PATH",
        summary_path,
    )
    monkeypatch.setattr(
        data_load_status_module,
        "DEFAULT_SUBSCRIPTION_EMAIL_PROGRESS_PATH",
        progress_path,
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 27, 12, 40, tzinfo=UTC),
    )

    email_status = status["subscription_email_status"]
    assert email_status["processed_email_count"] == 1
    assert email_status["article_links_found"] == 1
    assert email_status["linked_content_skipped"] == 0
    assert email_status["login_required"] == 1
    assert (
        email_status["continue_action_url"] == "/scheduler/subscription-emails/continue-after-login"
    )
    assert email_status["continue_button_label"] == "I logged in - open and analyze articles"


def test_subscription_email_status_reports_chrome_access_needed_after_login_ack(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    summary_path = tmp_path / "subscription-email-ingest.json"
    progress_path = tmp_path / "subscription-email-progress.json"
    detail = (
        "could not connect to Chrome DevTools at http://127.0.0.1:9222 "
        "after opening regular Chrome."
    )
    summary_path.write_text(
        json.dumps(
            {
                "verdict": "needs_article_login",
                "fetched_at": "2026-05-27T13:00:00+00:00",
                "processed_emails": 10,
                "linked_content": {"login_required": 10, "skipped": 10, "succeeded": 0},
            }
        ),
        encoding="utf-8",
    )
    progress_path.write_text(
        json.dumps(
            {
                "state": "login_acknowledgement_required",
                "status_class": "warn",
                "detail": detail,
                "updated_at": "2026-05-27T13:34:47+00:00",
                "selected_email_count": 10,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        data_load_status_module,
        "DEFAULT_SUBSCRIPTION_EMAIL_SUMMARY_PATH",
        summary_path,
    )
    monkeypatch.setattr(
        data_load_status_module,
        "DEFAULT_SUBSCRIPTION_EMAIL_PROGRESS_PATH",
        progress_path,
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 27, 13, 35, tzinfo=UTC),
    )

    email_status = status["subscription_email_status"]
    assert email_status["status_label"] == "Chrome agent access needed"
    assert email_status["status_class"] == "warn"
    assert detail in email_status["detail"]
    assert (
        "No current subscription email article-analysis progress file" not in email_status["detail"]
    )
    assert email_status["progress_label"] == (
        "Login acknowledged; Chrome agent access not connected"
    )
    assert email_status["progress_percent"] == 0
    assert "Close all Chrome windows" in email_status["next_action"]
    assert (
        email_status["continue_action_url"] == "/scheduler/subscription-emails/continue-after-login"
    )
    assert email_status["continue_button_label"] == "I logged in - open and analyze articles"


def test_subscription_email_status_prefers_portfolio_news_agent_bridge(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    monkeypatch.setattr(
        data_load_status_module,
        "load_portfolio_news_agent_status",
        lambda: {
            "source_agent": "portfolio_news_agent",
            "state": "success",
            "status_label": "SA email evidence analyzed",
            "status_class": "pass",
            "processed_email_count": 2,
            "article_links_found": 2,
            "linked_content_attempted": 2,
            "linked_content_succeeded": 2,
            "linked_content_failed": 0,
            "linked_content_skipped": 0,
            "cache_hits": 0,
            "login_required": 0,
            "unavailable": 0,
            "updated_at": "2026-05-27T12:03:00+00:00",
            "detail": "Portfolio News Agent DB is authoritative.",
            "next_action": "Use article summaries.",
            "progress_label": "2/2 SA article links analyzed",
            "progress_percent": 100,
            "progress_style": "width: 100%",
            "refresh_action_url": "/scheduler/subscription-emails/login-refresh",
            "refresh_button_label": "Open SA browser and verify login",
            "continue_action_url": "/scheduler/subscription-emails/continue-after-login",
            "continue_button_label": "Analyze unread SA emails",
        },
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 27, 13, 35, tzinfo=UTC),
    )

    email_status = status["subscription_email_status"]
    assert email_status["source_agent"] == "portfolio_news_agent"
    assert email_status["status_label"] == "SA email evidence analyzed"
    assert email_status["refresh_button_label"] == "Open SA browser and verify login"
    assert email_status["continue_button_label"] == "Analyze unread SA emails"


def test_data_load_status_blocks_stale_health_monitor_rows(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    old_source = _source("daily-market-bars", freshness="FRESH", status="HEALTHY")
    old_source["checked_at"] = "2026-05-12T12:00:00+00:00"

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        source_health_rows=[old_source],
        source_health_origin="live runtime source-health reader",
        now=datetime(2026, 5, 12, 13, 0, tzinfo=UTC),
    )

    monitor = status["health_monitor"]
    assert isinstance(monitor, dict)
    assert monitor["status_label"] == "Health Monitor Needs Refresh"
    assert monitor["status_class"] == "block"
    assert monitor["live"] is False
    assert monitor["reliable"] is False


def test_premarket_lane_is_not_required_before_premarket_window(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_ready_core_market_lanes(paths)
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 0,
            "market_flow_trend": 2,
        },
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 12, 7, 15, tzinfo=UTC),
    )

    premarket = _lane(status, "pre_market_unusual_activity")
    assert status["tradable_ready"] is True
    assert premarket["status"] == "ready"
    assert premarket["required_now"] is False
    assert premarket["expected_count"] is None
    assert "next pre-market refresh starts at" in premarket["detail"]


def test_premarket_lane_blocks_during_premarket_when_raw_lane_is_stale(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_ready_core_market_lanes(paths)
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T11:58:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_premarket_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-10T11:58:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 12, 0, tzinfo=UTC),
    )

    premarket = _lane(status, "pre_market_unusual_activity")
    assert status["tradable_ready"] is False
    assert premarket["status"] == "blocked"
    assert premarket["required_now"] is True
    assert premarket["source_status"] == "STALE"
    assert any(blocker["item"] == "pre_market_unusual_activity" for blocker in status["blockers"])
    massive_source = next(
        row for row in status["freshness_rows"] if row["source"] == "massive-stock-trades"
    )
    assert massive_source["status"] == "STALE"
    assert "massive_premarket_trade_slices" in str(massive_source["detail"])
    source_summary = status["source_summary"]
    assert isinstance(source_summary, dict)
    assert source_summary["critical_blocker_count"] == 1


def test_premarket_trade_lane_accepts_twenty_minute_old_proof(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_ready_core_market_lanes(paths)
    for lane_id in ("massive_live_trade_slices", "massive_premarket_trade_slices"):
        _write_massive_lane_manifest(
            paths["manifest_root"],
            lane_id=lane_id,
            tickers=["AAPL", "MSFT"],
            fetched_at="2026-05-11T12:00:00+00:00",
            coverage=[
                {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
                {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
            ],
        )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 12, 20, tzinfo=UTC),
    )

    premarket = _lane(status, "pre_market_unusual_activity")
    massive_source = next(
        row for row in status["freshness_rows"] if row["source"] == "massive-stock-trades"
    )
    assert status["tradable_ready"] is True
    assert premarket["status"] == "ready"
    assert premarket["source_status"] == "HEALTHY"
    assert massive_source["status"] == "HEALTHY"
    assert not [
        blocker
        for blocker in status["blockers"]
        if blocker["item"] == "pre_market_unusual_activity"
    ]


def test_data_load_status_operator_copy_avoids_raw_stale_wording(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    _write_ready_core_market_lanes(paths)
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T14:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    displayed_text = " ".join(
        [
            str(status["detail"]),
            *[str(row["detail"]) for row in status["datasets"]],
            *[str(row["detail"]) for row in status["freshness_rows"]],
            *[str(issue["reason"]) for issue in status["blockers"]],
            *[str(issue["reason"]) for issue in status["warnings"]],
        ]
    )
    assert "stale" not in displayed_text.lower()
    assert "is needs refresh" not in displayed_text.lower()
    assert "needs refresh" in displayed_text.lower()


def test_data_load_status_handles_corrupt_manifest_gracefully(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    paths = _fixtures(tmp_path, monkeypatch)
    (paths["manifest_root"] / "prices_daily.json").write_text(
        "{invalid json}",
        encoding="utf-8",
    )

    status = load_data_load_status(
        config_path=paths["config"],
        universe_path=paths["universe"],
        manifest_root=paths["manifest_root"],
        parquet_root=paths["parquet_root"],
        runtime_summary_path=paths["runtime_summary"],
        source_health_path=paths["source_health"],
        now=datetime(2026, 5, 11, 15, 2, tzinfo=UTC),
    )

    assert status["state"] in {"blocked", "attention", "error", "missing"}
    assert _dataset(status, "prices_daily")["status"] in {"missing", "blocked"}


def _fixtures(tmp_path: Path, monkeypatch: MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setattr(
        data_load_status_module,
        "load_portfolio_news_agent_status",
        lambda: {"state": "not_configured"},
    )
    manifest_root = tmp_path / "manifests"
    parquet_root = tmp_path / "parquet"
    manifest_root.mkdir()
    parquet_root.mkdir()
    config = tmp_path / "live-refresh.local.json"
    config.write_text(
        json.dumps(
            {
                "end": "2026-05-11",
                "datasets": [
                    "prices_daily",
                    "stock_trades",
                    "sec_company_facts",
                    "sec_form4",
                    "sec_13f",
                    "news_rss",
                    "subscription_emails",
                ],
                "runtime_universe": "active",
                "runtime_signals": [
                    "fundamentals",
                    "insider",
                    "institutional",
                    "abnormal_volume",
                    "technical_analysis",
                    "buy_sell_pressure",
                    "block_trade_pressure",
                    "unusual_trade_activity",
                    "pre_market_unusual_activity",
                    "market_flow_trend",
                    "sector_momentum",
                    "news",
                    "subscription_thesis",
                ],
                "market_data_provider": "massive",
            }
        ),
        encoding="utf-8",
    )
    universe = tmp_path / "universe_membership.parquet"
    pd.DataFrame(
        [
            _member("AAPL", date(2019, 1, 1), None),
            _member("MSFT", date(2019, 1, 1), None),
        ]
    ).to_parquet(universe, index=False)
    refresh_status = tmp_path / "data-refresh-status.json"
    refresh_status.write_text(
        json.dumps(
            {
                "progress": {
                    "state": "complete",
                    "total_jobs": 2,
                    "completed_jobs": 2,
                    "percent_complete": 100,
                },
                "jobs": [
                    {"dataset": "prices_daily", "status": "passed"},
                    {"dataset": "stock_trades", "status": "passed"},
                ],
            }
        ),
        encoding="utf-8",
    )
    source_health = tmp_path / "source-health.json"
    source_health.write_text("[]", encoding="utf-8")
    runtime_summary = tmp_path / "live-runtime-cycle-summary.json"
    monkeypatch.setenv("DATA_REFRESH_STATUS_PATH", str(refresh_status))
    monkeypatch.setenv("MASSIVE_API_KEY", "key")
    return {
        "config": config,
        "universe": universe,
        "manifest_root": manifest_root,
        "parquet_root": parquet_root,
        "refresh_status": refresh_status,
        "runtime_summary": runtime_summary,
        "source_health": source_health,
    }


def _write_manifest(
    manifest_root: Path,
    dataset: str,
    *,
    row_count: int,
    tickers: list[str] | None = None,
    path: str | None = None,
    max_timestamp_as_of: str = "2026-05-11T00:00:00+00:00",
    fetched_at: str | None = None,
    stale_after: str | None = None,
    issues: list[dict[str, object]] | None = None,
    **extra: object,
) -> None:
    payload: dict[str, object] = {
        "dataset": dataset,
        "row_count": row_count,
        "issues": issues or [],
        "path": path or dataset,
        "max_timestamp_as_of": max_timestamp_as_of,
    }
    if fetched_at is not None:
        payload["fetched_at"] = fetched_at
    if stale_after is not None:
        payload["stale_after"] = stale_after
    if tickers is not None:
        payload["tickers"] = tickers
    payload.update(extra)
    (manifest_root / f"{dataset}.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_runtime_summary(path: Path, lane_counts: dict[str, int]) -> None:
    path.write_text(
        json.dumps(
            {
                "cycle_id": "live-ready-test",
                "evidence_pack_count": 2,
                "signal_count": sum(lane_counts.values()),
                "lane_counts": lane_counts,
                "prompt_audit_count": 1,
            }
        ),
        encoding="utf-8",
    )


def _write_source_health(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


def _write_ready_core_market_lanes(paths: dict[str, Path]) -> None:
    _write_manifest(
        paths["manifest_root"],
        "prices_daily",
        row_count=20,
        tickers=["AAPL", "MSFT"],
    )
    _write_manifest(
        paths["manifest_root"],
        "stock_trades",
        row_count=200,
        tickers=["AAPL", "MSFT"],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_daily_bars",
        dataset="prices_daily",
        source_manifest="prices_daily.json",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_massive_lane_manifest(
        paths["manifest_root"],
        lane_id="massive_live_trade_slices",
        tickers=["AAPL", "MSFT"],
        fetched_at="2026-05-11T15:00:00+00:00",
        coverage=[
            {"ticker": "AAPL", "coverage_status": "complete", "complete": True},
            {"ticker": "MSFT", "coverage_status": "complete", "complete": True},
        ],
    )
    _write_runtime_summary(
        paths["runtime_summary"],
        {
            "abnormal_volume": 2,
            "technical_analysis": 2,
            "buy_sell_pressure": 2,
            "block_trade_pressure": 2,
            "unusual_trade_activity": 2,
            "pre_market_unusual_activity": 2,
            "market_flow_trend": 2,
        },
    )
    _write_source_health(
        paths["source_health"],
        [
            _source("daily-market-bars", freshness="FRESH", status="HEALTHY"),
            _source("massive-stock-trades", freshness="FRESH", status="HEALTHY"),
        ],
    )


def _source(source: str, *, freshness: str, status: str) -> dict[str, object]:
    checked_at = datetime.now(UTC).isoformat()
    return {
        "schema_version": "0.1.0",
        "source": source,
        "source_tier": "MARKET_DATA",
        "status": status,
        "checked_at": checked_at,
        "freshness": freshness,
        "last_success_at": checked_at,
        "observed_lag_seconds": 3600,
        "error_count": 0,
        "reliability_score": 1.0,
        "rate_limit_reset_at": None,
        "notes": [],
    }


def _partition(parquet_root: Path, dataset: str, ticker: str) -> None:
    path = parquet_root / dataset / f"ticker={ticker}"
    path.mkdir(parents=True)
    (path / "rows.parquet").write_bytes(b"placeholder")


def _write_stock_trade_coverage(
    parquet_root: Path,
    statuses: dict[str, str | dict[str, object]],
) -> None:
    root = parquet_root / "stock_trades"
    root.mkdir(parents=True, exist_ok=True)
    rows = {}
    for key, status in statuses.items():
        ticker, trade_date = key.split("|", 1)
        extra = {"coverage_status": status} if isinstance(status, str) else dict(status)
        rows[key] = {
            "ticker": ticker,
            "trade_date": trade_date,
            **extra,
        }
    (root / "_coverage.json").write_text(
        json.dumps({"schema_version": "0.1.0", "ticker_days": rows}),
        encoding="utf-8",
    )


def _write_stock_trade_parquet(
    parquet_root: Path,
    ticker: str,
    rows: list[dict[str, object]],
) -> None:
    path = parquet_root / "stock_trades" / f"ticker={ticker}" / "year=2026"
    path.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path / "trades.parquet", index=False)


def _write_massive_lane_manifest(
    manifest_root: Path,
    *,
    lane_id: str,
    dataset: str = "stock_trades",
    source_manifest: str = "stock_trades.json",
    tickers: list[str],
    fetched_at: str,
    coverage: list[dict[str, object]],
    window_start: str = "2026-05-11",
    window_end: str = "2026-05-11",
    issues: list[dict[str, object]] | None = None,
) -> None:
    root = manifest_root / "massive_lanes"
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "0.1.0",
        "lane_id": lane_id,
        "dataset": dataset,
        "raw_source_dataset": dataset,
        "fetched_at": fetched_at,
        "window": {"start": window_start, "end": window_end},
        "ticker_count": len(tickers),
        "tickers": tickers,
        "row_count": 1000,
        "source_manifest": source_manifest,
        "status": "complete",
        "coverage_pct": 100,
        "coverage": coverage,
        "issues": issues or [],
        "issue_count": len(issues or []),
    }
    (root / f"{lane_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _member(ticker: str, start: date, end: date | None) -> dict[str, object]:
    return {"ticker": ticker, "start_date": start, "end_date": end}


def _dataset(status: dict[str, object], name: str) -> dict[str, object]:
    return _row_by_key(
        status,
        collection="datasets",
        key="dataset",
        value=name,
        missing_label="dataset",
    )


def _lane(status: dict[str, object], name: str) -> dict[str, object]:
    return _row_by_key(
        status,
        collection="lanes",
        key="lane",
        value=name,
        missing_label="lane",
    )


def _lane_state(status: dict[str, object], name: str) -> dict[str, object]:
    return _row_by_key(
        status,
        collection="lane_states",
        key="lane_id",
        value=name,
        missing_label="lane state",
    )


def _source_row(status: dict[str, object], name: str) -> dict[str, object]:
    return _row_by_key(
        status,
        collection="freshness_rows",
        key="source",
        value=name,
        missing_label="source",
    )


def _row_by_key(
    status: dict[str, object],
    *,
    collection: str,
    key: str,
    value: str,
    missing_label: str,
) -> dict[str, object]:
    rows = status[collection]
    if not isinstance(rows, list):
        raise TypeError(f"{collection} must be a list")
    for row in rows:
        if isinstance(row, dict) and row.get(key) == value:
            return row
    raise AssertionError(f"missing {missing_label} {value}")
