from __future__ import annotations

import os
import ssl
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import certifi
import httpx
import truststore
import yfinance as yf
from curl_cffi import requests as curl_requests

os.environ.setdefault("CURL_CA_BUNDLE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

_YAHOO_MODULES = "summaryDetail,financialData,defaultKeyStatistics"
_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
    )
}


class FetchError(RuntimeError):
    """Raised when yfinance cannot return a fundamentals snapshot."""


@dataclass(frozen=True)
class YfinanceSnapshot:
    ticker: str
    forward_pe: float | None
    trailing_pe: float | None
    forward_eps: float | None
    trailing_eps: float | None
    peg_ratio: float | None
    analyst_mean_target: float | None
    analyst_median_target: float | None
    analyst_count: int | None
    revenue_growth: float | None
    earnings_growth: float | None
    return_on_equity: float | None
    return_on_assets: float | None
    operating_margins: float | None
    profit_margins: float | None
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def pull_yfinance_snapshot(ticker: str) -> YfinanceSnapshot:
    normalized = ticker.upper().strip()
    try:
        info = yf.Ticker(normalized, session=_curl_session()).info or {}
    except Exception as yfinance_exc:
        try:
            return _snapshot_from_yahoo_quote_summary(
                normalized,
                _pull_yahoo_quote_summary(normalized),
            )
        except Exception as fallback_exc:
            raise FetchError(
                f"yfinance fundamentals pull failed for {normalized}: {yfinance_exc}; "
                f"Yahoo quote-summary fallback failed: {fallback_exc}"
            ) from fallback_exc
    if not isinstance(info, dict):
        raise FetchError(f"yfinance fundamentals pull failed for {normalized}: info was not a dict")
    return _snapshot_from_yfinance_info(normalized, info)


def _snapshot_from_yfinance_info(ticker: str, info: dict[str, object]) -> YfinanceSnapshot:
    return YfinanceSnapshot(
        ticker=ticker,
        forward_pe=_num(info.get("forwardPE")),
        trailing_pe=_num(info.get("trailingPE")),
        forward_eps=_num(info.get("forwardEps")),
        trailing_eps=_num(info.get("trailingEps")),
        peg_ratio=_num(info.get("pegRatio")),
        analyst_mean_target=_num(info.get("targetMeanPrice")),
        analyst_median_target=_num(info.get("targetMedianPrice")),
        analyst_count=_int(info.get("numberOfAnalystOpinions")),
        revenue_growth=_num(info.get("revenueGrowth")),
        earnings_growth=_num(info.get("earningsGrowth")),
        return_on_equity=_num(info.get("returnOnEquity")),
        return_on_assets=_num(info.get("returnOnAssets")),
        operating_margins=_num(info.get("operatingMargins")),
        profit_margins=_num(info.get("profitMargins")),
    )


def _snapshot_from_yahoo_quote_summary(ticker: str, modules: dict[str, object]) -> YfinanceSnapshot:
    summary_detail = _module(modules, "summaryDetail")
    financial_data = _module(modules, "financialData")
    default_key_statistics = _module(modules, "defaultKeyStatistics")
    return YfinanceSnapshot(
        ticker=ticker,
        forward_pe=_num(_raw(summary_detail.get("forwardPE"))),
        trailing_pe=_num(_raw(summary_detail.get("trailingPE"))),
        forward_eps=_num(_raw(default_key_statistics.get("forwardEps"))),
        trailing_eps=_num(_raw(default_key_statistics.get("trailingEps"))),
        peg_ratio=_num(_raw(default_key_statistics.get("pegRatio"))),
        analyst_mean_target=_num(_raw(financial_data.get("targetMeanPrice"))),
        analyst_median_target=_num(_raw(financial_data.get("targetMedianPrice"))),
        analyst_count=_int(_raw(financial_data.get("numberOfAnalystOpinions"))),
        revenue_growth=_num(_raw(financial_data.get("revenueGrowth"))),
        earnings_growth=_num(_raw(financial_data.get("earningsGrowth"))),
        return_on_equity=_num(_raw(financial_data.get("returnOnEquity"))),
        return_on_assets=_num(_raw(financial_data.get("returnOnAssets"))),
        operating_margins=_num(_raw(financial_data.get("operatingMargins"))),
        profit_margins=_num(_raw(financial_data.get("profitMargins"))),
    )


def _pull_yahoo_quote_summary(ticker: str) -> dict[str, object]:
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with httpx.Client(
        verify=context,
        headers=_YAHOO_HEADERS,
        timeout=20.0,
        follow_redirects=True,
    ) as client:
        # Yahoo's crumb endpoint expects a browser cookie from the yahoo.com domain.
        client.get("https://fc.yahoo.com")
        client.get("https://finance.yahoo.com/quote/" + ticker).raise_for_status()
        crumb_response = client.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
        crumb_response.raise_for_status()
        crumb = crumb_response.text.strip()
        response = client.get(
            f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}",
            params={"modules": _YAHOO_MODULES, "crumb": crumb},
        )
        response.raise_for_status()
    payload = response.json()
    result = payload.get("quoteSummary", {}).get("result")
    if not isinstance(result, list) or not result or not isinstance(result[0], dict):
        raise FetchError(f"Yahoo quote-summary returned no fundamentals for {ticker}")
    return result[0]


def _curl_session() -> curl_requests.Session:
    return curl_requests.Session(verify=certifi.where())


def _module(modules: dict[str, object], name: str) -> dict[str, object]:
    value = modules.get(name)
    return value if isinstance(value, dict) else {}


def _raw(value: object) -> object:
    if isinstance(value, dict) and "raw" in value:
        return value.get("raw")
    return value


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
