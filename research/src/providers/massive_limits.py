from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

DEFAULT_DAILY_REQUEST_BUDGET: int | None = None
DEFAULT_MAX_REQUESTS_PER_MINUTE = 0
DEFAULT_USAGE_DIR = Path("research/results/massive-api-usage")
RECENT_EVENT_LIMIT = 50
SECONDS_PER_MINUTE = 60.0
SleepFn = Callable[[float], Awaitable[None]]


class MassiveApiQuotaExceededError(RuntimeError):
    """Raised before a Massive request would exceed the local daily budget."""


@dataclass(frozen=True)
class MassiveApiLimitConfig:
    enabled: bool = True
    daily_request_budget: int | None = DEFAULT_DAILY_REQUEST_BUDGET
    max_requests_per_minute: int = DEFAULT_MAX_REQUESTS_PER_MINUTE
    usage_dir: Path = DEFAULT_USAGE_DIR

    @classmethod
    def from_env(cls, *, disabled: bool = False) -> Self:
        return cls(
            enabled=(not disabled) and _env_bool("MASSIVE_API_LIMITS_ENABLED", default=False),
            daily_request_budget=_env_optional_int(
                "MASSIVE_API_DAILY_REQUEST_BUDGET",
                default=DEFAULT_DAILY_REQUEST_BUDGET,
            ),
            max_requests_per_minute=_env_int(
                "MASSIVE_API_MAX_REQUESTS_PER_MINUTE",
                default=DEFAULT_MAX_REQUESTS_PER_MINUTE,
            ),
            usage_dir=Path(os.environ.get("MASSIVE_API_USAGE_DIR", DEFAULT_USAGE_DIR.as_posix())),
        )


class MassiveApiLimiter:
    def __init__(
        self,
        config: MassiveApiLimitConfig | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        self.config = config or MassiveApiLimitConfig.from_env()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleep = sleep
        self._lock = asyncio.Lock()
        _validate_config(self.config)

    @classmethod
    def from_env(cls, *, disabled: bool = False) -> Self:
        return cls(MassiveApiLimitConfig.from_env(disabled=disabled))

    async def acquire(self, *, endpoint: str, ticker: str) -> None:
        if not self.config.enabled:
            return
        async with self._lock:
            now = _as_utc(self._clock())
            payload = _read_usage(_usage_path(self.config, now))
            delay = _pace_delay_seconds(payload, now, self.config.max_requests_per_minute)
            if delay > 0.0:
                await self._sleep(delay)
                now = _as_utc(self._clock())
                payload = _read_usage(_usage_path(self.config, now))
            _reserve_request(self.config, now, payload, endpoint=endpoint, ticker=ticker)


def current_usage(
    config: MassiveApiLimitConfig | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    resolved = config or MassiveApiLimitConfig.from_env()
    timestamp = _as_utc(now or datetime.now(UTC))
    payload = _read_usage(_usage_path(resolved, timestamp))
    made = _request_count(payload)
    budget = resolved.daily_request_budget
    return {
        "enabled": resolved.enabled,
        "date": timestamp.date().isoformat(),
        "daily_request_budget": budget,
        "daily_request_budget_label": "unlimited" if budget is None else str(budget),
        "requests_made": made,
        "requests_remaining": None if budget is None else max(budget - made, 0),
        "requests_remaining_label": "unlimited" if budget is None else str(max(budget - made, 0)),
        "max_requests_per_minute": resolved.max_requests_per_minute,
        "max_requests_per_minute_label": (
            "unpaced"
            if resolved.max_requests_per_minute == 0
            else str(resolved.max_requests_per_minute)
        ),
        "usage_path": _usage_path(resolved, timestamp).as_posix(),
        "recent_events": _events(payload),
    }


def _reserve_request(
    config: MassiveApiLimitConfig,
    now: datetime,
    payload: Mapping[str, Any],
    *,
    endpoint: str,
    ticker: str,
) -> None:
    made = _request_count(payload)
    if config.daily_request_budget is not None and made >= config.daily_request_budget:
        raise MassiveApiQuotaExceededError(
            "Massive local daily request budget exhausted: "
            f"{made}/{config.daily_request_budget} used for {now.date().isoformat()}. "
            "Set MASSIVE_API_DAILY_REQUEST_BUDGET=0 to remove the local daily cap."
        )
    events = [
        *_events(payload),
        {
            "timestamp": now.isoformat(),
            "endpoint": endpoint,
            "ticker": ticker.upper(),
        },
    ][-RECENT_EVENT_LIMIT:]
    output = {
        "date": now.date().isoformat(),
        "requests_made": made + 1,
        "daily_request_budget": config.daily_request_budget,
        "daily_request_budget_label": (
            "unlimited" if config.daily_request_budget is None else str(config.daily_request_budget)
        ),
        "max_requests_per_minute": config.max_requests_per_minute,
        "max_requests_per_minute_label": (
            "unpaced"
            if config.max_requests_per_minute == 0
            else str(config.max_requests_per_minute)
        ),
        "recent_events": events,
    }
    _write_usage(_usage_path(config, now), output)


def _pace_delay_seconds(
    payload: Mapping[str, Any],
    now: datetime,
    max_requests_per_minute: int,
) -> float:
    events = _events(payload)
    if max_requests_per_minute == 0:
        return 0.0
    if not events:
        return 0.0
    last = _parse_time(events[-1].get("timestamp"))
    if last is None:
        return 0.0
    min_interval = SECONDS_PER_MINUTE / max_requests_per_minute
    return max(min_interval - (now - last).total_seconds(), 0.0)


def _usage_path(config: MassiveApiLimitConfig, now: datetime) -> Path:
    return config.usage_dir / f"{now.date().isoformat()}.json"


def _read_usage(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _write_usage(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _request_count(payload: Mapping[str, Any]) -> int:
    value = payload.get("requests_made", 0)
    return value if isinstance(value, int) and value >= 0 else 0


def _events(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    value = payload.get("recent_events", [])
    if not isinstance(value, list):
        return []
    return [
        {str(key): str(item_value) for key, item_value in item.items()}
        for item in value
        if isinstance(item, Mapping)
    ]


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return _as_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_config(config: MassiveApiLimitConfig) -> None:
    if config.daily_request_budget is not None and config.daily_request_budget < 1:
        raise ValueError("daily_request_budget must be >= 1 or None for unlimited")
    if config.max_requests_per_minute < 0:
        raise ValueError("max_requests_per_minute must be >= 0")


def _env_int(name: str, *, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return default if value == "" else int(value)


def _env_optional_int(name: str, *, default: int | None) -> int | None:
    value = os.environ.get(name, "").strip().lower()
    if value == "":
        return default
    if value in {"0", "none", "unlimited", "off"}:
        return None
    return int(value)


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if value == "":
        return default
    return value in {"1", "true", "yes", "on"}
