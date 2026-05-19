# Data Batching Strategy

The agency separates data extraction into three layers:

1. Baseline load: build durable local history once.
2. Incremental updates: fetch only missing or stale partitions.
3. Market-aware batches: decide what should run now based on the exchange session.

## Market Clock

The planner classifies each moment in New York time:

| Phase | Action |
| --- | --- |
| `pre_market` | Poll Massive trade prints, subscription emails, and news quickly. |
| `regular_market` | Keep market-flow batches small and frequent; defer heavy slow data. |
| `after_hours` | Reconcile late prints, refresh daily bars, recompute technical lanes. |
| `overnight_after_hours` | Run catch-up market-flow, daily bars, and slow maintenance. |
| `closed_weekend` / `closed_holiday` | Run maintenance, SEC, 13F, backtests, and LLM review; avoid trade polling. |

Regular market hours are modeled as 09:30-16:00 New York time, with supported
early-close days ending at 13:00.

## Dataset Policy

| Dataset | Active-session policy | Quiet-window policy |
| --- | --- | --- |
| `stock_trades` | 5 minute batches, 15-20 tickers per batch. | Catch-up only; no constant polling. |
| `news_rss` | 10 minute polling during active market windows. | 30 minute polling. |
| `subscription_emails` | 10 minute mailbox/article polling. | 30 minute polling and deeper article analysis. |
| `prices_daily` | Defer until bars are final. | Run after close or during closed-market windows. |
| `sec_form4` | Hourly incremental checks. | Slower event checks. |
| `sec_company_facts` | Defer unless explicitly forced. | Weekly/stale maintenance. |
| `sec_13f` | Defer unless explicitly forced. | Quarterly filing-window maintenance. |

## Operator Command

Preview the current plan:

```powershell
.\.venv\Scripts\python research\scripts\plan_market_aware_refresh.py
```

Preview a specific session:

```powershell
.\.venv\Scripts\python research\scripts\plan_market_aware_refresh.py `
  --now 2026-05-11T10:00:00-04:00
```

The output is written to:

`research/results/latest-market-aware-refresh-plan/`

The planner also handles the subtle intraday case where a `stock_trades`
partition for the current trading day already exists but is stale. During
pre-market, regular market, and after-hours windows, a current-day partition
older than five minutes is treated as an incremental refresh target instead of
as complete historical coverage.

## Safety Rules

`run_data_refresh_batch.py` is market-aware by default. During active decision
windows it runs only the datasets that can affect the next action now, and it
defers heavy baseline repair to quiet windows. Use `--no-market-aware` only for
intentional maintenance.

Direct `stock_trades` pulls are guarded. A broad historical trade-print request
is rejected before any Massive/Polygon API call; use
`research/scripts/backfill_massive_stock_trades.py` for resumable historical
repair instead.

Lane ownership is mandatory:

- Use `massive_live_trade_slices` for current-day latest prints in explicit
  scheduler-owned active-tier ticker batches.
- Use `massive_premarket_trade_slices` for 04:00-09:30 ET premarket prints.
- Use `massive_backtest_trade_tape` through
  `research/scripts/backfill_massive_stock_trades.py` for off-hours historical
  repair.

Signal agents should read the raw lane outputs instead of starting their own
Massive trade pulls.
