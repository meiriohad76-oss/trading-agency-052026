# T32: Server-rendered dashboard shell

**Owner:** codex
**Phase:** 2 (design/build bridge)
**Estimate:** small
**Dependencies:** T31

## Goal
Add the first operational dashboard screen using FastAPI and server-rendered templates.

## Context
The dashboard should read the same contract and source-health data as the API. It should
be quiet, scannable, and status-first, not a marketing page.

## Outputs
- Root dashboard route at `/`.
- Jinja template and packaged static CSS.
- Tests for dashboard rendering and static asset serving.

## Acceptance Criteria
1. `GET /` renders a dashboard page.
2. Page shows service status, contract count, source count, source table, and contract list.
3. `GET /static/styles.css` serves the stylesheet.
4. UI uses the same API helper data as `/contracts` and `/status/data-sources`.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- htmx live fragments.
- Authentication.
- Real source-health persistence.
- Trade or candidate workflows.
