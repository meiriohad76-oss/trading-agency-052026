# T77: Live refresh readiness

**Owner:** codex
**Phase:** 1 research unblock
**Status:** done

## Goal

Make the live T72 data refresh inputs explicit and repeatable before running
external data pulls.

## Delivered

- Added a JSON live-refresh config loader for the data refresh batch.
- Added `--config` support to `research/scripts/run_data_refresh_batch.py`.
- Added example live-refresh and CUSIP-map config files.
- Added `docs/live-research-readiness.md` with the dry-run and live-run handoff.
- Added unit coverage for config parsing and validation.

## Acceptance Notes

1. CLI flags override config-file values.
2. Local config files matching `research/config/*.local.json` are ignored by git.
3. T72 remains blocked until real `SEC_USER_AGENT`, RSS feeds, 13F CIKs, and CUSIP
   map values are supplied.
