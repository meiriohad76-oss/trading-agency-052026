# UXC-010 Settings And Preferences QA

Date: 2026-06-01

Ticket: UXC-010 - Settings And Preferences

Definition Of Done

- Preferences include color preset, theme, and density controls: PASS
- Preferences survive reload across desktop, kiosk, and mobile browser checks: PASS
- A/C variation switch is not exposed as an operator control: PASS
- Scenario selector remains QA-only and is not part of the normal settings panel: PASS
- Settings entry point is a normal cockpit control, not a floating prototype tweaks card: PASS
- No `EDITMODE` production marker was introduced: PASS

Implementation Evidence

- `scripts/check_cockpit_ux_qa.py` now supports `--focus preferences`.
- The preferences browser check opens the cockpit settings panel, changes the color preset, theme, and density, reloads the page, and verifies the persisted shell attributes.
- `tests/unit/test_cockpit_ux_qa_script.py` covers the preferences-focus branch so the browser QA contract does not silently regress.

Verification

- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_preferences.py tests\unit\test_cockpit_ux_qa_script.py tests\unit\test_cockpit_views.py -q` -> 35 passed
- `.\.venv\Scripts\python scripts\check_ux_preservation.py --group all` -> pass
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_preferences.py tests\unit\test_cockpit_ux_qa_script.py tests\unit\test_cockpit_views.py tests\unit\test_cockpit_routes.py tests\unit\test_fastapi_app.py -q` -> 274 passed
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --focus preferences --output research\results\ux-qa\cockpit-preferences-uxc-010.json` -> failure_count=0

Browser QA Artifacts

- `research/results/ux-qa/cockpit-preferences-uxc-010.json/cockpit-ux-qa.json`
- `research/results/ux-qa/cockpit-preferences-uxc-010.json/desktop-1920-normal-preferences.png`
- `research/results/ux-qa/cockpit-preferences-uxc-010.json/desktop-1366-normal-preferences.png`
- `research/results/ux-qa/cockpit-preferences-uxc-010.json/kiosk-1280-normal-preferences.png`
- `research/results/ux-qa/cockpit-preferences-uxc-010.json/mobile-390-normal-preferences.png`

Visual Review Note

- The preferences control path keeps the production cockpit shell and validates persistence through real browser storage instead of relying on a static fixture.
- The temporary QA server on port `8017` was stopped after browser verification.
