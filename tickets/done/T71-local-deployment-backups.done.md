# T71: Local deployment and backups

**Owner:** codex
**Phase:** 3 provisional runtime scaffolding
**Status:** done

## Goal

Make the first local paper runtime reproducible enough to start, smoke-check,
back up, and later transfer to a Pi-style Docker Compose deployment.

## Delivered

- Added a Docker app image and Compose `app` profile alongside Postgres.
- Added local runtime start and smoke-check scripts.
- Added compressed Postgres backup and restore scripts.
- Added Make targets for dev startup, serving, smoke checks, backups, restores,
  and Compose validation.
- Documented the local runtime, Compose app flow, backup commands, and Pi notes.

## Acceptance Notes

1. The app remains paper/demo only and does not submit broker orders.
2. Backups are written under `backups/postgres/` and ignored by git.
3. The current local testing path still favors the venv runner for fast iteration.
