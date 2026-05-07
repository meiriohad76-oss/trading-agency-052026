from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
from news.rss import FeedSpec, parse_rss
from news.storage import write_manifest, write_news_frame

from agency.provenance import SourceTier, VerificationLevel, compute_freshness

Fetcher = Callable[[str], Awaitable[str]]


@dataclass(frozen=True)
class NewsPullSummary:
    feeds_requested: int
    rows_written: int
    issues: list[dict[str, str]]


async def pull_rss_feeds(
    *,
    feeds: list[FeedSpec],
    parquet_path: Path,
    manifest_path: Path,
    fetcher: Fetcher | None = None,
    clock: Callable[[], datetime] | None = None,
) -> NewsPullSummary:
    get_now = clock or (lambda: datetime.now(UTC))
    fetched_at = get_now()
    issues: list[dict[str, str]] = []
    frames: list[pd.DataFrame] = []
    fetch = fetcher or _httpx_fetch
    for feed in feeds:
        try:
            xml = await fetch(feed.url)
            rows = parse_rss(xml, feed=feed, fetched_at=fetched_at)
        except Exception as exc:
            issues.append({"feed_url": feed.url, "reason": str(exc)})
            continue
        if rows:
            frames.append(_normalize(rows, fetched_at=fetched_at))
    rows_written = 0
    if frames:
        rows_written = write_news_frame(parquet_path, pd.concat(frames, ignore_index=True))
    write_manifest(manifest_path, parquet_path, fetched_at=fetched_at)
    return NewsPullSummary(len(feeds), rows_written, issues)


async def _httpx_fetch(url: str) -> str:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def _normalize(rows: list[dict[str, object]], *, fetched_at: datetime) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["timestamp_observed"] = fetched_at
    frame["timestamp_as_of"] = pd.to_datetime(frame["published_at"], utc=True)
    frame["source"] = "rss"
    frame["source_tier"] = SourceTier.RSS_HEADLINE.value
    frame["source_url"] = frame["url"]
    frame["freshness"] = frame["timestamp_as_of"].map(
        lambda value: compute_freshness(value.to_pydatetime(), "news", now=fetched_at).value
    )
    frame["confidence"] = 0.55
    frame["verification_level"] = VerificationLevel.CONFIRMED.value
    frame["source_id"] = frame.apply(_source_id, axis=1)
    return frame


def _source_id(row: pd.Series) -> str:
    digest = hashlib.sha256()
    digest.update(str(row["feed_name"]).encode("utf-8"))
    digest.update(str(row["ticker"]).encode("utf-8"))
    digest.update(str(row["url"]).encode("utf-8"))
    digest.update(str(row["title"]).encode("utf-8"))
    return f"rss:{digest.hexdigest()[:24]}"
