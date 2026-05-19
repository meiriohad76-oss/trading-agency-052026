# T162 - Seeking Alpha Article Login Flow Hardening

Status: PASS

## Scope

Hardened the subscription email/article analysis flow so Seeking Alpha links are not opened or marked as skipped evidence when the required browser login is not confirmed.

## Changes

- `research/src/subscription_email/article_session.py`
  - Attached-CDP mode now requires the user's already-open Chrome at `article_browser_cdp_url`.
  - It no longer launches an isolated Chrome profile when CDP connection fails.
- `research/src/subscription_email/linked_content.py`
  - Login-handler failures from `BrowserSessionUnavailableError` or `EOFError` now abort the run instead of being swallowed into `article_login_preflight_required`.
- `research/scripts/import_subscription_emails.py`
  - Manual email ingest now stops with a JSON `login_acknowledgement_required` payload and exit code `2` when login cannot be verified.
- `research/scripts/watch_subscription_emails.py`
  - Watch/once mode now stops with a JSON `login_acknowledgement_required` payload and exit code `2` when login cannot be verified.
- `tests/unit/test_subscription_email_agents.py`
  - Added regression coverage for failed preflight handler aborts, import preflight aborts, and attached-CDP requiring user-opened Chrome.

## Verification

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_subscription_email_agents.py -q -k "preflight_handler_failure or import_preflight_aborts or attached_chrome_preflight_requires"
```

Result: `3 passed, 86 deselected`

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_subscription_email_agents.py -q
```

Result: `89 passed`

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_data_refresh_batch.py tests\unit\test_scheduler_work_queue.py -q -k "subscription_email or interactive_subscription_email_login or article_login"
```

Result: `3 passed, 74 deselected`

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_ops_scripts.py -q
```

Result: `33 passed`

```powershell
.\.venv\Scripts\python -m py_compile research\scripts\import_subscription_emails.py research\scripts\watch_subscription_emails.py research\src\subscription_email\article_session.py research\src\subscription_email\linked_content.py
```

Result: passed

```powershell
.\.venv\Scripts\python research\scripts\import_subscription_emails.py --config research\config\subscription-email.local.json --source-path research\data\raw\subscription_emails\ff0a0d6a8fba5240f8a25b2d.eml --max-emails 1 --max-article-links 1 --enable-article-llm-analysis --require-article-login --article-login-service seeking_alpha; Write-Output "EXIT_CODE=$LASTEXITCODE"
```

Result: stopped before article opening with `status=login_acknowledgement_required`; `EXIT_CODE=2`.

## Remaining Live Step

To prove actual Seeking Alpha article analysis, start Chrome with remote debugging, log in to Seeking Alpha in that Chrome session, then rerun a small ingest. Expected success criterion: `linked_content_attempted >= 1` and `linked_content_succeeded >= 1`.
