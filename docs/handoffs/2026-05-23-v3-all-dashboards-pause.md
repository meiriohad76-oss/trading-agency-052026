# V3 All-Dashboards Handoff - Pause

Captured: 2026-05-23 13:18:42 +03:00

## Honest Status

The user is correct: the previous V3 implementation did not fully implement the expert V3 UX across all dashboards. It implemented a real V3 `/cockpit`, then added a shared V3 shell/marker and partial route styling to legacy dashboard pages. That made Cockpit visibly different, but most other pages still felt like the pre-V3 product.

This handoff is mid-fix. Do not claim V3 is complete from this checkpoint.

## Branch And Repo State

- Repo: `C:\Users\meiri\trading_agency`
- Branch: `feat/ux-redesign-v3-cockpit`
- Branch state: ahead of `origin/feat/ux-redesign-v3-cockpit` by 3 commits.
- Worktree: dirty, with in-progress V3 all-dashboard changes.
- No commit was made for the in-progress changes in this pause.

## Changes Made In This Pause Session

Added failing regression coverage first, then implemented the first broad V3 all-dashboard shell pass:

- `tests/unit/test_v3_ux_rollout.py`
  - Added checks that non-cockpit dashboards declare a V3 identity and explicit briefing blocks.
  - Added checks for a visible universal V3 briefing strip in `base.html`.
  - Updated expected static cache key to `ux-v3-all-dashboards-20260523`.
- `src/agency/templates/base.html`
  - Changed cache/build marker to `ux-v3-all-dashboards-20260523`.
  - Added body class `v3-screen-...`.
  - Added a visible universal briefing strip with BLUF, Operator move, and Evidence cards.
  - Updated visible UX marker to `UX V3 · Pre-Flight Dashboards · 2026-05-23`.
- Route templates now declare `v3_screen`, `workflow_phase`, `operator_focus`, and `evidence_contract` blocks:
  - `audit.html`
  - `candidate_detail.html`
  - `dashboard.html`
  - `execution_preview.html`
  - `final_selection.html`
  - `learning.html`
  - `market_regime.html`
  - `policy.html`
  - `portfolio_monitor.html`
  - `risk.html`
  - `signals.html`
- `src/agency/static/v3-screens.css`
  - Expanded from a thin shell override into a broader product-wide V3 treatment.
  - Added shared V3 variables matching the prototype palette.
  - Added universal briefing strip styling.
  - Strengthened cards, tables, KPIs, evidence rows, tags, provenance strips, action controls, and responsive behavior.

## Verification Run

Command:

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_v3_ux_rollout.py -q
```

Result:

```text
11 passed in 1.10s
```

This verifies template/static contract only. It does not prove the live browser pages now look good.

## Current Dirty Files

```text
M src/agency/static/v3-screens.css
M src/agency/templates/audit.html
M src/agency/templates/base.html
M src/agency/templates/candidate_detail.html
M src/agency/templates/dashboard.html
M src/agency/templates/execution_preview.html
M src/agency/templates/final_selection.html
M src/agency/templates/learning.html
M src/agency/templates/market_regime.html
M src/agency/templates/policy.html
M src/agency/templates/portfolio_monitor.html
M src/agency/templates/risk.html
M src/agency/templates/signals.html
M tests/unit/test_v3_ux_rollout.py
```

Diff stat:

```text
14 files changed, 462 insertions(+), 25 deletions(-)
```

## Root Cause Of The User-Visible Failure

The previous implementation treated `/cockpit` as the full V3 product surface and treated the other dashboards as legacy pages inside a V3 shell. The regression tests allowed that by checking only for markers, page titles, data-health panels, and some common classes. They did not enforce that every dashboard had:

- a V3 screen identity,
- a visible BLUF/operator/evidence briefing,
- route-specific workflow copy,
- product-wide V3 visual treatment beyond the shell,
- browser proof that the page no longer visually resembles the pre-V3 dashboards.

That is why the user saw almost no difference outside Cockpit.

## Do Not Do Next

- Do not claim all dashboards are V3 complete yet.
- Do not commit until browser QA has been run and screenshots are inspected.
- Do not hide the old pages behind another marker-only change.
- Do not restart broad data pipelines as part of this UX fix unless a QA script explicitly needs current route data.

## Resume Plan

1. Inspect the current dirty diff:

   ```powershell
   git diff -- src/agency/templates/base.html src/agency/static/v3-screens.css tests/unit/test_v3_ux_rollout.py
   git diff -- src/agency/templates
   ```

2. Run targeted regression again:

   ```powershell
   .\.venv\Scripts\python -m pytest tests\unit\test_v3_ux_rollout.py -q
   ```

3. Restart the guarded local server so the new cache key and template changes are served:

   ```powershell
   .\scripts\start_dev.ps1 -SkipMigrations
   ```

4. Run live dashboard QA:

   ```powershell
   .\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py --readiness-scope review-subset
   ```

5. Add a dedicated all-dashboard V3 visual QA script or extend the existing checker to assert:

   - every route returns `data-ux-build="ux-v3-all-dashboards-20260523"`,
   - every route shows `[data-v3-universal-briefing]`,
   - every route body has `v3-screen-*`,
   - no route has horizontal overflow,
   - no visible button/tag text is clipped,
   - screenshots for `/command`, `/final-selection`, `/execution-preview`, `/portfolio-monitor`, `/risk`, `/signals`, `/market-regime`, `/policy`, `/learning`, `/audit`, and `/candidates/NVDA` visibly differ from pre-V3.

6. Browser-check the pages manually or through Playwright screenshots before reporting back:

   - `http://127.0.0.1:8000/command?v=ux-v3-all-dashboards-20260523`
   - `http://127.0.0.1:8000/final-selection?v=ux-v3-all-dashboards-20260523`
   - `http://127.0.0.1:8000/execution-preview?v=ux-v3-all-dashboards-20260523`
   - `http://127.0.0.1:8000/portfolio-monitor?v=ux-v3-all-dashboards-20260523`
   - `http://127.0.0.1:8000/risk?v=ux-v3-all-dashboards-20260523`

7. If screenshots still look too legacy, continue with page-by-page V3 body reconstruction. Priority:

   1. `/command`
   2. `/final-selection`
   3. `/execution-preview`
   4. `/candidate/<ticker>`
   5. `/portfolio-monitor`
   6. `/risk`
   7. research/control/trust screens

8. After browser QA is green, run:

   ```powershell
   .\.venv\Scripts\python -m pytest tests\unit\test_v3_ux_rollout.py tests\unit\test_cockpit_routes.py tests\unit\test_fastapi_app.py -q
   .\.venv\Scripts\python -m ruff check tests\unit\test_v3_ux_rollout.py
   ```

9. Commit only after visual/browser QA and tests are green.

## Exact User Complaint To Honor On Resume

The user said:

> what i see is very far from the ux v3 design. i see no difference from the pre-v3 version. the only difference is the cockpit dashboard. all other dashboards looks exactly the same

The next response after resume must be evidence-based: either show screenshots/QA proof that non-cockpit dashboards changed, or say they are still not ready and continue fixing.

## Resume Completion Update

Captured after resume on 2026-05-23.

Implemented the all-dashboard V3 pass and verified it against live pages:

- Added a universal V3 briefing strip to non-cockpit dashboards.
- Added per-route V3 screen identity and BLUF/operator/evidence wording.
- Expanded `v3-screens.css` into a product-wide dashboard treatment.
- Strengthened `scripts/check_dashboard_live_data_qa.py` so it fails if live pages do not serve the all-dashboard V3 build, screen class, and briefing strip.
- Fixed the forbidden-term checker to use word boundaries so `demoted` no longer false-positives as `demo`.
- Reworded Learning evidence copy to avoid forbidden synthetic-data terms.
- Tightened candidate-detail score metadata layout after screenshot inspection.

Fresh verification:

```powershell
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py --readiness-scope review-subset
```

Result: `failure_count=0`

```powershell
.\.venv\Scripts\python scripts\check_cockpit_ux_qa.py --url http://127.0.0.1:8000/cockpit --focus panels --output research/results/ux-redesign-v3-qa/all-dashboards-20260523
```

Result: `failure_count=0`

```powershell
.\.venv\Scripts\python -m pytest tests\unit\test_v3_ux_rollout.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_cockpit_routes.py tests\unit\test_fastapi_app.py -q
```

Result: `209 passed, 3 warnings in 251.23s`

```powershell
.\.venv\Scripts\python -m ruff check scripts\check_dashboard_live_data_qa.py tests\unit\test_dashboard_live_data_qa_script.py tests\unit\test_v3_ux_rollout.py
git diff --check
```

Result: both passed.

Screenshots inspected:

- `research/results/latest-ui-live-data-qa/desktop-command.png`
- `research/results/latest-ui-live-data-qa/desktop-final-selection.png`
- `research/results/latest-ui-live-data-qa/desktop-execution-preview.png`
- `research/results/latest-ui-live-data-qa/desktop-candidates-NVDA.png`
- `research/results/latest-ui-live-data-qa/desktop-portfolio-monitor.png`
- `research/results/latest-ui-live-data-qa/desktop-risk.png`
- `research/results/latest-ui-live-data-qa/desktop-policy.png`
- `research/results/latest-ui-live-data-qa/mobile-command.png`

The non-cockpit dashboards are now visibly V3-styled in the generated screenshots. This does not mean every downstream trading/data readiness issue is solved; it means the UX V3 visibility failure was addressed and covered by live QA.
