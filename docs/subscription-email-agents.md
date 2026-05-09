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

## Authenticated Article Sessions

For paid article links, use a local saved browser session instead of storing
site passwords in config. Install the optional browser tooling:

```powershell
.\.venv\Scripts\python -m pip install .[web]
.\.venv\Scripts\python -m playwright install chromium
```

Then save a session for each paid provider you want the agent to open:

```powershell
.\.venv\Scripts\python research\scripts\save_article_browser_session.py `
  --provider seeking_alpha
```

The script opens a visible browser. Log in manually, return to the terminal, and
press Enter. The session is saved under
`research/config/browser-sessions/`, which is ignored by git.

Supported providers are:

- `seeking_alpha`
- `tradevision`
- `zacks`

After at least one session is saved, enable link opening in
`research/config/subscription-email.local.json`:

```json
"follow_article_links": true,
"article_fetch_mode": "auto",
"article_browser_state_dir": "research/config/browser-sessions",
"article_browser_wait_seconds": 5
```

`auto` tries direct HTTP, Scrapling, and then the saved browser session. Use
`browser` when a provider always requires login. Article text is analyzed in
memory only; summaries store hashes, ticker tags, direction, and catalyst tags,
not the raw paid article body.

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

## Automatic Monitor

Run one monitor cycle:

```powershell
.\.venv\Scripts\python research\scripts\watch_subscription_emails.py `
  --config research\config\subscription-email.local.json `
  --once
```

Run continuously:

```powershell
.\.venv\Scripts\python research\scripts\watch_subscription_emails.py `
  --config research\config\subscription-email.local.json `
  --poll-seconds 60
```

In `local_eml` mode, the monitor watches
`research/data/raw/subscription_emails/` and starts analysis when a new or
changed `.eml` file appears.

For IMAP-style mailbox polling, set `mode` to `imap`, `gmail`, or `outlook` and
keep secrets in `.env`, not in JSON:

```json
"mode": "gmail",
"mailbox_label": "INBOX",
"mailbox_username_env": "SUBSCRIPTION_EMAIL_USERNAME",
"mailbox_password_env": "SUBSCRIPTION_EMAIL_PASSWORD",
"mailbox_search": "UNSEEN",
"mailbox_mark_seen": false
```

Then add the corresponding values to `.env`. The monitor downloads only
allowlisted sender domains into the ignored local `.eml` folder, then runs the
same analysis pipeline. Messages are fetched with `BODY.PEEK[]` by default so
they are not marked read unless `mailbox_mark_seen` is set to `true`.

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
