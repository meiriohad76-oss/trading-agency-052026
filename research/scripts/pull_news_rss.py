from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHORT_FEED_PARTS = 2
TICKER_FEED_PARTS = 3

sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from news.puller import pull_rss_feeds  # noqa: E402
from news.rss import FeedSpec  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull forward RSS/news headlines.")
    parser.add_argument(
        "--feed",
        action="append",
        required=True,
        help="Feed spec as SOURCE_NAME,URL or SOURCE_NAME,TICKER,URL.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "news_rss.parquet",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "news_rss.json",
    )
    args = parser.parse_args()
    feeds = [_feed_spec(value) for value in args.feed]
    summary = asyncio.run(
        pull_rss_feeds(feeds=feeds, parquet_path=args.output, manifest_path=args.manifest)
    )
    print(summary)


def _feed_spec(value: str) -> FeedSpec:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) == SHORT_FEED_PARTS:
        return FeedSpec(source_name=parts[0], url=parts[1])
    if len(parts) == TICKER_FEED_PARTS:
        return FeedSpec(source_name=parts[0], ticker=parts[1], url=parts[2])
    raise ValueError("--feed must be SOURCE_NAME,URL or SOURCE_NAME,TICKER,URL")


if __name__ == "__main__":
    main()
