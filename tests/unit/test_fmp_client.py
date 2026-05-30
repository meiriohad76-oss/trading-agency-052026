from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fundamentals.fmp_client import (
    FmpClient,
    FmpEarningsSurprise,
    FmpProviderError,
    build_fmp_state,
    compute_beat_rate,
)

from research.scripts.pull_fmp_earnings import pull_tickers


def test_earnings_surprises_returns_structured_objects() -> None:
    client = FmpClient(api_key="key", http_client=_client_for_path(
        "/api/v3/earnings-surprises/AAPL",
        [
            {
                "date": "2024-11-01",
                "symbol": "AAPL",
                "actualEarningResult": 1.64,
                "estimatedEarning": 1.60,
            }
        ],
    ))

    result = client.earnings_surprises("aapl")

    assert result == [
        FmpEarningsSurprise(
            date="2024-11-01",
            ticker="AAPL",
            actual_eps=1.64,
            estimated_eps=1.60,
        )
    ]


def test_analyst_estimates_returns_structured_objects() -> None:
    client = FmpClient(api_key="key", http_client=_client_for_path(
        "/api/v3/analyst-estimates/AAPL",
        [
            {
                "date": "2025-12-31",
                "symbol": "AAPL",
                "estimatedEpsAvg": 7.28,
                "estimatedRevenueAvg": 402_000_000_000,
                "numberAnalystEstimatedEps": 47,
                "numberAnalystEstimatedRevenue": 42,
            }
        ],
    ))

    result = client.analyst_estimates("AAPL")

    assert len(result) == 1
    assert result[0].ticker == "AAPL"
    assert result[0].estimated_eps_avg == pytest.approx(7.28)
    assert result[0].estimated_revenue_avg == pytest.approx(402_000_000_000)
    assert result[0].number_analysts_estimated_eps == 47
    assert result[0].number_analysts_estimated_revenue == 42


def test_returns_empty_list_on_404() -> None:
    client = FmpClient(
        api_key="key",
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(404, request=request))
        ),
    )

    assert client.earnings_surprises("AAPL") == []
    assert client.analyst_estimates("AAPL") == []


def test_beat_rate_computed_correctly() -> None:
    surprises = [
        FmpEarningsSurprise(date="2024-11-01", ticker="AAPL", actual_eps=1.64, estimated_eps=1.60),
        FmpEarningsSurprise(date="2024-08-01", ticker="AAPL", actual_eps=1.40, estimated_eps=1.45),
        FmpEarningsSurprise(date="2024-05-01", ticker="AAPL", actual_eps=1.53, estimated_eps=1.50),
        FmpEarningsSurprise(date="2024-02-01", ticker="AAPL", actual_eps=2.18, estimated_eps=2.10),
    ]

    assert compute_beat_rate(surprises) == pytest.approx(0.75)


def test_build_state_combines_beat_rate_and_estimate_counts() -> None:
    client = FmpClient(
        api_key="key",
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json=[
                        {
                            "date": "2024-11-01",
                            "symbol": "AAPL",
                            "actualEarningResult": 1.64,
                            "estimatedEarning": 1.60,
                            "estimatedEpsAvg": 7.28,
                            "numberAnalystEstimatedEps": 47,
                        }
                    ],
                    request=request,
                )
            )
        ),
    )

    state = build_fmp_state("AAPL", client, fetched_at="2026-05-30T12:00:00+00:00")

    assert state["status"] == "ready"
    assert state["eps_beat_rate"] == pytest.approx(1.0)
    assert state["analyst_count"] == 47
    assert state["forward_eps"] == pytest.approx(7.28)


def test_pull_tickers_writes_not_configured_state_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = pull_tickers(["AAPL"], output_dir=tmp_path, delay=0.0)

    payload = json.loads((tmp_path / "AAPL.json").read_text(encoding="utf-8"))
    assert result == {"ok": 0, "errors": 0, "not_configured": 1, "tickers": 1}
    assert payload["status"] == "not_configured"
    assert payload["ticker"] == "AAPL"


def test_pull_tickers_writes_provider_error_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FMP_API_KEY", "key")

    def failing_state(*_: object, **__: object) -> dict[str, object]:
        raise FmpProviderError("upstream 500")

    monkeypatch.setattr("research.scripts.pull_fmp_earnings.build_fmp_state", failing_state)
    result = pull_tickers(["AAPL"], output_dir=tmp_path, delay=0.0)

    payload = json.loads((tmp_path / "AAPL.json").read_text(encoding="utf-8"))
    assert result == {"ok": 0, "errors": 1, "not_configured": 0, "tickers": 1}
    assert payload["status"] == "provider_error"
    assert payload["detail"] == "upstream 500"


def _client_for_path(path: str, payload: object) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path
        assert request.url.params["apikey"] == "key"
        return httpx.Response(200, json=payload, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))
