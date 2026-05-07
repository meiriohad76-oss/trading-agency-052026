# T64: Real runtime cycle orchestrator

**Owner:** codex
**Phase:** 3 (build)
**Estimate:** small
**Dependencies:** T63

## Goal
Add a local paper-cycle orchestrator that wires schema-valid runtime inputs through
selection, risk, execution preview, persistence, and lifecycle audit events.

## Outputs
- Runtime cycle service.
- `scripts/run_agency_cycle.py` command.
- README usage for running a cycle from JSON input.
- Unit tests for build, payload loading, contract validity, and persistence flow.

## Acceptance Criteria
1. The cycle builds EvidencePack, SelectionReport, RiskDecision, ExecutionPreview,
   and CandidateLifecycleEvent artifacts.
2. Source health, selection reports, risk decisions, and lifecycle events are persisted
   through injectable writers.
3. Execution previews remain no-submit paper artifacts.
4. Missing ticker signals degrade to blocked no-trade reports instead of being ignored.
5. No broker calls or real order submissions are performed.
