# T41: Candidate lifecycle API endpoints

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T38

## Goal
Expose candidate lifecycle timelines through the API.

## Context
Lifecycle events are now contract-valid and persistable. The API needs a read endpoint so
dashboard and detail views can answer why a ticker appeared, changed, or disappeared.

## Outputs
- `src/agency/api/candidates.py`
- App router registration.
- Unit tests for route fallback and repository-backed helper behavior.

## Acceptance Criteria
1. `GET /candidates/{ticker}/timeline` returns lifecycle events for a ticker.
2. Optional `cycle_id` filters the timeline.
3. Missing or unreachable database returns an empty list rather than breaking local dev.
4. Returned events are validated against the `candidate-lifecycle-event` contract.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Dashboard lifecycle detail view.
- Lifecycle write endpoints.
- Engine code that emits lifecycle events.
