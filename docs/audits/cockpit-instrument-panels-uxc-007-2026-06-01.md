# UXC-007 Instrument Panels QA

Date: 2026-06-01

Ticket: UXC-007 - Instrument Panels

Definition Of Done

- Universe/Data Sources panel shows lane state, progress, proof timestamps, gaps, and eligible refresh actions: PASS
- Signals panel has confirmed/inferred/suppressed filters and concrete candidate evidence rows, not only lane health: PASS
- Audit panel shows per-ticker lifecycle trace and evidence proof fingerprint when available: PASS
- Policy panel shows deployed/staged values, diff state, next-cycle apply, and LIVE_TRADING locked off: PASS
- Monitor panel shows live or polling fallback state plus current event rows: PASS
- Ticker panel opens from candidate rows and loads full candidate detail from the cockpit API: PASS
- Panels open/close through the browser flow with no console errors, page errors, unreadable controls, or horizontal overflow: PASS

Implementation Evidence

- `src/agency/views/cockpit.py` now feeds the Signals panel with candidate evidence rows first, then signal-process health rows.
- `src/agency/templates/_cockpit_panels.html` now renders each signal row with source, proof timestamp, key value, and row kind.
- `src/agency/static/cockpit.js` no longer falls back to a vague signal-summary line when a signal has hard evidence or detail attached.
- `tests/unit/test_cockpit_panels.py` verifies the Signals panel includes candidate evidence and concrete proof fields.

Verification

- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_panels.py tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_routes.py -q` -> 75 passed
- `node --check src\agency\static\cockpit.js` -> passed
- `.\.venv\Scripts\python -m ruff check src\agency\views\cockpit.py tests\unit\test_cockpit_panels.py tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_routes.py` -> passed
- `.\.venv\Scripts\python scripts\check_ux_preservation.py --group all` -> pass
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_panels.py tests\unit\test_cockpit_candidates.py tests\unit\test_cockpit_routes.py tests\unit\test_fastapi_app.py -q` -> 292 passed
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --focus panels --output research\results\ux-qa\cockpit-panels-uxc-007-final.json` -> failure_count=0

Browser QA Artifacts

- `research/results/ux-qa/cockpit-panels-uxc-007-final.json/cockpit-ux-qa.json`
- `research/results/ux-qa/cockpit-panels-uxc-007-final.json/desktop-1366-normal-panel-signals.png`
- `research/results/ux-qa/cockpit-panels-uxc-007-final.json/mobile-390-normal-panel-signals.png`

Residual Risk

- The live browser snapshot had no current candidate signal rows to display in the panel; the populated signal-log behavior is covered by unit/context tests using the cockpit source contract.
