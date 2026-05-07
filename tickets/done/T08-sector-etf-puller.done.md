# T08: Sector ETF puller

**Owner:** codex
**Phase:** 1 (research)
**Estimate:** small (< 2h)
**Dependencies:** T06

## Goal
Pull daily OHLCV for the SPDR sector ETFs and broad-market reference ETFs, persisted in the same parquet structure as T06, accessible via the PIT loader's `sector_etfs()` method.

## Context
Sector tailwind/pressure is one of v2's signal lanes (Market Regime Engine). v1's "one-stock Real Estate tailwind" lesson means we need ETF data alongside top-constituent data, never just one. Reference: `v2-plan.md` §7.3, `research-brief.md` §4.1.

## Inputs
- T06's yfinance puller logic — reuse it.
- T04's PIT loader.

## Outputs
- ETF tickers covered:
  - **Sectors (SPDR):** XLK (Tech), XLE (Energy), XLF (Financials), XLV (Healthcare), XLI (Industrials), XLB (Materials), XLY (Consumer Disc.), XLP (Consumer Staples), XLU (Utilities), XLC (Communications), XLRE (Real Estate)
  - **Broad market:** SPY, QQQ, IWM, DIA
- Same parquet location as T06 (`research/data/parquet/prices_daily/ticker=XXX/year=YYYY/`).
- Manifest entry added to `prices_daily.json` indicating these tickers are also covered.
- PIT loader's `sector_etfs(as_of, lookback_days)` method functional.

## Acceptance Criteria
1. All listed ETFs have daily OHLCV from 2019-01-01 to today.
2. PIT loader query `sector_etfs(date(2022,6,15), 60)` returns 60 trading days of data for all listed ETFs.
3. Idempotent re-run.
4. ETF data exists alongside individual ticker data in the same parquet hierarchy (no special-case storage).

## Tests Required
- Unit test: the sector ETF list is fully covered.
- Integration test: PIT loader query returns expected shape and known prices (spot-check XLK on a known date).

## Out of Scope
- ETF holdings or constituent breakdowns (out of scope for Phase 1; we use ETFs as price proxies, not for constituent-level analysis).
- Newer / niche ETFs.

## Notes for Implementer
- This is a small extension of T06; consider implementing as a `--include-etfs` flag on T06's puller rather than a separate script.
- XLC was created in 2018; data starts mid-2018. That's fine for our window.
- XLRE was created in 2015; fine.
