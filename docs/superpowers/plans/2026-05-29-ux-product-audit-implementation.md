# UX Product Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development when explicit subagent delegation is available and authorized; otherwise use superpowers:executing-plans task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the 2026-05-29 UX/product audit so the agency gives operators a clear walk-me workflow, plain-language state, trustworthy freshness proof, and actionable candidate-to-paper-trade flow.

**Architecture:** Keep the current FastAPI/Jinja/V3 shell. Add thin view-model helpers where pages need shared operator vocabulary, status labels, workflow summaries, freshness labels, or trace rows. Avoid new runtime data sources; this pass reformats existing production state into better operator surfaces.

**Tech Stack:** Python, FastAPI, Jinja2 templates, vanilla CSS/JS, pytest, Ruff, existing Playwright/browser QA scripts.

---

## Global Rules

- Use `.\.venv\Scripts\python -m pytest`, not bare `pytest`.
- For each ticket group, write failing regression tests first, verify they fail, implement the smallest change, then rerun targeted and broader tests.
- Use Browser Use or existing Playwright QA scripts for template/CSS/JS changes before claiming completion.
- Do not weaken broker, approval, order-intent hash, freshness, policy, or paper-only safety gates.
- Do not use hardcoded/demo/prototype data as readiness proof.
- Keep visible copy operator-facing: what happened, why it matters, what the user can do next.

## Sprint 1: Command Dashboard Foundation

Tickets: T-UX-09, T-UX-10, T-UX-01, T-UX-05, T-UX-06, T-UX-21.

- [ ] Add tests in `tests/unit/test_ux_product_audit_20260529.py` proving `/command` has an Act zone before diagnostics, a checklist card, a review queue directly below it, four KPI tiles, visible freshness proof, and no visible internal jargon.
- [ ] Add shared operator vocabulary/status helpers in `src/agency/views/_shared.py`.
- [ ] Add `operator_checklist_context()` and dashboard freshness/impact context in `src/agency/views/command.py`.
- [ ] Restructure `src/agency/templates/dashboard.html` into Act and Diagnose zones, reducing KPI tiles to four.
- [ ] Hide the full email progress panel when idle and keep only a compact actionable alert when login/processing is active.
- [ ] Verify: targeted audit tests, existing UX audit tests, dashboard live-data QA script.

## Sprint 2: Navigation And Cockpit Workflow

Tickets: T-UX-02, T-UX-03, T-UX-12, T-UX-13, T-UX-14, T-UX-23, T-UX-24, T-UX-25.

- [ ] Add route/view tests for smart `/` redirect and sidebar workflow summary.
- [ ] Update root route in `src/agency/dashboard.py` to route to pending review, execution preview, or command.
- [ ] Update `base.html` navigation labels, section order, and workflow breadcrumb.
- [ ] Update `cockpit.html`, `cockpit.js`, and `views/cockpit.py` for dynamic titles, session-readiness wording, phase state attributes, and no numeric cockpit phase labels.
- [ ] Verify: cockpit route/state tests, V3 rollout tests, browser QA on `/cockpit` and `/command`.

## Sprint 3: Candidate And Execution Clarity

Tickets: T-UX-16, T-UX-17, T-UX-18, T-UX-19, T-UX-20, T-UX-22.

- [ ] Add tests for candidate page dynamic recommendation title, sticky-review context, evidence timestamps, and execution trace.
- [ ] Update `candidate_detail.html` and `views/candidates.py` with recommendation title, top reason, and evidence delta/freshness labels.
- [ ] Update `execution_preview.html` and `views/execution.py` to rename paper promotion to eligibility, hide hash from visible metrics, show order verified, and render a pipeline trace.
- [ ] Verify: execution service/view tests, UX audit tests, browser QA on candidate detail and execution preview.

## Sprint 4: Evidence, Tooltips, And Pipeline Polish

Tickets: T-UX-04, T-UX-07, T-UX-08, T-UX-11, T-UX-15, T-UX-26, T-UX-27.

- [ ] Add reusable evidence legend partial and include it anywhere evidence tiers appear.
- [ ] Add conviction tooltip everywhere conviction appears.
- [ ] Add cockpit clearance phrase feedback and JS tests/static assertions.
- [ ] Add `docs/TOOLTIP_REGISTRY.md` and complete dashboard tooltips.
- [ ] Add scheduler candidate impact summary.
- [ ] Verify: targeted tests, hardcoded/jargon scans, browser QA screenshots.

## Final Acceptance

- [ ] Run targeted UX suites:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_ux_product_audit_20260529.py tests\unit\test_ux_audit_implementation.py tests\unit\test_v3_ux_rollout.py -q
```

- [ ] Run route/runtime smoke tests:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_routes.py tests\unit\test_cockpit_state.py tests\unit\test_execution_preview_service.py -q
.\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
```

- [ ] Run dashboard/browser QA:

```powershell
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py --readiness-scope review-subset
.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8000/cockpit --focus panels --output research/results/ux-product-audit-20260529
```

- [ ] Run code hygiene:

```powershell
.\.venv\Scripts\python -m ruff check src\agency tests\unit\test_ux_product_audit_20260529.py
git diff --check
```

- [ ] Commit only after fresh verification is green.
