# T100: Subscription Email Evidence Foundation

**Owner:** codex
**Phase:** 4 validation expansion
**Estimate:** medium
**Dependencies:** T18, T19, T81, T98, T99

## Goal

Create the shared local ingestion foundation for paid-subscription emails so
service-specific agents can turn Seeking Alpha, TradeVision, and Zacks messages
into PIT-clean evidence.

## Context

The user has paid subscriptions that send relevant research, ranking changes,
news, alerts, dark-pool information, and recommendations by email. The agency
should monitor the user's mailbox and reduce manual review work by ingesting
approved subscription emails as first-class evidence with provenance.

This ticket is the shared foundation only. Service-specific parsing belongs in
T101-T103.

## Inputs

- Dedicated mailbox/folder or label for agency-readable subscription emails.
- Allowlisted sender domains.
- Existing PIT news/activity-alert datasets.
- Existing candidate review and audit flow.

## Outputs

- Email ingestion configuration example with:
  - mailbox provider/mode,
  - label/folder,
  - allowed sender domains,
  - lookback window,
  - local token/credential paths,
  - manual-review fallback behavior.
- A local email evidence dataset or normalized adapter that can feed existing
  `news_rss` and `unusual_activity_alerts` lanes without bypassing PIT.
- Provenance fields for every email-derived item:
  - source,
  - sender,
  - message id,
  - received timestamp,
  - article/alert URL,
  - timestamp observed,
  - confidence,
  - verification level.
- Deduplication by message id and normalized source URL.
- A refresh-batch job that can run the email ingest independently.
- Redaction rules so raw email bodies and secrets are not committed.

## Acceptance Criteria

1. The agency can ingest approved emails from a local export fixture without
   network access.
2. The same interfaces can later support Gmail/Outlook/IMAP without changing
   downstream signal code.
3. Email-derived rows are PIT-readable and cannot leak future emails into an
   earlier `as_of` date.
4. Email-derived evidence appears in source/readiness reporting without exposing
   private email content.
5. Missing mailbox credentials produce a readiness warning, not a hard blocker
   for the current stocks-only paper workflow.
6. Unit tests cover sender allowlisting, ticker extraction, deduplication,
   PIT filtering, and redaction.

## Tests Required

- Unit tests for parsing local `.eml` fixtures.
- Unit tests for config validation and blocked/missing credential states.
- Unit tests for PIT loader filtering.
- Refresh-batch dry-run test.

## Out of Scope

- Service-specific Seeking Alpha, TradeVision, or Zacks classification.
- Browser login automation.
- Bulk website crawling.
- Broker execution.

## Notes

Implement this as user-authorized personal mailbox monitoring. It should replace
manual inbox triage, not crawl subscription websites broadly.
