# N2 — Three-Layer Test Plan

**Status:** Accepted  
**Owner:** Ohad Meiri  
**Date:** 2026-05-14  
**Non-negotiable:** N2 (Three-layer testing: unit, integration, e2e)

---

## 1. Overview

Every component in the agency must have coverage at three layers. This document
specifies what each layer must cover, maps components to test files, and records
which gaps remain open.

| Layer | Purpose | Scope | Tooling |
| --- | --- | --- | --- |
| **Unit** | Verify a single function/class in isolation | No I/O, no DB, no API calls | pytest, mocks |
| **Integration** | Verify that two or more components compose correctly | Seeded in-memory DB or tmp files; no real network | pytest, SQLite or tmp_path |
| **E2e** | Verify the full daily cycle path from data → review queue | No external API calls; seeded data only | pytest, DemoRuntimeSeed |

All three layers must be green in CI before any production deployment.

---

## 2. Component Map

### 2.1 Research / Signal Evaluation

| Component | Unit | Integration | E2e |
| --- | --- | --- | --- |
| `signals/_common.py` (zscore, payload_dict) | `test_signals_common.py` ✅ | — | — |
| `signals/fundamentals.py` | `test_fundamentals_signal.py` ✅ | — | — |
| `signals/insider.py` | `test_insider_signal.py` ✅ | — | — |
| `signals/institutional.py` | `test_institutional_signal.py` ✅ | — | — |
| `signals/sector_momentum.py` | `test_sector_momentum_signal.py` ✅ | — | — |
| `signals/abnormal_volume.py` | `test_abnormal_volume_signal.py` ✅ | — | — |
| `signals/news.py` | `test_news_signal.py` ✅ | — | — |
| `signals/buy_sell_pressure.py` | `test_buy_sell_pressure_signal.py` ✅ | — | — |
| `signals/block_trade_pressure.py` | `test_block_trade_pressure_signal.py` ✅ | — | — |
| `signals/technical_analysis.py` | `test_technical_analysis_signal.py` ✅ | — | — |
| `signals/options_anomaly.py` | `test_options_anomaly_signal.py` ✅ | — | — |
| `signals/activity_alerts.py` | `test_activity_alerts_signal.py` ✅ | — | — |
| `evaluation/h1_ic.py` | `test_h1_ic.py` ✅ | — | — |
| `evaluation/combination.py` | `test_combination.py` ✅ | — | — |
| `evaluation/llm_ab.py` | `test_llm_ab.py` ✅ | — | — |
| `evaluation/verdicts.py` | `test_verdicts.py` ✅ | — | — |
| `evaluation/profile.py` | `test_profile.py` ✅ | — | — |

**Open gap:** Integration-layer tests for the research batch runner (`result_batch.py`)
against a real (tmp) parquet dataset. Currently only unit-tested with mocked manifests.

### 2.2 PIT Data Access

| Component | Unit | Integration | E2e |
| --- | --- | --- | --- |
| `pit/loader.py` | `test_pit_loader.py` ✅ | `test_pit_integration.py` ✅ | via e2e cycle |
| `pit/manifest.py` | `test_pit_manifest.py` ✅ | — | — |
| `pit/cusip_utils.py` | `test_cusip_utils.py` ✅ | — | — |
| PIT bypass guard | `test_pit_bypass_guard.py` ✅ | — | CI gate (T126) |

**Open gap:** PIT bypass guard is not yet a hard CI failure (T126 spec). The test
exists; wiring it as a blocking CI check is the remaining action.

### 2.3 Data Refresh

| Component | Unit | Integration | E2e |
| --- | --- | --- | --- |
| `data_refresh/batch.py` | `test_data_refresh_batch.py` ✅ | — | — |
| `data_refresh/jobs.py` | `test_data_refresh_jobs.py` ✅ | — | — |
| `prices/puller.py` | `test_prices_puller.py` ✅ | — | — |
| `market_flow/massive.py` | `test_massive_api_limits.py` ✅ | — | — |
| `market_flow/worker.py` | `test_market_flow_worker.py` ✅ | — | — |

### 2.4 Live Runtime

| Component | Unit | Integration | E2e |
| --- | --- | --- | --- |
| `live_runtime/freshness.py` | `test_live_runtime_freshness.py` ✅ | — | — |
| `live_runtime/source_health.py` | `test_live_runtime_source_health.py` ✅ | — | — |
| `live_runtime/cycle.py` | `test_live_runtime_cycle.py` ✅ | — | via e2e |
| `live_runtime/signals.py` | `test_live_runtime_signals.py` ✅ | — | — |

### 2.5 Agency Services

| Component | Unit | Integration | E2e |
| --- | --- | --- | --- |
| `services/final_selection.py` | `test_final_selection.py` ✅ | — | via e2e |
| `services/risk.py` | `test_risk.py` ✅ | `test_policy_persistence.py` ✅ | via e2e |
| `services/portfolio_monitor.py` | `test_portfolio_monitor.py` ✅ | — | — |
| `services/actionability_gate.py` | `test_actionability_gate.py` ✅ | — | — |
| `services/llm_review.py` | `test_llm_review.py` ✅ | — | — |
| `services/execution_preview.py` | `test_execution_preview.py` ✅ | — | via e2e |
| `services/demo_cycle.py` | `test_demo_cycle.py` ✅ | — | via e2e |
| Contract validation | `test_contracts.py` ✅ | — | via e2e |

### 2.6 Agency API

| Component | Unit | Integration | E2e |
| --- | --- | --- | --- |
| `api/risk.py` | `test_api_risk.py` ✅ | — | — |
| `api/status.py` | `test_api_status.py` ✅ | — | — |
| `api/selections.py` | `test_api_selections.py` ✅ | — | — |
| Dashboard routes | `test_dashboard.py` ✅ | — | — |

### 2.7 Persistence

| Component | Unit | Integration | E2e |
| --- | --- | --- | --- |
| `persistence/models.py` | `test_models.py` ✅ | `test_persistence_integration.py` ✅ | — |
| `runtime/` (list_recent_*) | `test_runtime.py` ✅ | — | — |

---

## 3. E2e Coverage Requirements

### 3.1 Daily Loop Happy Path (existing — `test_daily_loop_smoke.py`)

| Step | Must cover |
| --- | --- |
| Source health check | ≥ 1 HEALTHY source; cycle proceeds |
| Cycle run | Evidence packs built for every ticker in universe |
| Selection reports | ≥ 1 WATCH candidate produced |
| Risk decisions | All WATCH candidates have a risk decision |
| Review queue | Queue contains the WATCH candidates |
| Human review | APPROVE recorded; lifecycle event persists |
| Contract validation | All payloads validate against schemas |

### 3.2 Edge Cases (existing — `test_daily_loop_edge_cases.py`)

| Scenario | Test | Status |
| --- | --- | --- |
| Empty state — all NO_TRADE | `test_empty_state_no_candidates` | ✅ |
| Degraded source — STALE; cycle still completes | `test_degraded_source_cycle_still_completes` | ✅ |
| Rejected candidate | `test_rejected_candidate_recorded_in_lifecycle` | ✅ |
| Demo/test-mode seed | `test_demo_seed_is_identified_as_test_mode` | ✅ |
| Paper-only policy | `test_paper_only_mode_prevents_real_orders` | ✅ |
| BUY + paper policy = no live order | `test_paper_mode_broker_submit_false_is_enforced` | ✅ |

### 3.3 Open E2e Gaps

| Scenario | Priority | Ticket |
| --- | --- | --- |
| Freshness STALE blocks WATCH (freshness gate fires) | High | Future |
| inferred-only lane demoted to CONTEXT_ONLY (corroboration gate fires) | High | Future |
| Trailing stop exit recorded in lifecycle | Medium | Future |
| LLM review changes final_action from WATCH to NO_TRADE | Medium | Future |
| Policy update via API persists across cycle | Medium | Future |

---

## 4. Contract Validation Rules

All test layers must validate payloads against named schemas wherever a payload is
produced or consumed. The validate_contract() function from `agency.contracts` is the
single validation entry point. No test should hand-roll schema assertions.

Requirements by layer:

| Layer | Requirement |
| --- | --- |
| Unit | Validate any payload built by a builder function under test |
| Integration | Validate all payloads entering and leaving DB boundary |
| E2e | Validate 100% of payloads in the DemoRuntimeSeed |

---

## 5. Test Infrastructure Requirements

| Requirement | Status |
| --- | --- |
| `pytest-asyncio` for async test support | ✅ |
| `tmp_path` fixture for all file I/O tests | ✅ |
| `DemoRuntimeSeed` for seeded e2e runs | ✅ |
| `httpx.MockTransport` for API mock calls | ✅ |
| `monkeypatch` for env-var isolation | ✅ |
| No real network calls in any test | ✅ (enforced by convention) |
| No real DB required for unit tests | ✅ |
| PIT bypass guard as hard CI failure | ⬜ T126 |

---

## 6. Acceptance

N2 is accepted when:

1. All unit and integration tests pass (currently ✅ — 941 tests green)
2. All six e2e edge-case scenarios pass (currently ✅)
3. PIT bypass guard is wired as a hard CI failure (T126 — open)
4. The three open e2e gap scenarios are covered or explicitly deferred with a
   written rationale

The open e2e gaps are deferred to Phase 3 build because they require either live LLM
API integration (H3) or a fully-wired scheduler (T118). Both are Phase 3 work.
