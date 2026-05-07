# T42: Deterministic selection service stub

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T29, T38

## Goal
Add the first deterministic selection service that consumes an `EvidencePack` and emits
contract-valid selection artifacts.

## Context
The runtime now has contracts and persistence helpers for selection reports and candidate
lifecycle events. Engine code needs a small deterministic bridge before orchestration and
dashboard surfaces are wired to real outputs.

## Outputs
- `src/agency/services/deterministic_selection.py`
- Service package exports.
- Unit tests covering valid, blocked, empty, invalid, and repeatable outputs.

## Acceptance Criteria
1. Valid evidence packs produce schema-valid `SelectionReport` payloads.
2. Matching `DETERMINISTIC_ACTION` lifecycle events are produced for the same cycle/ticker.
3. Data-quality blockers force `NO_TRADE`.
4. Repeated calls with the same inputs produce the same lifecycle event id.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Database writes.
- LLM review calls.
- Final selection arbitration.
