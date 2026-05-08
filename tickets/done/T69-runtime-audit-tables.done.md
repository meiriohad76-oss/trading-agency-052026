# T69: Runtime audit tables

**Owner:** codex
**Phase:** 3 provisional runtime scaffolding
**Status:** done

## Goal

Add durable database contracts and repositories for runtime audit records needed by
the first testable paper workflow.

## Delivered

- Added audit contracts for agent runs, prompt audits, execution state history, and
  risk snapshots.
- Added SQLAlchemy metadata and Alembic migration `0006_runtime_audit_tables`.
- Added repository helpers for row conversion, idempotent inserts/upserts, and recent
  audit selects.
- Added unit coverage for schemas, contract validation, metadata/migration shape, and
  repository statements.

## Acceptance Notes

1. Prompt audit payloads store hashes/metadata, not raw secrets by default.
2. Execution state and risk snapshots are append-only by audit id.
3. Agent runs are upserted by run id so running jobs can be finalized.
