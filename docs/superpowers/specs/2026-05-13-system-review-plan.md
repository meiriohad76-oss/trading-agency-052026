# Trading Agency v2 — System Review & Implementation Plan

**Status:** Approved for implementation planning  
**Owner:** Ohad Meiri  
**Date:** 2026-05-13  
**Approach:** Fast-path sprint → three parallel tracks  
**Priority order (user-stated):** Stability → Data/refresh → UX → Signal quality

---

## 1. Scope

This document is the output of a four-part system review:

1. **Module alignment** — agency implementation vs v2-plan design and non-negotiables
2. **UX review** — usability, information architecture, workflow, and visual design
3. **Code review** — bugs, edge cases, structural quality
4. **Market-aware data extraction** — update frequency, freshness accuracy, data reliability

The implementation plan uses **Approach 2 (operational fast-path)**:

- **Sprint (Week 1–2):** 8 tickets that unblock reliable daily paper operation
- **Three parallel tracks (Week 3+):** ~40 tickets across code quality, UX, and research validation

Gate criterion for the sprint: data refreshes, the cycle runs, and WATCH candidates appear in the review queue without manual debugging between steps.

---

## 2. Architecture Alignment — Findings

### 2.1 What Is Well Aligned

- Agent topology matches v2-plan §5 closely: analytical engines, aggregators, infrastructure, and operations/feedback are all present
- N5 (supervised execution) is fully enforced — broker submission requires explicit env gate + human approval + freshness check
- N6 (schemas-first) is implemented with JSON schema validation at every boundary
- N7 (provenance) is a first-class type throughout
- N8 (PIT discipline) is guarded by the PIT loader and bypass guard
- N9 (idempotency) is structurally sound — same snapshot in → same snapshot out
- The 12-question agent decomposition from v1 is rationalized into the four-category topology
- Evidence quality tiers, verification levels, and refusal patterns all carried forward correctly

### 2.2 Gaps vs Non-Negotiables

| Non-negotiable | Status | Gap |
|---|---|---|
| N1 — Data-sufficiency gating | Partially met | Freshness domain bug (D1) + inferred lanes bypass confirmed requirement (D2) |
| N2 — Three-layer testing | Partially met | e2e covers only first-version smoke path; empty/rejected/degraded states untested |
| N3 — Signal-to-noise UX | Partially met | Command panel overlap, dense vocabulary, no sticky review actions |
| N4 — Free-first sourcing | Met | No paid sources added without justification |
| N5 — Supervised execution | Met | ✅ |
| N6 — Schemas-first | Met | ✅ |
| N7 — Provenance | Met | ✅ |
| N8 — PIT discipline | Met | Minor: post-market bar availability window not modeled |
| N9 — Idempotency | Met | ✅ |
| N10 — Reproducible deployment | Partially met | Docker Compose exists; runbook incomplete |

### 2.3 Phase Gate Status

- **Phase 0:** Complete
- **Phase 1:** Implementation scaffolding complete; empirical gate NOT accepted. No signal lane survives Bonferroni-adjusted H1. Conservative thresholds active (2 sources + 1 confirmed).
- **Phase 2:** Provisional scaffolding only. Design doc, finalized schemas, and test plan not written.
- **Phase 3:** Local paper cycle runs and persists. Not a Phase 3 acceptance — scaffolding ahead of gate.
- **Phase 4:** First-version manual inspection ready. Formal validation not complete.
- **Phase 5:** Not started.

---

## 3. Code Review — Findings

### 3.1 Confirmed Bugs

**BUG-1 — Freshness domain coverage (High severity)**  
File: `research/src/live_runtime/freshness.py`  
Only `PRICES_DAILY` receives a calendar-aware timestamp correction. Every other dataset uses raw `timestamp_as_of`. Consequence: SEC facts will flip STALE after the freshness window even when no new filing exists; 13F will always appear STALE between quarterly filings; stock trades need a post-market availability offset before marking FRESH. Source health silently misreports, affecting the actionability gate downstream.

**BUG-2 — Inferred lanes can be ACTIONABLE with zero confirmed signals (High severity)**  
File: `src/agency/services/actionability_gate.py` lines 43–51  
`min_confirmed_sources=0` is set for: `abnormal_volume`, `technical_analysis`, all five market-flow lanes (`block_trade_pressure`, `buy_sell_pressure`, `market_flow_trend`, `pre_market_unusual_activity`, `unusual_trade_activity`), `prepost`, `options_flow`, `options_anomaly`.  
Consequence: these lanes can reach `ACTIONABLE` with no confirmed signal present, silently bypassing the T73 gate requirement and N1. The deterministic engine's `minimum_confirmed_signals=1` check operates at the evidence-pack level, but by that point the lane is already labeled ACTIONABLE.

**BUG-3 — Post-market bar availability window not modeled (Medium severity)**  
File: `research/src/live_runtime/freshness.py`  
`_latest_completed_daily_bar_date()` checks only that `timestamp_as_of >= yesterday`. A cycle run during market hours (e.g. 14:30 ET) will find today's `prices_daily` timestamp, pass the FRESH check, and compute technical signals on yesterday's close while reporting today's date. No warning is emitted.

**BUG-4 — Trailing stop high-water state is not persisted (Medium severity)**  
File: `src/agency/services/portfolio_monitor.py`  
High-water-mark tracking resets on each cycle. Positions held across cycles will not enforce trailing stops correctly. The trailing stop is displayed in the UI and in policy but does not function for positions spanning multiple paper cycles.

**BUG-5 — zscore silent fallback (Low severity)**  
File: `research/src/signals/_common.py` line 27  
When fewer than 2 non-null observations exist, `zscore()` returns a series of 0.0 values with no warning. Downstream signal scores are silently zeroed; the evidence pack carries a score of 0.0 that appears normal. Should emit a structured reason code ("insufficient_cross_section") rather than silent zero.

**BUG-6 — 13F CUSIP mapping is static with no change-detection (Low severity)**  
File: `research/config/cusip-map.local.json`  
If a holding's CUSIP changes due to a corporate action (merger, ticker change, spinoff), the institutional lane silently drops that holding with no alert. For S&P 100 constituents this is infrequent but not rare.

**BUG-7 — Subscription email dedup midnight edge case (Low severity)**  
File: `research/src/subscription_email/` deduplication logic  
The 24h deduplication key uses approximate time bucketing. Events near midnight UTC may be bucketed into different days, producing duplicates that appear as independent signals. For paid-sub emails that arrive around market close (20:00–00:00 UTC), this is a real risk.

### 3.2 Structural Issues

**STRUCT-1 — `dashboard.py` is 5,864 lines**  
The working model's own rule: 500-line smell, 1,000-line refactor. This file contains the full view-model construction for every dashboard page. At 5.8× the refactor threshold, any change has blast radius across all pages. It must be decomposed into per-page view-model modules before further UX work is done on it.

**STRUCT-2 — Market-aware scheduler is a planning primitive, not an executor**  
`market_batching.py` produces a correct plan dict. Nothing actually fires it. The market-aware operating model described in §10 of the system review is not wired end-to-end. This is the single largest gap between the documented operating model and reality.

**STRUCT-3 — LLM reviewer not wired to live cycles**  
`src/agency/services/llm_review.py` is implemented and tested. The live cycle runner in `research/src/live_runtime/cycle.py` does not call it. Paper cycles are deterministic-only. This blocks H3 research and the supervised review value proposition.

**STRUCT-4 — PIT bypass guard not a hard CI failure**  
The bypass guard exists and the integration test exists, but it is not wired as a hard failure in CI. Regressions can merge silently.

**STRUCT-5 — Portfolio policy is env/static only**  
Phase 4 validation requires adjusting thresholds based on paper cycle results. Currently requires `.env` edits and a server restart. A DB-backed persistence layer with a UI editor is needed for real operational use.

**STRUCT-6 — yfinance fallback has no alerting**  
If the Massive/Polygon key is absent, yfinance is the sole price source. If yfinance returns empty or malformed data, the PIT loader builds a cycle on it with no alert. Need an explicit "provider fallback active" warning in source health.

**STRUCT-7 — Massive pagination completeness unverified**  
`stock_trades` pulls are unbounded by default but there is no checksum or record-count validation against an expected total. Partial pulls silently under-report market-flow pressure.

### 3.3 Test Coverage Gaps

- e2e tests cover only the first-version happy path
- Empty state, rejected candidate, degraded data source, and test-mode states have no e2e coverage
- PIT bypass guard not a hard CI gate
- Missing unit test: PIT query at a date with no data → empty result, not raise

---

## 4. UX Review — Findings

### 4.1 Information Architecture Issues

**IA-1 — Six overlapping status panels on Command**  
"Full-Live Readiness", "Operational Checklist", "Live Config", "Provider Readiness", "Data Sources", and "Scheduler Work Queue" all communicate variants of "is the system ready?" The user must read all six to form a complete picture. Target: one **System Status** panel with three scannable rows (data / agents / broker), plus one Review Queue panel above the fold.

**IA-2 — Navigation order doesn't match workflow**  
Current nav: Command → Final Selection → Risk → Execution → Portfolio → Learning → Audit → Policy.  
The natural workflow is: Command → Review candidates → Risk context → Execution preview → Portfolio.  
"Final Selection" is implementation vocabulary, not user vocabulary. "Candidates" is the right label.

**IA-3 — Universe and Signals are in nav but disabled**  
These pages appear in navigation with no disabled state explanation. Users cannot tell if they are coming soon, unavailable due to missing data, or broken.

### 4.2 Decision Workflow Issues

**UX-1 — Review queue doesn't distinguish state**  
WATCH candidates don't visually separate: "ready to review" / "blocked by risk" / "already reviewed". All appear as equivalent rows. Users must open each one to determine reviewability.

**UX-2 — Review actions not sticky on candidate detail**  
Approve/Defer/Reject appear at the bottom of a long page. After reading evidence, the user must scroll back up or all the way down to act. Actions should persist at the top or float.

**UX-3 — Subscription Intelligence mixes pipeline audit with evidence**  
The section combines: email matched / linked article found / article opened / thesis analyzed — four different things with different evidential weight. A user cannot quickly tell whether subscription data is affecting the agency's score or is purely informational context.

**UX-4 — Technical vocabulary in user-facing content**  
`source_count`, `timestamp_as_of`, `selection_report`, `risk_decision`, `evidence_pack`, `ACTIONABLE`, `SUPPRESSED` all appear as primary labels. These are correct implementation terms but wrong product terms. Each needs a user-facing label with the technical term available on hover.

**UX-5 — Dense information without progressive disclosure**  
Dashboards show operational internals (provenance fields, lane weights, freshness timestamps) before user-meaningful content (why this stock, what to do). Detail is partly collapsed but the defaults show too much.

### 4.3 Empty and Edge States

**UX-6 — Portfolio Monitor and Learning have empty containers**  
Both pages show empty panels with no explanation of what will appear, when, or what the system will never do automatically. The Learning page especially needs explicit copy about what "learning" means and what decisions it will never make without human confirmation.

**UX-7 — Execution Preview doesn't lead with "paper mode — no real orders"**  
The paper-mode safety disclaimer appears but is not the first thing a user sees. In paper trading mode this should be a persistent, prominent banner — not an afterthought.

### 4.4 Audit and Policy Pages

**UX-8 — Audit is dense with no filtering**  
No filter by ticker, cycle ID, event type, or status. Full payload is visible by default. Users investigating a specific candidate must scan all rows.

**UX-9 — Policy page needs a clearer safety taxonomy**  
Hard constraints should be scannable as three tiers: "never" / "requires explicit confirmation" / "paper-only". Currently all policy values are presented as a flat list.

### 4.5 Mobile

**UX-10 — Long cards and dense tables need mobile-first treatment**  
Core pages render on mobile but the column-heavy tables and wide cards are unusable on phone-width viewports. *Flagged as visual companion candidate for the browser session.*

---

## 5. Market-Aware Data Extraction — Dedicated Review

### 5.1 What Is Working

- Market session classification correctly identifies pre-market / regular / after-hours / overnight phases
- Batch plan correctly defers slow SEC baselines during live market windows
- Stock-trades pagination defaults to full (unbounded) coverage
- Subscription email refresh is properly separated from market-data refresh

### 5.2 Update Frequency Requirements vs Current State

| Data type | Required cadence | Current state | Gap |
|---|---|---|---|
| Daily prices (Massive) | Once daily, post-close (~17:15 ET) | Manual script | Not automated |
| Daily prices (yfinance fallback) | Once daily | Manual script | Not automated + no fallback alert |
| Stock trades (Massive) | Pre-market window + after-hours | Manual script | Not automated |
| RSS news | Every 30–60 min during market hours | Manual script | Not automated |
| Subscription email | On arrival (watch) or daily (import) | Manual import only | Watch mode undocumented for daily ops |
| SEC company facts | Weekly / on filing event | Manual script | No change-detection |
| SEC Form 4 | Daily incremental | Manual script | No incremental trigger |
| SEC 13F | Quarterly | Manual script | No schedule |
| Options chains | Pre-cycle snapshot | Manual script | Not automated |

### 5.3 Freshness Domain Gaps by Dataset

| Dataset | Issue |
|---|---|
| `prices_daily` | Calendar fix exists ✅ |
| `sec_company_facts` | No adjustment — quarterly cadence not modeled; flips STALE after window even with no new filing |
| `sec_form4` | No adjustment — sporadic cadence makes rigid window unreliable |
| `sec_13f` | No adjustment — always appears STALE between quarterly filings by design; this is correct behavior but should be labeled "lagged by design" not STALE |
| `news_rss` | Correct to enforce tight freshness; no backoff during market close needed |
| `stock_trades` | No post-market availability offset; delayed prints need ~15 min post-market before marking FRESH |
| `subscription_emails` | Email delivery lag not modeled; a 20-minute delivery window should be built into freshness |

### 5.4 Data Accuracy and Reliability Issues

- **yfinance fallback:** No alerting when Massive key is absent and yfinance is the active source. Silent degradation.
- **Massive pagination:** No record-count checksum. Partial pulls under-report market-flow pressure silently.
- **13F CUSIP mapping:** Static manual file. Corporate actions (merger, spinoff, ticker change) silently drop holdings.
- **Subscription email dedup:** Midnight UTC edge case can produce duplicate events treated as independent signals.
- **Post-market bar timing:** Cycle run before 17:15 ET reports today's prices as FRESH but bars exclude today's close.

---

## 6. Fast-Path Sprint — Ticket Specs

### T115 — Fix dataset freshness domains for all non-price sources

**Owner:** Claude Code  
**Phase:** Sprint  
**Estimate:** Medium (2–6h)  
**Dependencies:** None

**Goal:** Eliminate silent freshness misreporting for SEC, news, stock trades, and subscription email datasets.

**Context:** `freshness.py` only applies a calendar-aware correction for `PRICES_DAILY`. Every other dataset uses raw `timestamp_as_of`, causing incorrect FRESH/STALE/AGING status that propagates to the actionability gate.

**Inputs:** `research/src/live_runtime/freshness.py`, `research/src/live_runtime/source_health.py`, `research/src/pit/manifest.py` (DatasetName enum)

**Outputs:** Updated `freshness.py` with per-dataset domain logic. Updated unit tests.

**Acceptance Criteria:**
1. `sec_company_facts` reports FRESH if the latest filing is within the configured staleness window, regardless of the calendar day
2. `sec_13f` reports a new status "LAGGED_BY_DESIGN" (not STALE) when between quarterly filing periods, with a human-readable reason
3. `stock_trades` reports FRESH only after 17:15 ET on the filing date (configurable offset)
4. `subscription_emails` applies a 20-minute delivery lag before marking FRESH
5. All existing freshness unit tests pass; new tests cover each dataset type
6. Source health dashboard reflects the new labels

**Tests Required:**
- Unit: one test per dataset type covering fresh/aging/stale/lagged transitions
- Unit: midnight boundary cases for each

**Out of Scope:** Changing the freshness window values themselves (those are config)

---

### T116 — Enforce confirmed-signal corroboration for inferred lanes

**Owner:** Claude Code  
**Phase:** Sprint  
**Estimate:** Small (< 2h)  
**Dependencies:** None

**Goal:** Ensure no inferred lane can reach ACTIONABLE without a confirmed signal present, honoring T73 and N1.

**Context:** `actionability_gate.py` sets `min_confirmed_sources=0` for all inferred lanes. This allows them to fire ACTIONABLE with zero confirmed signals, bypassing the T73 gate requirement.

**Inputs:** `src/agency/services/actionability_gate.py`

**Outputs:** Updated `DEFAULT_LANE_RULES`. Updated unit tests.

**Acceptance Criteria:**
1. All inferred lanes (`abnormal_volume`, `technical_analysis`, all five market-flow lanes, `prepost`, `options_flow`, `options_anomaly`) have `inferred_needs_confirmed_corroboration=True` and `min_confirmed_sources=0` (the corroboration is checked at gate level, not source-count level)
2. When no confirmed signal is present anywhere in the signal set, all inferred lanes are demoted to CONTEXT_ONLY
3. When at least one confirmed signal is present, inferred lanes are evaluated normally
4. Existing actionability gate tests pass; new tests cover the zero-confirmed-signals case

**Tests Required:**
- Unit: signal set with only inferred signals → all demoted to CONTEXT_ONLY
- Unit: signal set with one confirmed + multiple inferred → inferred evaluated normally
- Unit: regression — existing passing cases unchanged

**Out of Scope:** Changing the confirmed-lane rules (fundamentals, insider, institutional, activity_alerts)

---

### T117 — Split dashboard.py into per-page view-model modules

**Owner:** Codex  
**Phase:** Sprint  
**Estimate:** Large (6h+)  
**Dependencies:** None

**Goal:** Decompose the 5,864-line `dashboard.py` into focused per-page modules, each under 500 lines.

**Context:** `dashboard.py` contains view-model construction for every dashboard page. At 5.8× the 1,000-line refactor threshold, it is the highest blast-radius file in the repo. UX track work cannot proceed safely until this is decomposed.

**Inputs:** `src/agency/dashboard.py`

**Outputs:** 
- `src/agency/views/command.py` — Command page view model
- `src/agency/views/candidates.py` — Final selection + candidate detail
- `src/agency/views/risk.py` — Risk dashboard view model
- `src/agency/views/execution.py` — Execution preview view model
- `src/agency/views/portfolio.py` — Portfolio monitor view model
- `src/agency/views/learning.py` — Learning view model
- `src/agency/views/signals.py` — Signals dashboard view model
- `src/agency/views/market_regime.py` — Market regime view model
- `src/agency/views/_shared.py` — Shared helpers used by 2+ view models
- `src/agency/dashboard.py` reduced to router + template dispatch only (< 100 lines)

**Acceptance Criteria:**
1. All existing dashboard routes return identical responses before and after
2. No view module exceeds 500 lines
3. `dashboard.py` itself is under 150 lines (routing only)
4. All existing dashboard unit tests pass
5. No circular imports

**Tests Required:**
- Run full test suite; no new test logic needed if behaviour is unchanged
- Smoke: each dashboard page returns HTTP 200 with the same key fields

**Out of Scope:** Any UX changes. This is a pure structural decomposition.

---

### T118 — Wire market-aware scheduler executor

**Owner:** Claude Code  
**Phase:** Sprint  
**Estimate:** Large (6h+)  
**Dependencies:** None (T119 documents what this ticket builds; T119 depends on T118, not vice versa)

**Goal:** Make the market-aware planner actually fire refresh jobs at the right market phase without manual script invocation.

**Context:** `market_batching.py` produces a correct plan. Nothing executes it. The APScheduler dependency is already in the stack (`src/agency/runtime/scheduler.py` exists). The gap is wiring the plan output to actual job dispatch.

**Inputs:** `src/agency/runtime/scheduler.py`, `research/src/data_refresh/market_batching.py`, `research/scripts/run_data_refresh_batch.py`

**Outputs:**
- Updated `scheduler.py` with market-phase-aware job definitions
- A `scheduler_runner.py` entry point that can be started as a background process
- Job definitions for: daily prices (post-close), stock trades (pre-market + after-hours), RSS news (30-min during market hours), SEC incremental (overnight)

**Acceptance Criteria:**
1. Starting `scheduler_runner.py` runs the correct refresh jobs for the current market phase
2. Job failures are logged with structured JSON and do not crash the scheduler
3. The scheduler respects the `dry_run` flag from live-refresh config
4. The Command dashboard scheduler panel reflects running/queued jobs from the live scheduler (not just the plan)
5. Market phase transitions trigger the appropriate job set without manual intervention

**Tests Required:**
- Unit: scheduler produces correct job set for each market phase (mock clock)
- Unit: job failure → structured log entry, scheduler continues
- Integration: scheduler_runner starts and produces at least one job dispatch log entry

**Out of Scope:** Full APScheduler persistence (jobs reset on restart is acceptable for v1)

---

### T119 — Write daily ops runbook

**Owner:** Codex  
**Phase:** Sprint  
**Estimate:** Small (< 2h)  
**Dependencies:** T118

**Goal:** Single authoritative document and script for daily paper-trading operation.

**Context:** Multiple scripts exist (`run_first_version_pipeline.py`, `run_data_refresh_batch.py`, `check_operational_readiness.py`, etc.) but no single document tells the user what to run, in what order, and how to recover from partial failure.

**Inputs:** Existing scripts and docs in `scripts/`, `docs/testing-first-version.md`, `docs/operational-gap-analysis.md`

**Outputs:**
- `docs/daily-ops-runbook.md` — authoritative daily operating procedure
- `scripts/run_daily_ops.py` — single entry-point script that runs the full daily loop with clear phase labels and recovery instructions

**Acceptance Criteria:**
1. `run_daily_ops.py --help` describes every step with estimated duration
2. Each step prints a clear success/failure message before proceeding
3. A failed step prints a recovery instruction and exits with non-zero code
4. The runbook covers: startup check, data refresh, cycle run, review queue check, end-of-day close
5. The runbook explicitly states which steps require manual action vs are automated

**Tests Required:**
- Manual: run `run_daily_ops.py --dry-run` and verify each step is described correctly

**Out of Scope:** Automating the human review step itself

---

### T120 — Consolidate subscription email ingest path

**Owner:** Claude Code  
**Phase:** Sprint  
**Estimate:** Small (< 2h)  
**Dependencies:** None

**Goal:** Eliminate ambiguity between `watch_subscription_emails.py` (polling monitor) and `import_subscription_emails.py` (one-shot import) for daily operations.

**Context:** Both scripts exist. The operational gap analysis references only the import path. There is no documented guidance on which to use for daily ops, what happens if both run concurrently, or how the watch mode integrates with the daily cycle.

**Inputs:** `research/scripts/watch_subscription_emails.py`, `research/scripts/import_subscription_emails.py`, `research/src/subscription_email/monitor.py`

**Outputs:**
- Updated `docs/subscription-email-agents.md` with explicit daily-ops guidance
- A concurrency guard in the watch monitor to prevent double-processing with the import script
- Clear log output distinguishing "watch mode active" from "one-shot import complete"

**Acceptance Criteria:**
1. Documentation clearly states: use watch mode for continuous daily operation; use import for one-shot historical backfill
2. Running both simultaneously does not produce duplicate subscription email rows
3. Watch mode logs a structured startup message with the active mailbox and cadence
4. Import script logs a completion summary with counts

**Tests Required:**
- Unit: concurrent run guard — second invocation detects first is running and exits cleanly

**Out of Scope:** Changing the email processing logic itself

---

### T121 — End-to-end smoke test for the daily loop

**Owner:** Claude Code  
**Phase:** Sprint  
**Estimate:** Medium (2–6h)  
**Dependencies:** T115, T116, T117, T118, T119, T120

**Goal:** A single runnable test that validates the complete daily loop: data status check → cycle build → candidates in review queue → human review action recorded.

**Context:** Current e2e tests cover the first-version paper path but do not cover the full daily loop including scheduler output, freshness gate behavior, and review queue state.

**Inputs:** `tests/e2e/test_first_version_smoke.py`, sprint ticket outputs

**Outputs:** `tests/e2e/test_daily_loop_smoke.py`

**Acceptance Criteria:**
1. Test runs against seeded local data (no external API calls)
2. Covers: source health check → cycle run → evidence packs built → selection reports → risk decisions → review queue populated → approve action recorded
3. Test fails if any step produces an unexpected empty result or exception
4. Runs in under 60 seconds on the development machine

**Tests Required:** This ticket IS the test

**Out of Scope:** Full user-flow browser test (that is Track 1 T2-F work)

---

### T122 — Surface silent failures in data refresh subprocess runner

**Owner:** Claude Code  
**Phase:** Sprint  
**Estimate:** Small (< 2h)  
**Dependencies:** None

**Goal:** Ensure data refresh subprocess failures are visible in the dashboard and logs, not swallowed.

**Context:** `research/src/data_refresh/batch.py` runs puller commands as subprocesses. If a puller exits with a non-zero code or produces unexpected output, the refresh may record a partial success without surfacing the failure to the user.

**Inputs:** `research/src/data_refresh/batch.py`, `research/src/data_refresh/status.py`

**Outputs:** Updated batch runner with explicit failure capture and structured log output. Updated status schema to include `failed_datasets` list.

**Acceptance Criteria:**
1. Any puller subprocess that exits non-zero is recorded as `failed` in `data-refresh-status.json`
2. The Command dashboard shows a warning when any dataset in the latest refresh has `failed` status
3. Partial success (some datasets succeeded, some failed) is explicitly labeled — not reported as overall success
4. Structured log entry includes: dataset name, exit code, stderr excerpt (first 500 chars), timestamp

**Tests Required:**
- Unit: mock subprocess that returns non-zero → status records failure
- Unit: partial success → status reports partial, not success

**Out of Scope:** Retry logic (that is a follow-on ticket)

---

## 7. Parallel Track Tickets — Outlines

These are scoped but not yet fully specced. Full specs are written when each track starts.

### Track 1 — Code Quality & Stability (T123–T137)

| Ticket | Title | Owner | Depends On |
|---|---|---|---|
| T123 | Add zscore insufficient-cross-section reason code | Codex | — |
| T124 | Fix directional_rank_score degenerate single-value edge case | Codex | — |
| T125 | Model post-market bar availability window in freshness | Claude Code | T115 |
| T126 | Wire PIT bypass guard as hard CI failure | Claude Code | — |
| T127 | Add PIT empty-result unit test (no-data date) | Codex | — |
| T128 | Persist portfolio policy to DB with UI editor | Claude Code | — |
| T129 | Wire LLM reviewer into live cycle runner | Claude Code | — |
| T130 | Add yfinance fallback alert in source health | Claude Code | T115 |
| T131 | Add Massive pagination completeness checksum | Claude Code | — |
| T132 | Add CUSIP change-detection alerting for 13F | Claude Code | — |
| T133 | Fix subscription email dedup midnight UTC edge case | Codex | T120 |
| T134 | Persist trailing stop high-water mark across cycles | Claude Code | — |
| T135 | Complete e2e test coverage: empty/rejected/degraded states | Claude Code | T121 |
| T136 | Complete e2e test coverage: test-mode and paper-only states | Claude Code | T135 |
| T137 | Add structured JSON logging to all agent runs | Codex | — |

### Track 2 — UX & Dashboard Usability (T138–T150)

| Ticket | Title | Owner | Depends On |
|---|---|---|---|
| T138 | Merge six status panels into one System Status panel | Codex | T117 |
| T139 | Fix navigation labels (Candidates, not Final Selection) | Codex | T117 |
| T140 | Add disabled-page explanations for Universe and Signals | Codex | — |
| T141 | Add review queue state encoding (ready/blocked/reviewed) | Codex | T117 |
| T142 | Make review actions sticky on candidate detail | Codex | T117 |
| T143 | Redesign Subscription Intelligence as 4-tier pipeline label | Claude Code | T117 |
| T144 | Replace technical vocabulary with product language + tooltips | Codex | T117 |
| T145 | Add progressive disclosure: hide provenance fields by default | Codex | T117 |
| T146 | Write empty states for Portfolio Monitor and Learning | Codex | — |
| T147 | Add paper-mode safety banner to Execution Preview | Codex | T117 |
| T148 | Add audit filter by ticker/cycle/event type | Codex | T117 |
| T149 | Redesign Policy page with three-tier safety taxonomy | Codex | T117 |
| T150 | Mobile layout — card/table hierarchy and column reduction | Codex | T117, visual companion session |

### Track 3 — Research Validation & Phase Gates (T151–T162)

| Ticket | Title | Owner | Depends On |
|---|---|---|---|
| T151 | Widen Massive historical stock-trade coverage (full universe) | Codex | — |
| T152 | Rerun H1 with wider coverage and improved ticker-tagged news | Claude Code | T151 |
| T153 | H2 deterministic combination test | Claude Code | T152 |
| T154 | H3 LLM A/B harness runs | Claude Code | T129, T152 |
| T155 | H4/H5 realistic strategy profile sweep | Claude Code | T152 |
| T156 | Formal Phase 1 gate acceptance — update findings.md + phase-status.md | Claude Code | T155 |
| T157 | Write Phase 2 design document | Claude Code | T156 |
| T158 | Finalize EvidencePack schema | Claude Code | T156 |
| T159 | Finalize SignalResult schema | Claude Code | T156 |
| T160 | Finalize SelectionReport schema | Claude Code | T156 |
| T161 | Finalize DataSourceHealth schema | Claude Code | T156 |
| T162 | Write full N2 three-layer test plan | Claude Code | T157 |

---

## 8. Priority Ordering

**Week 1 — Sprint (run in parallel where possible):**
1. T116 (inferred lane corroboration — no dependencies, highest safety impact)
2. T122 (surface silent failures — no dependencies, immediate operational impact)
3. T115 (freshness domains — no dependencies, fixes silent data misreporting)
4. T120 (consolidate email ingest — no dependencies)
5. T117 (split dashboard.py — no dependencies, unblocks UX track)
6. T118 + T119 (scheduler executor + runbook — T119 depends on T118)
7. T121 (daily loop smoke test — depends on all above)

**Week 3+ — Parallel tracks start after T121 passes:**
- Track 1 tickets: T123–T127 have no sprint dependencies; start immediately
- Track 2 tickets: T138+ depend on T117; start after T117 merges
- Track 3 tickets: T151 has no dependencies; start immediately

---

## 9. Open Questions

| # | Question | Owner | Resolve by |
|---|---|---|---|
| OQ-1 | Which APScheduler job store? Memory (resets on restart) vs SQLite vs Postgres? | User + Claude Code | T118 spec |
| OQ-2 | Should `sec_13f` use "LAGGED_BY_DESIGN" as a new status enum, or "CONTEXT_ONLY" to reuse existing vocabulary? | Claude Code | T115 spec |
| OQ-3 | Is a Massive/Polygon API key available for T151? Cost/quota? | User | T151 start |
| OQ-4 | Mobile layout: what is the primary mobile use case? Quick status check, or full review workflow? | User | T150 visual companion session |
| OQ-5 | Policy editor: simple form in the Policy dashboard, or a separate admin page? | User | T128 spec |

---

*End of system review and implementation plan design.*
