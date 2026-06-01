# 2026-06-01 Cockpit Variation A Decision Lock

## Decision

Variation A, the Pre-Flight Cockpit, is the implementation target for the next
operator cockpit release.

Variation C remains a future product backlog option. It is not a runtime toggle
and must not be exposed as a user preference during this implementation phase.

## Why This Is Locked

The current priority is to make the agency walk one human operator through a
focused paper-trading workflow:

1. Review candidates.
2. Review portfolio/capacity.
3. Clear and submit paper orders.

Variation A is the package's recommended first implementation because it is
sequential, easier to use on a Raspberry Pi/kiosk display, and directly addresses
the current product failure mode: the user is not always shown the next concrete
action.

## Production Rules

- `/cockpit` is the primary operator surface.
- Paper trading only. `LIVE_TRADING` remains locked off and must not appear as an
  enabled cockpit control.
- The cockpit consumes real agency data from the existing backend contracts.
- The cockpit must not use prototype mock data, random order identifiers,
  `DesignCanvas`, `EDITMODE`, or floating tweak controls in normal operation.
- Submit friction remains: checkbox, exact phrase `submit paper orders`, and
  explicit submit button.
- Existing signal, fundamentals, lane-state, ranking, and paper-promotion logic
  stays authoritative. The UX may reorder and clarify it, but must not replace it
  with generic display text.

## Confirmed Defaults Until User Changes Them

| Item | Decision |
|---|---|
| Settings entry point | Normal cockpit control, likely an icon button in the cockpit chrome. |
| Calm mode | Manual preference first; no automatic mode switch until tested. |
| Staged decision restore | Local restore prompt on reload is recommended; submit gate never persists. |
| Outage persistence | Preserve staged decisions visually, but require revalidation before submit. |
| Empty portfolio | Show explicit "no positions" state and allow advance to clearance. |
| Pi/kiosk target | Optimize for Raspberry Pi/kiosk constraints; verify locally first, Pi later. |
| Legacy dashboards | Keep as diagnostics while cockpit absorbs operator-facing flows. |

## Done Criteria For UXC-000

- The primary implementation target is Variation A.
- Variation C is documented as future backlog, not a runtime toggle.
- Human-confirm items are listed with safe defaults.
- The decision is linked from the main implementation plan.
