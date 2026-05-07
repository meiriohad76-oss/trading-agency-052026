# T44: SignalResult adapters

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T29, T43

## Goal
Add generic adapters that convert normalized lane scores and provenance into
schema-valid `SignalResult` payloads.

## Context
Research lanes currently return ticker-score mappings. Production selection needs those
scores wrapped with actionability, direction, reason codes, and provenance before they can
enter an `EvidencePack`.

## Outputs
- `src/agency/services/signal_adapters.py`
- Service package exports.
- Unit tests for one-off signal construction and score-map adaptation.

## Acceptance Criteria
1. Signal results validate against the `signal-result` contract.
2. Scores derive deterministic direction and actionability classifications.
3. Score-map adaptation uppercases and sorts tickers for repeatability.
4. Missing provenance fails explicitly.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Running research lane pullers.
- Evidence pack persistence.
- Lane-specific weighting.
