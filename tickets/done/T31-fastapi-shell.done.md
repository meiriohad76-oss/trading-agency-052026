# T31: FastAPI application shell

**Owner:** codex
**Phase:** 2 (design/build bridge)
**Estimate:** small
**Dependencies:** T30

## Goal
Create the first production FastAPI app shell with health and contract visibility endpoints.

## Context
The repo now has canonical JSON Schemas and runtime validation helpers. The app shell
should expose a small API surface before any engine orchestration or dashboard UI exists.

## Outputs
- `src/agency/app.py`
- `src/agency/api/health.py`
- Tests using FastAPI `TestClient`.
- Runtime dependencies for FastAPI and uvicorn.

## Acceptance Criteria
1. `agency.app:create_app` returns a FastAPI app.
2. `GET /health` returns service status.
3. `GET /contracts` lists known contract names, IDs, versions, and titles.
4. `GET /contracts/{name}` returns a contract schema or 404.
5. `GET /status/data-sources` returns a schema-validated bootstrap status payload.
6. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.

## Out of Scope
- Dashboard templates.
- Authentication.
- Engine orchestration.
- Database-backed status.
