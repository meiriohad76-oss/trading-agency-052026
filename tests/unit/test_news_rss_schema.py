from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from news.storage import write_manifest, write_news_frame

FETCHED_AT = datetime(2026, 5, 7, 8, 0, tzinfo=UTC)
NEWS_RSS_SCHEMA_VERSION = 2
RESOLUTION_MIN_CONFIDENCE = 0.7


def test_storage_adds_resolution_defaults_for_legacy_frames(tmp_path: Path) -> None:
    parquet_path = tmp_path / "news_rss.parquet"

    written = write_news_frame(parquet_path, _legacy_frame())

    frame = pd.read_parquet(parquet_path)
    assert written == 1
    assert frame.iloc[0]["ticker_match_status"] == "feed_ticker"
    assert frame.iloc[0]["ticker_match_method"] == "feed_ticker"
    assert frame.iloc[0]["ticker_match_confidence"] == 1.0
    assert frame.iloc[0]["ticker_match_reason"] == "Legacy ticker-specific RSS row."
    assert frame.iloc[0]["matched_text"] == "AAPL"
    assert frame.iloc[0]["related_tickers"] == "AAPL"
    assert frame.iloc[0]["raw_feed_ticker"] == "AAPL"
    assert frame.iloc[0]["raw_source_id"] == "legacy:aapl"


def test_manifest_schema_version_2_includes_resolution_stats(tmp_path: Path) -> None:
    parquet_path = tmp_path / "news_rss.parquet"
    manifest_path = tmp_path / "news_rss.json"
    frame = pd.concat(
        [
            _legacy_frame(),
            _legacy_frame(
                ticker=None,
                source_id="legacy:generic",
                title="Generic market headline",
            ),
        ],
        ignore_index=True,
    )
    write_news_frame(parquet_path, frame)

    write_manifest(
        manifest_path,
        parquet_path,
        fetched_at=FETCHED_AT,
        resolution_min_confidence=RESOLUTION_MIN_CONFIDENCE,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == NEWS_RSS_SCHEMA_VERSION
    assert manifest["resolved_row_count"] == 0
    assert manifest["feed_ticker_row_count"] == 1
    assert manifest["ticker_linked_row_count"] == 1
    assert manifest["unresolved_row_count"] == 1
    assert manifest["ambiguous_row_count"] == 0
    assert manifest["ticker_count"] == 1
    assert manifest["resolution_min_confidence"] == RESOLUTION_MIN_CONFIDENCE


def test_news_manifest_uses_thirty_minute_operational_freshness(tmp_path: Path) -> None:
    parquet_path = tmp_path / "news_rss.parquet"
    manifest_path = tmp_path / "news_rss.json"
    write_news_frame(parquet_path, _legacy_frame())

    write_manifest(
        manifest_path,
        parquet_path,
        fetched_at=FETCHED_AT,
        resolution_min_confidence=RESOLUTION_MIN_CONFIDENCE,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert datetime.fromisoformat(manifest["stale_after"]) == FETCHED_AT + timedelta(minutes=30)


def _legacy_frame(
    *,
    ticker: str | None = "AAPL",
    source_id: str = "legacy:aapl",
    title: str = "AAPL beats estimates",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "feed_url": "https://example.test/rss",
                "feed_name": "Example",
                "title": title,
                "url": "https://example.test/aapl",
                "summary": "Apple raises guidance",
                "published_at": FETCHED_AT,
                "source": "rss",
                "source_tier": "RSS_HEADLINE",
                "source_id": source_id,
                "source_url": "https://example.test/aapl",
                "timestamp_observed": FETCHED_AT,
                "timestamp_as_of": FETCHED_AT,
                "freshness": "FRESH",
                "confidence": 0.55,
                "verification_level": "CONFIRMED",
            }
        ]
    )
