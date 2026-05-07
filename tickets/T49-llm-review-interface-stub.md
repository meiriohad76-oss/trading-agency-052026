# T49: LLM review interface stub

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T45, T48

## Goal
Add the service interface and context-only stub for LLM review artifacts.

## Context
The v2 plan keeps deterministic and LLM review as separate lanes, but live LLM calls should
not be wired until policy, prompt, and provider choices are explicit. The system still
needs a stable review shape and lifecycle event for audit continuity.

## Outputs
- `src/agency/services/llm_review.py`
- Deterministic selection uses the shared context-only review helper.
- Unit tests for review shape, lifecycle event, and invalid inputs.

## Acceptance Criteria
1. A provider protocol exists for future async LLM review implementations.
2. The default stub emits `NO_REVIEW` with zero confidence.
3. The stub emits a schema-valid `LLM_ACTION` lifecycle event.
4. Deterministic selection reports remain schema-valid with the shared review payload.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Live OpenAI calls.
- Prompt templates.
- LLM persistence beyond lifecycle event creation.
