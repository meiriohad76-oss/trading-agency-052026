# Current Controlled Version - 2026-05-21

Generated: 2026-05-21 08:01 Asia/Jerusalem

## Repository State

- Repository: `trading_agency`
- Branch: `main`
- Previous HEAD before this checkpoint: `0cd1b4e33b857e1c6cdbf849c383795c43d1e49c`
- Previous commit subject: `Harden live readiness smoke checks`
- Purpose of this checkpoint: turn the accumulated implementation state into a documented, reviewable, reproducible repo version.

## Controlled Scope

This checkpoint intentionally includes source, schema, template, static asset, and unit-test changes in these areas:

- Operator-facing data-health wording that avoids showing the word `stale`; the UI now explains whether data is unavailable, waiting for analysis, refresh-recommended, or verified current.
- Data-health proof and refresh-action metadata for command, candidate, signal, risk, and execution screens.
- Execution preview and paper-promotion handling for warned but user-approved research candidates, while preserving broker/risk safety checks.
- Scheduler work queue freshness policy, including closed-market handling and explicit test-mode freshness knobs.
- Massive lane manifest/status support and tests for lane-level orchestration.
- Contract/schema updates for candidate lifecycle and human review events.
- UI readability and evidence-presentation improvements across the reviewed templates.
- Unit tests that pin the above behavior and isolate dashboard/API tests from local runtime-data drift.

## Generated Artifact Policy

Generated runtime data is kept on disk for operator history, but it is not part of the controlled source checkpoint. The `.gitignore` now excludes:

- `research/results/**` except `research/results/.gitkeep`
- generated manifests under `research/data/manifests/**` except tracked baseline files
- local email-monitor locks and portfolio high-water marks
- `logs/`, local tool folders, mockup images, root exported reports, and archive zips

Tracked historical evidence files that were already in `research/results` remain tracked; this checkpoint does not delete or rewrite them.

## Verification

Fresh verification completed before this checkpoint was committed:

- `.\.venv\Scripts\python -m pytest tests\unit -q` -> `1281 passed, 8 warnings in 118.87s`
- `.\.venv\Scripts\python -m compileall src\agency` -> exit 0
- `git diff --check` -> exit 0; Git reported CRLF normalization warnings for several touched view files only.

The 8 warnings are the known unit-test warnings for insufficient one-row cross sections and one Massive pagination-boundary fixture. They are not test failures.

## Known Boundaries

- This is a source-control and documentation checkpoint, not a claim that live market data is currently fresh.
- Live lane freshness has short SLAs and must be re-probed before any operational-readiness claim.
- Generated local runtime artifacts are intentionally ignored rather than deleted.
