# Trading Agency UX / Design Review Export

Generated: 2026-05-21 08:06 Asia/Jerusalem

Current controlled source commit: `8e8822f chore: checkpoint controlled agency version`

## Purpose

This bundle is for an external UX/design specialist reviewing the Trading Agency v2 operator experience, especially dashboards, data-health indicators, candidate review, risk, and paper-trading workflow.

## What To Review First

1. `rendered-html/`
   - Current server-rendered HTML snapshots for the main screens.
   - `route-status.json` lists each captured route and status code.
2. `review-material/docs/ux-specialist-brief.md`
   - Existing UX specialist brief.
3. `review-material/docs/audit-findings.md`
   - Consolidated previous UX audit findings.
4. `review-material/docs/audit-implementation-plan.md`
   - Existing implementation plan from the prior audit.
5. `review-material/docs/current-controlled-version-2026-05-21.md`
   - Current source-control checkpoint, verification, and artifact policy.

## Key Screens / Routes

- Command dashboard: `/`
- Signals dashboard: `/signals`
- Final selection: `/final-selection`
- Candidate detail sample: `/candidates/AAPL`
- Risk dashboard: `/risk`
- Execution preview: `/execution-preview`
- Portfolio monitor: `/portfolio-monitor`
- Market regime: `/market-regime`
- Policy: `/policy`
- Audit: `/audit`
- Learning: `/learning`

## Bundle Contents

- `source-current-controlled-8e8822f.zip`
  - Full tracked repository source at the current controlled checkpoint.
  - Does not include untracked local runtime files, `.env`, raw emails, parquet data, local DBs, or ignored logs.
- `review-material/docs/`
  - Product, workflow, UX audit, system review, recovery, and planning documents.
- `review-material/ui-source/agency/`
  - Current FastAPI app package, templates, CSS, JS, views, and services.
- `review-material/tests/`
  - UX/API/dashboard/data-health-related unit tests.
- `review-material/scripts/`
  - Local run and readiness-check scripts useful for reproducing screens.
- `runtime-snapshots/`
  - Selected current/latest JSON and Markdown snapshots for dashboard context.
  - These are operational artifacts, not a guarantee of live market freshness.
- `existing-screenshots/`
  - Existing mockup screenshots, if present locally.
- `review-material/docs/ux-review-assets/`
  - Historical screenshots from the previous UX audit pass.

## Privacy / Safety Notes

This export intentionally excludes:

- `.env` and `.env.*`
- local provider token/config files
- raw subscription emails
- local databases
- parquet datasets
- logs
- browser sessions

The bundle may include provider names, ticker symbols, dashboard state, route output, and synthetic/test descriptions from source and docs. It should not include live API secrets.

## How To Run Locally

From the full repository, not from this export folder:

```powershell
.\.venv\Scripts\python scripts\run_local_app.py
```

Then open:

```text
http://127.0.0.1:8000/
```

If using the packaged source zip in a new location, restore the Python environment and configure local env vars first. Do not add real API keys to this export bundle.

## Suggested UX Review Focus

- Is the first screen clearly bottom-line-up-front?
- Can an operator immediately see system readiness, blockers, refresh actions, and review queue?
- Does each dashboard explain data health in plain language?
- Are candidate conviction, contradictory evidence, LLM analysis, risk, and execution next steps understandable?
- Are table rows, badges, timestamps, and tooltips readable on desktop and mobile?
- Does the paper-trading approval flow make the next operator action obvious?
