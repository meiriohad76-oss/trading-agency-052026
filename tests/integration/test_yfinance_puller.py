from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from pit.loader import PITLoader
from prices.puller import pull_prices
from prices.storage import DateRange

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
