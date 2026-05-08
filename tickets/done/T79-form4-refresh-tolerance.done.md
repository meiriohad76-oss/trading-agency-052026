# T79: SEC Form 4 refresh tolerance

**Owner:** codex
**Phase:** 1 research unblock
**Status:** done

## Goal

Keep T72 live data refreshes running when newer SEC Form 4 submissions expose an
`xslF345X05/` viewer document path or malformed XML.

## Delivered

- Normalized SEC Form 4 primary documents to the underlying XML filename before
  fetching.
- Recorded malformed Form 4 XML as manifest issues instead of failing the pull.
- Added Windows certificate-store support for SEC `httpx` calls through
  `truststore`.
- Added integration coverage for malformed XML and SEC viewer-path fallback.

## Acceptance Notes

1. A one-ticker 2025 Form 4 live smoke wrote rows with zero issues.
2. The full configured Form 4 stream passed and wrote 4,163 rows.
