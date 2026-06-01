# Variation A — Tickets

The complete backlog for the Pre-Flight Cockpit, grouped into six epics (VA-E0…VA-E5). Each ticket has an ID (`VA-###`), scope, explicit acceptance criteria, dependencies, and a rough estimate. Build epics in order. Test IDs (`VA-T-###`) referenced here are specified in `TESTING.md`; the DoD gate for each epic is in `DEFINITION-OF-DONE.md`.

**Estimate key:** S ≤ 2h · M = ½ day · L = 1 day · XL > 1 day.

**Conventions for every ticket (the per-ticket DoD):**
- Visual output matches `src/Variation A.html` within reason (spacing to the 4px grid, exact palette, mono for all numbers).
- No new colours, icons, or fonts (`../05-components.md`).
- No console errors/warnings; no orphaned timers/listeners.
- Linked test cases pass.

---

## VA-E0 · Project setup  _(≈ ½ day)_

### VA-001 · Scaffold Vite + React + TS  · S
Stand up the project per `IMPLEMENTATION.md §2/§5`.
- **AC:** `npm run dev` serves a blank mount; `npm run build` emits a single `/dist`. TypeScript strict mode on. Repo layout matches §5.
- **Dep:** none.

### VA-002 · Port `cockpit.css` + font face setup  · S
Move `src/cockpit/cockpit.css` in; keep the `.vA` scope (or migrate to a root `data-theme` attr — pick one, document it). Wire local `@font-face` for sans + mono (placeholder WOFF2 ok until VA-401).
- **AC:** `.mono` renders tabular mono; `.vA` palette variables resolve; calm-mode override selectors present. No external font requests in the network tab.
- **Dep:** VA-001.

### VA-003 · Port theme presets + scale-to-fit  · M
Port `COLOR_PRESETS`, `THEME_PRESETS`, `tweaksToCss`, and `useFitScale` out of `Variation A.html` into `theme/presets.ts` + `theme/useFitScale.ts`. Strip the `/*EDITMODE*/` markers.
- **AC:** all 3 colour presets × 3 themes inject correct CSS vars onto `.vA`; the 1440-wide artboard scales to fit any viewport and letterboxes on black; resize is debounced/cheap. Defaults are hard-coded (`amber` / `accent` / `full`).
- **Dep:** VA-002. **Test:** VA-T-101.

### VA-004 · Type the data schema  · M
Create `data/types.ts` from `../07-data-schema.md` and port `data.js` → `data/mock.ts` typed against it.
- **AC:** `mock.ts` compiles with no `any`; every field in `../07-data-schema.md` is represented; status/state string unions match the doc exactly.
- **Dep:** VA-001.

---

## VA-E1 · Static shell  _(≈ 1 day)_  — renders pixel-accurate, no interactions yet

### VA-101 · Shell hooks + primitives  · M
Port `shell/`: `useCockpitCountdown`, `useAnimatedValue`, `CockpitTip`, `WhyMark`, `CockpitOverlay`.
- **AC:** countdown ticks mm:ss and loops at 0 → 13:00; `useAnimatedValue` eases 0→target over duration with ease-out cubic and re-fires on deps; `CockpitTip` shows a 220px black tip on hover, no arrow, 6px offset; `WhyMark` is a circular "?" using the tip; `CockpitOverlay` is modal (backdrop `rgba(0,0,0,.55)` + 2px blur, max-height 80vh, Esc + click-outside close).
- **Dep:** VA-001. **Test:** VA-T-001, VA-T-002, VA-T-003.

### VA-102 · `ArcGauge` primitive  · M
Half-circle 160×100 SVG gauge: coloured zones, tick marks, needle that eases from 0→value (700–800ms) on mount, big mono number + unit + label (+ optional `WhyMark`) + sub-line.
- **AC:** needle maps value 0→1 to −90°→+90°; zones render per config; animates once on mount; clamps out-of-range values.
- **Dep:** VA-101. **Test:** VA-T-004.

### VA-103 · `ConvictionDial` + `SegDisplay`  · S
Compact 64×40 conviction half-dial (colour tracks 0.62 / 0.40 thresholds) and the faux-7-segment readout slab (dark slab, mono number, subtle glow, label).
- **AC:** dial fill + needle colour switch at the thresholds; SegDisplay supports amber + cyan variants; glow is the only text-shadow.
- **Dep:** VA-101.

### VA-104 · `InstrumentCluster` + `EngineStrip`  · M
The always-visible top row: 4 `ArcGauge` (Market Regime, Gross Exposure, Cash Reserve, Concentration) + 3 `SegDisplay` (Buying Power cyan, Ready-to-Trade amber, P/L Week green); engine strip listing every engine with a status dot + name + age.
- **AC:** gauge values + zones exactly per `../03-variation-a.md → The instrument cluster`; each gauge has its threshold `WhyMark` tip; engine dots are green=live / amber=stale; "Ready to Trade" reflects approved count.
- **Dep:** VA-102, VA-103. **Test:** VA-T-005.

### VA-105 · Instruments nav + `PhaseRail`  · M
The five-button instruments nav (Universe / Signals / Audit / Policy / Monitor) and the four-cell phase rail.
- **AC:** phase rail shows all 4 cells always; active = amber number + bright title + amber underline (8px glow) + lighter bg; done = green check + dim; locked = `◌` + "LOCKED" badge at 42% opacity. Nav buttons are present (wired in VA-204).
- **Dep:** VA-101. **Test:** VA-T-006.

### VA-106 · `CandidatesPhase` (resting state)  · L
Phase 1: BLUF headline + subline, "Advance to Portfolio" button, and the ranked candidate table (sorted by `finalConviction` desc) with columns # / Ticker·sector / Conviction (dial + number) / Why / Risk / Status chip / Decision buttons.
- **AC:** rows sort correctly; status chips colour per `../05-components.md` (READY amber, BLOCKED red, LLM DEMOTED amber, BELOW THRESHOLD grey); non-actionable rows greyed with an `audit ›` link; decision buttons render (wired in VA-201); headline text matches the no-approval copy.
- **Dep:** VA-103, VA-104. **Test:** VA-T-007.

### VA-107 · `ExpandedCandidate` row  · M
Inline three-column expansion: evidence pack (tier-coloured left border), LLM rationale (cyan-tinted italic) + watch-list, order preview (`PreviewRow`s) or blocker note.
- **AC:** confirmed evidence = green border, inferred = amber; rationale block cyan-tinted; order preview only for `approved` status, else shows the blocker reason.
- **Dep:** VA-106.

### VA-108 · `PortfolioPhase`  · L
Two-column: positions table (5 rows: ticker·days held / P/L / stop distance / setup tag / thesis / keep-close) + capacity check (`CapBar` stack for gross, top-3 sectors, cash floor) + amber heads-up.
- **AC:** P/L and stop-distance computed from entry/current/stop (not stored); setup tags HOLD green / REVIEW amber / CLOSE red; cash CapBar uses floor inversion; heads-up paragraph present.
- **Dep:** VA-103. **Test:** VA-T-008.

### VA-109 · `ClearancePhase` (manifest + gate, static)  · L
Two-column: order manifest (exits-first section + one row per staged buy, or empty state) + gate panel (status dot, arm checkbox, confirm-phrase input, submit button, flags footer).
- **AC:** manifest lists approved buys with qty/limit/notional/stop/target; exits-first section appears only when closes staged; gate renders CLOSED/red by default; submit shows "Locked". Gate logic wired in VA-202.
- **Dep:** VA-103. **Test:** VA-T-009.

### VA-110 · `ClearedPhase` (static)  · M
Phase 4 success: green-ring check, "{n} paper orders submitted", per-order cards (ticker · BUY qty @ price · order ID), total notional + next-cycle countdown. (Demo "Start over" present but flagged for removal in prod — VA-503.)
- **AC:** renders for a given set of approved orders; counts + total notional correct.
- **Dep:** VA-103.

### VA-111 · Assemble `VariationA` root (static)  · M
Compose cluster + engine strip + nav + phase rail + active phase into the full screen at the 1440×1100 artboard size; wire `density`/`scenario` props (render-only).
- **AC:** full screen matches `src/Variation A.html` in `normal`/`full` at phase 1; switching the `phase` prop swaps content; layout is stable at 1920×1080 after scale-to-fit.
- **Dep:** VA-104…VA-110. **Test:** VA-T-010, VA-T-301.

---

## VA-E2 · Interactions  _(≈ 1 day)_  — behaves like the prototype, still hardcoded data

### VA-201 · Candidate decisions (approve/defer/reject)  · M
Wire `decisions` state in the root; `DecisionBtn` toggles; status chips + "Ready to Trade" + Advance-button enablement react.
- **AC:** clicking Approve flips the chip to "YOU APPROVED" (green) and increments the SegDisplay; only `approved`-status candidates are actionable; decisions are reversible; Advance disabled until ≥1 approval. Row-click expand still works and doesn't fire decisions (stop-propagation).
- **Dep:** VA-111. **Test:** VA-T-011, VA-T-012.

### VA-202 · Submit gate logic  · M
Wire `gateOpen` + `phrase`; required phrase `submit paper orders` (case/space-insensitive trim); submit enables only when `gateOpen && phraseOk && approved.length>0`.
- **AC:** status dot flips red→green on arm; input disabled until armed; submit glows green only when all three conditions hold; clicking it transitions to Phase 4 (UI-only here). Gate + phrase reset if you leave and return to clearance.
- **Dep:** VA-109, VA-201. **Test:** VA-T-013, VA-T-014.

### VA-203 · Phase navigation + portfolio exits  · M
Advance/Back across phases; `exits` state with keep/close; Advance-to-Clearance gated until every non-HOLD position is decided; phase rail reflects active/done/locked.
- **AC:** can't advance past portfolio with an undecided REVIEW/CLOSE position; Back preserves prior decisions; rail states update; exits feed the clearance manifest's exits-first section.
- **Dep:** VA-108, VA-111. **Test:** VA-T-015.

### VA-204 · Instrument panels wired  · L
Open/close all six panels from the nav (and TickerDetail from a ticker click) via `CockpitOverlay`; each renders its data slice from `../05-components.md`.
- **AC:** Universe, Signals, TickerDetail, Audit, Policy, Monitor each open, render correct data, scroll if long, close on Esc / click-outside / Close button; opening a panel doesn't lose phase/decision state.
- **Dep:** VA-101, VA-111, panels ported. **Test:** VA-T-016, VA-T-017.

### VA-205 · Scenario switching (debug)  · M
Implement `normal` / `no-actionable` / `outage` / `submitted` switchable via a debug control (and `?scenario=` URL param) — `OutageStateA`, `NoActionableStateA`, and the submitted/cleared view.
- **AC:** each scenario renders per `../06-states.md`; outage keeps only the topbar; no-actionable keeps cluster/engines/nav/rail and replaces phase-1 content with the skip-ahead view; the param round-trips.
- **Dep:** VA-111. **Test:** VA-T-018, VA-T-302…VA-T-305.

### VA-206 · Settings overlay (replaces tweaks card)  · M
Port the four tweak axes into a Settings overlay (gear icon in topbar **or** long-press brand logo — **[CONFIRM]** which). Color / theme / density are user prefs; scenario sits behind a "developer" toggle.
- **AC:** changing color/theme/density updates live and matches the prototype's presets; the floating draggable card is gone; layout/pattern (A vs C) is NOT exposed.
- **Dep:** VA-003. **Test:** VA-T-019.

---

## VA-E3 · Backend integration  _(≈ 1.5–2 days)_

### VA-301 · API client + types  · M
`data/api.ts`: typed `GET /api/cockpit` + `GET /api/cycle`. Replace `mock.ts` consumption with fetch + React state (loading / error / empty).
- **AC:** cockpit renders from a live snapshot; loading and error states exist (no white screen on failure); `mock.ts` is used only by tests after this. **[CONFIRM]** final endpoint shapes with the human.
- **Dep:** VA-004, VA-111. **Test:** VA-T-020.

### VA-302 · Live derived numbers  · M
Compute `grossPostTrade`, P/L, stop distance, "Ready to Trade", capacity bars from live data + current staged decisions.
- **AC:** approving/deferring a candidate updates the Gross Exposure gauge + capacity bars in real time; nothing derived is read from the payload.
- **Dep:** VA-301, VA-201. **Test:** VA-T-021.

### VA-303 · Submit flow (`POST /api/decisions`)  · L
Real submit: post `{ decisions, exits, phrase }`, await broker ack, transition to Phase 4 with real order IDs; handle errors in the gate panel with a retry; never persist gate/phrase.
- **AC:** success → cleared with broker IDs; failure → inline error + retry, gate stays armed; double-submit guarded; mock random IDs gone.
- **Dep:** VA-202, VA-301. **Test:** VA-T-022, VA-T-023.

### VA-304 · Monitor SSE stream  · M
`PanelMonitor` consumes `GET /api/monitor/stream` (SSE), prepending events live; filter chips + live pulse work.
- **AC:** events append in real time; stream reconnects on drop; filters (all/info/warn/block) work; stream closes when the panel closes.
- **Dep:** VA-204, VA-301. **Test:** VA-T-024.

### VA-305 · Policy write path (`PUT /api/policy`)  · L
Policy panel gains the diff-and-confirm step the prototype lacks: show staged vs deployed, "Apply next cycle" confirm, PUT on confirm.
- **AC:** edits stage locally with a visible diff; confirm PUTs and reflects the deployed value; `LIVE_TRADING` cannot be enabled; cancel discards.
- **Dep:** VA-204, VA-301. **Test:** VA-T-025.

### VA-306 · Audit on demand (`GET /api/audit/:ticker`)  · M
`PanelAudit` fetches the lifecycle trace for any ticker the user clicks `audit ›` on (not just NFLX).
- **AC:** opening audit for any non-actionable ticker fetches + renders its timeline; loading + not-found states handled.
- **Dep:** VA-204, VA-301. **Test:** VA-T-026.

---

## VA-E4 · Pi hardening  _(≈ ½ day)_

### VA-401 · Bundle everything offline  · M
Remove all CDNs (React/ReactDOM bundled), no Babel-in-browser, ship real WOFF2 fonts locally.
- **AC:** the `/dist` bundle loads with the network disabled; zero external requests; fonts render from `/fonts/`. **Test:** VA-T-401.
- **Dep:** VA-301.

### VA-402 · Touch input  · M
Tappable targets ≥ 44px (esp. decision buttons), tooltips on tap-and-hold ~300ms, disable tap-highlight, `touch-action: manipulation`.
- **AC:** every decision/keep-close/submit/nav control is ≥ 44px in one dimension on the Pi build; tips appear on long-press; no 300ms click delay; no accidental page zoom. **Test:** VA-T-402.
- **Dep:** VA-201, VA-203.

### VA-403 · Session persistence + restore prompt  · M
Persist `decisions` + `exits` + prefs to localStorage; on reload mid-cycle show a "restore your session?" prompt; reset on cycle change; never persist gate/phrase.
- **AC:** reload mid-session offers restore and rehydrates decisions/exits; a new cycle clears them; gate always reopens closed and phrase empty. **Test:** VA-T-403.
- **Dep:** VA-201, VA-203, VA-206.

### VA-404 · Kiosk autostart + resilience  · M
systemd service launching Chromium `--kiosk` on boot, restart on crash, disable DPMS/screen-blank, `unclutter` the cursor; document the exact unit + flags.
- **AC:** Pi boots straight into the cockpit; killing the browser auto-restarts it and restores session; screen never sleeps. **[CONFIRM]** Pi model + touch vs non-touch. **Test:** VA-T-404.
- **Dep:** VA-401.

---

## VA-E5 · Edge cases & polish  _(≈ 1 day)_

### VA-501 · Empty / partial states  · M
Empty portfolio (fresh account), all-candidates-approved copy, exits-only manifest (`▸ Submit · 1 sell order`), zero-candidate `normal` falling back to no-actionable.
- **AC:** each renders sensibly per `../06-states.md → Edge cases`; submit-button copy adapts; **[CONFIRM]** whether empty portfolio skips Phase 2.
- **Dep:** VA-E3. **Test:** VA-T-027.

### VA-502 · Live scenario transitions + stale-data warning  · M
Handle `scenarioHint` changing mid-session (e.g. feeds die in Phase 2 → outage, staged decisions preserved); show a warning if no agent heartbeat in > 60s.
- **AC:** outage can interrupt any phase without losing staged decisions; recovery returns the user to their prior phase; a stale-data banner appears past the threshold. **[CONFIRM]** persist-through-outage behaviour.
- **Dep:** VA-205, VA-301. **Test:** VA-T-028.

### VA-503 · Production cleanup  · S
Remove the demo "Start over" button, EDITMODE markers, mock IDs, and any DesignCanvas/floating-tweaks remnants.
- **AC:** none of the "What NOT to port" items (`IMPLEMENTATION.md §9`) remain in the bundle.
- **Dep:** VA-E3.

### VA-504 · Full QA matrix pass  · L
Run the visual-state checklist in `../06-states.md` and the matrix in `TESTING.md` across scenario × density × theme × color, spot-checking compositions.
- **AC:** every box in `DEFINITION-OF-DONE.md → QA matrix` is checked; no regressions; performance budget met (VA-T-405).
- **Dep:** all above. **Test:** VA-T-405 + the full `VA-T-3xx` suite.

---

## Dependency summary

```
E0  VA-001 → VA-002 → VA-003
     VA-001 → VA-004
E1  (VA-101 primitives) → VA-102/103 → VA-104/105/106 → VA-107/108/109/110 → VA-111
E2  VA-111 → VA-201 → VA-202/203 ; VA-204 ; VA-205 ; VA-003→VA-206
E3  VA-004+VA-111 → VA-301 → VA-302/303/304/305/306
E4  VA-301 → VA-401 → VA-402/403/404
E5  E3 → VA-501/502/503 → VA-504 (gate)
```

Build top-to-bottom. Push for human review at the end of **E1** (visual parity), **E3** (real data looks right), and **E4** (feels right on the Pi) — per `../10-implementation-order.md`.
