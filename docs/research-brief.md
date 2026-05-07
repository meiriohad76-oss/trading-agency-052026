# Autonomous Stock Trading Agency — v2 Research Brief

**Status:** Draft v0.2
**Owner:** Ohad Meiri
**Last updated:** 2026-05-06
**Companion documents:** `v2-plan.md`, `working-model.md`, `tickets/README.md`, `phase-status.md`

This is the operational plan for the v2 research phase (Phase 1 in the v2 Plan). The research phase exists to answer one question honestly: **which signals from v1 actually have edge, and what realistic return profile is achievable from a disciplined combination of them?** Until those answers exist, we don't know which v2 to build.

This document is expected to evolve as findings accrue. The `v2-plan.md` companion stays relatively stable, `findings.md` records phase-gate conclusions, and `phase-status.md` records the current implementation-vs-gate truth. Execution is split between OpenAI Codex (heavy lifting) and Claude Code (architecture + safety-critical) per `working-model.md`; current ticket queue is in `tickets/`.

---

## 1. Goals of the Research Phase

By the end of this phase we want, in writing:

1. **A validated signal inventory** — for each candidate signal lane (v1 lanes + the new lanes added in requirements), an evidence-backed verdict: "adds measurable edge," "marginal/inconclusive," or "no edge — drop from v2."
2. **A baseline strategy profile** — Sharpe, CAGR, hit rate, average win/loss, max drawdown, and recovery time, under realistic costs and slippage, on the chosen universe over a multi-year out-of-sample window.
3. **Honest threshold ranges** — for the surviving signals, the conviction thresholds, holding periods, and position-sizing rules that historically performed best, with overfitting controls.
4. **A revised v2 architecture** — concrete revisions to `v2-plan.md` §5 (agent topology) and §7 (signals taxonomy) based on what the data says.
5. **A defensible 3% weekly target answer** — what return profile is realistically reachable, how that compares to the 3% planning target, and what risk budget would be required to even attempt the target (with all the survival caveats).

The phase ends when these five artifacts exist and have been reviewed.

---

## 2. Non-Goals of the Research Phase

To prevent scope creep:

- **Not building v2.** No production code is written this phase. Research code is in notebooks or research scripts and is allowed to be messy, but research findings produce specs, not features.
- **Not optimizing for the 3% target.** We measure what's actually there. Optimizing toward a target is how researchers overfit themselves into ruin.
- **Not exploring strategy regimes outside equity swing.** Same strategy as v1 (long/short equity swing on S&P 100 + QQQ) is the locked starting point. Options-as-instrument, intraday, futures, etc. are out of scope here.
- **Not building the dashboard.** That's Phase 2.

---

## 3. Core Hypotheses

Each hypothesis is testable. Each has a clear success criterion. Each has a "what we do if it's true / false / inconclusive" plan.

### H1 — Individual signal lanes have measurable edge

**Claim:** For each lane in v1's signals layer (and each new lane from the requirements round), the signal has a non-zero, statistically significant Information Coefficient against forward returns at the 1-week and 4-week horizons, on the S&P 100 + QQQ universe, over a 5+ year out-of-sample window.

**Test method:**
- For each signal lane, generate a daily per-ticker score using only data available at that point in time (PIT-correct).
- Compute Spearman rank IC between the score and forward 1w / 4w returns.
- Report mean IC, IC standard error, IC t-statistic, IC information ratio (IR).
- Significance threshold: |t-stat| > 2.5 with mean |IC| > 0.02 (these are research norms, not magic numbers; we'll revisit if results are sparse).

**Lanes to test:**
- Fundamentals factor scores (each factor family separately, then composite).
- News sentiment (RSS-only baseline).
- Insider transactions (Form 4 net buying, weighted by transaction size).
- Institutional flow (13F change in shares held, lagged appropriately).
- Sector momentum / tailwind.
- Abnormal volume (inferred-from-bars).
- Pre/post-market price gap and volume.
- Options activity (yfinance chains, IV skew, put/call ratio).
- Quant Rank changes (Seeking Alpha — requires email-archive sourcing or paid historical).
- Zacks Rank changes (similar).

**If true:** the lane survives into v2 with provisional weight proportional to its IR.
**If false:** the lane is dropped from v2 (saves complexity, saves API spend).
**If inconclusive:** the lane stays in v2 as context-only (not actionable on its own), revisited after Phase 5 produces live outcomes.

### H2 — The deterministic combination beats the best single signal

**Claim:** A weighted combination of the surviving signals from H1 produces higher risk-adjusted returns than the best single signal alone.

**Test method:**
- Define the deterministic combination using v1's structure (long score + short score with regime-conditioned thresholds), but with weights estimated from H1's IRs (not v1's hard-coded engineering defaults).
- Backtest the combination on a 5+ year out-of-sample window (with a separate in-sample window for weight estimation).
- Compare Sharpe ratio of the combination to the Sharpe ratio of each individual signal traded standalone.
- Report turnover, transaction costs assumed, and sensitivity to weight perturbations.

**If true:** the deterministic engine is justified; weights become a v2 default (tagged as "research-validated").
**If false:** the combination is overfit or the lanes are too correlated; v2 simplifies to a smaller set of orthogonal signals, possibly without a "combination" step at all.

### H3 — The LLM review adds edge above deterministic alone

**Claim:** LLM Selection's qualitative review, applied to the deterministic engine's output, improves risk-adjusted returns by a margin that justifies the API cost.

**Test method:**
- Run identical backtests, one with deterministic-only selection, one with deterministic + LLM review (using v1's `llm_selection_committee_v2` prompt or a refined version).
- The LLM review uses only the JSON evidence pack — no outside knowledge, no peeking.
- Report Sharpe, CAGR, max DD, and turnover differences. Estimate API cost per cycle and per year.
- Account for the LLM's stochasticity: run each LLM-included backtest 3-5 times with same seed setup, report the variance.

**If true:** LLM stays in v2, possibly with a tighter prompt and/or smaller/cheaper model variants tested.
**If false (LLM doesn't beat deterministic, or beats it by less than the cost):** LLM moves to context-only (writes the user-facing rationale but doesn't influence selection), or is dropped entirely. This is a substantial v2 simplification.

### H4 — A realistic strategy profile

**Claim:** The full v2 deterministic + LLM strategy on S&P 100 + QQQ, over a 5+ year out-of-sample window, with realistic costs and slippage, produces a Sharpe ratio between X and Y, CAGR between A and B, max drawdown below D, with a recovery time below R.

**Test method:**
- Final backtest using the validated lanes, validated weights, and validated thresholds from H1-H3.
- Walk-forward methodology: rolling re-estimation of weights every N months, no peeking forward.
- Realistic costs: Alpaca commission-free, but assume bid-ask spread of 5 bps for liquid names, 15 bps for less liquid; slippage of 5 bps on entry/exit.
- Stress test under different market regimes: 2018-2019, 2020 COVID, 2022 bear market, 2023-2025 recovery.
- Report the realistic Sharpe / CAGR / DD ranges.

**Output:** a single number for "what is the realistic upper bound on this strategy's CAGR." This becomes the honest answer to the 3% weekly question.

**If the realistic CAGR is, say, 15-30%:** that's a strong retail strategy. v2 architecture is justified. The 3% weekly planning target is documented as aspirational and the actual operating expectation is calibrated to the backtest range.
**If realistic CAGR is below SPY (~10%):** v2 doesn't have edge worth pursuing in current form. We either go back to find what we missed, change the universe, change the strategy regime, or seriously reconsider the project.

### H5 — Universe, holding period, and conviction threshold

**Claim:** The optimal universe size, holding period, and conviction threshold fall out of the data — they are not engineering choices.

**Test method:**
- Vary universe (S&P 100 vs S&P 500 vs full QQQ vs union) and measure Sharpe at each.
- Vary average holding period (3 days, 1 week, 2 weeks, 1 month) and measure.
- Vary conviction threshold (looser → more trades, tighter → fewer/higher-quality trades) and find the curve.
- Report the surface and pick the operating point that maximizes Sharpe subject to a max-DD ceiling.

**Output:** v2's default universe, default holding period, and default conviction threshold, with sensitivity ranges.

### H6 — Paid-sub email signals add edge

**Claim:** Signals derived from your paid subscription emails (SA Quant Rank changes, Zacks Rank changes, TradeVision alerts) add measurable edge above what's available from free sources.

**Test method:**
- Sourcing challenge first: getting *historical* email archives for Quant Rank / Zacks Rank changes is harder than getting current ones. Options:
  - Use whatever email archive exists in your inbox (forward all relevant emails to a research mailbox).
  - Subscribe to a forward-going research feed for the next 4-8 weeks and use that as a held-out forward-test sample.
  - Use SA Premium's web archive of historical Quant Rank changes (needs investigation — may require manual scraping which is ToS-questionable).
- For lanes with sufficient historical data, run the H1 IC analysis.
- For lanes with only forward data, compute IC over the held-out window and report as preliminary.

**If true:** each lane is justified as an actionable signal in v2, with the email-ingest architecture in place from day one.
**If insufficient data to test:** the lane goes into v2 as context-only initially; full validation happens during Phase 5 (operate) on accumulated outcomes.

### H7 — Twitter / X signals justify their cost

**Claim:** Curated content from a defined list of X accounts adds measurable edge above the news lanes.

**Test method:**
- This requires a list of X accounts (Q1 in `v2-plan.md` open questions).
- For accounts that also publish elsewhere (Substack, SA, blog), use those PIT-clean archives instead — same content, no API cost.
- For accounts that are X-only with no historical archive, defer until forward-data is collected (parallel to H6).

**If true with $200/mo justified:** add X Basic API to v2 paid sources.
**If true but only via alternative channels (Substack/blog):** route around X entirely.
**If false:** drop X from v2 scope.

---

## 4. Data Sourcing Plan

What we need to acquire, and how, before the hypotheses above can be tested. This is where the research phase actually starts.

### 4.1 Required Datasets

| Dataset | Source | Coverage Needed | PIT Status | Acquisition |
|---|---|---|---|---|
| Daily OHLCV | yfinance / Alpaca | S&P 100 + QQQ historical members, 2019-01-01 to today | PIT-clean for prices | Bulk download script, cached locally. |
| Historical universe membership | Wikipedia + manual reconstruction | S&P 100 + QQQ membership at month-end, 2019-2026 | Reconstructed PIT | One-off effort; reusable. |
| SEC fundamentals | SEC EDGAR Company Facts API | All universe tickers, all filings 2019+ | PIT-clean (filing date) | API pull, cached locally. ~few GB. |
| SEC Form 4 (insider) | SEC EDGAR | All universe tickers, 2019+ | PIT-clean (filing date) | API pull. |
| SEC 13F (institutional) | SEC EDGAR | All universe tickers, 2019+ | PIT-clean (quarter end + filing lag) | API pull. |
| Earnings calendar | yfinance / SEC + web | Universe, 2019+ | Mostly PIT-clean | Yfinance has earnings_dates. |
| Free RSS news (historical) | Yahoo, Google | NA — RSS is real-time only | Forward-only | Start collection now; use prospectively only. |
| Paid-sub historical signals | SA / Zacks / Investing / TradeVision | Whatever is reachable from email archive or web | Variable | See H6 method. |
| Sector ETFs | yfinance | XLE, XLK, XLF, XLV, XLI, XLB, XLY, XLP, XLU, XLC, XLRE, plus broad SPY/QQQ/IWM | PIT-clean | Bulk download. |
| Options chains | yfinance | Universe, going forward | Forward-only (yfinance doesn't preserve historical chains for free) | Start collection now. Historical options data is paid (Polygon ~$30/mo if needed for H1 options test). |

### 4.2 Storage Format

- Parquet files for time-series datasets, partitioned by symbol and year.
- DuckDB or SQLite for the research workspace (SQLite is simpler; DuckDB is faster for analytical queries).
- All raw data preserved separately from cleaned/derived data.
- Every dataset has a manifest: source URL, fetch timestamp, schema version, row count, checksum.

### 4.3 Research Repository Layout (proposed)

```
research/
  data/
    raw/              # raw API responses, raw RSS, raw emails
    parquet/          # cleaned, partitioned, columnar
    manifests/        # one manifest per dataset
  notebooks/          # exploratory notebooks (one per hypothesis)
  src/
    pit/              # PIT data loader; the only way notebooks access data
    signals/          # one signal-generator function per lane
    backtests/        # walk-forward harness, performance metrics
    statistics/       # IC, IR, regression utilities
  results/
    h1/               # IC tables, plots, write-ups per lane
    h2/               # combination backtest results
    h3/               # LLM-vs-deterministic comparison
    h4/               # final realistic profile
    h5/               # universe / horizon / threshold sweep
    h6-paid-subs/
    h7-twitter/
  scripts/            # one-off jobs: data refresh, universe rebuild
  README.md           # how to run the pipeline
```

The PIT loader is the single source of truth for "what was known at time T" — no notebook reads raw files directly. This enforces N8 (PIT discipline) at the layer where it matters.

---

## 5. Sprint Breakdown (compressed, parallel-extension model)

This is the speedrun: 1-2 weeks of calendar time leveraging Codex (heavy lifting) + Claude Code (architecture and safety-critical) in parallel, with the human reviewing PRs and me producing specs. The original 8-week single-developer plan is retired. Concrete tickets for each step live in `tickets/`; see `working-model.md` for role split and git workflow.

### Wave 1 — Foundation (Days 1-2)

| Track | Work | Tickets |
|---|---|---|
| Codex | Repo scaffold, Postgres+Docker stack | T01, T02 |
| Claude Code | Provenance type and external-API wrapper | T03 |
| Human | Resolve open items: Pi specs, research mailbox, cloud VM call | (see `v2-plan.md` §9) |

**Deliverable:** working dev environment, schema-ready repo, Provenance type that everything else depends on. CI green.

### Wave 2 — PIT Layer + Statistics (Days 2-4, parallel with Wave 3)

| Track | Work | Tickets |
|---|---|---|
| Claude Code | PIT loader scaffold | T04 |
| Claude Code (parallel) | IC and statistical utilities | T09 |

**Deliverable:** the load-bearing data layer (PIT) and stats primitives. Once these merge, every Codex data-pull ticket can run in parallel.

### Wave 3 — Data Acquisition (Days 3-6, heavy parallel)

| Track | Work | Tickets |
|---|---|---|
| Codex (parallel A) | Universe history reconstruction | T05 |
| Codex (parallel B) | yfinance daily OHLCV puller | T06 |
| Codex (parallel C) | SEC EDGAR puller suite | T07 |
| Codex (parallel D) | Sector ETF puller (small; can fold into B) | T08 |
| Claude Code | Walk-forward backtest harness | T10 |

**Deliverable:** every free PIT-clean dataset is loaded, queryable, and reachable through the PIT loader. Walk-forward harness tested. Ready to run H1 IC analysis.

### Wave 4 — H1 (signal edge) (Days 6-9)

A new ticket batch (T11-T2x) gets written by me after Wave 3 lands; one ticket per signal lane. Codex implements each lane's signal-generation function; the IC notebook is also Codex (using Claude Code's utilities). Human reviews verdicts.

**Lanes covered (free-source first, paid-sub forward-only):**
- Fundamentals factor lanes (per factor family)
- Insider transactions (Form 4-derived)
- Institutional flow (13F-derived)
- Sector momentum / tailwind
- Abnormal volume (inferred-from-bars)
- Pre/post-market price + volume (Alpaca/yfinance free coverage)
- Options chain features (yfinance forward; historical options deferred)
- News sentiment (free RSS baseline)

**Deferred from Wave 4 to Phase 5 (operate, on accumulated outcomes):**
- SA Quant Rank historical edge (forward-collection only — start the email pipeline NOW)
- Zacks Rank historical edge (forward-collection only)
- TradeVision alert historical edge (forward-collection only)
- X/Twitter (deferred entirely until baseline H1/H4 verdict is in)

**Deliverable:** one verdict per lane (survive / drop / inconclusive) with IC, t-stat, IR, and Bonferroni-adjusted significance.

### Wave 5 — H4 + H5 (realistic profile + sweep) (Days 9-11)

Codex runs the universe / horizon / threshold sweep through the walk-forward harness. Claude Code reviews the cost/slippage assumptions.

**Deliverable:** the realistic Sharpe / CAGR / max-DD profile. Honest answer to the 3% weekly question.

### Wave 6 — H3 (LLM contribution) + Findings (Days 11-14)

| Track | Work |
|---|---|
| Codex | Run identical backtests with and without LLM review (3-5 seeds for variance) |
| Claude Code | Refine the LLM prompt if needed |
| Me | Write the Phase 1 findings document; produce revised `v2-plan.md` §5 and §7 |

**Deliverable:** complete Phase 1 findings. v2 Plan revision PR. Ready for Phase 2 (Design).

### Realistic time bounds

- **Aggressive (full focus, multiple parallel sessions):** 1 week.
- **Realistic (daytime + evening, single-window-at-a-time human review):** 2 weeks.
- **Tight evenings/weekends only:** 3-4 weeks.

The compression vs. the original 8 weeks comes from three sources: Codex parallel data pulls (replaces ~2 weeks of single-dev work), Claude Code on infra in parallel with Codex on data (replaces ~1 week), and ticket pre-writing (replaces ~1 week of context-switching). The remaining ~4 weeks of original plan compress into the irreducible review cycles.

### Sequential bottlenecks (don't try to skip)

- **T03 → T04 → T06/T07/T08:** Provenance type → PIT loader → data pullers is sequential. Skipping invites schema breakage on Wave 4.
- **T09 → T10:** stats utilities before the harness consuming them.
- **T04 + data pullers → H1 lane tickets:** lanes need real data queryable through the loader.

---

## 6. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **PIT contamination** — accidentally using future-revised data as if it were original | High | Severe | All access through PIT loader. Loader unit-tested against known-bad cases. Spot-check backtests with manual queries. |
| **Survivorship bias** — using current S&P 100 members for historical periods | High if lazy | Severe | Historical membership reconstruction is week 1 deliverable, not optional. |
| **Multiple-comparisons overfit** — testing 15 signals will produce false positives by chance | High | Medium | Apply Bonferroni or Benjamini-Hochberg correction to H1 results. Hold out 2024+ as final out-of-sample window not used during H1. |
| **Look-ahead bias in news/text features** — using publication date when only timestamp_observed is available | Medium | High | Treat news without proper publish-time as forward-collection only, not historical backtest. |
| **Free data quality gaps** — yfinance has occasional bad bars, missing days | Medium | Low-medium | Cross-check against Alpaca for spot validation. Filter implausible returns. |
| **Time overruns** — 8 weeks turns into 16+ at evening pace | High | Medium | Ruthless prioritization: H1 + H4 are mandatory, H2+H5 are important, H3/H6/H7 can be deferred or done in lighter form. |
| **Research findings invalidate v1 architecture** | Medium | Medium (but desired) | This is the feature, not the bug. v2 Plan revision is built into the phase gate. |
| **Paid-sub email historical sourcing impossible** | Medium-high | Low | Pivot H6 to forward-test; document as "preliminary" in v2 until Phase 5 outcomes accumulate. |
| **All signals show no edge** | Possible | Severe | Existential. If the data really says no edge exists, we have to accept that and decide whether to broaden universe, change regime, or shelve. The honest answer matters more than the convenient one. |

---

## 7. Open Items Before Starting

These need resolution to start cleanly. Most map to open questions in `v2-plan.md`.

T65 note: implementation scaffolding has moved ahead of the empirical research gate.
The items below still matter before any signal lane becomes action-weighted.

1. **Universe revision authority** (Q10 in v2-plan). Confirmed open: research can revise lanes. Can it also revise the universe (e.g., S&P 100 → Russell 1000)?
2. **Cloud VM for heavy backtests** (Q11). Recommendation: a Hetzner CPX31 (~€10/mo) or AWS spot for week-5/6 backtests if the Pi struggles. Confirm budget.
3. **Paid-sub emails — research mailbox** (Q6). Need a dedicated email address for forwarding, with IMAP/Gmail API access for the ingest scripts.
4. **Paid sub historical access**. For H6 to be testable on historical data: do you have email archives going back, or do we need to start prospective collection now?
5. **Polygon options data subscription**. If H1 options testing is in scope, ~$30/mo for 2 years of historical options data. Worth it, or skip and treat options as forward-only?
6. **Twitter accounts list**. List the accounts to make H7 concrete.
7. **Time commitment honest estimate**. 8 weeks at full focus or 16+ at evening pace will affect what we attempt vs defer.

---

## 8. What Comes After This Brief

Once Phase 1 is done, the deliverables feed into Phase 2 (Design). At that point:

- The v2 Plan §5 (agent topology) and §7 (signals taxonomy) get updated with the validated lane list.
- The Phase 2 design doc is produced: schemas finalized, dashboard wireframes prototyped using Claude design tools and the web-artifacts-builder skill, test fixtures designed.
- Budget-and-paid-source decisions are finalized based on the cost/benefit each lane demonstrated.

---

## 9. Document Maintenance

This document updates as findings come in. After each hypothesis is tested, append the result, verdict, and architecture implications to `docs/findings.md`, then update the relevant hypothesis section here only if the operating plan changes.

When the research phase ends, `docs/findings.md`, this document, and the results folder are the input to Phase 2.
Until then, `docs/phase-status.md` should be used to distinguish provisional build
work from accepted phase-gate work.

---

*End of Research Brief.*
