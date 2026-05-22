from __future__ import annotations

import asyncio
import hashlib
import math
import os
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self, cast
from urllib.parse import urlparse

import httpx
import truststore
from dotenv import load_dotenv

DEFAULT_TRADING_BASE_URL = "https://paper-api.alpaca.markets"
LIVE_TRADING_BASE_URL = "https://api.alpaca.markets"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_ORDER_LIMIT = 50
CLIENT_ORDER_ID_LENGTH = 48
PAPER_HOST_TOKEN = "paper-api.alpaca.markets"


class AlpacaBrokerError(RuntimeError):
    """Raised when Alpaca broker configuration or API calls fail."""


@dataclass(frozen=True, slots=True)
class AlpacaTradingConfig:
    api_key: str
    secret_key: str
    base_url: str = DEFAULT_TRADING_BASE_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    allow_live_trading: bool = False

    def __post_init__(self) -> None:
        self.validate_safety()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Self:
        if env is None:
            load_dotenv()
        values = os.environ if env is None else env
        api_key = values.get("ALPACA_API_KEY", "").strip()
        secret_key = values.get("ALPACA_SECRET_KEY", "").strip()
        if not api_key or not secret_key:
            raise AlpacaBrokerError("ALPACA_API_KEY and ALPACA_SECRET_KEY must be set")
        return cls(
            api_key=api_key,
            secret_key=secret_key,
            base_url=values.get("ALPACA_TRADING_BASE_URL", DEFAULT_TRADING_BASE_URL).strip()
            or DEFAULT_TRADING_BASE_URL,
            timeout_seconds=_env_float(
                values.get("ALPACA_TRADING_TIMEOUT_SECONDS"),
                default=DEFAULT_TIMEOUT_SECONDS,
            ),
            allow_live_trading=_env_bool(values.get("ALPACA_ALLOW_LIVE_TRADING")),
        )

    @property
    def is_paper(self) -> bool:
        parsed = urlparse(self.base_url.strip())
        return parsed.scheme.lower() == "https" and parsed.hostname == PAPER_HOST_TOKEN

    @property
    def mode(self) -> str:
        return "paper" if self.is_paper else "live"

    def validate_safety(self) -> None:
        if self.is_paper:
            return
        if not self.allow_live_trading:
            raise AlpacaBrokerError(
                "live Alpaca trading base URL is blocked unless "
                "ALPACA_ALLOW_LIVE_TRADING=true"
            )

    def require_paper(self, *, purpose: str = "paper broker operation") -> None:
        if not self.is_paper:
            raise AlpacaBrokerError(f"{purpose} requires the Alpaca paper endpoint")


class AlpacaBrokerClient:
    def __init__(
        self,
        config: AlpacaTradingConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport

    async def account(self) -> dict[str, object]:
        payload = await self._request("GET", "/v2/account")
        if not isinstance(payload, Mapping):
            raise AlpacaBrokerError("Alpaca account response must be an object")
        return normalize_account(cast(Mapping[str, object], payload))

    async def positions(self) -> list[dict[str, object]]:
        payload = await self._request("GET", "/v2/positions")
        if not isinstance(payload, list):
            raise AlpacaBrokerError("Alpaca positions response must be a list")
        return [
            normalize_position(cast(Mapping[str, object], item))
            for item in payload
            if isinstance(item, Mapping)
        ]

    async def orders(
        self,
        *,
        status: str = "open",
        limit: int = DEFAULT_ORDER_LIMIT,
    ) -> list[dict[str, object]]:
        payload = await self._request(
            "GET",
            "/v2/orders",
            params={"status": status, "limit": str(limit), "direction": "desc"},
        )
        if not isinstance(payload, list):
            raise AlpacaBrokerError("Alpaca orders response must be a list")
        return [
            normalize_order(cast(Mapping[str, object], item))
            for item in payload
            if isinstance(item, Mapping)
        ]

    async def order(self, order_id: str) -> dict[str, object]:
        payload = await self._request("GET", f"/v2/orders/{order_id}")
        if not isinstance(payload, Mapping):
            raise AlpacaBrokerError("Alpaca order response must be an object")
        return normalize_order(payload)

    async def order_by_client_order_id(self, client_order_id: str) -> dict[str, object]:
        cleaned = client_order_id.strip()
        if not cleaned:
            raise AlpacaBrokerError("client_order_id is required for order reconciliation")
        payload = await self._request(
            "GET",
            "/v2/orders:by_client_order_id",
            params={"client_order_id": cleaned},
        )
        if not isinstance(payload, Mapping):
            raise AlpacaBrokerError("Alpaca order reconciliation response must be an object")
        return normalize_order(payload)

    async def clock(self) -> dict[str, object]:
        payload = await self._request("GET", "/v2/clock")
        if not isinstance(payload, Mapping):
            raise AlpacaBrokerError("Alpaca clock response must be an object")
        return normalize_clock(payload)

    async def submit_order(self, payload: Mapping[str, object]) -> dict[str, object]:
        response = await self._request("POST", "/v2/orders", json_payload=dict(payload))
        if not isinstance(response, Mapping):
            raise AlpacaBrokerError("Alpaca order response must be an object")
        return normalize_order(response)

    async def cancel_order(self, order_id: str) -> dict[str, object]:
        await self._request("DELETE", f"/v2/orders/{order_id}", expect_json=False)
        return {"order_id": order_id, "status": "CANCEL_REQUESTED"}

    async def close_position(self, ticker: str) -> dict[str, object]:
        payload = await self._request("DELETE", f"/v2/positions/{ticker.upper()}")
        if not isinstance(payload, Mapping):
            raise AlpacaBrokerError("Alpaca close-position response must be an object")
        return normalize_order(payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json_payload: Mapping[str, object] | None = None,
        expect_json: bool = True,
    ) -> object:
        url = f"{self._config.base_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(
            timeout=self._config.timeout_seconds,
            transport=self._transport,
            verify=_ssl_context(),
        ) as client:
            try:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_payload,
                    headers=_headers(self._config),
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise AlpacaBrokerError(_http_error_message(exc.response)) from exc
            except httpx.HTTPError as exc:
                raise AlpacaBrokerError(f"Alpaca broker request failed: {exc}") from exc
        if not expect_json or response.status_code == httpx.codes.NO_CONTENT:
            return None
        return response.json()


async def broker_snapshot(
    *,
    config: AlpacaTradingConfig | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, object]:
    resolved = AlpacaTradingConfig.from_env() if config is None else config
    client = AlpacaBrokerClient(resolved, transport=transport)
    checked_at = datetime.now(UTC)
    account, positions, orders = await asyncio.gather(
        client.account(),
        client.positions(),
        client.orders(status="open"),
    )
    return {
        "provider": "alpaca",
        "mode": resolved.mode,
        "connected": True,
        "checked_at": checked_at.isoformat(),
        "account": account,
        "positions": positions,
        "orders": orders,
        "gross_exposure_pct": gross_exposure_pct(account, positions),
        "status_label": "Broker Connected",
        "status_class": "pass",
        "detail": "Alpaca paper broker account, positions, and open orders loaded.",
    }


def normalize_account(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "account_id_hash": _stable_hash(_text(payload.get("id"))),
        "status": _text(payload.get("status")),
        "currency": _text(payload.get("currency")),
        "cash": _number(payload.get("cash")),
        "buying_power": _number(payload.get("buying_power")),
        "equity": _number(payload.get("equity")),
        "portfolio_value": _number(payload.get("portfolio_value")),
        "long_market_value": _number(payload.get("long_market_value")),
        "short_market_value": _number(payload.get("short_market_value")),
        "trading_blocked": _bool(payload.get("trading_blocked")),
        "account_blocked": _bool(payload.get("account_blocked")),
        "pattern_day_trader": _bool(payload.get("pattern_day_trader")),
    }


def normalize_position(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "ticker": _text(payload.get("symbol")).upper(),
        "asset_id": _text(payload.get("asset_id")),
        "asset_class": _text(payload.get("asset_class")),
        "side": _text(payload.get("side")).upper(),
        "qty": _number(payload.get("qty")),
        "market_value": _number(payload.get("market_value")),
        "cost_basis": _number(payload.get("cost_basis")),
        "avg_entry_price": _number(payload.get("avg_entry_price")),
        "current_price": _number(payload.get("current_price")),
        "unrealized_pl": _number(payload.get("unrealized_pl")),
        "unrealized_plpc": _number(payload.get("unrealized_plpc")),
    }


def normalize_order(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "order_id": _text(payload.get("id")),
        "client_order_id": _text(payload.get("client_order_id")),
        "ticker": _text(payload.get("symbol")).upper(),
        "side": _text(payload.get("side")).upper(),
        "type": _text(payload.get("type")).upper(),
        "time_in_force": _text(payload.get("time_in_force")).upper(),
        "status": _text(payload.get("status")).upper(),
        "qty": _optional_number(payload.get("qty")),
        "notional": _optional_number(payload.get("notional")),
        "limit_price": _optional_number(payload.get("limit_price")),
        "stop_price": _optional_number(payload.get("stop_price")),
        "submitted_at": _text(payload.get("submitted_at")),
        "filled_at": _text(payload.get("filled_at")),
        "filled_qty": _optional_number(payload.get("filled_qty")),
        "filled_avg_price": _optional_number(payload.get("filled_avg_price")),
    }


def normalize_clock(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "timestamp": _text(payload.get("timestamp")),
        "is_open": _bool(payload.get("is_open")),
        "next_open": _text(payload.get("next_open")),
        "next_close": _text(payload.get("next_close")),
    }


def build_market_order_payload(
    *,
    cycle_id: str,
    ticker: str,
    side: str,
    quantity: float | None,
    notional: float | None,
    time_in_force: str = "day",
    order_intent_hash: str | None = None,
) -> dict[str, object]:
    if (quantity is None) == (notional is None):
        raise AlpacaBrokerError("paper order requires exactly one quantity or notional")
    payload: dict[str, object] = {
        "symbol": ticker.upper(),
        "side": _alpaca_order_side(side),
        "type": "market",
        "time_in_force": time_in_force.lower(),
        "client_order_id": _client_order_id(
            cycle_id=cycle_id,
            ticker=ticker,
            side=side,
            order_intent_hash=order_intent_hash,
        ),
    }
    if quantity is not None:
        payload["qty"] = round(_positive_finite_number(quantity, "quantity"), 6)
    else:
        payload["notional"] = round(_positive_finite_number(cast(float, notional), "notional"), 2)
    return payload


def _alpaca_order_side(side: str) -> str:
    normalized = side.upper()
    if normalized in {"BUY", "COVER"}:
        return "buy"
    if normalized in {"SELL", "SHORT"}:
        return "sell"
    raise AlpacaBrokerError(f"unsupported order side: {side}")


def _positive_finite_number(value: float, label: str) -> float:
    if not math.isfinite(value) or value <= 0:
        raise AlpacaBrokerError(f"paper order {label} must be positive and finite")
    return value


def gross_exposure_pct(
    account: Mapping[str, object],
    positions: Sequence[Mapping[str, object]],
) -> float:
    equity = _number(account.get("equity"))
    if equity <= 0:
        return 0.0
    gross = sum(abs(_number(position.get("market_value"))) for position in positions)
    return round(gross / equity * 100.0, 6)


def _headers(config: AlpacaTradingConfig) -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": config.api_key,
        "APCA-API-SECRET-KEY": config.secret_key,
    }


def _ssl_context() -> ssl.SSLContext:
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _http_error_message(response: httpx.Response) -> str:
    try:
        detail = response.text[:300]
    except httpx.HTTPError:
        detail = ""
    return f"Alpaca broker request failed with HTTP {response.status_code}: {detail}"


def _client_order_id(
    *,
    cycle_id: str,
    ticker: str,
    side: str,
    order_intent_hash: str | None = None,
) -> str:
    intent = (order_intent_hash or "").strip()[:16]
    digest_input = f"{cycle_id}:{ticker}:{side}:{intent}"
    digest = hashlib.sha256(digest_input.encode()).hexdigest()[:16]
    raw = f"ta-{ticker.upper()}-{side.upper()}-{digest}"
    return raw[:CLIENT_ORDER_ID_LENGTH]


def _stable_hash(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _number(value: object) -> float:
    if value is None or value == "":
        return 0.0
    if not isinstance(value, int | float | str):
        raise AlpacaBrokerError("numeric Alpaca field must be a number or string")
    return float(value)


def _optional_number(value: object) -> float | None:
    if value is None or value == "":
        return None
    if not isinstance(value, int | float | str):
        raise AlpacaBrokerError("numeric Alpaca field must be a number or string")
    return float(value)


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_bool(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(value: str | None, *, default: float) -> float:
    if value is None or not value.strip():
        return default
    return float(value)
