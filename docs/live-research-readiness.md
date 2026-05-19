# Live Research Readiness

T72/T73 need live data inputs before empirical refresh and calibration can run.
Use this checklist to make those inputs explicit.

## Required Inputs

- `SEC_USER_AGENT` in `.env`
  - Format should identify the project and a contact email.
- RSS feeds
  - Pass as `SOURCE,URL` or `SOURCE,TICKER,URL`.
- 13F filer CIKs
  - Pass one or more institutional filer CIKs.
- CUSIP map
  - JSON object mapping CUSIP strings to tickers.
- Massive/Polygon stock trades, optional
  - Add `POLYGON_API_KEY` or `MASSIVE_API_KEY` in `.env`.
  - Include `stock_trades` only when you want delayed trade-print pressure
    lanes. The signals infer direction from prints; they do not identify true
    buyer/seller aggressor side.
  - Use `"stock_trades_max_pages_per_day": null` for full coverage. For a
    bounded smoke run, set a positive page count or pass `--max-pages-per-day 1`.
  - The local Massive request ledger is disabled by default. Re-enable
    `MASSIVE_API_LIMITS_ENABLED=true` only when you deliberately want an extra
    local cap below the provider subscription.
- Unusual activity alerts CSV, optional
  - Use for paid/confirmed provider alerts such as block trades, dark-pool prints,
    unusual options activity, options sweeps, and unusual stock activity.
  - Required columns: `ticker`, `alert_type`, `direction`, `observed_at`.
  - Optional useful columns: `event_time`, `summary`, `price`, `volume`,
    `notional`, `premium`, `source`, `source_id`, `source_url`, `confidence`.
  - Supported useful `alert_type` values include `block_trade`, `dark_pool`,
    `large_print`, `unusual_stock_activity`, `unusual_options_activity`,
    `options_sweep`, `call_sweep`, and `put_sweep`.
- Subscription email agents, optional
  - Use for user-authorized Seeking Alpha, TradeVision, and Zacks mailbox
    exports.
  - Copy `research/config/subscription-email.example.json` to
    `research/config/subscription-email.local.json`.
  - Export approved `.eml` messages into
    `research/data/raw/subscription_emails/`.
  - Set `follow_article_links` to `true` when the agent should open allowlisted
    article links and analyze page content in memory.
  - Add `subscription_emails` to `datasets` only when that local export exists.
  - See `docs/subscription-email-agents.md` for the exact command flow.

## Dry Run

Copy the template and replace example values:

```powershell
Copy-Item research\config\live-refresh.example.json research\config\live-refresh.local.json
```

Then run:

```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --config research\config\live-refresh.local.json `
  --dry-run `
  --output-root research\results\t72-readiness
```

The run is ready when `data-refresh-status.json` reports:

- `blocked: false`
- `failed: false`
- each job status is `planned` in dry-run mode

When `runtime_universe` is `active`, `/status/live-config` also reports the
active PIT universe size from `universe_membership.parquet` and warns if local
core datasets cover only a subset of that universe. Treat that warning as a
staging reminder, not as a provider-key blocker.

## Live Refresh

After the dry run is unblocked:

```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --config research\config\live-refresh.local.json `
  --no-dry-run `
  --output-root research\results\t72-live
```

To watch that custom output root on the Command page, set:

```powershell
$env:DATA_REFRESH_STATUS_PATH="research/results/t72-live/data-refresh-status.json"
```

Raw and parquet outputs stay local-only. Commit only compact status/result
artifacts that are small enough to review.

Validate the live outputs:

```powershell
.\.venv\Scripts\python research\scripts\check_live_refresh_outputs.py `
  --status-path research\results\t72-live\data-refresh-status.json
```

The command exits nonzero if the batch failed, any job did not pass, a manifest
has zero rows, or a manifest reports issues.

Check the Massive request ledger before enabling a live Massive refresh:

```powershell
.\.venv\Scripts\python research\scripts\check_massive_api_usage.py
```

When `stock_trades` has enough historical coverage, run the market-flow worker:

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

Review `market-flow-calibration.md` before changing paper-review expectations
for `buy_sell_pressure`, `block_trade_pressure`, `unusual_trade_activity`,
`pre_market_unusual_activity`, or `market_flow_trend`.

Run the technical-analysis worker after the daily bars refresh. It can use
Massive trade pressure when `stock_trades` exists, but it still produces chart
and setup features from `prices_daily` alone:

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

Review `technical-analysis-calibration.md` before raising the
`technical_analysis` lane's paper-review importance.

Import a local unusual-activity export directly when you have one:

First smoke-test the file in an isolated results folder:

```powershell
.\.venv\Scripts\python research\scripts\smoke_activity_alert_import.py `
  --input research\config\activity-alerts.example.csv `
  --output-root research\results\t82-activity-alert-import
```

Review:

```powershell
Get-Content research\results\t82-activity-alert-import\activity-alert-import-summary.md
```

If the verdict is `ready_for_research_batch`, import it into the live local
dataset:

```powershell
.\.venv\Scripts\python research\scripts\import_activity_alerts.py `
  --input research\config\activity-alerts.example.csv
```

For a refresh batch, set `activity_alerts_csv` in
`research\config\live-refresh.local.json` and include
`unusual_activity_alerts` in `datasets`.

To enable the optional options/activity lanes in a paper cycle, include the
datasets and runtime signals explicitly:

```json
"datasets": [
  "prices_daily",
  "sec_company_facts",
  "sec_form4",
  "sec_13f",
  "news_rss",
  "subscription_emails",
  "stock_trades",
  "options_chains",
  "unusual_activity_alerts"
],
"runtime_signals": [
  "fundamentals",
  "insider",
  "institutional",
  "abnormal_volume",
  "buy_sell_pressure",
  "block_trade_pressure",
  "unusual_trade_activity",
  "pre_market_unusual_activity",
  "market_flow_trend",
  "sector_momentum",
  "news",
  "options_anomaly",
  "options_flow",
  "activity_alerts"
]
```

`buy_sell_pressure`, `block_trade_pressure`, `unusual_trade_activity`,
`pre_market_unusual_activity`, and `market_flow_trend` are inferred from delayed
Massive/Polygon stock prints. `options_anomaly` and `options_flow` are inferred
from forward option-chain snapshots. `activity_alerts` is the confirmed lane for
provider-sourced dark-pool, block-trade, and unusual-options alerts.

`subscription_emails` feeds the existing `news_rss` and
`unusual_activity_alerts` datasets. It also writes a safe deduped
`subscription_emails` event view for source-health and calibration review.

Write the compact summary artifact:

```powershell
.\.venv\Scripts\python research\scripts\write_live_refresh_summary.py `
  --status-path research\results\t72-live\data-refresh-status.json `
  --output-root research\results\t72-live-summary
```

## Calibration

Once T72 writes usable PIT data, run the research result batch and use the output
to calibrate actionability thresholds for T73.

Write the compact T73 calibration artifact after the H1 batch:

```powershell
.\.venv\Scripts\python research\scripts\write_actionability_calibration.py `
  --h1-verdicts research\results\t73-actionability-calibration\h1-verdicts.csv `
  --batch-status research\results\t73-actionability-calibration\batch-status.json `
  --output-root research\results\t73-actionability-calibration
```
