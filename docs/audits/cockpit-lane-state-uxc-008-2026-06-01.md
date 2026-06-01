# UXC-008 Data State And Lane Visibility QA

Date: 2026-06-01

Ticket: UXC-008 - Data State And Lane Visibility

Definition Of Done

- Cockpit lane state uses normalized operator language for loading, analysis pending, unavailable, needs refresh, optional, ready for review, and ready for paper execution: PASS
- Internal `stale` state is normalized to `needs_refresh` before cockpit display: PASS
- Lane rows show progress, ETA when reported, latest proof/as-of, checked timestamp, gap, and next action: PASS
- Refresh buttons are shown only for lanes or datasets with a runnable scheduler action; disabled explicit actions show a non-clickable reason: PASS
- Optional lanes are not counted as blockers: PASS
- The Universe/Data Sources panel layout keeps gap/action text readable at desktop/kiosk/mobile QA viewports: PASS

Implementation Evidence

- `src/agency/views/cockpit.py` now normalizes raw lane state values before display, carries `eta_label`, and suppresses explicit refresh URLs when scheduler metadata says no runnable job exists.
- `src/agency/templates/_cockpit_panels.html` now displays ETA and combines state, required-now, and paper-impact details into a compact lane-board column.
- `src/agency/templates/cockpit.html` removes numeric phase badges that conflicted with the current product-language tests.
- `src/agency/static/styles.css` compacts the lane-board grid so the gap/action column remains visible.
- `src/agency/views/_shared.py` removes one remaining operator-facing "this lane" phrase from the signal methodology copy.
- `tests/unit/test_cockpit_lane_state.py` covers state normalization, ETA, refresh suppression, and the compact lane-board labels.

Verification

- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_lane_state.py tests\unit\test_lane_state.py tests\unit\test_fastapi_app.py -q` -> 235 passed
- `.\.venv\Scripts\python -m pytest tests\unit\test_ux_product_audit_20260529.py tests\unit\test_cockpit_lane_state.py tests\unit\test_cockpit_panels.py -q` -> 44 passed
- `.\.venv\Scripts\python -m ruff check src\agency\views\cockpit.py src\agency\views\_shared.py tests\unit\test_cockpit_lane_state.py tests\unit\test_ux_product_audit_20260529.py` -> passed
- `.\.venv\Scripts\python scripts\check_ux_preservation.py --group all` -> pass
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_lane_state.py tests\unit\test_lane_state.py tests\unit\test_fastapi_app.py tests\unit\test_cockpit_panels.py tests\unit\test_cockpit_routes.py tests\unit\test_ux_product_audit_20260529.py -q` -> 294 passed
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --focus panels --output research\results\ux-qa\cockpit-lane-state-uxc-008-final.json` -> failure_count=0

Browser QA Artifacts

- `research/results/ux-qa/cockpit-lane-state-uxc-008-final.json/cockpit-ux-qa.json`
- `research/results/ux-qa/cockpit-lane-state-uxc-008-final.json/desktop-1366-normal-panel-universe.png`
- `research/results/ux-qa/cockpit-lane-state-uxc-008-final.json/mobile-390-normal-panel-universe.png`

Visual Review Note

- The first browser pass showed the gap/action column squeezed at 1366px. The lane board was compacted and retested; the final screenshot shows the gap/action text and refresh button visible in the panel.
