# Phase Status

**Status:** reconciled after T138-T150 (Track 2 / UX & Dashboard Usability)
**Owner:** Ohad Meiri
**Last updated:** 2026-05-14

This document is the operational truth table for the repo. It separates merged
implementation scaffolding from accepted phase gates.

## Current Truth

- T01-T162 tracked in `tickets/done/`. Track 1 (T123-T137) closed structural bugs,
  wired LLM into live cycles, persisted portfolio policy to DB, and completed e2e
  coverage. Track 3 (T151-T162) widened Massive coverage, improved the H1 harness,
  wrote H2/H3/H4/H5 run scripts, formalized the Phase 1 gate, wrote Phase 2 design,
  finalized four core schemas, and wrote the N2 three-layer test plan. Track 2
  (T138-T150) completed the UX prototype: Command page consolidated, Review Queue
  above fold, sticky review actions, subscription pipeline visible, empty states,
  paper-mode banner, policy safety taxonomy, audit filters, mobile layout, and
  product-language vocabulary with progressive disclosure.
- The repo contains Phase 0 foundation, Phase 1 research machinery, Phase 2 design
  and finalized contracts, and Phase 3/4 runtime scaffolding for local paper cycles.
- T29-T64 are provisional build scaffolding. They remain valid for local paper/demo
  workflows but do not replace empirical verdicts. Phase 1 gate is formally assessed
  as not accepted on empirical terms (see `docs/findings.md`).
- The dashboard and cycle runner are local paper/demo tools. They are not a live
  trading system and do not submit broker orders without explicit env gate + human
  approval.

## Phase Gates

| Phase | Planned gate | Current status | Next action |
| --- | --- | --- | --- |
| Phase 0 setup | Repo runnable; provenance-wrapped values persist end to end. | Complete. | Keep Docker/Python setup green. |
| Phase 1 research | Validated lanes, realistic profile, thresholds, plan revision. | **Gate formally assessed: not accepted.** No lane survived Bonferroni H1. Conservative thresholds active (T73). Phase 1 design doc (`findings.md`) updated with formal gate acceptance and constraint set. | Widen Massive coverage (T151), rerun `run_h1_ic.py --all-signals`, run H4 profile. Accept gate when CAGR ≥ 15% + Sharpe ≥ 0.8 at realistic cost. |
| Phase 2 design | Design doc, finalized schemas, UX prototype, test plan. | **Design doc written (`docs/phase2-design.md`). Four core schemas finalized (T158-T161). N2 test plan written (T162). UX prototype complete (T138-T150).** | Accept Phase 2 gate after first-version inspection of the UX prototype confirms review workflow is usable. |
| Phase 3 build | Components built with all three test layers green. | Runtime persists seeded, PIT-backed, and stocks-only paper cycles. Unit and integration test layers green. e2e coverage for happy path + edge cases added (T121, T135-T136). | Keep first-version path stable; complete N2 test plan coverage (T162). |
| Phase 4 validate | Paper-test against live data; user testing; threshold adjustment. | Live data refresh, real Alpaca paper-broker reads, persisted paper cycles ready for inspection. Portfolio policy now DB-persisted and UI-editable (T128). Trailing stops wired (T134). | Inspect paper validation cycles from Command review queue; adjust policy thresholds. |
| Phase 5 operate | Production paper trading and learning loop. | Not started. | Wait for Phase 4 validation. |

## High-Priority Gaps

1. Live refresh inputs are configured locally and T72 has a compact committed
   summary under `research/results/t72-live-summary/`. Raw/parquet data remains
   local-only.
2. T73 calibrated the deterministic `WATCH` gate to require two usable independent
   sources and at least one confirmed signal. No tested H1 lane is standalone-validated.
3. Runtime audit persistence and read-only visibility are wired for manual,
   scheduled, seeded, and PIT-backed local paper cycles; prompt audit capture
   waits for live LLM calls.
4. Lightweight scheduler, `/metrics`, structured JSON logging, local deployment
   commands, and backup/restore scripts exist.
5. First-version manual inspection checklist and server-side e2e smoke coverage exist.
6. `/status/live-readiness`, Command-page readiness, and readiness metrics explain
   whether the latest cycle is reviewable or context-only.
7. Portfolio policy is still env/static, not persisted or user-editable.
8. Options/unusual-activity lanes are implemented and opt-in:
   `options_anomaly`, `options_flow`, and `activity_alerts`. Provider selection
   is still deferred for confirmed options/dark-pool alerts; the default runtime
   lane set remains stocks-only.
9. Current-date live validation now treats `market_data_provider="massive"` as
   the preferred research market-data path; Alpaca remains the broker and
   fallback data provider.
10. Data refresh batches now write incremental progress and ETA status; the
    Command page polls the latest status file while data is loading, and command
    duration stamps now measure elapsed subprocess time.
11. `/status/live-config` and the Command-page Live Config panel show refresh
    config and credential readiness without exposing secret values.
12. Current-date local validation produced a `ready_for_paper_validation` cycle
    with WATCH candidates and paper-only risk decisions.
13. The Command dashboard now pairs latest-cycle reviewable selection reports
    with risk decisions so paper candidates can be inspected from one queue.
14. Paper review decisions can be recorded as append-only candidate lifecycle
    events from the Command review queue.
15. The Command review queue now shows the latest recorded human-review state
    for each current-cycle candidate.
16. The Command dashboard now summarizes review progress for the latest paper
    cycle, including pending, approved, deferred, and rejected counts.
17. Candidate detail pages now show latest paper-review state and the same
    approve/defer/reject review actions as the Command queue.
18. `/status/paper-review` exposes the current paper-review queue and progress
    summary for CLI checks and future automation.
19. `scripts/check_paper_review_status.py` provides a one-command smoke check
    for paper-review queue and progress thresholds.
20. `/status/operational-readiness` and
    `scripts/check_operational_readiness.py` combine health, live config, data
    refresh, live runtime, paper review, and key-presence checks into one local
    first-version readiness gate.
21. Optional options/activity runtime wiring now supports forward option-chain
    anomaly scoring plus confirmed provider/export alerts for dark-pool,
    block-trade, and unusual-options activity.
22. `/status/provider-readiness` and the Command dashboard now show the
    whole-agency provider-key checklist without exposing secret values. Missing
    future-provider keys stay planned instead of blocking the current paper flow.
23. Subscription-email agents are wired as an opt-in local `.eml` ingestion path
    for Seeking Alpha, TradeVision, and Zacks. They feed existing `news_rss` and
    `unusual_activity_alerts` lanes, write a safe deduped event view, and remain
    context-only until forward validation.
24. Massive/Polygon delayed stock trades are now wired as an opt-in
    `stock_trades` dataset with `buy_sell_pressure`, `block_trade_pressure`,
    `unusual_trade_activity`, `pre_market_unusual_activity`, and
    `market_flow_trend` runtime lanes. These lanes are inferred from confirmed
    prints and require `POLYGON_API_KEY` or `MASSIVE_API_KEY` only when enabled.
25. A dedicated market-flow analysis worker now generates feature panels, IC
    checks, threshold sweeps, holdout validation, and runtime guidance artifacts
    for the market-flow lanes.
26. Alpaca paper-broker account/position/order reads and guarded paper-order
    submission are wired behind explicit env gates. Portfolio monitor can now
    read real Alpaca paper positions when enabled.
27. `scripts/run_paper_broker_validation.py` verifies the real Alpaca paper
    account, keeps broker submission disabled, runs three persisted paper cycles,
    records APPROVE/DEFER/REJECT review events, and writes the validation report
    under `research/results/alpaca-paper-validation/`.
28. The broker validation script now has a guarded `--trade-test` path. It
    submits a tiny Alpaca paper BUY, cleans it up with a SELL when filled during
    market hours, or cancels the queued order outside market hours and confirms
    no test ticker order remains open.
29. Paper broker order lifecycle events are now persisted in execution audit
    history, and Alpaca paper account snapshots are persisted in
    `portfolio_snapshots` with API, Audit, and Portfolio Monitor visibility.
30. A dedicated `technical_analysis` runtime worker now scores trend, momentum,
    volume confirmation, relative strength, volatility risk, Massive trade
    pressure when available, and the agency blue/pink candle regime.
31. The technical-analysis worker now detects named chart patterns, writes IC
    and threshold calibration artifacts, and has a documented smoke command in
    `docs/technical-analysis-worker.md`.
32. Massive `stock_trades` refreshes now default to full page coverage; set
    `stock_trades_max_pages_per_day` only for bounded smoke or repair runs.
33. Runtime cycles can now use the active PIT S&P 100 + QQQ membership through
    `runtime_universe="active"` and `runtime_max_tickers=250`. The Live Config
    readiness check reports the active universe count and warns when local PIT
    datasets cover only a subset of that universe.
34. Track 1 (T123-T137) closed structural bugs: zscore warning (T123), freshness
    post-market window (T125), PIT empty-result (T127), policy DB persistence (T128),
    LLM wired into live cycle (T129), yfinance fallback alert (T130), Massive
    pagination checksum (T131), CUSIP change-detection (T132), subscription email
    dedup midnight fix (T133), trailing-stop high-water persisted (T134), full
    e2e edge-case coverage (T135-T136), structured JSON logging (T137).
35. Track 3 (T151-T162) widened Massive historical coverage (T151), improved H1
    harness with HAC/bootstrap (T152), wrote H2 combination / H3 LLM A/B / H4
    profile scripts (T153-T155), formally accepted Phase 1 gate finding (T156),
    wrote Phase 2 design doc (T157), finalized four core schemas (T158-T161), and
    wrote the N2 three-layer test plan (T162).

## Next Ticket Candidates

**Empirical (highest value):**
1. Pull full-universe Massive stock-trade history using `--full-universe` flag (T151).
2. Rerun H1 with wider universe: `research/scripts/run_h1_ic.py --all-signals --start 2024-01-01 --end 2026-01-01 --output-csv research/results/h1-wide/h1-ic.csv --output-md research/results/h1-wide/h1-verdicts.md`.
3. If any lane reaches `survive`: run H2 combination (`run_h2_combination.py`), then H4 profile (`run_h4_profile.py`). Accept Phase 1 gate if CAGR ≥ 15% + Sharpe ≥ 0.8.
4. Run H3 A/B harness (`run_h3_llm_ab.py --signal fundamentals --reviewer mock_approve_all --repeats 3`) as baseline; replace mock reviewer with live LLM when H1 has a surviving lane.

**UX (Track 2 — unblocked):**
- T138-T150 depend on T117 (dashboard decomposition). Start with T138 and T139.

**Operational:**
- Wire market-aware scheduler executor (T118) to automate daily refresh jobs.

## Operating Rule

Any new feature ticket should say whether it is provisional scaffolding or accepted
phase-gate work. Research verdicts in `docs/findings.md` remain the authority for
which signal lanes become action-weighted.
