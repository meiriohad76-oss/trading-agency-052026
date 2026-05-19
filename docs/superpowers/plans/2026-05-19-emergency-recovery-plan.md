# Emergency Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore credibility and operational readiness by making the Trading Agency complete a verified real-data analysis-to-paper-trade path with truthful data health, no hidden fallback data, and bottom-line-first UX.

**Architecture:** Fix the system in vertical slices. First repair the live-trading blocker path, then reconcile data-lane readiness and provenance, then repair LLM/email evidence inclusion, then harden UX and performance. Every ticket ends with an automated check and an artifact in `research/results/emergency-recovery-qa-20260519/` or a successor dated folder.

**Tech Stack:** FastAPI, Jinja templates, SQLite/Postgres-compatible SQLAlchemy, Alembic, pytest, Playwright/local UI QA, Massive/Polygon lanes, Alpaca paper broker, OpenAI LLM review, Gmail/subscription email ingestion.

---

## Priority Rules

- P0 tickets block a believable paper-trading MVP.
- P1 tickets block operator trust, reproducibility, or trading-day reliability.
- P2 tickets improve clarity, accessibility, or maintenance but do not block a controlled paper-trading run.
- No ticket is done without a failing test or failing check first, a code fix, and a green verification command.
- Do not weaken production safety gates to make demos pass. If a workflow needs test-only bypasses, label them as test-only.

## Emergency Backlog

### T144 - P0 - Prove One Current Submit-Ready Paper Preview

**Problem:** Latest real cycle has `NO_TRADE 148`, `WATCH 20`, `0` BUY/SELL/SHORT/COVER rows, `0` ALLOW rows, and `0` submit-ready previews.

**Files likely involved:**

- `src/agency/services/paper_trade_promotion.py`
- `src/agency/services/execution_preview.py`
- `src/agency/services/risk.py`
- `src/agency/dashboard.py`
- `src/agency/views/execution.py`
- `tests/unit/test_paper_trade_promotion.py`
- `tests/unit/test_execution_preview_service.py`
- `tests/unit/test_risk_service.py`

**Definition of done:**

- Latest current cycle has at least one eligible BUY/SELL/SHORT/COVER preview or an approved WATCH promoted into a paper BUY by explicit policy.
- The preview has `risk_decision=ALLOW` or a clear caution acknowledgement for non-blocking WARN.
- The order intent is hash-bound to the exact current preview.
- A local paper-safe check proves `submit_enabled=true` without submitting a live order.

**Verification:**

```powershell
.\.venv\Scripts\python scripts\check_paper_review_status.py
.\.venv\Scripts\python scripts\check_operational_readiness.py --min-queue 1
pytest tests\unit\test_paper_trade_promotion.py tests\unit\test_execution_preview_service.py tests\unit\test_risk_service.py -q
```

### T145 - P0 - Fix Massive Daily Bars Active-Universe Coverage Gate

**Problem:** `massive_daily_bars` marks itself complete while operational readiness sees only `100/168` active tickers. This blocks `prices_daily`, `abnormal_volume`, and `technical_analysis`.

**Files likely involved:**

- `research/src/data_refresh/massive_orchestrator.py`
- `research/src/data_refresh/massive_lane_manifest.py`
- `research/src/prices/massive_daily.py`
- `research/scripts/pull_massive_grouped_daily.py`
- `src/agency/runtime/data_load_status.py`
- `tests/unit/test_massive_daily.py`
- `tests/unit/test_massive_orchestrator.py`
- `tests/unit/test_data_load_status.py`

**Definition of done:**

- Daily-bar lane coverage is measured against the active universe, not just requested tickers.
- Missing 68 tickers are automatically queued or displayed as exact missing symbols.
- `status-data-load.json` and `status-full-live-readiness.json` no longer say daily bars are complete when only partial active-universe coverage exists.
- Technical analysis and abnormal volume remain blocked until daily-bar coverage policy is actually satisfied.

**Verification:**

```powershell
pytest tests\unit\test_massive_daily.py tests\unit\test_massive_orchestrator.py tests\unit\test_data_load_status.py -q
.\.venv\Scripts\python scripts\check_operational_readiness.py --min-queue 1
```

### T146 - P0 - Unify Data-Load, Source-Health, Scheduler, and Execution Freshness Verdicts

**Problem:** One surface says daily bars are healthy, another says data-load is blocked, another says execution is context-only, and dashboard QA sees fallback provenance. The operator cannot know which status is authoritative.

**Files likely involved:**

- `research/src/live_runtime/source_health.py`
- `src/agency/runtime/data_load_status.py`
- `src/agency/runtime/full_live_readiness.py`
- `src/agency/runtime/scheduler_work_queue.py`
- `src/agency/runtime/readiness_sources.py`
- `src/agency/api/health.py`
- `src/agency/views/_shared.py`
- `tests/unit/test_data_load_status.py`
- `tests/unit/test_full_live_readiness.py`
- `tests/unit/test_scheduler_work_queue.py`

**Definition of done:**

- A single evidence snapshot produces consistent `ready`, `context_only`, `warn`, or `blocked` verdicts across command dashboard, data-load API, source-health API, scheduler, paper-review, and execution freshness.
- Closed-market freshness uses latest completed market session where appropriate.
- Execution-critical freshness uses strict near-real-time requirements only at submit time.
- The UI explicitly says whether the displayed status is live DB-backed, latest artifact, or unavailable.

**Verification:**

```powershell
pytest tests\unit\test_data_load_status.py tests\unit\test_full_live_readiness.py tests\unit\test_scheduler_work_queue.py -q
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py
```

### T147 - P0 - Remove Hidden Runtime Artifact Fallback From Operational Mode

**Problem:** Runtime artifact fallback defaults to enabled and can substitute dashboard/API data when DB reads fail or return no rows.

**Files likely involved:**

- `src/agency/runtime/artifact_fallbacks.py`
- `src/agency/api/reports.py`
- `src/agency/api/risk.py`
- `src/agency/views/_shared.py`
- `src/agency/views/execution.py`
- `tests/unit/test_reports_api.py`
- `tests/unit/test_risk_api.py`
- `tests/unit/test_execution_preview_service.py`

**Definition of done:**

- Production mode disables artifact fallback by default.
- If fallback is explicitly enabled for local/offline mode, every row and every endpoint exposes fallback origin.
- Production DB failure returns a clear 503 or dashboard blocker, not silently substituted operational data.
- Order approval cannot become submit-ready from artifact-only lifecycle events.

**Verification:**

```powershell
pytest tests\unit\test_reports_api.py tests\unit\test_risk_api.py tests\unit\test_execution_preview_service.py -q
rg -n "runtime_artifact_fallback" src tests
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py
```

### T148 - P0 - Add Fresh Broker and Critical Source Refresh Before Submit

**Problem:** Broker endpoint can read Alpaca, but execution freshness can still use stale persisted broker/source rows and block submission.

**Files likely involved:**

- `src/agency/broker/alpaca.py`
- `src/agency/services/broker_audit.py`
- `src/agency/runtime/scheduler_work_queue.py`
- `src/agency/views/execution.py`
- `scripts/run_paper_broker_validation.py`
- `tests/unit/test_alpaca_broker.py`
- `tests/unit/test_broker_audit_service.py`
- `tests/unit/test_paper_broker_validation_script.py`

**Definition of done:**

- Before order approval/submit, the agency refreshes or verifies broker snapshot age under 60 seconds.
- Critical source-health is checked against the execution policy immediately before submit.
- The submit button explains in plain English which freshness item blocks submission.
- Read-only broker readiness and optional paper trade smoke are separated.

**Verification:**

```powershell
pytest tests\unit\test_alpaca_broker.py tests\unit\test_broker_audit_service.py tests\unit\test_paper_broker_validation_script.py -q
.\.venv\Scripts\python scripts\run_paper_broker_validation.py
```

### T149 - P1 - Enable Runtime LLM Review After Environment Is Loaded

**Problem:** OpenAI is configured, but the scheduler snapshots LLM enablement before `.env` is loaded. Latest cycle has `Prompt audits: 0` and `NO_REVIEW 168`.

**Files likely involved:**

- `src/agency/app.py`
- `src/agency/runtime/scheduler_runner.py`
- `scripts/run_live_runtime_cycle.py`
- `src/agency/services/llm_review.py`
- `tests/unit/test_scheduler_runner.py`
- `tests/unit/test_llm_review_service.py`
- `tests/unit/test_openai_llm_check.py`

**Definition of done:**

- LLM enablement is resolved after `.env` load or lazily at command construction time.
- Regression test proves `AGENCY_ENABLE_LLM_REVIEW=true` adds `--enable-llm-review`.
- Latest runtime cycle with LLM enabled writes prompt audits.
- Candidate page clearly shows LLM status: included, skipped by policy, failed, or not configured.

**Verification:**

```powershell
pytest tests\unit\test_scheduler_runner.py tests\unit\test_llm_review_service.py tests\unit\test_openai_llm_check.py -q
.\.venv\Scripts\python scripts\check_openai_llm_review.py
```

### T150 - P1 - Carry Subscription Article Analysis Into Runtime Evidence

**Problem:** Subscription ingest analyzed linked articles, but latest runtime source-health marks subscription thesis unavailable/stale and the signal table has no `subscription_thesis` row.

**Files likely involved:**

- `research/src/subscription_email/ingest.py`
- `research/src/subscription_email/storage.py`
- `research/src/signals/subscription_thesis.py`
- `research/src/live_runtime/cycle.py`
- `src/agency/views/candidates.py`
- `tests/unit/test_subscription_email_agents.py`
- `tests/unit/test_subscription_thesis_signal.py`
- `tests/unit/test_runtime_cycle.py`

**Definition of done:**

- Fresh `article_analyzed` rows are included in the next runtime cycle when relevant to a ticker.
- If article evidence is pending next cycle or context-only, the candidate page says that explicitly.
- Candidate page distinguishes included evidence, pending evidence, stale evidence, login-required evidence, and discarded context.

**Verification:**

```powershell
pytest tests\unit\test_subscription_email_agents.py tests\unit\test_subscription_thesis_signal.py tests\unit\test_runtime_cycle.py -q
.\.venv\Scripts\python research\scripts\import_subscription_emails.py --config research\config\subscription-email.local.json --include-seen --max-emails 10 --max-article-links 10 --enable-article-llm-analysis
```

### T151 - P1 - Surface Seeking Alpha Login Required Per Candidate

**Problem:** Login-gated article handling is safe, but terminal login-required statuses can be moved to ignored rows and disappear from candidate UX.

**Files likely involved:**

- `research/src/subscription_email/classifiers.py`
- `research/src/subscription_email/linked_content.py`
- `src/agency/views/candidates.py`
- `src/agency/templates/candidate_detail.html`
- `tests/unit/test_subscription_email_agents.py`
- `tests/unit/test_fastapi_app.py`

**Definition of done:**

- Any login-required article creates a visible per-ticker non-evidence callout.
- The callout says the article was not analyzed because user login is required.
- The email agent pauses for user login acknowledgement before retrying links in that session.
- Login-required rows are not counted as bullish/bearish evidence.

**Verification:**

```powershell
pytest tests\unit\test_subscription_email_agents.py tests\unit\test_fastapi_app.py::test_candidate_detail_renders_audit_empty_state -q
```

### T152 - P1 - Make WATCH Promotion Diagnostics Visible

**Problem:** Paper promotion is enabled, but no WATCH row passes current thresholds. The UI does not clearly explain which promotion checks failed.

**Files likely involved:**

- `src/agency/services/paper_trade_promotion.py`
- `src/agency/services/execution_preview.py`
- `src/agency/templates/execution_preview.html`
- `src/agency/templates/candidate_detail.html`
- `tests/unit/test_paper_trade_promotion.py`
- `tests/unit/test_execution_preview_service.py`

**Definition of done:**

- Each WATCH row shows exact promotion checks: conviction, source count, confirmed signal count, freshness, conflict, human review, risk policy.
- The UI says "research approved, not orderable because..." only with concrete failed checks.
- A fixture proves an approved WATCH crossing thresholds becomes a paper BUY preview.

**Verification:**

```powershell
pytest tests\unit\test_paper_trade_promotion.py tests\unit\test_execution_preview_service.py -q
```

### T153 - P1 - Reject Stale Direct Stock-Trades Batch Plans

**Problem:** Old refresh plans still contain direct `run_data_refresh_batch.py --dataset stock_trades --no-market-aware` commands. Current code blocks those jobs, but the plan runner should fail fast before execution.

**Files likely involved:**

- `research/scripts/run_active_universe_refresh_plan.py`
- `research/scripts/plan_active_universe_refresh.py`
- `research/src/data_refresh/jobs.py`
- `tests/unit/test_active_universe_refresh_plan.py`

**Definition of done:**

- Plan runner rejects any direct stock-trades generic batch command.
- Error message tells the operator to regenerate a lane-owned plan.
- No runbook or generated plan points operators toward disabled full-universe live-puller bypass flags.

**Verification:**

```powershell
pytest tests\unit\test_active_universe_refresh_plan.py tests\unit\test_data_refresh_batch.py -q
```

### T154 - P1 - Treat Full-Coverage Partial-Usable Live Slices As Satisfied

**Problem:** `massive_live_trade_slices` is `partial_usable` with `168/168` usable tickers, but scheduler signal jobs can still wait on that raw lane.

**Files likely involved:**

- `src/agency/runtime/scheduler_work_queue.py`
- `research/src/data_refresh/massive_orchestrator.py`
- `research/src/data_refresh/massive_lane_manifest.py`
- `tests/unit/test_scheduler_work_queue.py`
- `tests/unit/test_massive_orchestrator.py`

**Definition of done:**

- `partial_usable` with full active-universe usable coverage satisfies live latest-slice derived lanes.
- Full-depth repair remains assigned to `massive_backtest_trade_tape`.
- Scheduler distinguishes "live usable" from "historical complete."

**Verification:**

```powershell
pytest tests\unit\test_scheduler_work_queue.py tests\unit\test_massive_orchestrator.py -q
```

### T155 - P1 - Stabilize Slow Report and Dashboard Routes

**Problem:** `/reports/selection` timed out in local runtime smoke, and Command dashboard timed out once in dashboard QA.

**Files likely involved:**

- `src/agency/api/reports.py`
- `src/agency/views/command.py`
- `src/agency/templates/dashboard.html`
- `src/agency/views/final_selection.py`
- `scripts/check_local_runtime.py`
- `scripts/check_dashboard_live_data_qa.py`
- `tests/unit/test_reports_api.py`
- `tests/unit/test_fastapi_app.py`

**Definition of done:**

- `/reports/selection` returns under 5 seconds on the current data size.
- Command dashboard returns first byte under 3 seconds locally.
- Large tables are paginated, summarized, or lazy-loaded.
- The smoke checks fail if route budgets regress.

**Verification:**

```powershell
.\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py
pytest tests\unit\test_reports_api.py tests\unit\test_fastapi_app.py -q
```

### T156 - P1 - Rebuild Command Dashboard Around Next Required Operator Action

**Problem:** The dashboard still makes the operator scroll through less important data before seeing what to do next.

**Files likely involved:**

- `src/agency/views/command.py`
- `src/agency/templates/dashboard.html`
- `src/agency/templates/_data_health.html`
- `src/agency/static/styles.css`
- `tests/unit/test_fastapi_app.py`
- `tests/unit/test_ux_audit_implementation.py`

**Definition of done:**

- First viewport shows: overall status, blockers, next action, ETA/progress, review queue top items, and trade eligibility.
- Every health row has "what this means" and "what to do next."
- No generic text like "blocked by policy" appears without concrete reason.
- Review queue is reachable without long scrolling.

**Verification:**

```powershell
pytest tests\unit\test_ux_audit_implementation.py tests\unit\test_fastapi_app.py::test_dashboard_renders_status_overview -q
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py
```

### T157 - P1 - Unify Caution Acknowledgement Across Review Paths

**Problem:** Candidate sticky review can approve directly while the lower full review panel has caution acknowledgement behavior.

**Files likely involved:**

- `src/agency/templates/candidate_detail.html`
- `src/agency/dashboard.py`
- `src/agency/services/human_review.py`
- `tests/unit/test_human_review_service.py`
- `tests/unit/test_fastapi_app.py`

**Definition of done:**

- Every approval path requires the same acknowledgement when caution is required.
- Sticky action either includes the acknowledgement or jumps to the full review panel.
- Approval without required acknowledgement is rejected server-side.

**Verification:**

```powershell
pytest tests\unit\test_human_review_service.py tests\unit\test_fastapi_app.py -q
```

### T158 - P2 - Fix UX Accessibility and Label Credibility

**Problem:** Essential help is title-only, some muted labels have low contrast, portfolio placeholders show "None," and step numbers are inconsistent.

**Files likely involved:**

- `src/agency/templates/base.html`
- `src/agency/templates/_data_health.html`
- `src/agency/templates/portfolio_monitor.html`
- `src/agency/templates/signals.html`
- `src/agency/templates/market_regime.html`
- `src/agency/static/styles.css`
- `tests/unit/test_ux_audit_implementation.py`

**Definition of done:**

- Tooltips that carry operational meaning are keyboard/touch accessible.
- Muted labels meet at least 4.5:1 contrast on dark surfaces.
- Null placeholders are replaced by operational states like "Broker offline" or "No current thesis."
- Workflow step labels match navigation or are removed.

**Verification:**

```powershell
pytest tests\unit\test_ux_audit_implementation.py -q
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py
```

### T159 - P2 - Make Premarket Lane Session-Aware

**Problem:** Premarket lane is stale and can count as a Massive health block before premarket when it should be session-aware.

**Files likely involved:**

- `research/src/data_refresh/market_calendar.py`
- `research/src/data_refresh/massive_orchestrator.py`
- `src/agency/runtime/data_load_status.py`
- `tests/unit/test_market_calendar.py`
- `tests/unit/test_massive_orchestrator.py`
- `tests/unit/test_data_load_status.py`

**Definition of done:**

- Stale premarket data blocks premarket execution only when that lane is required.
- Overnight status explains when premarket will refresh next.
- Premarket readiness does not pollute unrelated overnight readiness.

**Verification:**

```powershell
pytest tests\unit\test_market_calendar.py tests\unit\test_massive_orchestrator.py tests\unit\test_data_load_status.py -q
```

### T160 - P2 - Rewrite Obsolete Full-Universe Pull Runbook

**Problem:** `research/config/full-universe-pull.example.sh` still advertises disabled `--full-universe` and `--allow-long-window` flags.

**Files likely involved:**

- `research/config/full-universe-pull.example.sh`
- `docs/data-batching-strategy.md`
- `docs/data-extraction-strategy.md`
- `tests/unit/test_ops_scripts.py`

**Definition of done:**

- No operator-facing runbook instructs users to bypass the lane model for live stock trades.
- Historical repair examples use `backfill_massive_stock_trades.py` and `massive_backtest_trade_tape`.
- Live slice examples use lane IDs and active ticker tiers.

**Verification:**

```powershell
rg -n "allow-long-window|full-universe" docs research\\config research\\scripts
pytest tests\unit\test_ops_scripts.py -q
```

### T161 - P2 - Tighten No-Test-Data Production Scan

**Problem:** The forbidden-term scan catches many false positives from docs, tests, and browser profiles, while real runtime fallback still needs targeted production assertions.

**Files likely involved:**

- `scripts/check_dashboard_live_data_qa.py`
- `src/agency/runtime/operational_filters.py`
- `src/agency/api/reports.py`
- `src/agency/api/risk.py`
- `tests/unit/test_dashboard_live_data_qa_script.py`
- `tests/unit/test_reports_api.py`
- `tests/unit/test_risk_api.py`

**Definition of done:**

- Production payload scan excludes docs/tests/browser dictionaries but includes runtime/API/template data.
- Demo/mock/fake/fixture/manual-smoke rows are rejected or visibly labeled non-operational.
- Fallback artifacts are not accepted as live operational data.

**Verification:**

```powershell
pytest tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_reports_api.py tests\unit\test_risk_api.py -q
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py
```

## Execution Order

1. T144, T145, T146, T147, T148.
2. T149, T150, T151, T152.
3. T153, T154, T155.
4. T156, T157, T158.
5. T159, T160, T161.

## Final Acceptance Gate

The emergency recovery is complete only when all commands below pass on real current data:

```powershell
.\.venv\Scripts\python scripts\check_provider_readiness.py
.\.venv\Scripts\python scripts\check_operational_readiness.py --min-queue 1
.\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py
pytest tests\e2e\test_daily_loop_edge_cases.py tests\e2e\test_daily_loop_smoke.py tests\e2e\test_first_version_smoke.py -q
pytest tests\unit\test_runtime_cycle.py tests\unit\test_paper_trade_promotion.py tests\unit\test_execution_preview_service.py tests\unit\test_scheduler_work_queue.py -q
pytest tests\unit\test_data_load_status.py tests\unit\test_massive_orchestrator.py tests\unit\test_massive_daily.py tests\unit\test_massive_grouped_daily.py tests\unit\test_massive_stock_trades.py tests\unit\test_massive_block_trade_feed.py tests\unit\test_lane_promotion.py -q
pytest tests\unit\test_subscription_email_agents.py tests\unit\test_subscription_email_dedup.py tests\unit\test_llm_review_service.py tests\unit\test_openai_llm_check.py tests\unit\test_combination_and_llm_ab.py tests\unit\test_h3_llm_comparison.py -q
pytest tests\unit\test_ux_audit_implementation.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_fastapi_app.py -q
```

Required final state:

- `full_universe_tradable=true` or a clearly scoped "paper-tradable for N eligible tickers" with exact blockers.
- `tradable_ready=true` for live-critical lanes.
- At least one current-cycle orderable paper preview is proven.
- LLM prompt audits are present when LLM review is enabled.
- Candidate email/article evidence says whether it was included in the latest decision pack.
- No operational dashboard row silently uses fallback artifacts.
- The first viewport tells the operator what to do next.

