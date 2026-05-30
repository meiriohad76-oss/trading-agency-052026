from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

DEFAULT_FRESHNESS_DAYS = 7
FORWARD_SOURCE_NAME = "forward-fundamentals"
FORWARD_SOURCE_LABEL = "Forward fundamentals"


class FileForwardFundamentalsLoader:
    def __init__(
        self,
        *,
        state_root: Path,
        now: datetime | None = None,
        max_age: timedelta = timedelta(days=DEFAULT_FRESHNESS_DAYS),
    ) -> None:
        self._state_root = state_root
        self._now = now
        self._max_age = max_age

    def forward_fundamentals(self, ticker: str, as_of: date) -> dict[str, object]:
        del as_of
        return read_forward_fundamentals_state(
            ticker,
            state_root=self._state_root,
            now=self._now,
            max_age=self._max_age,
        )


def read_forward_fundamentals_state(
    ticker: str,
    *,
    state_root: Path,
    now: datetime | None = None,
    max_age: timedelta = timedelta(days=DEFAULT_FRESHNESS_DAYS),
) -> dict[str, object]:
    normalized = ticker.upper().strip()
    current = _utc(now)
    yfinance = _provider_state(
        "yfinance",
        _read_json(state_root / "yfinance" / f"{normalized}.json"),
        now=current,
        max_age=max_age,
    )
    fmp = _provider_state(
        "fmp",
        _read_json(state_root / "fmp" / f"{normalized}.json"),
        now=current,
        max_age=max_age,
    )
    providers = [item for item in (yfinance, fmp) if item["exists"] is True]
    ready = [item for item in providers if item["usable"] is True]
    newest_as_of = _newest_timestamp(item.get("fetched_at") for item in providers)
    if ready:
        return _ready_state(normalized, ready, providers, newest_as_of)
    if any(item["status"] == "provider_error" for item in providers):
        status = "provider_error"
        detail = "Forward fundamentals provider error; refresh yfinance/FMP state before use."
    elif any(item["status"] == "expired" for item in providers):
        status = "expired"
        detail = "Forward fundamentals needs refresh; latest provider state is older than 7 days."
    elif any(item["status"] == "not_configured" for item in providers):
        status = "not_configured"
        detail = "Forward fundamentals not configured; optional FMP estimates are unavailable."
    else:
        status = "missing"
        detail = "No forward fundamentals state has been written for this ticker."
    return _empty_state(normalized, status=status, detail=detail, as_of=newest_as_of)


def forward_fundamentals_source_health(
    tickers: Iterable[str],
    *,
    state_root: Path,
    now: datetime | None = None,
    max_age: timedelta = timedelta(days=DEFAULT_FRESHNESS_DAYS),
) -> dict[str, object]:
    current = _utc(now)
    normalized = sorted({str(ticker).upper().strip() for ticker in tickers if str(ticker).strip()})
    states = [
        read_forward_fundamentals_state(
            ticker,
            state_root=state_root,
            now=current,
            max_age=max_age,
        )
        for ticker in normalized
    ]
    ready_count = sum(1 for state in states if state["forward_data_status"] == "ready")
    provider_errors = [state for state in states if state["forward_data_status"] == "provider_error"]
    expired = [state for state in states if state["forward_data_status"] == "expired"]
    not_configured = [
        state for state in states if state["forward_data_status"] == "not_configured"
    ]
    status = "HEALTHY" if normalized and ready_count == len(normalized) else "DEGRADED"
    freshness = "FRESH" if status == "HEALTHY" else "PARTIAL"
    if not normalized:
        detail = "Forward fundamentals has no active tickers to check."
    elif provider_errors:
        detail = "Forward fundamentals provider error; optional estimates are not fully usable."
    elif expired:
        detail = "Forward fundamentals needs refresh for one or more tickers."
    elif not_configured and ready_count == 0:
        detail = "Forward fundamentals not configured; optional estimates are unavailable."
    elif ready_count == 0:
        detail = "Forward fundamentals state is missing; SEC-backed fundamentals remain usable."
    else:
        detail = (
            f"Forward fundamentals ready for {ready_count}/{len(normalized)} tickers; "
            "missing or optional provider state is a review warning."
        )
    checked_at = current.isoformat()
    return {
        "schema_version": "0.1.0",
        "source": FORWARD_SOURCE_NAME,
        "source_tier": "SUPPORT",
        "status": status,
        "freshness": freshness,
        "checked_at": checked_at,
        "last_success_at": _latest_success(states) or checked_at,
        "observed_lag_seconds": 0,
        "error_count": len(provider_errors),
        "reliability_score": 1.0 if status == "HEALTHY" else 0.75,
        "rate_limit_reset_at": None,
        "critical": False,
        "ready_ticker_count": ready_count,
        "expected_ticker_count": len(normalized),
        "max_age_seconds": round(max_age.total_seconds()),
        "detail": detail,
        "notes": [
            f"ready {ready_count}/{len(normalized)}",
            "optional forward provider state does not block SEC fundamentals",
        ],
    }


def _ready_state(
    ticker: str,
    ready: list[dict[str, object]],
    providers: list[dict[str, object]],
    as_of: str | None,
) -> dict[str, object]:
    yfinance = _provider_by_name(ready, "yfinance")
    fmp = _provider_by_name(ready, "fmp")
    forward_pe = _first_number(yfinance, "forward_pe")
    forward_eps = _first_number(yfinance, "forward_eps") or _first_number(fmp, "forward_eps")
    analyst_count = _max_int(
        _first_value(yfinance, "analyst_count"),
        _first_value(fmp, "analyst_count"),
    )
    return {
        "ticker": ticker,
        "forward_pe": forward_pe,
        "forward_eps": forward_eps,
        "eps_beat_rate": _first_number(fmp, "eps_beat_rate"),
        "analyst_count": analyst_count,
        "forward_data_status": "ready",
        "forward_data_as_of": as_of,
        "forward_data_detail": _ready_detail(ready, providers),
        "providers": [str(item["name"]) for item in ready],
    }


def _empty_state(ticker: str, *, status: str, detail: str, as_of: str | None) -> dict[str, object]:
    return {
        "ticker": ticker,
        "forward_pe": None,
        "forward_eps": None,
        "eps_beat_rate": None,
        "analyst_count": None,
        "forward_data_status": status,
        "forward_data_as_of": as_of,
        "forward_data_detail": detail,
        "providers": [],
    }


def _provider_state(
    name: str,
    payload: dict[str, object],
    *,
    now: datetime,
    max_age: timedelta,
) -> dict[str, object]:
    if not payload:
        return {"name": name, "exists": False, "usable": False, "status": "missing"}
    fetched_at = _parse_datetime(payload.get("fetched_at"))
    raw_status = str(payload.get("status") or "ready").lower()
    if raw_status in {"not_configured", "provider_error"}:
        status = raw_status
    elif fetched_at is not None and now - fetched_at > max_age:
        status = "expired"
    else:
        status = "ready"
    return {
        "name": name,
        "exists": True,
        "usable": status == "ready",
        "status": status,
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "payload": payload,
    }


def _ready_detail(
    ready: list[dict[str, object]],
    providers: list[dict[str, object]],
) -> str:
    provider_names = ", ".join(str(item["name"]) for item in ready)
    warnings = [
        str(item["name"])
        for item in providers
        if item["usable"] is not True and item["status"] != "missing"
    ]
    if warnings:
        return (
            f"Forward fundamentals ready from {provider_names}; "
            f"{', '.join(warnings)} needs attention."
        )
    return f"Forward fundamentals ready from {provider_names}."


def _provider_by_name(
    providers: list[dict[str, object]],
    name: str,
) -> dict[str, object] | None:
    return next((item for item in providers if item["name"] == name), None)


def _first_number(provider: dict[str, object] | None, key: str) -> float | None:
    return _num(_first_value(provider, key))


def _first_value(provider: dict[str, object] | None, key: str) -> object:
    if provider is None:
        return None
    payload = provider.get("payload")
    if not isinstance(payload, dict):
        return None
    return payload.get(key)


def _max_int(*values: object) -> int | None:
    parsed = [_int(value) for value in values]
    valid = [value for value in parsed if value is not None]
    return max(valid) if valid else None


def _latest_success(states: list[dict[str, object]]) -> str | None:
    return _newest_timestamp(
        state.get("forward_data_as_of")
        for state in states
        if state.get("forward_data_status") == "ready"
    )


def _newest_timestamp(values: Iterable[object]) -> str | None:
    parsed = [_parse_datetime(value) for value in values]
    valid = [value for value in parsed if value is not None]
    if not valid:
        return None
    return max(valid).isoformat()


def _read_json(path: Path) -> dict[str, object]:
    try:
        import json

        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _utc(value: datetime | None) -> datetime:
    return _ensure_utc(value or datetime.now(UTC))


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _num(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
