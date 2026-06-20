# UXC-012 Legacy Dashboard Reconciliation QA

Date: 2026-06-01

Ticket: UXC-012 - Legacy Dashboard Reconciliation

Definition Of Done

- `/` sends the operator to `/cockpit`, not to Command, Final Selection, or Execution Preview: PASS
- Brand navigation points to `/cockpit`: PASS
- Legacy dashboards remain reachable as diagnostics: PASS
- Sidebar and global phase rail label legacy routes as diagnostic surfaces, not the primary workflow: PASS
- Old operator-visible copy such as `Command dashboard`, `Open signal dashboard`, `Selection blocked`, and `No concrete evidence line` is removed from cockpit and core operator templates: PASS
- Shared data-health copy says page/diagnostic page instead of implying every route is the primary dashboard: PASS
- Recent signal/fundamentals explainability and candidate evidence contracts remain protected by the preservation harness: PASS

Implementation Evidence

- `src/agency/dashboard.py` now redirects `/` directly to `/cockpit` and removes the obsolete root action router.
- `src/agency/templates/base.html` now makes the brand link target `/cockpit`, updates the build marker to `ux-v3-cockpit-primary-20260601`, and labels legacy routes as diagnostics.
- `src/agency/templates/cockpit.html`, `candidate_detail.html`, `execution_preview.html`, and `dashboard.html` remove old dashboard-primary wording and unclear blocked copy.
- `src/agency/views/_shared.py`, `views/command.py`, and `views/cockpit.py` align data-health/evidence fallback copy with the cockpit-primary model.
- `tests/unit/test_cockpit_legacy_reconciliation.py` adds a regression guard for root navigation, diagnostic route labels, and old dashboard copy.

Verification

- `.\.venv\Scripts\python -m ruff check src\agency\dashboard.py src\agency\views\_shared.py src\agency\views\command.py src\agency\views\cockpit.py tests\unit\test_cockpit_legacy_reconciliation.py tests\unit\test_cockpit_routes.py tests\unit\test_cockpit_views.py tests\unit\test_v3_ux_rollout.py tests\unit\test_ux_product_audit_20260529.py` -> passed
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_legacy_reconciliation.py tests\unit\test_cockpit_routes.py tests\unit\test_cockpit_views.py tests\unit\test_cockpit_candidates.py tests\unit\test_v3_ux_rollout.py tests\unit\test_ux_product_audit_20260529.py tests\unit\test_ux_audit_implementation.py -q` -> 138 passed
- `.\.venv\Scripts\python scripts\check_ux_preservation.py --group all` -> pass
- `.\.venv\Scripts\python -m pytest tests\unit\test_cockpit_legacy_reconciliation.py tests\unit\test_cockpit_routes.py tests\unit\test_cockpit_views.py tests\unit\test_cockpit_candidates.py tests\unit\test_v3_ux_rollout.py tests\unit\test_ux_product_audit_20260529.py tests\unit\test_ux_audit_implementation.py tests\unit\test_fastapi_app.py tests\unit\test_ops_scripts.py -q` -> 434 passed
- `/` redirect smoke on temp server -> HTTP 303 Location `/cockpit`
- `.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8017/cockpit --focus shell --output research\results\ux-qa\cockpit-legacy-reconciliation-uxc-012.json` -> failure_count=0
- Route smoke for `/cockpit` and `/command` -> 200 OK, no old dashboard copy found

Browser QA Artifacts

- `research/results/ux-qa/cockpit-legacy-reconciliation-uxc-012.json/cockpit-ux-qa.json`
- `research/results/ux-qa/cockpit-legacy-reconciliation-uxc-012.json/desktop-1920-normal-shell.png`
- `research/results/ux-qa/cockpit-legacy-reconciliation-uxc-012.json/kiosk-1280-normal-shell.png`
- `research/results/ux-qa/cockpit-legacy-reconciliation-uxc-012.json/mobile-390-normal-shell.png`

Residual Note

- `scripts/check_local_runtime.py` was not used as the UXC-012 acceptance gate because the temp server returned 503 for `/reports/selection`; that endpoint depends on live runtime data availability, not on legacy-dashboard reconciliation. Direct route smoke and cockpit browser QA passed.
