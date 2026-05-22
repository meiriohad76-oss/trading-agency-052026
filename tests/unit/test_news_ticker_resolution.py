from __future__ import annotations

from news.ticker_resolution import (
    TickerAlias,
    TickerResolutionRegistry,
    resolve_news_row,
)

SEC_CIK_CONFIDENCE = 0.98
MARKET_SYMBOL_CONFIDENCE = 0.93
LEGAL_NAME_CONFIDENCE = 0.88
BRAND_ALIAS_CONFIDENCE = 0.78


def test_feed_ticker_is_preserved_as_high_confidence() -> None:
    registry = _registry()
    row = _row("Analysts raise cloud software estimates", ticker="aapl")

    resolved = resolve_news_row(row, registry)

    assert len(resolved) == 1
    assert resolved[0].ticker == "AAPL"
    assert resolved[0].match.status == "feed_ticker"
    assert resolved[0].match.method == "feed_ticker"
    assert resolved[0].match.confidence == 1.0
    assert resolved[0].to_row()["raw_feed_ticker"] == "aapl"


def test_sec_cik_in_title_maps_to_ticker() -> None:
    registry = _registry()
    row = _row("Apple Inc. files Form 10-K for CIK 0000320193")

    resolved = resolve_news_row(row, registry)

    assert _matches(resolved) == {"AAPL": "sec_cik"}
    assert resolved[0].match.confidence == SEC_CIK_CONFIDENCE
    assert resolved[0].match.matched_text == "0000320193"
    assert "CIK" in resolved[0].match.reason


def test_market_symbol_syntax_maps_to_active_ticker() -> None:
    registry = _registry()
    row = _row("Chip demand lifts NASDAQ:NVDA after the open")

    resolved = resolve_news_row(row, registry)

    assert _matches(resolved) == {"NVDA": "market_symbol"}
    assert resolved[0].match.confidence == MARKET_SYMBOL_CONFIDENCE
    assert resolved[0].match.matched_text == "NASDAQ:NVDA"


def test_plain_ambiguous_symbol_now_does_not_match() -> None:
    registry = _registry()
    row = _row("What investors need now before the CPI release")

    resolved = resolve_news_row(row, registry)

    assert len(resolved) == 1
    assert resolved[0].ticker is None
    assert resolved[0].match.status == "unresolved"


def test_plain_single_letter_t_does_not_match() -> None:
    registry = _registry()
    row = _row("T shares a market update before the open")

    resolved = resolve_news_row(row, registry)

    assert len(resolved) == 1
    assert resolved[0].ticker is None
    assert resolved[0].match.status == "unresolved"


def test_legal_name_alias_maps_to_ticker() -> None:
    registry = _registry()
    row = _row("Microsoft Corporation announces quarterly dividend")

    resolved = resolve_news_row(row, registry)

    assert _matches(resolved) == {"MSFT": "legal_name"}
    assert resolved[0].match.confidence == LEGAL_NAME_CONFIDENCE
    assert resolved[0].match.matched_text == "Microsoft Corporation"


def test_brand_alias_maps_with_lower_confidence_and_reason() -> None:
    registry = _registry()
    row = _row("Azure demand accelerates in enterprise cloud contracts")

    resolved = resolve_news_row(row, registry)

    assert _matches(resolved) == {"MSFT": "brand_alias"}
    assert resolved[0].match.confidence == BRAND_ALIAS_CONFIDENCE
    assert resolved[0].match.matched_text == "Azure"
    assert "brand alias" in resolved[0].match.reason


def test_multi_company_headline_emits_multiple_ticker_matches() -> None:
    registry = _registry()
    row = _row("Apple Inc. and Microsoft Corporation expand AI partnership")

    resolved = resolve_news_row(row, registry)

    assert _matches(resolved) == {"AAPL": "legal_name", "MSFT": "legal_name"}
    assert {item.to_row()["related_tickers"] for item in resolved} == {"AAPL,MSFT"}


def test_unmatched_generic_headline_is_unresolved() -> None:
    registry = _registry()
    row = _row("Global market futures rise before Fed minutes")

    resolved = resolve_news_row(row, registry)

    assert len(resolved) == 1
    assert resolved[0].ticker is None
    assert resolved[0].match.status == "unresolved"
    assert resolved[0].match.confidence == 0.0
    assert "No high-confidence ticker match" in resolved[0].match.reason


def _registry() -> TickerResolutionRegistry:
    return TickerResolutionRegistry(
        aliases=[
            TickerAlias(
                ticker="AAPL",
                cik="0000320193",
                legal_names=("Apple Inc.",),
                brand_aliases=("Apple",),
                allow_plain_brand=True,
            ),
            TickerAlias(
                ticker="MSFT",
                cik="0000789019",
                legal_names=("Microsoft Corporation",),
                brand_aliases=("Azure",),
                allow_plain_brand=True,
            ),
            TickerAlias(
                ticker="NVDA",
                cik="0001045810",
                legal_names=("NVIDIA Corporation",),
                brand_aliases=("NVIDIA",),
                allow_plain_brand=True,
            ),
            TickerAlias(ticker="NOW", legal_names=("ServiceNow, Inc.",)),
            TickerAlias(ticker="T", legal_names=("AT&T Inc.",)),
        ],
        active_tickers=("AAPL", "MSFT", "NVDA", "NOW", "T"),
    )


def _row(title: str, *, ticker: str | None = None) -> dict[str, object]:
    return {
        "ticker": ticker,
        "feed_url": "https://example.test/rss",
        "feed_name": "Example",
        "title": title,
        "url": f"https://example.test/{abs(hash(title))}",
        "summary": "",
    }


def _matches(resolved: object) -> dict[str, str]:
    return {item.ticker: item.match.method for item in resolved}
