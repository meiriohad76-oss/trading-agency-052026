# Variation C — Tickets

The complete backlog for Mission Control, grouped into six epics (VC-E0…VC-E5). Each ticket has an ID (`VC-###`), scope, explicit acceptance criteria, dependencies, and an estimate. Build epics in order. Test IDs (`VC-T-###`) are in `TESTING.md`; the epic DoD gate is in `DEFINITION-OF-DONE.md`.

**Estimate key:** S ≤ 2h · M = ½ day · L = 1 day · XL > 1 day.

**Per-ticket DoD (every ticket):** visual output matches `src/Variation C.html` within reason (4px grid, exact `.vC` palette, mono for all numbers); no new colours/icons/fonts; no console errors; no orphaned timers/listeners; linked tests pass.

---

## VC-E0 · Project setup  _(≈ ½ day)_

### VC-001 · Scaffold Vite + React + TS  · S
Per `IMPLEMENTATION.md §2/§5`.
- **AC:** `npm run dev` serves a blank mount; `npm run build` emits a single `/dist`; TS strict; layout matches §5.
- **Dep:** none.

### VC-002 · Port `cockpit.css` + fonts  · S
Move `cockpit.css` in; keep the `.vC` scope; preserve the calm-mode `[data-calm-hide]` selectors. Wire local `@font-face` (placeholder WOFF2 until VC-401).
- **AC:** `.mono` tabular; `.vC` palette resolves; `grid-bg` + calm overrides present; no external font requests.
- **Dep:** VC-001.

### VC-003 · Theme presets + scale-to-fit  · M
Port `COLOR_PRESETS`/`THEME_PRESETS`/`tweaksToCss` (`.vC` vars) + `useFitScale(1440,1000)` out of the HTML; strip EDITMODE markers.
- **AC:** 3 color × 3 theme presets inject correct `.vC` vars; 1440×1000 artboard scales + letterboxes; defaults hard-coded (amber/accent/full).
- **Dep:** VC-002. **Test:** VC-T-101.

### VC-004 · Type the data schema  · M
`data/types.ts` from `../07-data-schema.md`; port `data.js` → `data/mock.ts` typed.
- **AC:** compiles with no `any`; every field represented; string unions match the doc.
- **Dep:** VC-001.

---

## VC-E1 · Static shell  _(≈ 1–1.5 days)_  — three columns render pixel-accurate, no interactions

### VC-101 · Shell hooks + primitives  · M
Port `shell/`: `useCockpitCountdown`, `useAnimatedValue`, `CockpitTip`, `WhyMark`, `CockpitOverlay` (must accept `scope="vC"`).
- **AC:** as `../05-components.md`; overlay inherits the `.vC` palette via scope; Esc + click-outside close.
- **Dep:** VC-001. **Test:** VC-T-001, VC-T-002, VC-T-003.

### VC-102 · `MCColumn` + `MCBadge` + `Telem` primitives  · M
Generic column wrapper (header strip + body + active/dimmed states); the small uppercase badge; the telemetry label·value element (+ `big` variant for counters).
- **AC:** `MCColumn` active = brighter bg + amber underline + full opacity; dimmed = 42% saturation; `Telem` colours value by sign; `big` variant styled for counters.
- **Dep:** VC-101.

### VC-103 · `TelemetryStrip`  · L
The top strip: brand block (`CrosshairMark` + "AGENCY · MISSION CTRL" + cycle/countdown/date) · live metrics (SPY/VIX/breadth/gross/cash/open-ord, gross+cash with WhyMark tips) · approval counters (Approved green, To-exit red) · panel nav (5 single-letter `PanelNavBtn` ≤26px + PAPER badge).
- **AC:** four-column grid matches `../04-variation-c.md → telemetry strip`; metrics read documented values; gross shows "67 → 84%" amber; counters reflect approved/exit counts; `data-calm-hide="telem-mid"` on the middle block.
- **Dep:** VC-102. **Test:** VC-T-005.

### VC-104 · `CandidatesColumn` static (Stage 01)  · L
Header (stage label · "Candidates" · "{approved}/{actionable} cleared" · `FunnelCrumbs`); body split: ranked list (compact rows: index, ticker, `ConvictionBar` vertical, one-line evidence, status dot) over the `CandidateDetailC` pane (ticker/sector/price/earnings/DET·LLM dots, score chips, evidence rows with CONF/INF badges, risk flags, cyan italic rationale, three decision buttons).
- **AC:** list sorted by `finalConviction` desc; `ConvictionBar` colour tracks thresholds; detail pane renders the selected candidate; CONF=green/INF=amber badges; rationale cyan-tinted. Selection wired in VC-204.
- **Dep:** VC-102. **Test:** VC-T-007.

### VC-105 · `PortfolioColumn` static (Stage 02)  · L
Header (stage label · "Portfolio" · "5 pos · {n} exit" · three `MiniMeter`s: Gross/Cash/Tech); body: 5 position rows (ticker · status tag · P/L · thesis · keep/close) + `SectorRadar` 11-cell heatmap.
- **AC:** P/L computed (not stored); status tags coloured HOLD/REVIEW/CLOSE; mini-meters show cur→post; heatmap colours tailwind green / pressure red / neutral grey / unavail faded across all 11 sectors. Keep/close wired in VC-203.
- **Dep:** VC-102. **Test:** VC-T-008.

### VC-106 · `ClearanceColumn` static (Stage 03)  · L
Header (stage label · "Clearance" · gate status · order count + total notional); body: exits-first block (if closes) → staged BUY `ManifestRow`s → `GatePanel` (SAFE/ARMED, confirm phrase, big TRANSMIT button, flags footer).
- **AC:** manifest lists approved buys (ticker · BUY qty @ price · stop/target · notional); exits-first only when closes staged; gate shows "○ SAFE" + CLOSED by default; TRANSMIT shows count + total (`▸ TRANSMIT · 3 ORDERS · $19K`). Gate logic wired in VC-202.
- **Dep:** VC-102. **Test:** VC-T-009.

### VC-107 · `EngineFooter`  · S
Bottom engine strip: every engine as a tiny chip (uppercased, name truncated to 14 chars) + "RUNTIME_OK · 6/7" at the end.
- **AC:** matches `../04-variation-c.md → footer engine strip`; status dots green/amber/red; `data-calm-hide="footer-engines"` present.
- **Dep:** VC-102.

### VC-108 · Assemble `VariationC` root (static)  · M
Compose telemetry strip + three columns + footer at 1440×1000; wire `density`/`scenario` props (render-only); default `selected` = top candidate; `stage`=0 active.
- **AC:** full screen matches `src/Variation C.html` in `normal`/`full`; Stage 01 active/bright, others at full opacity (not dimmed until mid-flight); stable at 1920×1080 after scale-to-fit.
- **Dep:** VC-103…VC-107. **Test:** VC-T-010, VC-T-301.

---

## VC-E2 · Interactions  _(≈ 1.5 days)_

### VC-201 · Candidate decisions  · M
Wire `decisions`; `MCDecisionBtn` (Reject/Defer/Approve·stage); detail pane + status dots + telemetry counters + clearance manifest all react.
- **AC:** approving adds the candidate to the manifest, ticks the "Approved" counter, updates the gross telem + portfolio mini-meter; reversible; only `approved`-status candidates actionable.
- **Dep:** VC-108. **Test:** VC-T-011, VC-T-012.

### VC-202 · Gate logic (`GatePanel`)  · M
Wire `gateOpen` + `phrase`; required `submit paper orders`; TRANSMIT enables only when `gateOpen && phraseOk && approved>0`; SAFE→ARMED on open.
- **AC:** arming flips "○ SAFE"→"● ARMED"; input disabled until armed; TRANSMIT activates only with all three; click → submitted (UI-only here).
- **Dep:** VC-106, VC-201. **Test:** VC-T-013, VC-T-014.

### VC-203 · Portfolio keep/close  · S
Wire `exits` keep/close on non-HOLD positions; exits feed the clearance exits-first block + "To exit" counter.
- **AC:** keep/close reversible; exits-first block + counter update; HOLD rows have no buttons.
- **Dep:** VC-105, VC-108. **Test:** VC-T-015.

### VC-204 · List selection → detail pane  · S
Clicking any list row updates `selected` → `CandidateDetailC`; selection persists across scenarios; defaults to top.
- **AC:** selecting any candidate (actionable or not) updates the detail pane; selection survives scenario switches.
- **Dep:** VC-104, VC-108. **Test:** VC-T-016.

### VC-205 · Fly-to-manifest animation  · M
On approve, spawn a `FlyChip` (`▸ TICKER`, green) from the click position, animate toward the clearance column manifest (700ms translate + scale-down + fade), `position:fixed`, `z 60`, cleared 750ms after spawn.
- **AC:** chip spawns at click point, lands in the manifest area, doesn't shift layout, cleans itself up; multiple rapid approvals queue without leaking nodes; respects reduced-motion (instant if set). See `../04-variation-c.md`.
- **Dep:** VC-201. **Test:** VC-T-017.

### VC-206 · Auto-advance  · M
Active column advances: start Stage 01; first approval → Stage 02 (or 03 if exits staged); clicking inside a column makes it active; on submit, dim all but clearance.
- **AC:** active column's brighter bg + amber underline track the rules; non-active columns full-opacity until mid-flight; submitted dims Candidates+Portfolio to 42%, Clearance bright.
- **Dep:** VC-201, VC-202, VC-203. **Test:** VC-T-018.

### VC-207 · Instrument panels wired  · L
Open/close all six from the panel nav (+ TickerDetail from ticker click) via `CockpitOverlay scope="vC"`; each renders its data slice.
- **AC:** Universe/Signals/TickerDetail/Audit/Policy/Monitor open, render correct data, scroll, close on Esc/outside/Close; opening a panel preserves stage/selection/decisions.
- **Dep:** VC-101, VC-108, panels ported. **Test:** VC-T-019, VC-T-020.

### VC-208 · Scenario switching (debug)  · M
`normal`/`no-actionable`/`outage`/`submitted` via debug control + `?scenario=` — `OutageStateC`, `NoActionableStateC`, `SubmittedPane`/column-dim.
- **AC:** each renders per `../06-states.md`: outage = two-column (telemetry strip stays); no-actionable = Stage 01 empty card while Portfolio stays active + Stage 03 empty-manifest note; submitted = dim two columns, clearance bright. Param round-trips.
- **Dep:** VC-108, VC-206. **Test:** VC-T-021, VC-T-302…VC-T-305.

### VC-209 · Settings overlay  · M
Port the four tweak axes into a Settings overlay (gear icon **or** long-press brand logo — **[CONFIRM]**); color/theme/density = prefs; scenario behind a developer toggle; calm mode hides telem-mid + footer engines.
- **AC:** color/theme/density update live and match presets; calm mode hides the two `[data-calm-hide]` regions + kills glows; floating card gone; A/C switch not exposed.
- **Dep:** VC-003. **Test:** VC-T-022.

---

## VC-E3 · Backend integration  _(≈ 1.5–2 days)_

### VC-301 · API client + types  · M
`data/api.ts`: typed `GET /api/cockpit` + `GET /api/cycle`; replace mock with fetch + state (loading/error/empty).
- **AC:** cockpit renders from live snapshot; loading + error states (no white screen); mock only used by tests after this. **[CONFIRM]** endpoint shapes.
- **Dep:** VC-004, VC-108. **Test:** VC-T-023.

### VC-302 · Live derived telemetry  · M
Bind telemetry metrics, approval counters, portfolio mini-meters, sector heatmap, and `grossPostTrade` to live data + staged decisions.
- **AC:** approving a candidate updates the Approved counter + gross telem + mini-meter together in real time; nothing derived read from payload.
- **Dep:** VC-301, VC-201. **Test:** VC-T-024.

### VC-303 · Submit flow (`POST /api/decisions`)  · L
Real submit: post `{ decisions, exits, phrase }`, await ack, render `SubmittedPane` with real broker IDs; errors shown in the gate with retry; never persist gate/phrase.
- **AC:** success → submitted pane (dimmed columns) with broker IDs; failure → inline error + retry, ARMED preserved; double-submit guarded; mock IDs gone.
- **Dep:** VC-202, VC-301. **Test:** VC-T-025, VC-T-026.

### VC-304 · Monitor SSE  · M
`PanelMonitor` consumes `GET /api/monitor/stream`; live append + filters + pulse.
- **AC:** events append live; reconnect on drop; filters work; stream closes with the panel.
- **Dep:** VC-207, VC-301. **Test:** VC-T-027.

### VC-305 · Policy write path (`PUT /api/policy`)  · L
Diff-and-confirm Policy panel ("Apply next cycle"); PUT on confirm; `LIVE_TRADING` cannot be enabled.
- **AC:** edits stage with visible diff; confirm PUTs + reflects deployed value; live trading locked; cancel discards.
- **Dep:** VC-207, VC-301. **Test:** VC-T-028.

### VC-306 · Audit on demand (`GET /api/audit/:ticker`)  · M
`PanelAudit` fetches the lifecycle trace for any ticker clicked.
- **AC:** any non-actionable ticker's `audit ›` fetches + renders its timeline; loading/not-found handled.
- **Dep:** VC-207, VC-301. **Test:** VC-T-029.

---

## VC-E4 · Pi hardening  _(≈ ½ day)_

### VC-401 · Bundle everything offline  · M
Remove CDNs (bundle React/ReactDOM), no Babel-in-browser, ship WOFF2 fonts locally.
- **AC:** `/dist` loads with network disabled; zero external requests; fonts local. **Test:** VC-T-401.
- **Dep:** VC-301.

### VC-402 · Touch input  · M
Targets ≥ 44px — esp. decision buttons **and** the ≤26px panel-nav letters — without breaking the dense strip; tap-and-hold tips; disable tap-highlight; `touch-action: manipulation`.
- **AC:** every tappable target ≥ 44px in one dimension on the Pi build; long-press tips; no click delay; no zoom; telemetry strip still fits. **Test:** VC-T-402.
- **Dep:** VC-201, VC-203, VC-207.

### VC-403 · Persistence + restore prompt  · M
Persist `decisions`/`exits`/`selected`/prefs; restore prompt on reload mid-cycle; reset on cycle change; never persist gate/phrase.
- **AC:** reload offers restore + rehydrates; new cycle clears (and clears the submitted dim, reactivates Candidates); gate reopens SAFE/empty. **Test:** VC-T-403.
- **Dep:** VC-201, VC-203, VC-209.

### VC-404 · Kiosk autostart + resilience  · M
systemd Chromium `--kiosk` on boot, crash-restart, no DPMS/blank, `unclutter`; document the unit + flags.
- **AC:** Pi boots into cockpit; browser-kill restarts + restores; no screen sleep. **[CONFIRM]** Pi model + touch. **Test:** VC-T-404.
- **Dep:** VC-401.

---

## VC-E5 · Edge cases & polish  _(≈ 1 day)_

### VC-501 · Empty / partial states  · M
Empty portfolio, all-approved header ("3/3 cleared"), exits-only manifest (TRANSMIT copy adapts: `▸ TRANSMIT · 1 SELL ORDER`), zero-candidate normal → no-actionable Stage 01.
- **AC:** each renders per `../06-states.md → Edge cases`; TRANSMIT copy adapts; **[CONFIRM]** empty-portfolio behaviour.
- **Dep:** VC-E3. **Test:** VC-T-030.

### VC-502 · Live scenario transitions + stale-data warning  · M
`scenarioHint` change mid-session (outage can interrupt; recovery restores staged state + active column); warn if no heartbeat > 60s.
- **AC:** outage interrupts any stage without losing staged decisions; recovery restores prior state; stale banner past threshold. **[CONFIRM]** persist-through-outage.
- **Dep:** VC-208, VC-301. **Test:** VC-T-031.

### VC-503 · Production cleanup  · S
Remove EDITMODE markers, mock IDs, DesignCanvas/floating-tweaks remnants. **Confirm no "Start over" button exists** (C must not have one).
- **AC:** none of the "What NOT to port" items (`IMPLEMENTATION.md §10`) remain; no start-over control.
- **Dep:** VC-E3.

### VC-504 · Full QA matrix pass  · L
Run the visual-state checklist (`../06-states.md`) + the matrix in `TESTING.md` across scenario × density × theme × color; spot-check compositions; verify fly-chip + auto-advance under load.
- **AC:** every box in `DEFINITION-OF-DONE.md → QA matrix` checked; performance budget met (VC-T-405); no node leaks from the fly-chip.
- **Dep:** all above. **Test:** VC-T-405 + full `VC-T-3xx`.

---

## Dependency summary

```
E0  VC-001 → VC-002 → VC-003 ; VC-001 → VC-004
E1  VC-101 → VC-102 → VC-103/104/105/106/107 → VC-108
E2  VC-108 → VC-201 → VC-202/203/204 ; VC-201→VC-205 ; VC-205→VC-206 ; VC-207 ; VC-208 ; VC-003→VC-209
E3  VC-004+VC-108 → VC-301 → VC-302/303/304/305/306
E4  VC-301 → VC-401 → VC-402/403/404
E5  E3 → VC-501/502/503 → VC-504 (gate)
```

Build top-to-bottom. Human review checkpoints at end of **E1** (visual parity, incl. dense three-column layout), **E3** (real data), **E4** (feels right on the Pi).
