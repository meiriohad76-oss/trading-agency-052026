from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pandas as pd
from prices.massive_daily import (
    MassiveDailyConfig,
    build_massive_downloader,
    normalize_massive_bars,
)
from prices.storage import DateRange

FETCHED_AT = datetime(2026, 5, 8, tzinfo=UTC)
EXPECTED_ROWS = 1
EXPECTED_CLOSE = 101.0


def test_normalize_massive_bars_writes_price_schema() -> None:
    raw = pd.DataFrame(
        [
            {
                "t": _ms("2026-05-07T04:00:00Z"),
                "o": 100.0,
                "h": 102.0,
                "l": 99.0,
                "c": 101.0,
                "v": 1234,
            },
            {
                "t": _ms("2026-05-09T04:00:00Z"),
                "o": 110.0,
                "h": 112.0,
                "l": 109.0,
                "c": 111.0,
                "v": 999,
            },
        ]
    )
    raw.attrs["source_url"] = "https://api.polygon.io/v2/aggs/ticker/AAPL"
    raw.attrs["requested_start"] = date(2026, 5, 7)
    raw.attrs["requested_end"] = date(2026, 5, 8)

    frame = normalize_massive_bars("aapl", raw, fetched_at=FETCHED_AT)

    assert len(frame) == EXPECTED_ROWS
    assert frame.iloc[0]["ticker"] == "AAPL"
    assert frame.iloc[0]["source"] == "massive"
    assert frame.iloc[0]["source_id"] == "massive:AAPL:2026-05-07"
    assert frame.iloc[0]["adj_close"] == EXPECTED_CLOSE
    assert frame.attrs == {}


async def test_massive_downloader_requests_daily_aggregate_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "t": _ms("2026-05-07T04:00:00Z"),
                        "o": 100.0,
                        "h": 102.0,
                        "l": 99.0,
                        "c": 101.0,
                        "v": 1234,
                    }
                ]
            },
        )

    config = MassiveDailyConfig(api_key="key", base_url="https://api.polygon.io")
    downloader = build_massive_downloader(config, transport=httpx.MockTransport(handler))

    frame = await downloader("AAPL", DateRange(date(2026, 5, 7), date(2026, 5, 8)))

    assert len(frame) == EXPECTED_ROWS
    assert requests[0].url.path == "/v2/aggs/ticker/AAPL/range/1/day/2026-05-07/2026-05-08"
    assert requests[0].url.params["apiKey"] == "key"
    assert requests[0].url.params["adjusted"] == "true"


def _ms(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1_000)
