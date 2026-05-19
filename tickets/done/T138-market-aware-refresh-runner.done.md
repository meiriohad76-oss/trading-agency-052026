# T138: Market-Aware Refresh Runner

## Status
Done.

## What Changed
- `run_data_refresh_batch.py` is market-aware by default.
- Active-session runs select only datasets appropriate for the current market phase.
- Implicit universe refreshes now filter membership by `start_date` / `end_date`, so live jobs do not pull historical index members that are no longer active.
- Heavy baseline repair is deferred unless the operator explicitly runs with `--no-market-aware`.

## Verification
- `tests/unit/test_market_batching.py`
- `tests/unit/test_incremental_refresh_plan.py`
- `tests/unit/test_ops_scripts.py`
