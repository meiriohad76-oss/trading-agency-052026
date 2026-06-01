# UXC-004 Ticker Detail Drawer QA

Date: 2026-06-01

## Scope

Implemented a stronger cockpit ticker drawer without changing signal calculations:

- Drawer still lazy-loads `/api/cockpit/ticker/{ticker}` through the bounded quick-detail path.
- Data health now includes an explanatory detail line with blocker, recommended action, and timestamp where available.
- LLM section now exposes manual review action metadata when the current report has cycle/as-of proof and the LLM was not run.
- News/RSS and subscription-email context cards are rendered in the drawer.
- Empty support, caution, signal, and evidence sections now name the ticker and report timestamp instead of using generic "no evidence" wording.

## Verification

Passed:

- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_routes.py::test_api_cockpit_ticker_detail_returns_rich_payload tests\unit\test_cockpit_routes.py::test_cockpit_ticker_detail_uses_light_candidate_context tests\unit\test_cockpit_routes.py::test_cockpit_ticker_detail_has_bounded_timeout -q`
- `node --check src\agency\static\cockpit.js`
- `.\.venv\Scripts\python -m ruff check src\agency\views\cockpit.py tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_routes.py`
- `.\.venv\Scripts\python -m pytest tests\unit\test_signal_evidence.py tests\unit\test_signal_evidence_fundamentals.py tests\unit\test_subscription_thesis_signal.py -q`
- `.\.venv\Scripts\python scripts\check_ux_preservation.py --group all`
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_routes.py tests\unit\test_fastapi_app.py -q`
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --scenario normal --focus panels --output research\results\ux-redesign-v3-qa\uxc-004-panels`

Browser QA result: `failure_count=0` across desktop, kiosk, and mobile panel checks.

## Live-Data Caveat

The temporary local cockpit run on port `8017` was in the `no-actionable` scenario, so no visible candidate-row drawer button existed for a live click-through test. Unit/API tests cover reviewable, order-reviewable, audit-only, timeout, and API payload behavior with controlled data.

