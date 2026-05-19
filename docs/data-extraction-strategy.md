# Data Extraction Strategy

The agency uses a two-stage extraction model:

1. **Baseline extraction** builds the first local point-in-time dataset for the active universe.
2. **Incremental extraction** checks freshness, validates that an update is due, and fetches only missing or stale data.

This avoids repeatedly pulling slow-moving SEC and quarterly datasets while still keeping live/event-driven lanes fresh.

## Dataset Policy

| Dataset | Baseline | Incremental rule |
| --- | --- | --- |
| `prices_daily` | Pull requested historical daily bars for the universe. | Append only missing daily bars after the latest local date. |
| `stock_trades` | Pull Massive trade partitions for selected dates/tickers. | Fetch only missing trade-date partitions for the live window. |
| `sec_company_facts` | Pull SEC company facts per ticker. | Re-check stale tickers on a weekly freshness window or when forced by an earnings/filing event. |
| `sec_form4` | Pull historical Form 4 filings once. | Fetch filings after the latest local filing date; run in small batches. |
| `sec_13f` | Pull historical 13F holdings for configured filers. | Re-check around quarterly filing windows; do not poll constantly. |
| `news_rss` | Seed current RSS rows. | Poll every 15-30 minutes and dedupe new headlines. |
| `subscription_emails` | Import saved and mailbox-matched emails. | Poll mailbox every 5-10 minutes and process only new messages or unprocessed article links. |

The default mode is `auto`. Use `force` only for repair jobs, provider migrations, or deliberate full rebuilds.

## Signal Lane Cadence

| Cadence | Lanes | Meaning |
| --- | --- | --- |
| Continuous | `subscription_thesis`, `activity_alerts`, `buy_sell_pressure`, `block_trade_pressure`, `pre_market_unusual_activity`, `unusual_trade_activity`, `market_flow_trend` | Lightweight polling during active windows; never full historical reload after baseline. |
| Event-driven | `news`, `insider` | Check for new RSS/SEC filings and append only confirmed new rows. |
| Daily | `abnormal_volume`, `sector_momentum`, `technical_analysis` | Recompute after daily bars are complete. |
| Scheduled | `fundamentals`, `institutional` | Use filing/quarterly windows and freshness checks. |
| Backlog | `options_anomaly`, `options_flow` | Disabled until options provider and limits are wired. |

## Operator Commands

Plan the next extraction before running it:

```powershell
.\.venv\Scripts\python research\scripts\plan_incremental_refresh.py `
  --config research\config\live-refresh.local.json
```

Run the plan through the standard batch runner:

```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --config research\config\live-refresh.local.json
```

If a provider migration or corrupted local partition requires a rebuild, use:

```powershell
.\.venv\Scripts\python research\scripts\run_data_refresh_batch.py `
  --config research\config\live-refresh.local.json `
  --extraction-mode force
```

Force mode should be rare because it intentionally bypasses freshness and partition coverage checks.

## Massive Trade Lanes

Trade prints are lane-owned. Do not start a broad live-puller job to fill
historical gaps.

Live decision lanes use bounded latest slices:

```powershell
.\.venv\Scripts\python research\scripts\pull_massive_stock_trades.py `
  --start 2026-05-19 `
  --end 2026-05-19 `
  --lane-id massive_live_trade_slices `
  --trade-session full_day `
  --max-pages-per-day 1 `
  --ticker AAPL `
  --ticker MSFT
```

Premarket analysis uses the premarket lane:

```powershell
.\.venv\Scripts\python research\scripts\pull_massive_stock_trades.py `
  --start 2026-05-19 `
  --end 2026-05-19 `
  --lane-id massive_premarket_trade_slices `
  --trade-session pre_market `
  --max-pages-per-day 1 `
  --ticker AAPL `
  --ticker MSFT
```

Historical repair uses the backtest lane and the resumable backfill worker:

```powershell
.\.venv\Scripts\python research\scripts\backfill_massive_stock_trades.py `
  --start 2024-01-01 `
  --end 2024-01-05 `
  --lane-id massive_backtest_trade_tape `
  --allow-active-universe `
  --batch-size 1 `
  --max-batches 5 `
  --recent-first
```
