from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from pit.loader import PITLoader
from prices.puller import pull_prices
from prices.storage import DateRange, write_price_frame

TICKERS = ["AAPL", "MSFT"]
TOTAL_ROWS = 60
PIT_ROWS = 30


async def test_yfinance_puller_writes_partitioned_prices_for_pit_loader(
    tmp_path: Path,
) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    price_root = parquet_root / "prices_daily"
    manifest_path = manifest_root / "prices_daily.json"
    requested = DateRange(date(2022, 6, 1), date(2022, 6, 30))

    summary = await pull_prices(
        tickers=["aapl", "MSFT"],
        requested=requested,
        price_root=price_root,
        manifest_path=manifest_path,
        downloader=_fake_downloader,
        clock=lambda: datetime(2026, 5, 6, tzinfo=UTC),
    )

    assert summary.tickers_requested == len(TICKERS)
    assert summary.issues == []
    assert (price_root / "ticker=AAPL" / "year=2022" / "prices.parquet").is_file()
    assert (price_root / "ticker=MSFT" / "year=2022" / "prices.parquet").is_file()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dataset"] == "prices_daily"
    assert manifest["ticker_count"] == len(TICKERS)
    assert manifest["row_count"] == TOTAL_ROWS

    loader = PITLoader(
        parquet_root=parquet_root,
        manifest_root=manifest_root,
        today=lambda: date(2026, 5, 6),
    )
    result = loader.prices(TICKERS, date(2022, 6, 15), lookback_days=PIT_ROWS)

    assert result.height == PIT_ROWS
    assert set(result.get_column("ticker").to_list()) == set(TICKERS)
    assert set(result.columns).issuperset({"adj_close", "dividend", "split_factor"})


async def test_yfinance_puller_ignores_empty_edge_range_when_prices_exist(
    tmp_path: Path,
) -> None:
    price_root = tmp_path / "parquet" / "prices_daily"
    manifest_path = tmp_path / "manifests" / "prices_daily.json"
    write_price_frame(
        price_root,
        _normalized_price_frame("AAPL", [date(2021, 1, 4), date(2021, 1, 5)]),
    )

    summary = await pull_prices(
        tickers=["AAPL"],
        requested=DateRange(date(2021, 1, 1), date(2021, 1, 5)),
        price_root=price_root,
        manifest_path=manifest_path,
        downloader=_empty_downloader,
        clock=lambda: datetime(2026, 5, 6, tzinfo=UTC),
    )

    assert summary.issues == []
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["issues"] == []


async def _fake_downloader(ticker: str, requested: DateRange) -> pd.DataFrame:
    index = pd.date_range(requested.start, requested.end, freq="D", name="Date")
    offset = 10.0 if ticker.upper() == "MSFT" else 0.0
    return pd.DataFrame(
        {
            "Open": [100.0 + offset + row for row in range(len(index))],
            "High": [101.0 + offset + row for row in range(len(index))],
            "Low": [99.0 + offset + row for row in range(len(index))],
            "Close": [100.5 + offset + row for row in range(len(index))],
            "Adj Close": [100.25 + offset + row for row in range(len(index))],
            "Volume": [1000 + row for row in range(len(index))],
            "Dividends": [0.0 for _ in index],
            "Stock Splits": [0.0 for _ in index],
        },
        index=index,
    )


async def _empty_downloader(ticker: str, requested: DateRange) -> pd.DataFrame:
    del ticker, requested
    return pd.DataFrame()


def _normalized_price_frame(ticker: str, dates: list[date]) -> pd.DataFrame:
    fetched_at = datetime(2026, 5, 6, tzinfo=UTC)
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "year": value.year,
                "date": value,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "adj_close": 100.5,
                "volume": 1000,
                "dividend": 0.0,
                "split_factor": 1.0,
                "source": "fixture",
                "fetched_at": fetched_at,
                "source_tier": "MARKET_DATA",
                "source_id": f"fixture:{ticker}:{value}",
                "source_url": "fixture://prices",
                "timestamp_observed": fetched_at,
                "timestamp_as_of": value,
                "freshness": "STALE",
                "confidence": 1.0,
                "verification_level": "CONFIRMED",
            }
            for value in dates
        ]
    )
