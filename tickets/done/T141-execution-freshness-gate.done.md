# T141: Execution Freshness Gate

## Status
Done.

## What Changed
- The scheduler execution gate checks broker freshness and critical source freshness before paper execution is considered tradable.
- The scheduler now falls back to data-load freshness rows when DB source-health rows are absent, so the dashboard reports the real blocker.

## Verification
- `tests/unit/test_scheduler_work_queue.py`
- `tests/unit/test_fastapi_app.py`

