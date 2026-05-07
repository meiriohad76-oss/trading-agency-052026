from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import polars as pl
from news.puller import pull_rss_feeds
from news.rss import FeedSpec, parse_rss
from news.scrapling_adapter import ScraplingUnavailableError, parse_html, scrapling_available
from pit.manifest import DatasetName
from pit_fixtures import loader_with, provenance

from agency.provenance import SourceTier

FETCHED_AT = datetime(2026, 5, 7, 8, 0, tzinfo=UTC)
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


def _news(ticker: str, title: str, as_of: date) -> dict[str, object]:
    return {
        "ticker": ticker,
        "feed_url": "https://example.test/rss",
        "feed_name": "Example",
        "title": title,
        "url": f"https://example.test/{title}",
        "summary": None,
        "published_at": as_of,
        **provenance(SourceTier.RSS_HEADLINE, as_of, source_id=title),
    }
