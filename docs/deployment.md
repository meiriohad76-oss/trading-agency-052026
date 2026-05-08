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
