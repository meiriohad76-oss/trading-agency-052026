# T101: Seeking Alpha Email Agent

**Owner:** codex
**Phase:** 4 validation expansion
**Estimate:** medium
**Dependencies:** T100

## Goal

Add a Seeking Alpha email agent that converts user-received Seeking Alpha
articles, news alerts, Quant Rating changes, and ranking changes into
PIT-clean catalyst evidence.

## Context

Seeking Alpha is already a paid subscription source for the user. The agency
should monitor the allowed mailbox/folder, open relevant Seeking Alpha emails,
extract article/alert metadata and available email content, and classify it for
research and selection.

## Inputs

- T100 email evidence foundation.
- Seeking Alpha emails from the user's approved mailbox/folder.
- Configured ticker universe.
- Optional Seeking Alpha RSS feeds already supported by the RSS lane.

## Outputs

- Seeking Alpha-specific parser/classifier for:
  - analyst articles,
  - market news,
  - Quant Rating or Quant Rank changes,
  - author/rating sentiment where present,
  - earnings/transcript notices where present.
- Normalized evidence rows that feed the news/catalyst lane.
- Optional rating-change rows if a dedicated ranking-change lane exists by the
  time this ticket is implemented.
- Provider-specific source-health/readiness details.
- Tests with local `.eml` fixtures for each supported email type.

## Acceptance Criteria

1. SA article emails produce ticker-tagged catalyst evidence.
2. SA news emails produce ticker-tagged news evidence.
3. SA Quant Rating/Rank changes are classified separately from generic news.
4. Duplicate emails and duplicate links are not double-counted.
5. Emails without a matched ticker are retained for manual review or ignored
   according to config.
6. The agent never prints or commits full private email bodies in test output,
   logs, fixtures, or reports.

## Tests Required

- Unit tests for representative SA article/news/rating-change fixtures.
- Unit tests for ticker extraction and source IDs.
- Integration test through the T100 local fixture ingest path.

## Out of Scope

- Scraping Seeking Alpha outside user-authorized email/article workflows.
- Historical backfill beyond available mailbox history.
- Paid-content redistribution.

## Notes

Use Seeking Alpha emails as user-owned research inbox evidence. RSS remains the
preferred source for public headlines; email adds paid-subscription context.
