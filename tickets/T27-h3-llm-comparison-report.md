# T27: H3 LLM comparison report

**Owner:** codex
**Phase:** 1 (H3 LLM contribution)
**Estimate:** small
**Dependencies:** T25, T26

## Goal
Summarize deterministic-vs-LLM-review A/B runs into one repeatable H3 verdict artifact.

## Context
T26 added the mockable A/B harness. H3 still needs a compact summary that reports deltas,
variance, and a conservative survive/drop/inconclusive verdict before the findings document
can use the result.

## Outputs
- `research/src/evaluation/h3_llm_comparison.py`
- `research/scripts/summarize_h3_llm_ab.py`
- Unit coverage for H3 summary and Markdown rendering.

## Acceptance Criteria
1. A/B results with one deterministic row and one or more reviewed rows produce one summary row.
2. Summary includes Sharpe, CAGR, max drawdown, turnover, repeat count, deltas, and verdict.
3. Markdown output can be pasted into `docs/findings.md`.
4. Empty or malformed inputs raise deterministic errors.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Live LLM API calls.
- Prompt engineering.
- Real empirical H3 execution on historical data.
