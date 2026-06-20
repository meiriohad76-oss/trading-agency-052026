# Variation A — Pre-Flight Cockpit · Build Package

> Self-contained implementation package for **one** dashboard: the Pre-Flight Cockpit (instrument-cluster aesthetic, sequential phases). Everything Codex needs to take this from prototype to a Raspberry-Pi-ready product lives in this folder.

If you are building **Variation C** instead, use `../variation-c/` — do not build both in one binary (see `../08-tweaks.md → Things that are NOT tweaks`).

---

## Read in this order

| # | File | What it is |
|---|------|-----------|
| 1 | **`IMPLEMENTATION.md`** | The master build guide: target stack, repo layout, file-by-file port plan, API contract, Pi hardening. Start here. |
| 2 | **`TICKETS.md`** | Every unit of work as a numbered ticket (`VA-###`) grouped into epics, each with scope, acceptance criteria, dependencies, and an estimate. This is your backlog. |
| 3 | **`TESTING.md`** | Test strategy, the full QA matrix, named test cases (`VA-T-###`) for unit / interaction / scenario / visual / Pi, and how to run them. |
| 4 | **`DEFINITION-OF-DONE.md`** | The global DoD plus a per-epic DoD checklist. A ticket is not done until its box here is checked. |
| — | **`src/`** | A frozen, runnable copy of the prototype (the source of truth for visuals + interactions). Open `src/Variation A.html` in a browser to see exactly what you are building. |

## Shared context (one level up)

These docs are shared by both dashboards — read them once, they are the *why* behind every ticket. Tickets reference them by number.

- `../01-design-philosophy.md` — the five principles. The lens for every decision.
- `../02-user-workflow.md` — what the operator actually does, in order.
- `../03-variation-a.md` — the design spec for **this** dashboard (anatomy, phases, gauges, animations). **Your primary spec.**
- `../05-components.md` — shared component inventory.
- `../06-states.md` — the four scenarios and the visual-state checklist.
- `../07-data-schema.md` — the data shape the UI consumes + server contract sketch.
- `../08-tweaks.md` — the four runtime-preference axes.
- `../09-raspberry-pi.md` — kiosk deployment, fonts, touch, performance budget.

## The prototype is the source of truth

`src/Variation A.html` is fully interactive and frozen at handoff. When a ticket says "match the prototype," it means that file. When the docs and the prototype disagree, **the prototype wins for visuals/interaction; the docs win for reasoning and the real-product deltas** (API, persistence, touch). Anything genuinely undecided is tagged **[CONFIRM]** — raise it with the human, don't guess.

## What "done" means for this package

A Raspberry-Pi-ready Pre-Flight Cockpit where:

- The four phases (Candidates → Portfolio → Clearance → Cleared) render pixel-accurate to the prototype at 1920×1080.
- All four scenarios (`normal` / `no-actionable` / `outage` / `submitted`) are reachable and correct.
- All six instrument panels open, render real data, and close cleanly.
- The clearance flow works end-to-end against a real paper broker.
- Colour / theme / density preferences persist across reboots.
- It runs 8+ hours in kiosk mode inside the performance budget in `../09-raspberry-pi.md`.

Every one of those is decomposed into tickets in `TICKETS.md` with a checkable DoD in `DEFINITION-OF-DONE.md`.
