# UXC-011 Pi/Kiosk Hardening QA

Date: 2026-06-01

Ticket: UXC-011 - Pi/Kiosk Hardening

Definition Of Done

- Cockpit production assets make zero CDN or external browser requests during browser QA: PASS
- Cockpit uses local/system font stacks only; no unbundled named web fonts remain in production CSS: PASS
- Cockpit viewport and Pi runbook include accidental pinch/overscroll guardrails: PASS
- Visible cockpit operator controls meet the 44px touch-target floor in browser QA: PASS
- Tooltips are available by focus, tap, and long-press: PASS
- Shared polling intervals are registered centrally, skip hidden tabs, use request timeouts for heartbeat, and clear on `pagehide`: PASS
- Ticker detail fetches are bounded by timeout, abort prior requests, and ignore older racing responses: PASS
- Local staged decisions are not erased until the operator explicitly restores or discards the restore prompt: PASS
- Scenario-locked states keep the operator in the safe phase and keep submit blocked: PASS
- Kiosk launch and restart instructions are documented: PASS
- Short pre-ship desktop kiosk soak is recorded: PASS
- Physical 8-hour Raspberry Pi memory/CPU soak: DEFERRED until hardware-session verification.

Implementation Evidence

- `src/agency/templates/cockpit.html` now overrides the viewport for the cockpit with `maximum-scale=1`, `user-scalable=no`, and `viewport-fit=cover`.
- `src/agency/static/styles.css` and `src/agency/static/v3-screens.css` keep cockpit controls at or above 44px and remove unbundled named web-font references from production font stacks.
- `src/agency/static/cockpit.js` now handles local-storage failures without breaking the cockpit, preserves staged restore state until explicit operator choice, applies scenario-safe phase routing on phase clicks, supports long-press tooltips, and aborts racing ticker-detail requests.
- `src/agency/static/data-refresh-progress.js` now uses a central interval registry, skips polling while hidden, clears timers on `pagehide`, and gives heartbeat requests the same timeout/in-flight protection as other polling.
- `scripts/check_cockpit_ux_qa.py` now fails on external requests and visible cockpit controls smaller than 44px.
- `docs/raspberry-pi-cockpit.md` now documents `--disable-pinch`, disabled overscroll navigation, long-press tooltips, and the physical soak checklist.

Verification

- `node --check src\agency\static\cockpit.js` -> passed
- `node --check src\agency\static\data-refresh-progress.js` -> passed
- `.\.venv\Scripts\python -m ruff check scripts\check_cockpit_ux_qa.py tests\unit\test_cockpit_ux_qa_script.py tests\unit\test_cockpit_pi_readiness.py` -> passed
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_pi_readiness.py tests\unit\test_cockpit_ux_qa_script.py tests\unit\test_cockpit_preferences.py -q` -> 33 passed
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_ux_qa_script.py tests\unit\test_cockpit_pi_readiness.py -q` -> 26 passed
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --focus shell --output research\results\ux-qa\cockpit-kiosk-uxc-011-rerun.json` -> failure_count=0
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --scenario all --focus shell --output research\results\ux-qa\cockpit-kiosk-uxc-011-all-scenarios.json` -> failure_count=0
- 60-second kiosk soak at 1280x720 touch viewport -> PASS, 0 console errors, 0 page errors, 0 external requests, 0 horizontal overflow
- `.\.venv\Scripts\python scripts\check_ux_preservation.py --group all` -> pass
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_pi_readiness.py tests\unit\test_cockpit_ux_qa_script.py tests\unit\test_cockpit_preferences.py tests\unit\test_cockpit_views.py tests\unit\test_cockpit_routes.py tests\unit\test_fastapi_app.py -q` -> 287 passed

Browser QA Artifacts

- `research/results/ux-qa/cockpit-kiosk-uxc-011-rerun.json/cockpit-ux-qa.json`
- `research/results/ux-qa/cockpit-kiosk-uxc-011-rerun.json/kiosk-1280-normal-shell.png`
- `research/results/ux-qa/cockpit-kiosk-uxc-011-all-scenarios.json/cockpit-ux-qa.json`
- `research/results/ux-qa/cockpit-kiosk-uxc-011-all-scenarios.json/kiosk-1280-outage-shell.png`
- `research/results/ux-qa/cockpit-kiosk-uxc-011-soak.json`
- `research/results/ux-qa/cockpit-kiosk-uxc-011-soak.png`

Visual Review Note

- The browser QA detected the real current backend scenario as no-actionable during the initial normal request. The submit-gate checker was corrected to treat a hidden/locked submit gate as safe only for safety scenarios, then all-scenario browser QA passed.
- The full 8-hour physical Pi soak remains a hardware-only verification item. The repo now has static, browser, and short-soak guardrails so that the eventual Pi session starts from a controlled state.
