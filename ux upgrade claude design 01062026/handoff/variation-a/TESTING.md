# Variation A — Testing

How to verify the Pre-Flight Cockpit. Test cases are referenced by ID from `TICKETS.md`. The pass bar for each epic is the checklist in `DEFINITION-OF-DONE.md`.

---

## 1. Strategy

| Layer | Tooling (recommended) | What it covers |
|---|---|---|
| **Unit** | Vitest + React Testing Library | hooks, primitives, pure derivations (P/L, gross-post-trade, phrase match) |
| **Component / interaction** | Vitest + RTL (or Playwright component) | decisions, gate logic, phase nav, panel open/close |
| **Scenario / visual** | Playwright (full-page) against `?scenario=` URLs | the four scenarios × phases render correctly |
| **Visual regression** | Playwright screenshots vs the frozen prototype | pixel parity at 1920×1080 |
| **Pi / system** | manual on-device checklist | offline load, touch, kiosk autostart, performance budget |

The frozen `src/Variation A.html` is the **visual oracle** — diff against it, not against memory.

## 2. Test environments

- **Dev:** Chromium desktop at 1920×1080 (kiosk target). Verify scale-to-fit also at 1280×720 (readability borderline — see `../09-raspberry-pi.md`).
- **Pi:** the actual target (Pi 4/5, Chromium kiosk, touch if applicable). E4 tests must run here, not just on desktop.

---

## 3. Unit & primitive tests

| ID | Target | Assert |
|---|---|---|
| **VA-T-001** | `useCockpitCountdown` | counts down per second; at 0 loops to 13:00; clears its interval on unmount (no leak). |
| **VA-T-002** | `useAnimatedValue` | eases 0→target over duration (ease-out cubic); re-fires when deps change; lands exactly on target. |
| **VA-T-003** | `CockpitOverlay` | opens/closes on the `open` prop; Esc closes; click-outside closes; click-inside doesn't; backdrop blur present; restores focus. |
| **VA-T-004** | `ArcGauge` | value 0→1 maps needle −90°→+90°; out-of-range clamps; zones render in order; animates once on mount. |
| **VA-T-021** | derivations | P/L = (current−entry)/entry; stop-dist from current/stop; `grossPostTrade` recomputes from staged approvals — all UI-side, none read from payload. |

## 4. Component / interaction tests

| ID | Scenario | Steps → expected |
|---|---|---|
| **VA-T-005** | Cluster | gauges read the documented values/zones; each has a `WhyMark`; "Ready to Trade" = approved count. |
| **VA-T-006** | Phase rail | active cell = amber underline + glow; done = green check; locked = `◌`+"LOCKED" at 42% opacity. |
| **VA-T-007** | Candidate table | rows sorted by `finalConviction` desc; chips colour-correct; non-actionable rows greyed with `audit ›`. |
| **VA-T-008** | Portfolio | 5 rows; setup tags coloured; capacity bars correct; cash bar uses floor inversion; heads-up shows when tight. |
| **VA-T-009** | Clearance static | manifest lists buys; exits-first only when closes staged; gate CLOSED/red by default; submit "Locked". |
| **VA-T-010** | Full assembly | phase-1 `normal` matches prototype; changing `phase` prop swaps content; stable at 1920×1080. |
| **VA-T-011** | Approve | click Approve → chip "YOU APPROVED" green, SegDisplay +1, Gauge updates, Advance enabled; reversible. |
| **VA-T-012** | Non-actionable guard | Approve/Defer/Reject absent on blocked/demoted/rejected rows; row-expand doesn't trigger a decision. |
| **VA-T-013** | Gate arm | arm checkbox flips dot red→green and enables the phrase input. |
| **VA-T-014** | Phrase + submit | wrong phrase → submit stays Locked; `submit paper orders` (any case/extra spaces) → submit glows green and is clickable; 0 approvals → still Locked. |
| **VA-T-015** | Phase nav | can't advance past portfolio with an undecided non-HOLD position; Back preserves decisions; exits flow to manifest. |
| **VA-T-016** | Panels open/close | all six open from nav (+TickerDetail from ticker click), render correct data, close on Esc/outside/Close. |
| **VA-T-017** | State preserved | opening/closing a panel doesn't reset phase or decisions. |
| **VA-T-019** | Settings | color/theme/density change live and match presets; no floating draggable card; A/C switch not exposed. |

## 5. Scenario / visual-state tests

Drive these via `?scenario=` (VA-205). Each is a full-page screenshot diff against the prototype.

| ID | Scenario / view | Expected (per `../06-states.md`) |
|---|---|---|
| **VA-T-301** | `normal` · phase 1 candidates | full cockpit, ranked table |
| **VA-T-302** | `normal` · phase 2 portfolio | positions + capacity check |
| **VA-T-303** | `normal` · phase 3 clearance (gate closed → armed → phrase ok) | three sub-states render |
| **VA-T-304** | `normal` · phase 4 / submitted | green-ring success, order cards, total |
| **VA-T-305a** | `no-actionable` | cluster/engines/nav/rail kept; skip-to-portfolio view + 3 near-miss cards + agent note |
| **VA-T-305b** | `outage` | only topbar; red banner; two OFFLINE engine cards; retry countdown; **no blink/siren/shake** |
| **VA-T-305c** | `submitted` (entry state) | post-clearance success view |
| **VA-T-018** | scenario param round-trip | `?scenario=outage` loads outage directly; debug toggle matches |

## 6. Backend integration tests (E3)

| ID | Target | Assert |
|---|---|---|
| **VA-T-020** | snapshot fetch | cockpit renders from `GET /api/cockpit`; loading + error states (no white screen); empty payload handled. |
| **VA-T-022** | submit success | `POST /api/decisions` → Phase 4 with **broker-returned** order IDs; double-submit guarded. |
| **VA-T-023** | submit failure | API error → inline error in gate panel + retry; gate stays armed; no phantom transition. |
| **VA-T-024** | monitor SSE | events append live; reconnect on drop; filters work; stream closes with the panel. |
| **VA-T-025** | policy write | edits show diff vs deployed; confirm PUTs; `LIVE_TRADING` stays locked; cancel discards. |
| **VA-T-026** | audit on demand | `audit ›` on any non-actionable ticker fetches + renders its trace; loading/not-found handled. |

## 7. Pi / system tests (E4) — run on the device

| ID | Target | Pass condition |
|---|---|---|
| **VA-T-401** | Offline load | with network disabled, `/dist` loads fully; **zero** external requests; fonts from `/fonts/`. |
| **VA-T-402** | Touch | every decision/keep-close/submit/nav target ≥ 44px; tips on ~300ms long-press; no click delay; no pinch-zoom. |
| **VA-T-403** | Persistence/restore | reload mid-session → restore prompt rehydrates decisions/exits; new cycle clears them; gate reopens closed, phrase empty. |
| **VA-T-404** | Kiosk | Pi boots into cockpit; browser-kill auto-restarts + restores; screen never sleeps; cursor auto-hides. |
| **VA-T-405** | Performance budget | cold-start < 3s; idle CPU < 5%; memory < 200MB after 8h; gauge/needle animations ≥ 30fps (target 60). |

## 8. The QA matrix

Per `../06-states.md`: 10 visual states × density (full/calm) × color (amber/duotone/saturated) × theme (dark/accent/light). Full cartesian = 162 — **don't** brute-force all. Required coverage:

- **All 10 visual states** at the default combo (amber / accent / full).
- **Each density** (full + calm) at one representative phase + one scenario.
- **Each theme** (dark / accent / light) at phase 1 — light theme is the inversion risk; verify status colours still read.
- **Each color preset** at phase 1.
- **Spot-check** 6–8 random off-default compositions for layout breakage.

Record results in `DEFINITION-OF-DONE.md → QA matrix sign-off`.

## 9. Regression guard

Before any "done" call: re-run VA-T-301…305 screenshot diffs against the frozen `src/Variation A.html`. Visual drift from the prototype is a defect unless it's an intentional, documented real-product delta (touch sizing, font swap).
