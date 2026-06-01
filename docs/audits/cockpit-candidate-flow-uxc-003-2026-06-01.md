# UXC-003 Candidate Phase Process Flow QA

Date: 2026-06-01

## Scope

Implemented ticker-context continuity for the cockpit candidate phase:

- Candidate rows expose a focused execution URL.
- Cockpit order-detail links target `/execution-preview?ticker=TICKER#focused-preview-TICKER`.
- Manifest review buttons, review forms, and order-detail links carry `data-cockpit-focus-ticker`.
- Cockpit local storage persists only selected ticker/phase/exits/staged local decisions, not server approvals.
- The selected ticker is highlighted when the operator moves between cockpit phases.
- Candidate action buttons use stronger V3 contrast and stable 44px minimum height.

## Verification

Passed:

- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_candidates.py tests\unit\test_fastapi_app.py::test_cockpit_renders_order_intent_review_control tests\unit\test_fastapi_app.py::test_execution_preview_page_keeps_requested_ticker_in_focus tests\unit\test_fastapi_app.py::test_candidate_review_post_records_human_review -q`
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_routes.py tests\unit\test_fastapi_app.py -q`
- `.\.venv\Scripts\python -m ruff check src\agency\views\cockpit.py tests\unit\test_cockpit_candidates.py tests\unit\test_fastapi_app.py`
- `node --check src\agency\static\cockpit.js`
- `.\.venv\Scripts\python scripts\check_ux_preservation.py --group all`
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --scenario normal --focus candidates --output research\results\ux-redesign-v3-qa\uxc-003`
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --scenario normal --focus shell --output research\results\ux-redesign-v3-qa\uxc-003-shell`

Browser QA result: `failure_count=0` for both cockpit candidate and shell focus runs across desktop, kiosk, and mobile viewports.

## Live-Data Caveat

The temporary local cockpit run on port `8017` had no currently actionable manifest button and no order-review focused link to click in live data. A Playwright probe verified that no rendered focused execution links were malformed. The click-through behavior is covered by unit/FastAPI regression tests using controlled candidate and execution-preview data.

