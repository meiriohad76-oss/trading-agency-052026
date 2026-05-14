# Phase 2 Design Document

**Status:** Accepted for implementation  
**Owner:** Ohad Meiri  
**Date:** 2026-05-14  
**Prerequisite:** Phase 1 gate formally assessed (see `docs/findings.md`)

---

## 1. Scope

Phase 2 designs the contracts, evaluation paths, and UX prototype that Phase 3 builds
on. The three outputs required before Phase 2 is accepted:

1. **Finalized schemas** — EvidencePack, SignalResult, SelectionReport, DataSourceHealth
   (T158–T161). See `schemas/*.schema.json`.
2. **Three-layer test plan** — unit, integration, e2e coverage requirements for each
   component (T162). See `docs/n2-test-plan.md`.
3. **UX prototype** — first-version human-review workflow with signal-to-noise
   improvements (Track 2 T138–T150). Not started.

Phase 2 does NOT require Phase 1 empirical gate acceptance. It proceeds with the
conservative Phase 1 constraint set: no lane is action-weighted; WATCH requires ≥ 2
independent sources and ≥ 1 confirmed signal.

---

## 2. Architecture

### 2.1 Evaluation Path

Two evaluation paths produce a `SelectionReport` from an `EvidencePack`:

```
EvidencePack
  ├── Deterministic engine (always runs)
  │     → EngineDecision {action, score, conviction, reason_codes, blockers}
  └── LLM reviewer (opt-in, AGENCY_ENABLE_LLM_REVIEW=true)
        → LlmReview {action, confidence, rationale, supporting_factors, concerns}
              ↓
        final_action = deterministic.action unless LLM overrides with higher confidence
```

The LLM reviewer is wired into the live cycle runner as of T129. Its output is advisory:
it may change `final_action` from WATCH to BUY (stronger conviction) or from WATCH to
NO_TRADE (concern override), but it cannot reduce the deterministic gate requirements.

### 2.2 Signal Actionability Model

Every `SignalResult` in an `EvidencePack` carries an `actionability` label:

| Label | Meaning | Runtime effect |
| --- | --- | --- |
| `ACTIONABLE` | Lane passes freshness, source-count, and corroboration gates | Contributes to conviction score |
| `CONTEXT_ONLY` | Inferred lane or insufficient confirmed corroboration | Contributes to rationale only |
| `SUPPRESSED` | Freshness or data-quality gate failed | Not used; reason recorded |

The inferred-lane corroboration rule (T116): an inferred lane can only reach
`ACTIONABLE` when at least one confirmed signal is present anywhere in the pack.

### 2.3 Source Tier Hierarchy

| Tier | Examples | Used for |
| --- | --- | --- |
| `OFFICIAL_FILING` | SEC Form 4, 13F, company facts | Confirmed insider/institutional signals |
| `CONFIRMED_TRADE_PRINT` | Massive/Polygon stock-trade prints | Market-flow confirmed signals |
| `MARKET_DATA` | Massive/yfinance daily bars | Technical, volume, pre/post signals |
| `PROVIDER_NEWS` | Subscription email alerts | Activity-alert confirmed signals |
| `PAID_SUB_EMAIL` | Seeking Alpha, TradeVision theses | Subscription thesis signal |
| `RSS_HEADLINE` | Public RSS feeds | News sentiment signal |
| `INFERRED_FROM_BARS` | Technical indicators, sector momentum | Inferred signals |
| `SOCIAL_CROWD` | Not used in current version | Reserved |

---

## 3. Schema Contracts

### 3.1 EvidencePack (T158)

Shared between deterministic and LLM selection. Key additions for Phase 2:

- `evaluation_method`: `"deterministic"` | `"llm_enhanced"` — records which path produced this pack
- `lane_weights`: optional dict mapping lane name to float weight — populated when combination signal is used

### 3.2 SignalResult (T159)

- `suppression_reason_code`: standardized code from a closed enum (e.g., `FRESHNESS_STALE`, `INSUFFICIENT_SOURCES`, `INFERRED_NO_CONFIRMED_CORROBORATION`, `DATA_UNAVAILABLE`)
- All existing fields remain required; `summary` field is optional

### 3.3 SelectionReport (T160)

- `deterministic.action` and `llm_review.action` are both recorded
- `final_action` reflects the combined path output
- `trade_plan` gains `trailing_stop_pct` and `position_pct` for Phase 3 integration with the portfolio monitor

### 3.4 DataSourceHealth (T161)

- `dataset` field: identifies the `DatasetName` enum value this record corresponds to
- `next_expected_refresh_at`: optional ISO timestamp — for LAGGED sources (e.g., SEC 13F between filings), indicates when the next filing is expected

---

## 4. LLM Reviewer Design

### 4.1 Input Contract

The LLM reviewer receives an `EvidencePack` JSON payload and must produce a
`LlmReview` JSON payload. It may NOT receive any data not present in the evidence pack
(no external API calls, no current price lookups).

### 4.2 Prompt Structure

The LLM prompt is structured as:

1. System context: role, non-negotiables (no extrapolation beyond evidence, must flag uncertainty)
2. Evidence pack: signals, source tiers, freshness status, actionability labels
3. Policy context: current thresholds, risk flags
4. Response schema: required JSON fields from `LlmReview`

### 4.3 H3 Acceptance Criterion

The LLM stays in the selection path if and only if the H3 A/B harness across ≥ 3
repeats produces `llm_survives` verdict: Sharpe delta ≥ 0.05, CAGR delta ≥ 0.0, and
drawdown delta ≥ -0.02. Otherwise the LLM moves to context-only rationale generation
(produces rationale text but does not influence `final_action`).

---

## 5. Human Review Workflow

### 5.1 Review Queue

The Command dashboard review queue shows only WATCH-action candidates from the latest
cycle. Each row shows:

- Ticker, conviction score, final action
- Review state: `PENDING` | `APPROVED` | `DEFERRED` | `REJECTED`
- Data quality summary: freshness, source count, confirmed signal count

### 5.2 Approval Actions

| Action | Effect |
| --- | --- |
| APPROVE | Routes candidate to execution preview; generates risk decision |
| DEFER | Keeps candidate in queue for next cycle review |
| REJECT | Records REJECT lifecycle event; removes from queue |

### 5.3 Non-Negotiable Safety Invariants

1. Human approval is required before any candidate reaches execution stage
2. `broker_submit_enabled=True` requires explicit env gate; default is False
3. Paper-mode cycles never submit real broker orders regardless of review outcome

---

## 6. Phase 2 Acceptance Criteria

Phase 2 is accepted when ALL of the following are true:

| Criterion | Required | Owner |
| --- | --- | --- |
| Four core schemas finalized and all validation tests pass | Yes | T158–T161 |
| N2 three-layer test plan written and agreed | Yes | T162 |
| UX prototype: first-version human-review workflow passes inspection | Yes | T138–T150 |
| Phase 1 empirical gate accepted OR explicit provisional-defaults decision made | Yes | Research |
| No test layer regressions (unit + integration + e2e all green) | Yes | CI |

The empirical gate criterion can be waived with explicit decision: "proceed to Phase 3
build on provisional thresholds, accept Phase 1 gate when wider H1 retest completes."

---

## 7. Relationship to Phase 3

Phase 3 builds all components against the Phase 2 contracts. The key inputs Phase 3
inherits from Phase 2:

- Finalized schema JSON files (ground truth for all contract validation)
- N2 test plan (test coverage requirements per component)
- Conservative thresholds from Phase 1 (until empirical gate is accepted)
- UX prototype specs (what the dashboard must show)

Phase 3 completion criterion: all three test layers green for the full first-version
daily cycle path (data → signals → evidence → selection → risk → execution preview →
human review → lifecycle record).
