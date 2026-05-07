# T01: Scaffold the v2 repository

**Owner:** codex
**Phase:** 0 (setup)
**Estimate:** small (< 2h)
**Dependencies:** none

## Goal
Create a working Python 3.14 monorepo with the directory structure from `working-model.md` §2, baseline tooling configured (ruff, mypy, pytest), and a green CI pipeline that runs lint + type-check + tests on every push.

## Context
This is the foundation every other ticket builds on. Get the structure right once; don't reorganize later. Reference: `working-model.md` §2 for the directory layout, §7 for testing layers.

## Inputs
- `working-model.md` (this repo's `docs/` folder) for canonical structure.
- `v2-plan.md` §4.1 for stack decisions (Python 3.14, FastAPI, htmx, pytest, ruff, mypy).

## Outputs
- Empty (but structurally complete) directory tree per `working-model.md` §2.
- `pyproject.toml` configured for Python 3.14, ruff, mypy, pytest. Use `uv` or `pip` — pick one and document.
- `.gitignore` covering: `research/data/raw/`, `research/data/parquet/`, `.env`, `__pycache__/`, `.venv/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `*.parquet`, `*.duckdb`, IDE folders.
- `.env.example` with all expected env-var names commented (no real values).
- `README.md` at repo root: one-paragraph project description, link to `docs/v2-plan.md`, dev setup instructions (clone → install → run tests).
- `.github/workflows/ci.yml` running ruff, mypy, pytest on Python 3.14 on push and PR to `main`.
- A single passing placeholder test in `tests/unit/test_smoke.py` (just `assert True`) so CI has something to run.

## Acceptance Criteria
1. `git clone` + `make setup` (or documented equivalent) produces a working dev environment from scratch.
2. `ruff check .` passes on the empty repo.
3. `mypy src research` passes on the empty repo.
4. `pytest` passes (the smoke test).
5. CI badge in README is green after the first push to `main`.
6. Directory tree matches `working-model.md` §2 exactly.
7. No file in the repo exceeds 200 lines (this is scaffolding only).

## Tests Required
- `tests/unit/test_smoke.py` exists and passes.
- CI workflow file is syntactically valid (lint with `actionlint` if available).
- Manual: clone the repo from a different directory, follow README setup, confirm `pytest` passes.

## Out of Scope
- Any Postgres or Docker setup (T02).
- Any actual production code in `src/`.
- Any research code in `research/`.
- FastAPI app skeleton (separate ticket later).

## Notes for Implementer
- Use `pyproject.toml` (PEP 621) for project metadata and tool config — don't use legacy `setup.py`.
- For `mypy` config, set `strict = true` for `src/` and `research/src/`. Allow looser config for `research/notebooks/`.
- For `ruff`, enable `E, F, W, I, N, UP, B, A, C4, PIE, RET, SIM, ARG, PTH, ERA, PL` rule sets. Disable any rule that conflicts with FastAPI patterns.
- The `Makefile` target `setup` should: create venv, install deps, install pre-commit, run lint+test.
- Use Python 3.14; reject earlier versions in `pyproject.toml`.
- Keep this PR small — it's foundation, not features.
