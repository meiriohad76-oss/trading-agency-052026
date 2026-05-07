# T29: Core Phase 2 contract schemas

**Owner:** codex
**Phase:** 2 (design)
**Estimate:** medium
**Dependencies:** T28

## Goal
Define the first schema-first contracts consumed by the production agency engines.

## Context
Phase 2 starts with inter-agent contracts before implementation. The immediate findings
artifact names four priorities: SignalResult, EvidencePack, SelectionReport, and
DataSourceHealth.

## Outputs
- `schemas/signal-result.schema.json`
- `schemas/evidence-pack.schema.json`
- `schemas/selection-report.schema.json`
- `schemas/data-source-health.schema.json`
- Unit tests that validate schemas and nested sample payloads.

## Acceptance Criteria
1. Every schema is Draft 2020-12 JSON Schema with `$id` and `x-version`.
2. EvidencePack references SignalResult.
3. SelectionReport references EvidencePack.
4. SignalResult and DataSourceHealth reference the provenance schema source/freshness enums.
5. Nested sample payloads validate, and unknown fields are rejected.
6. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Pydantic runtime models.
- FastAPI endpoints.
- Database tables.
