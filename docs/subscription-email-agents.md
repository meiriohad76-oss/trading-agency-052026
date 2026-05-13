## Daily Operations Guide

**For continuous daily operation:** use `watch_subscription_emails.py`.
This script polls the configured mailbox on a regular cadence (default: every
5 minutes) and ingests new emails as they arrive. Start it once at the beginning
of the day alongside the scheduler.

**For one-shot historical backfill only:** use `import_subscription_emails.py`.
This script processes the mailbox once and exits. Do not run it while
`watch_subscription_emails.py` is active — the concurrency guard will prevent
the second process from starting, but running them sequentially on the same
timeframe may produce duplicate rows.

**Running both safely:** `watch_subscription_emails.py` holds a lock file at
`research/data/.email-watch.lock` while running. Any attempt to start a second
instance exits with a clear error message.

---

# Subscription Email Agents

T100-T104 add a local, user-authorized mailbox evidence path for paid
subscription emails. The agent can read local `.eml` exports or poll an
allowlisted Gmail/IMAP mailbox folder, then convert relevant alerts and linked
articles into ticker-level evidence.

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

The agent can use direct HTTP fetches for simple links, but paid providers
should use the authenticated browser flow below. In that flow the agent reuses
one visible Chrome/Edge session for the run, opens each paid article in a new
tab, analyzes the rendered content, saves the session state, and closes the
article tab before moving to the next link.

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
  --provider seeking_alpha `
  --browser-channel chrome
```

The script opens a visible browser. Log in manually, return to the terminal, and
press Enter. The session is saved under
`research/config/browser-sessions/`, which is ignored by git. It also uses a
persistent local browser profile under that same ignored directory. If a paid
site blocks Playwright's bundled Chromium, use `--browser-channel chrome` or
`--browser-channel msedge`.

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
"article_analysis_cache_path": "research/config/article-analysis-cache.local.json",
"article_browser_wait_seconds": 5,
"article_browser_channel": "chrome",
"article_browser_headless": false
```

`auto` tries direct HTTP, Scrapling, and then the saved browser session. Use
`browser` when a provider always requires login. With
`article_browser_headless=false`, if the saved session is missing or an article
still resolves to a login/security page, the agent pauses and tells you to log in
inside the Chrome window, then press Enter in PowerShell. Each article opens in a
new tab in that same window and the tab is closed after analysis. Article text is
analyzed in memory only; summaries store hashes, ticker tags, direction,
catalyst tags, risk flags, key-point labels, and a compact derived thesis, not
the raw paid article body.

If a provider blocks the Playwright-launched Chrome window, use your own Chrome
window through the local Chrome DevTools Protocol port. First close normal Chrome
windows, then start a dedicated user-owned Chrome profile:

```powershell
Start-Process "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" `
  -ArgumentList @(
    "--remote-debugging-port=9222",
    "--user-data-dir=$env:LOCALAPPDATA\TradingAgency\ChromeProfile",
    "https://seekingalpha.com"
  )
```

Log in to Seeking Alpha manually in that Chrome window and clear any human
verification prompt yourself. Then set:

```json
"article_fetch_mode": "browser",
"article_browser_cdp_url": "http://127.0.0.1:9222",
"article_browser_headless": false
```

With `article_browser_cdp_url` set, the agent connects to that already-open
Chrome instead of launching its own browser. It opens each article in a new tab,
reads the rendered content, and closes only the article tab.

## Interactive Login Preflight

For Seeking Alpha, enable the login preflight so the mailbox/article agent does
not begin opening email links until you have confirmed the browser is logged in:

```json
"article_login_preflight_required": true,
"article_login_preflight_services": ["seeking_alpha"]
```

When this is enabled, `import_subscription_emails.py` and
`watch_subscription_emails.py` first open the provider login page in the
configured browser. If `article_browser_cdp_url` is set, the login page opens in
the already-running user Chrome attached to that DevTools port. If no attached
Chrome is responding yet, the process starts a dedicated Trading Agency Chrome
window with that DevTools port and local profile. Log in manually, clear any
human-verification screen yourself, then press Enter in PowerShell. Only after
that confirmation does the email agent sync the mailbox and open article links.
Article links reuse that same logged-in browser context.

The guarded first-version pipeline and data-refresh batch also honor this
setting. When the subscription-email config requires the preflight, that step is
run attached to the PowerShell console so the browser-login instruction and
Enter confirmation are visible before the agent continues.

You can force the preflight for a one-off import even if the config disables it:

```powershell
.\.venv\Scripts\python research\scripts\import_subscription_emails.py `
  --config research\config\subscription-email.local.json `
  --require-article-login `
  --article-login-service seeking_alpha `
  --include-seen `
  --max-emails 2 `
  --max-article-links 1 `
  --enable-article-llm-analysis
```

Successful article analyses are cached by normalized URL in the ignored
`article_analysis_cache_path`. The cache stores only URL, hashes, ticker tags,
direction, catalyst tags, risk flags, key-point labels, derived thesis, status,
and fetch time, so repeated monitor cycles do not reopen old paid links.

## LLM Article Analysis

For deeper article reasoning, enable the article LLM layer:

```json
"article_llm_analysis_enabled": true,
"article_llm_model": "gpt-4.1-mini",
"article_llm_timeout_seconds": 45
```

The agent then sends each successfully opened article link, up to
`article_max_total_per_run`, to OpenAI using `OPENAI_API_KEY`. It asks for a
ticker-focused thesis, specific key points, catalyst tags, risk flags, direction,
signal strength, and how the agency should use the article. The raw article text
is not written to parquet, summaries, or cache.

If OpenAI is unavailable, the link still falls back to deterministic article
classification and the context source records that fallback. When LLM article
analysis is enabled, old deterministic cache entries are ignored so already-seen
links can be upgraded to LLM-derived thesis rows.

## Import Command

```powershell
.\.venv\Scripts\python research\scripts\import_subscription_emails.py `
  --config research\config\subscription-email.local.json `
  --summary-root research\results\latest-subscription-emails
```

To override the JSON setting for one run:

```powershell
.\.venv\Scripts\python research\scripts\import_subscription_emails.py `
  --config research\config\subscription-email.local.json `
  --enable-article-llm-analysis `
  --max-article-links 1
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
