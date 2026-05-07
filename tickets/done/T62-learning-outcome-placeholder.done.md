# T62: Learning outcome placeholder

**Owner:** codex
**Phase:** 2 (UX/build)
**Estimate:** small
**Dependencies:** T61

## Goal
Add an advisory learning snapshot and dashboard page without automatic tuning.

## Outputs
- `learning-outcome` JSON Schema contract.
- `build_learning_outcome` service.
- `/learning` page and nav link.
- Unit tests for premature and ready-for-review sample states.

## Acceptance Criteria
1. Learning snapshots validate against the contract.
2. The default state is premature with zero samples.
3. The page shows sample requirements and backtest/audit caveats.
4. The UI explicitly states no auto-tuning is performed.
5. No policy changes are applied from learning output.
