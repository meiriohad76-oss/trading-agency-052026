# Variation A — Implementation Guide

The master build instructions for the Pre-Flight Cockpit. Pair this with `TICKETS.md` (the backlog), `TESTING.md` (verification), and `DEFINITION-OF-DONE.md` (the gate). Design reasoning lives in `../01-design-philosophy.md` and `../03-variation-a.md` — this doc is the *how*.

---

## 1. What you are building

A single-page, single-user kiosk app. One operator opens it once or twice a day near market open, reviews the agent's recommended trades across four sequential phases, clears the manifest through a deliberate submit gate, and walks away. **Sequential layout** — one phase fills the screen at a time; a phase rail at the top shows progress. Target hardware: Raspberry Pi 4/5 in Chromium kiosk at 1920×1080 landscape.

The prototype (`src/Variation A.html`) already solves the visual + interaction design. Your job is to make it a real, bundled, backend-driven, Pi-hardened product — not to redesign it.

## 2. Target stack

Recommended (closest to the prototype, tiny bundles, runs anywhere):

- **Build:** Vite
- **UI:** React 18 (the prototype is already React) + **plain CSS** (port `cockpit.css` as-is; it is mostly CSS variables)
- **Language:** TypeScript — port `data.js` to a typed module so the data contract is enforced
- **Output:** a single static `/dist` directory (HTML + JS + CSS + fonts), served by the agent's existing local HTTP process

Do **not** reach for Next.js (overkill for a one-page kiosk), Tailwind (the prototype is CSS-variable driven — converting is churn for no gain), or any component library (the design uses almost no chrome; a kit fights it). If you have a strong reason to deviate, that's a **[CONFIRM]** with the human.

## 3. Source map — what's in `src/` and where it goes

| Prototype file | Lines | Role | Ports to |
|---|---|---|---|
| `Variation A.html` | ~144 | Bootstraps React/Babel, defines tweak presets, scale-to-fit, mounts `<App>` | `index.html` + `src/main.tsx` + `src/theme/presets.ts` |
| `cockpit/cockpit.css` | ~126 | Shared base styles, `.vA` palette scope, calm-mode overrides | `src/styles/cockpit.css` (keep `.vA` scope or migrate to a root data-attr) |
| `cockpit/data.js` | ~462 | `window.COCKPIT_DATA` mock — the full data shape | `src/data/mock.ts` (typed) → later replaced by API fetch |
| `cockpit/shell.jsx` | ~230 | Hooks + primitives: `useCockpitCountdown`, `useAnimatedValue`, `CockpitTip`, `WhyMark`, `CockpitOverlay` | `src/shell/*` (one file per export) |
| `cockpit/panels.jsx` | — | The six instrument panels (Universe, Signals, TickerDetail, Audit, Policy, Monitor) | `src/panels/*` (one file per panel) |
| `cockpit/variation-a-preflight.jsx` | ~1265 | The whole Variation A tree: cluster, engine strip, phase rail, 4 phases, scenario states | `src/cockpit/*` (split — see §5) |
| `tweaks-panel.jsx` | — | Floating tweaks card (starter component) | becomes the **Settings overlay** — see `../08-tweaks.md` |

### Component inventory inside `variation-a-preflight.jsx`

Port these as named components (the tickets reference them by name):

- **Primitives:** `StatusLight`, `ArcGauge`, `ConvictionDial`, `SegDisplay`, `DecisionBtn`, `PreviewRow`, `MetaSm`, `CapBar`
- **Cluster row:** `InstrumentCluster` (4 `ArcGauge` + 3 `SegDisplay`), `EngineStrip`
- **Nav:** instruments nav (Universe / Signals / Audit / Policy / Monitor), `PhaseRail`
- **Phases:** `CandidatesPhase` (+ `ExpandedCandidate`), `PortfolioPhase`, `ClearancePhase`, `ClearedPhase`
- **Scenario states:** `OutageStateA`, `NoActionableStateA`
- **Root:** `VariationA({ density, scenario })`

## 4. Build phases (milestones)

Mirrors `../10-implementation-order.md`, scoped to Variation A. Each phase maps to an epic in `TICKETS.md`.

| Phase | Epic | Goal | Est. |
|---|---|---|---|
| 0 | **VA-E0 · Project setup** | Vite + TS + React, bundle pipeline, fonts, local server wiring | ½ day |
| 1 | **VA-E1 · Static shell** | Layout renders pixel-accurate with hardcoded data, no interactions | 1 day |
| 2 | **VA-E2 · Interactions** | Decisions, phase nav, scenarios, panels, settings — all behave like prototype | 1 day |
| 3 | **VA-E3 · Backend integration** | Real data drives the cockpit; submit hits a real paper broker | 1.5–2 days |
| 4 | **VA-E4 · Pi hardening** | Offline assets, touch, persistence, kiosk autostart | ½ day |
| 5 | **VA-E5 · Edge cases & polish** | Empty/partial states, live scenario transitions, stale-data warning, QA matrix | 1 day |

**Total: ~5–6 working days** for a careful single-dev build to production-ready. The expensive, variable parts are E3 (depends on the agent's API design) and E4 if you have not done Pi kiosk work before.

Build the phases **in order**. Each unlocks the next. Don't start E3 before E2 is visually signed off by the human.

## 5. Recommended repo layout

```
src/
  main.tsx                  ← mount, scale-to-fit, theme injection
  index.css                 ← :root font vars + reset
  styles/cockpit.css        ← ported .vA palette + calm overrides
  theme/
    presets.ts              ← COLOR_PRESETS, THEME_PRESETS, tweaksToCss (from the HTML)
    useFitScale.ts
  data/
    types.ts                ← the typed schema (from ../07-data-schema.md)
    api.ts                  ← fetch + SSE client (E3)
    mock.ts                 ← ported COCKPIT_DATA (kept only for tests after E3)
  shell/
    useCockpitCountdown.ts
    useAnimatedValue.ts
    CockpitTip.tsx
    WhyMark.tsx
    CockpitOverlay.tsx
  panels/
    PanelUniverse.tsx  PanelSignals.tsx  PanelTickerDetail.tsx
    PanelAudit.tsx     PanelPolicy.tsx   PanelMonitor.tsx
  cockpit/
    VariationA.tsx          ← root, owns phase + decisions + exits + scenario state
    InstrumentCluster.tsx   ArcGauge.tsx  ConvictionDial.tsx  SegDisplay.tsx
    EngineStrip.tsx         PhaseRail.tsx
    phases/
      CandidatesPhase.tsx   PortfolioPhase.tsx
      ClearancePhase.tsx    ClearedPhase.tsx
    scenarios/
      OutageStateA.tsx      NoActionableStateA.tsx
  settings/
    SettingsOverlay.tsx     ← replaces tweaks-panel.jsx
    usePreferences.ts       ← persisted color/theme/density
```

Keep files small. `variation-a-preflight.jsx` is 1,265 lines in the prototype because it's a single throwaway file — **split it** on the way in.

## 6. State ownership

`VariationA` is the root. It owns:

| State | Source of truth | Persistence (real product) |
|---|---|---|
| `phase` (`candidates`/`portfolio`/`clearance`/`submitted`) | `VariationA` | local; reset on cycle change |
| `decisions` (`{ [ticker]: 'approve'\|'defer'\|'reject' }`) | `VariationA` | localStorage; reset on cycle change |
| `exits` (`{ [ticker]: 'close'\|'keep' }`) | `VariationA` | localStorage; reset on cycle change |
| `gateOpen` | `ClearancePhase` | **never persist** — always starts closed |
| `phrase` | `ClearancePhase` | **never persist** — always starts empty |
| `expanded` (which candidate row is open) | `CandidatesPhase` | local; ephemeral |
| `scenario` | backend `scenarioHint` (debug toggle in prototype) | n/a — server-driven |
| color / theme / density prefs | `usePreferences` | **persist across sessions** |

The derived numbers — P/L, stop distance, `grossPostTrade` — are **computed in the UI**, never stored. See `../07-data-schema.md → positions / account`.

## 7. Backend integration (E3)

The prototype reads a static `window.COCKPIT_DATA`. The real product is a thin client of the agent. Contract sketch (Codex finalizes — see `../07-data-schema.md`):

| Endpoint | Method | Drives |
|---|---|---|
| `GET /api/cockpit` | GET | one-shot snapshot: cycle, market, engines, funnel, candidates, positions, account, sectors, sources, signals, policy |
| `GET /api/cycle` | GET | cheap poll: cycle + market + engines (for the countdown + engine strip + outage trigger) |
| `POST /api/decisions` | POST | the submit. Body `{ decisions, exits, phrase }`. Returns broker order IDs → drives Phase 4 |
| `PUT /api/policy` | PUT | Policy panel writes (add the diff + confirm step the prototype lacks) |
| `GET /api/monitor/stream` | SSE | live event stream for `PanelMonitor` |
| `GET /api/audit/:ticker` | GET | lifecycle trace on demand for `PanelAudit` |

Key deltas from the prototype:
- `grossPostTrade` must recompute live as the user approves/defers (prototype hardcodes 84%).
- Order IDs come from the broker response, not `ALP-${Math.random()...}`.
- `scenario` comes from `scenarioHint`; the cockpit must handle it **changing mid-session** (e.g. feeds die while the user is in Phase 2 → transition to outage, preserving staged decisions). See `../06-states.md`.
- Submit is real: handle success (→ Phase 4), error (show in the gate panel with retry), and never-persist the gate/phrase.

## 8. Pi hardening (E4) — the non-negotiables

From `../09-raspberry-pi.md`:

- **No CDNs.** Bundle React, ReactDOM, everything. The prototype's unpkg + Babel-in-browser must be gone.
- **Bundle fonts.** Ship WOFF2 locally (`@font-face`). Sans → Inter or IBM Plex Sans; Mono → JetBrains Mono or IBM Plex Mono. The prototype's system stack may not exist on Pi.
- **Touch:** bump decision buttons (Approve/Defer/Reject are 24px in the prototype) and all tappable targets to **≥ 44px**. Tooltips appear on tap-and-hold (~300ms), not hover. Disable the tap-highlight, set `touch-action: manipulation`.
- **Persistence:** decisions + exits + tweak prefs to localStorage; a "restore your session?" prompt on reload mid-cycle. Gate + phrase never persist.
- **Kiosk:** systemd autostart of Chromium `--kiosk`, restart on crash, disable screen sleep, `unclutter` the cursor.
- **Budget:** cold-start < 3s, idle CPU < 5%, memory < 200MB after 8h, 60fps on the gauge/needle animations.

## 9. What NOT to port

(From `../10-implementation-order.md → What NOT to build`.)

- The **DesignCanvas** wrapper / `design-canvas.jsx` — that's the design tool, not the product. The product is one variation, full-bleed.
- The **floating draggable Tweaks card** — becomes a Settings overlay (gear icon or long-press the brand logo). See `../08-tweaks.md`.
- The `/*EDITMODE-BEGIN*/…/*EDITMODE-END*/` markers — design-tool plumbing. Strip them; hard-code defaults or read the Pi config file.
- The **"Start over"** button in Phase 4 — demo-only. The next cycle resets state in production.
- Mock random order IDs.

## 10. Scope discipline

The prototype is the scope. **Don't add** features it doesn't show (no charts, no watchlists, no news feed — see `../01-design-philosophy.md → What's not in this design`). **Don't remove** anything either — every element is load-bearing (the conviction needle is the skim-scan read; the WhyMark tooltips are how the user learns the gauges). If reality forces a non-trivial deviation, **flag it as a [CONFIRM]** rather than quietly inventing or deleting. `LIVE_TRADING` stays locked off for v1 — that is not negotiable.
