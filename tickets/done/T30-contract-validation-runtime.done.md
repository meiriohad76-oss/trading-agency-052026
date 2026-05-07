# T30: Runtime contract validation helpers

**Owner:** codex
**Phase:** 2 (design)
**Estimate:** small
**Dependencies:** T29

## Goal
Expose the JSON Schema contracts through a small runtime validation API for production code.

## Context
FastAPI endpoints, engine boundaries, and inter-agent flow tests need a single way to load
and validate named contracts. Schema validation should be centralized so endpoints do not
hand-roll file loading or reference registries.

## Outputs
- `src/agency/contracts/`
- Runtime dependency updates for JSON Schema validation.
- Unit tests for successful nested validation, invalid payload failures, and schema loading.

## Acceptance Criteria
1. Code can call `validate_contract("selection-report", payload)`.
2. External schema references resolve through the provenance and core contract schemas.
3. Invalid payloads raise a clear `ContractValidationError`.
4. Boolean validation is available for non-exception control flow.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Pydantic contract models.
- FastAPI routes.
- Database persistence.
