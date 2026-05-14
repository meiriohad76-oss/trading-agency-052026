from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
import pytest
from market_flow.massive import MassiveTradesConfig, pull_massive_trades
from market_flow.storage import DateRange as TradeDateRange
from prices.massive_daily import MassiveDailyConfig, build_massive_downloader
from prices.storage import DateRange as PriceDateRange
from providers.massive_limits import (
    MassiveApiLimitConfig,
    MassiveApiLimiter,
    MassiveApiQuotaExceededError,
    current_usage,
)

NOW = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)  # Monday — avoids weekend trading-day skip
DAILY_BUDGET = 2
MAX_REQUESTS_PER_MINUTE = 60
EXPECTED_RECORDED_REQUESTS = 2
EXPECTED_SINGLE_REQUEST = 1


async def test_massive_limiter_records_and_blocks_daily_budget(tmp_path: Path) -> None:
    limiter = _limiter(tmp_path)

    await limiter.acquire(endpoint="daily_aggs", ticker="AAPL")
    await limiter.acquire(endpoint="stock_trades", ticker="MSFT")

    usage = current_usage(_config(tmp_path), now=NOW)
    assert usage["requests_made"] == EXPECTED_RECORDED_REQUESTS
    assert usage["requests_remaining"] == 0
    with pytest.raises(MassiveApiQuotaExceededError):
        await limiter.acquire(endpoint="daily_aggs", ticker="NVDA")


async def test_massive_daily_downloader_uses_explicit_limiter(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "t": _ms("2026-05-08T04:00:00Z"),
                        "o": 1,
                        "h": 2,
                        "l": 1,
                        "c": 2,
                        "v": 3,
                    }
                ]
            },
        )

    downloader = build_massive_downloader(
        MassiveDailyConfig(api_key="key"),
        transport=httpx.MockTransport(handler),
        limiter=_limiter(tmp_path),
    )

    await downloader("AAPL", PriceDateRange(NOW.date(), NOW.date()))

    assert len(requests) == EXPECTED_SINGLE_REQUEST
    assert current_usage(_config(tmp_path), now=NOW)["requests_made"] == EXPECTED_SINGLE_REQUEST


async def test_massive_stock_trades_uses_explicit_limiter(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"results": [_raw_trade("1", "2026-05-10T13:31:00Z")]},
        )

    await pull_massive_trades(
        tickers=("AAPL",),
        requested=TradeDateRange(NOW.date(), NOW.date()),
        trade_root=tmp_path / "stock_trades",
        manifest_path=tmp_path / "stock_trades.json",
        config=MassiveTradesConfig(api_key="key"),
        transport=httpx.MockTransport(handler),
        clock=lambda: NOW,
        limiter=_limiter(tmp_path),
    )

    assert len(requests) == EXPECTED_SINGLE_REQUEST
    assert current_usage(_config(tmp_path), now=NOW)["requests_made"] == EXPECTED_SINGLE_REQUEST


def test_current_usage_tolerates_missing_or_corrupt_ledger(tmp_path: Path) -> None:
    path = tmp_path / f"{NOW.date().isoformat()}.json"
    path.write_text("{not-json", encoding="utf-8")

    usage = current_usage(_config(tmp_path), now=NOW)

    assert usage["requests_made"] == 0
    assert usage["requests_remaining"] == DAILY_BUDGET


def test_massive_limiter_from_env_defaults_to_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MASSIVE_API_LIMITS_ENABLED", raising=False)
    monkeypatch.delenv("MASSIVE_API_MAX_REQUESTS_PER_MINUTE", raising=False)

    config = MassiveApiLimitConfig.from_env()

    assert config.enabled is False
    assert config.daily_request_budget is None
    assert config.max_requests_per_minute == 0


async def test_massive_limiter_zero_minute_pacing_means_unpaced(tmp_path: Path) -> None:
    config = MassiveApiLimitConfig(
        daily_request_budget=None,
        max_requests_per_minute=0,
        usage_dir=tmp_path,
    )
    slept: list[float] = []

    async def no_sleep(seconds: float) -> None:
        slept.append(seconds)

    limiter = MassiveApiLimiter(config, clock=_clock(), sleep=no_sleep)

    await limiter.acquire(endpoint="stock_trades", ticker="AAPL")
    await limiter.acquire(endpoint="stock_trades", ticker="MSFT")

    usage = current_usage(config, now=NOW)
    assert slept == []
    assert usage["max_requests_per_minute_label"] == "unpaced"
    assert usage["requests_made"] == EXPECTED_RECORDED_REQUESTS


async def test_massive_limiter_default_daily_budget_is_unlimited(tmp_path: Path) -> None:
    config = MassiveApiLimitConfig(
        usage_dir=tmp_path,
        max_requests_per_minute=MAX_REQUESTS_PER_MINUTE,
    )
    clock = _clock()

    async def no_sleep(seconds: float) -> None:
        del seconds

    limiter = MassiveApiLimiter(config, clock=clock, sleep=no_sleep)

    for index in range(DAILY_BUDGET + 1):
        await limiter.acquire(endpoint="stock_trades", ticker=f"T{index}")

    usage = current_usage(config, now=NOW)
    assert usage["daily_request_budget"] is None
    assert usage["requests_made"] == DAILY_BUDGET + 1
    assert usage["requests_remaining"] is None
    assert usage["requests_remaining_label"] == "unlimited"


def _config(tmp_path: Path) -> MassiveApiLimitConfig:
    return MassiveApiLimitConfig(
        daily_request_budget=DAILY_BUDGET,
        max_requests_per_minute=MAX_REQUESTS_PER_MINUTE,
        usage_dir=tmp_path,
    )


def _limiter(tmp_path: Path) -> MassiveApiLimiter:
    clock = _clock()

    async def no_sleep(seconds: float) -> None:
        del seconds

    return MassiveApiLimiter(_config(tmp_path), clock=clock, sleep=no_sleep)


def _clock() -> Callable[[], datetime]:
    state = {"now": NOW}

    def tick() -> datetime:
        state["now"] += timedelta(seconds=1)
        return state["now"]

    return tick


def _raw_trade(trade_id: str, timestamp: str) -> dict[str, object]:
    return {
        "p": 100.0,
        "s": 100,
        "y": _ns(timestamp),
        "x": 4,
        "c": ["@"],
        "i": trade_id,
        "q": int(trade_id, 36),
        "z": 3,
        "e": 0,
    }


def _ms(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1_000)


def _ns(value: str) -> int:
    return int(pd.Timestamp(value).timestamp() * 1_000_000_000)
