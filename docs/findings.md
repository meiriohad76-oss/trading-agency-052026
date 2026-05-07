# Phase 1 Findings

**Status:** Preliminary scaffold
**Owner:** Ohad Meiri
**Last updated:** 2026-05-07

This document is the phase-gate record for the v2 research phase. It separates
implemented research machinery from empirical findings. Until result files exist under
`research/results/`, every strategy verdict below remains provisional.

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
| Signal lanes | Fundamentals, insider, institutional, sector, volume, pre/post, news, options | Deterministic functions implemented; empirical IC pending. |
| Evaluation | H1 IC, H1 verdicts, walk-forward, profile, sweep, combination, LLM A/B | Reusable utilities implemented and unit-tested. |

---

## H1: Individual Signal Lanes

| Lane | Source | Current verdict | Next action |
| --- | --- | --- | --- |
| Fundamentals | SEC company facts | Pending empirical IC | Run `research/scripts/run_h1_ic.py --signal fundamentals`. |
| Insider | SEC Form 4 | Pending empirical IC | Run H1 IC after Form 4 refresh. |
| Institutional | SEC 13F | Pending empirical IC | Run H1 IC after 13F refresh. |
| Sector momentum | Sector ETF bars | Pending empirical IC | Run H1 IC after ETF refresh. |
| Abnormal volume | Daily bars | Pending empirical IC | Run H1 IC with inferred-source label preserved. |
| Pre/post | Extended-hours-capable source | Pending data coverage check | Keep context-only if free coverage is sparse. |
| News | RSS-forward corpus | Forward-only preliminary | Accumulate held-out window before declaring edge. |
| Options flow | yfinance forward chains | Forward-only preliminary | Accumulate forward observations or buy historical data. |

**Architecture implication:** no lane should become action-weighted in production until it
survives H1 or is explicitly accepted as context-only.

---

## H2: Deterministic Combination

The deterministic combination utility exists and derives positive weights from H1
information ratios. It is ready to test whether a weighted lane blend beats the best
single surviving lane.

**Current verdict:** pending empirical comparison.

**Next action:** run H1 verdicts first, then build the combined signal from surviving
lanes and profile it with the walk-forward harness.

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
not complete. The next highest-value work is to run the data refresh and H1/H2/H3/H4
result jobs, commit compact result summaries, and then revise `docs/v2-plan.md` with
validated lane weights or documented simplifications.

See `docs/phase-status.md` for the current implementation-vs-phase-gate truth table
and next ticket candidates.
