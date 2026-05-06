from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from prices.storage import DateRange, missing_ranges_for_ticker, write_price_frame


def test_missing_ranges_skip_existing_date_bounds(tmp_path: Path) -> None:
    price_root = tmp_path / "prices_daily"
    write_price_frame(
        price_root,
        _price_frame(
            "AAPL",
            [
                date(2020, 1, 1),
                date(2020, 3, 31),
            ],
        ),
    )

    ranges = missing_ranges_for_ticker(
        price_root,
        "AAPL",
        DateRange(date(2019, 12, 1), date(2020, 6, 30)),
    )

    assert ranges == [
        DateRange(date(2019, 12, 1), date(2019, 12, 31)),
        DateRange(date(2020, 4, 1), date(2020, 6, 30)),
    ]


def test_missing_ranges_refresh_downloads_full_request(tmp_path: Path) -> None:
    requested = DateRange(date(2020, 1, 1), date(2020, 1, 31))

    assert missing_ranges_for_ticker(
        tmp_path / "prices_daily",
        "AAPL",
        requested,
        refresh=True,
    ) == [requested]


def _price_frame(ticker: str, dates: list[date]) -> pd.DataFrame:
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
