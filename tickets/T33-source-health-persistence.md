# T33: Source health persistence schema

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T31

## Goal
Add the first runtime reliability table for data-source health snapshots.

## Context
The dashboard and API currently expose a bootstrap source-health payload. Before wiring
real monitors, the database needs a durable table and metadata so source status can be
audited and served consistently.

## Outputs
- SQLAlchemy metadata for `data_source_health`.
- Alembic migration `0002_data_source_health`.
- Unit tests for table metadata and migration linkage.

## Acceptance Criteria
1. Metadata includes a `data_source_health` table keyed by `source`.
2. Table captures status, source tier, freshness, timestamps, reliability score, notes,
   raw schema payload, and last error.
3. Alembic env points at agency metadata for future autogenerate support.
4. Migration upgrades from `0001_initial` and can be downgraded.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Repository upsert/query helpers.
- Dashboard database reads.
- Source monitor jobs.
