# UXC-006 Clearance And Submit Gate QA

Date: 2026-06-01

Ticket: UXC-006 - Clearance And Submit Gate

Definition Of Done

- Manifest lists exits before buys: PASS
- Every broker-submit row exposes ticker, side, notional, cycle ID, proof time, and intent hash label: PASS
- Exit review rows are visibly review-only and do not include broker submit hidden fields: PASS
- Submit button remains disabled until checkbox acknowledgement and exact phrase `submit paper orders`: PASS
- Submit payload stays JSON-bound and server revalidates cycle, ticker, as-of, side, notional, and order-intent hash before broker submit: PASS
- Broker IDs are displayed only from broker responses: PASS

Implementation Evidence

- `src/agency/views/cockpit.py` now carries visible clearance proof fields from the current orderable execution preview into the cockpit manifest.
- `src/agency/templates/cockpit.html` now renders action, value, cycle, proof time, and intent hash label for each paper order row.
- `src/agency/static/cockpit.js` now stages local exit-review rows with the same manifest structure and marks them review-only.
- `src/agency/static/styles.css` adds stable manifest proof-grid layout with mobile collapse.
- `tests/unit/test_cockpit_clearance.py` covers visible manifest proof and context propagation.

Verification

- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_clearance.py tests\unit\test_cockpit_candidates.py -q` -> 58 passed
- `node --check src\agency\static\cockpit.js` -> passed
- `.\.venv\Scripts\python -m ruff check src\agency\views\cockpit.py tests\unit\test_cockpit_clearance.py tests\unit\test_cockpit_candidates.py` -> passed
- `.\.venv\Scripts\python scripts\check_ux_preservation.py --group all` -> pass
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_routes.py tests\unit\test_fastapi_app.py tests\unit\test_cockpit_clearance.py -q` -> 297 passed
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --focus clearance --output research\results\ux-qa\cockpit-clearance-uxc-006.json` -> failure_count=0

Browser QA Artifacts

- `research/results/ux-qa/cockpit-clearance-uxc-006.json/cockpit-ux-qa.json`
- `research/results/ux-qa/cockpit-clearance-uxc-006.json/desktop-1366-normal-clearance.png`
- `research/results/ux-qa/cockpit-clearance-uxc-006.json/mobile-390-normal-clearance.png`

Residual Risk

- The live QA snapshot had no orderable paper manifest rows, so browser QA verified the clearance phase and gate behavior while unit/context tests verified populated manifest proof rows.
