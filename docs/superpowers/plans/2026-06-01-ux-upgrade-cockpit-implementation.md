# 2026-06-01 UX Upgrade Cockpit Implementation Plan

## Source Package

Analyzed folder:

`ux upgrade claude design 01062026/`

This package is a complete expert UX handoff for a Raspberry Pi paper-trading
operator cockpit. It is not a small CSS refresh. It defines a new cockpit product
model with frozen prototypes, shared design doctrine, two variation build packages,
implementation tickets, testing plans, and definitions of done.

## Folder Inventory

Root files:

- `Variation A.html` - standalone Pre-Flight Cockpit prototype.
- `Variation C.html` - standalone Mission Control prototype.
- `Trading Cockpit.html` - side-by-side design canvas for comparing A and C.
- `design-canvas.jsx` - design tool wrapper; not production code.
- `tweaks-panel.jsx` - prototype tweak controls; production should become settings.
- `cockpit/` - shared source for the root prototypes.
- `handoff/` - shared docs plus self-contained A/C build packages.
- `uploads/ux-design-review-export-20260521-0806/` - older UX-review export of the
  existing FastAPI/Jinja product at commit `8e8822f`; useful context, not the new
  cockpit implementation source.
- `.scratch/` - screenshot/proof images.

Important file counts:

- 22 Markdown files.
- 14 JSX files.
- 5 HTML prototypes.
- 3 CSS/JS support files.
- 10 PNG screenshots/proofs.
- 1 old controlled source zip.

## Readme And Instruction Files Reviewed

Repo-level:

- `README.md`
- `tickets/README.md`
- `src/agency/static/fonts/README.md`

UX package:

- `handoff/README.md`
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
- `handoff/variation-a/README.md`
- `handoff/variation-a/IMPLEMENTATION.md`
- `handoff/variation-a/TICKETS.md`
- `handoff/variation-a/TESTING.md`
- `handoff/variation-a/DEFINITION-OF-DONE.md`
- `handoff/variation-c/README.md`
- `handoff/variation-c/IMPLEMENTATION.md`
- `handoff/variation-c/TICKETS.md`
- `handoff/variation-c/TESTING.md`
- `handoff/variation-c/DEFINITION-OF-DONE.md`
- `uploads/ux-design-review-export-20260521-0806/README.md`
- `uploads/ux-design-review-export-20260521-0806/bundle-manifest.tsv`
- `uploads/ux-design-review-export-20260521-0806/secret-scan-report.txt`

Note: the user-provided AGENTS instruction says to use the superpowers plugin
when relevant. There is no `AGENTS.md` file present in the repo root, but the
instruction was supplied in-session and should be treated as active.

## Core Product Doctrine

The user is one human operator running a paper-trading agency on a Raspberry Pi.
They open the app once or twice a day, usually near market open. The agent should
have already done the work. The operator audits, decides, and clears.

Non-negotiables:

- Three-phase workflow: Candidates -> Portfolio -> Clearance.
- Paper-only v1; `LIVE_TRADING` remains locked off.
- Every primary screen starts with a BLUF sentence.
- Provenance is part of the product, not secondary metadata.
- Evidence hierarchy is visible: confirmed, inferred, suppressed.
- Submit requires deliberate friction: checkbox, exact phrase, submit button.
- Approvals are staged and reversible until submit.
- No charts, watchlists, ticker tape, news feed, or freeform dashboard building.
- No ambient motion. Motion is used only when it explains a change.
- Amber is the primary accent. All numbers are monospaced.

## Variation Decision

The package explicitly says to pick one variation, not both.

Variation A, Pre-Flight Cockpit:

- Sequential, one phase visible at a time.
- Better for focus, touch, first use, and process guidance.
- Default recommendation in the expert handoff.
- Best first implementation for the current agency because it directly fixes the
  user's repeated complaint: "walk me through the process."

Variation C, Mission Control:

- Three columns visible simultaneously.
- Denser, more ambient, more advanced.
- Requires fly-to-manifest and auto-advance as signature behaviors.
- Better as a second implementation after A is correct.

Recommendation:

Implement Variation A first as the operational cockpit. Keep Variation C as a
future ticket, not a runtime toggle.

## Current Agency Reality

The current repo already has a server-side cockpit path:

- `src/agency/views/cockpit.py`
- `src/agency/templates/cockpit.html`
- `src/agency/static/cockpit.js`
- `src/agency/static/v3-screens.css`
- `GET /cockpit`
- `GET /api/cockpit`
- `GET /api/cycle`
- `GET /api/cockpit/ticker/{ticker}`
- `GET /api/audit/{ticker}`
- `POST /cockpit/submit`

This is useful and should not be thrown away, but it is not yet a faithful
implementation of the expert package. It is a hybrid Jinja cockpit using existing
view models, while the expert handoff expects a self-contained cockpit interface
with prototype-level visual parity and stronger state/scenario discipline.

The safest path is not to retrofit every legacy dashboard one by one. Build the
expert cockpit as the primary operator surface and keep existing dashboards as
back-office/debug routes. The cockpit's instrument panels should absorb the
operator-facing roles of Command, Signals, Audit, Policy, Monitor, Candidate
Detail, Portfolio, and Execution Preview.

## Recent Work That Must Be Preserved

This UX implementation must not cancel or dilute the last 72 hours of signal,
fundamentals, market-flow, portfolio, and data-state improvements. The cockpit is
a new operator surface over the improved agency logic, not a replacement for that
logic.

Reviewed preservation sources:

- Git history from the last 72 hours, including:
  - `a4fd8a5` - institutional/13F lane capped at `CONTEXT_ONLY` because 13F data
    is delayed and should not directly authorize trade action.
  - `0335f1e` - concrete signal and fundamentals evidence improvements.
  - `4890b03` through `287be38` - SEC fiscal-period alignment, PIT fundamentals
    history, SEC metric expansion, forward-state health, FMP/yfinance forward
    state, detailed fundamentals panel, and regression gates.
  - `ab26e58`, `0f651a6`, `eb50731` - Massive TRF/off-exchange, dark-pool-like,
    block, and unusual-trade evidence improvements.
  - `f7fcd7d`, `3cce63c` - operator-facing data-state wording and cockpit label
    fixes.
- Current uncommitted audit/fix work in:
  - `research/src/pit/sec_views.py`
  - `research/src/signals/subscription_thesis.py`
  - `src/agency/runtime/lane_promotion.py`
  - `src/agency/runtime/signal_evidence.py`
  - `src/agency/templates/signals.html`
  - `src/agency/views/signals.py`
  - related unit tests under `tests/unit/`
- New audit documents:
  - `docs/audits/signals-audit-2026-05-31.md`
  - `docs/audits/subscription-email-agent-audit-2026-05-31.md`
  - `docs/superpowers/plans/2026-05-31-signal-audit-tier1-tier2.md`
  - `docs/superpowers/plans/2026-05-31-signals-quality-clarity.md`

Protected behavior:

- Fundamentals evidence keeps concrete period, filing, trend, quality, forward
  state, and meaning explanations. The UX must not collapse this back into
  generic "fundamentals are bullish/bearish" wording.
- SEC/PIT fundamentals keep the latest valid filing logic, fiscal-period
  alignment, amended filing precedence, and point-in-time cutoff behavior.
- Forward fundamentals from yfinance/FMP remain optional but explicitly reported
  with health/status when missing or unavailable.
- Signal evidence keeps hard facts: trigger metric, baseline, source, timestamp,
  direction, confidence, and user meaning.
- Massive/TRF/off-exchange/block/unusual-trade evidence keeps venue, latest
  period, notional, size, relative threshold, pressure, and baseline context.
- Institutional/13F evidence remains context-only for actionability unless a
  future ticket intentionally changes that policy with tests.
- Subscription email/thesis evidence keeps recency, source depth, relevance, and
  analyzed-article context. Generic RSS/email labels cannot override stronger
  article-level analysis.
- Candidate ranking and promotion must keep the existing conviction, gate,
  caution, and lane-promotion logic unless explicitly changed by a ticket with
  regression tests.
- Operator wording keeps the "no generic stale/blocker wording" rule. If data is
  not usable, the cockpit says whether it is loading, unavailable, unanalyzed,
  needs refresh, optional, or ready.

Implementation rule:

Any UX ticket that touches candidate cards, signal panels, fundamentals panels,
data-state strips, lane status, ranking, actionability, or paper-promotion must
first identify the backend field it consumes. It may reformat or prioritize the
field, but it must not recompute, simplify, or replace the existing signal and
fundamentals contracts with generic display text.

## Plan Improvement Cycle 1 - Faithful Source Port

Initial plan:

- Port the expert prototype directly.
- Start from Variation A.
- Preserve the prototype's visual language and flow.
- Use the existing backend only after static parity is achieved.

Issue found:

The prototype uses static `window.COCKPIT_DATA`, React/Babel CDNs, mock random
broker IDs, design-canvas plumbing, and a floating tweaks panel. That cannot be
production.

Improvement:

Keep the prototype as the visual and interaction truth, but implement it through
the current FastAPI app with real API-backed data. Strip all design-tool plumbing.

## Plan Improvement Cycle 2 - Agency Integration

Initial plan:

- Build a separate Vite/React SPA and serve it from FastAPI.

Issue found:

The current agency already has a working `/cockpit` route, API contract, submit
path, policy path, lane-state registry, local static assets, and server-side data
aggregation. A total frontend stack swap would increase schedule risk.

Improvement:

Use a staged integration:

1. First, bring the existing `/cockpit` into strict Variation A parity using Jinja,
   CSS, and small JS where practical.
2. Extract an explicit cockpit contract from `src/agency/views/cockpit.py` so the
   UI stops depending on scattered legacy dashboard shapes.
3. Only introduce Vite/React if the Jinja path cannot meet parity, performance, or
   interaction requirements.

This preserves paper-trading plumbing while upgrading the UX.

## Plan Improvement Cycle 3 - QA And Operational Proof

Initial plan:

- Implement tickets, run unit tests, inspect screens.

Issue found:

The user's main pain has been presentation-layer regressions, stale-looking data,
generic wording, and flows that appear complete but break during real operation.
Normal unit tests are insufficient.

Improvement:

Each ticket must have a definition of done with:

- Real API payload test or explicit mock-only flag.
- Playwright visual/interaction proof.
- Data freshness/state proof.
- Copy/provenance review.
- Preservation review against recent signal/fundamentals behavior.
- No hidden fallback artifacts as operational proof.
- Re-run of the affected workflow path from candidate review to paper submit where
  relevant.

## Visual Fidelity Gate Against Expert HTML

The expert HTML files are the visual contract. The production cockpit is allowed
to differ only where real data, security, or production operation requires it.

Reference files:

- `ux upgrade claude design 01062026/Variation A.html`
- `ux upgrade claude design 01062026/handoff/variation-a/src/Variation A.html`
- `ux upgrade claude design 01062026/cockpit/cockpit.css`
- `ux upgrade claude design 01062026/cockpit/variation-a-preflight.jsx`
- `ux upgrade claude design 01062026/handoff/05-components.md`
- `ux upgrade claude design 01062026/handoff/06-states.md`
- `ux upgrade claude design 01062026/handoff/08-tweaks.md`

Required comparison workflow for every visual ticket:

1. Open the frozen Variation A HTML locally.
2. Open the running `/cockpit` page with the same viewport.
3. Capture desktop screenshots at `1920x1080`.
4. Capture at least one smaller/kiosk-relevant viewport.
5. Compare:
   - font families and number typography.
   - amber/accent/danger/cleared/cyan color roles.
   - 4px grid rhythm, spacing, border radii, panel density, and alignment.
   - topbar, gauges, engine strip, phase rail, cards, drawers, panels, buttons,
     and submit gate.
   - animations and transitions, limited to meaningful state changes.
6. Record documented deltas. A delta is acceptable only when it is caused by real
   data, production safety, accessibility, or removal of prototype-only tooling.

Hard visual constraints:

- No new color palette unless it maps to the expert design tokens.
- No new font family unless it is the local production equivalent of the expert
  package.
- All numbers remain monospaced.
- No prototype `DesignCanvas`, `EDITMODE`, floating tweaks card, random order ID,
  mock ticker count, or `LIVE_TRADING` affordance reaches production.
- The submit gate remains checkbox plus exact phrase plus explicit submit button.
- A Playwright screenshot comparison or documented manual screenshot diff is
  required before a ticket that changes cockpit visuals is marked done.

## Preservation Regression Test Set

Before merging UX tickets that touch evidence, ranking, fundamentals, lane state,
or candidate flow, run the relevant subset below. Before declaring the full
cockpit rollout ready, run the complete set.

Signal/fundamentals preservation:

```powershell
.\.venv\Scripts\python -m pytest `
  tests\unit\test_signal_evidence.py `
  tests\unit\test_signal_evidence_fundamentals.py `
  tests\unit\test_subscription_thesis_signal.py `
  tests\unit\test_pit_loader.py `
  tests\unit\test_sec_views_period_fix.py
```

Cockpit/process/data-state preservation:

```powershell
.\.venv\Scripts\python -m pytest `
  tests\unit\test_cockpit_candidates.py `
  tests\unit\test_cockpit_lane_state.py `
  tests\unit\test_cockpit_routes.py `
  tests\unit\test_fastapi_app.py `
  tests\unit\test_actionability_gate.py
```

The protected assertions include:

- Generic summaries are overridden by concrete trigger headlines.
- Technical-analysis, buy/sell pressure, market-flow trend, TRF/off-exchange,
  unusual-trade, pre-market, news, insider, options, and institutional evidence
  explain their driver metrics and meaning.
- Fundamentals cards explain sign, trend, filing period, missing data, and user
  meaning.
- SEC metrics do not mix inconsistent fiscal periods.
- PIT loaders respect point-in-time cutoffs and manifest freshness.
- Candidate rows preserve concrete evidence, score, LLM status, actionability,
  and selected ticker flow.
- Data-state rows use operator language and individual lane refresh actions.
- Institutional 13F evidence remains capped at context-only actionability.

## Final Implementation Backlog

### UXC-000 - Baseline And Decision Lock

Goal:

Freeze the implementation target and stop ambiguity.

Implementation artifact:

- `docs/superpowers/specs/2026-06-01-cockpit-variation-a-decision-lock.md`

Scope:

- Record that Variation A is the implementation target.
- Keep Variation C as future backlog.
- Add a product note that A/C is not a runtime toggle.
- Record all `[CONFIRM]` items:
  settings entry point, calm mode auto/manual, staged decision restore behavior,
  outage persistence behavior, empty portfolio behavior, Pi model/touch target.

Definition of done:

- A single plan file points to Variation A as target.
- No implementation ticket depends on choosing A vs C.
- Human-confirm items are listed and visible.

Testing:

- Documentation review only.

### UXC-001 - Cockpit Contract Audit

Goal:

Map the expert `COCKPIT_DATA` schema to the existing `cockpit_context` output.

Implementation artifact:

- `docs/audits/cockpit-contract-audit-2026-06-01.md`

Scope:

- Compare `handoff/07-data-schema.md` to `safe_cockpit_api_payload()`.
- Define missing or renamed fields for cycle, market, engines, funnel, candidates,
  positions, account, sectors, sources, signals, audit lifecycle, policy, monitor.
- Ensure every field shown in the UI has timestamp/provenance where relevant.
- Replace unclear "stale" wording with specific states:
  data loading, data unavailable, analysis pending, analysis needs refresh, ready.
- Map candidate, signal, fundamentals, and subscription-thesis displays to the
  existing enriched backend fields before any template/CSS rewrite starts.

Definition of done:

- Contract table documents source, field, current backend mapping, missing gap.
- Contract table marks protected signal/fundamentals fields as "consume only;
  do not recompute in UI."
- Tests prove `/api/cockpit` contains no secrets and no mock-only fields in
  production scenario.

Testing:

- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_lane_state.py tests\unit\test_fastapi_app.py`
- API smoke: `GET /api/cockpit`, inspect scenario, candidates, data_state,
  sources, engines.

### UXC-002 - Variation A Visual Shell Parity

Goal:

Make `/cockpit` visually recognizable as the expert Pre-Flight Cockpit.

Scope:

- Align topbar, instrument cluster, engine strip, instrument nav, phase rail, and
  phase layout to `Variation A.html`.
- Preserve exact design roles: amber attention, green cleared, red danger, cyan
  LLM/provenance voice.
- Keep all numbers mono.
- Remove old dashboard residue inside the primary cockpit surface.
- Keep existing evidence, ranking, lane-state, and actionability data intact while
  changing layout and styling.

Definition of done:

- Desktop screenshot at 1920x1080 matches the Variation A structure within
  documented real-product deltas.
- Existing sidebar/topbar chrome is hidden or removed on cockpit.
- No hardcoded mock counts unless explicitly flagged as QA scenario.
- Visual-diff notes explicitly compare fonts, colors, animations, and theme to
  the frozen Variation A HTML.

Testing:

- Playwright screenshot of `/cockpit`.
- Manual compare against `ux upgrade claude design 01062026/Variation A.html`.
- CSS audit for new colors/icons/font families.
- Preservation smoke: candidate evidence/ranking before and after the visual
  shell change is semantically identical.

### UXC-003 - Candidate Phase Process Flow

Goal:

Make candidate review self-explanatory and process-focused.

Scope:

- Candidate list sorted by final conviction.
- Row shows ticker, sector, conviction dial, evidence line, risk line, status,
  and one clear next action.
- Action states:
  research review pending, research approved, order details need approval, ready
  for paper submit, audit only.
- Clicking approve keeps the operator in a coherent flow and auto-focuses that
  ticker in the next step.
- No generic evidence copy. Each visible claim must state concrete facts.
- Candidate ranking must consume the existing final conviction and promotion
  fields; the UI must not introduce a separate ranking formula.

Definition of done:

- Approving a candidate carries ticker context to the next screen/phase.
- No long stock list appears without selecting the approved ticker.
- Button text is readable and aligned.
- Non-actionable rows have audit affordance but no misleading disabled action.
- Top candidate ordering matches the backend report used by the previous
  candidates/command workflow.

Testing:

- Playwright: approve top candidate, verify phase/state/ticker persistence.
- Playwright: approve a lower candidate such as PLTR if present, verify it remains
  selected in order-review/clearance context.
- Unit: candidate status-label mapping.
- Unit: concrete evidence and "LLM not run for this ticker" copy regressions stay
  covered.

### UXC-004 - Ticker Detail Drawer

Goal:

Replace generic candidate detail text with concrete evidence and meaning.

Scope:

- Use lazy `/api/cockpit/ticker/{ticker}` detail loading.
- Show top-line judgment, data health, LLM status, supports, cautions, primary
  signals, gates, and exact next action.
- Evidence text must include source, timestamp, metric, comparison baseline, and
  interpretation where available.
- If LLM was not run, explain why and offer manual run button if policy permits.
- Reuse `src/agency/runtime/signal_evidence.py` output and fundamentals evidence
  payloads. Do not rebuild signal copy in the drawer.

Definition of done:

- Drawer loads within target timeout or shows explicit "detail still loading"
  without stale-looking data.
- No empty generic sections such as "No primary signal evidence" unless that is
  true and timestamped.
- LLM panel is present when available and clearly absent with reason when not.
- Fundamentals, TRF/off-exchange, unusual-trade, block-trade, insider, news, and
  subscription-thesis examples all show concrete evidence and plain meaning.

Testing:

- API test for `/api/cockpit/ticker/NVDA` or available ticker.
- Browser test: open drawer for at least three statuses:
  reviewable, order-reviewable, audit-only.
- Copy audit for "generic" fallback strings.
- Preservation tests:
  `test_signal_evidence.py`, `test_signal_evidence_fundamentals.py`, and
  `test_subscription_thesis_signal.py`.

### UXC-005 - Portfolio Phase

Goal:

Make portfolio review a compact capacity and exit decision surface.

Scope:

- Show current positions, thesis, P/L, stop distance, exit/keep action.
- Show capacity impact from staged candidate decisions:
  gross exposure, sector exposure, cash reserve.
- Empty portfolio gets a deliberate empty state, not a blank table.

Definition of done:

- Keep/close decisions update manifest locally.
- Capacity numbers recompute from staged state.
- The UI tells the operator whether portfolio review is required or can be skipped.

Testing:

- Unit: P/L, stop distance, staged exposure derivations.
- Browser: keep/close updates manifest and phase labels.
- Empty portfolio fixture.

### UXC-006 - Clearance And Submit Gate

Goal:

Make paper submit deliberate, hash-bound, and readable.

Scope:

- Manifest lists exits first, then buys.
- Each order row includes ticker, side, notional, order-intent hash, cycle ID, and
  timestamp proof.
- Submit requires checkbox plus exact phrase `submit paper orders`.
- Broker IDs only come from broker response, never random IDs.
- Server revalidates order intent before broker submit.

Definition of done:

- Gate never persists across reload.
- Submit button is disabled until acknowledgement and phrase match.
- Tampered order values/hash/cycle fail safely.
- Success moves to Cleared phase with broker-returned IDs.

Testing:

- Existing submit tests plus new cockpit-specific JSON submit tests.
- Browser test for wrong phrase, correct phrase, success path, failure path.
- Unit: hash/tamper validation.

### UXC-007 - Instrument Panels

Goal:

Make the cockpit's panels replace the operator-facing portions of legacy dashboards.

Scope:

- Universe/Data Sources panel:
  lane status, progress, ETA, timestamp proof, per-lane refresh action.
- Signals panel:
  confirmed/inferred/suppressed filter and concrete signal log that preserves
  enriched signal/fundamentals evidence details.
- Audit panel:
  per-ticker lifecycle trace and evidence hash.
- Policy panel:
  deployed vs staged values, diff, apply next cycle, `LIVE_TRADING` locked off.
- Monitor panel:
  live event stream or current polling fallback, with clear disconnected state.
- Ticker panel:
  full per-ticker candidate detail.

Definition of done:

- All six panels open, scroll, close by Esc and click-outside.
- Every panel has loaded/empty/error states.
- No panel uses hardcoded demo data in normal operation.
- Signals and fundamentals panels show the same or richer concrete evidence than
  the current signal inspector, never less.

Testing:

- Browser test opens and closes all panels.
- API tests for panel data sources.
- Accessibility: focus returns to trigger.
- Regression: signal/fundamentals evidence tests remain green after panel
  rendering changes.

### UXC-008 - Data State And Lane Visibility

Goal:

Make data state an integral, reliable cockpit feature.

Scope:

- Use `src/agency/runtime/lane_state.py` as normalized truth.
- For each lane show:
  loading, ready, unavailable, analysis pending, needs refresh, disabled optional.
- Show progress percent, covered tickers, ETA where available, latest timestamp,
  and exact gap to operability.
- Add refresh button only when the scheduler has a runnable job for that lane.
- Do not show old/stale data as if usable while a lane is in progress.
- Preserve existing lane-promotion and readiness semantics. The cockpit can
  explain state more clearly, but it cannot relax a data-quality gate silently.

Definition of done:

- The cockpit explains why review is ready or not ready.
- User can refresh individual eligible lanes.
- Disabled optional lanes are not counted as blockers.
- "Stale" is not used as operator-facing wording.

Testing:

- Lane-state unit cases:
  raw lane running, ready raw but derived not analyzed, partial but usable, provider
  unavailable, optional disabled, execution-blocking not fresh enough.
- Browser: each lane row shows progress/action correctly.
- Visual fidelity: lane board uses expert cockpit spacing, typography, and state
  tokens, not legacy dashboard table styling.

### UXC-009 - Scenario States

Goal:

Implement normal, no-actionable, outage, and submitted states as real product states.

Scope:

- `normal`: standard workflow.
- `no-actionable`: clear low-conviction day explanation, skip to portfolio.
- `outage`: critical engines down, no candidate controls, retry/last-good proof.
- `submitted`: post-submit confirmation and no accidental "start over" production reset.
- QA scenario controls stay behind QA/dev flag and are labeled training only.

Definition of done:

- Backend chooses scenario from state.
- QA scenario overrides are visibly marked non-operational.
- Mid-session scenario changes preserve staged decisions but block submit until
  revalidated.

Testing:

- Unit: scenario selection.
- Browser: all scenarios and phase states.
- QA route with `?scenario=` only when enabled.

### UXC-010 - Settings And Preferences

Goal:

Replace prototype Tweaks card with product settings.

Scope:

- Preferences:
  color preset, theme, density.
- Persist preferences across sessions.
- A/C variation switch is not exposed.
- Scenario selector is QA-only.
- Settings entry point is a normal cockpit control, not a floating design card.

Definition of done:

- Preferences survive reload.
- Calm mode hides nonessential chrome but keeps the workflow usable.
- No `EDITMODE` markers remain in production.

Testing:

- Browser: change each preference and reload.
- CSS visual check for amber/accent/full defaults.

### UXC-011 - Pi/Kiosk Hardening

Goal:

Make cockpit viable on Raspberry Pi.

Scope:

- Zero CDN requests.
- Local fonts only.
- Touch targets >= 44px.
- Long-press/tap tooltip behavior.
- Disable accidental pinch/zoom.
- Kiosk launch and restart documented.
- Memory/timer/listener cleanup.

Definition of done:

- Offline load has zero external requests.
- 8-hour kiosk soak or documented shorter pre-ship soak passes.
- Idle CPU and memory within budget where measurable.

Testing:

- Playwright network audit.
- Manual Pi test or desktop approximation if Pi unavailable.
- JS event listener/timer review.

### UXC-012 - Legacy Dashboard Reconciliation

Goal:

Stop the app feeling like a mix of old dashboards and new cockpit.

Scope:

- Make `/cockpit` the primary operator entry.
- Keep `/command`, `/signals`, `/risk`, `/execution-preview`, etc. as deep
  diagnostic pages, not the primary workflow.
- Update navigation labels so the user knows when they leave the cockpit.
- Any route still linked from cockpit must use the same data-state wording and
  provenance/copy standards.
- Legacy routes must keep recent signal/fundamentals explainability improvements
  until their operator-facing role is fully absorbed into cockpit panels.

Definition of done:

- Primary route sends user to cockpit or strongly surfaces cockpit.
- No old dashboard screen contradicts cockpit status.
- No hardcoded/mock data appears on operator routes.

Testing:

- Route smoke for all dashboards.
- Visual audit for V3/V4 consistency.
- Copy audit for "stale", "blocked", "generic evidence" regressions.
- Preservation audit that `/signals` and candidate detail still expose concrete
  signal/fundamentals evidence during the transition.

### UXC-013 - Full Workflow Rehearsal

Goal:

Prove the agency can complete a real operator workflow.

Scope:

- Start server fresh.
- Load `/cockpit`.
- Review data state.
- Open candidate detail.
- Approve one research candidate.
- Approve order details if required.
- Review portfolio.
- Clear manifest.
- Submit paper order if paper broker is configured and policy permits.
- Verify broker/audit record.
- Review at least one ticker with rich signal/fundamentals evidence and confirm
  the user can see why the recommendation exists, what data was used, and what
  data state applies.

Definition of done:

- Workflow either completes to broker paper submission or stops with one clear,
  actionable, truthful reason.
- No hidden stale/fallback/mock data is used as proof.
- Every transition preserves ticker context and user intent.
- No signal, fundamentals, or email evidence degradation is found compared with
  the pre-UX implementation.

Testing:

- `.\.venv\Scripts\python -m pytest` targeted cockpit/execution tests.
- `.\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1`
- `.\.venv\Scripts\python scripts\check_operational_readiness.py --min-queue 1`
- Playwright end-to-end cockpit path.

### UXC-014 - Preservation Regression Harness

Goal:

Make "do not regress the recent audit work" an executable gate, not a reminder.

Implementation artifact:

- `scripts/check_ux_preservation.py`
- `tests/unit/test_ux_preservation_harness.py`

Scope:

- Add or update a single script/test target that runs the preservation regression
  set for:
  signal evidence, fundamentals evidence, subscription thesis, PIT fundamentals,
  lane-state wording, candidate ranking/status, and institutional actionability.
- Add a small fixture or snapshot check for a rich candidate detail payload with:
  fundamentals, TRF/off-exchange, unusual-trade, LLM/email state, and lane state.
- Record a before/after semantic comparison for key fields when a UX ticket
  changes templates or cockpit APIs.
- Produce an artifact in `research/results/` or `docs/audits/` that lists:
  tests run, screenshots captured, prototype compared, and any accepted deltas.

Definition of done:

- One command gives a clear preservation PASS/FAIL.
- Failures point to the exact protected behavior that changed.
- The command is referenced by every ticket that touches evidence, ranking, data
  state, candidate flow, or paper promotion.

Testing:

- Run the preservation command after implementation.
- Deliberately change one protected fixture locally during development and
  confirm the gate fails, then revert that local probe.

Command:

```powershell
.\.venv\Scripts\python scripts\check_ux_preservation.py --group all
```

## Quality Gates Before Any "Done" Claim

For every ticket:

1. Code compiles and targeted tests pass.
2. A browser interaction check is run if the ticket touches UX.
3. A visual fidelity check against the frozen expert HTML is run if the ticket
   touches cockpit layout, styling, animation, or interaction.
4. A data-proof check is run if the ticket touches readiness, lane state, or
   evidence.
5. A preservation regression check is run if the ticket touches signals,
   fundamentals, ranking, actionability, subscription/email evidence, or
   candidate flow.
6. No mock/demo/training data appears in normal operation.
7. No operator-facing generic copy was introduced.
8. No old "stale" or unclear blocker wording appears.
9. The exact next user action is visible on screen.

Repo test command standard:

```powershell
.\.venv\Scripts\python -m pytest
```

Targeted cockpit commands:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_fastapi_app.py tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_lane_state.py tests\unit\test_cockpit_routes.py
.\.venv\Scripts\python scripts\check_local_runtime.py --min-selection-reports 1 --min-risk-decisions 1
.\.venv\Scripts\python scripts\check_operational_readiness.py --min-queue 1
```

Visual proof commands/artifacts to add during implementation:

```powershell
# Exact command depends on the Playwright harness created in UXC-002/UXC-014.
# Required artifact shape:
# - prototype Variation A screenshot
# - production /cockpit screenshot
# - accepted-deltas markdown note
# - PASS/FAIL summary for fonts, colors, spacing, animation, and theme roles
```

## Open Decisions For Human Confirmation

- Confirm Variation A as the first implementation target.
- Confirm settings entry point: gear button vs long-press logo vs command panel.
- Confirm calm mode: manual only or auto after submission/between cycles.
- Confirm staged decision persistence across reload: restore prompt recommended.
- Confirm outage behavior: preserve staged decisions but require revalidation before
  submit recommended.
- Confirm empty portfolio behavior: show explicit "no positions" phase and allow
  advance to clearance recommended.
- Confirm Raspberry Pi model and touch vs non-touch display.
- Confirm whether legacy dashboards remain reachable as diagnostics after cockpit
  becomes the primary operator route.

## Implementation Recommendation

Start with UXC-000, UXC-001, UXC-014, then UXC-002 and UXC-003. Do not begin
broad dashboard restyling first. The user's biggest operational pain is workflow
continuity: candidate approval must carry the selected ticker forward, the next
action must be obvious, and the cockpit must display reliable data-state proof.
UXC-014 must be in place early so visual work cannot accidentally erase the
recent improvements to signal explainability, fundamentals analysis, ranking,
lane-state wording, or paper-promotion safety. Once that is correct, migrate the
instrument panels and legacy screens behind the cockpit.
