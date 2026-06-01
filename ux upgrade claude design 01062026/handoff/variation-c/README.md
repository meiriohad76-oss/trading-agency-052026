# Variation C — Mission Control · Build Package

> Self-contained implementation package for **one** dashboard: Mission Control (NASA-console aesthetic, three columns always visible). Everything Codex needs to take this from prototype to a Raspberry-Pi-ready product lives in this folder.

If you are building **Variation A** instead, use `../variation-a/` — do not build both in one binary (see `../08-tweaks.md → Things that are NOT tweaks`). A and C are different products, not a runtime toggle.

---

## Read in this order

| # | File | What it is |
|---|------|-----------|
| 1 | **`IMPLEMENTATION.md`** | The master build guide: target stack, repo layout, file-by-file port plan, the fly-to-manifest animation, auto-advance, API contract, Pi hardening. Start here. |
| 2 | **`TICKETS.md`** | Every unit of work as a numbered ticket (`VC-###`) grouped into epics, each with scope, acceptance criteria, dependencies, and an estimate. Your backlog. |
| 3 | **`TESTING.md`** | Test strategy, the full QA matrix, named test cases (`VC-T-###`), and how to run them. |
| 4 | **`DEFINITION-OF-DONE.md`** | The global DoD plus a per-epic DoD checklist. A ticket isn't done until its box is checked. |
| — | **`src/`** | A frozen, runnable copy of the prototype. Open `src/Variation C.html` to see exactly what you're building. |

## Shared context (one level up)

Read once — the *why* behind every ticket. Tickets reference them by number.

- `../01-design-philosophy.md` — the five principles. The lens.
- `../02-user-workflow.md` — what the operator does, in order.
- `../04-variation-c.md` — the design spec for **this** dashboard (three columns, telemetry strip, fly-to-manifest, auto-advance, sector heatmap). **Your primary spec.**
- `../05-components.md` — shared component inventory.
- `../06-states.md` — the four scenarios and the visual-state checklist.
- `../07-data-schema.md` — the data shape + server contract sketch.
- `../08-tweaks.md` — the four runtime-preference axes (note C's calm mode hides the middle telemetry block + footer engine strip).
- `../09-raspberry-pi.md` — kiosk deployment, fonts, touch, performance budget.

## The prototype is the source of truth

`src/Variation C.html` is fully interactive and frozen at handoff. "Match the prototype" means that file. Prototype wins for visuals/interaction; docs win for reasoning and real-product deltas (API, persistence, touch). Undecided items are tagged **[CONFIRM]** — raise them, don't guess.

## What "done" means for this package

A Raspberry-Pi-ready Mission Control where:

- The three columns (Candidates · Portfolio · Clearance) render pixel-accurate to the prototype at 1920×1080, with correct active/dimmed states.
- The **fly-to-manifest** approval animation and **auto-advance** behaviour work.
- All four scenarios (`normal` / `no-actionable` / `outage` / `submitted`) are reachable and correct, including the submitted-state column dimming.
- All six instrument panels open, render real data, and close cleanly.
- The clearance gate works end-to-end against a real paper broker.
- Colour / theme / density preferences persist across reboots (calm mode strips the telemetry middle + footer engines).
- It runs 8+ hours in kiosk mode inside the performance budget in `../09-raspberry-pi.md`.

Each is decomposed into tickets in `TICKETS.md` with a checkable DoD in `DEFINITION-OF-DONE.md`.
