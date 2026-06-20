# Variation C — Testing

How to verify Mission Control. Test cases are referenced by ID from `TICKETS.md`. The pass bar per epic is the checklist in `DEFINITION-OF-DONE.md`.

---

## 1. Strategy

| Layer | Tooling (recommended) | Covers |
|---|---|---|
| **Unit** | Vitest + RTL | hooks, primitives, pure derivations (P/L, gross-post-trade, phrase match) |
| **Component / interaction** | Vitest + RTL / Playwright component | decisions, gate, keep/close, selection, panels |
| **Animation** | Playwright (trace + timing) | fly-to-manifest spawn/land/cleanup, auto-advance transitions |
| **Scenario / visual** | Playwright full-page vs `?scenario=` | four scenarios × column states |
| **Visual regression** | Playwright screenshots vs frozen prototype | pixel parity at 1920×1080 |
| **Pi / system** | manual on-device | offline load, touch, kiosk, performance |

`src/Variation C.html` is the **visual oracle** — diff against it.

## 2. Environments

- **Dev:** Chromium desktop 1920×1080; verify scale-to-fit at 1280×720 (the dense strip is the readability risk).
- **Pi:** the actual target. E4 tests run here.

---

## 3. Unit & primitive tests

| ID | Target | Assert |
|---|---|---|
| **VC-T-001** | `useCockpitCountdown` | per-second tick; loops at 0; clears interval on unmount. |
| **VC-T-002** | `useAnimatedValue` | ease-out cubic 0→target; re-fires on deps; lands on target. |
| **VC-T-003** | `CockpitOverlay scope="vC"` | open/close; Esc + click-outside; inherits `.vC` palette; backdrop blur. |
| **VC-T-024** | derivations | approval counters, gross-post-trade, mini-meters, P/L all UI-computed from staged state, not payload. |

## 4. Component / interaction tests

| ID | Scenario | Steps → expected |
|---|---|---|
| **VC-T-005** | Telemetry strip | brand/metrics/counters/nav grid matches; gross "67 → 84%" amber; counters reflect staged state; `telem-mid` carries the calm-hide attr. |
| **VC-T-007** | Candidates column | list sorted desc; `ConvictionBar` colours track thresholds; detail pane renders selected; CONF/INF badges; cyan rationale. |
| **VC-T-008** | Portfolio column | 5 rows; status tags coloured; mini-meters cur→post; 11-sector heatmap colours correct. |
| **VC-T-009** | Clearance column | manifest lists buys; exits-first only when closes staged; gate SAFE/CLOSED default; TRANSMIT shows count+total. |
| **VC-T-010** | Full assembly | `normal`/`full` matches prototype; Stage 01 active/bright, others full-opacity; stable at 1920×1080. |
| **VC-T-011** | Approve | Approve → manifest gains the row, Approved counter +1, gross telem + mini-meter update; reversible. |
| **VC-T-012** | Non-actionable guard | decision buttons absent on blocked/demoted/rejected; selecting them still updates the detail pane (read-only). |
| **VC-T-013** | Gate arm | open gate flips "○ SAFE"→"● ARMED" and enables the phrase input. |
| **VC-T-014** | Phrase + TRANSMIT | wrong phrase → TRANSMIT inert; correct (any case/spaces) + ≥1 approval → TRANSMIT active. |
| **VC-T-015** | Keep/close | keep/close on non-HOLD updates exits-first block + "To exit" counter; reversible; HOLD rows have no buttons. |
| **VC-T-016** | Selection | clicking any list row updates `CandidateDetailC`; survives scenario switch; defaults to top. |
| **VC-T-017** | Fly-to-manifest | chip spawns at click point, animates to manifest, no layout shift, node removed ≤750ms; rapid approvals don't leak nodes; reduced-motion → instant. |
| **VC-T-018** | Auto-advance | start Stage 01; first approval → Stage 02 (or 03 w/ exits); click-in activates a column; submit dims Candidates+Portfolio, Clearance bright. |
| **VC-T-019** | Panels open/close | all six (+TickerDetail) open with `.vC` palette, render data, scroll, close on Esc/outside/Close. |
| **VC-T-020** | State preserved | panel open/close doesn't reset stage/selection/decisions. |
| **VC-T-022** | Settings | color/theme/density live + match presets; calm hides telem-mid + footer engines + kills glows; no floating card; A/C not exposed. |

## 5. Scenario / visual-state tests

Drive via `?scenario=`. Full-page diffs vs prototype.

| ID | Scenario / view | Expected (per `../06-states.md` + `../04-variation-c.md`) |
|---|---|---|
| **VC-T-301** | `normal` · all three columns | telemetry + 3 columns + footer; Stage 01 active |
| **VC-T-302** | `normal` · after 1 approval | Stage 02 active; manifest + counters updated; fly-chip fired |
| **VC-T-303** | `normal` · gate armed + phrase ok | TRANSMIT active, total correct |
| **VC-T-304** | `submitted` | Candidates+Portfolio dimmed 42%; Clearance = `SubmittedPane` with order cards (no "Start over") |
| **VC-T-305a** | `no-actionable` | Stage 01 amber "NO ACTIONABLE" card + 3 near-miss cards; Portfolio still active; Stage 03 empty-manifest note (cyan) |
| **VC-T-305b** | `outage` | two-column (telemetry strip stays); red banner + engine telemetry table incl. healthy LIVE engines; **no blink/siren/shake** |
| **VC-T-021** | param round-trip | `?scenario=outage` loads outage directly |

## 6. Backend integration tests (E3)

| ID | Target | Assert |
|---|---|---|
| **VC-T-023** | snapshot fetch | renders from `GET /api/cockpit`; loading/error/empty handled. |
| **VC-T-025** | submit success | `POST /api/decisions` → `SubmittedPane` with **broker** IDs; columns dim; double-submit guarded. |
| **VC-T-026** | submit failure | error in gate + retry; ARMED preserved; no phantom transition. |
| **VC-T-027** | monitor SSE | live append; reconnect; filters; closes with panel. |
| **VC-T-028** | policy write | diff vs deployed; confirm PUTs; `LIVE_TRADING` locked; cancel discards. |
| **VC-T-029** | audit on demand | any ticker's `audit ›` fetches + renders; loading/not-found handled. |

## 7. Pi / system tests (E4) — on the device

| ID | Target | Pass condition |
|---|---|---|
| **VC-T-401** | Offline load | network disabled → loads fully; zero external requests; local fonts. |
| **VC-T-402** | Touch | all targets ≥ 44px incl. panel-nav letters; long-press tips; no click delay/zoom; strip still fits. |
| **VC-T-403** | Persistence/restore | reload → restore prompt rehydrates decisions/exits/selection; new cycle clears + clears submitted dim; gate reopens SAFE/empty. |
| **VC-T-404** | Kiosk | boots into cockpit; browser-kill restarts + restores; no screen sleep; cursor hides. |
| **VC-T-405** | Performance budget | cold-start < 3s; idle CPU < 5%; < 200MB after 8h; **fly-chip + conviction-bar animations ≥ 30fps (target 60)**; no node leak after 100 approvals. |

## 8. The QA matrix

Per `../06-states.md`: visual states × density (full/calm) × color (amber/duotone/saturated) × theme (dark/accent/light). Don't brute-force all. Required:

- **All scenario/column states** at amber/accent/full (VC-T-301…305).
- **Each density** (full + calm) — calm must hide telem-mid + footer engines and still be usable.
- **Each theme** at the normal three-column view — light theme is the inversion risk; status colours must still read on paper bg.
- **Each color preset** at the normal view.
- **Spot-check** 6–8 off-default compositions.
- **Animation under load:** 20 rapid approvals — fly-chips clean up, no leak, auto-advance correct.

Record in `DEFINITION-OF-DONE.md → QA matrix sign-off`.

## 9. Regression guard

Before any "done": re-run VC-T-301…305 diffs against frozen `src/Variation C.html`. Drift is a defect unless it's a documented real-product delta (touch sizing, font swap).
