# Cockpit Visual Fidelity Audit - 2026-06-01

## Scope

Ticket: UXC-002 - Variation A Visual Shell Parity

Reference:

- `ux upgrade claude design 01062026/.scratch/verify-a.png`
- `ux upgrade claude design 01062026/Variation A.html`
- `ux upgrade claude design 01062026/cockpit/cockpit.css`

Production screenshot artifacts:

- `research/results/ux-redesign-v3-qa/latest/desktop-1920-normal-shell-top-v2.png`
- `research/results/ux-redesign-v3-qa/latest/desktop-1920-normal-shell.png`
- `research/results/ux-redesign-v3-qa/latest/kiosk-1280-normal-shell.png`
- `research/results/ux-redesign-v3-qa/latest/mobile-390-normal-shell.png`

## Implemented Similarity

- `/cockpit` now uses a full-width, centered 1440px Variation A artboard on a
  black stage, instead of the legacy sidebar/topbar shell.
- The production shell declares `class="cockpit-shell vA"` and
  `data-ux-variation="variation-a-preflight"`.
- Core prototype anchors are present:
  `topline`, `datastate`, `cluster`, `engines`, `instruments`, `phaserail`,
  `candidates`.
- The cockpit color tokens match the frozen package roles:
  amber `#ffb845`, cyan `#5ad7f0`, green `#5fe49d`, red `#ff6868`.
- Numbers remain monospaced.
- The cockpit phase rail now uses numbered phase cells like the prototype.
- The old displayed-data-health dashboard panel was removed from the primary
  cockpit surface. Data-state proof remains in the cockpit strip and Universe
  panel lane board.

## Accepted Production Deltas

- The production cockpit keeps an explicit BLUF/header because the agency product
  rule says every primary operator screen starts with a bottom-line statement.
- Email login alerts can appear above the instrument cluster because they are a
  live operator action, not demo content.
- Data-state proof is shown more prominently than in the prototype because the
  agency must prove loading/analysis/freshness state before review.
- The frozen prototype uses static mock data and React/Babel CDNs. Production uses
  FastAPI/Jinja and real backend data only.
- The captured `Variation A.html` did not render in this environment due its CDN
  prototype dependencies, so `.scratch/verify-a.png` was used as the stable visual
  reference.

## Verification

- `scripts/check_cockpit_ux_qa.py` passed for desktop 1920, desktop 1366,
  kiosk 1280, and mobile 390.
- No console errors, page errors, horizontal overflow, unreadable controls, or
  unsafe submit gate behavior were reported.
- Preservation harness passed after the visual changes.
