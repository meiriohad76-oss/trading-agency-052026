# User Process Flow Audit - 2026-05-25/26

## Scope

This audit targets operator workflow behavior, not only route availability:

- Command dashboard to candidate review to execution preview focus persistence.
- All 168 current execution-preview tickers through the live status contract.
- Ticker-focused execution preview rendering for the full active execution universe.
- Candidate detail light-shell rendering for a live ticker sample.
- Core V3 dashboard routes, forbidden old/test UX residue, and route budgets.

## Current Verified Results

| Check | Result | Evidence |
| --- | --- | --- |
| User-process audit harness tests | PASS | `.\.venv\Scripts\python -m pytest tests/unit/test_ops_scripts.py -k "user_process_audit" -q` |
| Broad unit/UX regression suite | PASS | `.\.venv\Scripts\python -m pytest tests/unit/test_fastapi_app.py tests/unit/test_ops_scripts.py tests/unit/test_ux_audit_implementation.py tests/unit/test_cockpit_preferences.py -q` -> 288 passed |
| V3/paper promotion targeted suite | PASS | `.\.venv\Scripts\python -m pytest tests/unit/test_v3_ux_rollout.py tests/unit/test_paper_trade_promotion.py -q` -> 27 passed |
| Ruff | PASS | `.\.venv\Scripts\python -m ruff check .` -> All checks passed |
| Full focused execution audit | PASS | 168/168 focused execution routes, 168/168 status contracts, failure_count 0 |
| Candidate sample process audit | PASS | 24 candidate light pages, 12 focused execution routes, 12 final-selection focus routes, failure_count 0 |

Report snapshots:

- `research/results/user-process-flow-audit/final-all-focus-20260526/user-process-flow-audit.json`
- `research/results/user-process-flow-audit/final-candidate-sample-20260526/user-process-flow-audit.json`

## Confirmed Fixes

- Selected ticker focus is preserved from Command and candidate review into `/execution-preview?ticker=TICKER`.
- Focused execution pages render the selected ticker card before any generic queue and hide the long queue by default.
- Focused final-selection pages render only the requested candidate state plus a clear path back to the full queue.
- Candidate `?audit=light` pages no longer rebuild rich signal evidence, call broker status, or reload heavy data-health state for every ticker.
- The generic execution preview is a bounded triage page instead of a long 168-stock detail dump.
- User-facing operator copy is sanitized away from the old "stale" wording and toward "needs refresh" language.
- The audit harness now fails explicitly when `/status/execution-preview` is unavailable and uses `Connection: close` for large localhost page checks.

## Remaining Watch Items

- Normal, non-light candidate detail still renders rich evidence and can be expensive by design.
- The full app server should be restarted with the scheduler setting appropriate for the operating mode after QA-only audits.
- If future UX work expands signal/candidate detail again, rerun both final audit profiles before claiming readiness.
