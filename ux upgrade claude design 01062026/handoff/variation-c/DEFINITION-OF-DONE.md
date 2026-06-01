# Variation C — Definition of Done

A ticket, epic, or the whole build is **not done** until the relevant boxes are checked. This is the gate. `[CONFIRM]` items must be resolved with the human.

---

## Global DoD (every ticket)

- [ ] Output matches `src/Variation C.html` within reason — 4px grid, exact `.vC` palette, **all numbers in mono**.
- [ ] No new colours, icons, or fonts (six-colour rule + no-icons rule hold).
- [ ] No console errors/warnings; no orphaned timers/listeners (clean unmount); **no leaked fly-chip nodes**.
- [ ] TypeScript strict — no `any`, no unexplained `@ts-ignore`.
- [ ] Linked `VC-T-###` tests pass.
- [ ] Esc closes overlays; focus order sane.
- [ ] Files split sensibly — no carry-over of the 1,103-line monolith.

---

## VC-E0 · Project setup
- [ ] `npm run dev`/`build` work; `/dist` is one static dir.
- [ ] `cockpit.css` ported; `.vC` palette + `[data-calm-hide]` + `grid-bg` resolve; local `@font-face` wired.
- [ ] 3 color × 3 theme presets inject `.vC` vars; scale-to-fit (1440×1000) letterboxes (VC-T-101).
- [ ] `data/types.ts` covers every field in `../07-data-schema.md`; `mock.ts` typed (VC-004).
- [ ] EDITMODE markers stripped; defaults hard-coded.

## VC-E1 · Static shell  — _human review checkpoint_
- [ ] Shell hooks + scoped overlay behave (VC-T-001…003).
- [ ] `MCColumn`/`MCBadge`/`Telem` active/dimmed correct.
- [ ] Telemetry strip matches; gross "67 → 84%"; calm-hide attr present (VC-T-005).
- [ ] Three columns render statically (VC-T-007…009); footer engine strip correct.
- [ ] Full assembly matches prototype; Stage 01 active, others full-opacity (VC-T-010).
- [ ] **Pixel parity reviewed by the human** at 1920×1080 — incl. the dense three-column layout.

## VC-E2 · Interactions
- [ ] Decisions update manifest + counters + meters together; reversible (VC-T-011, VC-T-012).
- [ ] Gate: SAFE→ARMED, phrase, TRANSMIT — all three required (VC-T-013, VC-T-014).
- [ ] Keep/close feeds exits-first + counter (VC-T-015).
- [ ] Selection drives detail pane; survives scenario switch (VC-T-016).
- [ ] **Fly-to-manifest** spawns/lands/cleans up; no leak; reduced-motion honoured (VC-T-017).
- [ ] **Auto-advance** rules correct; submit dims two columns (VC-T-018).
- [ ] Six panels open/close with `.vC` palette, preserve state (VC-T-019, VC-T-020).
- [ ] Four scenarios via debug + `?scenario=` (VC-T-021, VC-T-302…305).
- [ ] Settings overlay replaces floating card; calm hides telem-mid + footer; A/C not exposed (VC-T-022).
- [ ] **[CONFIRM]** Settings entry point.

## VC-E3 · Backend integration  — _human review checkpoint_
- [ ] Renders from live API; loading/error/empty (VC-T-023).
- [ ] Telemetry/counters/meters/heatmap/gross recompute live from staged state (VC-T-024).
- [ ] Submit returns **real broker IDs**; success → submitted pane + dim; failure handled; double-submit guarded (VC-T-025, VC-T-026).
- [ ] Monitor SSE with reconnect + filters (VC-T-027).
- [ ] Policy diff+confirm; `LIVE_TRADING` cannot be enabled (VC-T-028).
- [ ] Audit fetches on demand (VC-T-029).
- [ ] `mock.ts` no longer drives the running app.
- [ ] **Real data reviewed by the human.**

## VC-E4 · Pi hardening  — _human review checkpoint_
- [ ] Fully offline; local fonts; zero external requests (VC-T-401).
- [ ] Touch targets ≥ 44px incl. panel-nav letters; long-press tips; no delay/zoom; strip fits (VC-T-402).
- [ ] Persistence + restore; never persist gate/phrase; cycle change clears + resets the dim (VC-T-403).
- [ ] Kiosk autostart + crash-restart + no sleep; systemd unit documented (VC-T-404).
- [ ] Performance budget incl. animation fps + no node leak (VC-T-405).
- [ ] **[CONFIRM]** Pi model + touch vs non-touch.

## VC-E5 · Edge cases & polish  — _final gate_
- [ ] Empty/partial states; TRANSMIT copy adapts (VC-T-030).
- [ ] Live scenario transitions preserve staged state; stale-data warning > 60s (VC-T-031).
- [ ] Production cleanup complete; **no "Start over" button exists** (`IMPLEMENTATION.md §10`).
- [ ] **[CONFIRM]** empty-portfolio + persist-through-outage behaviour.
- [ ] Full QA matrix signed off (below).

---

## QA matrix sign-off  (VC-504)

Per `TESTING.md §8`.

**Scenario/column states @ amber/accent/full:**
- [ ] normal · 3 columns  - [ ] normal · after approval (Stage 02 active)  - [ ] normal · gate armed + phrase ok
- [ ] submitted (dim + submitted pane)  - [ ] no-actionable  - [ ] outage  - [ ] all six panels

**Density:** - [ ] full  - [ ] calm (telem-mid + footer hidden, usable)
**Theme:** - [ ] dark  - [ ] accent  - [ ] light (status colours read on paper bg)
**Color:** - [ ] amber  - [ ] duotone  - [ ] saturated
**Animation under load:** - [ ] 20 rapid approvals — chips clean up, no leak, auto-advance correct
**Spot-checks:** - [ ] 6–8 off-default compositions

---

## Ship gate (all must hold)

- [ ] Three columns pixel-accurate at 1920×1080 with correct active/dimmed states.
- [ ] Fly-to-manifest + auto-advance work.
- [ ] Four scenarios reachable + correct (incl. submitted dim).
- [ ] Six panels open / render real data / close.
- [ ] Clearance works end-to-end against the real paper broker.
- [ ] Color/theme/density persist across reboot; calm mode strips telem-mid + footer.
- [ ] 8+ hours in kiosk within the performance budget; no node leaks.
- [ ] `LIVE_TRADING` locked off; no "Start over" button.
- [ ] Every `[CONFIRM]` resolved with the human.
