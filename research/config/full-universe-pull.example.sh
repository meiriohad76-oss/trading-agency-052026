#!/usr/bin/env bash
# Full-universe historical stock-trade backfill for one calendar year.
#
# Prerequisites:
#   - MASSIVE_API_KEY set in .env (Key Active plan — no daily request limits)
#   - universe_membership.parquet present at research/data/parquet/
#
# This command disables all safety limits (--full-universe) and pulls every
# ticker in the trading universe for the given date range.  Only run this when
# you are certain the API plan has no daily call cap.
#
# Usage: bash research/config/full-universe-pull.example.sh
#        Adjust --start / --end to the desired backfill window.

python research/scripts/pull_massive_stock_trades.py \
  --start 2024-01-01 \
  --end   2024-12-31 \
  --full-universe \
  --allow-long-window
