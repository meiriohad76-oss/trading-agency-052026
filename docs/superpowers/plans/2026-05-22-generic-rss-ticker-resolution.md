# Generic RSS Ticker Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert generic SEC/PRN RSS headlines from mostly unlinked context into ticker-specific, explainable, confidence-scored news evidence without creating false-positive ticker signals.

**Architecture:** Keep RSS collection as the raw acquisition lane, then add a deterministic ticker-resolution stage between RSS parsing and parquet storage. The resolver will use active-universe tickers, CIK mappings from existing SEC datasets, and a maintained alias map to emit one ticker-linked row per high-confidence match while preserving unresolved generic rows for audit/coverage. The `news` signal will consume only ticker-linked rows with explicit resolution metadata and weight headline sentiment by ticker-match confidence.

**Tech Stack:** Python 3.14, pandas/polars parquet storage, current `research/src/news` ingestion modules, current PIT loader, current `signals.news`, pytest via `.\.venv\Scripts\python -m pytest`, Superpowers TDD/debugging/verification, and existing dashboard/data-health view-model patterns.

---

## Current Problem

Generic RSS feeds are configured as `SOURCE_NAME,URL`, not `SOURCE_NAME,TICKER,URL`. `research/src/news/rss.py` therefore writes those rows with `ticker=None`. The PIT loader filters `news_rss` by ticker, and `signals.news` groups only rows where `payload["ticker"]` is in the active universe. Result: generic SEC/PRN rows are collected but usually do not affect ticker-specific news evidence.

Subscription emails are stronger today because their classifier scans email text for configured tickers and article analysis validates ticker relevance. Generic RSS needs an equivalent but conservative ticker-resolution layer.

## Product Principles

- Prefer false negatives over false positives. A missed PRN headline is safer than incorrectly attaching news to `NOW`, `APP`, `T`, or `ON`.
- Every ticker match must be explainable: method, matched text, confidence, and reason.
- Official identifiers are strongest: SEC CIK to ticker beats any name match.
- Plain ticker symbols are only accepted when market-formatted: `$AAPL`, `NASDAQ:AAPL`, `(AAPL)`, `NYSE:HD`, or feed-specific official metadata.
- Ambiguous plain words never match as symbols.
- Company aliases require word boundaries and ambiguity controls.
- Multi-company articles produce multiple ticker rows, each with the same raw source URL but separate ticker-level match metadata.
- Unresolved generic rows remain stored for data-health and audit coverage, but they do not feed ticker-specific news scores.
- No LLM is used for every RSS item. If LLM disambiguation is added later, it is limited to ambiguous, high-priority, current-cycle items.

## New Data Contract

Extend `news_rss.parquet` with nullable columns:

- `ticker_match_status`: `resolved`, `unresolved`, `ambiguous`, `feed_ticker`
- `ticker_match_method`: `feed_ticker`, `sec_cik`, `market_symbol`, `legal_name`, `brand_alias`, `manual_alias`
- `ticker_match_confidence`: float from `0.0` to `1.0`
- `ticker_match_reason`: short operator-facing explanation
- `matched_text`: text fragment that caused the match
- `related_tickers`: sorted list or comma-separated string of all tickers matched from the same raw headline
- `raw_feed_ticker`: original ticker supplied by a ticker-specific feed, if any
- `raw_source_id`: source id shared by all ticker-expanded rows from the same raw RSS item

Signal rules:

- `ticker_match_status in {"resolved", "feed_ticker"}` can feed the news signal.
- `ticker_match_confidence >= 0.70` is required for signal scoring.
- `ambiguous` and `unresolved` rows are visible in source coverage but excluded from ticker scoring.
- `news.sentiment_score` becomes a confidence-weighted sentiment rate.

## Resolution Confidence Ladder

- `1.00`: feed was explicitly ticker-specific.
- `0.98`: SEC CIK matched known ticker CIK.
- `0.93`: market-formatted symbol matched active universe, for example `$NVDA`, `NASDAQ:NVDA`, `(NVDA)`.
- `0.88`: exact legal name matched alias registry, for example `Apple Inc.`
- `0.78`: configured brand alias matched in a business/technology finance context.
- `0.50`: possible but ambiguous match; store as `ambiguous`, do not score.
- `0.00`: unresolved.

Ambiguous ticker denylist:

- Single-letter symbols: `A`, `C`, `F`, `T`
- Common English words or app terms: `APP`, `NOW`, `ON`, `IT`, `ALL`, `ARE`, `CAN`, `HAS`, `KEY`, `LOW`, `SEE`, `TEAM`
- Any active-universe ticker shorter than 3 characters unless matched as `$T`, `NYSE:T`, or equivalent market syntax.

## Files To Create Or Modify

Create:

- `research/src/news/ticker_resolution.py`
- `research/config/news-ticker-aliases.example.json`
- `tests/unit/test_news_ticker_resolution.py`
- `tests/unit/test_news_rss_schema.py`

Modify:

- `research/src/news/puller.py`
- `research/src/news/storage.py`
- `research/scripts/pull_news_rss.py`
- `research/src/data_refresh/types.py`
- `research/src/data_refresh/jobs.py`
- `research/src/pit/forward_views.py`
- `research/src/signals/news.py`
- `research/config/live-refresh.example.json`
- `research/config/live-refresh.local.json`
- `src/agency/runtime/data_load_status.py`
- `src/agency/views/_shared.py`
- Existing tests:
  - `tests/unit/test_news_ingestion.py`
  - `tests/unit/test_news_signal.py`
  - `tests/unit/test_data_refresh_batch.py`
  - `tests/unit/test_data_load_status.py`

Do not expand large shared files beyond thin view-model glue. If UI health text needs more than a small helper, create a focused module.

---

## Ticket 1: Ticker Alias Registry And Resolver

**Goal:** Build a deterministic, testable resolver that maps raw generic RSS rows to zero, one, or many ticker matches with confidence and reason.

**Files:**

- Create: `research/src/news/ticker_resolution.py`
- Create: `research/config/news-ticker-aliases.example.json`
- Create: `tests/unit/test_news_ticker_resolution.py`

**Steps:**

- [ ] Step 1: Write failing resolver tests.

  Test cases:

  - `test_feed_ticker_is_preserved_as_high_confidence`
  - `test_sec_cik_in_title_maps_to_ticker`
  - `test_market_symbol_syntax_maps_to_active_ticker`
  - `test_plain_ambiguous_symbol_now_does_not_match`
  - `test_plain_single_letter_t_does_not_match`
  - `test_legal_name_alias_maps_to_ticker`
  - `test_brand_alias_maps_with_lower_confidence_and_reason`
  - `test_multi_company_headline_emits_multiple_ticker_matches`
  - `test_unmatched_generic_headline_is_unresolved`

  Run:

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_news_ticker_resolution.py -q
  ```

  Expected before implementation: import failure for `news.ticker_resolution`.

- [ ] Step 2: Implement data types.

  Required objects:

  - `TickerAlias`
  - `TickerResolutionRegistry`
  - `TickerMatch`
  - `ResolvedNewsRow`
  - `resolve_news_row(row, registry) -> list[ResolvedNewsRow]`

- [ ] Step 3: Implement match methods.

  Required methods, in priority order:

  - feed ticker
  - SEC CIK
  - market-formatted symbol
  - legal-name alias
  - brand alias

- [ ] Step 4: Implement ambiguity controls.

  Rules:

  - no plain symbol match for ambiguous denylist terms
  - no plain symbol match for symbols shorter than 3 characters
  - no alias match inside longer words
  - no duplicate ticker rows per raw headline

- [ ] Step 5: Add alias example config.

  Example shape:

  ```json
  {
    "aliases": [
      {
        "ticker": "AAPL",
        "cik": "0000320193",
        "legal_names": ["Apple Inc."],
        "brand_aliases": ["Apple"],
        "allow_plain_brand": true
      }
    ],
    "ambiguous_symbols": ["A", "C", "F", "T", "APP", "NOW", "ON"]
  }
  ```

- [ ] Step 6: Run targeted tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_news_ticker_resolution.py -q
  ```

**Ticket DoD:**

- Resolver emits explainable ticker matches.
- Ambiguous symbols are excluded unless market-formatted.
- Multi-ticker headlines are supported.
- No network calls or LLM calls are required.

---

## Ticket 2: Ingestion Integration And Schema Version 2

**Goal:** Integrate ticker resolution into RSS pulling and store resolution metadata without breaking existing parquet files.

**Files:**

- Modify: `research/src/news/puller.py`
- Modify: `research/src/news/storage.py`
- Modify: `research/scripts/pull_news_rss.py`
- Create: `tests/unit/test_news_rss_schema.py`
- Modify: `tests/unit/test_news_ingestion.py`

**Steps:**

- [ ] Step 1: Write failing ingestion tests.

  Test cases:

  - `test_pull_rss_feeds_resolves_generic_feed_with_alias_registry`
  - `test_pull_rss_feeds_keeps_unresolved_generic_row_for_audit`
  - `test_storage_adds_resolution_defaults_for_legacy_frames`
  - `test_source_id_is_unique_per_raw_item_and_ticker_match`
  - `test_raw_source_id_is_shared_across_multi_ticker_expansion`

- [ ] Step 2: Add CLI arguments.

  Required args:

  - `--ticker`, repeatable
  - `--ticker-aliases`, path
  - `--universe-path`, path
  - `--resolve-generic-tickers`
  - `--news-resolution-min-confidence`, default `0.70`
  - `--keep-unresolved-generic-news`, default true

- [ ] Step 3: Update `pull_rss_feeds(...)`.

  Add optional params:

  - `ticker_registry`
  - `resolve_generic_tickers`
  - `keep_unresolved`
  - `min_confidence`

  Existing behavior remains unchanged when `resolve_generic_tickers=False`.

- [ ] Step 4: Update storage columns.

  Add new nullable columns to `NEWS_COLUMNS`. When appending old parquet data, fill missing columns with defaults before selecting columns.

- [ ] Step 5: Bump manifest schema version.

  `news_rss` manifest schema changes from `1` to `2`.

  Add manifest stats:

  - `resolved_row_count`
  - `unresolved_row_count`
  - `ambiguous_row_count`
  - `ticker_count`
  - `resolution_min_confidence`

- [ ] Step 6: Run tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_news_ingestion.py tests\unit\test_news_rss_schema.py -q
  ```

**Ticket DoD:**

- Generic RSS rows can produce ticker-linked rows.
- Unresolved generic rows remain available for coverage/audit.
- Old parquet files can still be read/appended.
- Manifest exposes resolution coverage.

---

## Ticket 3: Data Refresh Wiring

**Goal:** Make normal data refresh jobs pass active-universe tickers and alias config into the RSS puller automatically.

**Files:**

- Modify: `research/src/data_refresh/types.py`
- Modify: `research/src/data_refresh/jobs.py`
- Modify: `research/config/live-refresh.example.json`
- Modify: `research/config/live-refresh.local.json`
- Modify: `tests/unit/test_data_refresh_batch.py`
- Modify: `tests/unit/test_data_refresh_live_config.py`

**Steps:**

- [ ] Step 1: Add config fields.

  Fields:

  - `news_ticker_aliases_path`
  - `news_resolve_generic_tickers`
  - `news_resolution_min_confidence`
  - `news_keep_unresolved_generic`

- [ ] Step 2: Write failing job tests.

  Test cases:

  - `test_news_job_passes_alias_registry_and_active_tickers`
  - `test_news_job_can_disable_generic_resolution`
  - `test_news_job_blocks_when_alias_file_missing_and_resolution_enabled`
  - `test_live_refresh_config_loads_news_resolution_settings`

- [ ] Step 3: Update `_news_job`.

  Command must include:

  - `--resolve-generic-tickers` when enabled
  - `--ticker-aliases <path>`
  - active/configured `--ticker` values
  - min confidence and keep-unresolved flags

  If config tickers are empty, use the same active-universe lookup pattern already used by scheduler jobs.

- [ ] Step 4: Add example config values.

  `live-refresh.example.json` should show the settings without requiring local secrets.

- [ ] Step 5: Run tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_data_refresh_batch.py tests\unit\test_data_refresh_live_config.py -q
  ```

**Ticket DoD:**

- News refresh automatically resolves generic RSS against the active universe.
- Missing alias config is visible as a blocked reason, not silent zero enrichment.
- Resolution can be disabled intentionally.

---

## Ticket 4: PIT Loader And News Signal Weighting

**Goal:** Ensure ticker-specific signals consume only validated ticker-linked news and weight sentiment by ticker-match confidence.

**Files:**

- Modify: `research/src/pit/forward_views.py`
- Modify: `research/src/signals/news.py`
- Modify: `tests/unit/test_news_ingestion.py`
- Modify: `tests/unit/test_news_signal.py`

**Steps:**

- [ ] Step 1: Write failing PIT/signal tests.

  Test cases:

  - `test_pit_loader_excludes_unresolved_news_when_ticker_filter_is_used`
  - `test_news_signal_ignores_ambiguous_news_rows`
  - `test_news_signal_requires_min_resolution_confidence`
  - `test_news_sentiment_is_weighted_by_match_confidence`
  - `test_news_signal_keeps_source_count_by_unique_feed_or_url`

- [ ] Step 2: Update PIT filtering.

  When tickers are provided, include rows where:

  - `ticker` is in requested tickers
  - `ticker_match_status` is `resolved` or `feed_ticker`, or missing because it is a legacy ticker-specific row

- [ ] Step 3: Update `signals.news`.

  - read `ticker_match_confidence`, default `1.0` for legacy rows
  - ignore rows below `0.70`
  - compute weighted sentiment rate
  - include `weighted_headline_count` or `match_confidence_avg` for evidence display

- [ ] Step 4: Run tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_news_ingestion.py tests\unit\test_news_signal.py -q
  ```

**Ticket DoD:**

- Unresolved and ambiguous headlines do not move ticker scores.
- Resolved generic RSS contributes to ticker-specific news.
- Coverage-heavy tickers do not dominate through raw count.
- Evidence rows can explain match confidence.

---

## Ticket 5: Dashboard And Candidate Evidence Presentation

**Goal:** Show operators whether generic RSS is being resolved and why a headline was attached to a ticker.

**Files:**

- Modify: `src/agency/runtime/data_load_status.py`
- Modify: `src/agency/views/_shared.py`
- Modify: `src/agency/views/candidates.py`
- Modify: `src/agency/templates/candidate_detail.html`
- Modify: `tests/unit/test_data_load_status.py`
- Modify: `tests/unit/test_fastapi_app.py`

**Steps:**

- [ ] Step 1: Write failing UI/view-model tests.

  Test cases:

  - `test_data_load_status_reports_news_resolution_coverage`
  - `test_candidate_news_evidence_shows_match_reason_and_confidence`
  - `test_unresolved_generic_news_is_reported_as_context_not_signal`
  - `test_news_health_copy_names_resolution_gap`

- [ ] Step 2: Add data-health fields.

  Display:

  - generic RSS rows fetched
  - rows resolved to tickers
  - rows unresolved
  - ambiguous rows
  - active tickers with resolved news
  - last RSS fetch time

- [ ] Step 3: Add candidate evidence copy.

  Example:

  `PR Newswire matched AAPL by legal name "Apple Inc." in the headline; confidence 0.88.`

  For unresolved:

  `Generic PRN headline collected but not attached to this ticker because no high-confidence ticker match was found.`

- [ ] Step 4: Run tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_data_load_status.py tests\unit\test_fastapi_app.py -q
  ```

**Ticket DoD:**

- The dashboard tells the user how much generic RSS was resolved.
- Candidate pages explain why a news item belongs to a stock.
- No raw internal status names leak into the primary UI.

---

## Ticket 6: Backfill/Repair Command For Existing RSS Rows

**Goal:** Let us reprocess already collected generic RSS rows without pulling the feeds again.

**Files:**

- Create: `research/scripts/resolve_existing_news_rss.py`
- Create: `tests/unit/test_news_resolution_repair.py`

**Steps:**

- [ ] Step 1: Write failing script tests.

  Test cases:

  - `test_resolve_existing_news_rss_updates_unresolved_generic_rows`
  - `test_resolve_existing_news_rss_is_idempotent`
  - `test_resolve_existing_news_rss_writes_manifest_coverage`

- [ ] Step 2: Implement repair script.

  Required args:

  - `--input`
  - `--output`
  - `--manifest`
  - `--ticker-aliases`
  - `--ticker`
  - `--min-confidence`
  - `--dry-run`

- [ ] Step 3: Add dry-run output.

  Print:

  - raw rows scanned
  - newly resolved rows
  - ambiguous rows
  - unresolved rows
  - top matched tickers

- [ ] Step 4: Run tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_news_resolution_repair.py -q
  ```

**Ticket DoD:**

- Existing RSS history can be resolved safely.
- Repair is idempotent.
- Dry-run gives confidence before writing.

---

## Ticket 7: Live Validation And Sanity Checks

**Goal:** Prove the new generic RSS resolution works on real SEC/PRN feeds and produces sensible evidence.

**Files:**

- Create runtime output only: `research/results/news-rss-resolution-qa-YYYYMMDD-HHMM/`

**Steps:**

- [ ] Step 1: Run targeted tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_news_ticker_resolution.py tests\unit\test_news_ingestion.py tests\unit\test_news_rss_schema.py tests\unit\test_news_signal.py tests\unit\test_data_refresh_batch.py -q
  ```

- [ ] Step 2: Run a dry-run repair on existing news.

  ```powershell
  .\.venv\Scripts\python research\scripts\resolve_existing_news_rss.py --input research\data\parquet\news_rss.parquet --output research\results\news-rss-resolution-qa\resolved-news.parquet --manifest research\results\news-rss-resolution-qa\resolved-news.json --ticker-aliases research\config\news-ticker-aliases.local.json --dry-run
  ```

- [ ] Step 3: Pull current RSS with resolution enabled.

  ```powershell
  .\.venv\Scripts\python research\scripts\pull_news_rss.py --resolve-generic-tickers --ticker-aliases research\config\news-ticker-aliases.local.json --universe-path research\data\parquet\universe_membership.parquet --feed "PRN-Technology,https://www.prnewswire.com/rss/technology-latest-news/technology-latest-news-list.rss" --output research\results\news-rss-resolution-qa\news_rss.parquet --manifest research\results\news-rss-resolution-qa\news_rss.json
  ```

- [ ] Step 4: Sanity review the top 25 resolved rows.

  Required checks:

  - matched ticker is visibly related to title/summary
  - ambiguous ticker words are not attached
  - CIK matches resolve correctly
  - multi-ticker rows make sense
  - confidence/reason is readable

- [ ] Step 5: Run a news signal smoke test against resolved rows.

  Confirm:

  - at least one ticker receives generic RSS evidence when relevant
  - unresolved rows do not score
  - high-confidence official/ticker matches have stronger influence than weak brand matches

**Ticket DoD:**

- Real feed run produces explainable ticker matches.
- Manual spot-check finds no obvious false positives in top resolved rows.
- Dashboard/source health shows resolution coverage.
- News signal output is sensible and not dominated by generic feed volume.

---

## Ticket 8: LLM Disambiguation Backlog Gate

**Goal:** Decide whether to add LLM reasoning for ambiguous generic RSS items after deterministic resolution is proven.

**Do not implement this until Tickets 1-7 pass.**

Candidate design:

- Only consider `ambiguous` rows from current cycle.
- Only run for T0/T1 tickers or top review candidates.
- Max 10 items per cycle.
- Prompt asks whether the headline is materially about each candidate ticker.
- Output must include ticker relevance, direction, confidence, and quoted evidence fragment.
- LLM output never overrides CIK or market-symbol matches.
- LLM output is context-only until backtested.

**Ticket DoD:**

- A written go/no-go recommendation exists after deterministic resolver QA.
- Token budget and operational value are clear.

---

## Final Acceptance Criteria

This gap is fixed when:

- Generic SEC/PRN RSS rows are no longer mostly `ticker=None` dead context.
- Resolved generic RSS rows carry method, confidence, matched text, and reason.
- Unresolved/ambiguous rows remain visible but do not affect ticker scores.
- SEC CIK matches are strong and deterministic.
- Ambiguous symbols like `NOW`, `APP`, and `T` do not false-match as plain words.
- Candidate/detail dashboards explain why a headline belongs to a ticker.
- News signal uses confidence-weighted sentiment.
- Existing subscription-email article analysis remains unchanged.
- Existing data lane methodology is preserved.
- Tests and a real-feed QA report prove the behavior.

## Recommended Execution Order

1. Ticket 1: resolver.
2. Ticket 2: ingestion/schema.
3. Ticket 3: refresh wiring.
4. Ticket 4: PIT/signal scoring.
5. Ticket 5: dashboard/candidate presentation.
6. Ticket 6: existing-row repair.
7. Ticket 7: real-feed QA.
8. Ticket 8 only if deterministic resolution is not enough.

Stop after Ticket 2 for a quick schema review before modifying live refresh jobs.
