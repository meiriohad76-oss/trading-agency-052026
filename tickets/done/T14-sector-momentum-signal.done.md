# T14: Sector ETF momentum signal lane

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** medium (2-6h)
**Dependencies:** T04, T08, T10

## Goal
Implement a PIT-safe sector ETF momentum score using the sector and broad-market ETF price data from T08.

## Context
Sector tailwind/pressure is part of the market-regime lane. Before building a full regime engine, H1 needs a small deterministic signal that can rank sector ETFs by recent relative momentum.

## Inputs
- `PITLoader.sector_etfs(as_of, lookback_days)` from T08.
- Signal callable contract from T10.

## Outputs
- `research/src/signals/sector_momentum.py`
  - `sector_momentum_score(as_of, universe, loader, lookback_days=60) -> dict[str, float]`
  - `sector_momentum_frame(as_of, universe, loader, lookback_days=60) -> pandas.DataFrame`
  - columns for start price, end price, total return, SPY excess return, observations, and normalized score.
- Unit tests using a fake PIT loader.

## Acceptance Criteria
1. Uses only `loader.sector_etfs(as_of, lookback_days)`; no raw parquet reads.
2. Missing or incomplete ETF rows do not fail the whole cross-section.
3. Higher sector ETF momentum improves score.
4. Scores are cross-sectionally normalized and deterministic.
5. Output can be passed directly to `WalkForward` for ETF-universe experiments.

## Tests Required
- Unit: score ranking matches a hand-computed sector ETF fixture.
- Unit: incomplete ETF histories are skipped cleanly.
- Unit: returned dict is deterministic and uppercases ETF tickers.

## Out of Scope
- Mapping individual stocks to sector ETFs.
- Full regime labels.
- Constituent breadth.
