from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pandas as pd
from prices.massive_grouped_daily import (
    MassiveGroupedDailyConfig,
    normalize_massive_grouped_daily,
    pull_massive_grouped_daily,
)
from prices.storage import DateRange, write_price_frame

from research.scripts.pull_massive_grouped_daily import (
    _fill_grouped_daily_missing_tickers,
    _normalize_tickers,
    _tickers_needing_history,
    _validate_lane_invocation,
)

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


async def test_grouped_daily_script_repairs_missing_ticker_with_daily_aggs() -> None:
    grouped = normalize_massive_grouped_daily(
        day=date(2026, 5, 11),
        rows=[_row("AAPL", OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME)],
        tickers={"AAPL", "BK"},
        source_url="https://api.polygon.io/v2/aggs/grouped/locale/us/market/stocks/2026-05-11",
        fetched_at=FETCHED_AT,
    )
    calls: list[tuple[str, DateRange]] = []

    async def fake_daily_downloader(ticker: str, requested: DateRange) -> pd.DataFrame:
        calls.append((ticker, requested))
        raw = pd.DataFrame(
            [
                {
                    "t": _ms("2026-05-11T04:00:00Z"),
                    "o": 40.0,
                    "h": 41.0,
                    "l": 39.0,
                    "c": 40.5,
                    "v": 500,
                }
            ]
        )
        raw.attrs["source_url"] = "https://api.polygon.io/v2/aggs/ticker/BK"
        raw.attrs["requested_start"] = date(2026, 5, 11)
        raw.attrs["requested_end"] = date(2026, 5, 11)
        raw.attrs["adjusted"] = True
        return raw

    frame = await _fill_grouped_daily_missing_tickers(
        day=date(2026, 5, 11),
        tickers=["AAPL", "BK"],
        grouped_frame=grouped,
        fetched_at=FETCHED_AT,
        daily_downloader=fake_daily_downloader,
    )

    assert calls == [("BK", DateRange(date(2026, 5, 4), date(2026, 5, 11)))]
    assert sorted(frame["ticker"].to_list()) == ["AAPL", "BK"]
    bk = frame[frame["ticker"] == "BK"].iloc[0]
    assert bk["source_id"] == "massive:BK:2026-05-11"
    assert bk["close"] == 40.5


async def test_grouped_daily_script_uses_latest_available_daily_aggs_bar() -> None:
    calls: list[tuple[str, DateRange]] = []

    async def fake_daily_downloader(ticker: str, requested: DateRange) -> pd.DataFrame:
        calls.append((ticker, requested))
        raw = pd.DataFrame(
            [
                {
                    "t": _ms("2026-05-20T04:00:00Z"),
                    "o": 39.0,
                    "h": 40.0,
                    "l": 38.0,
                    "c": 39.5,
                    "v": 400,
                }
            ]
        )
        raw.attrs["source_url"] = "https://api.polygon.io/v2/aggs/ticker/BK"
        raw.attrs["requested_start"] = requested.start
        raw.attrs["requested_end"] = requested.end
        raw.attrs["adjusted"] = True
        return raw

    frame = await _fill_grouped_daily_missing_tickers(
        day=date(2026, 5, 21),
        tickers=["BK"],
        grouped_frame=pd.DataFrame(),
        fetched_at=FETCHED_AT,
        daily_downloader=fake_daily_downloader,
    )

    assert calls == [("BK", DateRange(date(2026, 5, 14), date(2026, 5, 21)))]
    assert frame["ticker"].to_list() == ["BK"]
    assert frame.iloc[0]["date"] == date(2026, 5, 20)
    assert frame.iloc[0]["close"] == 39.5


def test_grouped_daily_history_bootstrap_detects_shallow_price_history(tmp_path) -> None:
    price_root = tmp_path / "prices_daily"
    write_price_frame(
        price_root,
        pd.DataFrame(
            [
                _price_row("AAPL", date(2026, 5, 7)),
                _price_row("AAPL", date(2026, 5, 8)),
                *[_price_row("MSFT", date(2026, 4, day)) for day in range(1, 6)],
            ]
        ),
    )

    needed = _tickers_needing_history(
        price_root,
        ["AAPL", "MSFT", "NVDA"],
        end=date(2026, 5, 8),
        lookback_days=60,
        min_observations=5,
    )

    assert needed == ["AAPL", "NVDA"]


def test_grouped_daily_normalizes_shell_ticker_whitespace() -> None:
    assert _normalize_tickers([" aapl", "MSFT\r", "msft", "", "  "]) == ["AAPL", "MSFT"]


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


def _ms(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1_000)


def _price_row(ticker: str, observed: date) -> dict[str, object]:
    return {
        "ticker": ticker,
        "year": observed.year,
        "date": observed,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "adj_close": 100.5,
        "volume": 1_000,
        "dividend": 0.0,
        "split_factor": 1.0,
        "source": "massive",
        "fetched_at": FETCHED_AT,
        "source_tier": "MARKET_DATA",
        "source_id": f"massive:{ticker}:{observed.isoformat()}",
        "source_url": "https://api.polygon.io",
        "timestamp_observed": FETCHED_AT,
        "timestamp_as_of": observed,
        "freshness": "FRESH",
        "confidence": 0.9,
        "verification_level": "CONFIRMED",
    }
