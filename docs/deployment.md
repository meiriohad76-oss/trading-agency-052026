# Deployment And Backups

This is the current reproducible path for local testing and a Pi-style deployment
checkpoint. The stack is paper-only by default; demo data is opt-in.

## Local Test Runtime

PowerShell one-shot:

```powershell
.\scripts\start_dev.ps1
```

This is the guarded local entrypoint. It stops older local
`uvicorn agency.app:app` processes for the same port before starting a fresh
server, so `http://127.0.0.1:8000/` cannot accidentally serve an older checkout.

For a Docker/Postgres runtime, use:

```powershell
.\scripts\start_local_runtime.ps1
```

For a demo-only dashboard seed, opt in explicitly:

```powershell
.\scripts\start_local_runtime.ps1 -SeedDemo
```

Then open `http://127.0.0.1:8000/`.

For the V3 cockpit or Raspberry Pi kiosk rehearsal, start the local cockpit
entrypoint explicitly:

```powershell
.\scripts\start_dev.ps1 -Kiosk
```

The dev and kiosk scripts bind uvicorn to `127.0.0.1` unless you intentionally
change the command. See `docs/raspberry-pi-cockpit.md` for Chromium flags,
systemd restart, touch checks, local-only logs, and the Pi performance
measurement checklist.

Smoke-check a seeded runtime:

```powershell
.\.venv\Scripts\python scripts\check_local_runtime.py `
  --min-selection-reports 1 --min-risk-decisions 1

.\.venv\Scripts\python scripts\check_operational_readiness.py `
  --min-queue 1
```

## Credential Checklist

Set local-only secrets in `.env`; do not commit real values.

- `POLYGON_API_KEY` or `MASSIVE_API_KEY` is required when the live refresh
  config uses `market_data_provider="massive"` or enables `stock_trades`.
- `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` are still required for Alpaca broker
  reads, paper-order validation, or if the live refresh config is changed back
  to `market_data_provider="alpaca"`.
- `SEC_USER_AGENT` is required for SEC EDGAR refreshes unless
  `research/config/live-refresh.local.json` sets `sec_user_agent`.
- `OPENAI_API_KEY` is optional for paper mode. To enable supervised LLM review,
  set `AGENCY_ENABLE_LLM_REVIEW=true`; optionally set
  `OPENAI_LLM_REVIEW_MODEL`, `OPENAI_BASE_URL`, and
  `AGENCY_LLM_REVIEW_MAX_CANDIDATES`.
- Planned provider keys are optional until their connectors are enabled:
  `OPENFIGI_API_KEY`, `BENZINGA_API_KEY`, `UNUSUAL_WHALES_API_KEY`,
  `FRED_API_KEY`, `THETADATA_USERNAME`, and `THETADATA_PASSWORD`.

Non-secret refresh settings live in `research/config/live-refresh.local.json`,
including `rss_feeds`, `filer_ciks`, `cusip_map`, ticker universe, and the
selected market-data provider. Options/dark-pool provider keys are not required
until a provider is selected; current unusual-activity ingestion uses a local
provider/export CSV.

The runtime can now use the active PIT S&P 100 + QQQ universe independently of
the smaller refresh ticker list:

```json
"runtime_universe": "active",
"runtime_max_tickers": 250
```

`runtime_universe="active"` reads `universe_membership.parquet` at the cycle
as-of date. Keep `runtime_max_tickers` above the active universe size when you
want the full operational queue; lower it only for bounded smoke tests.

## Live PIT Paper Cycle

After a live refresh has written local PIT manifests and parquet files, run a
paper cycle from those research artifacts:

```powershell
.\.venv\Scripts\python scripts\run_live_runtime_cycle.py `
  --output-root research\results\t83-live-runtime-cycle
```

To include supervised LLM review for bounded WATCH candidates:

```powershell
.\.venv\Scripts\python scripts\run_live_runtime_cycle.py `
  --enable-llm-review `
  --llm-review-max-candidates 10 `
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

For an active-universe local smoke that does not call providers or write to the
database:

```powershell
.\.venv\Scripts\python scripts\run_live_runtime_cycle.py `
  --config research\config\live-refresh.local.json `
  --as-of 2026-05-08 `
  --replay-freshness `
  --no-persist `
  --no-enable-llm-review `
  --output-root research\results\active-universe-runtime-smoke
```

Review `/status/live-config` before treating the run as operational. The Live
Config panel warns when local PIT datasets cover only part of the active
universe, for example when prices or stock-trade prints have been refreshed for
only a smoke subset.

To opt into market-flow, options, or activity lanes after importing coverage, add
`stock_trades`, `options_chains`, and/or `unusual_activity_alerts` to `datasets`,
then set `runtime_signals` in `research/config/live-refresh.local.json` or pass
repeated `--signal` flags to `scripts/run_live_runtime_cycle.py`. The
`technical_analysis` lane runs from daily OHLCV by default and enriches its
summary with Massive trade-pressure context when `stock_trades` is present.

For Massive stock-trade pressure, set one local key and keep the default base URL:

```powershell
POLYGON_API_KEY=<local key>
# or MASSIVE_API_KEY=<local key>
MASSIVE_BASE_URL=https://api.polygon.io
```

To use the same Massive subscription for daily OHLCV bars, set
`"market_data_provider": "massive"` in `research/config/live-refresh.local.json`.
The technical-analysis worker can run from any `prices_daily` provider, but
Massive bars plus `stock_trades` give it one provider family for chart structure
and trade-pressure context.

For full trade-print coverage, leave the local page cap disabled. The provider
page size remains explicit at the maximum supported value:

```json
"stock_trades_limit": 50000,
"stock_trades_max_pages_per_day": null
```

For a bounded smoke run, temporarily set `stock_trades_max_pages_per_day` to a
positive integer or pass `--max-pages-per-day 1`. Passing `0` on the command
line means unbounded.

Massive REST calls can pass through an optional local request ledger before any
HTTP request is sent. It is disabled by default for full coverage. Set these in
`.env` only when you want this machine to impose an extra local cap:

```powershell
MASSIVE_API_LIMITS_ENABLED=true
MASSIVE_API_DAILY_REQUEST_BUDGET=100
MASSIVE_API_MAX_REQUESTS_PER_MINUTE=30
MASSIVE_API_USAGE_DIR=research/results/massive-api-usage
```

Set `MASSIVE_API_MAX_REQUESTS_PER_MINUTE=0` when you want the optional local
ledger to count calls without adding per-minute pacing.

Check the local ledger before a refresh:

```powershell
.\.venv\Scripts\python research\scripts\check_massive_api_usage.py
```

The ledger cannot see requests made earlier from another machine, browser, or
tool, so lower `MASSIVE_API_DAILY_REQUEST_BUDGET` when you know calls were
already used today.

Then add these opt-in runtime lanes when `stock_trades` has refreshed:

```json
"runtime_signals": [
  "fundamentals",
  "insider",
  "institutional",
  "abnormal_volume",
  "technical_analysis",
  "buy_sell_pressure",
  "block_trade_pressure",
  "unusual_trade_activity",
  "pre_market_unusual_activity",
  "market_flow_trend",
  "sector_momentum",
  "news"
]
```

Then verify the runtime can see the persisted rows:

```powershell
.\.venv\Scripts\python scripts\check_local_runtime.py `
  --min-selection-reports 1 --min-risk-decisions 1

curl.exe http://127.0.0.1:8000/status/live-config
curl.exe http://127.0.0.1:8000/status/provider-readiness
curl.exe http://127.0.0.1:8000/status/live-readiness
curl.exe http://127.0.0.1:8000/status/operational-readiness
```

After `stock_trades` has enough history, run the market-flow worker before
raising market-flow importance in paper review. This covers buy/sell pressure,
block/off-exchange pressure, unusual trade activity, pre-market unusual
activity, and market-flow trend:

```powershell
.\.venv\Scripts\python research\scripts\run_market_flow_worker.py `
  --start 2024-01-01 `
  --end 2026-05-08 `
  --ticker AAPL `
  --ticker MSFT `
  --horizon 5 `
  --horizon 20 `
  --output-root research\results\t110-market-flow-worker
```

This remains paper-only. Stale or missing local PIT datasets intentionally
degrade source health and can leave candidates blocked or context-only until a
fresh refresh and required provider feeds are available.

Run the technical-analysis worker from the same PIT data before changing the
technical lane's paper-review importance:

```powershell
.\.venv\Scripts\python research\scripts\run_technical_analysis_worker.py `
  --start 2025-01-01 `
  --end 2026-05-08 `
  --ticker AAPL `
  --ticker MSFT `
  --ticker NVDA `
  --horizon 5 `
  --horizon 20 `
  --output-root research\results\latest-technical-analysis-worker
```

Review `technical-analysis-calibration.md`. It is normal for most features to
stay `context_only_until_more_coverage` until the Massive historical sample is
wider than a smoke test.

### Current-Date Price Refresh

The project configuration now treats Massive/Polygon as the preferred research
market-data source for daily OHLCV and stock trade prints. Configure the Massive
key in `.env` and keep the default Massive base URL:

```powershell
POLYGON_API_KEY=<local key>
# or MASSIVE_API_KEY=<local key>
MASSIVE_BASE_URL=https://api.polygon.io
```

```json
"market_data_provider": "massive",
"massive_base_url": "https://api.polygon.io"
```

Alpaca remains the broker and paper-portfolio provider. Configure Alpaca keys
when using broker reads, paper-order validation, or Alpaca as a fallback market
data source:

```powershell
ALPACA_API_KEY=<local key>
ALPACA_SECRET_KEY=<local secret>
ALPACA_DATA_FEED=iex
ALPACA_DATA_ADJUSTMENT=all
ALPACA_DATA_BASE_URL=https://data.alpaca.markets
ALPACA_TRADING_BASE_URL=https://paper-api.alpaca.markets
AGENCY_ALPACA_BROKER_ENABLED=true
AGENCY_BROKER_SUBMIT_ENABLED=false
AGENCY_REQUIRE_HUMAN_APPROVAL_FOR_ORDERS=true
```

The refresh batch will block `prices_daily` or `stock_trades` with a credential
message if Massive is selected without `POLYGON_API_KEY` or `MASSIVE_API_KEY`.

### Alpaca Paper Broker

Alpaca broker reads and paper order submission are separate from the market-data
refresh. Set `AGENCY_ALPACA_BROKER_ENABLED=true` when you want the dashboard
to read the Alpaca paper account, positions, and open orders. Keep
`AGENCY_BROKER_SUBMIT_ENABLED=false` until you want approved READY previews to
show a paper-order submit button. The app blocks live Alpaca trading URLs unless
`ALPACA_ALLOW_LIVE_TRADING=true`.

To verify the real paper broker and record a repeatable paper-review trail, run:

```powershell
.\.venv\Scripts\python scripts\run_paper_broker_validation.py --cycles 3
```

The command forces broker reads on, keeps broker submission off, runs three
persisted paper cycles, records APPROVE/DEFER/REJECT review events, and writes
`research/results/alpaca-paper-validation/paper-broker-validation.md`.

To include a guarded Alpaca paper order test, add `--trade-test`:

```powershell
.\.venv\Scripts\python scripts\run_paper_broker_validation.py `
  --cycles 3 `
  --trade-test `
  --test-trade-ticker AAPL `
  --test-trade-notional 5
```

During market hours this submits a tiny paper BUY and then submits a cleanup SELL
when the BUY fills. Outside market hours it submits the paper BUY, verifies the
order path, cancels the queued order, and confirms no test ticker order remains
open. Live Alpaca trading remains blocked.

The broker validation also persists order lifecycle states under
`/audit/execution-states` and broker portfolio snapshots under
`/audit/portfolio-snapshots`. The Portfolio Monitor page includes a manual
`Record snapshot` action for capturing another paper-account state without
submitting any order.

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
