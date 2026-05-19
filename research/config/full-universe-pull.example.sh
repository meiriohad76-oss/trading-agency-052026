#!/usr/bin/env bash
# Massive trade data lane examples.
#
# This legacy filename is kept so old references still land on a safe runbook.
# Do not use the live slice puller for broad historical repair. Live trade
# data and historical repair are separate lanes with different freshness,
# batching, and request-budget policies.
#
# Prerequisites:
#   - MASSIVE_API_KEY set in .env
#   - universe_membership.parquet present at research/data/parquet/
#
# Historical repair lane:
#   - Lane: massive_backtest_trade_tape
#   - Timing: off-hours / maintenance windows
#   - Scope: reviewed scheduler plan, resumable one ticker-day batch at a time
#
python research/scripts/backfill_massive_stock_trades.py \
  --start 2024-01-01 \
  --end 2024-01-05 \
  --lane-id massive_backtest_trade_tape \
  --allow-active-universe \
  --batch-size 1 \
  --max-batches 5 \
  --recent-first

# Live latest-slice lane:
#   - Lane: massive_live_trade_slices
#   - Timing: pre-market, regular market, and after-hours catch-up
#   - Scope: explicit active-tier ticker batches owned by the scheduler
#
python research/scripts/pull_massive_stock_trades.py \
  --start 2026-05-19 \
  --end 2026-05-19 \
  --lane-id massive_live_trade_slices \
  --trade-session full_day \
  --max-pages-per-day 1 \
  --order desc \
  --ticker AAPL \
  --ticker MSFT

# Pre-market latest-slice lane:
#   - Lane: massive_premarket_trade_slices
#   - Timing: 04:00-09:30 ET only
#   - Scope: explicit active-tier ticker batches owned by the scheduler
#
python research/scripts/pull_massive_stock_trades.py \
  --start 2026-05-19 \
  --end 2026-05-19 \
  --lane-id massive_premarket_trade_slices \
  --trade-session pre_market \
  --max-pages-per-day 1 \
  --order desc \
  --ticker AAPL \
  --ticker MSFT
