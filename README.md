# Trading Agency v2

[![CI](https://github.com/meiriohad76-oss/trading-agency-052026/actions/workflows/ci.yml/badge.svg)](https://github.com/meiriohad76-oss/trading-agency-052026/actions/workflows/ci.yml)

Trading Agency v2 is a supervised, Python-first equity research and paper-trading assistant. The project starts with a point-in-time research pipeline, versioned schemas, and strict testing discipline before any production trading workflow is built.

## Project Docs

- [v2 plan](docs/v2-plan.md)
- [research brief](docs/research-brief.md)
- [phase 1 findings](docs/findings.md)
- [working model](docs/working-model.md)

## First-Time Setup

This repo uses Python 3.14 and standard `pip` tooling.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\pre-commit install
.\.venv\Scripts\ruff check .
.\.venv\Scripts\mypy src research
.\.venv\Scripts\pytest
```

On systems with `make`, the equivalent one-command setup is:

```sh
make setup
```

## Local Database

Start the local Postgres 16 service and run the empty baseline migration:

```powershell
Copy-Item .env.example .env
docker compose -f docker/docker-compose.yml up -d postgres
.\.venv\Scripts\python -m alembic upgrade head
```

The default development connection settings are in [.env.example](.env.example). To remove the database container and volume:

```powershell
docker compose -f docker/docker-compose.yml down -v
```

To populate the local dashboard with deterministic paper/demo data:

```powershell
.\.venv\Scripts\python scripts\seed_demo_runtime.py
```

## Local API

Run the FastAPI shell:

```powershell
.\.venv\Scripts\python -m uvicorn agency.app:app --reload
```

The initial API exposes `/health`, `/contracts`, `/contracts/{name}`, and `/status/data-sources`.
The root path `/` renders the first server-side dashboard shell.
