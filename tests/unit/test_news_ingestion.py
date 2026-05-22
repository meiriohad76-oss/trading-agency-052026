from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import news.puller as news_puller
import pandas as pd
import polars as pl
from news.puller import pull_rss_feeds
from news.rss import FeedSpec, parse_rss
from news.scrapling_adapter import ScraplingUnavailableError, parse_html, scrapling_available
from news.ticker_resolution import TickerAlias, TickerResolutionRegistry
from pit.manifest import DatasetName
from pit_fixtures import loader_with, provenance

from agency.provenance import SourceTier

FETCHED_AT = datetime(2026, 5, 7, 8, 0, tzinfo=UTC)
LEGAL_NAME_CONFIDENCE = 0.88
EXPECTED_MULTI_TICKER_ROWS = 2
RSS_XML = """\
<rss><channel>
  <item>
    <title>AAPL beats estimates</title>
    <link>https://example.test/aapl</link>
    <description>Apple raises guidance</description>
    <pubDate>Thu, 07 May 2026 07:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""
GENERIC_APPLE_RSS_XML = """\
<rss><channel>
  <item>
    <title>Apple Inc. announces new AI features</title>
    <link>https://example.test/apple-ai</link>
    <description>New AI features will ship this fall</description>
    <pubDate>Thu, 07 May 2026 07:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""
GENERIC_UNRESOLVED_RSS_XML = """\
<rss><channel>
  <item>
    <title>Global futures rise before central bank remarks</title>
    <link>https://example.test/global-futures</link>
    <description>Broad market context without a listed company</description>
    <pubDate>Thu, 07 May 2026 07:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""
GENERIC_MULTI_TICKER_RSS_XML = """\
<rss><channel>
  <item>
    <title>Apple Inc. and Microsoft Corporation expand AI partnership</title>
    <link>https://example.test/apple-msft-ai</link>
    <description>Both companies announced a new integration</description>
    <pubDate>Thu, 07 May 2026 07:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""


def test_scrapling_adapter_reports_missing_optional_dependency(monkeypatch) -> None:
    def missing(_name: str) -> object:
        raise ImportError("missing")

    monkeypatch.setattr("news.scrapling_adapter.import_module", missing)

    assert not scrapling_available()
    try:
        parse_html("<html><title>x</title></html>")
    except ScraplingUnavailableError as exc:
        assert "pip install .[web]" in str(exc)


def test_parse_rss_extracts_ticker_tagged_items() -> None:
    rows = parse_rss(
        RSS_XML,
        feed=FeedSpec("https://example.test/rss", "Example", ticker="aapl"),
        fetched_at=FETCHED_AT,
    )

    assert rows == [
        {
            "ticker": "AAPL",
            "feed_url": "https://example.test/rss",
            "feed_name": "Example",
            "title": "AAPL beats estimates",
            "url": "https://example.test/aapl",
            "summary": "Apple raises guidance",
            "published_at": datetime(2026, 5, 7, 7, 0, tzinfo=UTC),
        }
    ]


def test_news_puller_verify_context_uses_windows_truststore(monkeypatch: object) -> None:
    class FakeContext:
        def __init__(self, protocol: object) -> None:
            self.protocol = protocol

    class FakeTruststore:
        SSLContext = FakeContext

    def fake_import_module(name: str) -> object:
        assert name == "truststore"
        return FakeTruststore

    monkeypatch.setattr(news_puller.sys, "platform", "win32")
    monkeypatch.setattr(news_puller, "import_module", fake_import_module)

    context = news_puller._verify_context()

    assert isinstance(context, FakeContext)


def test_news_puller_builds_sec_user_agent_header() -> None:
    headers = news_puller._request_headers("Trading Agency admin@example.com")

    assert headers == {"User-Agent": "Trading Agency admin@example.com"}


def test_news_puller_omits_blank_user_agent_header() -> None:
    assert news_puller._request_headers("  ") == {}


async def test_pull_rss_feeds_writes_parquet_and_manifest(tmp_path: Path) -> None:
    parquet_path = tmp_path / "news_rss.parquet"
    manifest_path = tmp_path / "news_rss.json"

    async def fetcher(url: str) -> str:
        assert url == "https://example.test/rss"
        return RSS_XML

    summary = await pull_rss_feeds(
        feeds=[FeedSpec("https://example.test/rss", "Example", ticker="AAPL")],
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        fetcher=fetcher,
        clock=lambda: FETCHED_AT,
    )

    frame = pd.read_parquet(parquet_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert summary.rows_written == 1
    assert frame.iloc[0]["source_tier"] == SourceTier.RSS_HEADLINE.value
    assert manifest["dataset"] == "news_rss"
    assert manifest["row_count"] == 1


async def test_pull_rss_feeds_resolves_generic_feed_with_alias_registry(tmp_path: Path) -> None:
    parquet_path = tmp_path / "news_rss.parquet"
    manifest_path = tmp_path / "news_rss.json"

    async def fetcher(_url: str) -> str:
        return GENERIC_APPLE_RSS_XML

    summary = await pull_rss_feeds(
        feeds=[FeedSpec("https://example.test/generic", "PRN")],
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        fetcher=fetcher,
        clock=lambda: FETCHED_AT,
        ticker_registry=_ticker_registry(),
        resolve_generic_tickers=True,
    )

    frame = pd.read_parquet(parquet_path)
    assert summary.rows_written == 1
    assert frame.iloc[0]["ticker"] == "AAPL"
    assert frame.iloc[0]["ticker_match_status"] == "resolved"
    assert frame.iloc[0]["ticker_match_method"] == "legal_name"
    assert frame.iloc[0]["ticker_match_confidence"] == LEGAL_NAME_CONFIDENCE
    assert "Apple Inc." in frame.iloc[0]["ticker_match_reason"]
    assert pd.isna(frame.iloc[0]["raw_feed_ticker"])


async def test_pull_rss_feeds_keeps_unresolved_generic_row_for_audit(tmp_path: Path) -> None:
    parquet_path = tmp_path / "news_rss.parquet"
    manifest_path = tmp_path / "news_rss.json"

    async def fetcher(_url: str) -> str:
        return GENERIC_UNRESOLVED_RSS_XML

    summary = await pull_rss_feeds(
        feeds=[FeedSpec("https://example.test/generic", "PRN")],
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        fetcher=fetcher,
        clock=lambda: FETCHED_AT,
        ticker_registry=_ticker_registry(),
        resolve_generic_tickers=True,
        keep_unresolved=True,
    )

    frame = pd.read_parquet(parquet_path)
    assert summary.rows_written == 1
    assert pd.isna(frame.iloc[0]["ticker"])
    assert frame.iloc[0]["ticker_match_status"] == "unresolved"
    assert frame.iloc[0]["ticker_match_confidence"] == 0.0
    assert "No high-confidence ticker match" in frame.iloc[0]["ticker_match_reason"]


async def test_source_id_is_unique_per_raw_item_and_ticker_match(tmp_path: Path) -> None:
    parquet_path = tmp_path / "news_rss.parquet"
    manifest_path = tmp_path / "news_rss.json"

    async def fetcher(_url: str) -> str:
        return GENERIC_MULTI_TICKER_RSS_XML

    await pull_rss_feeds(
        feeds=[FeedSpec("https://example.test/generic", "PRN")],
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        fetcher=fetcher,
        clock=lambda: FETCHED_AT,
        ticker_registry=_ticker_registry(),
        resolve_generic_tickers=True,
    )

    frame = pd.read_parquet(parquet_path).sort_values("ticker").reset_index(drop=True)
    assert frame["ticker"].tolist() == ["AAPL", "MSFT"]
    assert frame["source_id"].nunique() == EXPECTED_MULTI_TICKER_ROWS
    assert frame["source_id"].str.startswith("rss:").all()


async def test_raw_source_id_is_shared_across_multi_ticker_expansion(tmp_path: Path) -> None:
    parquet_path = tmp_path / "news_rss.parquet"
    manifest_path = tmp_path / "news_rss.json"

    async def fetcher(_url: str) -> str:
        return GENERIC_MULTI_TICKER_RSS_XML

    await pull_rss_feeds(
        feeds=[FeedSpec("https://example.test/generic", "PRN")],
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        fetcher=fetcher,
        clock=lambda: FETCHED_AT,
        ticker_registry=_ticker_registry(),
        resolve_generic_tickers=True,
    )

    frame = pd.read_parquet(parquet_path)
    assert frame["raw_source_id"].nunique() == 1
    assert set(frame["related_tickers"]) == {"AAPL,MSFT"}


def test_pit_loader_filters_news_by_timestamp_and_ticker(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            _news("AAPL", "inside", date(2026, 5, 5)),
            _news("AAPL", "future", date(2026, 5, 7)),
            _news("MSFT", "other", date(2026, 5, 5)),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.NEWS_RSS: frame})

    result = loader.news(date(2026, 5, 6), lookback_days=2, tickers=["AAPL"])

    assert [item.value["title"] for item in result] == ["inside"]
    assert result[0].provenance.source_id == "inside"


def test_pit_loader_excludes_unresolved_news_when_ticker_filter_is_used(tmp_path: Path) -> None:
    frame = pl.DataFrame(
        [
            _news(
                "AAPL",
                "unresolved",
                date(2026, 5, 5),
                ticker_match_status="unresolved",
                ticker_match_confidence=0.0,
            ),
            _news(
                "AAPL",
                "ambiguous",
                date(2026, 5, 5),
                ticker_match_status="ambiguous",
                ticker_match_confidence=0.5,
            ),
            _news(
                "AAPL",
                "resolved",
                date(2026, 5, 5),
                ticker_match_status="resolved",
                ticker_match_confidence=0.88,
            ),
            _news("AAPL", "legacy", date(2026, 5, 5)),
        ]
    )
    loader = loader_with(tmp_path, {DatasetName.NEWS_RSS: frame})

    result = loader.news(date(2026, 5, 6), lookback_days=2, tickers=["AAPL"])

    assert [item.value["title"] for item in result] == ["resolved", "legacy"]


def _news(
    ticker: str,
    title: str,
    as_of: date,
    **extra: object,
) -> dict[str, object]:
    row = {
        "ticker": ticker,
        "feed_url": "https://example.test/rss",
        "feed_name": "Example",
        "title": title,
        "url": f"https://example.test/{title}",
        "summary": None,
        "published_at": as_of,
        **provenance(SourceTier.RSS_HEADLINE, as_of, source_id=title),
    }
    row.update(extra)
    return row


def _ticker_registry() -> TickerResolutionRegistry:
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
                brand_aliases=("Microsoft",),
                allow_plain_brand=True,
            ),
        ],
        active_tickers=("AAPL", "MSFT"),
    )
