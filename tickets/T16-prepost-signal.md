# T16: Pre/post-market signal lane

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** medium (2-6h)
**Dependencies:** T10

## Goal
Implement the pre/post-market gap-and-volume signal contract so the lane is ready when intraday extended-hours data lands.

## Context
The plan names pre/post-market price and volume as an inferred signal lane. The current repo does not yet include the data puller, so this ticket implements the signal over a loader protocol and validates it with fake PIT data.

## Inputs
- Future loader method: `prepost_bars(tickers, as_of, lookback_days)`.
- Signal callable contract from T10.

## Outputs
- `research/src/signals/prepost.py`
  - `prepost_gap_score(as_of, universe, loader, lookback_days=10) -> dict[str, float]`
  - `prepost_gap_frame(as_of, universe, loader, lookback_days=10) -> pandas.DataFrame`
  - columns for gap return, pre/post volume, relative volume, pressure, and normalized score.
- Scoped walk-forward loader proxy for `prepost_bars`.
- Unit tests using a fake PIT loader.

## Acceptance Criteria
1. Uses only `loader.prepost_bars(tickers, as_of, lookback_days)`; no raw parquet reads.
2. Missing or incomplete rows do not fail the whole cross-section.
3. Positive extended-hours gaps with volume improve score; negative gaps lower score.
4. Scores are cross-sectionally normalized and deterministic.
5. Output can be passed directly to `WalkForward` once a real loader method exists.

## Tests Required
- Unit: score ranking matches a positive/neutral/negative gap fixture.
- Unit: missing or incomplete rows are skipped cleanly.
- Unit: returned dict is deterministic, uppercases tickers, and forwards lookback.

## Out of Scope
- The actual pre/post-market data puller.
- Alpaca/yfinance provider selection.
- Options-chain features.
