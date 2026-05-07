# T02: Postgres + Docker Compose for development

**Owner:** codex
**Phase:** 0 (setup)
**Estimate:** small (< 2h)
**Dependencies:** T01

## Goal
Provide a single-command local development environment: a Postgres 16 instance running in Docker, reachable from the host, with an initial migration system in place (Alembic) and a `db.py` module that exposes a typed connection pool.

## Context
v2 uses Postgres in production (on Pi) and SQLite only for tests. Locally we want Postgres-in-Docker so dev matches prod. Reference: `v2-plan.md` §4.3.

## Inputs
- T01's repo scaffold.
- `v2-plan.md` §4.3 (storage decisions).

## Outputs
- `docker/docker-compose.yml` with services:
  - `postgres`: postgres:16-alpine, port 5432, named volume for data, healthcheck.
  - `pgadmin` (optional, behind a `--profile dev` flag) for inspection.
- `docker/postgres/init.sql`: creates the `agency` database and a `agency_app` role.
- `src/agency/db.py`: SQLAlchemy 2.0 async engine + sessionmaker. Reads connection settings from env vars (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`). Exposes `get_session()` async context manager.
- `migrations/` directory initialized with Alembic; one initial empty migration committed.
- Updated `.env.example` with the new DB-related vars.
- Updated `README.md` with the dev start sequence: `docker compose up -d postgres && alembic upgrade head`.

## Acceptance Criteria
1. `docker compose up -d postgres` brings up Postgres successfully.
2. `alembic upgrade head` runs cleanly against the new DB.
3. A pytest integration test in `tests/integration/test_db_connection.py` connects, runs `SELECT 1`, and tears down. Test passes.
4. `docker compose down -v` cleanly removes containers and volumes.
5. Connection settings come from env, never hardcoded.
6. README's "First-time setup" section walks a new user from clone to working DB in under 5 minutes.

## Tests Required
- `tests/integration/test_db_connection.py`: starts a session, runs a trivial query, asserts result. Skip if `DB_HOST` env var is missing.
- Manual: bring stack up, connect via psql, verify `agency_app` role exists.

## Out of Scope
- Any actual schema (tables/columns) beyond what Alembic creates by default. Schemas come per-engine in their own tickets.
- SQLite test fixture (separate ticket; comes later).
- Production deployment Dockerfile (separate ticket).

## Notes for Implementer
- Use SQLAlchemy 2.0 async style throughout — no legacy `engine.connect()` patterns.
- Pin Postgres to `16-alpine`. Don't use `:latest`.
- Keep credentials simple in `.env.example` (e.g. `agency` / `agency` for local dev) — production credentials are managed separately.
- The `agency_app` role should NOT be a superuser. Grant only what's needed (CONNECT, USAGE, CREATE on specific schemas).
