# T55: Risk and execution preview placeholders

**Owner:** codex
**Phase:** 2 (UX)
**Estimate:** small
**Dependencies:** T51, T53

## Goal
Add read-only risk and execution preview pages that make unavailable backend behavior
explicit without implying orders or risk approvals exist.

## Outputs
- `GET /risk` placeholder page.
- `GET /execution-preview` placeholder page.
- Disabled gate and button states.
- Candidate input tables backed by persisted selection reports.

## Acceptance Criteria
1. Both routes render through the shared shell.
2. Both pages clearly show disabled/read-only status.
3. No page action can submit, approve, or generate an order.
4. Candidate inputs appear when reports exist, with unavailable states otherwise.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.
