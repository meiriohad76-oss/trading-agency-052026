# T05: Universe history reconstruction

**Owner:** codex
**Phase:** 1 (research)
**Estimate:** medium (2-6h)
**Dependencies:** T01, T04

## Goal
Produce a parquet file `research/data/parquet/universe_membership.parquet` listing every (ticker, start_date, end_date) tuple for membership in S&P 100 and QQQ from 2019-01-01 to today, plus a manifest documenting the source.

## Context
Survivorship bias is one of the most common ways quant backtests lie. Without historical universe membership, a backtest run today over 2020 silently uses 2026's S&P 100, which includes survivors and excludes failures. Reference: `research-brief.md` §6 (Risks → Survivorship bias).

## Inputs
- Public sources for S&P 100 historical changes (Wikipedia maintains a changelog; the official S&P website also publishes additions/removals).
- Public sources for NASDAQ-100 / QQQ historical changes.
- T04's manifest schema for documenting the dataset.

## Outputs
- `research/data/parquet/universe_membership.parquet` with columns:
  - `ticker: str` (symbol)
  - `index_name: str` ("SP100" or "NASDAQ100")
  - `start_date: date` (inclusive — first day of membership)
  - `end_date: date | NULL` (exclusive — first day of NON-membership; NULL if currently a member)
  - `as_of_source: str` (URL or description of the source row)
  - `source_fetched_at: datetime` (UTC)
- `research/data/manifests/universe_membership.json`: dataset manifest (source URLs, fetch timestamp, row count, schema version, checksum).
- `research/scripts/build_universe_membership.py`: idempotent script that rebuilds the parquet from the upstream sources. Re-runnable; produces deterministic output for the same source state.
- `research/scripts/data/universe_membership/`: downloaded source files (HTML/CSV) committed to the repo so reconstruction is reproducible without network access.

## Acceptance Criteria
1. The parquet covers at minimum 2019-01-01 to today.
2. For SP100: at least 100 active members on any given date (the index is occasionally 99-101 due to corporate actions; tolerate ±2).
3. For QQQ/NASDAQ100: at least 95 active members on any given date.
4. `start_date < end_date` for every closed row.
5. No overlapping membership rows for the same (ticker, index_name).
6. Spot-check fixtures pass:
   - AAPL is a member of both indices on 2022-06-15.
   - A stock that was removed from SP100 in 2021 (pick one and document) is NOT in membership on 2022-01-01.
   - A stock added to QQQ in 2024 (pick one and document) is NOT a member on 2023-12-01.
7. Re-running `build_universe_membership.py` produces a byte-identical parquet (modulo `source_fetched_at`).
8. The PIT loader's `universe_members(as_of)` works on this parquet correctly.

## Tests Required
- Unit tests in `tests/unit/test_universe_membership.py`: load the parquet, assert the spot-check fixtures.
- Integration test: query via `PITLoader.universe_members(2022-06-15)` and assert size and known members.
- Manual: spot-check a dozen historical changes against published S&P / Nasdaq announcements.

## Out of Scope
- Mid-day intraday membership (use end-of-day boundaries).
- Other indices (S&P 500, Russell). If the universe revision question (Q10) is later resolved to expand, this script extends.
- Corporate actions other than membership changes (splits, mergers — handled separately if they affect ticker mapping).

## Notes for Implementer
- Wikipedia's "Historical components of the S&P 100" article is reasonably maintained and a fine starting source. NOT authoritative — cross-check additions/removals against S&P press releases where possible.
- For NASDAQ-100, Wikipedia also maintains a list. NASDAQ publishes annual rebalances.
- Use `pandas` for the parsing (pyarrow under the hood), write parquet with snappy compression.
- When a ticker changes (e.g., FB → META in 2022), maintain TWO rows: FB's membership ends 2022-06-09, META's membership starts 2022-06-09. Both rows exist; downstream consumers see the rename naturally.
- Commit the raw HTML/CSV source files to `research/scripts/data/universe_membership/` so the build is reproducible offline.
