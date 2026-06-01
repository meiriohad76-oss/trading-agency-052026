# Cockpit Contract Audit - 2026-06-01

## Purpose

This audit maps the expert UX package schema to the current agency backend so
the cockpit implementation can move quickly without rebuilding business logic in
the browser.

Reference schema:

- `ux upgrade claude design 01062026/handoff/07-data-schema.md`
- `ux upgrade claude design 01062026/Variation A.html`
- `ux upgrade claude design 01062026/cockpit/data.js`

Current backend entry points:

- `src/agency/views/cockpit.py::cockpit_context_from_sources`
- `src/agency/views/cockpit.py::safe_cockpit_api_payload`
- `GET /api/cockpit`
- `GET /api/cycle`
- `GET /api/cockpit/ticker/{ticker}`
- `GET /api/audit/{ticker}`
- `POST /cockpit/submit`

## Contract Summary

| Expert section | Current backend field | Current status | Implementation rule |
|---|---|---|---|
| `cycle` | `context["cycle"]` from `_cycle_section()` | Present | Use as cockpit topbar source. Add only real next-cycle timestamp later if needed. |
| `market` | `context["market"]` from `_market_section()` | Partial | Use current regime/readiness fields now; add missing gauge metrics without changing market-regime logic. |
| `engines` | `context["engines"]` from `_engine_rows()` | Present | Display as expert engine strip. Do not rename states into unclear "stale" copy. |
| `funnel` | `context["funnel"]` from `_funnel_section()` | Present | Use for BLUF and counts; candidate ordering remains backend final conviction. |
| `candidates` | `context["candidates"]` from `_candidate_rows()` | Present | Consume existing ranking, status, evidence, gates, LLM, and order-preview fields. Do not recompute ranking in UI. |
| `positions` | `context["positions"]` from `_position_rows()` | Present | Use for portfolio phase. Preserve portfolio manager exit-state meanings. |
| `account` | `context["account"]` from `_account_section()` | Present | Use for capacity gauges. Recompute staged exposure only from staged cockpit decisions. |
| `sectors` | `context["sectors"]` from `_sector_rows()` | Partial | Use for sector tags/heat. Missing sector reference must show reference-data status, not "sector not reported" as a dead end. |
| `sources` | `context["sources"]` from `_source_rows()` | Present | Use for Universe/Data Sources panel with tier, timestamp, coverage, and note. |
| `universeBlocked` | `context["universe_blocked"]` from `_universe_blocked_rows()` | Present | Keep as audit/debug detail; not first-screen noise unless it blocks operation. |
| `signals` | `context["signals"]` from `_signal_rows()` plus ticker detail evidence | Present | Must preserve concrete signal/fundamentals evidence text and tiers. |
| `auditLifecycle` | `context["audit_lifecycle"]` and `GET /api/audit/{ticker}` | Present | Use for per-ticker trace. Add richer lifecycle later without changing evidence hashes. |
| `policy` | `context["policy"]` from `_policy_section()` | Present | Display deployed vs staged policy. Keep `LIVE_TRADING` locked off. |
| `monitorEvents` | `context["monitor_events"]` from `_monitor_events()` | Poll fallback | Use polling now; SSE can be a later ticket. Show disconnected state clearly. |
| Session state | local cockpit state | Needs implementation | Persist staged decisions with restore prompt; never persist submit phrase/gate. |

## Protected Backend Fields

The cockpit must consume these fields as authoritative and may not replace them
with generic copy:

| Field family | Backend source | Why protected |
|---|---|---|
| Candidate rank/conviction | `_candidate_rows()` | Preserves final selection and paper-promotion logic. |
| Candidate `status_label`, `actionable`, `reviewable`, `order_reviewable` | `_candidate_rows()` | Prevents disabled/blocked UX from contradicting backend policy. |
| Evidence line/cards/tiers | `_evidence_items()`, `_compact_cards()`, `_compact_signals()` | Preserves recent signal explainability work. |
| Fundamentals evidence payload | `src/agency/runtime/signal_evidence.py` | Preserves SEC/PIT period alignment, trend, quality, forward-state, and meaning explanations. |
| TRF/off-exchange and unusual-trade evidence | `src/agency/runtime/signal_evidence.py` and market-flow features | Preserves venue, notional, threshold, timing, and pressure details. |
| Subscription thesis context | `research/src/signals/subscription_thesis.py` | Preserves analyzed article relevance, recency, source depth, and relevance weighting. |
| Data-state rows | `_data_state_section()` and `_data_state_lane_row()` | Preserves operator wording for loading, unavailable, unanalyzed, needs refresh, optional, ready. |
| Institutional actionability | `src/agency/services/actionability_gate.py` | 13F data remains context-only because of reporting delay. |

## Gaps To Close During Visual Implementation

| Gap | Impact | Ticket |
|---|---|---|
| Expert arc gauges expect more numeric market/account values than `/cockpit` currently exposes. | Some gauges may be visually present but less informative. | UXC-002 / UXC-005 |
| `monitorEvents` is a static/polled list, not SSE. | Monitor panel is useful but not truly live-streamed. | UXC-007 |
| Policy write semantics are read-heavy today. | Product can show values, but editing must be staged and explicit. | UXC-010 / later policy ticket |
| Staged decisions need explicit reload restore semantics. | Browser refresh could confuse approval state. | UXC-003 / UXC-006 |
| Visual token parity is not yet proven against the frozen HTML. | User may still see "old dashboard" feel. | UXC-002 |

## UXC-001 Done State

- Every expert top-level schema section is mapped to a current backend field or
  an explicit gap.
- Protected signal/fundamentals/ranking/data-state fields are marked as
  consume-only.
- The cockpit implementation can begin visual work without inventing a new
  business contract.
