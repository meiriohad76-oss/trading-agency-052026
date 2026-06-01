# UXC-005 Portfolio Phase QA

Date: 2026-06-01

## Scope

Implemented a more operator-focused portfolio phase:

- Portfolio phase now explains whether review is required or can be skipped.
- Empty portfolio state gives a clear "continue to clearance" path.
- Gross exposure and cash reserve values visibly recompute from locally staged candidate decisions.
- Keep/Close position decisions persist in cockpit session state.
- Close decisions add a local close-review row to the clearance manifest, with clear server-revalidation wording.

## Verification

Passed:

- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_candidates.py -q`
- `node --check src\agency\static\cockpit.js`
- `.\.venv\Scripts\python -m ruff check src\agency\views\cockpit.py tests\unit\test_cockpit_candidates.py`
- `.\.venv\Scripts\python scripts\check_ux_preservation.py --group all`
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_routes.py tests\unit\test_fastapi_app.py -q`
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --scenario normal --focus portfolio --output research\results\ux-redesign-v3-qa\uxc-005-portfolio`

Browser QA result: `failure_count=0` across desktop, kiosk, and mobile portfolio checks.

## Live-Data Caveat

The temporary local cockpit run on port `8017` reported zero open positions, so the live browser probe verified the empty-portfolio path and actionable clearance guidance. The Keep/Close-to-manifest behavior is covered by unit/static tests with controlled position data.

