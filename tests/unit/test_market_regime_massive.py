# tests/unit/test_market_regime_massive.py
from __future__ import annotations

import httpx

from agency.market_regime.massive import (
    fetch_etf_daily_bars,
    fetch_grouped_daily_rows,
    fetch_intraday_snapshot,
)


def _bars_payload(ticker: str) -> dict:
    return {
        "results": [
            {"t": 1748390400000, "o": 100.0, "h": 102.0, "l": 99.0, "c": 101.0, "v": 1_000_000}
        ],
        "status": "OK",
    }


def _snapshot_payload() -> dict:
    return {
        "tickers": [
            {
                "ticker": "SPY",
                "day": {"c": 456.0},
                "prevDay": {"c": 450.0},
            },
            {
                "ticker": "XLK",
                "day": {"c": 200.0},
                "prevDay": {"c": 195.0},
            },
        ]
    }


def _grouped_payload() -> dict:
    return {
        "results": [
            {"T": "AAPL", "o": 10.0, "c": 11.0},
            {"T": "BBB", "o": 10.0, "c": 9.0},
        ]
    }


def _make_transport(routes: dict[str, dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        for pattern, payload in routes.items():
            if pattern in str(request.url):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={"status": "NOT_FOUND"})

    return httpx.MockTransport(handler)


def test_fetch_etf_daily_bars_returns_ticker_keyed_bars() -> None:
    transport = _make_transport(
        {
            "/v2/aggs/ticker/SPY": _bars_payload("SPY"),
            "/v2/aggs/ticker/QQQ": _bars_payload("QQQ"),
        }
    )
    result = fetch_etf_daily_bars(
        ["SPY", "QQQ"],
        start_date="2026-05-01",
        end_date="2026-05-28",
        api_key="test",
        _transport=transport,
    )
    assert "SPY" in result
    assert "QQQ" in result
    assert result["SPY"][0]["close"] == 101.0
    assert result["SPY"][0]["date"] != ""


def test_fetch_etf_daily_bars_skips_404_tickers() -> None:
    transport = _make_transport({"/v2/aggs/ticker/SPY": _bars_payload("SPY")})
    result = fetch_etf_daily_bars(
        ["SPY", "MISSING"],
        start_date="2026-05-01",
        end_date="2026-05-28",
        api_key="test",
        _transport=transport,
    )
    assert "SPY" in result
    assert "MISSING" not in result


def test_fetch_intraday_snapshot_returns_price_and_prior_close() -> None:
    transport = _make_transport({"/v2/snapshot": _snapshot_payload()})
    result = fetch_intraday_snapshot(["SPY", "XLK"], api_key="test", _transport=transport)
    assert result["SPY"]["price"] == 456.0
    assert result["SPY"]["prior_close"] == 450.0
    assert result["XLK"]["price"] == 200.0


def test_fetch_intraday_snapshot_still_accepts_results_alias() -> None:
    transport = _make_transport({"/v2/snapshot": {"results": _snapshot_payload()["tickers"]}})
    result = fetch_intraday_snapshot(["SPY"], api_key="test", _transport=transport)
    assert result["SPY"]["price"] == 456.0


def test_fetch_etf_daily_bars_skips_one_failed_ticker() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/v2/aggs/ticker/SPY" in url:
            return httpx.Response(200, json=_bars_payload("SPY"))
        if "/v2/aggs/ticker/QQQ" in url:
            return httpx.Response(429, json={"status": "RATE_LIMITED"})
        return httpx.Response(404, json={"status": "NOT_FOUND"})

    result = fetch_etf_daily_bars(
        ["SPY", "QQQ"],
        start_date="2026-05-01",
        end_date="2026-05-28",
        api_key="test",
        _transport=httpx.MockTransport(handler),
    )
    assert "SPY" in result
    assert "QQQ" not in result


def test_fetch_grouped_daily_rows_returns_open_close_rows() -> None:
    transport = _make_transport({"/v2/aggs/grouped": _grouped_payload()})
    result = fetch_grouped_daily_rows("2026-05-28", api_key="test", _transport=transport)
    assert len(result) == 2
    assert result[0]["open"] == 10.0
    assert result[0]["close"] == 11.0
