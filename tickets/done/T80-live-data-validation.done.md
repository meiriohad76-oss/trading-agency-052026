# T80: Live data validation hardening

**Owner:** codex
**Phase:** 1 research unblock
**Status:** done

## Goal

Run repeated live data-source tests and remove brittle cases found in the T72
refresh path.

## Delivered

- Suppressed false price issues for empty edge ranges when valid ticker history
  already exists.
- Broadened SEC 13F information-table detection to all non-primary XML
  attachments.
- Added a reusable live-refresh output validator script.
- Added unit/integration coverage for the price edge case, 13F document variants,
  and output validation.

## Acceptance Notes

1. Repeated per-source live tests passed for prices, company facts, Form 4, 13F,
   and RSS news.
2. The full combined live refresh passed.
3. Live manifests reported positive row counts and zero issues.
