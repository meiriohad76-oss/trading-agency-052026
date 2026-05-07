# T39: DB-backed runtime status endpoints

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T34

## Goal
Make runtime source-health status read from persistence when available, while preserving
the bootstrap fallback for local development and unavailable databases.

## Context
The dashboard and `/status/data-sources` endpoint currently return a hard-coded bootstrap
payload. T34 added repository helpers, so the route can read real stored source-health
rows without making local no-DB mode brittle.

## Outputs
- Async DB-backed source-health status helper.
- `/status/data-sources` route using the helper.
- Dashboard `/` using the same helper.
- Unit tests for repository-backed, empty, and unavailable-DB fallback behavior.

## Acceptance Criteria
1. Stored source-health payloads are returned when the repository yields rows.
2. Empty repository results fall back to the bootstrap status payload.
3. Missing/unreachable database falls back to the bootstrap status payload.
4. Returned repository payloads are contract-validated before leaving the API layer.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Source monitor jobs.
- Database-backed selection report routes.
- Dashboard candidate lists.
