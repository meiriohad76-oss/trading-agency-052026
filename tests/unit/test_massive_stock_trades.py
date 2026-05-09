from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
from market_flow.classification import classify_trades
from market_flow.massive import MassiveTradesConfig, normalize_massive_trades, pull_massive_trades
from market_flow.storage import DateRange, write_manifest, write_stock_trade_frame

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
