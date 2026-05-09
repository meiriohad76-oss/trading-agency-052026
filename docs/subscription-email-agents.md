# Subscription Email Agents

T100-T104 add a local, user-authorized mailbox evidence path for paid
subscription emails. The first implementation reads local `.eml` exports only;
Gmail, Outlook, and IMAP are represented in config for later connectors.

## What It Ingests

- Seeking Alpha emails become ticker-tagged news/catalyst rows.
- Zacks emails become ticker-tagged news, rank-change, rating-change, or analyst
  recommendation rows.
- TradeVision news emails become news/catalyst rows.
- TradeVision dark-pool, block-trade, unusual stock, and options-flow emails
  become `unusual_activity_alerts` rows.

Raw email bodies are never written to summary artifacts. Message IDs are stored
as hashes, article titles are stored only as hashes, and fetched article text is
analyzed in memory only.

## Local Setup

Copy the example config and edit the local copy:

```powershell
Copy-Item research\config\subscription-email.example.json `
  research\config\subscription-email.local.json
```

Export approved messages from the dedicated mailbox folder into:

```text
research/data/raw/subscription_emails/
```

That folder is ignored by git. Keep only service emails that the agency is
allowed to read.

To let the agent open article links from those emails, set this in
`research/config/subscription-email.local.json`:

```json
"follow_article_links": true,
"article_link_domains": [
  "seekingalpha.com",
  "email.seekingalpha.com",
  "tradevision.io",
  "tradevision.com",
  "zacks.com"
]
```

The first implementation uses direct HTTP fetches for allowlisted links. If a
paid article requires an active browser login, the fetch may return a login page
or fail; those attempts are counted but do not expose article content.

## Import Command

```powershell
.\.venv\Scripts\python research\scripts\import_subscription_emails.py `
  --config research\config\subscription-email.local.json `
  --summary-root research\results\latest-subscription-emails
```

The command writes:

- `research/data/parquet/news_rss.parquet`
- `research/data/parquet/unusual_activity_alerts.parquet`
- `research/data/parquet/subscription_emails.parquet`
- downstream manifests for written datasets
- `research/results/latest-subscription-emails/subscription-email-ingest.json`
- `research/results/latest-subscription-emails/subscription-email-ingest.md`

The safe summary includes link-fetch counts: attempted, analyzed, failed, and
skipped.

## Refresh Batch

To run the agents through the data-refresh batch, add this dataset and config
path to `research/config/live-refresh.local.json`:

```json
"datasets": [
  "prices_daily",
  "sec_company_facts",
  "sec_form4",
  "sec_13f",
  "news_rss",
  "subscription_emails"
],
"subscription_email_config": "research/config/subscription-email.local.json"
```

If the local export folder or future mailbox token is missing, the Live Config
panel shows a warning. If `subscription_emails` is explicitly selected in a
refresh batch, the job blocks cleanly until the configured local input exists.

## Calibration

After an import, write the conservative T104 calibration report:

```powershell
.\.venv\Scripts\python research\scripts\write_subscription_email_calibration.py `
  --ingest-summary research\results\latest-subscription-emails\subscription-email-ingest.json `
  --output-root research\results\latest-subscription-email-calibration
```

Initial runtime guidance is context-only:

- `news`: context only until forward validation.
- `activity_alerts`: context only until forward validation.

Subscription evidence can corroborate and enrich runtime evidence packs through
the existing `news_rss` and `unusual_activity_alerts` lanes, but it should not
increase WATCH/BUY weighting until real mailbox coverage is validated.
