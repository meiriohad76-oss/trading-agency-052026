# T20: Options-chain forward collector and signal

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** medium (2-6h)
**Dependencies:** T10

## Goal
Start forward-only yfinance options-chain collection and add a basic call/put pressure signal.

## Context
Free yfinance options data is not a historical PIT source. The collector stores snapshots prospectively so later research can test whether options features add value.

## Outputs
- `research/src/options/` puller, normalizer, storage utilities.
- `research/scripts/pull_yfinance_options.py`.
- `PITLoader.option_chains(tickers, as_of, lookback_days)`.
- `research/src/signals/options_flow.py`.

## Acceptance Criteria
1. Snapshots are persisted with provenance and `timestamp_as_of`.
2. Loader returns only snapshots known by `as_of`.
3. Signal uses only `loader.option_chains(...)`.
4. Higher call-volume pressure improves score; put-volume pressure lowers score.

## Tests Required
- Unit: options normalizer and puller write expected columns.
- Unit: PIT loader filters option snapshots point-in-time.
- Unit: signal ranking fixture.

## Out of Scope
- Historical options backfill.
- Polygon subscription.
- Options execution.
