# T26: LLM review A/B harness

**Owner:** codex
**Phase:** 1 (H3 LLM contribution)
**Estimate:** medium (2-6h)
**Dependencies:** T23, T25

## Goal
Add a mockable A/B harness that compares deterministic-only backtests with deterministic + LLM review backtests.

## Context
H3 needs identical backtests with and without qualitative review. The live LLM call is out of scope for this research utility; tests should use deterministic reviewers.

## Outputs
- `research/src/evaluation/llm_ab.py`
  - `ReviewDecision`
  - `ReviewFn`
  - `reviewed_signal_fn(...)`
  - `run_llm_ab(...)`

## Acceptance Criteria
1. Reviewer receives only date, ticker, deterministic score, and evidence payload.
2. Reviewer can approve, reject, or scale a score.
3. A/B output compares Sharpe, CAGR, max drawdown, turnover, and weekly target gap.
4. Multiple seeds/repeats are supported for stochastic reviewer experiments.
5. Tests use mock reviewers only.

## Tests Required
- Unit: reviewer rejection removes a ticker.
- Unit: reviewer scaling changes score.
- Unit: A/B output contains deterministic and reviewed rows.

## Out of Scope
- Live OpenAI API calls.
- Prompt design.
- EvidencePack production schema.
