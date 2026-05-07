# T13: Institutional holdings signal lane

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** medium (2-6h)
**Dependencies:** T04, T07, T10

## Goal
Implement a PIT-safe SEC 13F institutional flow score for every ticker in the current universe.

## Context
13F data is official but lagged. The first H1 version should test whether institutional accumulation or distribution, as known after filing, has measurable forward-return edge.

## Inputs
- `PITLoader.institutional_holdings(ticker, as_of)` from T07.
- Signal callable contract from T10: `signal_fn(as_of, universe, loader) -> dict[ticker, score]`.

## Outputs
- `research/src/signals/institutional.py`
  - `institutional_score(as_of, universe, loader) -> dict[str, float]`
  - `institutional_factor_frame(as_of, universe, loader) -> pandas.DataFrame`
  - factor columns for holder count, total shares held, quarterly change, change ratio, and normalized score.
- Unit tests using a fake PIT loader.

## Acceptance Criteria
1. Uses only `loader.institutional_holdings(ticker, as_of)`; no raw parquet reads.
2. Missing data for one ticker does not fail the whole cross-section.
3. Higher quarterly accumulation improves score; distribution lowers score.
4. Scores are cross-sectionally normalized and deterministic.
5. Output can be passed directly to `WalkForward` as a `signal_fn`.

## Tests Required
- Unit: score ranking matches an accumulation/neutral/distribution fixture.
- Unit: missing or incomplete ticker payloads are skipped cleanly.
- Unit: returned dict is deterministic and uppercases tickers.

## Out of Scope
- Fund-level quality weighting.
- Float-adjusted ownership percentage.
- Combining 13F data with market cap.
