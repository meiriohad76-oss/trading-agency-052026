# T36: Selection report repository helpers

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T35

## Goal
Add runtime helpers to persist validated selection-report payloads.

## Context
The `selection_reports` table exists. Final selection output should be validated against
the JSON Schema contract before being converted to database values or upserted.

## Outputs
- `src/agency/runtime/selection_reports.py`
- Shared runtime coercion helpers.
- Unit tests for row conversion, invalid payload rejection, and Postgres upsert generation.

## Acceptance Criteria
1. Payloads are validated against `selection-report` before persistence.
2. `cycle_id`, `ticker`, and `as_of` are used as the upsert conflict target.
3. Timestamp and numeric fields are converted to database-friendly values.
4. Recent-report query helper orders by generated time descending.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Final selection engine.
- API/dashboard routes reading reports.
- Candidate lifecycle tables.
