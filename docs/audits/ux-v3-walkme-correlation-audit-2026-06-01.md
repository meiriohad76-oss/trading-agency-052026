# UX V3 Walk-Me Correlation Audit - 2026-06-01

## Bottom Line

The user's complaint is valid.

The last 48 hours produced real cockpit code, tests, and several useful safety
improvements, but the visible product is not yet a faithful implementation of
the expert UX V3 / Variation A walk-me design.

The main failure is traceability: implementation moved into incremental cockpit
patches and narrow QA checks before the foundational visual and workflow parity
gate was truly satisfied. Several tickets were marked PASS based on unit tests,
route smoke, controlled fixtures, or "element exists" browser checks, while live
visual parity and complete operator-flow proof were either caveated or missing.

## Evidence Reviewed

- UX package:
  - `ux upgrade claude design 01062026/handoff/02-user-workflow.md`
  - `ux upgrade claude design 01062026/handoff/03-variation-a.md`
  - `ux upgrade claude design 01062026/handoff/05-components.md`
  - `ux upgrade claude design 01062026/handoff/variation-a/TICKETS.md`
  - `ux upgrade claude design 01062026/handoff/variation-a/DEFINITION-OF-DONE.md`
  - `ux upgrade claude design 01062026/handoff/variation-a/TESTING.md`
- Local implementation plan:
  - `docs/superpowers/plans/2026-06-01-ux-upgrade-cockpit-implementation.md`
- Recent commits:
  - `778cdac feat(cockpit): align shell with variation a`
  - `d18b7a9 feat(cockpit): preserve candidate ticker flow`
  - `74afb91 feat(cockpit): enrich ticker detail drawer`
  - `230a8db feat(cockpit): improve portfolio review phase`
  - `ecb92db feat(cockpit): clarify clearance submit gate`
  - `ea57556 feat(cockpit): enrich instrument signal panels`
  - `69ece00 feat(cockpit): clarify lane state visibility`
  - `c3dc87c feat(cockpit): harden scenario state flow`
  - `818fae9 feat(cockpit): make cockpit primary workflow`
  - `40ddac1 test(cockpit): rehearse full workflow`
  - `5153451 test(cockpit): add UX preservation gate`
  - `738b209 test(process): accept refresh-required candidate state`
- Current dirty files:
  - `src/agency/templates/cockpit.html`
  - `src/agency/static/v3-screens.css`
  - `src/agency/static/cockpit.js`
  - `src/agency/views/cockpit.py`
  - QA scripts/tests and shared template/style files.
- Live screenshots:
  - Current production probe:
    `research/results/ux-qa/walkme-correlation-audit/desktop-1920-normal-shell.png`
  - Expert reference:
    `ux upgrade claude design 01062026/.scratch/verify-a.png`

## What Was Actually Implemented

Positive work that should be preserved:

- Variation A was selected as the target in
  `docs/superpowers/specs/2026-06-01-cockpit-variation-a-decision-lock.md`.
- `GET /cockpit` is now the primary operator route and `/` redirects there.
- The cockpit uses a dark instrument-panel frame, gauges, engine strip,
  instrument buttons, phase rail, and panel overlays.
- Candidate ticker focus, focused execution URLs, and local staged state were
  improved.
- Ticker detail drawer uses a lazy API path and preserves richer signal,
  fundamentals, email, and LLM evidence contracts.
- Data lane status wording is better than the old "stale" wording in many
  places.
- Clearance has hash/proof/cycle fields and deliberate submit friction.
- Preservation harness protects several recent signal/fundamentals improvements.

These are real improvements. They are not enough to claim UX V3 is implemented.

## Core Mismatch

The expert Variation A first screen is a compact, sequential operator workflow:

1. User sees cycle, engine health, gauges.
2. User sees the active phase rail.
3. User immediately sees a ranked candidate table with concrete evidence and
   Approve / Defer / Reject decisions.
4. The primary call to action is "Advance to Portfolio" after candidate
   decisions.

The live cockpit currently opens with:

1. Large gauges, some with unavailable or zero values.
2. Engine strip.
3. Extra "Open dashboards" navigation.
4. A readiness/data-state block that can dominate the screen.
5. A "Selection paused" lane message before the candidate decision table.

That is safer than ignoring data issues, but it is not the same product shape.
The data-state proof was accepted as a production delta, but it changed the
first-screen experience enough that it should have triggered redesign rather
than a PASS.

## Traceability Matrix

| Item | Plan expectation | Current evidence | Audit status |
|---|---|---|---|
| UXC-000 Decision lock | Variation A locked, C future only | Done doc exists | Done |
| UXC-001 Contract audit | Map expert schema to backend fields and protected signal fields | Done doc exists; some gaps remain for market/account gauges and live monitor | Partial done |
| UXC-002 Visual shell parity | 1920 screenshot matches Variation A structure with documented narrow deltas | Visual doc exists, but accepted broad deltas; current screenshot diverges from reference in first-screen flow | Not passed |
| UXC-003 Candidate process | No long list after approval, focused ticker persists, one clear next action | Code/tests added, but live audit caveat says no actionable manifest/order link was available to click | Partial |
| UXC-004 Ticker drawer | Concrete evidence and LLM/manual-review state visible from live row | Code/tests added, but live audit caveat says no visible candidate-row drawer button existed in that run | Partial |
| UXC-005 Portfolio phase | Keep/close, capacity, empty portfolio path | Empty portfolio path tested; keep/close flow covered by controlled tests only | Partial |
| UXC-006 Clearance gate | Real manifest proof, phrase gate, safe submit | Code/tests added; live browser snapshot had no orderable manifest rows | Partial |
| UXC-007 Instrument panels | Panels replace operator-facing portions of legacy dashboards | Panels open and contain data, but "Open dashboards" nav still exists and legacy pages remain visually separate | Partial |
| UXC-008 Lane visibility | Lane state integral and readable with per-lane actions | Better wording exists, but it can still dominate first screen and interrupt candidate workflow | Partial |
| UXC-009 Scenario states | Normal, no-actionable, outage, submitted are real product states | Scenario tests exist; needs real visual parity and mid-session proof | Partial |
| UXC-010 Settings | Product settings, no prototype tweaks | Implemented mechanically; visual parity not independently proven | Partial |
| UXC-011 Pi hardening | Offline/touch/kiosk behavior | Desktop approximation and docs exist; no current Pi proof in this audit | Partial |
| UXC-012 Legacy reconciliation | Cockpit primary, legacy as diagnostics, no contradictions | Diagnostics labels exist; non-cockpit routes still retain older layout/design language | Partial |
| UXC-013 Workflow rehearsal | Complete real workflow or stop with one clear actionable reason | Prior run passed with caveats; current live screen stops at data lane attention and does not feel actionable enough | Partial |
| UXC-014 Preservation harness | One command protects recent signal/fundamentals behavior and records screenshots/prototype comparison | Harness protects data/copy, but its own doc says screenshots captured 0 and prototype compared No | Partial |

## Why Testing Missed This

1. The cockpit QA script checked mechanics, not design fidelity.
   It verified no console errors, no horizontal overflow, BLUF visible, phase
   visible, candidates visible, and touch target sizes. It did not compare the
   live screen against the frozen Variation A reference.

2. The visual parity gate accepted overly broad production deltas.
   Data-state proof became more prominent than the expert flow. That may be a
   valid safety requirement, but it changes the walk-me experience and should
   have required a new layout decision.

3. Some tickets passed despite live-data caveats.
   Examples:
   - UXC-003 had no currently actionable manifest/order-review focused link to
     click in live data.
   - UXC-004 had no visible candidate-row drawer button in the live run.
   - UXC-006 had no live orderable paper manifest rows.
   These are useful partial checks, not complete operator-flow proof.

4. The preservation harness is not a visual harness.
   `docs/audits/ux-preservation-uxc-014-2026-06-01.md` explicitly reports:
   screenshots captured: 0, prototype compared: No.

5. Legacy dashboards were re-labeled as diagnostics, not redesigned.
   That explains why the broader app still feels like the old product outside
   `/cockpit`.

6. A route-wide dashboard QA command hung during this audit.
   The current QA infrastructure is not yet reliable enough to be the final
   arbiter for "all dashboards are good."

## Concrete Product Gaps

P0 - Must fix before saying UX V3 is implemented:

- First viewport must match the Variation A walk-me hierarchy:
  topbar, gauges, engines, phase rail, BLUF, candidate decision table.
- Data-state proof must be present but should not bury the operator workflow
  unless the system is in a true outage/no-review state.
- Candidate table must show actionable rows with concrete evidence, risk,
  status, and readable decision buttons in the first useful viewport.
- "Open dashboards" should not be the primary navigation language inside the
  cockpit. It should be "Instruments" / overlays, with legacy pages clearly
  secondary.
- UXC-002 needs to be re-run as a real visual parity gate using current live
  screenshot versus the expert reference.

P1 - Must fix for credible operator flow:

- Re-run a real candidate approval path where an actionable ticker exists:
  candidate -> approve -> selected ticker remains focused -> portfolio ->
  clearance -> paper submit readiness or one clear stop reason.
- Require at least one live click-through for ticker drawer, focused execution,
  and clearance manifest before marking UXC-003/004/006 complete.
- Make dashboard QA bounded with a timeout and fail-fast report instead of
  hanging.
- Add a QA assertion that a PASS cannot be issued when the report contains a
  live-data caveat for the core behavior being tested.

P2 - Must fix for full product consistency:

- Decide whether legacy dashboards remain diagnostics or receive full V3
  redesign. Right now they are diagnostics with some V3 styling, not fully V3.
- Add screenshot comparison artifacts for all default cockpit scenarios:
  normal, no-actionable, outage, submitted.
- Add a human-review visual checkpoint after UXC-002 before later UX tickets are
  accepted.

## Corrective Implementation Order

1. Reopen UXC-002 as failed/partial.
   Build a strict `check_cockpit_visual_parity.py` gate that captures:
   prototype reference, live cockpit, diff summary, and accepted deltas.

2. Redesign the first viewport, not just CSS.
   Keep lane safety, but compress data-state into an operator status strip unless
   it truly blocks review. In normal/review-ready mode, the ranked candidate
   decision table must be the main content.

3. Replace cockpit "Open dashboards" with instrument semantics.
   Keep links to legacy diagnostics, but do not make them look like the main
   workflow.

4. Re-run UXC-003/004/005/006 with live actionable data.
   Do not accept controlled fixtures as the only proof for the operator path.

5. Harden QA rules.
   A UX ticket cannot pass if:
   - prototype comparison was not run,
   - the route-wide QA hangs,
   - the core user action was skipped due to missing live data,
   - the first viewport does not show the next action clearly.

## Final Assessment

UX V3 is partially implemented in infrastructure and styling, but not completed
as a product experience. The current live cockpit is safer and more capable than
the old dashboard in some backend-driven ways, but it is not yet the expert
Variation A walk-me cockpit the user asked for.

