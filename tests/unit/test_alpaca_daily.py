from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pandas as pd
from prices.alpaca_daily import AlpacaDailyConfig, build_alpaca_downloader, normalize_alpaca_bars
from prices.storage import DateRange

EXPECTED_ADJ_CLOSE = 101.0
EXPECTED_PAGE_COUNT = 2


def test_normalize_alpaca_bars_writes_price_schema() -> None:
    raw = pd.DataFrame(
        [
            {"t": "2026-05-07T04:00:00Z", "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 1234},
            {"t": "2026-05-09T04:00:00Z", "o": 110.0, "h": 112.0, "l": 109.0, "c": 111.0, "v": 999},
        ]
    )
    raw.attrs["feed"] = "iex"
    raw.attrs["source_url"] = "https://data.alpaca.markets/v2/stocks/bars"
    raw.attrs["requested_start"] = date(2026, 5, 7)
    raw.attrs["requested_end"] = date(2026, 5, 8)

    frame = normalize_alpaca_bars(
        "aapl",
        raw,
        fetched_at=datetime(2026, 5, 8, tzinfo=UTC),
    )

    assert len(frame) == 1
    assert frame.iloc[0]["ticker"] == "AAPL"
    assert frame.iloc[0]["source"] == "alpaca"
    assert frame.iloc[0]["source_id"] == "alpaca:iex:AAPL:2026-05-07"
    assert frame.iloc[0]["adj_close"] == EXPECTED_ADJ_CLOSE


async def test_alpaca_downloader_requests_pages_with_auth_headers(tmp_path: Path) -> None:
    del tmp_path
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("page_token") == "next":
            payload = {
                "bars": {
                    "AAPL": [
                        {
                            "t": "2026-05-08T04:00:00Z",
                            "o": 102.0,
                            "h": 103.0,
                            "l": 101.0,
                            "c": 102.5,
                            "v": 1500,
                        }
                    ]
                }
            }
        else:
            payload = {
                "bars": {
                    "AAPL": [
                        {
                            "t": "2026-05-07T04:00:00Z",
                            "o": 100.0,
                            "h": 101.0,
                            "l": 99.0,
                            "c": 100.5,
                            "v": 1000,
                        }
                    ]
                },
                "next_page_token": "next",
            }
        return httpx.Response(200, json=payload)

    config = AlpacaDailyConfig(api_key="key", secret_key="secret", feed="iex")
    downloader = build_alpaca_downloader(config, transport=httpx.MockTransport(handler))

    frame = await downloader("AAPL", DateRange(date(2026, 5, 7), date(2026, 5, 8)))

    assert len(frame) == EXPECTED_PAGE_COUNT
    assert len(requests) == EXPECTED_PAGE_COUNT
    assert requests[0].headers["APCA-API-KEY-ID"] == "key"
    assert requests[0].url.params["symbols"] == "AAPL"
    assert requests[0].url.params["feed"] == "iex"
    assert requests[0].url.params["timeframe"] == "1Day"
