from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
from prices.puller import pull_prices
from prices.storage import (
    PRICE_COLUMNS,
    DateRange,
    missing_ranges_for_ticker,
    write_price_frame,
)

FETCHED_AT = datetime(2026, 5, 8, tzinfo=UTC)


async def test_pull_prices_records_per_ticker_failures_and_writes_successes(
    tmp_path,
) -> None:
    async def downloader(ticker: str, _requested: DateRange) -> pd.DataFrame:
        if ticker == "MSFT":
            raise TimeoutError("provider read timed out")
        return pd.DataFrame([{"date": date(2026, 5, 8), "close": 100.0}])

    summary = await pull_prices(
        tickers=["AAPL", "MSFT"],
        requested=DateRange(date(2026, 5, 8), date(2026, 5, 8)),
        price_root=tmp_path / "prices_daily",
        manifest_path=tmp_path / "prices_daily.json",
        downloader=downloader,
        normalizer=_normalizer,
        clock=lambda: FETCHED_AT,
    )

    assert summary.rows_written == 1
    assert summary.issues == [
        {
            "ticker": "MSFT",
            "reason": "download_or_parse_failed",
            "detail": "provider read timed out",
        }
    ]
    assert (tmp_path / "prices_daily" / "ticker=AAPL").exists()
    assert (tmp_path / "prices_daily.json").exists()


def test_price_missing_ranges_find_holes_inside_existing_bounds(tmp_path) -> None:
    price_root = tmp_path / "prices_daily"
    write_price_frame(
        price_root,
        pd.DataFrame(
            [
                _price_row("AAPL", date(2026, 5, 1)),
                _price_row("AAPL", date(2026, 5, 3)),
            ]
        ),
    )

    ranges = missing_ranges_for_ticker(
        price_root,
        "AAPL",
        DateRange(date(2026, 5, 1), date(2026, 5, 3)),
    )

    assert ranges == [DateRange(date(2026, 5, 2), date(2026, 5, 2))]


def test_price_duplicate_writes_return_newly_persisted_count(tmp_path) -> None:
    price_root = tmp_path / "prices_daily"
    frame = pd.DataFrame([_price_row("AAPL", date(2026, 5, 8))])

    first = write_price_frame(price_root, frame)
    second = write_price_frame(price_root, frame)

    assert first == 1
    assert second == 0


def _normalizer(ticker: str, raw: pd.DataFrame, *, fetched_at: datetime) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    row = {
        "ticker": ticker,
        "year": 2026,
        "date": date(2026, 5, 8),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "adj_close": 100.0,
        "volume": 1000,
        "dividend": 0.0,
        "split_factor": 1.0,
        "source": "test",
        "fetched_at": fetched_at,
        "source_tier": "MARKET_DATA",
        "source_id": f"test:{ticker}:2026-05-08",
        "source_url": "https://example.test",
        "timestamp_observed": fetched_at,
        "timestamp_as_of": date(2026, 5, 8),
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }
    return pd.DataFrame([row])


def _price_row(ticker: str, observed_date: date) -> dict[str, object]:
    row = _normalizer(ticker, pd.DataFrame([{"date": observed_date}]), fetched_at=FETCHED_AT).iloc[
        0
    ].to_dict()
    row["date"] = observed_date
    row["source_id"] = f"test:{ticker}:{observed_date.isoformat()}"
    return row
