# Phase 1 Findings

**Status:** Preliminary empirical H1 complete
**Owner:** Ohad Meiri
**Last updated:** 2026-05-08

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
| Signal lanes | Fundamentals, insider, institutional, sector, volume, pre/post, news, options, activity alerts | First live H1 run is inconclusive for tested lanes; activity alerts are newly scaffolded and need provider coverage. |
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
| Options flow | yfinance forward chains | Forward-only preliminary | Accumulate forward observations or buy historical data. |
| Activity alerts | Local paid/confirmed CSV import | Forward-only scaffold; no empirical verdict yet | Import TradeVision/block-trade exports and run H1 once coverage exists. |

**Architecture implication:** no tested lane is research-validated as a standalone
action trigger. T73 therefore keeps the actionability bar conservative: deterministic
`WATCH` now requires at least two usable independent sources and one confirmed signal.

---

## H2: Deterministic Combination

The deterministic combination utility exists and derives positive weights from H1
information ratios. It is ready to test whether a weighted lane blend beats the best
single surviving lane.

**Current verdict:** pending empirical comparison.

**Next action:** no H1 lane survived, so H2 should stay blocked until a wider retest,
stronger ticker-tagged news coverage, or an explicit context-only combination experiment
is accepted.

---

## H3: LLM Review Contribution

The A/B harness and H3 summary tooling exist. The LLM reviewer must consume only the
same evidence payload available to the deterministic engine.

**Current verdict:** pending empirical A/B runs.

**Decision rule:** keep the LLM in the selection path only if reviewed runs improve
Sharpe and CAGR without materially worsening drawdown after repeat variance is reported.
Otherwise, move the LLM to context-only rationale generation.

---

## H4/H5: Realistic Profile And Sweep

The profile and parameter sweep utilities exist. They report CAGR, Sharpe, max drawdown,
weekly target gap, turnover, and cost assumptions.

**Current verdict:** pending full historical walk-forward run.

**Next action:** run the deterministic combined strategy across realistic cost/slippage
settings, then sweep thresholds and position counts.

---

## Phase 2 Inputs

Phase 2 design should start only after the pending result files are produced, or with
explicit acceptance that the first build will use provisional defaults. The immediate
schema priorities are:

- EvidencePack schema shared by deterministic and LLM selection.
- SignalResult schema with actionability, provenance, freshness, and suppression reason.
- SelectionReport schema covering approval, concerns, gates, trade plan, and evidence.
- DataSourceHealth schema powering dashboard validity strips and reliability gates.

---

## Current Phase-Gate Status

Phase 1 implementation scaffolding is substantially complete. Empirical validation is
not complete. T66 added a repeatable result runner, T67 added the local data-refresh
orchestrator, and T68 added v1 actionability gates. T72 records the first compact
live-refresh summary; raw/parquet outputs remain intentionally local-only. T73 records
the first live H1 calibration result and keeps runtime thresholds conservative because
no lane survived the Bonferroni-adjusted H1 bar. T81 adds a confirmed activity-alert
lane for provider/email block trades, dark-pool prints, and unusual-activity exports,
but it remains context-only until enough forward or historical coverage is tested. The
next highest-value work is to test the first version with the conservative gate and
decide whether to widen H1 coverage or add stronger ticker-tagged sources.

See `docs/phase-status.md` for the current implementation-vs-phase-gate truth table
and next ticket candidates.
