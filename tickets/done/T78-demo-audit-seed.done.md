# T78: Demo audit seed

**Owner:** codex
**Phase:** 3 runtime hardening
**Status:** done

## Goal

Make the deterministic local demo seed populate the runtime audit trail visible on
`/audit`.

## Delivered

- Wired `persist_demo_runtime_seed` to build runtime audit artifacts.
- Persisted demo agent-run, risk-snapshot, and execution-state rows in the same
  seed transaction as the existing runtime rows.
- Kept persistence writers injectable for unit tests and future scripts.
- Added contract-validating unit coverage for demo audit payloads.

## Acceptance Notes

1. Fresh local demo seeding now gives `/audit` data without a manual cycle run.
2. The seed remains paper/demo-only and deterministic.
3. Prompt audits remain empty until a real prompt-producing runtime path exists.
