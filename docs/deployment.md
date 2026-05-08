# Deployment And Backups

This is the current reproducible path for local testing and a Pi-style deployment
checkpoint. The stack is still paper/demo only.

## Local Test Runtime

PowerShell one-shot:

```powershell
.\scripts\start_local_runtime.ps1
```

Manual equivalent:

```powershell
docker compose -f docker\docker-compose.yml up -d postgres
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python scripts\seed_demo_runtime.py
.\.venv\Scripts\python -m uvicorn agency.app:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/`.

Smoke-check a seeded runtime:

```powershell
.\.venv\Scripts\python scripts\check_local_runtime.py `
  --min-selection-reports 1 --min-risk-decisions 1
```

## Live PIT Paper Cycle

After a live refresh has written local PIT manifests and parquet files, run a
paper cycle from those research artifacts:

```powershell
.\.venv\Scripts\python scripts\run_live_runtime_cycle.py `
  --output-root research\results\t83-live-runtime-cycle
```

For the first stocks-only PIT replay, keep options/unusual-activity providers out
of the gate and evaluate freshness at the replay date:

```powershell
.\.venv\Scripts\python scripts\run_live_runtime_cycle.py `
  --as-of 2025-12-31 `
  --replay-freshness `
  --output-root research\results\t85-stocks-only-replay
```

Use `--no-persist` for a dry run that only writes the compact summary files.
When persisted, the cycle flows through the same evidence, final-selection,
risk, execution-preview, audit, dashboard, and metrics path as the seeded
runtime.

Then verify the runtime can see the persisted rows:

```powershell
.\.venv\Scripts\python scripts\check_local_runtime.py `
  --min-selection-reports 1 --min-risk-decisions 1

curl.exe http://127.0.0.1:8000/status/live-readiness
```

This remains paper-only. Stale or missing local PIT datasets intentionally
degrade source health and can leave candidates blocked or context-only until a
fresh refresh and required provider feeds are available.

## Compose App Image

The app image is defined in `docker/app.Dockerfile`. Build and run it with the
`app` profile after Postgres is healthy:

```powershell
docker compose -f docker\docker-compose.yml --profile app build app
docker compose -f docker\docker-compose.yml up -d postgres
docker compose -f docker\docker-compose.yml --profile app run --rm app `
  python -m alembic upgrade head
docker compose -f docker\docker-compose.yml --profile app up -d app
```

The compose app uses `postgres` as `DB_HOST`; local venv commands use
`localhost` from `.env.example`. External API credentials are not interpolated
into Compose yet so `docker compose config` stays safe to inspect.

## Database Backups

Create a compressed Postgres backup:

```powershell
.\.venv\Scripts\python scripts\backup_postgres.py
```

Restore a backup:

```powershell
.\.venv\Scripts\python scripts\restore_postgres.py `
  backups\postgres\agency-YYYYMMDD-HHMMSS.sql.gz
```

Backups are written under `backups/postgres/` and are intentionally ignored by git.

## Pi Notes

- Use the same Docker Compose file and pin the repo to a tagged commit.
- Keep Postgres on a named Docker volume.
- Run the backup command nightly before any upgrade or data refresh.
- Cloud backup provider is still open; copy the generated `.sql.gz` file to the
  selected bucket once Q7 is decided.
