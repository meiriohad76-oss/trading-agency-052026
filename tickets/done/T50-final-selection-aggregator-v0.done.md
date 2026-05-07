# T50: Final selection aggregator v0

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T45, T49

## Goal
Add the first final selection aggregator that combines deterministic rules, LLM review,
policy gates, and lifecycle audit events into one report.

## Context
Deterministic selection and LLM review now have separate service artifacts. The system
needs a conservative arbitration layer before risk and execution preview tickets can
consume a single final action.

## Outputs
- `src/agency/services/final_selection.py`
- Service exports.
- Unit tests for happy path, policy blocking, LLM promotion blocking, and LLM demotion.

## Acceptance Criteria
1. Aggregator emits a schema-valid `SelectionReport`.
2. Aggregator emits `DETERMINISTIC_ACTION`, `LLM_ACTION`, and `FINAL_ACTION` lifecycle events.
3. Blocking policy gates force `NO_TRADE`.
4. LLM review cannot promote deterministic `NO_TRADE` to a trade/watch action.
5. LLM review can demote a deterministic `WATCH` to `CLOSE_REVIEW`.
6. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Risk engine.
- Execution preview.
- Live LLM calls.
