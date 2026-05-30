from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fundamentals.yfinance_snapshot import (
    FetchError,
    YfinanceSnapshot,
    _pull_yahoo_quote_summary,
    pull_yfinance_snapshot,
)


def test_pull_returns_forward_pe_and_targets() -> None:
    ticker = _mock_ticker(
        {
            "forwardPE": 24.3,
            "trailingPE": 28.1,
            "forwardEps": 7.28,
            "trailingEps": 6.84,
            "targetMeanPrice": 242.0,
            "targetMedianPrice": 238.0,
            "numberOfAnalystOpinions": 47,
        }
    )
    with patch("fundamentals.yfinance_snapshot.yf.Ticker", return_value=ticker):
        result = pull_yfinance_snapshot("aapl")

    assert result.ticker == "AAPL"
    assert result.forward_pe == pytest.approx(24.3)
    assert result.trailing_pe == pytest.approx(28.1)
    assert result.forward_eps == pytest.approx(7.28)
    assert result.trailing_eps == pytest.approx(6.84)
    assert result.analyst_mean_target == pytest.approx(242.0)
    assert result.analyst_median_target == pytest.approx(238.0)
    assert result.analyst_count == 47


def test_pull_handles_missing_fields_as_none() -> None:
    with patch("fundamentals.yfinance_snapshot.yf.Ticker", return_value=_mock_ticker({})):
        result = pull_yfinance_snapshot("AAPL")

    assert result.forward_pe is None
    assert result.forward_eps is None
    assert result.analyst_mean_target is None


def test_pull_raises_fetch_error_on_provider_exception() -> None:
    with (
        patch("fundamentals.yfinance_snapshot.yf.Ticker", side_effect=RuntimeError("network")),
        patch("fundamentals.yfinance_snapshot._pull_yahoo_quote_summary", side_effect=RuntimeError("fallback")),
        pytest.raises(FetchError, match="AAPL"),
    ):
        pull_yfinance_snapshot("AAPL")


def test_pull_falls_back_to_yahoo_quote_summary_when_yfinance_provider_fails() -> None:
    quote_summary = {
        "summaryDetail": {
            "forwardPE": {"raw": 24.3},
            "trailingPE": {"raw": 28.1},
        },
        "defaultKeyStatistics": {
            "forwardEps": {"raw": 7.28},
            "trailingEps": {"raw": 6.84},
            "pegRatio": {"raw": 2.1},
        },
        "financialData": {
            "targetMeanPrice": {"raw": 242.0},
            "targetMedianPrice": {"raw": 238.0},
            "numberOfAnalystOpinions": {"raw": 47},
            "revenueGrowth": {"raw": 0.085},
            "earningsGrowth": {"raw": 0.12},
            "returnOnEquity": {"raw": 1.47},
            "returnOnAssets": {"raw": 0.31},
            "operatingMargins": {"raw": 0.302},
            "profitMargins": {"raw": 0.243},
        },
    }
    with (
        patch("fundamentals.yfinance_snapshot.yf.Ticker", side_effect=RuntimeError("network")),
        patch("fundamentals.yfinance_snapshot._pull_yahoo_quote_summary", return_value=quote_summary),
    ):
        result = pull_yfinance_snapshot("aapl")

    assert result.ticker == "AAPL"
    assert result.forward_pe == pytest.approx(24.3)
    assert result.trailing_pe == pytest.approx(28.1)
    assert result.forward_eps == pytest.approx(7.28)
    assert result.trailing_eps == pytest.approx(6.84)
    assert result.peg_ratio == pytest.approx(2.1)
    assert result.analyst_count == 47


def test_yahoo_quote_summary_warms_cookie_before_crumb(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeYahooClient()
    monkeypatch.setattr("fundamentals.yfinance_snapshot.httpx.Client", lambda **_: client)

    result = _pull_yahoo_quote_summary("AAPL")

    assert result["financialData"]["targetMeanPrice"]["raw"] == pytest.approx(242.0)
    assert client.paths[:3] == [
        "https://fc.yahoo.com",
        "https://finance.yahoo.com/quote/AAPL",
        "https://query1.finance.yahoo.com/v1/test/getcrumb",
    ]


def test_snapshot_to_dict_is_json_serializable() -> None:
    snapshot = YfinanceSnapshot(
        ticker="AAPL",
        forward_pe=24.3,
        trailing_pe=28.1,
        forward_eps=7.28,
        trailing_eps=6.84,
        peg_ratio=None,
        analyst_mean_target=242.0,
        analyst_median_target=238.0,
        analyst_count=47,
        revenue_growth=0.085,
        earnings_growth=0.12,
        return_on_equity=1.47,
        return_on_assets=0.31,
        operating_margins=0.302,
        profit_margins=0.243,
        fetched_at="2026-05-30T12:00:00+00:00",
    )

    payload = snapshot.to_dict()

    assert payload["ticker"] == "AAPL"
    assert payload["forward_pe"] == pytest.approx(24.3)
    assert json.loads(json.dumps(payload))["peg_ratio"] is None


def _mock_ticker(info: dict[str, object]) -> MagicMock:
    ticker = MagicMock()
    ticker.info = info
    return ticker


class _FakeYahooClient:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.cookie_ready = False

    def __enter__(self) -> _FakeYahooClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, url: str, **_: object) -> _FakeYahooResponse:
        self.paths.append(url)
        if url == "https://fc.yahoo.com":
            self.cookie_ready = True
            return _FakeYahooResponse(text="not found")
        if url == "https://query1.finance.yahoo.com/v1/test/getcrumb" and not self.cookie_ready:
            raise RuntimeError("crumb requested before cookie warmup")
        if url == "https://query1.finance.yahoo.com/v1/test/getcrumb":
            return _FakeYahooResponse(text="crumb")
        if url.startswith("https://query2.finance.yahoo.com/v10/finance/quoteSummary/"):
            return _FakeYahooResponse(
                payload={
                    "quoteSummary": {
                        "result": [
                            {
                                "financialData": {
                                    "targetMeanPrice": {"raw": 242.0},
                                }
                            }
                        ]
                    }
                }
            )
        return _FakeYahooResponse(text="")


class _FakeYahooResponse:
    def __init__(self, *, text: str = "", payload: dict[str, object] | None = None) -> None:
        self.text = text
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload
