from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pandas as pd
from market_flow.classification import classify_trades
from market_flow.massive import (
    MassiveTradesConfig,
    _params,
    _trade_session_window_utc,
    normalize_massive_trades,
    pull_massive_trades,
    redact_sensitive_text,
)
from market_flow.storage import (
    DateRange,
    load_stock_trade_coverage_metadata,
    update_stock_trade_coverage_metadata,
    write_manifest,
    write_stock_trade_frame,
)

from research.scripts.pull_massive_stock_trades import (
    MAX_LIVE_LANE_TICKERS,
    StockTradeProgressWriter,
    _lane_default_limit,
    _lane_resume_enabled,
    _merged_lane_manifest_payload,
    _selected_tickers,
    _validate_lane_invocation,
)

FETCHED_AT = datetime(2026, 5, 6, 13, 0, tzinfo=UTC)
EXPECTED_LAG = timedelta(minutes=15)


async def test_pull_massive_trades_downloads_day_and_writes_manifest(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"results": [_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")]},
        )

    summary = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=tmp_path / "stock_trades",
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(api_key="key", base_url="https://api.polygon.io"),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )

    assert summary.rows_written == 1
    assert requests[0].url.path == "/v3/trades/AAPL"
    assert requests[0].url.params["apiKey"] == "key"
    assert (tmp_path / "stock_trades.json").is_file()


def test_normalize_massive_trades_maps_short_fields_and_infers_pressure() -> None:
    frame = normalize_massive_trades(
        "aapl",
        pd.DataFrame(
            [
                _raw("1", 100.0, 100, "2026-05-06T12:00:00Z"),
                _raw("2", 101.0, 200, "2026-05-06T13:31:00Z"),
                _raw("3", 101.0, 300, "2026-05-06T13:32:00Z"),
                _raw(
                    "4",
                    99.0,
                    20_000,
                    "2026-05-06T13:33:00Z",
                    trf_timestamp="2026-05-06T13:33:01Z",
                ),
                _raw("bad", 200.0, 100, "2026-05-06T13:34:00Z", correction=1),
            ]
        ),
        fetched_at=FETCHED_AT,
        source_url="https://api.polygon.io/v3/trades/AAPL",
    )

    assert frame["ticker"].to_list() == ["AAPL", "AAPL", "AAPL", "AAPL"]
    assert frame["direction"].to_list() == [0, 1, 1, -1]
    assert frame["session"].to_list()[0] == "PRE_MARKET"
    assert frame["session"].to_list()[1:] == ["REGULAR", "REGULAR", "REGULAR"]
    assert bool(frame.iloc[-1]["is_off_exchange"]) is True
    assert bool(frame.iloc[-1]["is_block_trade"]) is True
    assert frame.iloc[0]["timestamp_as_of"] == frame.iloc[0]["trade_ts"] + EXPECTED_LAG
    assert frame.iloc[0]["source_tier"] == "CONFIRMED_TRADE_PRINT"
    assert frame.iloc[0]["verification_level"] == "CONFIRMED"


def test_classify_trades_marks_explicit_trf_off_exchange_and_venue() -> None:
    classified = classify_trades(
        pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "trade_ts": "2026-05-06T13:31:00Z",
                    "price": 100.0,
                    "size": 100,
                    "exchange": "4",
                    "trf_id": "201",
                    "sequence_number": 1,
                    "trade_id": "1",
                },
                {
                    "ticker": "AAPL",
                    "trade_ts": "2026-05-06T13:32:00Z",
                    "price": 100.0,
                    "size": 100,
                    "exchange": "4",
                    "trf_id": "",
                    "sequence_number": 2,
                    "trade_id": "2",
                },
            ]
        )
    )

    by_sequence = classified.set_index("sequence_number")
    assert bool(by_sequence.loc[1, "is_trf_off_exchange"]) is True
    assert bool(by_sequence.loc[1, "is_off_exchange"]) is True
    assert by_sequence.loc[1, "trf_venue"] == "FINRA/NYSE TRF"
    assert bool(by_sequence.loc[2, "is_trf_off_exchange"]) is False
    assert bool(by_sequence.loc[2, "is_off_exchange"]) is False
    assert by_sequence.loc[2, "trf_venue"] == ""


def test_premarket_trade_session_uses_0400_to_0930_eastern_window() -> None:
    start, end = _trade_session_window_utc(FETCHED_AT.date(), "pre_market")

    assert start.isoformat() == "2026-05-06T08:00:00+00:00"
    assert end.isoformat() == "2026-05-06T13:30:00+00:00"


async def test_pull_massive_trades_can_bound_pages_for_smoke_runs(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")],
                "next_url": "https://api.polygon.io/v3/trades/AAPL?cursor=next",
            },
        )

    summary = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=tmp_path / "stock_trades",
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(
            api_key="key",
            base_url="https://api.polygon.io",
            limit=100,
            max_pages_per_day=1,
        ),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )

    assert summary.rows_written == 1
    assert summary.coverage[0]["complete"] is False
    assert len(requests) == 1
    assert requests[0].url.params["limit"] == "100"
    coverage = load_stock_trade_coverage_metadata(tmp_path / "stock_trades")
    assert coverage["AAPL|2026-05-06"]["coverage_status"] == "partial"


async def test_pull_massive_trades_can_bound_seconds_for_runaway_ticker(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")],
                "next_url": "https://api.polygon.io/v3/trades/AAPL?cursor=next",
            },
        )

    summary = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=tmp_path / "stock_trades",
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(
            api_key="key",
            base_url="https://api.polygon.io",
            max_seconds_per_day=0.000001,
        ),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )

    assert summary.rows_written == 1
    assert len(requests) == 1
    assert summary.coverage[0]["complete"] is False
    assert summary.coverage[0]["stop_reason"] == "max_seconds_per_day"


def test_stock_trade_progress_writer_counts_partial_pull_as_processed(
    tmp_path: Path,
) -> None:
    progress_path = tmp_path / "stock-trades-progress.json"
    writer = StockTradeProgressWriter(
        path=progress_path,
        lane_id="massive_backtest_trade_tape",
        tickers=("AAPL",),
        start=FETCHED_AT.date(),
        end=FETCHED_AT.date(),
    )

    writer.mark_started()
    writer.update(
        {
            "ticker": "AAPL",
            "trade_date": FETCHED_AT.date().isoformat(),
            "pages_downloaded": 1,
            "rows_downloaded": 50_000,
            "status": "partial",
        }
    )
    writer.complete(
        rows_written=50_000,
        issues=[],
        coverage=[
            {
                "ticker": "AAPL",
                "trade_date": FETCHED_AT.date().isoformat(),
                "coverage_status": "partial",
                "complete": False,
            }
        ],
    )

    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert payload["state"] == "partial"
    assert payload["percent_complete"] == 100
    assert payload["ticker_days_completed"] == 0
    assert payload["ticker_days_processed"] == 1
    assert payload["ticker_days_partial"] == 1
    assert payload["pipeline_ready_tickers"] == []
    assert payload["pipeline_usable_tickers"] == []
    assert payload["pipeline_usable_count"] == 0
    assert payload["ticker_statuses"][0]["status"] == "partial"
    assert payload["ticker_statuses"][0]["usable_for_live_pipeline"] is False


def test_live_slice_progress_treats_bounded_partial_page_as_usable(
    tmp_path: Path,
) -> None:
    progress_path = tmp_path / "stock-trades-progress.json"
    writer = StockTradeProgressWriter(
        path=progress_path,
        lane_id="massive_live_trade_slices",
        tickers=("AAPL",),
        start=FETCHED_AT.date(),
        end=FETCHED_AT.date(),
    )

    writer.complete(
        rows_written=1_000,
        issues=[],
        coverage=[
            {
                "ticker": "AAPL",
                "trade_date": FETCHED_AT.date().isoformat(),
                "coverage_status": "partial",
                "complete": False,
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
                "stop_reason": "max_pages_per_day",
            }
        ],
    )

    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert payload["state"] == "partial"
    assert payload["pipeline_ready_tickers"] == []
    assert payload["pipeline_usable_tickers"] == ["AAPL"]
    assert payload["pipeline_pending_tickers"] == []
    assert payload["ticker_statuses"][0]["usable_for_live_pipeline"] is True


def test_stock_trade_script_defaults_to_active_universe_only(tmp_path: Path) -> None:
    universe_path = tmp_path / "universe_membership.parquet"
    pd.DataFrame(
        [
            {
                "ticker": "AAPL",
                "start_date": "2020-01-01",
                "end_date": None,
            },
            {
                "ticker": "OLD",
                "start_date": "2020-01-01",
                "end_date": "2026-05-01",
            },
            {
                "ticker": "FUTR",
                "start_date": "2026-06-01",
                "end_date": None,
            },
        ]
    ).to_parquet(universe_path)

    args = SimpleNamespace(
        ticker=None,
        full_universe=False,
        include_inactive_universe=False,
        universe_path=universe_path,
        end=FETCHED_AT.date(),
    )

    assert _selected_tickers(args) == ("AAPL",)


def test_stock_trade_script_requires_explicit_lane_tickers_and_single_day() -> None:
    valid = SimpleNamespace(
        lane_id="massive_live_trade_slices",
        ticker=["AAPL"],
        full_universe=False,
        include_inactive_universe=False,
        allow_long_window=False,
        start=FETCHED_AT.date(),
        end=FETCHED_AT.date(),
        trade_session=None,
    )

    _validate_lane_invocation(valid)

    no_ticker = SimpleNamespace(**{**valid.__dict__, "ticker": None})
    bad_lane = SimpleNamespace(**{**valid.__dict__, "lane_id": "massive_backtest_trade_tape"})
    multi_day = SimpleNamespace(
        **{**valid.__dict__, "end": (FETCHED_AT + timedelta(days=1)).date()}
    )
    active_universe = SimpleNamespace(
        **{**valid.__dict__, "ticker": [f"T{i:03d}" for i in range(168)]}
    )
    broad = SimpleNamespace(
        **{
            **valid.__dict__,
            "ticker": [f"T{i:03d}" for i in range(MAX_LIVE_LANE_TICKERS + 1)],
        }
    )

    _validate_lane_invocation(active_universe)

    for args in (no_ticker, bad_lane, multi_day, broad):
        try:
            _validate_lane_invocation(args)
        except SystemExit:
            pass
        else:
            raise AssertionError("invalid live lane invocation should exit")


def test_stock_trade_script_live_lanes_default_to_small_latest_slice() -> None:
    assert _lane_default_limit("massive_live_trade_slices", None) == 1_000
    assert _lane_default_limit("massive_premarket_trade_slices", None) == 1_000
    assert _lane_default_limit("massive_backtest_trade_tape", None) == 50_000
    assert _lane_default_limit("massive_live_trade_slices", 500) == 500


def test_stock_trade_live_script_does_not_resume_partial_backtest_cursors() -> None:
    assert _lane_resume_enabled("massive_backtest_trade_tape") is False
    assert _lane_resume_enabled("massive_live_trade_slices") is False
    assert _lane_resume_enabled("massive_premarket_trade_slices") is False


def test_live_lane_coverage_pct_counts_bounded_pages_as_lane_coverage() -> None:
    from research.scripts.pull_massive_stock_trades import _lane_coverage_pct

    coverage = [
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
            "order": "asc",
        },
    ]

    assert _lane_coverage_pct("massive_live_trade_slices", coverage) == 50
    assert _lane_coverage_pct("massive_backtest_trade_tape", coverage) is None


def test_live_lane_manifest_merge_keeps_prior_batch_coverage(tmp_path: Path) -> None:
    manifest_path = tmp_path / "massive_live_trade_slices.json"
    manifest_path.write_text(
        json.dumps(
            {
                "lane_id": "massive_live_trade_slices",
                "window": {"start": "2026-05-06", "end": "2026-05-06"},
                "row_count": 100,
                "coverage": [
                    {
                        "ticker": "AAPL",
                        "trade_date": "2026-05-06",
                        "coverage_status": "partial",
                        "downloaded_row_count": 1000,
                        "pages_downloaded": 1,
                        "order": "desc",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    payload = _merged_lane_manifest_payload(
        manifest_path,
        lane_id="massive_live_trade_slices",
        fetched_at=FETCHED_AT,
        requested_start=FETCHED_AT.date(),
        requested_end=FETCHED_AT.date(),
        tickers=("MSFT",),
        rows_written=50,
        issues=[],
        coverage=[
            {
                "ticker": "MSFT",
                "trade_date": "2026-05-06",
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "desc",
            }
        ],
        page_limit=1,
    )

    assert payload["tickers"] == ["AAPL", "MSFT"]
    assert payload["row_count"] == 150
    assert {row["ticker"] for row in payload["coverage"]} == {"AAPL", "MSFT"}
    assert payload["status"] == "partial_usable"


def test_live_lane_manifest_merge_does_not_mark_unverified_complete_boundary_as_complete(
    tmp_path: Path,
) -> None:
    payload = _merged_lane_manifest_payload(
        tmp_path / "massive_live_trade_slices.json",
        lane_id="massive_live_trade_slices",
        fetched_at=FETCHED_AT,
        requested_start=FETCHED_AT.date(),
        requested_end=FETCHED_AT.date(),
        tickers=("AAPL",),
        rows_written=50,
        issues=[],
        coverage=[
            {
                "ticker": "AAPL",
                "trade_date": "2026-05-06",
                "coverage_status": "complete",
                "complete": True,
                "row_count_verified": False,
            }
        ],
        page_limit=1,
    )

    assert payload["status"] == "partial"


def test_live_lane_manifest_merge_flags_non_desc_partial_slice(tmp_path: Path) -> None:
    manifest_path = tmp_path / "massive_live_trade_slices.json"

    payload = _merged_lane_manifest_payload(
        manifest_path,
        lane_id="massive_live_trade_slices",
        fetched_at=FETCHED_AT,
        requested_start=FETCHED_AT.date(),
        requested_end=FETCHED_AT.date(),
        tickers=("AAPL",),
        rows_written=50,
        issues=[],
        coverage=[
            {
                "ticker": "AAPL",
                "trade_date": "2026-05-06",
                "coverage_status": "partial",
                "downloaded_row_count": 1000,
                "pages_downloaded": 1,
                "order": "asc",
            }
        ],
        page_limit=1,
    )

    assert payload["status"] == "partial"
    assert payload["issues"] == [
        {
            "ticker": "AAPL",
            "trade_date": "2026-05-06",
            "reason": "latest live trade slice failed",
        }
    ]


def test_stock_trade_progress_writer_marks_complete_ticker_pipeline_ready(
    tmp_path: Path,
) -> None:
    progress_path = tmp_path / "stock-trades-progress.json"
    writer = StockTradeProgressWriter(
        path=progress_path,
        tickers=("AAPL", "MSFT"),
        start=FETCHED_AT.date(),
        end=FETCHED_AT.date(),
    )

    writer.mark_started()
    writer.update(
        {
            "ticker": "AAPL",
            "trade_date": FETCHED_AT.date().isoformat(),
            "pages_downloaded": 1,
            "rows_downloaded": 100,
            "status": "complete",
            "durable": True,
        }
    )

    payload = json.loads(progress_path.read_text(encoding="utf-8"))
    statuses = {row["ticker"]: row["status"] for row in payload["ticker_statuses"]}
    assert payload["pipeline_ready_tickers"] == ["AAPL"]
    assert payload["pipeline_usable_tickers"] == ["AAPL"]
    assert payload["pipeline_ready_count"] == 1
    assert payload["pipeline_usable_count"] == 1
    assert statuses == {"AAPL": "complete", "MSFT": "pending"}


async def test_pull_massive_trades_persists_successful_days_when_later_day_fails(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"results": [_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")]},
            )
        return httpx.Response(429, json={"error": "rate limited"})

    summary = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), (FETCHED_AT + timedelta(days=1)).date()),
        trade_root=tmp_path / "stock_trades",
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(api_key="key", base_url="https://api.polygon.io"),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )

    assert summary.rows_written == 1
    assert summary.coverage[0]["coverage_status"] == "complete"
    assert summary.coverage[1]["coverage_status"] == "failed"
    assert (tmp_path / "stock_trades" / "ticker=AAPL" / "year=2026" / "trades.parquet").is_file()


async def test_pull_massive_trades_flushes_completed_ticker_before_next_ticker(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []
    aapl_partition = tmp_path / "stock_trades" / "ticker=AAPL" / "year=2026" / "trades.parquet"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/AAPL"):
            return httpx.Response(
                200,
                json={"results": [_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")]},
            )
        assert aapl_partition.is_file()
        return httpx.Response(429, json={"error": "rate limited"})

    summary = await pull_massive_trades(
        tickers=("MSFT", "AAPL"),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=tmp_path / "stock_trades",
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(api_key="key", base_url="https://api.polygon.io"),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )

    assert [request.url.path for request in requests] == ["/v3/trades/AAPL", "/v3/trades/MSFT"]
    assert summary.rows_written == 1
    coverage = load_stock_trade_coverage_metadata(tmp_path / "stock_trades")
    assert coverage["AAPL|2026-05-06"]["coverage_status"] == "complete"


async def test_pull_massive_trades_can_request_latest_rows_first(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"results": [_raw("1", 100.0, 100, "2026-05-06T19:59:00Z")]},
        )

    await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=tmp_path / "stock_trades",
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(api_key="key", order="desc", max_pages_per_day=1),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )

    assert requests[0].url.params["order"] == "desc"


def test_normalize_massive_trades_accepts_millisecond_timestamps() -> None:
    frame = normalize_massive_trades(
        "aapl",
        pd.DataFrame(
            [
                {
                    "p": 100.0,
                    "s": 100,
                    "timestamp": _ms("2026-05-06T13:31:00Z"),
                    "i": "1",
                    "q": 1,
                }
            ]
        ),
        fetched_at=FETCHED_AT,
        source_url="https://api.polygon.io/v3/trades/AAPL",
    )

    assert frame.iloc[0]["trade_ts"] == pd.Timestamp("2026-05-06T13:31:00Z")


def test_normalize_massive_trades_keeps_sip_and_participant_timestamps_distinct() -> None:
    sip_timestamp = "2026-05-06T13:31:00Z"
    participant_timestamp = "2026-05-06T13:30:59Z"

    frame = normalize_massive_trades(
        "aapl",
        pd.DataFrame(
            [
                {
                    "p": 100.0,
                    "s": 100,
                    "y": _ns(sip_timestamp),
                    "t": _ns(participant_timestamp),
                    "i": "1",
                    "q": 1,
                }
            ]
        ),
        fetched_at=FETCHED_AT,
        source_url="https://api.polygon.io/v3/trades/AAPL",
    )

    assert frame.iloc[0]["trade_ts"] == pd.Timestamp(sip_timestamp)
    assert frame.iloc[0]["sip_timestamp"] == pd.Timestamp(sip_timestamp)
    assert frame.iloc[0]["participant_timestamp"] == pd.Timestamp(participant_timestamp)
    assert frame.iloc[0]["timestamp_as_of"] == pd.Timestamp(sip_timestamp) + EXPECTED_LAG


def test_classify_trades_handles_missing_correction_values() -> None:
    classified = classify_trades(
        pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "trade_ts": "2026-05-06T13:31:00Z",
                    "price": 100.0,
                    "size": 100,
                    "correction": pd.NA,
                    "exchange": "",
                    "conditions": "",
                    "sequence_number": 1,
                    "trade_id": "1",
                }
            ]
        )
    )

    assert len(classified) == 1


def test_classify_trades_adds_defaults_for_missing_optional_order_fields() -> None:
    classified = classify_trades(
        pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "trade_ts": "2026-05-06T13:31:00Z",
                    "price": 100.0,
                    "size": 100,
                    "correction": pd.NA,
                    "exchange": "",
                    "conditions": "",
                }
            ]
        )
    )

    assert len(classified) == 1
    assert classified.iloc[0]["sequence_number"] == 0
    assert classified.iloc[0]["trade_id"] == ""


def test_classify_trades_prefers_quote_rule_when_bid_ask_are_available() -> None:
    classified = classify_trades(
        pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "trade_ts": "2026-05-06T13:31:00Z",
                    "price": 100.0,
                    "bid": 99.0,
                    "ask": 101.0,
                    "size": 100,
                    "sequence_number": 1,
                    "trade_id": "1",
                },
                {
                    "ticker": "AAPL",
                    "trade_ts": "2026-05-06T13:32:00Z",
                    "price": 99.8,
                    "bid": 99.0,
                    "ask": 99.5,
                    "size": 100,
                    "sequence_number": 2,
                    "trade_id": "2",
                },
            ]
        )
    )

    row = classified.iloc[1]
    assert row["direction"] == 1
    assert row["direction_method"] == "quote_rule"
    assert row["direction_confidence"] > 0.8


def test_write_stock_trade_frame_and_manifest_support_partitioned_dataset(
    tmp_path: Path,
) -> None:
    frame = normalize_massive_trades(
        "aapl",
        pd.DataFrame([_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")]),
        fetched_at=FETCHED_AT,
        source_url="https://api.polygon.io/v3/trades/AAPL",
    )
    trade_root = tmp_path / "stock_trades"
    manifest_path = tmp_path / "stock_trades.json"

    rows_written = write_stock_trade_frame(trade_root, frame)
    write_manifest(
        manifest_path,
        trade_root,
        fetched_at=FETCHED_AT,
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        issues=[],
        source_url="https://api.polygon.io",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert rows_written == 1
    assert (trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet").is_file()
    assert manifest["dataset"] == "stock_trades"
    assert manifest["row_count"] == 1
    assert manifest["tickers"] == ["AAPL"]


def test_write_stock_trade_frame_returns_newly_persisted_row_count(tmp_path: Path) -> None:
    frame = normalize_massive_trades(
        "aapl",
        pd.DataFrame([_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")]),
        fetched_at=FETCHED_AT,
        source_url="https://api.polygon.io/v3/trades/AAPL",
    )
    trade_root = tmp_path / "stock_trades"

    first_count = write_stock_trade_frame(trade_root, frame)
    second_count = write_stock_trade_frame(trade_root, frame)
    persisted = pd.read_parquet(trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet")

    assert first_count == 1
    assert second_count == 0
    assert len(persisted) == 1


def test_write_stock_trade_frame_quarantines_corrupt_existing_partition(
    tmp_path: Path,
) -> None:
    frame = normalize_massive_trades(
        "hon",
        pd.DataFrame([_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")]),
        fetched_at=FETCHED_AT,
        source_url="https://api.polygon.io/v3/trades/HON",
    )
    trade_root = tmp_path / "stock_trades"
    partition = trade_root / "ticker=HON" / "year=2026" / "trades.parquet"
    partition.parent.mkdir(parents=True)
    partition.write_text("not parquet", encoding="utf-8")

    rows_written = write_stock_trade_frame(trade_root, frame)
    persisted = pd.read_parquet(partition)
    quarantined = list(partition.parent.glob("trades.parquet.corrupt-*"))

    assert rows_written == 1
    assert persisted["ticker"].to_list() == ["HON"]
    assert len(quarantined) == 1


def test_massive_trade_params_use_new_york_trade_date_window() -> None:
    params = _params(
        datetime(2026, 5, 6, tzinfo=UTC).date(),
        MassiveTradesConfig(api_key="key"),
    )

    assert params["timestamp.gte"] == str(_ns("2026-05-06T04:00:00Z"))
    assert params["timestamp.lt"] == str(_ns("2026-05-07T04:00:00Z"))


def test_redact_sensitive_text_removes_massive_api_key_from_errors() -> None:
    message = (
        "403 for url 'https://api.polygon.io/v3/trades/AAPL?timestamp.gte=1&apiKey=secret-token'"
    )

    redacted = redact_sensitive_text(message)

    assert "secret-token" not in redacted
    assert "apiKey=<redacted>" in redacted


def _raw(
    trade_id: str,
    price: float,
    size: int,
    timestamp: str,
    *,
    trf_timestamp: str | None = None,
    correction: int = 0,
) -> dict[str, object]:
    return {
        "p": price,
        "s": size,
        "y": _ns(timestamp),
        "x": 4,
        "c": ["@"],
        "i": trade_id,
        "q": int(trade_id, 36),
        "z": 3,
        "f": "TRF" if trf_timestamp else None,
        "r": _ns(trf_timestamp) if trf_timestamp else None,
        "e": correction,
    }


def _ns(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1_000_000_000)


def _ms(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1_000)


async def test_row_count_verified_true_when_last_page_partial(tmp_path: Path) -> None:
    """3-page response: pages 1-2 return limit=2 rows, page 3 returns 1 row (partial) — verified."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(
                200,
                json={
                    "results": [
                        _raw(str(call_count * 10), 100.0, 100, "2026-05-06T13:31:00Z"),
                        _raw(str(call_count * 10 + 1), 101.0, 200, "2026-05-06T13:32:00Z"),
                    ],
                    "results_count": 2,
                    "next_url": f"https://api.polygon.io/v3/trades/AAPL?cursor=page{call_count}",
                },
            )
        # Last page: fewer rows than limit
        return httpx.Response(
            200,
            json={
                "results": [_raw("99", 102.0, 300, "2026-05-06T13:33:00Z")],
                "results_count": 1,
            },
        )

    summary = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=tmp_path / "stock_trades",
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(api_key="key", base_url="https://api.polygon.io", limit=2),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )

    assert summary.rows_written == 5
    cov = summary.coverage[0]
    assert cov["complete"] is True
    assert cov["row_count_verified"] is True
    assert cov["last_page_results_count"] == 1


async def test_row_count_verified_false_when_last_page_exactly_limit(tmp_path: Path) -> None:
    """Single page returns exactly limit rows but no next_url — suspicious, not verified."""
    import warnings

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    _raw("1", 100.0, 100, "2026-05-06T13:31:00Z"),
                    _raw("2", 101.0, 200, "2026-05-06T13:32:00Z"),
                ],
                "results_count": 2,
                # No next_url: pagination ended exactly on a full page boundary
            },
        )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        summary = await pull_massive_trades(
            tickers=("aapl",),
            requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
            trade_root=tmp_path / "stock_trades",
            manifest_path=tmp_path / "stock_trades.json",
            config=MassiveTradesConfig(api_key="key", base_url="https://api.polygon.io", limit=2),
            transport=httpx.MockTransport(handler),
            clock=lambda: FETCHED_AT,
        )

    cov = summary.coverage[0]
    assert cov["complete"] is True
    assert cov["row_count_verified"] is False
    assert cov["last_page_results_count"] == 2

    warning_messages = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]
    assert any("pagination_completeness_uncertain" in msg for msg in warning_messages), (
        f"Expected pagination_completeness_uncertain warning, got: {warning_messages}"
    )


async def test_partial_trade_page_is_persisted_when_later_page_fails(tmp_path: Path) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                200,
                json={
                    "results": [_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")],
                    "results_count": 1,
                    "next_url": "https://api.polygon.io/v3/trades/AAPL?cursor=next",
                },
            )
        raise httpx.ConnectError("temporary network break", request=request)

    trade_root = tmp_path / "stock_trades"
    manifest_path = tmp_path / "stock_trades.json"

    summary = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=trade_root,
        manifest_path=manifest_path,
        config=MassiveTradesConfig(
            api_key="key",
            base_url="https://api.polygon.io",
            limit=1,
            request_retries=0,
        ),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )

    persisted = pd.read_parquet(trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert summary.issues == []
    assert summary.rows_written == 1
    assert len(persisted) == 1
    assert manifest["row_count"] == 1
    assert summary.coverage[0]["coverage_status"] == "partial"
    assert summary.coverage[0]["downloaded_row_count"] == 1
    assert summary.coverage[0]["rows_written"] == 1
    assert str(summary.coverage[0]["stop_reason"]).startswith("request_failed_after_partial")


async def test_partial_trade_repair_resumes_from_saved_cursor(tmp_path: Path) -> None:
    import warnings

    trade_root = tmp_path / "stock_trades"
    manifest_path = tmp_path / "stock_trades.json"
    seen_cursors: list[str | None] = []

    def first_handler(request: httpx.Request) -> httpx.Response:
        seen_cursors.append(request.url.params.get("cursor"))
        return httpx.Response(
            200,
            json={
                "results": [_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")],
                "results_count": 1,
                "next_url": "https://api.polygon.io/v3/trades/AAPL?cursor=resume-1",
            },
        )

    first = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=trade_root,
        manifest_path=manifest_path,
        config=MassiveTradesConfig(
            api_key="key",
            base_url="https://api.polygon.io",
            limit=1,
            max_pages_per_day=1,
        ),
        transport=httpx.MockTransport(first_handler),
        clock=lambda: FETCHED_AT,
    )
    coverage = load_stock_trade_coverage_metadata(trade_root)
    partial = coverage["AAPL|2026-05-06"]

    assert first.rows_written == 1
    assert partial["coverage_status"] == "partial"
    assert partial["downloaded_row_count"] == 1
    assert partial["pages_downloaded"] == 1
    assert partial["resume_cursor"] == "resume-1"

    def second_handler(request: httpx.Request) -> httpx.Response:
        seen_cursors.append(request.url.params.get("cursor"))
        return httpx.Response(
            200,
            json={
                "results": [_raw("2", 101.0, 200, "2026-05-06T13:32:00Z")],
                "results_count": 1,
            },
        )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        second = await pull_massive_trades(
            tickers=("aapl",),
            requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
            trade_root=trade_root,
            manifest_path=manifest_path,
            config=MassiveTradesConfig(
                api_key="key",
                base_url="https://api.polygon.io",
                limit=1,
                max_pages_per_day=1,
            ),
            transport=httpx.MockTransport(second_handler),
            clock=lambda: FETCHED_AT,
        )
    final_coverage = load_stock_trade_coverage_metadata(trade_root)["AAPL|2026-05-06"]
    persisted = pd.read_parquet(trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet")
    warning_messages = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]

    assert second.rows_written == 1
    assert seen_cursors == [None, "resume-1"]
    assert len(persisted) == 2
    assert final_coverage["coverage_status"] == "complete"
    assert final_coverage["row_count_verified"] is False
    assert final_coverage["downloaded_row_count"] == 2
    assert final_coverage["pages_downloaded"] == 2
    assert any("pagination_completeness_uncertain" in msg for msg in warning_messages), (
        f"Expected pagination_completeness_uncertain warning, got: {warning_messages}"
    )


async def test_live_slice_can_ignore_saved_backfill_cursor(tmp_path: Path) -> None:
    trade_root = tmp_path / "stock_trades"
    update_stock_trade_coverage_metadata(
        trade_root,
        [
            {
                "ticker": "AAPL",
                "trade_date": FETCHED_AT.date().isoformat(),
                "coverage_status": "partial",
                "complete": False,
                "resume_cursor": "old-full-depth-cursor",
                "downloaded_row_count": 50_000,
                "pages_downloaded": 1,
            }
        ],
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"results": [_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")]},
        )

    await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=trade_root,
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(
            api_key="key",
            base_url="https://api.polygon.io",
            limit=1_000,
            order="desc",
            max_pages_per_day=1,
            resume_partial=False,
        ),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )

    assert requests[0].url.params.get("cursor") is None
    assert requests[0].url.params["limit"] == "1000"


async def test_pagination_rows_outside_requested_date_are_not_persisted(tmp_path: Path) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                200,
                json={
                    "results": [_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")],
                    "results_count": 1,
                    "next_url": "https://api.polygon.io/v3/trades/AAPL?cursor=bad-window",
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [_raw("2", 101.0, 200, "2026-05-07T13:32:00Z")],
                "results_count": 1,
            },
        )

    trade_root = tmp_path / "stock_trades"
    summary = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=trade_root,
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(
            api_key="key",
            base_url="https://api.polygon.io",
            limit=1,
        ),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )
    persisted = pd.read_parquet(trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet")

    assert len(persisted) == 1
    assert persisted["trade_date"].astype(str).to_list() == ["2026-05-06"]
    assert summary.coverage[0]["coverage_status"] == "complete"
    assert summary.coverage[0]["row_count_verified"] is True
    assert summary.coverage[0]["stop_reason"] == "page_outside_requested_trade_date"
    assert summary.coverage[0]["resume_cursor"] is None


async def test_time_windowed_backfill_marks_cross_window_page_as_boundary(
    tmp_path: Path,
) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                200,
                json={
                    "results": [_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")],
                    "next_url": "https://api.polygon.io/v3/trades/AAPL?cursor=next-window",
                },
            )
        return httpx.Response(
            200,
            json={"results": [_raw(str(call_count), 101.0, 200, "2026-05-06T17:31:00Z")]},
        )

    trade_root = tmp_path / "stock_trades"
    summary = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=trade_root,
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(
            api_key="key",
            base_url="https://api.polygon.io",
            limit=2,
            window_minutes=720,
        ),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )
    coverage = load_stock_trade_coverage_metadata(trade_root)["AAPL|2026-05-06"]
    persisted = pd.read_parquet(trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet")

    assert call_count == 3
    assert summary.coverage[0]["coverage_status"] == "complete"
    assert coverage["completed_window_count"] == 2
    assert coverage["row_count_verified"] is True
    assert persisted["trade_date"].astype(str).to_list() == ["2026-05-06", "2026-05-06"]


async def test_time_windowed_backfill_completes_independent_subday_windows(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        timestamp = "2026-05-06T13:31:00Z" if len(requests) == 1 else "2026-05-06T17:31:00Z"
        return httpx.Response(
            200,
            json={"results": [_raw(str(len(requests)), 100.0, 100, timestamp)]},
        )

    summary = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=tmp_path / "stock_trades",
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(
            api_key="key",
            base_url="https://api.polygon.io",
            window_minutes=720,
        ),
        transport=httpx.MockTransport(handler),
        clock=lambda: FETCHED_AT,
    )
    coverage = load_stock_trade_coverage_metadata(tmp_path / "stock_trades")["AAPL|2026-05-06"]

    assert len(requests) == 2
    assert summary.rows_written == 2
    assert coverage["coverage_status"] == "complete"
    assert coverage["download_mode"] == "time_windowed"
    assert coverage["window_count"] == 2
    assert coverage["completed_window_count"] == 2
    assert requests[0].url.params["timestamp.gte"] == str(_ns("2026-05-06T04:00:00Z"))
    assert requests[0].url.params["timestamp.lt"] == str(_ns("2026-05-06T16:00:00Z"))
    assert requests[1].url.params["timestamp.gte"] == str(_ns("2026-05-06T16:00:00Z"))
    assert requests[1].url.params["timestamp.lt"] == str(_ns("2026-05-07T04:00:00Z"))


async def test_time_windowed_backfill_resumes_after_completed_windows(
    tmp_path: Path,
) -> None:
    trade_root = tmp_path / "stock_trades"
    manifest_path = tmp_path / "stock_trades.json"
    first_run_requests: list[httpx.Request] = []

    def first_handler(request: httpx.Request) -> httpx.Response:
        first_run_requests.append(request)
        if len(first_run_requests) == 1:
            return httpx.Response(
                200,
                json={"results": [_raw("1", 100.0, 100, "2026-05-06T13:31:00Z")]},
            )
        raise httpx.ConnectError("temporary network break", request=request)

    first = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=trade_root,
        manifest_path=manifest_path,
        config=MassiveTradesConfig(
            api_key="key",
            base_url="https://api.polygon.io",
            window_minutes=720,
            request_retries=0,
        ),
        transport=httpx.MockTransport(first_handler),
        clock=lambda: FETCHED_AT,
    )
    partial = load_stock_trade_coverage_metadata(trade_root)["AAPL|2026-05-06"]

    assert first.issues == []
    assert first.coverage[0]["coverage_status"] == "partial"
    assert partial["completed_window_count"] == 1

    second_run_requests: list[httpx.Request] = []

    def second_handler(request: httpx.Request) -> httpx.Response:
        second_run_requests.append(request)
        return httpx.Response(
            200,
            json={"results": [_raw("2", 101.0, 200, "2026-05-06T17:31:00Z")]},
        )

    second = await pull_massive_trades(
        tickers=("aapl",),
        requested=DateRange(FETCHED_AT.date(), FETCHED_AT.date()),
        trade_root=trade_root,
        manifest_path=manifest_path,
        config=MassiveTradesConfig(
            api_key="key",
            base_url="https://api.polygon.io",
            window_minutes=720,
            request_retries=0,
        ),
        transport=httpx.MockTransport(second_handler),
        clock=lambda: FETCHED_AT,
    )
    final_coverage = load_stock_trade_coverage_metadata(trade_root)["AAPL|2026-05-06"]
    persisted = pd.read_parquet(trade_root / "ticker=AAPL" / "year=2026" / "trades.parquet")

    assert second.coverage[0]["coverage_status"] == "complete"
    assert len(second_run_requests) == 1
    assert second_run_requests[0].url.params["timestamp.gte"] == str(_ns("2026-05-06T16:00:00Z"))
    assert final_coverage["completed_window_count"] == 2
    assert final_coverage["downloaded_row_count"] == 2
    assert len(persisted) == 2
