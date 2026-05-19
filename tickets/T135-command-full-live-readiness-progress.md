# T135: Command Dashboard Full-Live Readiness Progress

**Owner:** codex
**Phase:** 4 (operate)
**Estimate:** medium
**Dependencies:** T87, T88, T98, T119, T124
**Status:** backlog

## Goal
Expose the full-live data-readiness and refresh-progress state directly on the
Command dashboard so the user can tell whether the agency is ready to run a full
paper-live cycle.

## Context
The current `/status/operational-readiness` gate says whether the latest runtime
cycle is usable, but the user also needs live-refresh progress before a cycle is
run: active-universe coverage, currently running dataset batch, provider usage,
email ingest status, and whether any required data lane is incomplete.

## Outputs
- Command dashboard panel named `Full-Live Readiness`.
- Machine endpoint, for example `/status/full-live-readiness`.
- Dataset coverage rows for at least:
  - `prices_daily`
  - `sec_company_facts`
  - `sec_form4`
  - `sec_13f`
  - `news_rss`
  - `subscription_emails`
  - `stock_trades`
- Active refresh status:
  - running dataset
  - running batch id
  - completed/planned/deferred ticker counts
  - ETA when available
  - stuck/long-running warning
- Provider usage status:
  - Massive/Polygon request usage and local guardrail state
  - SEC refresh state
  - Gmail/email ingest state
- Clear readiness verdict:
  - `ready_for_full_live_cycle`
  - `ready_with_partial_lanes`
  - `loading`
  - `blocked`

## Acceptance Criteria
1. Command dashboard shows one concise readiness card before the review queue.
2. User can see exactly which dataset is still loading and what remains.
3. User can see whether running a full-universe runtime cycle is recommended now.
4. Provider request usage is shown without exposing API keys.
5. Long-running or interrupted batches are called out as warnings.
6. Endpoint JSON is covered by unit tests.
7. Dashboard rendering is covered by FastAPI/e2e smoke tests.

## Tests Required
- Unit tests for coverage summarization.
- Unit tests for active batch detection.
- Unit tests for readiness verdict selection.
- FastAPI test for `/status/full-live-readiness`.
- Dashboard smoke test confirming the panel renders.

## Out of Scope
- Automatic provider retry scheduling.
- Changing signal weights.
- Submitting paper orders.
