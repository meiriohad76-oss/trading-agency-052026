# Trading Agency v2 - UX Audit Implementation Plan
Source: docs/audit-findings.md
Date: 2026-05-18

> This plan is the direct input for Codex UX improvement work.
> Execute tasks in order. Each task references the audit finding(s) it resolves.

---

## T001 - `final_selection.html`: Make the selection list actionable first
**Resolves:** F001, F019, F020, F021, F022, F040, F051
**File:** `src/agency/templates/final_selection.html` lines 16-155
**Change:** Rebuild the first viewport around Selected / Blocked / No-Trade KPIs, grouped WATCH / NO_TRADE / BLOCKED sections, action-colored badges, always-visible conviction plus top reasons and gate status, and move provenance and long rationale into standardized collapsed details.
**Acceptance:** The first viewport shows the three KPI counts and WATCH rows first, each actionable card shows ticker, conviction, gate status, and top reasons before expansion, and raw cycle/timestamp data is hidden in details.

---

## T002 - `dashboard.html`: Put the review queue and next step ahead of diagnostics
**Resolves:** F012, F013, F014, F015, F016, F017, F018, F026, F050
**File:** `src/agency/templates/dashboard.html` lines 12-187, 338-418, 1428
**Change:** Change the hero CTA to review the pending candidate count, add an above-fold LLM-disabled indicator, collapse Data Sources with other diagnostics, add Portfolio/Execute and exposure-warning affordances, and give review states plus Approve/Defer/Reject actions distinct icon-plus-color treatments.
**Acceptance:** Opening the Command dashboard shows a "Review X candidates" primary action, review queue path, LLM status, and exposure warning before expanded diagnostics; review states and actions are distinguishable by both icon and color.

---

## T003 - `candidate_detail.html`: Make the decision page navigable and evidence-focused
**Resolves:** F007, F008, F009, F010, F011, F018, F025, F035, F036, F049
**File:** `src/agency/templates/candidate_detail.html` lines 31-409
**Change:** Add a parent-list breadcrumb or next-candidate control, make recommendation plus conviction the dominant headline, show current-holding context, collapse supporting signals and provenance, color blocked signals red, add approval success/next-execution messaging, and rename Subscription Intelligence to Email/article evidence with Matched / Opened / Summarized / Score impact labels.
**Acceptance:** The first viewport contains navigation back to the list, a dominant recommendation and conviction, holding context when applicable, clear review actions, and no raw provenance or full signal lists until details are expanded.

---

## T004 - `portfolio_monitor.html`: Build the Step 2 portfolio decision surface
**Resolves:** F002, F003, F004, F027, F028, F029, F030, F031, F032, F033, F052
**File:** `src/agency/templates/portfolio_monitor.html` lines 21-220
**Change:** Add a top exposure summary, a calm empty state with Candidates CTA, position cards with styled P/L and stop/thesis context, a named Exit Recommendations panel with urgency, exposure freed, one confirm button, downstream effect text, no-exits-needed copy, and an Execution Preview link.
**Acceptance:** With positions and exit recommendations, the page shows exposure status, position cards, and one-click exit confirmations; with no positions, it explains why it is empty and links to Candidates.

---

## T005 - `portfolio_monitor.py`: Expose trailing-stop proximity and portfolio capacity data
**Resolves:** F023
**File:** `src/agency/services/portfolio_monitor.py` around line 248
**Change:** Add a trailing-stop proximity calculation for positions within five percentage points of triggering and expose the flag plus capacity values needed by the portfolio template.
**Acceptance:** A unit or view-model test with a position near the trailing-stop threshold returns a proximity warning flag that the template can render in amber or red.

---

## T006 - Risk and execution services: Promote approved WATCH candidates safely
**Resolves:** F005, F006
**Files:** `src/agency/services/risk.py` lines 409-419; `src/agency/services/execution_preview.py` around line 120
**Change:** Add a WATCH-to-ALLOW promotion path gated by human approval and paper-trade policy, then require that approval or promotion record in the `submit_enabled` calculation.
**Acceptance:** Tests prove an approved WATCH report can produce ALLOW and a READY preview flips `submit_enabled` from false to true only when the required approval/promotion record exists.

---

## T007 - `execution_preview.html`: Make paper order submission clear and confirmable
**Resolves:** F037, F038, F039, F054, F055
**File:** `src/agency/templates/execution_preview.html` lines 20-155
**Change:** Apply the shared paper-mode visual component, show inline post-submit confirmations, add LLM/rules conflict badges, add page-level LLM status, and add a bulk submit action for multiple ready paper orders.
**Acceptance:** Approved ready rows display a green Submit action, conflict rows show amber conflict status, paper mode is visually distinct, and successful submission renders confirmation inline.

---

## T008 - `risk.html`: Turn risk review into three clear tiers
**Resolves:** F041, F042, F043, F044, F045, F056
**File:** `src/agency/templates/risk.html` lines 12-217
**Change:** Replace current risk queues with Ready to review / Blocked by policy / Needs data tiers, add per-ready-row Execution Preview links, suppress passing checks into "Agent checked - OK", add deterministic-vs-LLM side-by-side display, and provide a collapsed candidate-by-dimension risk matrix.
**Acceptance:** A mixed risk dataset renders the three tiers in order, ready rows link to execution, LLM/deterministic comparison is visible, and detailed gate criteria appears only after expansion.

---

## T009 - LLM review surface: Provide row-ready disabled and rationale fields
**Resolves:** F034, F053
**Files:** `src/agency/services/llm_review.py` lines 130, 252, 332; consuming view models for Risk and Execution Preview
**Change:** Normalize LLM output into row-ready fields for action, disabled-state copy, one-line rationale, full rationale, conflicts, and system status so templates do not show blank LLM columns.
**Acceptance:** With LLM disabled, Risk and Execution Preview rows show "LLM review unavailable - rules-only"; with LLM enabled, each row has a one-line rationale and expandable full reasoning.

---

## T010 - `base.html`: Make the core workflow and status vocabulary obvious
**Resolves:** F024, F048, F057
**File:** `src/agency/templates/base.html` lines 27-84
**Change:** Add a distinct ordered Candidates / Portfolio / Execute nav group, mute secondary or placeholder screens, and add shared icon slots for pass, warning, blocked, pending, policy-locked, data, and agent states.
**Acceptance:** The left nav visually separates the three-step workflow from secondary screens and every top-level status type uses both color and icon.

---

## T011 - `styles.css`: Consolidate disclosure, paper-mode, action, and status styles
**Resolves:** F017, F018, F037, F046, F048, F050, F051
**File:** `src/agency/static/styles.css` lines 2376, 3321, 3777, 4081, 4354 and related tag/button styles
**Change:** Define or replace `tag-urgent`, create shared icon/color styles for review actions and statuses, create one amber/dashed paper-mode component, and consolidate all disclosure variants into a single summary/details pattern.
**Acceptance:** The CSS exposes one reusable disclosure pattern, one paper-mode component, and consistent pass/warn/block/action status styles used by the audited templates.

---

## T012 - `audit.html`: Collapse prompt audit detail and technical identifiers
**Resolves:** F047, F040
**File:** `src/agency/templates/audit.html` lines 104, 200, 255
**Change:** Show only short prompt-audit summaries by default, move full LLM rationale and raw run identifiers into details with monospace styling, and replace red paper-only tags with the shared paper-mode treatment.
**Acceptance:** Runtime Audit opens without full LLM rationales or long raw IDs visible, and paper-only status is shown with the same paper-mode styling as execution.
