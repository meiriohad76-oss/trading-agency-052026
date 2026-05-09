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

.\.venv\Scripts\python scripts\check_operational_readiness.py `
  --min-queue 1
```

## Credential Checklist

Set local-only secrets in `.env`; do not commit real values.

- `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` are required when the live refresh
  config uses `market_data_provider="alpaca"`.
- `SEC_USER_AGENT` is required for SEC EDGAR refreshes unless
  `research/config/live-refresh.local.json` sets `sec_user_agent`.
- `OPENAI_API_KEY` is optional in the current paper workflow and reserved for
  future live LLM review calls.
- Planned provider keys are optional until their connectors are enabled:
  `OPENFIGI_API_KEY`, `BENZINGA_API_KEY`, `UNUSUAL_WHALES_API_KEY`,
  `FRED_API_KEY`, `POLYGON_API_KEY`, `MASSIVE_API_KEY`,
  `THETADATA_USERNAME`, and `THETADATA_PASSWORD`.

Non-secret refresh settings live in `research/config/live-refresh.local.json`,
including `rss_feeds`, `filer_ciks`, `cusip_map`, ticker universe, and the
selected market-data provider. Options/dark-pool provider keys are not required
until a provider is selected; current unusual-activity ingestion uses a local
provider/export CSV.

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

To opt into the options/activity lanes after importing coverage, add
`options_chains` and/or `unusual_activity_alerts` to `datasets`, then set
`runtime_signals` in `research/config/live-refresh.local.json` or pass repeated
`--signal` flags to `scripts/run_live_runtime_cycle.py`.

Then verify the runtime can see the persisted rows:

```powershell
.\.venv\Scripts\python scripts\check_local_runtime.py `
  --min-selection-reports 1 --min-risk-decisions 1

curl.exe http://127.0.0.1:8000/status/live-config
curl.exe http://127.0.0.1:8000/status/provider-readiness
curl.exe http://127.0.0.1:8000/status/live-readiness
curl.exe http://127.0.0.1:8000/status/operational-readiness
```

This remains paper-only. Stale or missing local PIT datasets intentionally
degrade source health and can leave candidates blocked or context-only until a
fresh refresh and required provider feeds are available.

### Current-Date Price Refresh

The daily price puller defaults to yfinance. For current-date validation when
yfinance is stale, configure Alpaca in `.env` and
`research\config\live-refresh.local.json`:

```powershell
ALPACA_API_KEY=<local key>
ALPACA_SECRET_KEY=<local secret>
ALPACA_DATA_FEED=iex
ALPACA_DATA_ADJUSTMENT=all
ALPACA_DATA_BASE_URL=https://data.alpaca.markets
```

```json
"market_data_provider": "alpaca",
"market_data_feed": "iex",
"market_data_adjustment": "all",
"market_data_base_url": "https://data.alpaca.markets"
```

The refresh batch will block `prices_daily` with a credential message if Alpaca
is selected without keys.

The Command page Live Config panel and `/status/live-config` show whether the
local refresh config, selected provider, credentials, ticker universe, SEC
User-Agent, RSS feeds, 13F filers, CUSIP map, and activity-alert CSV are ready.
They report missing secret names only, never secret values.

The Command page Provider Readiness panel and `/status/provider-readiness` show
the whole-agency provider-key checklist. Missing future-provider keys are marked
as planned and do not block the current stocks-only paper workflow.

The default refresh output is `research/results/latest-data-refresh/`. During a
long run, the Command page polls that status file through `/status/data-refresh`
and shows percent complete, current dataset, and ETA. If you use a custom output
root, set `DATA_REFRESH_STATUS_PATH` to that run's `data-refresh-status.json`.

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
