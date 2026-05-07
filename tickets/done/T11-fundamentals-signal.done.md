# T11: Fundamentals factor signal lane

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** medium (2-6h)
**Dependencies:** T04, T07, T09, T10

## Goal
Implement the first H1 signal generator: a PIT-safe SEC fundamentals factor score for every ticker in the current universe.

## Context
Fundamentals are the highest-quality source tier in v2 because they are official SEC filings. This lane should be simple, deterministic, and explainable before any IC or walk-forward analysis consumes it.

## Inputs
- `PITLoader.fundamentals(ticker, as_of)` from T07.
- Signal callable contract from T10: `signal_fn(as_of, universe, loader) -> dict[ticker, score]`.
- SEC metrics currently exposed by Company Facts: `revenue`, `net_income`, `free_cash_flow`, `total_assets`, `total_liabilities`, and related values when available.

## Outputs
- `research/src/signals/fundamentals.py`
  - `fundamental_score(as_of, universe, loader) -> dict[str, float]`
  - `fundamental_factor_frame(as_of, universe, loader) -> pandas.DataFrame`
  - factor columns for profitability, cash generation, leverage, and composite score.
- Unit tests using a fake PIT loader, including missing metric behavior.

## Acceptance Criteria
1. Uses only `loader.fundamentals(ticker, as_of)`; no raw parquet reads.
2. Missing data for one ticker does not fail the whole cross-section.
3. Composite score is cross-sectionally normalized and deterministic.
4. Higher net margin and FCF margin improve score; higher leverage lowers score.
5. Output can be passed directly to `WalkForward` as a `signal_fn`.

## Tests Required
- Unit: score ranking matches a hand-computed fixture.
- Unit: missing metrics/tickers are skipped cleanly.
- Unit: returned dict is deterministic and uppercases tickers.

## Out of Scope
- IC notebook generation.
- Threshold tuning.
- Valuation factors that require market cap or enterprise value.
