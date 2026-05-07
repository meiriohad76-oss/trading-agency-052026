# T66: Research result runner batch

**Owner:** codex
**Phase:** 1/3 reconciliation
**Estimate:** small
**Dependencies:** T65

## Goal
Add a repeatable research-result batch runner that produces H1 artifacts when data
manifests are available and records an explicit blocked status when they are not.

## Outputs
- `evaluation.result_batch` batch helper.
- `research/scripts/run_research_batch.py` command.
- T66 status artifacts under `research/results/t66/`.
- Unit tests for dataset requirements, readiness inspection, and blocked status output.

## Acceptance Criteria
1. The batch checks required PIT manifests before running research jobs.
2. Missing datasets produce committed status artifacts instead of silent failure.
3. H1 IC/verdict outputs are written when required manifests exist.
4. H2-H5 are explicitly marked blocked until H1/price inputs exist.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.
