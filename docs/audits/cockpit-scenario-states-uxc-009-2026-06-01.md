# UXC-009 Scenario States QA

Date: 2026-06-01

Ticket: UXC-009 - Scenario States

Definition Of Done

- Backend chooses normal, review, no-actionable, outage, and submitted states from current source/execution context: PASS
- No-actionable state shows closest candidates and a clear skip-to-portfolio path: PASS
- Outage state blocks candidate controls and shows engine, retry, and last-good proof context: PASS
- Submitted state shows broker-returned paper order cards and total notional: PASS
- QA scenario overrides stay behind `AGENCY_COCKPIT_QA_SCENARIOS` and are labeled training-only/non-operational: PASS
- Restored local staged decisions preserve operator work but cannot reopen an unsafe scenario phase or unlock submit without revalidation: PASS
- Browser QA covers all scenario states and treats a locked submit gate as the correct behavior for safety scenarios: PASS

Implementation Evidence

- `src/agency/static/cockpit.js` now applies `scenarioSafePhase()` when restoring staged local decisions and invalidates submit when the active scenario forces a safety phase.
- `scripts/check_cockpit_ux_qa.py` now recognizes outage, no-actionable, and submitted states as safety scenarios where the submit button should remain locked.
- `tests/unit/test_cockpit_views.py` covers safety-phase restore behavior.
- `tests/unit/test_cockpit_ux_qa_script.py` covers the all-scenario browser checker behavior.

Verification

- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_state.py tests\unit\test_cockpit_preferences.py tests\unit\test_cockpit_routes.py tests\unit\test_cockpit_views.py tests\unit\test_cockpit_ux_qa_script.py -q` -> 60 passed
- `node --check src\agency\static\cockpit.js` -> passed
- `.\.venv\Scripts\python -m ruff check scripts\check_cockpit_ux_qa.py tests\unit\test_cockpit_ux_qa_script.py tests\unit\test_cockpit_views.py` -> passed
- `.\.venv\Scripts\python scripts\check_ux_preservation.py --group all` -> pass
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_state.py tests\unit\test_cockpit_preferences.py tests\unit\test_cockpit_routes.py tests\unit\test_cockpit_views.py tests\unit\test_cockpit_ux_qa_script.py tests\unit\test_fastapi_app.py tests\unit\test_cockpit_clearance.py -q` -> 299 passed
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --scenario all --focus shell --output research\results\ux-qa\cockpit-scenarios-uxc-009-final.json` -> failure_count=0

Browser QA Artifacts

- `research/results/ux-qa/cockpit-scenarios-uxc-009-final.json/cockpit-ux-qa.json`
- `research/results/ux-qa/cockpit-scenarios-uxc-009-final.json/desktop-1366-normal-shell.png`
- `research/results/ux-qa/cockpit-scenarios-uxc-009-final.json/desktop-1366-no-actionable-shell.png`
- `research/results/ux-qa/cockpit-scenarios-uxc-009-final.json/desktop-1366-outage-shell.png`
- `research/results/ux-qa/cockpit-scenarios-uxc-009-final.json/desktop-1366-submitted-shell.png`

Visual Review Note

- The first all-scenario browser pass failed because the checker expected submit to unlock even when the page was in a safety scenario. The checker was corrected and rerun; the final pass shows all scenario states green.
