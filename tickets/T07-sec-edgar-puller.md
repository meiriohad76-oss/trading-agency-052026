# T07: SEC EDGAR puller suite (Company Facts, Form 4, 13F)

**Owner:** codex
**Phase:** 1 (research)
**Estimate:** large (6h+)
**Dependencies:** T01, T03, T04, T05

## Goal
Implement three coordinated pullers against SEC EDGAR — Company Facts (fundamentals), Form 4 (insider transactions), and 13F (institutional holdings) — sharing rate-limit and auth logic, persisting to partitioned parquet, with manifests and PIT-correct ingestion.

## Context
SEC EDGAR is the foundation of v2's trustworthy data layer: official, free, ToS-clean, and PIT-correct by filing date. Reference: `v2-plan.md` §6.1, `research-brief.md` §4.1.

## Inputs
- SEC EDGAR APIs:
  - Company Facts: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`
  - Submissions: `https://data.sec.gov/submissions/CIK{cik}.json`
  - Form 4 / 13F: `https://www.sec.gov/cgi-bin/browse-edgar` (HTML; XBRL filings are also available)
- T05's universe → ticker → CIK mapping required (SEC EDGAR's company tickers JSON: `https://www.sec.gov/files/company_tickers.json`).
- T03's `instrumented_call` and `Provenanced` types.

## Outputs
- `research/src/sec/client.py`: shared HTTP client with required `User-Agent` header (SEC requires it: `"Name email@example.com"`), 10-req-per-second rate limit, retry-with-backoff on 429.
- `research/src/sec/company_facts.py`: pull and parse Company Facts JSON for the universe.
- `research/src/sec/form4.py`: pull and parse Form 4 (insider transactions).
- `research/src/sec/form13f.py`: pull and parse 13F (institutional holdings; this returns *funds'* holdings, so we'll need to invert: per-ticker, who holds it).
- `research/data/parquet/sec_company_facts/`: partitioned by ticker. One row per (ticker, metric, period). Captures revenue, net_income, FCF, shares_outstanding, total_assets, total_liabilities, etc.
- `research/data/parquet/sec_form4/`: partitioned by ticker. Columns: ticker, filer_cik, transaction_date, filing_date, transaction_type, shares, price, ownership_after.
- `research/data/parquet/sec_13f/`: partitioned by quarter. Columns: ticker, filer_cik, filer_name, quarter_end_date, filing_date, shares_held, change_from_prev_quarter.
- `research/data/manifests/sec_company_facts.json`, `sec_form4.json`, `sec_13f.json`.
- `research/scripts/pull_sec_*.py`: one entry-point script per dataset, all idempotent and incremental.
- PIT loader's `fundamentals()`, `insider_transactions()`, `institutional_holdings()` become functional.

## Acceptance Criteria
1. Coverage: every universe ticker with a CIK has fundamentals from at least 2019-Q1 to most recent filing.
2. Form 4 captures all transactions for universe tickers in the research window. Spot-check: a known insider buy on a known date (e.g., a public CEO purchase) appears in the data with correct details.
3. 13F captures the major funds' holdings; for each ticker, we can answer "what was institutional ownership change last quarter?"
4. SEC `User-Agent` is properly set; no rate-limit violations during a full pull (verified by no 429s in logs).
5. Each puller is incremental: re-running doesn't re-download already-cached filings.
6. PIT loader spot-checks pass:
   - `fundamentals("AAPL", date(2022,12,31))` returns data filed on or before that date.
   - `insider_transactions("AAPL", date(2023,1,15), 90)` returns Form 4 filings only with `filing_date <= 2023-01-15`.
7. Failed CIK lookups (e.g., for a ticker without SEC coverage) are logged but don't crash the pull.

## Tests Required
- Unit tests for parsing: feed a known SEC JSON fixture, assert parsed rows match expected.
- Unit test for ticker→CIK mapping: edge cases (multi-class shares like GOOGL/GOOG, ticker changes).
- Integration test: pull a single ticker (e.g., AAPL) end-to-end, query via PIT loader, assert known historical values (e.g., AAPL Q4 2022 revenue ≈ $90B).
- Rate-limit test: simulated burst respects the 10 req/s ceiling.
- Manual: spot-check a Form 4 entry against the SEC EDGAR website.

## Out of Scope
- Other SEC forms (8-K, 10-K full text, etc.) — out of scope for Phase 1.
- Real-time filings stream — Phase 1 uses batch pulls.
- XBRL-vs-JSON handling: use the JSON Company Facts API exclusively for fundamentals; avoid raw XBRL parsing.

## Notes for Implementer
- SEC EDGAR's `User-Agent` requirement is strictly enforced; missing or generic UA returns 403. Read https://www.sec.gov/os/accessing-edgar-data before implementing.
- Rate limit is "no more than 10 requests per second" — keep below it (use 8 r/s to be safe).
- Company Facts JSON is large (multi-MB per company). Cache raw responses to `research/data/raw/sec/companyfacts/CIK{cik}.json` for reproducibility.
- For 13F, the data structure is per-FILER (the fund), listing all their holdings. To get per-ticker views, you'll need to invert: collect all 13Fs in a quarter, then for each ticker count holdings. This is a meaningful chunk of work — call it out in PR description.
- Use `httpx` for the HTTP client (async-ready, modern). Pin version.
- Wrap calls with `instrumented_call`; `timestamp_as_of = filing_date` for fundamentals/insider/institutional values, NOT the fetch time.
