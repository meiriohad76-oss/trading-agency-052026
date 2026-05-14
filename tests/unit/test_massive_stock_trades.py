from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
from market_flow.classification import classify_trades
from market_flow.massive import (
    DownloadedTradeDay,
    MassiveTradesConfig,
    _params,
    normalize_massive_trades,
    pull_massive_trades,
)
from market_flow.storage import (
    DateRange,
    load_stock_trade_coverage_metadata,
    write_manifest,
    write_stock_trade_frame,
)
from research.scripts.pull_massive_stock_trades import StockTradeProgressWriter

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


def test_stock_trade_progress_writer_counts_partial_pull_as_processed(
    tmp_path: Path,
) -> None:
    progress_path = tmp_path / "stock-trades-progress.json"
    writer = StockTradeProgressWriter(
        path=progress_path,
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


def test_massive_trade_params_use_new_york_trade_date_window() -> None:
    params = _params(
        datetime(2026, 5, 6, tzinfo=UTC).date(),
        MassiveTradesConfig(api_key="key"),
    )

    assert params["timestamp.gte"] == "2026-05-06T04:00:00Z"
    assert params["timestamp.lt"] == "2026-05-07T04:00:00Z"


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
                    "next_url": "https://api.polygon.io/v3/trades/AAPL?cursor=page{}".format(
                        call_count
                    ),
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
