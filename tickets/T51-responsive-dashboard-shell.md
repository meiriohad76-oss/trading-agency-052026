# T51: Responsive dashboard shell upgrade

**Owner:** codex
**Phase:** 2 (UX)
**Estimate:** small
**Dependencies:** T47

## Goal
Promote the dashboard into a reusable responsive app shell inspired by the reviewed UX
mockup.

## Context
The mockup captured the right operational shape, but it used a fixed sidebar/grid layout
that broke on mobile. The real dashboard needs a server-rendered shell that works across
desktop and narrow viewports.

## Outputs
- `src/agency/templates/base.html`
- Dashboard template converted to extend the shell.
- Responsive sidebar/topbar/hero CSS.
- Tests updated to cover the shell text.

## Acceptance Criteria
1. Dashboard still renders candidate, source, and contract content.
2. Shell has real navigation links instead of mock div-buttons.
3. Mobile layout collapses to a single column and horizontal nav.
4. Existing API and candidate-detail routes continue to pass.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Additional dashboard pages.
- Live engine execution controls.
- Policy editing.
