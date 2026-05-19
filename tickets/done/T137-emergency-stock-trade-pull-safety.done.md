# T137: Emergency Stock-Trade Pull Safety

## Status
Done.

## What Changed
- Added a shared stock-trade safety guard for direct Massive trade pulls.
- Direct live refreshes now reject broad historical windows and excessive ticker-day requests.
- The batch runner and direct pull script both fail before any provider call if the request belongs in the resumable backfill path.

## Verification
- `tests/unit/test_data_refresh_batch.py`
- `tests/unit/test_massive_stock_trade_backfill.py`

