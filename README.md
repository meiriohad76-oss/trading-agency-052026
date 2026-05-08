# Trading Agency v2

[![CI](https://github.com/meiriohad76-oss/trading-agency-052026/actions/workflows/ci.yml/badge.svg)](https://github.com/meiriohad76-oss/trading-agency-052026/actions/workflows/ci.yml)

Trading Agency v2 is a supervised, Python-first equity research and paper-trading assistant. The project starts with a point-in-time research pipeline, versioned schemas, and strict testing discipline before any production trading workflow is built.

## Project Docs

- [v2 plan](docs/v2-plan.md)
- [research brief](docs/research-brief.md)
- [phase status](docs/phase-status.md)
- [phase 1 findings](docs/findings.md)
- [working model](docs/working-model.md)
- [deployment and backups](docs/deployment.md)

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

To run one local paper cycle from schema-valid JSON inputs:

```powershell
.\.venv\Scripts\python scripts\run_agency_cycle.py --input .\path\to\runtime-cycle.json
```

The cycle input must include `cycle_id`, `as_of`, `generated_at`, and optional `tickers`,
`source_health`, `signals`, and `current_gross_exposure_pct` fields. `source_health`
entries must match `data-source-health`; `signals` entries must match `signal-result`.
The runner writes runtime audit rows and emits one structured JSON log line with
persisted artifact counts.

To preview the local PIT data refresh plan without calling external services:

```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --start 2021-01-01 --end 2025-12-31 --dry-run
```

For live SEC pulls, set `SEC_USER_AGENT` in `.env`. RSS and 13F refreshes also need
explicit `--rss-feed`, `--filer-cik`, and `--cusip-map` inputs.

To run the research result batch after PIT data manifests are refreshed:

```powershell
.\.venv\Scripts\python research\scripts\run_research_batch.py `
  --start 2021-01-01 --end 2025-12-31 `
  --signal fundamentals --signal insider --signal institutional `
  --signal sector_momentum --signal abnormal_volume --signal news --signal options_flow
```

## Local API

Fast local test runtime:

```powershell
.\scripts\start_local_runtime.ps1
```

Run the FastAPI shell:

```powershell
.\.venv\Scripts\python -m uvicorn agency.app:app --reload
```

The local API exposes `/health`, `/contracts`, `/contracts/{name}`, `/status/data-sources`,
`/reports/selection`, `/risk/decisions`, and `/metrics`. The root path `/` renders the
server-side dashboard shell.

To smoke-check a seeded local runtime:

```powershell
.\.venv\Scripts\python scripts\check_local_runtime.py `
  --min-selection-reports 1 --min-risk-decisions 1
```
