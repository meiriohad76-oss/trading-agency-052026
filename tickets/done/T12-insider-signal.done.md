# T12: Insider transactions signal lane

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** medium (2-6h)
**Dependencies:** T04, T07, T10

## Goal
Implement a PIT-safe Form 4 insider transaction score for every ticker in the current universe.

## Context
Open-market insider buying can be a useful confirmed-source signal, while insider selling can be informative but noisy. The first version should be deterministic and simple enough for H1 IC testing.

## Inputs
- `PITLoader.insider_transactions(ticker, as_of, lookback_days)` from T07.
- Signal callable contract from T10: `signal_fn(as_of, universe, loader) -> dict[ticker, score]`.

## Outputs
- `research/src/signals/insider.py`
  - `insider_score(as_of, universe, loader, lookback_days=90) -> dict[str, float]`
  - `insider_factor_frame(as_of, universe, loader, lookback_days=90) -> pandas.DataFrame`
  - factor columns for buy value, sell value, net transaction value, transaction count, filer count, and normalized score.
- Unit tests using a fake PIT loader.
- Walk-forward scoped loader support for PIT signal methods beyond prices.

## Acceptance Criteria
1. Uses only `loader.insider_transactions(ticker, as_of, lookback_days)`; no raw parquet reads.
2. Missing data for one ticker does not fail the whole cross-section.
3. Open-market purchase code `P` increases score; sale code `S` lowers score.
4. Non-directional or incomplete transactions are ignored.
5. Composite score is cross-sectionally normalized and deterministic.
6. Output can be passed directly to `WalkForward` as a `signal_fn`.

## Tests Required
- Unit: score ranking matches a hand-computed purchase/neutral/sale fixture.
- Unit: missing data and incomplete rows are skipped cleanly.
- Unit: returned dict is deterministic, uppercases tickers, and forwards lookback.
- Unit: signal runs through `WalkForward` with the scoped PIT loader.

## Out of Scope
- Insider role weighting.
- 10b5-1 plan parsing.
- Separating buys by officer/director class.
