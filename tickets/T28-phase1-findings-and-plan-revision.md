# T28: Phase 1 findings and plan revision

**Owner:** codex
**Phase:** 1 phase gate
**Estimate:** small
**Dependencies:** T21-T27

## Goal
Create the Phase 1 findings artifact and revise the plan references that point Phase 2 at
the research outputs.

## Context
The research code can now load data, score lanes, profile strategies, sweep parameters,
combine lanes, and summarize LLM review A/B runs. The document should be honest about
what is implemented versus what is empirically validated.

## Outputs
- `docs/findings.md`
- `docs/research-brief.md` update pointing findings maintenance to `docs/findings.md`.
- `docs/v2-plan.md` update noting the Phase 1 findings artifact as the Phase 2 input.

## Acceptance Criteria
1. Findings document has H1-H5/H3 sections with status, evidence source, verdict, and next action.
2. It does not claim edge before result files exist.
3. Plan docs link to the findings artifact.
4. No file exceeds 200 lines as part of this scaffold.

## Out of Scope
- Running expensive data collection or long backtests.
- Declaring final validated signal weights without empirical result files.
