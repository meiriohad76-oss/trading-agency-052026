# T15: Abnormal volume signal lane

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** medium (2-6h)
**Dependencies:** T04, T06, T10

## Goal
Implement a PIT-safe abnormal-volume score from daily OHLCV bars.

## Context
Abnormal volume is inferred from market bars, not a confirmed standalone event. H1 should test it as a directional pressure feature while preserving the distinction between confirmed data and inferred signal.

## Inputs
- `PITLoader.prices(tickers, as_of, lookback_days)` from T06.
- Signal callable contract from T10.

## Outputs
- `research/src/signals/abnormal_volume.py`
  - `abnormal_volume_score(as_of, universe, loader, lookback_days=60) -> dict[str, float]`
  - `abnormal_volume_frame(as_of, universe, loader, lookback_days=60) -> pandas.DataFrame`
  - columns for latest volume, baseline volume, volume ratio, latest return, signed volume pressure, and normalized score.
- Unit tests using a fake PIT loader.

## Acceptance Criteria
1. Uses only `loader.prices(tickers, as_of, lookback_days)`; no raw parquet reads.
2. Missing data for one ticker does not fail the whole cross-section.
3. High volume on up moves improves score; high volume on down moves lowers score.
4. Scores are cross-sectionally normalized and deterministic.
5. Output can be passed directly to `WalkForward` as a `signal_fn`.

## Tests Required
- Unit: score ranking matches an up-volume/neutral/down-volume fixture.
- Unit: incomplete histories are skipped cleanly.
- Unit: returned dict is deterministic and uppercases tickers.

## Out of Scope
- Intraday volume velocity.
- Multi-source corroboration.
- Actionability decisions.
