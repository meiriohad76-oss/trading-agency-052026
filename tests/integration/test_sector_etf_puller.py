from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from pit.loader import PITLoader
from prices.puller import pull_prices
from prices.sector_etfs import SECTOR_ETF_TICKERS, include_sector_etfs
from prices.storage import DateRange

LOOKBACK_BARS = 60
XLK_BASE_CLOSE = 133.37


async def test_sector_etfs_are_pulled_into_prices_daily_and_read_by_pit(
    tmp_path: Path,
) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    price_root = parquet_root / "prices_daily"
    manifest_path = manifest_root / "prices_daily.json"
    requested = DateRange(date(2022, 1, 3), date(2022, 6, 15))
    tickers = include_sector_etfs(["AAPL"])

    await pull_prices(
        tickers=tickers,
        requested=requested,
        price_root=price_root,
        manifest_path=manifest_path,
        downloader=_fake_downloader,
        clock=lambda: datetime(2026, 5, 6, tzinfo=UTC),
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["sector_etfs"]) == set(SECTOR_ETF_TICKERS)

    loader = PITLoader(
        parquet_root=parquet_root,
        manifest_root=manifest_root,
        today=lambda: date(2026, 5, 6),
    )
    result = loader.sector_etfs(date(2022, 6, 15), LOOKBACK_BARS)

    assert result.height == len(SECTOR_ETF_TICKERS) * LOOKBACK_BARS
    assert set(result.get_column("ticker").to_list()) == set(SECTOR_ETF_TICKERS)
    assert "AAPL" not in result.get_column("ticker").to_list()

    xlk_last = result.filter(
        (result["ticker"] == "XLK") & (result["date"] == date(2022, 6, 15))
    )
    assert xlk_last.get_column("close").item() == _expected_xlk_close(requested)


async def _fake_downloader(ticker: str, requested: DateRange) -> pd.DataFrame:
    index = pd.bdate_range(requested.start, requested.end, name="Date")
    offset = _ticker_offset(ticker)
    return pd.DataFrame(
        {
            "Open": [offset + row - 0.5 for row in range(len(index))],
            "High": [offset + row + 1.0 for row in range(len(index))],
            "Low": [offset + row - 1.0 for row in range(len(index))],
            "Close": [offset + row for row in range(len(index))],
            "Adj Close": [offset + row for row in range(len(index))],
            "Volume": [10_000 + row for row in range(len(index))],
            "Dividends": [0.0 for _ in index],
            "Stock Splits": [0.0 for _ in index],
        },
        index=index,
    )


def _ticker_offset(ticker: str) -> float:
    if ticker.upper() == "XLK":
        return XLK_BASE_CLOSE
    return float(sum(ord(char) for char in ticker.upper()))


def _expected_xlk_close(requested: DateRange) -> float:
    days = pd.bdate_range(requested.start, requested.end)
    return XLK_BASE_CLOSE + len(days) - 1
