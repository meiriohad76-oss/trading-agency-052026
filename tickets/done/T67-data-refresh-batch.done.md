# T67: Data refresh batch

**Owner:** codex
**Phase:** 1 (research)
**Status:** done

## Goal

Add a repeatable local batch for refreshing PIT research data sources before running
the T66 empirical result runner.

## Delivered

- Added `research/scripts/run_data_refresh_batch.py`.
- Added `research/src/data_refresh/` orchestration for prices, SEC company facts,
  SEC Form 4, SEC 13F, RSS, and options chains.
- Added dry-run and per-source blocked/planned/passed/failed status output.
- Committed `research/results/t67/data-refresh-status.*` from a dry run.
- Added unit tests with injected command runners so CI never calls live APIs.

## Acceptance Notes

1. The batch records missing live configuration instead of silently skipping sources.
2. Raw/parquet refresh outputs remain local-only and gitignored.
3. Live SEC refreshes require `SEC_USER_AGENT`; RSS and 13F refreshes require explicit
   feed, filer CIK, and CUSIP-map inputs.
