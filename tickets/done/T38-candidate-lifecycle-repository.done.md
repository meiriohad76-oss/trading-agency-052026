# T38: Candidate lifecycle contract and repository

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T37

## Goal
Make candidate lifecycle events schema-valid and persistable through runtime helpers.

## Context
T37 added the append-only table. Runtime code now needs a contract and repository layer
so future engines can record candidate state changes deterministically.

## Outputs
- `schemas/candidate-lifecycle-event.schema.json`
- Runtime contract registration.
- `src/agency/runtime/candidate_lifecycle.py`
- Unit tests for schema validation, deterministic event IDs, row conversion, insert SQL,
  filtering, and invalid payload rejection.

## Acceptance Criteria
1. Candidate lifecycle events validate as Draft 2020-12 JSON Schema.
2. Event IDs can be generated deterministically from event identity fields.
3. Repository validates payloads before converting them to database values.
4. Insert helper is idempotent on `event_id`.
5. Query helper can filter by ticker and cycle, newest first.
6. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Dashboard lifecycle view.
- Engine code that emits lifecycle events.
- Event-specific payload schemas.
