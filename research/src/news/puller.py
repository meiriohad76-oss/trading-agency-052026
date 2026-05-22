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
from news.ticker_resolution import ResolvedNewsRow, TickerResolutionRegistry, resolve_news_row

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
    ticker_registry: TickerResolutionRegistry | None = None,
    resolve_generic_tickers: bool = False,
    keep_unresolved: bool = True,
    min_confidence: float = 0.70,
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
        if resolve_generic_tickers:
            rows = _resolve_rows(
                rows,
                registry=ticker_registry or TickerResolutionRegistry(),
                keep_unresolved=keep_unresolved,
                min_confidence=min_confidence,
            )
        if rows:
            frames.append(_normalize(rows, fetched_at=fetched_at))
    rows_written = 0
    if frames:
        rows_written = write_news_frame(parquet_path, pd.concat(frames, ignore_index=True))
    write_manifest(
        manifest_path,
        parquet_path,
        fetched_at=fetched_at,
        resolution_min_confidence=min_confidence,
    )
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
    if "raw_source_id" not in frame.columns:
        frame["raw_source_id"] = frame.apply(_raw_source_id, axis=1)
    else:
        missing_raw_id = frame["raw_source_id"].isna()
        if missing_raw_id.any():
            frame.loc[missing_raw_id, "raw_source_id"] = frame[missing_raw_id].apply(
                _raw_source_id,
                axis=1,
            )
    frame["source_id"] = frame.apply(_source_id, axis=1)
    return frame


def _source_id(row: pd.Series) -> str:
    if row.get("ticker_match_status") in {"resolved", "feed_ticker", "unresolved", "ambiguous"}:
        digest = hashlib.sha256()
        digest.update(str(row.get("raw_source_id") or _raw_source_id(row)).encode("utf-8"))
        digest.update(str(row.get("ticker")).encode("utf-8"))
        digest.update(str(row.get("ticker_match_status")).encode("utf-8"))
        digest.update(str(row.get("ticker_match_method")).encode("utf-8"))
        digest.update(str(row.get("matched_text")).encode("utf-8"))
        return f"rss:{digest.hexdigest()[:24]}"
    digest = hashlib.sha256()
    digest.update(str(row["feed_name"]).encode("utf-8"))
    digest.update(str(row["ticker"]).encode("utf-8"))
    digest.update(str(row["url"]).encode("utf-8"))
    digest.update(str(row["title"]).encode("utf-8"))
    return f"rss:{digest.hexdigest()[:24]}"


def _raw_source_id(row: pd.Series) -> str:
    digest = hashlib.sha256()
    digest.update(str(row["feed_name"]).encode("utf-8"))
    digest.update(str(row["url"]).encode("utf-8"))
    digest.update(str(row["title"]).encode("utf-8"))
    return f"rss-raw:{digest.hexdigest()[:24]}"


def _resolve_rows(
    rows: list[dict[str, object]],
    *,
    registry: TickerResolutionRegistry,
    keep_unresolved: bool,
    min_confidence: float,
) -> list[dict[str, object]]:
    resolved_rows: list[dict[str, object]] = []
    for row in rows:
        for resolved in resolve_news_row(row, registry):
            if resolved.match.status == "unresolved" and not keep_unresolved:
                continue
            if (
                resolved.match.status in {"resolved", "feed_ticker"}
                and resolved.match.confidence < min_confidence
            ):
                if keep_unresolved:
                    resolved_rows.append(_below_threshold_row(resolved, min_confidence))
                continue
            resolved_rows.append(resolved.to_row())
    return resolved_rows


def _below_threshold_row(resolved: ResolvedNewsRow, min_confidence: float) -> dict[str, object]:
    row = resolved.to_row()
    row["ticker"] = None
    row["ticker_match_status"] = "ambiguous"
    row["ticker_match_reason"] = (
        f"{resolved.match.reason} Match confidence {resolved.match.confidence:.2f} is below "
        f"the configured minimum {min_confidence:.2f}."
    )
    return row
