# Emergency Recovery QA Report - 2026-05-19

## Bottom Line

The agency is **not yet complete-active-universe paper-tradable** on the latest real runtime cycle.

The latest verified cycle, `auto-lane-refresh-20260519T065402Z`, can produce evidence packs, signals, WATCH candidates, broker account reads, and a paper-review queue. It cannot currently complete the whole path from analysis to a paper trade because:

- Daily OHLCV coverage is blocked at `100/168` active tickers.
- The latest cycle produced `NO_TRADE 148` and `WATCH 20`, with `0` BUY/SELL/SHORT/COVER rows.
- Risk produced `BLOCK 148` and `WARN 20`, with `0` ALLOW rows.
- Execution preview has no current orderable paper order.
- LLM review did not run in the latest cycle: `Prompt audits: 0`, `LLM review: NO_REVIEW 168`.
- Runtime/API health still exposes fallback artifact provenance and contradictory readiness states.

This report is intentionally blunt. Passing unit tests prove many components work in isolation. They do not prove the current live agency can complete the full workflow.

## Scope

This QA pass covered:

- Data acquisition lanes and Massive lane methodology.
- Signals, selection, human review, risk, execution preview, and Alpaca paper broker path.
- LLM review, subscription email article analysis, and Seeking Alpha login-gated article flow.
- Command dashboard and major UX surfaces.
- Safety and provenance gates, including artifact fallback and hash-bound approvals.

## Evidence Collected

Primary evidence folder:

`research/results/emergency-recovery-qa-20260519/`

Key snapshots and command outputs:

- `endpoint-snapshots/status-data-load.json`
- `endpoint-snapshots/status-full-live-readiness.json`
- `endpoint-snapshots/status-operational-readiness.json`
- `endpoint-snapshots/status-data-sources.json`
- `endpoint-snapshots/status-broker.json`
- `endpoint-snapshots/status-paper-review.json`
- `endpoint-snapshots/status-scheduler-work-queue.json`
- `check-operational-readiness.txt`
- `check-dashboard-live-data-qa.txt`
- `check-local-runtime.txt`
- `check-provider-readiness.txt`
- `check-paper-review-status.txt`
- `pytest-data-lanes.txt`
- `pytest-paper-workflow-core.txt`
- `pytest-llm-email.txt`
- `pytest-e2e-daily-loop.txt`
- `pytest-ux-dashboard.txt`

Parallel QA agents reviewed five domains:

- Agent A: data acquisition lanes, Massive lane ownership, freshness.
- Agent B: end-to-end selection to paper-trade path.
- Agent C: UX, readability, workflow actionability.
- Agent D: LLM, subscription email, article analysis, login-gated flow.
- Agent E: safety, provenance, fallback, approval gates.

## Verification Matrix

| Area | Status | Evidence | Meaning |
| --- | --- | --- | --- |
| Provider keys | PASS | `check-provider-readiness.txt`: `ready=true`, `configured_count=6`, `active_required_count=5` | Required configured providers are present. Planned providers without keys are not blockers. |
| Broker connection | PARTIAL PASS | `status-broker.json`: Alpaca paper account loaded, account `ACTIVE`, cash and position data present | Broker read works. This does not prove current submit readiness. |
| Operational readiness | FAIL | `check-operational-readiness.txt` | Blocked by data loaded/analyzed and pending human reviews. |
| Full-live readiness | FAIL | `status-full-live-readiness.json`: `ready=false`, `full_universe_tradable=false`, `blocker_count=3` | Full-live path is blocked. |
| Data-load readiness | FAIL | `status-data-load.json`: `state=blocked`, `tradable_ready=false`, `blocker_count=3` | Daily bars, abnormal volume, and technical analysis are blocked. |
| Massive live trade slices | PASS WITH WARNINGS | Agent A: `168/168` usable tickers, `125,907` latest-slice rows | Live market-flow slices are usable for latest-slice evidence. |
| Massive daily bars | FAIL | `status-data-load.json`: `100/168` active tickers through `2026-05-18` | Blocks technical analysis and abnormal-volume baseline reliability. |
| Backtest trade tape | NOT LIVE BLOCKER | Agent A: `massive_backtest_trade_tape` is `17%` and research-only | Historical repair should continue off-hours, but should not block live decisions. |
| Signals | PARTIAL | `live-runtime-cycle-summary.md`: `1491` signals across 11 lanes | Signals were generated, but critical lanes depend on blocked daily bars and missing LLM review. |
| Selection | FAIL FOR TRADING | `live-runtime-cycle-summary.md`: `NO_TRADE 148`, `WATCH 20` | No executable trade action exists in the latest cycle. |
| Risk | FAIL FOR TRADING | `live-runtime-cycle-summary.md`: `BLOCK 148`, `WARN 20`, no ALLOW | No current candidate is allowed for paper execution. |
| Human review queue | PENDING | `check-paper-review-status.txt`: `pending_count=20`, `reviewed_count=0` | Review queue exists but no latest-cycle reviews are recorded. |
| Execution preview | FAIL FOR TRADING | Agent B local execution context: `ready_count=0`, `submit_ready_count=0`, side counts `NONE:168` | There is no current orderable paper preview. |
| Order approval | NOT READY | Agent B DB counts: `ORDER_APPROVAL 0`, `ORDER_INTENT_APPROVAL 0` | Separate order approval path has no current order to approve. |
| LLM runtime review | FAIL | `live-runtime-cycle-summary.md`: `Prompt audits: 0`, `NO_REVIEW 168` | OpenAI key is configured, but runtime review did not execute. |
| Subscription article analysis | PARTIAL | `subscription-email-ingest.md`: `Linked content analyzed 10`; Agent D: not consumed by latest runtime | Articles were analyzed, but latest runtime marks subscription thesis unavailable/stale. |
| Seeking Alpha login gate | PARTIAL | Agent D found tests/code for blocking pre-login fetches | Safe login handling exists, but per-candidate UX can lose login-required rows. |
| Dashboard live-data QA | FAIL | `check-dashboard-live-data-qa.txt`: `failure_count=22` | Preflight found data-load block, fallback tokens, and one Command timeout. |
| Local runtime smoke | FAIL | `check-local-runtime.txt`: timeout on `/reports/selection` | Selection report endpoint is too slow or unstable under current data. |
| Core tests | PASS | 15 e2e tests, 85 paper workflow tests, 92 data-lane tests, 122 LLM/email tests, 20 UX tests passed | Good component coverage, but not sufficient for current live end-to-end readiness. |

## End-to-End Flow Status

```text
Provider keys
  PASS
    |
Raw data lanes
  PARTIAL: live trade slices usable, daily bars blocked at 100/168
    |
Derived signals
  PARTIAL: 1491 signals produced, but TA/abnormal-volume reliability blocked
    |
Selection
  WATCH only: 20 WATCH, 148 NO_TRADE, 0 trade actions
    |
Risk
  WARN/BLOCK only: 20 WARN, 148 BLOCK, 0 ALLOW
    |
Human review
  PENDING: 20 latest-cycle reviews pending
    |
Execution preview
  BLOCKED: 0 orderable previews, all sides NONE
    |
Order approval
  NOT AVAILABLE: no current order intent
    |
Alpaca paper submit
  NOT PROVEN: broker read works, submit path has no eligible order
```

## Confirmed Passes

- Provider readiness is green: 6 of 11 provider slots configured, 5 active required providers present.
- Alpaca paper broker read is connected and returns account/position/open-order data.
- Massive live latest-slice coverage is usable for `168/168` active tickers.
- Core unit test coverage passed for paper workflow, data lanes, LLM/email, UX helpers, and e2e daily-loop smoke.
- Seeking Alpha preflight/login-gated article logic is present in code and tested for safe handling.
- Demo/test fixture filtering exists in key report/risk/source-health paths.

## Confirmed Failures

### P0: No Complete Paper-Trade Path

The latest cycle has no executable trade row.

Evidence:

- `live-runtime-cycle-summary.md`: `NO_TRADE 148`, `WATCH 20`, `BLOCK 148`, `WARN 20`.
- Agent B local DB/runtime check: `ready_count=0`, `submit_ready_count=0`, `ORDER_APPROVAL_AVAILABLE_COUNT=0`, side counts `NONE:168`.

Impact:

The user can review candidates, but the agency cannot currently complete "approve candidate -> portfolio/risk sizing -> approve order -> submit paper order" on current real data.

### P0: Daily Bars Coverage Blocks Critical Lanes

`status-data-load.json` says the agency is blocked because Massive Daily Bars has verified OHLCV coverage for only `100/168` active tickers through `2026-05-18`.

This blocks:

- `prices_daily`
- `abnormal_volume`
- `technical_analysis`

Impact:

The dashboard can show signals, but the critical baseline used by TA, abnormal volume, and sector regime is not complete for the active universe.

### P0: Runtime Readiness Contradictions

Different readiness surfaces disagree:

- `status-data-load.json` says blocked.
- `source-health.json` says `daily-market-bars` is `HEALTHY`.
- `status-full-live-readiness.json` says blocked.
- Dashboard QA says `/status/data-sources` contains `runtime_artifact_fallback`.
- Broker endpoint is connected, but execution freshness gate can still use stale persisted broker/source data.

Impact:

The UI cannot yet be trusted as a single operational truth source.

### P1: LLM Is Configured But Not Active In Runtime

OpenAI is configured, but the latest runtime did not run LLM review.

Evidence:

- `status-provider-readiness.json`: OpenAI configured.
- `live-runtime-cycle-summary.md`: `Prompt audits: 0`, `LLM review: NO_REVIEW 168`.
- Agent D root cause: scheduler LLM enablement is snapped before `.env` is loaded.

Impact:

Candidate pages may imply LLM capability exists, but latest-cycle recommendations are not actually LLM reviewed.

### P1: Article Analysis Is Not Carried Into Current Runtime Evidence

Subscription email ingest analyzed linked articles, but the latest runtime still marks subscription thesis unavailable/stale.

Evidence:

- `subscription-email-ingest.md`: `Linked content analyzed 10`.
- `source-health.json`: `subscription-email-thesis` is `UNAVAILABLE`.
- Latest signal table has no `subscription_thesis` row.

Impact:

Candidate pages can show article context that was not part of the latest decision pack.

### P1: UX Still Has Actionability and Readability Gaps

Agent C found:

- Several scoped pages exceed local render budget.
- Candidate sticky review can bypass the caution acknowledgement pattern.
- Portfolio exit action says "Confirm exit" but only links to execution preview.
- Important explanations are title-only tooltips, not accessible on keyboard/touch.
- Some muted labels remain below normal contrast.
- Workflow numbering is inconsistent between nav and page badges.

Impact:

Even when data is correct, the operator may not know what action is expected or why.

### P1: Runtime Artifact Fallback Is Too Permissive

Agent E found runtime artifact fallback defaults to enabled and can substitute dashboard/API data when DB reads fail or return no rows.

Impact:

Fallback data can appear operational unless every row and endpoint clearly exposes provenance. This is a credibility issue for live trading.

## Specific Data Gaps

| Data or lane | Current status | Why it matters |
| --- | --- | --- |
| `massive_daily_bars` | `100/168` active tickers | Blocks TA, abnormal-volume baselines, sector regime. |
| `subscription_emails` / `subscription-email-thesis` | Aging/stale or unavailable in latest runtime | Email/article evidence not reliably included in latest decision pack. |
| `massive_premarket_trade_slices` | Stale from prior session | Premarket unusual activity should be session-aware. |
| `massive_backtest_trade_tape` | 17% and research-only | Not a live blocker, but historical research remains incomplete. |
| `massive_reference` | Missing/deferred | Corporate actions/reference accuracy not fully owned by Massive lane status. |
| `massive_options_flow` | Disabled or unavailable | Options flow cannot yet support recommendations. |
| `sec_company_facts` | 167/168 active tickers | Mostly healthy, but `BRK.B` coverage needs explicit handling. |

## Testing Results

Passing:

```text
scripts/check_provider_readiness.py
  ready=true, blocker_count=0

pytest tests/e2e/test_daily_loop_edge_cases.py tests/e2e/test_daily_loop_smoke.py tests/e2e/test_first_version_smoke.py -q
  15 passed

pytest tests/unit/test_runtime_cycle.py tests/unit/test_paper_trade_promotion.py tests/unit/test_execution_preview_service.py tests/unit/test_scheduler_work_queue.py -q
  85 passed

pytest tests/unit/test_data_load_status.py tests/unit/test_massive_orchestrator.py tests/unit/test_massive_daily.py tests/unit/test_massive_grouped_daily.py tests/unit/test_massive_stock_trades.py tests/unit/test_massive_block_trade_feed.py tests/unit/test_lane_promotion.py -q
  92 passed, 1 warning

pytest tests/unit/test_subscription_email_agents.py tests/unit/test_subscription_email_dedup.py tests/unit/test_llm_review_service.py tests/unit/test_openai_llm_check.py tests/unit/test_combination_and_llm_ab.py tests/unit/test_h3_llm_comparison.py -q
  122 passed

pytest tests/unit/test_ux_audit_implementation.py tests/unit/test_dashboard_live_data_qa_script.py tests/unit/test_fastapi_app.py::test_dashboard_renders_status_overview tests/unit/test_fastapi_app.py::test_risk_and_execution_pages_render_runtime_states tests/unit/test_fastapi_app.py::test_candidate_detail_renders_audit_empty_state -q
  20 passed
```

Failing:

```text
scripts/check_operational_readiness.py --min-queue 1
  blocked: Data loaded and analyzed, Human review progress

scripts/check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
  timed out reading /reports/selection

scripts/check_dashboard_live_data_qa.py
  failure_count=22
```

Warnings:

```text
tests/unit/test_massive_stock_trades.py::test_partial_trade_repair_resumes_from_saved_cursor
  pagination_completeness_uncertain for AAPL 2026-05-06
```

## Conclusion

The agency has useful building blocks, but it is not ready to be called a complete live operational paper-trading MVP.

The recovery plan must focus on:

1. Proving one current-cycle paper-trade path end to end.
2. Fixing daily-bar active-universe coverage and readiness contradictions.
3. Making LLM/article evidence part of the actual latest decision pack, or clearly labeling it as pending/context-only.
4. Disabling or loudly labeling fallback artifact data in operational surfaces.
5. Reworking dashboards so the user sees bottom-line status, required action, evidence freshness, and trade eligibility without scrolling or decoding generic labels.
