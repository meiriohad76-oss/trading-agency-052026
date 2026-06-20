# 10 · Implementation Order

A pragmatic build sequence. **Don't deviate without reason** — each milestone unlocks the next.

The plan assumes a single developer (Codex) building one variation end-to-end before iterating. If you build both variations in parallel, you'll get neither right.

## Phase 0 — Decide

Before writing code:

1. **Pick A or C.** Read `03-variation-a.md` and `04-variation-c.md`, look at the prototypes side-by-side in `Trading Cockpit.html`. **Ask the human.** Default: build A first (it's the simpler shape and teaches the workflow). Port to C later if desired.
2. **Pick the stack.** The human's note says "runs on Raspberry Pi" — no specific framework. Recommended: **Vite + React + plain CSS** (closest to the prototype, builds tiny bundles, runs anywhere). Alternatives: Next.js (overkill for a single-page kiosk), SvelteKit (smaller, but you'd be porting the prototype's React).
3. **Set up the bundle pipeline.** Vite project, JSX → JS, CSS bundled, fonts bundled, output is a single `/dist` directory.
4. **Set up the local server.** The agent's existing Node process serves `/dist` and exposes `/api/*`. **[CONFIRM]** with the human what process is running on the Pi.

## Phase 1 — Static shell (½ day)

Goal: the cockpit renders the prototype's *layout* with hardcoded data. No interactions yet.

1. Port `cockpit.css` as-is (it's mostly variables + scoped resets).
2. Port `data.js` as a typed TypeScript module (`cockpit-data.ts`).
3. Port `shell.jsx` — the hooks and primitives. `useCockpitCountdown`, `useAnimatedValue`, `<CockpitTip>`, `<WhyMark>`, `<CockpitOverlay>`. These are reusable; get them right.
4. Port the chosen variation's source (`variation-a-preflight.jsx` or `variation-c-mission.jsx`).
5. Render at the target resolution. Verify visual parity with the prototype.

**Acceptance:** open the build in a browser, see the cockpit, click around — non-interactive (no decisions persisted), but visually correct.

## Phase 2 — Interactions wired locally (½ day)

Goal: the cockpit *behaves* like the prototype with hardcoded data.

1. Wire up all decisions (approve / defer / reject for candidates, keep / close for positions, gate / phrase / submit for clearance).
2. Implement the four scenarios as a debug toggle (or via URL param: `?scenario=outage`).
3. Wire up the six instrument panels — they should open / close / scroll correctly.
4. Port the Tweaks panel (or its real-product replacement — `08-tweaks.md`).

**Acceptance:** matches the prototype's behaviour end-to-end. The "submitted" state still doesn't actually submit anything — it just flips the UI.

## Phase 3 — Backend API integration (1–2 days)

Goal: real data drives the cockpit.

1. Implement the agent → cockpit API (sketch in `07-data-schema.md`). Start with **GET /api/cockpit** — one-shot payload. Then add the rest.
2. Replace static `COCKPIT_DATA` with a fetch + React state. Handle loading, error, empty states.
3. Implement the SSE stream for `PanelMonitor`. The monitor should update in real time as the agent emits events.
4. Implement `POST /api/decisions` — the submit flow. Handle success (transition to submitted state), error (show error in the gate panel with retry).
5. Implement `PUT /api/policy` — the Policy panel writes to config. **Add the diff-and-confirm step** the prototype lacks.
6. Implement `GET /api/audit/:ticker` — load lifecycle traces on demand.

**Acceptance:** the cockpit is a thin client of the agent. All data, all writes, real. The prototype's `COCKPIT_DATA` is gone from the codebase.

## Phase 4 — Pi-specific hardening (½ day)

Goal: it runs reliably on the target hardware.

1. Bundle fonts locally (`@font-face` with WOFF2).
2. Remove all CDN dependencies. Bundle React, ReactDOM, everything.
3. Touch input — tap-to-tooltip, larger hit targets on decision buttons (≥ 44px).
4. Implement session-state persistence to localStorage (decisions, exits, tweak prefs).
5. Implement the session-restore prompt on reload mid-cycle.
6. Set up systemd autostart + crash restart for the browser kiosk.

**Acceptance:** kiosk starts on Pi boot, survives a browser crash, persists state across reload, behaves correctly on touch.

## Phase 5 — Edge cases & polish (1 day)

Goal: the cases the prototype doesn't cover.

1. **Empty portfolio** — what does Phase 2 look like with 0 positions?
2. **All-exits, no-buys** — submit button copy adapts.
3. **Mid-session scenario change** — outage hits while user is in clearance; cockpit transitions gracefully.
4. **Stale data warning** — if the cockpit hasn't heard from the agent in > 60s, show a warning.
5. **API error states** — every panel handles its data source being down.
6. **Spot-check all theme × density × scenario combos** — `06-states.md` has a checklist.

**Acceptance:** the cockpit doesn't break in any state the agent can produce.

## Phase 6 — The second variation (optional)

If the human wants both variations buildable:

1. Repeat phase 1 for the other variation source.
2. Choose between them at build time (or runtime, via the Tweaks panel — though "switch variation" is a heavy feature).

## What NOT to build

The prototype shows some patterns that **should not be ported as-is**:

- **The DesignCanvas wrapper** — that's the design tool. The production build is one variation, full-bleed.
- **The Tweaks panel as a floating draggable card** — see `08-tweaks.md`. Probably becomes a settings overlay or a gear icon.
- **The EDITMODE markers** — design-tool plumbing.
- **Mock random order IDs** (`ALP-${Math.floor(Math.random()*90000+10000)}`) — these come from the broker response.
- **The "Start over" button in Variation A's submitted state** — for the real product, the next cycle resets things; an explicit reset button is for demo use.

## Estimating

For a careful single-developer build of Variation A: **4–6 working days** to production-ready on the Pi. Add 1–2 days for Variation C if both ship.

The prototype has done most of the visual + interaction design work. **The expensive parts of this project are:**
1. The backend integration (depends on agent design — could be a day, could be a week)
2. The Pi-specific work (touch input, kiosk setup, fonts) — half a day if you've done it before, several days if not

## Communication checkpoints

Push for human review at:
- **End of Phase 1** — visual parity? Anything missing?
- **End of Phase 3** — does the real data look right in the UI? Any field mismatches?
- **End of Phase 4** — does it feel right on the Pi?

Don't go silent for more than a phase. The prototype is opinionated; if you find yourself making a non-trivial deviation, **flag it.**
