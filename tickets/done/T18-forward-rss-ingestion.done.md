# T18: Forward RSS/news ingestion

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** medium (2-6h)
**Dependencies:** T17

## Goal
Build a forward-only RSS/news collector that stores ticker-tagged headlines with provenance.

## Outputs
- `research/src/news/rss.py` parser.
- `research/src/news/puller.py` collector.
- `research/src/news/storage.py` parquet/manifest writer.
- `research/scripts/pull_news_rss.py`.
- `PITLoader.news(as_of, lookback_days, tickers=None)`.

## Acceptance Criteria
1. RSS items are persisted with source URL, observed time, timestamp-as-of, source tier, confidence, and verification level.
2. Loader returns only rows known by `as_of`.
3. Collector is forward-only unless reliable historical publish timestamps are present.
4. No paid-subscription scraping.

## Tests Required
- Unit: RSS parser extracts title, URL, summary, and publish time.
- Unit: puller writes parquet and manifest.
- Unit: PIT loader filters news point-in-time.

## Out of Scope
- Full article scraping.
- LLM sentiment.
- News deduplication beyond source ID.
