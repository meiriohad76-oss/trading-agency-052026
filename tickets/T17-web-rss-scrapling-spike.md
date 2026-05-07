# T17: Web/RSS discovery ingestion spike

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** medium (2-6h)
**Dependencies:** T03, T04

## Goal
Add a safe optional Scrapling integration for public web/RSS discovery without making scraping a core dependency.

## Context
Scrapling can help parse public pages and inspect RSS-linked articles, but v2 must not scrape paid-subscription pages or bypass source terms. This spike keeps Scrapling optional and parser/fetcher use isolated.

## Outputs
- Optional `web` dependency extra for Scrapling.
- `research/src/news/scrapling_adapter.py` with availability checks, HTML parsing, and basic fetch support.
- No required CI dependency on Scrapling.

## Acceptance Criteria
1. Normal setup and CI pass without installing Scrapling.
2. Scrapling calls fail with a clear install message when optional dependency is absent.
3. Adapter exposes parsed page title and text for public-page experiments.
4. Paid-sub scraping remains out of scope.

## Tests Required
- Unit: adapter reports unavailable when Scrapling is not installed.
- Unit: missing Scrapling raises a clear exception.

## Out of Scope
- Browser automation for anti-bot bypass.
- Paid subscription scraping.
- Persisting article body text as an actionable signal.
