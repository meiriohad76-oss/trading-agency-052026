# Phase 1 Findings

**Status:** Phase 1 gate formally accepted — no lane validated; conservative thresholds active
**Owner:** Ohad Meiri
**Last updated:** 2026-05-14

This document is the phase-gate record for the v2 research phase. It separates
implemented research machinery from empirical findings. Result files now exist for
T72 live refresh and T73 actionability calibration; H2-H5 remain pending.

T65 note: the repo has provisional Phase 2 and early Phase 3 implementation scaffolding
through T64. Those artifacts are useful for local paper/demo workflows, but they do not
replace the empirical verdicts required here.

---

## Evidence Inventory

| Area | Implemented artifact | Current evidence status |
| --- | --- | --- |
| PIT data access | `research/src/pit/loader.py` and scoped loader wrappers | Guarded by tests and PIT bypass check. |
| Free market data | yfinance daily bars, sector ETFs, options forward collector | Ready for refresh; historical options remain forward-only on free tier. |
| Official filings | SEC company facts, Form 4, 13F pullers | Ready for PIT-scoped lane evaluation. |
| Public web/RSS | RSS ingestion plus optional Scrapling adapter | Use only for public, forward-observed sources. No paid-sub scraping. |
| Signal lanes | Fundamentals, insider, institutional, sector, volume, pre/post, news, market-flow pressure, options anomaly/flow, activity alerts | First live H1 run is inconclusive for tested lanes; market-flow/options/activity lanes need provider or forward coverage. |
| Actionability gate | `src/agency/services/actionability_gate.py` | V1 rules enforce lane source counts, freshness, dedupe, and inferred corroboration. |
| Evaluation | H1 IC, H1 verdicts, walk-forward, profile, sweep, combination, LLM A/B | Reusable utilities implemented and unit-tested. |
| Data refresh batch | `research/scripts/run_data_refresh_batch.py` | Live refresh summary committed under `research/results/t72-live-summary/`; raw/parquet data remains local-only. |
| Research batch | `research/scripts/run_research_batch.py` | T73 live H1 artifacts committed under `research/results/t73-actionability-calibration/`. |

---

## H1: Individual Signal Lanes

| Lane | Source | Current verdict | Next action |
| --- | --- | --- | --- |
| Fundamentals | SEC company facts | Inconclusive; best 20d IC 0.0522, t 1.1058, Bonferroni p 1.0000 | Keep context-only until retest. |
| Insider | SEC Form 4 | Inconclusive; best 5d IC 0.0525, t 1.3829, Bonferroni p 1.0000 | Keep context-only until retest. |
| Institutional | SEC 13F | Inconclusive; best 5d IC 0.0163, t 0.4926, Bonferroni p 1.0000 | Keep context-only until retest. |
| Sector momentum | Sector ETF bars | Inconclusive; best 5d IC -0.0986, t -2.5095, Bonferroni p 0.1209 | Retest before considering inverse use. |
| Abnormal volume | Daily bars | Inconclusive; best 5d IC 0.1080, t 2.6284, Bonferroni p 0.0858 | Keep as corroborating context. |
| Pre/post | Extended-hours-capable source | Pending data coverage check | Keep context-only if free coverage is sparse. |
| News | RSS-forward corpus | Not evaluated in H1 output; insufficient ticker-tagged observations | Improve ticker tagging and accumulate held-out coverage. |
| Buy/sell pressure | Massive/Polygon delayed stock prints | Forward-only scaffold; inferred by tick/zero-tick direction | Pull `stock_trades`, accumulate coverage, and keep as corroborating context until H1 retest. |
| Block trade pressure | Massive/Polygon delayed stock prints | Forward-only scaffold; inferred from large/off-exchange prints | Use as market-flow context; confirmed provider dark-pool labels still belong in `activity_alerts`. |
| Unusual trade activity | Massive/Polygon delayed stock prints | Forward-only scaffold; inferred from activity spikes versus recent trade-print baselines | Keep as corroborating context until the market-flow worker validates holdout precision. |
| Pre-market unusual activity | Massive/Polygon delayed stock prints | Forward-only scaffold; inferred from pre-market volume/notional spikes | Use as early-session context only; avoid standalone action until historical coverage is tested. |
| Market-flow trend | Massive/Polygon delayed stock prints | Forward-only scaffold; inferred from short signed-pressure trend | Keep as low-weight context until H1 and market-flow calibration support higher runtime weight. |
| Technical analysis | Daily OHLCV plus optional Massive stock prints | Worker implemented; tiny AAPL/MSFT/NVDA smoke found only volume confirmation eligible | Keep as corroborating context until wider holdout and walk-forward runs improve. |
| Options anomaly/flow | yfinance forward chains | Forward-only preliminary; inferred from chain snapshots | Accumulate forward observations or buy historical options/trade data. |
| Activity alerts | Local paid/confirmed CSV import | Forward-only scaffold; no empirical verdict yet | Import provider block-trade, dark-pool, and unusual-options exports and run H1 once coverage exists. |

**Architecture implication:** no tested lane is research-validated as a standalone
action trigger. T73 therefore keeps the actionability bar conservative: deterministic
`WATCH` now requires at least two usable independent sources and one confirmed signal.

---

## H2: Deterministic Combination

The combination utility (`evaluation/combination.py`) derives positive weights from H1
information ratios and blends z-scored component lanes. The run script is
`research/scripts/run_h2_combination.py`.

**Current verdict:** pending empirical run. No H1 lane survived Bonferroni, so H2 is
a context-only experiment until a wider retest or explicit context-only acceptance.

**Decision rule:** run combination only after at least one H1 lane reaches `survive` or
`inverse_candidate` on the wider-coverage retest. Accept H2 only if the combined signal
improves mean IC over the best single lane with p_bonferroni ≤ 0.05.

---

## H3: LLM Review Contribution

The A/B harness (`evaluation/llm_ab.py`) wraps deterministic scores with a reviewer and
compares walk-forward profiles. The summary utility (`evaluation/h3_llm_comparison.py`)
reports Sharpe delta, CAGR delta, and drawdown delta. The run script is
`research/scripts/run_h3_llm_ab.py`.

The LLM reviewer is wired into the live cycle runner as of T129. The A/B harness can be
used with either a mock reviewer (for baseline comparison) or the live LLM reviewer.

**Current verdict:** pending empirical A/B runs.

**Decision rule:** keep the LLM in the selection path only if reviewed runs improve
Sharpe ≥ 0.05 and CAGR ≥ 0.0 without worsening drawdown beyond 2 pp across ≥ 3
repeats. Verdict `llm_survives` required; otherwise route the LLM to context-only
rationale generation.

---

## H4/H5: Realistic Profile And Sweep

The profile utility (`evaluation/profile.py`) runs a walk-forward with realistic costs
and reports CAGR, Sharpe, max drawdown, weekly target gap, and turnover. The sweep
utility (`evaluation/sweep.py`) iterates over parameter grids. Run scripts are
`research/scripts/run_h4_profile.py` (single profile) and
`research/scripts/run_walk_forward_sweep.py` (parameter sweep).

**Current verdict:** pending full historical walk-forward run.

**Next action:** run single-configuration profile (5d rebalance, 10 positions, 5 bps
round-trip, 2 bps slippage) as the baseline; then sweep step_size_days ∈ {1,5,21} and
max_positions ∈ {5,10,20} to identify robust regions. Require CAGR ≥ 15% and Sharpe
≥ 0.8 at realistic cost before raising runtime conviction thresholds.

---

## Formal Phase 1 Gate Acceptance

**Accepted:** 2026-05-14

### Gate criteria (from v2-plan §4)

| Criterion | Required | Achieved | Verdict |
| --- | --- | --- | --- |
| ≥ 1 signal lane survives Bonferroni-adjusted H1 | Yes | No (all inconclusive) | Not met |
| Realistic cost profile (H4) CAGR ≥ 15%, Sharpe ≥ 0.8 | Yes | Not run | Not met |
| Conservative thresholds active while gate is open | Yes | Yes (T73) | Met |
| All three test layers green for implemented paths | Yes | Unit ✅ / Integration ✅ / e2e partial | Partial |
| Evaluation machinery reusable and reproducible | Yes | Yes (T66, T152) | Met |

### Formal finding

No tested signal lane is research-validated as a standalone action trigger. The Phase 1
gate is **not accepted on empirical terms**. Implementation is complete and correct; the
gap is data coverage and observation count, not infrastructure quality.

### Accepted constraints carried forward

1. **No lane is action-weighted.** All inferred lanes remain `CONTEXT_ONLY` at runtime
   until a wider H1 retest (full S&P 100 universe, ≥ 12 months of stock-trade history)
   produces a surviving lane.
2. **Deterministic `WATCH` requires ≥ 2 usable independent sources and ≥ 1 confirmed
   signal.** This T73 threshold stays active.
3. **LLM review is wired but does not change the action gate.** LLM output is advisory
   until H3 A/B runs produce `llm_survives` verdict.
4. **Phase 2 design proceeds on provisional schemas.** The four core schemas
   (EvidencePack, SignalResult, SelectionReport, DataSourceHealth) are finalized in
   T158–T161 based on current production use and Phase 2 requirements.
5. **Phase 3/4 scaffolding is operational.** Paper cycles run, risk decisions persist,
   and Alpaca paper-broker reads work. These are not Phase 1 outputs; they are Phase 3
   scaffolding built ahead of gate.

### Next required empirical actions

1. Widen Massive stock-trade history to full S&P 100 universe (T151 unblocks this).
2. Rerun H1 with wider coverage: `run_h1_ic.py --all-signals --start 2024-01-01 --end 2026-01-01`.
3. If ≥ 1 lane survives: run H2 combination, H4 profile, H5 sweep.
4. If H4 meets CAGR ≥ 15% and Sharpe ≥ 0.8: accept Phase 1 gate and start Phase 2 design.

---

## Phase 2 Inputs

Phase 2 design (`docs/phase2-design.md`) is written based on provisional schemas and the
Phase 1 constraint set above. It specifies the LLM evaluation path, the schema contracts
shared between deterministic and LLM selection, and the three-layer test plan that must
be green before Phase 2 is accepted.

The finalized schemas are:

- **EvidencePack** — shared by deterministic and LLM selection; carries lane weights and
  evaluation method.
- **SignalResult** — standardized suppression reason codes; source tier and verification
  level enums locked.
- **SelectionReport** — trade plan, LLM review, policy gates, risk flags all present.
- **DataSourceHealth** — status and freshness enums locked; notes field carries
  per-dataset domain metadata (e.g. provider_fallback_active, next_expected_filing).

---

## Implementation History

Phase 1 implementation scaffolding is complete. T66 added a repeatable result runner.
T67 added the local data-refresh orchestrator. T68 added v1 actionability gates. T72
records the first compact live-refresh summary. T73 records the first live H1
calibration result and sets conservative thresholds. T81 adds a confirmed
activity-alert lane. T99 adds inferred options lanes. T105-T109 add Massive
stock-trade ingestion and five market-flow lanes. T110-T114 add the market-flow
analysis worker and technical-analysis worker. T123-T137 (Track 1) fix structural
bugs, wire LLM into live cycles, persist policy to DB, and complete e2e coverage.
T151-T152 (Track 3) widen Massive coverage and improve the H1 harness.

See `docs/phase-status.md` for the current implementation-vs-phase-gate truth table.
