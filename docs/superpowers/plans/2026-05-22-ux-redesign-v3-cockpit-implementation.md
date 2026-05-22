# UX Redesign V3 Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the expert UX redesign package into a production cockpit experience for the Trading Agency without weakening live data, paper-trading, policy, freshness, or broker safety rules.

**Architecture:** Build the cockpit inside the current FastAPI/Jinja application as a real-data server-rendered product surface, with small JSON endpoints only where live refresh or panel drill-down requires them. Do not embed the standalone React/Babel prototype or its mock `window.COCKPIT_DATA`; treat the prototype as the visual and interaction source of truth, then map it onto existing production view models and services. Ship Variation A first as a parallel `/cockpit` route, prove it end-to-end, then decide whether to make it the default command dashboard or later build Variation C.

**Tech Stack:** Python 3.14, FastAPI, Jinja templates, existing `src/agency` view-model services, plain CSS in `src/agency/static/styles.css`, small vanilla JavaScript for cockpit interactions, Playwright for browser QA, pytest via `.\.venv\Scripts\python -m pytest`, Browser Use for local visual inspection, Superpowers for planning, TDD, debugging, verification, and subagent execution.

---

## Source Package

The redesign source was extracted to:

`research/results/ux-redesign-v3-source-20260522/`

Important source files:

- `handoff/01-design-philosophy.md`
- `handoff/02-user-workflow.md`
- `handoff/03-variation-a.md`
- `handoff/04-variation-c.md`
- `handoff/05-components.md`
- `handoff/06-states.md`
- `handoff/07-data-schema.md`
- `handoff/08-tweaks.md`
- `handoff/09-raspberry-pi.md`
- `handoff/10-implementation-order.md`
- `Variation A.html`
- `Variation C.html`
- `cockpit/cockpit.css`
- `cockpit/data.js`
- `cockpit/shell.jsx`
- `cockpit/panels.jsx`
- `cockpit/variation-a-preflight.jsx`
- `cockpit/variation-c-mission.jsx`

Prototype-only files that must not ship in production:

- `design-canvas.jsx`
- floating design-tool behavior from `tweaks-panel.jsx`
- `Trading Cockpit.html`
- `window.COCKPIT_DATA`
- `EDITMODE` markers
- random demo order IDs
- pre-approved prototype decisions

## Product Decisions Locked For This Plan

- Build **Variation A - Pre-Flight Cockpit** first.
- Keep the existing FastAPI/Jinja architecture.
- Build `/cockpit` in parallel before replacing `/` or `/command`.
- Use only real production view models and runtime artifacts.
- Keep paper-only v1. `LIVE_TRADING` stays locked off.
- Keep the existing broker submit freshness gate and order-intent hash binding.
- Do not reintroduce direct broad stock-trade batches; data access stays lane-based.
- Do not use stale screenshots, demo artifacts, or hidden fallback data as readiness proof.

## Product Decisions That Need Human Confirmation Before The Affected Ticket

- Whether the session-restore prompt should default to restore or discard after a browser reload during the same cycle.
- Whether the outage recovery prompt should automatically restore staged decisions after fresh revalidation or require the user to review each staged decision again.
- Whether a zero-position portfolio skips Phase 2 or shows an empty portfolio state.
- How to handle a staged candidate that becomes blocked after a policy or freshness change.
- Whether calm mode auto-engages after submission or remains manual only.
- Whether settings open from a gear button, long-press brand logo, or a dedicated settings route.
- Raspberry Pi model, target display resolution, and whether the final device is touch-first.

If a ticket reaches one of these decisions before the user answers, implement the conservative default in this plan and mark the decision in the handoff:

- Persist tweak preferences, active phase, staged candidate decisions, and staged exit decisions per cycle.
- Show a restore prompt after reload or browser crash before rehydrating staged phase/decisions/exits.
- Never persist submit gate state, typed phrase, broker response, or submit-in-progress state.
- On outage, freeze local staged decisions, show outage, and prevent submit until the recovered cycle revalidates every staged item.
- Show zero-position portfolio as an explicit empty state.
- Calm mode is manual.
- Settings open from a gear button in the top bar.

## Global Rules For Every Ticket

- Use `superpowers:test-driven-development` before implementation changes.
- Use `superpowers:systematic-debugging` for every failing test, browser mismatch, or unexpected runtime behavior.
- Use `superpowers:verification-before-completion` before marking a ticket done.
- Use `browser-use:browser` or Playwright for every UI ticket that changes templates, CSS, or JavaScript.
- Use `superpowers:dispatching-parallel-agents` when a ticket has independent review tracks, such as UX copy, safety gates, and browser QA.
- Use CodeRabbit or a focused code-review subagent before merging a milestone branch.
- Do not modify unrelated behavior, demo seeds, provider credentials, browser sessions, or generated runtime data unless the ticket explicitly requires it.
- Do not claim operational readiness without fresh checks.
- Do not use bare `pytest`; use `.\.venv\Scripts\python -m pytest`.
- Every user-visible sentence must answer one of these: what happened, why it happened, what the user can do, or what the system will do next.
- Keep large-file growth controlled: prefer new cockpit-specific modules/tests over expanding `command.py`, `_shared.py`, `styles.css`, or `test_fastapi_app.py`; those files may receive thin route, import, token, or compatibility glue only.
- API payloads must be bounded, ticker-normalized, credential-free, account-secret-free, and free of raw environment values.
- Browser QA must run in no-broker-submit mode by default. Any real paper submit test requires an explicit `--allow-paper-submit` flag plus fresh broker/readiness evidence captured in the report.

## Definition Of Done Pattern For Every Ticket

Each ticket is only complete after this loop is green:

1. Write or update failing unit/view tests for the behavior.
2. Run the targeted test and confirm it fails for the expected reason.
3. Implement the smallest production change.
4. Run the targeted test and confirm it passes.
5. Run the ticket's broader regression tests.
6. Run hardcoded/demo/stale-data scans for touched production paths.
7. Run browser or screenshot QA for touched UI paths.
8. Run a large-file guard for touched files and explain any growth over 250 lines in one existing large file.
9. Fix findings and repeat from the failing check until all ticket checks pass.
10. Record verification evidence in the ticket note or commit message.
11. Commit only the files for that ticket.

The ticket is not done if:

- A check was skipped without a written reason.
- A screenshot or browser pass shows unreadable text, overlap, hidden buttons, or generic copy.
- Any new route renders prototype data.
- Any production path depends on `window.COCKPIT_DATA`.
- Any submit path can bypass existing broker, policy, or freshness guards.

## Baseline Commands

Use these before Ticket 1 and again before final acceptance:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py tests\unit\test_ux_audit_implementation.py tests\unit\test_data_load_status.py tests\unit\test_scheduler_work_queue.py -q
.\.venv\Scripts\python -m pytest tests\unit\test_ops_scripts.py tests\unit\test_massive_stock_trades.py tests\unit\test_massive_orchestrator.py tests\unit\test_data_refresh_progress.py tests\unit\test_scheduler_runner.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_reports_api.py tests\unit\test_risk_api.py -q
.\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
.\.venv\Scripts\python scripts\check_operational_readiness.py --min-queue 1
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py
```

Hardcoded/demo scans:

```powershell
rg -n "window\.COCKPIT_DATA|EDITMODE|C-14:32|14:30|grossPostTrade.*84|ALP-\$\{|Math\.random|Start over" src scripts research/config
rg -n "AGENCY_RUNTIME_ARTIFACT_FALLBACK.*true|allow-long-window|full-universe" src scripts research/config docs
rg -n "stock_trades.*batch|run_massive_stock_trades|pull_massive_stock_trades" docs scripts src/agency
rg -n "subscription_thesis|llm_conflict|raw lane|Unknown|None" src/agency/templates src/agency/views
```

The `Unknown` and `None` scan can have intentional code hits; the ticket owner must inspect hits and prove none render as confusing user-facing fallback text.

---

## Ticket 0: Branch, Checkpoint, And Redesign Source Control

**Goal:** Create a controlled starting point before UX implementation.

**Files:**

- Modify: none unless committing existing controlled state.
- Read: `git status --short`
- Read: `docs/handoff-2026-05-21-bug-hunt-pause.md`
- Read: `docs/handoff-2026-05-22-live-readiness-continuation.md`
- Read: `research/results/ux-redesign-v3-source-20260522/handoff/README.md`

**Steps:**

- [ ] Step 1: Inspect current worktree.

  ```powershell
  git status --short
  git branch --show-current
  ```

  Expected: identify unrelated dirty files before editing.

- [ ] Step 2: Create a new implementation branch.

  ```powershell
  git switch -c feat/ux-redesign-v3-cockpit
  ```

  Expected: branch switches cleanly. If branch exists, use a unique suffix.

- [ ] Step 3: Decide how to preserve existing dirty changes.

  If dirty files are the current controlled state, commit them first with the user's approval or record them in a handoff. Do not reset or discard user work.

- [ ] Step 4: Confirm the source package exists.

  ```powershell
  Test-Path research\results\ux-redesign-v3-source-20260522\handoff\01-design-philosophy.md
  Test-Path research\results\ux-redesign-v3-source-20260522\Variation A.html
  ```

  Expected: both commands print `True`.

**Ticket DoD:**

- Branch is clear.
- Current dirty state is understood and documented.
- Source package path is documented.
- No implementation files were changed by this ticket except a checkpoint/handoff required to preserve dirty state.

---

## Ticket 1: Cockpit Contract And View Model

**Goal:** Create one production cockpit aggregate that maps current agency data to the redesign's cockpit contract without prototype data.

**Files:**

- Create: `src/agency/views/cockpit.py`
- Create: `tests/unit/test_cockpit_contract.py`
- Modify: `src/agency/dashboard.py`
- Modify: `src/agency/views/__init__.py`

**Implementation Shape:**

Add `cockpit_context()` returning:

- `cycle`
- `market`
- `engines`
- `funnel`
- `candidates`
- `positions`
- `account`
- `sectors`
- `sources`
- `universe_blocked`
- `signals`
- `audit_lifecycle`
- `policy`
- `monitor_events`
- `scenario`

Map from existing sources:

- `dashboard_context()` and command view-models for review queue and readiness.
- `full_live_readiness_view()` for critical readiness.
- `data_load_status_view()` for data freshness and sources.
- `scheduler_work_queue_view()` for jobs and lane status.
- `execution_preview_context()` for staged paper-order preview fields.
- `portfolio_monitor_context()` for positions.
- `market_regime_context()` for market and sector fields.
- `signal_dashboard_rows()` for signal evidence rows.

**Steps:**

- [ ] Step 1: Write failing tests for the contract keys and no prototype data.

  Test names:

  - `test_cockpit_context_has_required_top_level_sections`
  - `test_cockpit_context_uses_real_dashboard_sources_not_prototype_data`
  - `test_cockpit_candidates_are_sorted_by_final_conviction`
  - `test_cockpit_only_agent_approved_candidates_are_actionable`
  - `test_cockpit_derived_values_are_not_hardcoded`

  Run:

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_contract.py -q
  ```

  Expected before implementation: fails because `src.agency.views.cockpit` does not exist.

- [ ] Step 2: Implement `cockpit_context()` with typed helper functions.

  Required helper boundaries:

  - `_cycle_section(...)`
  - `_engine_rows(...)`
  - `_funnel_section(...)`
  - `_candidate_rows(...)`
  - `_position_rows(...)`
  - `_account_section(...)`
  - `_source_rows(...)`
  - `_signal_rows(...)`
  - `_scenario_from_context(...)`

- [ ] Step 3: Ensure no prototype default decisions.

  Reject any default state that pre-approves `NVDA`, `HD`, `UNH`, or closes `XOM` unless those values come from real current reports.

- [ ] Step 4: Run targeted tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_contract.py -q
  ```

- [ ] Step 5: Run regression tests for current dashboard context.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py::test_command_dashboard_template_places_review_queue_before_system_health tests\unit\test_data_load_status.py -q
  ```

- [ ] Step 6: Run hardcoded scan.

  ```powershell
  rg -n "window\.COCKPIT_DATA|EDITMODE|C-14:32|14:30|grossPostTrade.*84|Math\.random" src/agency
  ```

  Expected: no hits in production code.

**Ticket DoD:**

- Contract exists and is backed by real current app sources.
- Unit tests prove no prototype constants or demo decisions.
- Candidate actionability is explicit.
- Scenario field is computed but does not yet drive UI.

---

## Ticket 2: Cockpit Routes And Read-Only API

**Goal:** Expose the cockpit as a parallel production route and read-only JSON endpoints without replacing the current command dashboard yet.

**Files:**

- Modify: `src/agency/dashboard.py`
- Create: `tests/unit/test_cockpit_routes.py`
- Create: `src/agency/templates/cockpit.html`

**Routes:**

- `GET /cockpit` renders the cockpit page.
- `GET /api/cockpit` returns the full cockpit snapshot.
- `GET /api/cycle` returns only cycle, market, engines, scenario.
- `GET /api/audit/{ticker}` returns ticker lifecycle trace from existing audit/candidate timeline.

Do not implement write endpoints yet.

**Steps:**

- [ ] Step 1: Write failing route tests.

  Test names:

  - `test_cockpit_route_renders`
  - `test_api_cockpit_returns_contract`
  - `test_api_cycle_returns_lightweight_sections`
  - `test_api_payloads_are_bounded_and_secret_free`
  - `test_api_payloads_do_not_use_artifact_fallback_as_proof`
  - `test_api_routes_do_not_collide_with_existing_namespaces`
  - `test_api_audit_rejects_invalid_ticker`
  - `test_api_audit_normalizes_ticker`
  - `test_api_audit_returns_trace_for_known_ticker`

  Run:

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_routes.py -q
  ```

- [ ] Step 2: Add route handlers in `src/agency/dashboard.py`.

  Keep them thin:

  - import `cockpit_context`
  - return template or JSON
  - no data processing in route bodies

- [ ] Step 3: Add a minimal `cockpit.html` skeleton that renders a BLUF and section counts from `cockpit_context`.

- [ ] Step 4: Run targeted tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_routes.py -q
  ```

- [ ] Step 5: Run existing FastAPI route smoke tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py tests\e2e\test_first_version_smoke.py -q
  ```

**Ticket DoD:**

- `/cockpit` exists.
- Current `/` and `/command` behavior is unchanged.
- JSON endpoints return only production-derived data.
- JSON endpoints do not expose credentials, raw account IDs, raw env values, browser session paths, or artifact-fallback proof.
- JSON endpoints limit row counts and normalize ticker input.
- No write or broker operation is exposed from these endpoints.

---

## Ticket 3: Scenario Routing And Safety States

**Goal:** Implement normal, no-actionable, outage, and submitted scenarios as first-class cockpit states.

**Files:**

- Modify: `src/agency/views/cockpit.py`
- Modify: `src/agency/templates/cockpit.html`
- Create or Modify: `tests/unit/test_cockpit_state.py`

**Rules:**

- `outage`: any critical engine is `down`; no candidates are actionable in the UI.
- `no-actionable`: pipeline completed, no actionable candidates, critical engines not down.
- `submitted`: current cycle already has submitted broker acknowledgements.
- `normal`: at least one reviewable or actionable current-cycle item and no outage/submitted state.
- `stale` is not a user-facing state label. Display the reason: data exists but needs refresh, data unavailable, access problem, or analysis not run.
- QA scenario overrides are not allowed until Ticket 9 adds the dev flag. Before that point, scenario tests must use mocked view-model inputs, not query params or production-facing override routes.

**Steps:**

- [ ] Step 1: Write failing tests for all four scenarios.

  Test names:

  - `test_outage_scenario_when_critical_engine_down`
  - `test_stale_noncritical_engine_does_not_trigger_outage`
  - `test_no_actionable_scenario_when_funnel_completed_without_ready_candidates`
  - `test_submitted_scenario_when_cycle_has_broker_ack`
  - `test_scenario_copy_never_uses_stale_as_primary_user_status`
  - `test_no_actionable_state_has_skip_to_portfolio_and_closest_candidate_explanations`
  - `test_outage_state_has_engine_cards_retry_countdown_and_last_good_cycle`
  - `test_qa_scenario_override_requires_dev_flag`

- [ ] Step 2: Implement `_scenario_from_context(...)`.

- [ ] Step 3: Add scenario-specific BLUF copy in the template.

  Required BLUF examples:

  - Normal: `{n} trades ready. Approve what you want to ship today.`
  - No actionable: `Nothing actionable today. The agent already filtered the universe.`
  - Outage: `Selection is paused because critical data is unavailable.`
  - Submitted: `{n} paper orders were transmitted for this cycle.`

- [ ] Step 4: Run targeted tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_state.py -q
  ```

- [ ] Step 5: Browser smoke each scenario via test fixtures or query-param test mode.

  Before Ticket 9, use mocked view-model fixtures only. After Ticket 9, query-param scenario mode is allowed only when `AGENCY_COCKPIT_QA_SCENARIOS=true`, and the page must display a non-operational QA banner.

  Use Playwright or Browser Use and capture screenshots to:

  `research/results/ux-redesign-v3-qa/ticket-03/`

**Ticket DoD:**

- All scenarios render with plain-English next action.
- Outage blocks submit visually and functionally.
- No-actionable is calm, not alarming.
- No-actionable includes skip-to-portfolio, closest-candidate explanation cards, and an agent note.
- Outage includes critical engine cards, retry countdown, and last-good-cycle context.
- Submitted state shows broker/order evidence if present.
- No visible primary label says only `stale`.
- QA scenario pages are visibly non-operational and never count as readiness proof.

---

## Ticket 4: Variation A Shell, Tokens, And First Viewport

**Goal:** Render the Pre-Flight Cockpit shell with BLUF, topbar, instrument cluster, engine strip, instruments nav, and phase rail.

**Files:**

- Modify: `src/agency/templates/cockpit.html`
- Modify: `src/agency/templates/base.html` only if route nav needs a Cockpit link
- Modify: `src/agency/static/styles.css`
- Create or Modify: `tests/unit/test_cockpit_views.py`
- Create: `scripts/check_cockpit_ux_qa.py`

**Design Rules:**

- Amber primary accent.
- Monospace for all numbers.
- No new icon library.
- Sharp cards and panels, border radius no more than 4px except pills.
- No decorative gradients, blobs, or ambient motion.
- BLUF is the first meaningful content after the app shell.
- Review queue must remain near the top; diagnostics do not bury actions.
- Variation A visual primitives are required: half-circle arc gauges, 7-segment readouts, four-cell phase rail, WhyMark threshold explanations, and compact conviction dials in candidate rows.

**Steps:**

- [ ] Step 1: Write failing template tests.

  Test names:

  - `test_cockpit_template_has_bluf_before_diagnostics`
  - `test_cockpit_template_has_phase_rail`
  - `test_cockpit_template_has_four_phase_cells`
  - `test_cockpit_template_has_arc_gauge_primitives`
  - `test_cockpit_template_has_segment_readouts`
  - `test_cockpit_template_has_whymark_threshold_tips`
  - `test_cockpit_template_has_engine_strip_with_data_hooks`
  - `test_cockpit_template_has_instrument_nav`
  - `test_cockpit_template_uses_mono_class_for_numeric_readouts`

- [ ] Step 2: Add CSS token mapping.

  Map prototype roles to existing app tokens:

  - accent amber: `--accent`
  - pass green: `--pass`
  - warn amber: `--warn`
  - block red: `--block`
  - LLM/info cyan: `--info`
  - panels: `--surface`

- [ ] Step 3: Build the top shell sections in `cockpit.html`.

  Sections:

  - cockpit topbar
  - BLUF briefing
  - instrument cluster with Market Regime, Gross Exposure, Cash Reserve, and Concentration arc gauges
  - 7-segment-style readouts for Buying Power, Ready to Trade, and P/L Week
  - engine strip
  - five-button instrument nav: Universe, Signals, Audit, Policy, Monitor
  - four-cell phase rail: Candidates, Portfolio, Clearance, Cleared
  - active phase container

- [ ] Step 4: Preserve current live data polling hooks where reused.

  Do not rename existing `data-*` hooks without updating the polling JavaScript and tests.

- [ ] Step 5: Run template tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_views.py -q
  ```

- [ ] Step 6: Run browser screenshot QA at 1920x1080 and 1366x768.

  ```powershell
  .\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8000/cockpit --scenario normal --output research/results/ux-redesign-v3-qa/ticket-04
  ```

  If the script does not exist yet, create it in this ticket with Playwright checks for:

  - HTTP 200
  - no console errors
  - no horizontal scroll
  - BLUF visible in first viewport
  - review phase visible in first viewport
  - screenshot saved

**Ticket DoD:**

- First viewport reads as cockpit, not old dashboard.
- BLUF and candidate phase are immediately visible.
- Required Variation A primitives render with real data and explanatory threshold tips.
- No unreadable contrast or overlapping text in screenshots.
- No production CSS imports from prototype standalone HTML.

---

## Ticket 5: Candidate Phase And Evidence-First Rows

**Goal:** Implement Phase 1 with ranked candidate rows, plain-English evidence, visible risks, status chips, user decisions, inline expansion, and ticker deep-dive entry.

**Files:**

- Modify: `src/agency/views/cockpit.py`
- Modify: `src/agency/templates/cockpit.html`
- Modify: `src/agency/static/styles.css`
- Create or Modify: `tests/unit/test_cockpit_candidates.py`

**Required Row Data:**

- rank
- ticker
- sector
- final conviction
- deterministic score
- LLM score or `LLM not run for this ticker`
- one-line evidence with hard value
- one-line risk with hard value or `No major risk flag in current pack`
- compact conviction dial plus mono score
- evidence tier styling for confirmed, inferred, and suppressed items
- status chip
- approve, defer, reject controls only for actionable rows
- audit link for non-actionable rows

**Steps:**

- [ ] Step 1: Write failing candidate view-model tests.

  Test names:

  - `test_candidate_row_includes_concrete_evidence_not_generic_copy`
  - `test_candidate_row_includes_concrete_risk_or_clear_empty_state`
  - `test_candidate_row_uses_conviction_dial_and_mono_score`
  - `test_candidate_evidence_tiers_are_visually_distinct`
  - `test_candidate_evidence_thresholds_have_whymark_tips`
  - `test_blocked_candidate_has_audit_link_not_approve_button`
  - `test_llm_not_run_copy_is_explicit_for_non_top_ten`
  - `test_candidate_status_copy_is_operator_facing`

- [ ] Step 2: Implement `cockpit_candidate_rows(...)` helpers.

  Reuse existing candidate evidence helpers where possible:

  - `candidate_decision_brief`
  - signal evidence grouping
  - candidate email evidence
  - risk gates

- [ ] Step 3: Implement template row and inline expansion.

  Use vanilla JS for expansion:

  - row click toggles expansion
  - ticker link opens existing candidate detail route or future overlay
  - action buttons do not trigger row toggle accidentally

- [ ] Step 4: Ensure decisions are staged, not submitted.

  Store phase, decisions, and exits in per-cycle localStorage with a restore prompt. Also keep hidden form fields for submission staging. Submit integration happens later.

  Never store:

  - submit gate state
  - typed confirmation phrase
  - broker response
  - submit-in-progress state

- [ ] Step 5: Run targeted tests and browser QA.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_candidates.py tests\unit\test_fastapi_app.py -q
  .\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --scenario normal --focus candidates --output research/results/ux-redesign-v3-qa/ticket-05
  ```

**Ticket DoD:**

- User can answer: why this stock, what risk, what action.
- Non-actionable rows are visible but cannot be approved.
- LLM top-10 policy is clear and does not look like missing data.
- Candidate text is not generic and includes concrete values where available.
- Evidence hierarchy is visible in the row and expansion.
- Phase/decision/exits restore prompt works per cycle, while gate/phrase never restore.
- Browser screenshot shows no clipped decision buttons.

---

## Ticket 6: Portfolio Phase And Capacity Impact

**Goal:** Implement Phase 2 with existing positions, keep/close decisions, and capacity meters that respond to staged candidate approvals.

**Files:**

- Modify: `src/agency/views/cockpit.py`
- Modify: `src/agency/templates/cockpit.html`
- Modify: `src/agency/static/styles.css`
- Create or Modify: `tests/unit/test_cockpit_portfolio.py`

**Rules:**

- Position P/L is derived from current and entry prices.
- Stop distance is derived from current and stop.
- Gross post-trade is derived from staged orders.
- Cash reserve is derived from account state and staged notional.
- Exits are shown before buys in clearance.
- Zero-position state is explicit.
- Phase 2 starts with a BLUF decision sentence, not the label `Portfolio`.

**Steps:**

- [ ] Step 1: Write failing tests for derived values and zero-position state.

  Test names:

  - `test_portfolio_position_pl_is_derived_from_prices`
  - `test_capacity_gross_post_trade_uses_staged_orders`
  - `test_zero_position_portfolio_has_explicit_empty_state`
  - `test_portfolio_phase_starts_with_bluf_sentence`
  - `test_close_candidate_requires_keep_or_close_before_clearance`
  - `test_capacity_warning_names_rule_value_and_user_action`
  - `test_capacity_thresholds_have_whymark_tips`

- [ ] Step 2: Implement portfolio and account helpers.

- [ ] Step 3: Add Phase 2 template.

  Include:

  - phase-level BLUF, for example `Review current positions before clearing today's manifest.`
  - positions table
  - keep/close controls
  - gross exposure meter
  - sector exposure meter
  - cash reserve meter
  - plain-English capacity warning
  - WhyMark tips explaining gross exposure, sector exposure, and cash reserve thresholds

- [ ] Step 4: Add JavaScript to recompute displayed staged capacity when candidate decisions change.

  Keep the authoritative validation server-side in later submit ticket.

- [ ] Step 5: Run tests and browser QA.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_portfolio.py tests\unit\test_portfolio_monitor.py -q
  .\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --scenario normal --focus portfolio --output research/results/ux-redesign-v3-qa/ticket-06
  ```

**Ticket DoD:**

- Portfolio phase works with positions, review positions, close candidates, and zero positions.
- Capacity meters update locally and are revalidated later on submit.
- Warnings name the rule and value.
- Phase-level BLUF is visible above the table.
- No derived value is stored as a hardcoded prototype number.

---

## Ticket 7: Clearance Phase, Submit Gate, And Paper Submit Integration

**Goal:** Implement the gated clearance flow while preserving current paper-trading safety.

**Files:**

- Modify: `src/agency/views/cockpit.py`
- Modify: `src/agency/dashboard.py`
- Modify: `src/agency/templates/cockpit.html`
- Modify: `src/agency/static/styles.css`
- Create or Modify: `tests/unit/test_cockpit_clearance.py`
- Modify: `tests/unit/test_fastapi_app.py`

**Submit Rules:**

- Exits first.
- Staged buys second.
- Gate starts closed every page load.
- Phrase is exactly `submit paper orders`.
- Submit button is disabled until checkbox and phrase are both complete.
- Server revalidates human approval, order intent hash, policy gates, broker state, critical source freshness, and current orderability immediately before broker submit.
- Server recomputes order side, quantity, limit, notional, stop, target, and exits from the current `execution_preview_context`; hidden form fields are treated as user intent hints only.
- Tampered hidden fields are rejected with a clear error.
- Multi-order partial failure behavior: accepted orders are recorded with broker IDs, rejected orders remain in the manifest with exact broker/error text, and the success state is `partial` until the user reviews the rejected rows.
- Paper only.
- `LIVE_TRADING` locked off.
- Phase 3 starts with a BLUF decision sentence, not the label `Clearance`.

**Steps:**

- [ ] Step 1: Write failing tests for gate behavior and server safety.

  Test names:

  - `test_clearance_gate_starts_closed`
  - `test_clearance_phrase_never_persists`
  - `test_submit_disabled_until_gate_and_phrase`
  - `test_clearance_phase_starts_with_bluf_sentence`
  - `test_cockpit_submit_reuses_execution_freshness_gate`
  - `test_cockpit_submit_recomputes_order_intent_from_execution_preview`
  - `test_cockpit_submit_rejects_tampered_hidden_fields`
  - `test_cockpit_submit_handles_partial_broker_failure`
  - `test_cockpit_submit_requires_order_intent_hash_match`
  - `test_cockpit_submit_rejects_live_trading`
  - `test_cockpit_submit_records_broker_order_ids`

- [ ] Step 2: Add `POST /cockpit/submit` or `POST /api/decisions`.

  Reuse or refactor the existing execution-preview approval/submit path. Do not create a second paper-submit implementation. The cockpit endpoint must call the same freshness, approval, order-intent hash, and broker submission functions as the execution preview path.

- [ ] Step 3: Wire form/JS submission from cockpit clearance.

- [ ] Step 4: Show success and error states.

  Error copy must say:

  - what blocked submit
  - which rule or source caused it
  - what the user should do next

- [ ] Step 5: Run paper broker validation before browser submit QA.

  ```powershell
  .\.venv\Scripts\python scripts\run_paper_broker_validation.py
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_clearance.py tests\unit\test_fastapi_app.py -q
  ```

- [ ] Step 6: Browser QA the submit gate in non-submitting test mode first.

  The browser QA script must run with broker submission disabled by default. A real paper submit is allowed only with `--allow-paper-submit`, after the script has captured fresh readiness, broker validation, and an orderable execution preview.

  Capture:

  - gate closed
  - gate open phrase empty
  - gate open phrase correct
  - submitted state with mocked broker ack

**Ticket DoD:**

- UI cannot accidentally submit.
- Server cannot submit without current safety revalidation.
- Server-side recomputation rejects tampered client values.
- Partial broker failures are visible and auditable.
- Success state shows real broker IDs in paper mode.
- Error states are actionable.
- Existing execution preview submit tests still pass.

---

## Ticket 8: Instrument Panels And Overlays

**Goal:** Implement the six cockpit panels with real production data and consistent modal behavior.

**Files:**

- Create: `src/agency/templates/_cockpit_panels.html`
- Modify: `src/agency/templates/cockpit.html`
- Modify: `src/agency/views/cockpit.py`
- Modify: `src/agency/static/styles.css`
- Create or Modify: `tests/unit/test_cockpit_panels.py`

**Panels:**

- Universe: data sources, coverage, blocked tickers, PIT integrity.
- Signals: evidence log with confirmed, inferred, suppressed filters.
- Audit: lifecycle trace and reproducibility note.
- Policy: deployed versus staged policy values; apply next cycle only.
- Monitor: event stream list, with SSE in a later ticket if not ready here.
- Ticker Detail: ticker hero, order preview, factor breakdown, evidence pack, LLM rationale, gates. This is a deep-dive overlay opened from ticker clicks, not a top-level instrument nav button.

**Steps:**

- [ ] Step 1: Write failing tests for panel presence and real data bindings.

  Test names:

  - `test_cockpit_has_all_six_instrument_panels`
  - `test_instrument_nav_has_five_buttons_and_excludes_ticker_detail`
  - `test_ticker_detail_opens_from_ticker_click`
  - `test_universe_panel_uses_source_health_rows`
  - `test_signals_panel_explains_tier_ladder`
  - `test_ticker_panel_shows_llm_rationale_or_not_run_reason`
  - `test_audit_panel_shows_cycle_and_evidence_hash_when_available`
  - `test_policy_panel_locks_live_trading`
  - `test_monitor_panel_has_live_or_last_event_timestamp`

- [ ] Step 2: Implement modal HTML using a shared macro.

  Required behavior:

  - five instrument nav buttons open Universe, Signals, Audit, Policy, and Monitor
  - ticker click opens Ticker Detail
  - Esc closes panel
  - click outside closes panel
  - close button text is clear
  - focus returns to trigger

- [ ] Step 3: Implement panel content using existing view models.

- [ ] Step 4: Browser QA every panel.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_panels.py -q
  .\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --focus panels --output research/results/ux-redesign-v3-qa/ticket-08
  ```

**Ticket DoD:**

- All six panels open, render real data, scroll, and close cleanly.
- Instrument nav has five buttons; ticker detail is reached from ticker context.
- Panel copy explains the data source and user action.
- No panel shows raw internal lane IDs as its main user-facing label.

---

## Ticket 9: Preferences, Calm Mode, And Scenario QA Toggle

**Goal:** Ship product-safe user preferences and QA-only scenario switching without exposing prototype design tooling.

**Files:**

- Modify: `src/agency/templates/cockpit.html`
- Modify: `src/agency/static/styles.css`
- Create: `src/agency/static/cockpit.js`
- Create or Modify: `tests/unit/test_cockpit_preferences.py`

**Preferences:**

- color preset: amber, duotone, saturated
- theme: dark, accent, light
- density: full, calm

Defaults:

- color preset: amber
- theme: accent
- density: full during active review, calm remains manual unless the user later approves auto-calm

**QA-only:**

- scenario override behind `AGENCY_COCKPIT_QA_SCENARIOS=true` or an equivalent dev flag.
- No scenario override in normal production mode.

**Steps:**

- [ ] Step 1: Write failing tests for preference UI and QA gating.

  Test names:

  - `test_cockpit_preferences_include_color_theme_density`
  - `test_cockpit_preferences_default_to_amber_accent_full`
  - `test_live_trading_is_not_a_tweak`
  - `test_scenario_override_is_hidden_without_dev_flag`
  - `test_qa_scenario_override_banner_marks_non_operational`
  - `test_calm_mode_hides_nonessential_chrome_but_keeps_actions`

- [ ] Step 2: Implement settings overlay, not draggable floating card.

- [ ] Step 3: Persist tweak preferences in localStorage.

  Never persist:

  - submit gate
  - typed phrase
  - broker submit state

- [ ] Step 4: Add CSS selectors for themes and density.

- [ ] Step 5: Browser QA preference combinations.

  Pairwise matrix for normal operation:

  - amber/dark/full
  - amber/accent/calm
  - duotone/accent/full
  - saturated/dark/full
  - amber/light/full
  - duotone/light/calm

  Full critical matrix for QA-flagged states:

  - every scenario with amber/accent/full
  - every scenario with amber/accent/calm
  - outage with dark, accent, and light themes
  - clearance gate ready with amber, duotone, and saturated color presets

**Ticket DoD:**

- Preferences work and persist.
- Calm mode is useful between cycles.
- Light theme is readable.
- Defaults match the expert handoff.
- Every QA scenario page is clearly marked non-operational.
- Scenario toggle cannot confuse production users or count as readiness proof.

---

## Ticket 10: Monitor Stream And Live Status Reliability

**Goal:** Make cockpit health and monitor data live enough to trust, with meaningful age, source, and action labels.

**Files:**

- Modify: `src/agency/dashboard.py`
- Modify: `src/agency/views/cockpit.py`
- Create: `src/agency/runtime/cockpit_monitor.py`
- Modify: `src/agency/templates/cockpit.html`
- Create or Modify: `tests/unit/test_cockpit_monitor.py`

**Rules:**

- Display health proof timestamp.
- Display source timestamp.
- Display analysis timestamp when different.
- Do not say only `fresh` without a timestamp.
- Do not say only `stale`; classify as unavailable, available-not-analyzed, analyzed-but-needs-refresh, access problem, or blocked by policy.
- Show refresh action where a lane can be refreshed.
- Show live indicators only when the UI is receiving current monitor updates, not merely because old status rows exist.

**Steps:**

- [ ] Step 1: Write failing monitor tests.

  Test names:

  - `test_monitor_event_rows_include_timestamp_topic_and_action`
  - `test_health_rows_include_proof_timestamp`
  - `test_cockpit_does_not_display_fresh_without_timestamp`
  - `test_cockpit_replaces_stale_with_actionable_state_copy`
  - `test_refreshable_lane_has_refresh_action`
  - `test_live_indicator_requires_recent_monitor_update`

- [ ] Step 2: Implement `/api/monitor/stream` SSE if current runtime events are available.

  If SSE needs more backend work, implement a polling endpoint first and record SSE as a follow-up ticket. Do not fake live streaming.

- [ ] Step 3: Wire monitor panel updates.

- [ ] Step 4: Run data-load and scheduler regressions.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_monitor.py tests\unit\test_data_load_status.py tests\unit\test_scheduler_work_queue.py -q
  ```

- [ ] Step 5: Browser QA monitor and source panels.

**Ticket DoD:**

- Cockpit health data has proof timestamps.
- Health states are plain English and actionable.
- Refresh actions use the lane model.
- No live indicator is shown unless the underlying status really updates.

---

## Ticket 11: Policy Panel With Diff And Confirm

**Goal:** Implement the policy editor as a safe staged editor, not a prototype-only slider panel, while staying compatible with the existing policy write route.

**Files:**

- Modify: `src/agency/views/cockpit.py`
- Modify: `src/agency/dashboard.py`
- Modify: `src/agency/templates/_cockpit_panels.html`
- Create or Modify: `tests/unit/test_cockpit_policy.py`

**Rules:**

- Show deployed value.
- Show staged value after edit.
- Show diff before apply.
- Confirm `Apply next cycle`.
- Never mutate current-cycle decisions silently.
- `LIVE_TRADING` locked off.
- Dangerous flags visibly explain risk.
- Reuse the existing policy write semantics. If the repo already exposes `POST /api/policy`, the cockpit must use that route or refactor it without introducing a conflicting duplicate `PUT /api/policy`.

**Steps:**

- [ ] Step 1: Write failing tests.

  Test names:

  - `test_policy_panel_shows_deployed_and_staged_values`
  - `test_policy_apply_requires_confirmation`
  - `test_policy_changes_apply_next_cycle_copy`
  - `test_cockpit_policy_uses_existing_policy_write_route`
  - `test_cockpit_policy_does_not_introduce_conflicting_put_route`
  - `test_live_trading_flag_is_locked_off`
  - `test_policy_change_invalidates_staged_submit_until_revalidated`

- [ ] Step 2: Wire cockpit policy writes through existing policy persistence.

  First inspect the current route. If `POST /api/policy` is the existing production contract, use it. Only add `PUT /api/policy` if it replaces the old route through a compatibility shim and tests prove both semantics do not conflict.

- [ ] Step 3: Add diff display in the panel.

- [ ] Step 4: Run policy and execution regression tests.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_policy.py tests\unit\test_policy_persistence.py tests\unit\test_paper_trade_promotion.py -q
  ```

**Ticket DoD:**

- Policy editing is understandable and safe.
- The user sees what changed and when it applies.
- No live trading toggle can be enabled in v1.
- Cockpit policy writes do not mutate current-cycle submit state silently.

---

## Ticket 12: Cockpit Browser QA Script And Visual Matrix

**Goal:** Add a repeatable browser QA suite for the cockpit so visual regressions are caught before user review.

**Files:**

- Create: `scripts/check_cockpit_ux_qa.py`
- Create: `tests/unit/test_cockpit_ux_qa_script.py`
- Create output at runtime only: `research/results/ux-redesign-v3-qa/<ticket>/`

**Script Requirements:**

- Start or use local server URL with a known runtime DB.
- Default environment:

  ```powershell
  $env:DATABASE_URL="sqlite+aiosqlite:///research/results/agency-scheduler.sqlite"
  ```

- Preflight these endpoints before screenshots:

  - `/status/data-load`
  - `/status/full-live-readiness`
  - `/status/data-sources`
  - `/status/execution-preview`

- Visit `/cockpit`.
- Check no console errors.
- Check no page errors.
- Check no horizontal scroll.
- Check first BLUF visible.
- Check phase/candidate area visible.
- Check submit gate disabled until armed and phrase typed.
- Never call real broker submit routes unless `--allow-paper-submit` is passed.
- Refuse `--allow-paper-submit` unless preflight shows fresh broker/readiness evidence and at least one orderable execution preview.
- Open all panels and screenshot them.
- Test viewports:
  - 1920x1080
  - 1366x768
  - 1280x720
  - 390x844 fallback, not full kiosk support but must not break.

**Steps:**

- [ ] Step 1: Write unit tests for script argument parsing and failure behavior.

- [ ] Step 2: Implement the script using Playwright.

- [ ] Step 3: Run no-broker-submit mode against the local app.

  ```powershell
  $env:DATABASE_URL="sqlite+aiosqlite:///research/results/agency-scheduler.sqlite"
  .\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8000/cockpit --output research/results/ux-redesign-v3-qa/full-matrix
  ```

- [ ] Step 4: Add the script to developer docs or the final handoff.

**Ticket DoD:**

- Browser QA is repeatable.
- Screenshots are saved.
- The script fails on unreadable or structurally broken cockpit states.
- Dynamic timestamps do not cause false failures.
- The script cannot accidentally submit paper orders.
- The script records the readiness/preflight JSON it used.

---

## Ticket 13: No Demo Data, No Prototype Leakage, No Stale Presentation Gate

**Goal:** Add guardrails that prevent prototype data, demo strings, stale labels, and hidden fallback artifacts from entering production cockpit paths.

**Files:**

- Create: `tests/unit/test_cockpit_no_demo_data.py`
- Modify: `src/agency/views/cockpit.py`
- Modify: `scripts/check_cockpit_ux_qa.py`
- Modify: `scripts/check_dashboard_live_data_qa.py`

**Steps:**

- [ ] Step 1: Write failing scan tests.

  Test names:

  - `test_cockpit_production_paths_do_not_reference_window_cockpit_data`
  - `test_cockpit_production_paths_do_not_reference_editmode`
  - `test_cockpit_no_prototype_cycle_or_time_constants`
  - `test_cockpit_no_random_demo_order_ids`
  - `test_cockpit_no_hidden_artifact_fallback_as_readiness_proof`
  - `test_cockpit_no_primary_stale_label`

- [ ] Step 2: Implement helper scans or assertions.

- [ ] Step 3: Run scans.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_no_demo_data.py -q
  rg -n "window\.COCKPIT_DATA|EDITMODE|C-14:32|14:30|grossPostTrade.*84|Math\.random|ALP-" src scripts research/config
  ```

- [ ] Step 4: Fix every production hit or explicitly whitelist test fixtures.

**Ticket DoD:**

- Production cockpit cannot use mock prototype data.
- User-facing stale presentation is replaced by actionable state copy.
- Hidden artifact fallback cannot be used as proof.

---

## Ticket 14: Raspberry Pi And Touch Hardening

**Goal:** Make the cockpit suitable for the Raspberry Pi kiosk target.

**Files:**

- Modify: `docs/deployment.md`
- Create or Modify: `scripts/start_dev.ps1`
- Create: `docs/raspberry-pi-cockpit.md`
- Modify: `src/agency/static/styles.css`
- Create: `src/agency/static/fonts/README.md`
- Create or Modify: `tests/unit/test_cockpit_pi_readiness.py`

**Requirements:**

- No CDN dependencies.
- Bundled WOFF2 fonts for the chosen sans and mono stacks, or a documented local fallback if font files are deferred.
- Touch targets at least 44px for primary actions.
- Tooltips work on tap or focus, not only hover.
- Kiosk route is local.
- API binds localhost by default unless explicitly configured otherwise.
- Cold load target is under 3 seconds on dev hardware; Pi result must be measured later.
- Idle CPU target: under 5 percent while the cockpit is open between cycles.
- Memory target: under 200 MB after 8 hours in kiosk mode.
- Animation target: 60 fps where possible and 30 fps minimum for gauge/phase/fly-to-manifest transitions.
- Kiosk launch docs include Chromium flags, systemd restart, cursor hiding, screen sleep disable, and local-only logs.

**Steps:**

- [ ] Step 1: Write static tests for no CDN references, bundled font declarations, and touch target classes.

- [ ] Step 2: Add Pi cockpit deployment docs.

- [ ] Step 3: Add CSS touch adjustments and local font declarations.

- [ ] Step 4: Browser QA at 1280x720 and touch-emulated viewport.

- [ ] Step 5: Add a Pi performance checklist to the handoff.

  Include:

  - cold load timing
  - idle CPU observation method
  - 8-hour memory observation method
  - kiosk restart check
  - local log file locations

**Ticket DoD:**

- Pi deployment path is documented.
- Touch-critical controls are usable.
- No external UI dependency is required.
- Performance and kiosk resilience checks are explicit, even if final Pi measurement is deferred until hardware access.

---

## Ticket 15: Controlled Paper-Trade Rehearsal

**Goal:** Prove the complete cockpit path from real current data to paper broker readiness.

**Files:**

- Modify only if rehearsal reveals bugs.
- Create runtime report: `research/results/ux-redesign-v3-qa/paper-rehearsal-YYYYMMDD-HHMM.md`

**Steps:**

- [ ] Step 1: Refresh operational readiness with market-closed context if applicable.

  ```powershell
  .\.venv\Scripts\python scripts\check_operational_readiness.py --min-queue 1
  .\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
  ```

- [ ] Step 2: Check execution-preview orderability.

  Fetch `/status/execution-preview` or the existing execution preview context and record:

  - orderable paper preview count
  - blocked/research-only count
  - broker readiness
  - exact blocker text for every staged/research-approved candidate

  If there are **0 orderable paper previews**, run the no-submit rehearsal branch:

  - prove the cockpit blocks submit
  - show exact blockers in plain English
  - do not seed demo candidates
  - do not force orderability
  - do not submit any broker order
  - record this as a valid safety rehearsal, not a successful trade rehearsal

- [ ] Step 3: Validate broker/paper setup.

  ```powershell
  .\.venv\Scripts\python scripts\run_paper_broker_validation.py
  ```

- [ ] Step 4: Open `/cockpit`.

  Check:

  - BLUF is current.
  - health proof timestamps are visible.
  - candidate evidence is concrete.
  - LLM top-10 status is visible where relevant.
  - approve/defer/reject work.
  - portfolio capacity updates.
  - clearance gate stays disabled until armed and phrase typed.

- [ ] Step 5: Submit only in paper mode and only after broker validation is green and the current cycle has at least one orderable paper preview.

- [ ] Step 6: Verify submitted order visibility.

  Check:

  - cockpit submitted state
  - execution preview
  - broker validation script
  - Alpaca paper dashboard if user wants manual confirmation

- [ ] Step 7: Record results in the rehearsal report.

**Ticket DoD:**

- Full cockpit path is proven.
- If orderable paper previews exist, paper order evidence is visible after submit.
- If orderable paper previews do not exist, cockpit block behavior and exact blockers are proven without any demo/forced order.
- Any failure becomes a new prioritized backlog ticket before continuing.

---

## Ticket 16: Default Route Decision And Handoff

**Goal:** Decide whether the cockpit replaces the command dashboard, then produce a clean handoff.

**Files:**

- Modify: `src/agency/templates/base.html`
- Modify: `src/agency/dashboard.py`
- Create: `docs/handoff-2026-05-22-ux-redesign-v3-cockpit.md`

**Options:**

1. Keep `/cockpit` parallel and link it first in nav.
2. Make `/` render cockpit and keep old command dashboard at `/command`.
3. Keep old default until one more live paper-trade cycle passes.

Recommended: option 1 until the user completes manual review.

**Steps:**

- [ ] Step 1: Write route/navigation tests for chosen option.

- [ ] Step 2: Implement navigation/default route change.

- [ ] Step 3: Run full focused suite.

  ```powershell
  .\.venv\Scripts\python -m pytest tests\unit\test_cockpit_contract.py tests\unit\test_cockpit_routes.py tests\unit\test_cockpit_state.py tests\unit\test_cockpit_views.py tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_portfolio.py tests\unit\test_cockpit_clearance.py tests\unit\test_cockpit_panels.py tests\unit\test_cockpit_preferences.py tests\unit\test_cockpit_monitor.py tests\unit\test_cockpit_policy.py tests\unit\test_cockpit_no_demo_data.py tests\unit\test_fastapi_app.py tests\unit\test_data_load_status.py tests\unit\test_scheduler_work_queue.py -q
  .\.venv\Scripts\python -m pytest tests\unit\test_ops_scripts.py tests\unit\test_massive_stock_trades.py tests\unit\test_massive_orchestrator.py tests\unit\test_data_refresh_progress.py tests\unit\test_scheduler_runner.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_reports_api.py tests\unit\test_risk_api.py -q
  ```

- [ ] Step 4: Run browser QA.

  ```powershell
  .\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8000/cockpit --output research/results/ux-redesign-v3-qa/final
  ```

- [ ] Step 5: Write handoff with:

  - branch and commit
  - what shipped
  - exact commands run
  - screenshots path
  - known limitations
  - next recommended ticket

**Ticket DoD:**

- User has a clear cockpit entrypoint.
- Old dashboard remains available unless explicitly replaced.
- Handoff is complete enough to resume without memory.
- Large-file growth is explained and contained.

---

## Three Plan Improvement Cycles Completed

### Cycle 1: Design-Intent Coverage

Changes applied to this plan:

- Chose Variation A first as the default implementation path.
- Added non-negotiable design rules from the expert handoff.
- Added explicit prototype-only exclusions.
- Added BLUF, provenance, gated-submit, paper-only, and calm-density principles to the global rules.
- Added phase-level BLUF coverage for Candidates, Portfolio, and Clearance.
- Added required Variation A primitives: arc gauges, 7-segment readouts, phase rail, conviction dials, and WhyMark threshold explanations.
- Clarified that instrument nav has five buttons and Ticker Detail opens from ticker context.

Coverage check:

- 3-phase workflow is represented by Tickets 5, 6, and 7.
- Six instrument panels are represented by Ticket 8.
- Four scenarios are represented by Ticket 3 and screenshot QA in Ticket 12.
- Tweaks/preferences are represented by Ticket 9.
- Pi hardening is represented by Ticket 14.
- Session restore and outage freeze/revalidate behavior are represented by Tickets 5 and 7.

### Cycle 2: Production Integration And Safety Review

Changes applied to this plan:

- Kept implementation inside FastAPI/Jinja instead of porting React.
- Added `/cockpit` as a parallel route before replacing the current dashboard.
- Added current safety constraints for paper submit, order-intent hash, broker freshness, policy gates, and live-trading lockout.
- Added no direct broad stock-trade batch rule.
- Added data-health proof timestamps and actionable freshness wording.
- Added no-broker browser QA default and explicit `--allow-paper-submit` gate.
- Added JSON payload safety rules, policy-route compatibility, server-side order recomputation, tamper rejection, and partial broker failure behavior.
- Added no-submit rehearsal branch when a real current cycle has zero orderable paper previews.

Coverage check:

- Existing command dashboard remains available during migration.
- Execution preview safety semantics are preserved.
- Current data-lane and scheduler guardrails are preserved.
- `stale` is no longer accepted as a user-facing primary state.
- QA scenario overrides are non-operational and cannot count as readiness proof.

### Cycle 3: QA, DoD, And Regression Hardening

Changes applied to this plan:

- Added per-ticket Definition of Done loops.
- Added targeted pytest commands per ticket.
- Added hardcoded/demo scan gates.
- Added Playwright/browser screenshot QA.
- Added no-stale/no-hardcoded-data guard ticket.
- Added final controlled paper-trade rehearsal.
- Added guardrail regression suites for ops scripts, Massive lanes, scheduler runner, dashboard QA script, reports API, and risk API.
- Added large-file growth controls.
- Added browser QA preflight for data-load, full-live readiness, data sources, and execution preview.
- Added Pi performance, kiosk, local font, local log, and resilience checks.

Coverage check:

- Each ticket includes tests before implementation.
- Each UI ticket includes browser QA.
- Every major scenario is screenshot-tested.
- The plan has an improvement loop for every failed check before moving to the next ticket.

## Final Acceptance Criteria

The UX redesign implementation is complete only when:

- `/cockpit` renders a production cockpit with real current agency data.
- No prototype mock data or hardcoded demo constants are used in production paths.
- Normal, no-actionable, outage, and submitted states all render correctly.
- Candidate, portfolio, and clearance phases can be completed end-to-end.
- Paper submit works through existing broker safety gates.
- Every block/caution names the rule, value, reason, and next action.
- Health/status panels include proof timestamps and actionable refresh paths.
- LLM top-10 automatic review policy is clear in candidate evidence.
- Preferences work without exposing design-tool UI.
- Six instrument panels open and close cleanly with real data.
- Browser QA screenshots are green at target viewports.
- Focused pytest suite passes.
- A paper-trade rehearsal report exists.
- A clean handoff exists.

## Execution Recommendation

Use subagent-driven execution:

- One worker per ticket.
- One reviewer subagent per high-risk ticket.
- Parent agent reviews diffs, runs targeted tests, and updates the ticket status.
- Commit after each ticket.
- Do not batch unrelated tickets into one commit.

Suggested first execution slice:

1. Ticket 0: branch and checkpoint.
2. Ticket 1: cockpit contract.
3. Ticket 2: routes and read-only API.
4. Ticket 3: scenarios.
5. Ticket 4: shell and first viewport.

Stop for user visual review after Ticket 4 before implementing the deeper interaction tickets.
