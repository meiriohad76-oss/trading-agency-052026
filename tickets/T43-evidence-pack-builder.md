# T43: EvidencePack builder service

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T29, T42

## Goal
Add a service helper that assembles contract-valid `EvidencePack` payloads from signal
results.

## Context
Selection services should consume one normalized evidence pack rather than each rebuilding
signal partitions and data-quality metadata. This helper creates that shared boundary.

## Outputs
- `src/agency/services/evidence_pack.py`
- Service package export.
- Unit tests for partitioning, data quality, invalid signals, and identity mismatch.

## Acceptance Criteria
1. Signal results are validated before inclusion.
2. Signals are partitioned into actionable, context-only, and suppressed arrays.
3. Data-quality freshness, source count, verification counts, and blockers are derived.
4. The final payload validates against the `evidence-pack` contract.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Signal adapters from research outputs.
- Database persistence.
- Selection rules beyond existing deterministic stub.
