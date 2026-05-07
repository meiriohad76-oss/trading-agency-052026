# T35: Selection report persistence schema

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T29, T33

## Goal
Add the database table for persisted final selection reports.

## Context
The selection report contract exists, but final selection outputs need a durable audit
destination before the dashboard and lifecycle views can show real candidates.

## Outputs
- SQLAlchemy metadata for `selection_reports`.
- Alembic migration `0003_selection_reports`.
- Unit tests for table metadata and migration linkage.

## Acceptance Criteria
1. Table is keyed by `cycle_id`, `ticker`, and `as_of`.
2. Table stores generated time, final action, final conviction, and raw contract payload.
3. Final conviction is constrained to `[0, 1]`.
4. Migration follows `0002_data_source_health`.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Selection report repository helpers.
- Candidate lifecycle tables.
- Final selection engine implementation.
