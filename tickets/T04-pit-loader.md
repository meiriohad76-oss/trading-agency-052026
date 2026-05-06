# T04: PIT (point-in-time) data loader scaffold

**Owner:** claude-code
**Phase:** 1 (research)
**Estimate:** large (6h+)
**Dependencies:** T01, T03

## Goal
Implement the single canonical entry point for "what did we know about ticker T as of date D?" Every notebook, every backtest, every signal generator reads through this loader. No code anywhere else may read raw parquet files directly.

## Context
PIT discipline (non-negotiable N8 in `v2-plan.md`) is the most important infra decision in v2. Without it, backtests lie. The loader is the enforcement point: by routing all reads through one module, we make PIT correctness a property of the system, not a property of every notebook author's discipline.

## Inputs
- `v2-plan.md` N8 (PIT discipline) and §4.4 (PIT data store description).
- `research-brief.md` §4 (Data Sourcing Plan) for which datasets exist and their PIT properties.
- T03's Provenance type.

## Outputs
- `research/src/pit/loader.py`: the `PITLoader` class with these public methods:
  - `prices(tickers: list[str], as_of: date, lookback_days: int) -> DataFrame` — daily OHLCV for the universe up to and including `as_of`. PIT-correct.
  - `fundamentals(ticker: str, as_of: date) -> Provenanced[dict]` — most recent SEC company facts as of `as_of`.
  - `insider_transactions(ticker: str, as_of: date, lookback_days: int) -> list[Provenanced[dict]]` — Form 4 events filed on or before `as_of`.
  - `institutional_holdings(ticker: str, as_of: date) -> Provenanced[dict]` — most recent 13F-derived holdings as of `as_of`.
  - `universe_members(as_of: date) -> set[str]` — historical S&P 100 + QQQ members on `as_of`.
  - `sector_etfs(as_of: date, lookback_days: int) -> DataFrame` — sector ETF prices.
- `research/src/pit/exceptions.py`: typed exceptions (`DataNotAvailableAt`, `LookaheadRequested`).
- `research/src/pit/manifest.py`: reads manifest files in `research/data/manifests/` and validates dataset readiness. The loader refuses to operate if manifests are missing or stale.
- A guard mechanism: any code that imports from `research/data/parquet/` directly (bypassing the loader) is detected and fails a CI check. Implement as a custom ruff rule, an import-linter contract, or a simple grep-based pre-commit check — pick the simplest that works.

## Acceptance Criteria
1. The loader returns data only with `timestamp_as_of <= as_of`. Verified by tests.
2. Calling any method with `as_of` in the future raises `LookaheadRequested`.
3. Calling any method when the underlying parquet is missing raises `DataNotAvailableAt` with a clear message.
4. All returned values are wrapped in or include `Provenance`.
5. Universe membership at `2022-06-15` correctly reflects S&P 100 membership on that date (test against a known fixture).
6. SEC fundamentals as of `2022-12-31` for AAPL return the data filed on or before that date — never the data revised in 2023.
7. The bypass-prevention guard fires when test code imports parquet directly.
8. Loader is performant enough to back a full universe daily backtest on a Pi (target: < 30s for one full universe-day query on cached parquet).

## Tests Required
- Unit tests in `tests/unit/test_pit_loader.py`:
  - PIT correctness on each method: feed a known fixture, assert returned data respects `as_of`.
  - Lookahead rejection: future `as_of` raises.
  - Missing data: stripped fixture raises `DataNotAvailableAt`.
  - Universe membership at known boundary dates (e.g., a stock added to S&P 100 on 2023-03-15 is NOT in the universe on 2023-03-14 but IS on 2023-03-15).
- Integration tests in `tests/integration/test_pit_loader_real_data.py`:
  - Once T05/T06/T07 land their data, run a smoke query and verify shape.
- Bypass guard test in `tests/unit/test_pit_bypass_guard.py`: synthesize a file that violates the rule, run the guard, assert it fires.

## Out of Scope
- The actual parquet file population (T05, T06, T07).
- Backtest harness (T10).
- Caching layer beyond what parquet's columnar storage provides natively.

## Notes for Implementer
- Use `polars` (or `duckdb` over parquet) for queries — both handle PIT predicates efficiently. Prefer `polars` for in-process work; `duckdb` for ad-hoc SQL.
- The loader should NOT cache results in a shared dict — concurrent backtests will fight. If caching is needed, scope it per-instance or use a proper LRU.
- Universe membership data is small (a few hundred rows per month over a few years). Keep it as a single parquet file with `start_date`, `end_date`, `ticker` columns; query as `start_date <= as_of < end_date`.
- For SEC fundamentals: the company facts API returns multiple values per metric across filings. The PIT-correct value at `as_of` is the most recent filing where `filing_date <= as_of`. Store filings indexed by ticker + filing_date; query takes max(filing_date <= as_of).
- Document explicitly in the docstring what each method returns and how PIT is enforced.
- This module gets review by the human and full test coverage. Don't ship it green-but-thin.
