# Variation A — Definition of Done

A ticket, an epic, or the whole build is **not done** until the relevant boxes below are checked. This is the gate. `[CONFIRM]` items must be resolved with the human, not assumed.

---

## Global DoD (applies to every ticket)

- [ ] Output matches `src/Variation A.html` within reason — spacing on the 4px grid, exact palette, **all numbers in mono** (`../05-components.md`).
- [ ] No new colours, icons, or fonts introduced (the six-colour rule + no-icons rule hold).
- [ ] No console errors or warnings; no orphaned `setInterval`/`setTimeout`/event listeners (clean unmount).
- [ ] TypeScript strict — no `any`, no `@ts-ignore` without a comment.
- [ ] Linked `VA-T-###` test cases pass.
- [ ] Keyboard: Esc closes overlays; focus order is sane.
- [ ] Code split sensibly — no single file approaching the prototype's 1,265-line monolith.

---

## VA-E0 · Project setup
- [ ] `npm run dev` and `npm run build` both work; `/dist` is a single static dir.
- [ ] `cockpit.css` ported; `.vA` palette + calm overrides resolve; local `@font-face` wired.
- [ ] All 3 color × 3 theme presets inject correct CSS vars; scale-to-fit letterboxes correctly (VA-T-101).
- [ ] `data/types.ts` covers every field in `../07-data-schema.md`; `mock.ts` typed, no `any` (VA-004).
- [ ] EDITMODE markers stripped; defaults hard-coded (amber / accent / full).

## VA-E1 · Static shell  — _human review checkpoint_
- [ ] Shell hooks + `CockpitOverlay` behave per VA-T-001…003.
- [ ] `ArcGauge`, `ConvictionDial`, `SegDisplay` correct (VA-T-004).
- [ ] Cluster + engine strip read documented values; gauges have WhyMark tips (VA-T-005).
- [ ] Phase rail active/done/locked styling correct (VA-T-006).
- [ ] All four phases render statically (VA-T-007…009); full assembly matches prototype at phase 1 (VA-T-010).
- [ ] **Pixel parity reviewed by the human** at 1920×1080. Anything missing flagged.

## VA-E2 · Interactions
- [ ] Decisions work + are reversible; Advance gating correct; non-actionable rows inert (VA-T-011, VA-T-012).
- [ ] Gate logic: arm → phrase → submit, all three required; resets on leave/return (VA-T-013, VA-T-014).
- [ ] Phase nav guards + Back preservation; exits flow to manifest (VA-T-015).
- [ ] All six panels open/close, render data, preserve state (VA-T-016, VA-T-017).
- [ ] Four scenarios switchable via debug + `?scenario=` (VA-T-018, VA-T-301…305).
- [ ] Settings overlay replaces the floating card; A/C switch not exposed (VA-T-019).
- [ ] **[CONFIRM]** Settings entry point (gear icon vs long-press logo).

## VA-E3 · Backend integration  — _human review checkpoint_
- [ ] Cockpit renders from live API with loading/error/empty states (VA-T-020).
- [ ] Derived numbers recompute live from staged decisions; nothing derived read from payload (VA-T-021).
- [ ] Submit posts and returns **real broker order IDs**; success + failure paths handled; double-submit guarded (VA-T-022, VA-T-023).
- [ ] Monitor consumes SSE with reconnect + filters (VA-T-024).
- [ ] Policy write has diff + confirm; `LIVE_TRADING` cannot be enabled (VA-T-025).
- [ ] Audit fetches on demand for any ticker (VA-T-026).
- [ ] `mock.ts` no longer drives the running app (tests only).
- [ ] **Real data reviewed by the human** — field mapping correct, nothing mislabeled.

## VA-E4 · Pi hardening  — _human review checkpoint_
- [ ] Fully offline: zero external requests; fonts local (VA-T-401).
- [ ] Touch targets ≥ 44px; long-press tips; no click delay; no zoom (VA-T-402).
- [ ] Session persists + restore prompt; gate/phrase never persist; cycle change resets (VA-T-403).
- [ ] Kiosk autostart + crash-restart + no screen sleep; systemd unit documented (VA-T-404).
- [ ] Performance budget met on-device (VA-T-405).
- [ ] **[CONFIRM]** Pi model + touch vs non-touch.

## VA-E5 · Edge cases & polish  — _final gate_
- [ ] Empty/partial states render; submit copy adapts (VA-T-027).
- [ ] Live scenario transitions preserve staged decisions; stale-data warning past 60s (VA-T-028).
- [ ] Production cleanup complete — no "Start over", EDITMODE, mock IDs, DesignCanvas/floating-tweaks remnants (`IMPLEMENTATION.md §9`).
- [ ] **[CONFIRM]** empty-portfolio behaviour; persist-through-outage behaviour.
- [ ] Full QA matrix signed off (below).

---

## QA matrix sign-off  (VA-504)

Per `TESTING.md §8`. Tick what you actually verified.

**All 10 visual states @ amber/accent/full:**
- [ ] normal · phase 1  - [ ] normal · phase 2  - [ ] normal · phase 3 gate closed
- [ ] normal · phase 3 armed  - [ ] normal · phase 3 phrase-ok/submit-ready  - [ ] normal · phase 4
- [ ] no-actionable  - [ ] outage  - [ ] submitted  - [ ] all six panels open/close

**Density:** - [ ] full (rep. phase)  - [ ] calm (rep. phase + scenario)
**Theme:** - [ ] dark  - [ ] accent  - [ ] light (status colours still read)
**Color:** - [ ] amber  - [ ] duotone  - [ ] saturated
**Spot-checks:** - [ ] 6–8 off-default compositions, no layout breakage

---

## Ship gate (all must hold)

- [ ] Four phases pixel-accurate at 1920×1080.
- [ ] Four scenarios reachable + correct.
- [ ] Six panels open / render real data / close.
- [ ] Clearance works end-to-end against the real paper broker.
- [ ] Color/theme/density persist across reboot.
- [ ] 8+ hours in kiosk within the performance budget.
- [ ] `LIVE_TRADING` locked off.
- [ ] Every `[CONFIRM]` resolved with the human.
