# T40: Selection report API endpoints

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T36

## Goal
Expose persisted selection reports through API endpoints.

## Context
Selection report persistence exists, but users and dashboard code need read endpoints
before candidate surfaces can be built.

## Outputs
- `src/agency/api/reports.py`
- App router registration.
- Repository ticker filtering.
- Unit tests for route fallback and repository-backed helper behavior.

## Acceptance Criteria
1. `GET /reports/selection` returns recent selection reports.
2. `GET /reports/selection/{ticker}` filters reports by ticker.
3. Missing or unreachable database returns an empty list rather than breaking local dev.
4. Returned reports are validated against the `selection-report` contract.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Candidate lifecycle API.
- Dashboard candidate list.
- Selection report write endpoints.
