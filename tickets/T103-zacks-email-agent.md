# T103: Zacks Email Agent

**Owner:** codex
**Phase:** 4 validation expansion
**Estimate:** medium
**Dependencies:** T100

## Goal

Add a Zacks email agent that converts user-received Zacks emails into
PIT-clean evidence for news, Zacks Rank changes, analyst recommendations, and
rating changes.

## Context

The user can receive Zacks news, Zacks Rank changes, and analyst recommendation
emails through a paid subscription. These can act as slow-to-medium speed
research catalysts and corroborating evidence alongside price/volume and
unusual-activity signals.

## Inputs

- T100 email evidence foundation.
- Zacks emails from the user's approved mailbox/folder.
- Configured ticker universe.
- Existing news/catalyst lane.

## Outputs

- Zacks-specific parser/classifier for:
  - Zacks Rank changes,
  - rating changes,
  - analyst recommendations,
  - earnings/news commentary.
- Normalized news/catalyst evidence rows.
- Optional rank-change rows if a dedicated ranking-change lane exists by the
  time this ticket is implemented.
- Provider-specific source-health/readiness details.

## Acceptance Criteria

1. Zacks Rank change emails are classified separately from generic news.
2. Analyst recommendation/rating emails preserve direction and ticker.
3. News/commentary emails feed the catalyst lane.
4. Duplicate Zacks emails are not double-counted.
5. Emails without ticker matches are retained for manual review or ignored
   according to config.
6. The agent keeps private email content out of logs and committed fixtures.

## Tests Required

- Unit tests for rank-change, rating-change, recommendation, and news fixtures.
- Unit tests for ticker extraction and source IDs.
- Integration test through the T100 local fixture ingest path.

## Out of Scope

- Scraping Zacks website pages.
- Historical backfill beyond available mailbox history.
- Broker execution.

## Notes

Zacks evidence should generally corroborate other market signals rather than
drive action alone unless later validation proves stronger edge.
