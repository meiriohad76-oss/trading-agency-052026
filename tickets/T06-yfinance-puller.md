# T06: yfinance daily OHLCV bulk puller

**Owner:** codex
**Phase:** 1 (research)
**Estimate:** medium (2-6h)
**Dependencies:** T01, T03, T04, T05

## Goal
Pull daily OHLCV data for every ticker that has ever been a member of S&P 100 or QQQ over the research window, store as partitioned parquet, and produce a dataset manifest.

## Context
Daily prices are the foundation for every signal lane. yfinance is the free baseline; Alpaca free can supplement if yfinance is incomplete for specific tickers. Reference: `research-brief.md` §4.1.

## Inputs
- T05's universe membership parquet — gives the full ticker set.
- T03's `instrumented_call` and `Provenanced` types.
- T04's manifest format.

## Outputs
- `research/data/parquet/prices_daily/`: partitioned parquet by `ticker=XXX/year=YYYY/`. Columns:
  - `date: date`
  - `open, high, low, close, adj_close: float64`
  - `volume: int64`
  - `dividend, split_factor: float64`
  - `source: str` ("yfinance")
  - `fetched_at: datetime` (UTC)
- `research/data/manifests/prices_daily.json`
- `research/scripts/pull_yfinance_daily.py`: idempotent puller. Takes `--start`, `--end`, `--tickers` (or default = all from universe). Skips tickers/date-ranges already cached. Logs structured JSON.
- Updated PIT loader: `prices()` method now functional (T04 scaffold becomes real implementation backed by this data).

## Acceptance Criteria
1. Coverage: every ticker that appears in T05's universe membership has price data for every active membership day from `start_date` to `end_date` (or today).
2. Adjusted close handled correctly: yfinance returns split- and dividend-adjusted close; raw OHLC is unadjusted. Store both.
3. Missing data gracefully: if yfinance returns nothing for a ticker (delisted, ticker change), log a warning, write a zero-row file with a sentinel, do NOT fail the whole pull.
4. Re-running the puller is idempotent and incremental: it does NOT re-download dates already on disk unless `--refresh` is passed.
5. The manifest captures: ticker count, date range, total row count, fetch timestamp, source.
6. PIT loader smoke query (`prices(["AAPL", "MSFT"], date(2022,6,15), 30)`) returns a non-empty DataFrame with correct columns.
7. Total disk usage is reasonable on Pi (target: < 5 GB for full universe over 7 years).

## Tests Required
- Unit test for the puller's range-skip logic: given existing files for 2020-Q1, the puller correctly identifies what's missing.
- Integration test in `tests/integration/test_yfinance_puller.py`: pull a small fixture (2 tickers, 1 month), assert files appear in expected paths, assert PIT loader returns them.
- Manual: pull AAPL for 2020-2024, spot-check known dates against Yahoo Finance website.

## Out of Scope
- Intraday bars (separate ticket if needed; daily is sufficient for H1/H4).
- Pre/post-market data (separate ticket — Alpaca-based).
- Options chains (separate ticket).

## Notes for Implementer
- Use the `yfinance` library; pin a version in `pyproject.toml` (`yfinance` is unstable across versions).
- Respect rate limits: parallelism > 4 has historically been flagged. Default to serial; allow `--workers N` flag with a sane max.
- yfinance occasionally returns bad bars (zero volume, NaN price). Filter at write time: a row with all-NaN OHLC is dropped; log how many.
- Use `pyarrow` to write parquet with snappy compression and dictionary-encoded ticker columns.
- For tickers that no longer exist on Yahoo (delisted), document the failure mode in the manifest's "issues" field.
- Wrap each ticker's pull with `instrumented_call` so each row's provenance is captured (source="yfinance", source_tier=`MARKET_DATA`, verification_level=`CONFIRMED`).
