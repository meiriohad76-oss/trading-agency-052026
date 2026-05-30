from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"


class FmpProviderError(RuntimeError):
    """Raised when FMP cannot return a fundamentals payload."""


@dataclass(frozen=True)
class FmpEarningsSurprise:
    date: str
    ticker: str
    actual_eps: float | None
    estimated_eps: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FmpAnalystEstimate:
    date: str
    ticker: str
    estimated_revenue_avg: float | None
    estimated_eps_avg: float | None
    number_analysts_estimated_revenue: int | None
    number_analysts_estimated_eps: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FmpClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = FMP_BASE_URL,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._http_client = http_client or httpx.Client(timeout=20.0)

    def earnings_surprises(self, ticker: str, *, limit: int = 4) -> list[FmpEarningsSurprise]:
        normalized = ticker.upper().strip()
        rows = self._get_rows(f"earnings-surprises/{normalized}", limit=limit)
        return [
            FmpEarningsSurprise(
                date=str(row.get("date") or ""),
                ticker=str(row.get("symbol") or normalized).upper(),
                actual_eps=_num(row.get("actualEarningResult")),
                estimated_eps=_num(row.get("estimatedEarning")),
            )
            for row in rows
        ]

    def analyst_estimates(self, ticker: str, *, limit: int = 4) -> list[FmpAnalystEstimate]:
        normalized = ticker.upper().strip()
        rows = self._get_rows(f"analyst-estimates/{normalized}", limit=limit)
        return [
            FmpAnalystEstimate(
                date=str(row.get("date") or ""),
                ticker=str(row.get("symbol") or normalized).upper(),
                estimated_revenue_avg=_num(row.get("estimatedRevenueAvg")),
                estimated_eps_avg=_num(row.get("estimatedEpsAvg")),
                number_analysts_estimated_revenue=_int(row.get("numberAnalystEstimatedRevenue")),
                number_analysts_estimated_eps=_int(row.get("numberAnalystEstimatedEps")),
            )
            for row in rows
        ]

    def _get_rows(self, path: str, *, limit: int) -> list[dict[str, object]]:
        try:
            response = self._http_client.get(
                f"{self._base_url}/{path}",
                params={"apikey": self._api_key, "limit": limit},
            )
        except httpx.HTTPError as exc:
            raise FmpProviderError(f"FMP request failed: {exc}") from exc
        if response.status_code == 404:
            return []
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FmpProviderError(f"FMP returned HTTP {response.status_code}") from exc
        payload = response.json()
        if not isinstance(payload, list):
            raise FmpProviderError("FMP response was not a list")
        return [row for row in payload if isinstance(row, dict)]


def compute_beat_rate(surprises: list[FmpEarningsSurprise]) -> float | None:
    comparable = [
        surprise
        for surprise in surprises
        if surprise.actual_eps is not None and surprise.estimated_eps is not None
    ]
    if not comparable:
        return None
    beats = sum(1 for surprise in comparable if surprise.actual_eps > surprise.estimated_eps)
    return beats / len(comparable)


def build_fmp_state(
    ticker: str,
    client: FmpClient,
    *,
    fetched_at: str | None = None,
) -> dict[str, object]:
    normalized = ticker.upper().strip()
    surprises = client.earnings_surprises(normalized)
    estimates = client.analyst_estimates(normalized)
    latest_estimate = estimates[0] if estimates else None
    return {
        "ticker": normalized,
        "provider": "fmp",
        "status": "ready",
        "fetched_at": fetched_at or datetime.now(UTC).isoformat(),
        "earnings_surprises": [surprise.to_dict() for surprise in surprises],
        "analyst_estimates": [estimate.to_dict() for estimate in estimates],
        "eps_beat_rate": compute_beat_rate(surprises),
        "forward_eps": latest_estimate.estimated_eps_avg if latest_estimate else None,
        "analyst_count": latest_estimate.number_analysts_estimated_eps if latest_estimate else None,
    }


def not_configured_state(ticker: str, *, fetched_at: str | None = None) -> dict[str, object]:
    return {
        "ticker": ticker.upper().strip(),
        "provider": "fmp",
        "status": "not_configured",
        "fetched_at": fetched_at or datetime.now(UTC).isoformat(),
        "detail": "FMP_API_KEY is not configured.",
        "earnings_surprises": [],
        "analyst_estimates": [],
        "eps_beat_rate": None,
        "forward_eps": None,
        "analyst_count": None,
    }


def provider_error_state(
    ticker: str,
    detail: str,
    *,
    fetched_at: str | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker.upper().strip(),
        "provider": "fmp",
        "status": "provider_error",
        "fetched_at": fetched_at or datetime.now(UTC).isoformat(),
        "detail": detail,
        "earnings_surprises": [],
        "analyst_estimates": [],
        "eps_beat_rate": None,
        "forward_eps": None,
        "analyst_count": None,
    }


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
