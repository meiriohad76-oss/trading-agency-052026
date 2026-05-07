# T45: Deterministic selection rules v0

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T42, T43, T44

## Goal
Promote the deterministic selection stub into explicit v0 scoring and policy-gate rules.

## Context
The service can emit contract-valid artifacts, but its scoring logic should be separable,
configurable, and directly testable before persistence and final aggregation are added.

## Outputs
- `src/agency/services/deterministic_rules.py`
- Deterministic selection service wired to rule outputs.
- Unit tests for weighting, blocking gates, and warning gates.

## Acceptance Criteria
1. Rule evaluation validates input `EvidencePack` payloads.
2. Lane weights and watch threshold are configurable.
3. Blocking policy gates force `NO_TRADE`.
4. Stale/aging evidence is warned but not blocked.
5. Selection reports still validate after the service uses the rule module.
6. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- LLM review.
- Final selection aggregation.
- Database persistence.
