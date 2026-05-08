from __future__ import annotations

import httpx
import pytest
from sec.client import AsyncRateLimiter, SecClient, SecClientConfig

REQUESTS_PER_SECOND = 8.0
EXPECTED_DELAY = 0.125
EXPECTED_RETRY_ATTEMPTS = 2


async def test_rate_limiter_spaces_burst_requests() -> None:
    clock = _FakeClock()
    sleeps: list[float] = []

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)
        clock.advance(delay)

    limiter = AsyncRateLimiter(
        requests_per_second=REQUESTS_PER_SECOND,
        clock=clock.time,
        sleeper=sleeper,
    )

    await limiter.wait()
    await limiter.wait()
    await limiter.wait()

    assert sleeps == pytest.approx([EXPECTED_DELAY, EXPECTED_DELAY])


async def test_sec_client_sets_required_user_agent_header() -> None:
    seen_user_agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_user_agents.append(request.headers["User-Agent"])
        return httpx.Response(200, json={"ok": True}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = SecClientConfig(user_agent="Trading Agency test@example.com")
    async with SecClient(config, client=client) as sec:
        payload = await sec.get_json("https://www.sec.gov/files/company_tickers.json")

    assert payload == {"ok": True}
    assert seen_user_agents == ["Trading Agency test@example.com"]


async def test_sec_client_retries_transient_transport_errors() -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ReadError("temporary read error", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    async def sleeper(delay: float) -> None:
        sleeps.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = SecClientConfig(user_agent="Trading Agency test@example.com")
    async with SecClient(config, client=client, sleeper=sleeper) as sec:
        payload = await sec.get_json("https://www.sec.gov/files/company_tickers.json")

    assert payload == {"ok": True}
    assert attempts["count"] == EXPECTED_RETRY_ATTEMPTS
    assert sleeps


def test_sec_client_rejects_blank_user_agent() -> None:
    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        SecClient(SecClientConfig(user_agent=""))


class _FakeClock:
    def __init__(self) -> None:
        self._value = 0.0

    def time(self) -> float:
        return self._value

    def advance(self, delay: float) -> None:
        self._value += delay
