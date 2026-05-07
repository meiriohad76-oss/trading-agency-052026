# T34: Source health repository helpers

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T33

## Goal
Add runtime helpers to persist validated data-source health payloads.

## Context
T33 created the table. Runtime source monitors and API/dashboard routes need one small
repository layer that validates payloads against the contract and performs deterministic
upserts keyed by source.

## Outputs
- `src/agency/runtime/source_health.py`
- Unit tests for row conversion, contract rejection, and Postgres upsert generation.

## Acceptance Criteria
1. Payloads are validated against `data-source-health` before persistence.
2. ISO timestamps are converted to timezone-aware Python datetimes for database writes.
3. Upsert statement targets the `source` primary key.
4. Query helper returns stored payloads ordered by source.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Live source monitor jobs.
- API routes reading from the database.
- Running migrations against a live Postgres instance.
