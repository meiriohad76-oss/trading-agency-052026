from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
from prices.massive_grouped_daily import (
    MassiveGroupedDailyConfig,
    normalize_massive_grouped_daily,
    pull_massive_grouped_daily,
)
from research.scripts.pull_massive_grouped_daily import _validate_lane_invocation

FETCHED_AT = datetime(2026, 5, 12, 6, 30, tzinfo=UTC)
OPEN_PRICE = 100.0
HIGH_PRICE = 102.0
LOW_PRICE = 99.0
CLOSE_PRICE = 101.0
VOLUME = 1_000


async def test_pull_massive_grouped_daily_filters_requested_tickers() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    _row("AAPL", 100.0, 101.0, 99.0, 100.5, 1_000),
                    _row("MSFT", 200.0, 201.0, 199.0, 200.5, 2_000),
                ]
            },
        )

    frame = await pull_massive_grouped_daily(
        day=date(2026, 5, 11),
        tickers=["aapl"],
        config=MassiveGroupedDailyConfig(api_key="key"),
        transport=httpx.MockTransport(handler),
        fetched_at=FETCHED_AT,
    )

    assert requests[0].url.path == "/v2/aggs/grouped/locale/us/market/stocks/2026-05-11"
    assert requests[0].url.params["apiKey"] == "key"
    assert frame["ticker"].to_list() == ["AAPL"]
    assert frame.iloc[0]["source_id"] == "massive-grouped:AAPL:2026-05-11"


def test_normalize_massive_grouped_daily_maps_price_schema() -> None:
    frame = normalize_massive_grouped_daily(
        day=date(2026, 5, 11),
        rows=[_row("AAPL", OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME)],
        tickers={"AAPL"},
        source_url="https://api.polygon.io",
        fetched_at=FETCHED_AT,
    )

    assert frame.iloc[0]["date"] == date(2026, 5, 11)
    assert frame.iloc[0]["open"] == OPEN_PRICE
    assert frame.iloc[0]["high"] == HIGH_PRICE
    assert frame.iloc[0]["low"] == LOW_PRICE
    assert frame.iloc[0]["close"] == CLOSE_PRICE
    assert frame.iloc[0]["volume"] == VOLUME
    assert frame.iloc[0]["verification_level"] == "CONFIRMED"


def test_grouped_daily_script_requires_daily_lane_and_explicit_tickers() -> None:
    class Args:
        lane_id = "massive_daily_bars"
        tickers = ["AAPL"]

    _validate_lane_invocation(Args())

    for lane_id, tickers in (
        ("massive_live_trade_slices", ["AAPL"]),
        ("massive_daily_bars", None),
    ):
        bad = Args()
        bad.lane_id = lane_id
        bad.tickers = tickers
        try:
            _validate_lane_invocation(bad)
        except SystemExit:
            pass
        else:
            raise AssertionError("invalid grouped-daily lane invocation should exit")


def _row(
    ticker: str,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: int,
) -> dict[str, object]:
    return {
        "T": ticker,
        "o": open_price,
        "h": high,
        "l": low,
        "c": close,
        "v": volume,
        "t": 1_778_457_600_000,
    }
