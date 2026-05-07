# T59: Execution preview service

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T57

## Goal
Add a no-submit execution preview service that consumes risk decisions.

## Outputs
- `execution-preview` JSON Schema contract.
- `build_execution_preview(s)` service.
- `EXECUTION_PREVIEW` lifecycle event generation.
- Unit tests for ready, disabled, and blocked previews.

## Acceptance Criteria
1. Execution previews validate against the contract.
2. `ALLOW` trade-side risk decisions can produce `READY` paper previews.
3. Watch/no-side decisions remain `DISABLED`.
4. Blocked risk decisions produce `BLOCKED` previews.
5. Broker submission remains false unless a later gate explicitly changes it.
