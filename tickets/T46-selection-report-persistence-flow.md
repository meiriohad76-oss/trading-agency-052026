# T46: Selection report persistence flow

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T36, T38, T45

## Goal
Add a service flow that persists a selection report and its matching lifecycle event.

## Context
Runtime repositories can write each payload independently. The selection path needs a
single service-level flow that validates both artifacts and records them in the right
order.

## Outputs
- `src/agency/services/selection_persistence.py`
- Service package exports.
- Unit tests with injected writers.

## Acceptance Criteria
1. Selection reports are validated before persistence.
2. Lifecycle events are validated before persistence.
3. The report writer is called before the lifecycle writer.
4. Deterministic selection can be built and persisted through one helper.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- API write endpoints.
- Database integration tests beyond existing repository coverage.
- Final selection aggregation.
