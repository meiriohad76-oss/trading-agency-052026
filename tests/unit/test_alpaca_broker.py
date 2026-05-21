from __future__ import annotations

import json

import httpx
import pytest

from agency.broker.alpaca import (
    AlpacaBrokerClient,
    AlpacaBrokerError,
    AlpacaTradingConfig,
    _ssl_context,
    broker_snapshot,
    build_market_order_payload,
)

EXPECTED_REQUEST_COUNT = 3
EXPECTED_GROSS_EXPOSURE = 25.0
EXPECTED_CLOSE_POSITION_QTY = 0.01706939


def test_alpaca_ssl_context_is_not_shared_across_concurrent_requests() -> None:
    assert _ssl_context() is not _ssl_context()


async def test_alpaca_broker_snapshot_reads_account_positions_and_orders() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v2/account":
            return httpx.Response(
                200,
                json={
                    "id": "paper-account",
                    "status": "ACTIVE",
                    "currency": "USD",
                    "cash": "9000",
                    "buying_power": "18000",
                    "equity": "10000",
                    "portfolio_value": "10000",
                    "long_market_value": "2500",
                    "short_market_value": "0",
                    "trading_blocked": False,
                    "account_blocked": False,
                    "pattern_day_trader": False,
                },
            )
        if request.url.path == "/v2/positions":
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": "AAPL",
                        "asset_id": "asset-1",
                        "asset_class": "us_equity",
                        "side": "long",
                        "qty": "10",
                        "market_value": "2500",
                        "cost_basis": "2000",
                        "avg_entry_price": "200",
                        "current_price": "250",
                        "unrealized_pl": "500",
                        "unrealized_plpc": "0.25",
                    }
                ],
            )
        if request.url.path == "/v2/orders":
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    config = AlpacaTradingConfig(api_key="key", secret_key="secret")

    snapshot = await broker_snapshot(config=config, transport=httpx.MockTransport(handler))

    assert snapshot["connected"] is True
    assert snapshot["mode"] == "paper"
    assert snapshot["gross_exposure_pct"] == EXPECTED_GROSS_EXPOSURE
    account = snapshot["account"]
    assert isinstance(account, dict)
    assert "account_id" not in account
    assert account["account_id_hash"]
    assert snapshot["positions"][0]["ticker"] == "AAPL"
    assert len(requests) == EXPECTED_REQUEST_COUNT
    assert requests[0].headers["APCA-API-KEY-ID"] == "key"


async def test_alpaca_submit_order_posts_market_payload() -> None:
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_payload
        seen_payload = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "id": "order-1",
                "client_order_id": seen_payload["client_order_id"],
                "symbol": "AAPL",
                "side": "buy",
                "type": "market",
                "time_in_force": "day",
                "status": "accepted",
                "notional": "1000",
                "submitted_at": "2026-05-10T09:30:00Z",
            },
        )

    config = AlpacaTradingConfig(api_key="key", secret_key="secret")
    client = AlpacaBrokerClient(config, transport=httpx.MockTransport(handler))
    payload = build_market_order_payload(
        cycle_id="cycle-1",
        ticker="AAPL",
        side="BUY",
        quantity=None,
        notional=1000.0,
    )

    order = await client.submit_order(payload)

    assert seen_payload["symbol"] == "AAPL"
    assert seen_payload["side"] == "buy"
    assert order["order_id"] == "order-1"
    assert order["status"] == "ACCEPTED"


async def test_alpaca_order_by_client_order_id_reconciles_submitted_order() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["client_order_id"] == "client-1"
        return httpx.Response(
            200,
            json={
                "id": "order-1",
                "client_order_id": "client-1",
                "symbol": "AAPL",
                "side": "buy",
                "type": "market",
                "time_in_force": "day",
                "status": "filled",
                "filled_qty": "3",
                "filled_avg_price": "177.25",
                "submitted_at": "2026-05-10T09:30:00Z",
                "filled_at": "2026-05-10T09:30:02Z",
            },
        )

    config = AlpacaTradingConfig(api_key="key", secret_key="secret")
    client = AlpacaBrokerClient(config, transport=httpx.MockTransport(handler))

    order = await client.order_by_client_order_id("client-1")

    assert requests[0].method == "GET"
    assert requests[0].url.path == "/v2/orders:by_client_order_id"
    assert order["client_order_id"] == "client-1"
    assert order["status"] == "FILLED"
    assert order["filled_qty"] == 3.0


async def test_alpaca_order_clock_and_cancel_helpers() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/v2/clock":
            return httpx.Response(
                200,
                json={
                    "timestamp": "2026-05-10T09:30:00Z",
                    "is_open": False,
                    "next_open": "2026-05-11T13:30:00Z",
                    "next_close": "2026-05-11T20:00:00Z",
                },
            )
        if request.url.path == "/v2/orders/order-1":
            if request.method == "DELETE":
                return httpx.Response(204)
            return httpx.Response(
                200,
                json={
                    "id": "order-1",
                    "symbol": "AAPL",
                    "side": "buy",
                    "type": "market",
                    "time_in_force": "day",
                    "status": "accepted",
                    "submitted_at": "2026-05-10T09:30:00Z",
                },
            )
        return httpx.Response(404)

    config = AlpacaTradingConfig(api_key="key", secret_key="secret")
    client = AlpacaBrokerClient(config, transport=httpx.MockTransport(handler))

    clock = await client.clock()
    order = await client.order("order-1")
    cancellation = await client.cancel_order("order-1")

    assert clock["is_open"] is False
    assert order["status"] == "ACCEPTED"
    assert cancellation == {"order_id": "order-1", "status": "CANCEL_REQUESTED"}
    assert requests == [
        ("GET", "/v2/clock"),
        ("GET", "/v2/orders/order-1"),
        ("DELETE", "/v2/orders/order-1"),
    ]


async def test_alpaca_close_position_uses_position_close_endpoint() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "DELETE" and request.url.path == "/v2/positions/AAPL":
            return httpx.Response(
                200,
                json={
                    "id": "close-1",
                    "symbol": "AAPL",
                    "side": "sell",
                    "type": "market",
                    "time_in_force": "day",
                    "status": "accepted",
                    "qty": "0.01706939",
                    "submitted_at": "2026-05-10T09:30:00Z",
                },
            )
        return httpx.Response(404)

    config = AlpacaTradingConfig(api_key="key", secret_key="secret")
    client = AlpacaBrokerClient(config, transport=httpx.MockTransport(handler))

    order = await client.close_position("aapl")

    assert order["ticker"] == "AAPL"
    assert order["side"] == "SELL"
    assert order["qty"] == EXPECTED_CLOSE_POSITION_QTY
    assert requests == [("DELETE", "/v2/positions/AAPL")]


def test_alpaca_config_blocks_live_trading_by_default() -> None:
    with pytest.raises(AlpacaBrokerError, match="live Alpaca trading"):
        AlpacaTradingConfig(
            api_key="key",
            secret_key="secret",
            base_url="https://api.alpaca.markets",
        )


def test_alpaca_require_paper_blocks_live_even_when_live_is_allowed() -> None:
    config = AlpacaTradingConfig(
        api_key="key",
        secret_key="secret",
        base_url="https://api.alpaca.markets",
        allow_live_trading=True,
    )
    config.validate_safety()

    with pytest.raises(AlpacaBrokerError, match="requires the Alpaca paper endpoint"):
        config.require_paper(purpose="test submit")


@pytest.mark.parametrize(
    "base_url",
    [
        "https://paper-api.alpaca.markets.evil.test",
        "https://api.alpaca.markets/paper-api.alpaca.markets",
        "http://paper-api.alpaca.markets",
    ],
)
def test_alpaca_require_paper_rejects_lookalike_urls(base_url: str) -> None:
    config = AlpacaTradingConfig(
        api_key="key",
        secret_key="secret",
        base_url=base_url,
        allow_live_trading=True,
    )

    with pytest.raises(AlpacaBrokerError, match="requires the Alpaca paper endpoint"):
        config.require_paper(purpose="test submit")


def test_market_order_payload_requires_exactly_one_positive_size() -> None:
    with pytest.raises(AlpacaBrokerError, match="exactly one"):
        build_market_order_payload(
            cycle_id="cycle-1",
            ticker="AAPL",
            side="BUY",
            quantity=1.0,
            notional=100.0,
        )

    with pytest.raises(AlpacaBrokerError, match="positive and finite"):
        build_market_order_payload(
            cycle_id="cycle-1",
            ticker="AAPL",
            side="BUY",
            quantity=0.0,
            notional=None,
        )

    payload = build_market_order_payload(
        cycle_id="cycle-1",
        ticker="AAPL",
        side="BUY",
        quantity=0.25,
        notional=None,
    )

    assert payload["qty"] == 0.25
