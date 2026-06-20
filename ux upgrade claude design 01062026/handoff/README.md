# Trading Agency Cockpit — Codex Handoff

You are implementing a **trading agent cockpit** that runs on a **Raspberry Pi**. The human operator opens it once a day, approves the agent's recommended trades, and closes it. Two design directions are included in this handoff — **A (Pre-Flight)** and **C (Mission Control)**. Both express the same workflow; pick one and build it (or build A first, then port to C).

## ⮕ Building a dashboard? Go straight to its package.

Each dashboard has a **self-contained build package** — a runnable copy of the prototype plus a full implementation guide, ticket-by-ticket backlog, test plan, and definition of done. **This is where you actually work.**

| Package | Build this if… | Contains |
|---|---|---|
| **[`variation-a/`](variation-a/README.md)** | sequential, instrument-cluster cockpit (focus, touch-friendly, teaches itself) | `README` · `IMPLEMENTATION.md` · `TICKETS.md` (VA-###) · `TESTING.md` · `DEFINITION-OF-DONE.md` · `src/` |
| **[`variation-c/`](variation-c/README.md)** | parallel three-column Mission Control (dense, simultaneity, ambient dashboard) | `README` · `IMPLEMENTATION.md` · `TICKETS.md` (VC-###) · `TESTING.md` · `DEFINITION-OF-DONE.md` · `src/` |

Start in the package's `README.md`, then `IMPLEMENTATION.md` → `TICKETS.md`. The numbered docs below (`01`–`10`) are the **shared context** every package references by number — read them first as the *why*; the packages are the *how*.

> Pick **one**. A and C are different products, not a runtime toggle (see `08-tweaks.md`). Default: build A first. Decide with the human in Phase 0 of `10-implementation-order.md`.

---

## Shared context — read in this order:

1. **`01-design-philosophy.md`** — the *why*. Mental models, principles, what to preserve and what's negotiable. **Read this first** — it's the lens for everything else.
2. **`02-user-workflow.md`** — what the user actually does, in order, in plain English.
3. **`03-variation-a.md`** — Pre-Flight cockpit spec (instrument-cluster aesthetic, sequential phases).
4. **`04-variation-c.md`** — Mission Control spec (three columns always visible, NASA-console aesthetic).
5. **`05-components.md`** — shared component inventory: gauges, panels, badges, overlays, tooltips, the works.
6. **`06-states.md`** — the four scenarios (normal / no-actionable / outage / submitted) and how each variation expresses them.
7. **`07-data-schema.md`** — placeholder data shape from the prototype. **Codex defines the real backend schema** — this is starting material, not a spec.
8. **`08-tweaks.md`** — configurable axes that ship as a runtime toggle panel.
9. **`09-raspberry-pi.md`** — deployment notes (kiosk mode, offline assets, performance, touch input).
10. **`10-implementation-order.md`** — the build order. Don't skip — it's how to make this tractable.

## What's in this project

```
Variation A.html                  ← Standalone Pre-Flight cockpit (working prototype)
Variation C.html                  ← Standalone Mission Control (working prototype)
Trading Cockpit.html              ← Side-by-side canvas of both (design exploration)

cockpit/
  cockpit.css                     ← Shared base styles + .vA / .vC palette scopes
  data.js                         ← Mock data (treat as placeholder schema reference)
  shell.jsx                       ← Shared hooks: countdown, tooltip, overlay, why-marker
  panels.jsx                      ← Six instrument-panel overlays (Universe, Signals, …)
  variation-a-preflight.jsx       ← Variation A root + sub-components
  variation-c-mission.jsx         ← Variation C root + sub-components

tweaks-panel.jsx                  ← Floating tweaks control panel
design-canvas.jsx                 ← Pan/zoom canvas (design tool — not part of product)

handoff/                          ← These docs (you are here)
  01..10 + README                 ← shared context (the WHY), referenced by both packages
  variation-a/                    ← Pre-Flight build package (the HOW) — runnable src/ + guide + tickets + tests + DoD
  variation-c/                    ← Mission Control build package (the HOW) — runnable src/ + guide + tickets + tests + DoD
```

> The build packages each carry a **frozen copy** of the prototype under `variation-x/src/` so they are self-contained and independently runnable. The root-level `Variation A.html` / `Variation C.html` / `cockpit/` remain the live design files; the package copies are the implementation snapshot.

## How to use the working prototypes

Open `Variation A.html` or `Variation C.html` in a browser. Both are fully interactive:
- Click candidates, expand rows, approve/defer/reject
- Open the five instrument panels from the nav bar (Universe, Signals, Audit, Policy, Monitor)
- Use the **Tweaks** panel (floating button) to switch color preset, theme, density mode, and scenario state
- The clearance flow is real — open the gate, type the confirmation phrase, submit

The prototypes are the **source of truth for visual + interaction design**. The docs explain the *reasoning* so you can make sensible decisions when reality doesn't match the prototype exactly.

## What "done" looks like

A Raspberry-Pi-ready app where:
- The chosen variation renders pixel-accurate to the prototype at 1920×1080
- All four scenarios are reachable and visually correct
- All five instrument panels open, render real data, close cleanly
- The clearance flow works end-to-end with a real broker integration (paper first)
- The Tweaks panel ships as a runtime preference menu (color/theme/density)
- It runs reliably for 8+ hours in kiosk mode without memory bloat or font/asset misses

## What to ask the human about

Anything in these docs marked **[CONFIRM]**. There are explicit hooks for decisions the prototype mocks but the real build needs to nail down.
