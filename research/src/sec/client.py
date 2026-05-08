from __future__ import annotations

import asyncio
import json
import ssl
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import Any, cast

import httpx

DATA_SEC_BASE = "https://data.sec.gov"
WWW_SEC_BASE = "https://www.sec.gov"
DEFAULT_REQUESTS_PER_SECOND = 8.0
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 0.5

type Sleeper = Callable[[float], Awaitable[None]]


class AsyncRateLimiter:
    def __init__(
        self,
        *,
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        clock: Callable[[], float] | None = None,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._interval = 1.0 / requests_per_second
        self._clock = time.monotonic if clock is None else clock
        self._sleeper = sleeper
        self._next_request_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = self._clock()
            delay = self._next_request_at - now
            if delay > 0:
                await self._sleeper(delay)
                now = self._clock()
            self._next_request_at = max(now, self._next_request_at) + self._interval


@dataclass(frozen=True)
class SecClientConfig:
    user_agent: str
    requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND


class SecClient:
    def __init__(
        self,
        config: SecClientConfig,
        *,
        client: httpx.AsyncClient | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        if config.user_agent.strip() == "":
            raise ValueError("SEC_USER_AGENT must identify the app and contact email")
        self._client = client or httpx.AsyncClient(timeout=30.0, verify=_verify_context())
        self._client.headers["User-Agent"] = config.user_agent
        self._client.headers["Accept-Encoding"] = "gzip, deflate"
        self._owns_client = client is None
        self._rate_limiter = rate_limiter or AsyncRateLimiter(
            requests_per_second=config.requests_per_second,
            sleeper=sleeper,
        )
        self._sleeper = sleeper

    async def __aenter__(self) -> SecClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_json(self, url: str) -> Mapping[str, Any]:
        response = await self._get(url)
        return cast(Mapping[str, Any], response.json())

    async def get_text(self, url: str) -> str:
        response = await self._get(url)
        return response.text

    async def company_tickers(self) -> Mapping[str, Any]:
        return await self.get_json(f"{WWW_SEC_BASE}/files/company_tickers.json")

    async def company_facts(self, cik: str) -> Mapping[str, Any]:
        return await self.get_json(f"{DATA_SEC_BASE}/api/xbrl/companyfacts/CIK{cik}.json")

    async def submissions(self, cik: str) -> Mapping[str, Any]:
        return await self.get_json(f"{DATA_SEC_BASE}/submissions/CIK{cik}.json")

    async def filing_index(self, cik: str, accession_number: str) -> Mapping[str, Any]:
        url = archive_url(cik, accession_number, "index.json")
        return await self.get_json(url)

    async def _get(self, url: str) -> httpx.Response:
        for attempt in range(MAX_ATTEMPTS):
            await self._rate_limiter.wait()
            response = await self._client.get(url)
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS and attempt < MAX_ATTEMPTS - 1:
                await self._sleeper(RETRY_BACKOFF_SECONDS * (2**attempt))
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("unreachable retry loop")


def archive_url(cik: str, accession_number: str, document: str) -> str:
    clean_cik = str(int(cik))
    clean_accession = accession_number.replace("-", "")
    return f"{WWW_SEC_BASE}/Archives/edgar/data/{clean_cik}/{clean_accession}/{document}"


def json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _verify_context() -> ssl.SSLContext | bool:
    if sys.platform != "win32":
        return True
    try:
        truststore = import_module("truststore")
    except ModuleNotFoundError:
        return True
    context_factory = cast(type[ssl.SSLContext], truststore.SSLContext)
    return context_factory(ssl.PROTOCOL_TLS_CLIENT)
