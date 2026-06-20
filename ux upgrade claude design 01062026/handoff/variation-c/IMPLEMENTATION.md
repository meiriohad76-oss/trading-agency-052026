# Variation C — Implementation Guide

The master build instructions for Mission Control. Pair with `TICKETS.md` (backlog), `TESTING.md` (verification), and `DEFINITION-OF-DONE.md` (the gate). Design reasoning lives in `../01-design-philosophy.md` and `../04-variation-c.md` — this doc is the *how*.

---

## 1. What you are building

A single-page, single-user kiosk app — same workflow as Variation A, **different layout philosophy**. Instead of one phase at a time, all three stages (Candidates · Portfolio · Clearance) are visible **simultaneously as three columns**. The operator works left-to-right and sees the consequence of every decision immediately on the right. A dense telemetry strip on top is the standing context; a footer engine strip runs along the bottom. Aesthetic: NASA launch console — amber on near-black with cyan secondary. Target hardware: Raspberry Pi 4/5 in Chromium kiosk at 1920×1080 landscape.

The prototype (`src/Variation C.html`) already solves the visual + interaction design, including the signature fly-to-manifest animation. Your job is to make it real, bundled, backend-driven, and Pi-hardened — not to redesign it.

## 2. Target stack

Same as Variation A: **Vite + React 18 + plain CSS + TypeScript**, output a single static `/dist` served by the agent's local HTTP process. Port `cockpit.css` as-is (`.vC` scope). Don't reach for Next.js / Tailwind / a component library. Deviations are a **[CONFIRM]**.

## 3. Source map — what's in `src/` and where it goes

| Prototype file | Lines | Role | Ports to |
|---|---|---|---|
| `Variation C.html` | ~140 | Bootstraps React/Babel, tweak presets (`.vC` vars), scale-to-fit (1440×1000), mounts `<App>` | `index.html` + `src/main.tsx` + `src/theme/presets.ts` |
| `cockpit/cockpit.css` | ~126 | Shared base styles, `.vC` palette scope, calm-mode overrides (`[data-calm-hide]`) | `src/styles/cockpit.css` |
| `cockpit/data.js` | ~462 | `window.COCKPIT_DATA` mock | `src/data/mock.ts` (typed) → later API |
| `cockpit/shell.jsx` | ~230 | Hooks + primitives (`useCockpitCountdown`, `useAnimatedValue`, `CockpitTip`, `WhyMark`, `CockpitOverlay`) | `src/shell/*` |
| `cockpit/panels.jsx` | — | The six instrument panels | `src/panels/*` |
| `cockpit/variation-c-mission.jsx` | ~1103 | The whole Variation C tree | `src/cockpit/*` (split — see §5) |
| `tweaks-panel.jsx` | — | Floating tweaks card | becomes the **Settings overlay** (`../08-tweaks.md`) |

> Note: `CockpitOverlay` takes a `scope` prop — pass `scope="vC"` so panels inherit the Mission Control palette.

### Component inventory inside `variation-c-mission.jsx`

Port these as named components (tickets reference them by name):

- **Primitives:** `MCBadge`, `MCColumn` (header + body + active/dimmed), `Telem`, `PanelNavBtn`, `CrosshairMark`, `ConvictionBar`, `DataChip`, `MCDecisionBtn`, `MiniMeter`
- **Top strip:** `TelemetryStrip` (brand · live metrics · approval counters · panel nav)
- **Stage 01:** `CandidatesColumn` (+ `FunnelCrumbs`, `CandidateDetailC`, `SidebySide`)
- **Stage 02:** `PortfolioColumn` (+ `SectorRadar` heatmap, `MiniMeter`s)
- **Stage 03:** `ClearanceColumn` (+ `ManifestRow`, `GatePanel`, `SubmittedPane`)
- **Scenario states:** `OutageStateC`, `NoActionableStateC`
- **Footer:** engine strip (bottom)
- **Root:** `VariationC({ density, scenario })` — owns `stage`, `decisions`, `exits`, `selected`, and the fly-chip queue

## 4. Build phases (milestones)

Mirrors `../10-implementation-order.md`, scoped to Variation C. Each maps to an epic in `TICKETS.md`.

| Phase | Epic | Goal | Est. |
|---|---|---|---|
| 0 | **VC-E0 · Project setup** | Vite + TS + React, bundle pipeline, fonts, server wiring | ½ day |
| 1 | **VC-E1 · Static shell** | Three columns + telemetry + footer render pixel-accurate, no interactions | 1–1.5 days |
| 2 | **VC-E2 · Interactions** | Decisions, fly-to-manifest, auto-advance, gate, panels, scenarios, settings | 1.5 days |
| 3 | **VC-E3 · Backend integration** | Real data drives the cockpit; submit hits a real paper broker | 1.5–2 days |
| 4 | **VC-E4 · Pi hardening** | Offline assets, touch, persistence, kiosk autostart | ½ day |
| 5 | **VC-E5 · Edge cases & polish** | Empty/partial states, live transitions, stale-data warning, QA matrix | 1 day |

**Total: ~5.5–6.5 working days.** C is marginally heavier than A in E1/E2 (the dense three-column layout + the fly-to-manifest animation + auto-advance logic). Build phases in order; don't start E3 before E2 is signed off.

## 5. Recommended repo layout

```
src/
  main.tsx                  ← mount, scale-to-fit (1440×1000), theme injection
  index.css
  styles/cockpit.css        ← ported .vC palette + calm overrides
  theme/ presets.ts  useFitScale.ts
  data/ types.ts  api.ts  mock.ts
  shell/ useCockpitCountdown.ts  useAnimatedValue.ts  CockpitTip.tsx  WhyMark.tsx  CockpitOverlay.tsx
  panels/ PanelUniverse.tsx … PanelMonitor.tsx
  cockpit/
    VariationC.tsx          ← root: stage, decisions, exits, selected, fly-chip queue, auto-advance
    TelemetryStrip.tsx  Telem.tsx  PanelNavBtn.tsx  CrosshairMark.tsx  MCBadge.tsx
    MCColumn.tsx
    stages/
      CandidatesColumn.tsx  FunnelCrumbs.tsx  CandidateDetailC.tsx  ConvictionBar.tsx
      PortfolioColumn.tsx   SectorRadar.tsx   MiniMeter.tsx
      ClearanceColumn.tsx   ManifestRow.tsx   GatePanel.tsx  SubmittedPane.tsx
    FlyChip.tsx             ← the approve→manifest animation
    EngineFooter.tsx
    scenarios/ OutageStateC.tsx  NoActionableStateC.tsx
  settings/ SettingsOverlay.tsx  usePreferences.ts
```

Split `variation-c-mission.jsx` (1,103 lines) on the way in — don't carry the monolith.

## 6. State ownership

`VariationC` is the root. It owns:

| State | Source of truth | Persistence (real product) |
|---|---|---|
| `stage` (0 candidates / 1 portfolio / 2 clearance — the **active/bright** column) | `VariationC` | local; reset on cycle change |
| `decisions` (`{ [ticker]: 'approve'\|'defer'\|'reject' }`) | `VariationC` | localStorage; reset on cycle change |
| `exits` (`{ [ticker]: 'close'\|'keep' }`) | `VariationC` | localStorage; reset on cycle change |
| `selected` (highlighted candidate in the list → drives the detail pane) | `VariationC` | local; defaults to top candidate |
| fly-chip queue | `VariationC` | ephemeral; cleared 750ms after spawn |
| `gateOpen` / `phrase` | `ClearanceColumn`/`GatePanel` | **never persist** |
| `scenario` | backend `scenarioHint` | server-driven |
| color / theme / density prefs | `usePreferences` | **persist across sessions** |

Derived numbers (P/L, `grossPostTrade`, mini-meters, approval counters) are **computed in the UI** from live data + staged decisions — never stored. The telemetry counters, portfolio mini-meters, and gross gauge must all update together as the user approves (see `../04-variation-c.md → strength`).

## 7. The two C-specific behaviours (don't cut these)

### Fly-to-manifest (VC-205)
On approve, spawn a green chip (`▸ TICKER`) from the click position that animates toward the clearance column and lands in the manifest area. 700ms translate + scale-down + fade; chip is `position: fixed`, `z 60`, doesn't affect layout; cleared 750ms after spawn. This is the payoff of the three-column design — a single CSS keyframe, high feel value. See `../04-variation-c.md → The signature animation`.

### Auto-advance (VC-206)
The bright/active column advances on activity: start = Stage 01; first approval → Stage 02 (or 03 if exits were also staged); clicking inside any column makes it active. Subtle navigation — the user doesn't manage stages; the brighter background + amber underline signal where the system thinks they are. On submit, all three columns dim except clearance (which shows `SubmittedPane`).

## 8. Backend integration (E3)

Same contract as Variation A (the data layer is shared). Endpoints: `GET /api/cockpit`, `GET /api/cycle`, `POST /api/decisions`, `PUT /api/policy`, `GET /api/monitor/stream` (SSE), `GET /api/audit/:ticker`. See `../07-data-schema.md`. C-specific deltas:

- The telemetry strip's live metrics (SPY/VIX/breadth/gross/cash/open-orders) + approval counters bind to live `market` + `account` + derived staged state.
- `grossPostTrade` (the "67 → 84%" Gross telem + the mini-meter) recomputes live.
- Sector heatmap binds to live `sectors`.
- Submit returns broker order IDs → `SubmittedPane` cards.
- `scenarioHint` can change mid-session → handle live (outage can interrupt; on recovery, restore staged state).

## 9. Pi hardening (E4) — the non-negotiables

From `../09-raspberry-pi.md`: no CDNs (bundle React/ReactDOM, no Babel-in-browser), bundle WOFF2 fonts locally, touch targets ≥ 44px (decision buttons + the ≤26px square panel-nav letters especially), tap-and-hold tooltips, persistence + restore prompt (decisions/exits/prefs; never gate/phrase), systemd kiosk autostart + crash-restart + no screen sleep. Budget: cold-start < 3s, idle CPU < 5%, < 200MB after 8h, 60fps on the fly-chip + conviction-bar animations.

> Touch note: the panel-nav buttons are single-letter ≤26px squares (U/S/A/P/M) — too small for touch. Enlarge to ≥ 44px on the Pi build without breaking the dense strip layout.

## 10. What NOT to port

(From `../10-implementation-order.md → What NOT to build`.)

- The **DesignCanvas** wrapper / `design-canvas.jsx` — design tool, not product.
- The **floating draggable Tweaks card** — becomes a Settings overlay. The middle telemetry block + footer engines are the calm-mode hide targets (`[data-calm-hide]`).
- The `/*EDITMODE*/` markers — strip them.
- Mock random order IDs.
- **No "Start over" button** — C deliberately has none; the next cycle clears the dim and reactivates Candidates. Don't add one.

## 11. Scope discipline

The prototype is the scope (`../01-design-philosophy.md`). Don't add (no charts/watchlists/news feed). Don't remove — the dense telemetry strip is the standing context, not decoration; the sector heatmap is *why* positions are tagged REVIEW/CLOSE (don't hide it); the fly-chip is the cause→effect payoff. Non-trivial deviations are **[CONFIRM]**, not silent edits. `LIVE_TRADING` stays locked off for v1.
