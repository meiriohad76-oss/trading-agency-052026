# Operational Audit Start Handoff

Source audit: `AUDIT-REPORT-2026-05-27.md`

Branch/status:

```text
## main...origin/main [ahead 2]
 M schemas/risk-decision.schema.json
 M schemas/selection-report.schema.json
 M src/agency/api/health.py
 M src/agency/api/reports.py
 M src/agency/api/risk.py
 M src/agency/runtime/data_load_status.py
 M src/agency/runtime/lane_state.py
 M src/agency/static/cockpit.js
 M src/agency/static/data-refresh-progress.js
 M src/agency/static/v3-screens.css
 M src/agency/templates/_cockpit_panels.html
 M src/agency/templates/_data_health.html
 M src/agency/templates/dashboard.html
 M src/agency/templates/execution_preview.html
 M src/agency/views/_shared.py
 M src/agency/views/cockpit.py
 M src/agency/views/command.py
 M tests/unit/test_cockpit_candidates.py
 M tests/unit/test_cockpit_contract.py
 M tests/unit/test_cockpit_lane_state.py
 M tests/unit/test_cockpit_routes.py
 M tests/unit/test_data_load_status.py
 M tests/unit/test_fastapi_app.py
 M tests/unit/test_lane_state.py
 M tests/unit/test_reports_api.py
 M tests/unit/test_risk_api.py
 M tests/unit/test_ux_audit_implementation.py
?? AUDIT-REPORT-2026-05-27.md
?? docs/superpowers/plans/2026-05-27-operational-audit-remediation.md
```

Dirty diff summary:

```text
 schemas/risk-decision.schema.json           |  14 +-
 schemas/selection-report.schema.json        |  14 +-
 src/agency/api/health.py                    |  18 ++-
 src/agency/api/reports.py                   |  33 ++++-
 src/agency/api/risk.py                      |  33 ++++-
 src/agency/runtime/data_load_status.py      |  59 +++++++-
 src/agency/runtime/lane_state.py            |  33 ++++-
 src/agency/static/cockpit.js                |  37 ++++-
 src/agency/static/data-refresh-progress.js  | 114 +++++++++++++---
 src/agency/static/v3-screens.css            |   7 +-
 src/agency/templates/_cockpit_panels.html   |   5 +
 src/agency/templates/_data_health.html      |  11 ++
 src/agency/templates/dashboard.html         |  12 +-
 src/agency/templates/execution_preview.html |  22 +++
 src/agency/views/_shared.py                 |  79 ++++++++++-
 src/agency/views/cockpit.py                 | 195 +++++++++++++++++++++++---
 src/agency/views/command.py                 | 113 ++++++++++++++-
 tests/unit/test_cockpit_candidates.py       |  44 +++++-
 tests/unit/test_cockpit_contract.py         |   6 +-
 tests/unit/test_cockpit_lane_state.py       |  30 ++++
 tests/unit/test_cockpit_routes.py           |  83 +++++++++++
 tests/unit/test_data_load_status.py         | 205 ++++++++++++++++++++++++++++
 tests/unit/test_fastapi_app.py              | 182 ++++++++++++++++++++++++
 tests/unit/test_lane_state.py               |   5 +-
 tests/unit/test_reports_api.py              |   5 +-
 tests/unit/test_risk_api.py                 |   5 +-
 tests/unit/test_ux_audit_implementation.py  |  50 +++++++
 27 files changed, 1338 insertions(+), 76 deletions(-)
```

Execution rule: preserve dirty work; use `.\.venv\Scripts\python -m pytest`.

First implementation task: Task 1 crash guards.
