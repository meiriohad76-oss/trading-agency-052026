# Autonomous Stock Trading Agency — v2 Plan

**Status:** Draft v0.1
**Owner:** Ohad Meiri
**Last updated:** 2026-05-06
**Companion document:** `research-brief.md`

This document is the strategic anchor for v2 of the autonomous stock trading agency. It captures the locked decisions, non-negotiable requirements, architectural direction, agent topology, data sources catalog, signals taxonomy, and phase structure. It is intended to stay relatively stable; the operational research plan lives separately in `research-brief.md`.

---

## 1. Vision

The v2 agency is a **supervised, autonomous, free-first equity research and paper-trading assistant** for a single user, running on a Raspberry Pi, operating over a defined universe of US equities (S&P 100 + QQQ holdings).

It exists to take the user from a broad universe to a small set of explainable, evidence-backed paper-trade candidates, with full traceability, transparent data quality, and explicit human approval before any order submission.

It is **not** an autonomous trader. It is **not** a return guarantee. It is a disciplined research and pre-trade assistant that refuses to make decisions when the evidence is thin, stale, or untrustworthy.

The longer-term planning target is a 3% weekly portfolio gain. This is a **planning and risk-budget objective**, not a promise of return and not a reason to force trades. Architecturally, v2 is optimized for **survival, edge persistence, and drawdown discipline**, not for hitting that number. The research phase will produce honest estimates of what return profile is realistically achievable; if those estimates fall well short of 3%/week (almost certain), v2's architecture and risk policy are unchanged — the planning target simply gets revised against reality.

---

## 2. Non-Negotiables

These are foundational. v2 is not "ready" until every one of them holds across every screen, every agent, and every test.

**N1 — Universal data-sufficiency gating.** Every agent output, every decision, every recommendation — including the LLM's — passes an explicit gate on three dimensions:
- **Amount** of supporting evidence (enough independent sources / enough data points)
- **Freshness** of that evidence (within the relevant domain freshness window)
- **Credibility** of that evidence (source reliability tier and verification level)

If any dimension fails the gate, the output is suppressed, downgraded to non-actionable, or labeled as "context only" — never silently passed through. This is both an architectural requirement and a test requirement.

**N2 — Three-layer testing as a release gate.** v2 is not shippable until all three layers pass:
1. **Unit/integration tests** for every agent and aggregator in isolation, including scarcity-gate behavior and failure modes.
2. **Inter-agent data flow tests** that verify schema conformance at every boundary, lifecycle traceability of a candidate from universe to execution preview, and degradation behavior when an upstream agent fails.
3. **Holistic end-to-end user-flow tests** that confirm a user can understand, on every screen, what the system is recommending, why, what data backs it, and what the next action is — including empty, rejected, test-mode, and degraded-data states.

**N3 — Signal-to-noise UX.** Every screen leads with the bottom-line answer. Color, size, weight, and iconography encode meaning (good / bad / neutral / unavailable). Detail is reachable but never blocking. Diagnostic data lives behind drill-down, never in the user's face on first read. The dashboard is designed using modern, proven UX patterns and prototyped using Claude design tools and the relevant installed skills.

**N4 — Free-first data sourcing.** The default for any data source is the free tier. A paid source is only justified when free sources are *demonstrably* incapable of supporting a needed capability, with that demonstration recorded in writing. Existing paid subscriptions (Zacks, Seeking Alpha, Investing.com, TradeVision) are first-class data sources, ingested via email and RSS, never via server-side scraping.

**N5 — Supervised execution.** Analysis is autonomous. Ranking is autonomous. Reports are autonomous. Paper-order previews are generated when gates pass. Actual order submission requires explicit human confirmation, every time. Live trading is disabled by default and requires a separate, deliberate enablement step.

**N6 — Schemas-first inter-agent contracts.** Every agent's input and output is a versioned JSON schema, defined and reviewed before code is written. Schema breakage is a hard test failure.

**N7 — Provenance as a first-class data type.** Every data value the system stores or acts on carries `(value, source, timestamp_observed, timestamp_as_of, freshness, confidence, verification_level)`. Provenance is not optional metadata — it is part of every value, and downstream agents must use it.

**N8 — Point-in-time (PIT) discipline.** Every backtest and every research result honors the data that was *actually available* at the simulated decision time. No lookahead, no survivorship bias, no use of revised data as if it were original.

**N9 — Idempotent agent runs.** Same input snapshot → same output, every time. Required for reproducible backtests, audit replay, and debuggable production behavior.

**N10 — Reproducible deployment.** v2 deploys to the Pi via a documented, versioned, idempotent process (Docker, or an ansible-style script, or a Makefile + scripted setup). Not a 154 KB bash heredoc.

---

## 3. v1 Retrospective

A clear-eyed view of v1 is the foundation of v2. Below is what to keep, what to discard, and what to revise.

### 3.1 Keep

These are v1's genuine strengths and v2 inherits them deliberately.

- **The 12-question agent decomposition.** The product thinking is good. Each agent answers a distinct question. v2 will rationalize the topology (see §5), but the underlying decomposition is sound.
- **Deterministic + LLM dual-track selection.** The pattern of running rules-based scoring in parallel with LLM review, then arbitrating, is the right architecture for a supervised system. v2 keeps it — pending research validation that the LLM actually adds edge.
- **Evidence quality tiers and verification levels.** The vocabulary of `high quality / needs confirmation / stale / duplicate / low signal / source limited` plus the verification scale (official filing > delayed trade print > bar-derived > provider news > RSS-only > social) is well-thought and reusable.
- **Refusal patterns.** "LLM cannot execute trades," "LLM cannot promote watch directly to execution," "shorts blocked unless explicitly enabled," "live trading off by default" — these are real safety patterns and v2 keeps every one of them.
- **The data-scarcity instinct.** The Real Estate / single-stock / no-ETF tailwind catch is exactly the kind of insight that prevents quiet strategy failure. v2 promotes this from "lesson learned" to "universal architectural gate" (N1).
- **The selection report structure.** Approval status, executive summary, agent votes, why-passed, concerns, policy gates, recent evidence, trade plan — this is the right shape. v2 inherits it.
- **JSON schemas across agent boundaries.** v1 already started with 9 schemas. v2 makes this absolute (N6).
- **The api_saver_testing profile concept.** API discipline during development is a real production need; v2 keeps and extends it.

### 3.2 Discard

These either don't work, are duplicated, or have become technical debt v2 doesn't inherit.

- **The hand-rolled HTTP router.** A Python web framework (FastAPI) gives us routing, request validation, OpenAPI generation, and middleware for free. The v1 router was a maintenance liability.
- **The 416 KB vanilla JS frontend `app.js`.** Replaced by a structured frontend in v2 (server-rendered htmx initially; small Vite+React bundle if interactive needs grow).
- **Parallel UI implementations.** `fundamentals.js`, `fundamentals-v2.js`, `fundamentals-NAAMA.js`, `fundamentals-NAAMA-2.js` — v2 has one UI per surface, period. Branching UIs without merging them back is a v1 anti-pattern.
- **Dual storage.** v1 has both Postgres and SQLite wired in. v2 picks one for production (Postgres on Pi) and uses SQLite only in tests.
- **Duplicate broker modules.** v1 has `alpaca.js`, `broker-alpaca.js`, `broker-alpaca-mcp.js`, `alpaca-mcp-client.js`. v2 has one broker module with one interface.
- **The 155 KB `persistence.js` and 77 KB `agency-cycle.js`.** Mega-files indicate missing module boundaries. v2 enforces module size discipline (rule of thumb: file > 500 lines is a smell, > 1000 lines is a refactor).
- **The 154 KB bash deploy script.** Replaced by Docker or a versioned setup script (N10).
- **Diagnostic scripts pretending to be tests.** v1's `npm run check:*` are smoke runners, not unit/integration tests. v2 has a real test framework (pytest) with the three-layer testing model from N2.
- **Bar-derived flow as evidence-by-default.** v1 lessons already flagged this; v2 explicitly separates inferred from confirmed flow at the schema level, with confirmed as default-actionable and inferred as context-only.
- **The "block_trade_*" event type sourced from bar inference.** Removed; only true trade prints from a confirmed source produce block-trade events.

### 3.3 Revise

These are kept in spirit but redesigned in v2.

- **Universe Agent.** v1 treats it as an agent; v2 treats it as a registry/infrastructure component (see §5). Its function is preserved, its framing is honest.
- **Portfolio Policy Agent.** v1 treats it as an agent; v2 treats it as configuration with validation. Same outputs, simpler model.
- **Runtime Reliability "Agent".** v1 buries this in a 44 KB module among the agents. v2 promotes it to first-class observability — every agent reads from a shared reliability service that knows the health of every data source.
- **Final Selection Agent.** v1's formula `0.62 * deterministic + 0.28 * LLM + bonuses/penalties` is engineering defaults, not validated weights. v2 keeps the *shape* of arbitration but defers the weights to research-phase findings (and tags them as "unvalidated default" until proven).
- **Learning Agent.** v1's design is sound; v2 actually has the data to feed it because of the audit/lifecycle requirement (see §4) and PIT discipline (N8).
- **Signals Agent.** Most-revised. See §7 for the v2 signals taxonomy and actionability bar.

---

## 4. Architectural Decisions

### 4.1 Stack

- **Language:** Python 3.14 end-to-end. Chosen because the research phase happens in Python regardless (pandas, numpy, scipy, statsmodels, vectorbt, scikit-learn), and keeping research and production in one language means research code becomes the production deterministic engine.
- **Backend framework:** FastAPI (async-capable, type-friendly, OpenAPI-native, good single-user fit).
- **Frontend:** htmx + server-rendered Jinja for the first cut. This is intentionally simple, gives us a working dashboard fast, and avoids the v1 JS-framework trap. If interactive complexity grows, we add a small Vite+React bundle for specific surfaces — but only after htmx is proven insufficient.
- **Background jobs:** APScheduler for cron-style scheduling, or RQ for queue-style work, depending on what the agent cycle ends up looking like.
- **Testing:** pytest, with separate fixtures for each test layer in N2.
- **Linting/typing:** ruff + mypy (or pyright). Type hints are not optional in v2.
- **LLM SDK:** OpenAI Python SDK for production; local fallback reviewer is a pure-Python rules engine.
- **Backtesting:** vectorbt as primary, with a thin local wrapper. Considered but not chosen: backtrader (older, slower), zipline-reloaded (heavier, less actively maintained).

### 4.2 Hardware

- **Production:** Raspberry Pi 4 with 8 GB RAM. Cheaper Pi 4 / Pi 5 versions usable but tighter.
- **Research/heavy backtesting:** ad-hoc cloud VM (Hetzner, Fly, AWS spot) for any backtest that exceeds Pi memory or wall-clock budget. Results are committed back to the Pi's data store.

### 4.3 Storage

- **Production database:** PostgreSQL on the Pi. One database, not two.
- **Test database:** SQLite in tests; Postgres in CI when feasible.
- **Object storage:** local filesystem on the Pi for raw artifacts (raw API responses, raw emails). Backed up to a cloud bucket nightly.
- **Audit history:** dedicated tables for agent runs, candidate lifecycle events, prompt+response pairs, and risk snapshots. Append-only.

### 4.4 Schema and Provenance

- Inter-agent data contracts are versioned JSON schemas, stored in a `schemas/` folder, validated on every boundary crossing in production.
- Every value carries provenance (N7). The provenance type is a first-class object: source, timestamp_observed, timestamp_as_of, freshness_status, confidence, verification_level.
- The PIT data store treats `timestamp_as_of` as a primary index dimension. Backtests query "what did we know about ticker X as of date D?" and get only data with `timestamp_as_of <= D`.

### 4.5 Idempotency and Auditability

- Every agent run is a function of its (versioned) input snapshot. Same snapshot in → same snapshot out, always. No hidden state.
- Every agent run writes an audit row: `run_id`, `agent`, `version`, `input_snapshot_id`, `output_snapshot_id`, `started_at`, `finished_at`, `status`, `provenance_summary`.
- Candidate lifecycle events are stored: entered_universe, passed_fundamentals, deterministic_action, llm_action, final_action, risk_decision, execution_state, removed_or_demoted (with reason). This is what answers "why did Netflix disappear?"

### 4.6 Deployment

- Docker Compose on the Pi. One file describes the production stack: Postgres, FastAPI app, scheduler, frontend.
- Configuration via `.env` (per-environment), with a sample `.env.example` checked in.
- Backups: nightly Postgres dump to local storage + cloud bucket; raw artifact rsync to cloud bucket.

### 4.7 Observability

- Structured JSON logging from every agent (`logging` + `structlog`).
- A `/health` endpoint exposes per-agent readiness and per-data-source freshness.
- A `/metrics` endpoint exposes counters and gauges for cycle time, decisions per cycle, gate-block rates, API call counts, and error rates.
- The dashboard's "validity strip" reads from the same data the metrics endpoint exposes — so what the user sees and what observability sees are the same numbers.

---

## 5. Agent Topology

v1 had 12 "agents" treated as peers. v2 keeps the underlying responsibilities but classifies them honestly into four categories. This is a naming/framing change with structural implications: analytical engines run on data-quality gates; aggregators don't produce signal independently; infrastructure provides shared services; operations & feedback close the loop.

### 5.1 Analytical Engines

These independently produce signal from raw data. Each has its own data-sufficiency gate (N1) and its own test suite (N2).

| Engine | Mission | Primary Inputs | Primary Outputs |
|---|---|---|---|
| **Fundamentals Engine** | Score business quality from SEC-backed facts. | SEC EDGAR (company facts, filings), market reference for valuation. | Composite fundamental score, factor scores, screen stage, reason codes, provenance. |
| **Market Regime Engine** | Read the top-down market and sector backdrop. | Market index data, sector ETF prices, top-constituent prices, breadth. | Regime label (risk_on / risk_off / high_dispersion / balanced), sector tailwinds/pressures, thresholds for selection. |
| **Signals Engine** | Collect and classify near-term, stock-specific evidence. | News feeds (RSS, email), Form 4, 13F, market-flow, pre/post-market data, options data, X content (if enabled). | Evidence documents tagged with type, ticker, freshness, source, verification level, downstream weight. |
| **Deterministic Selection Engine** | Convert the evidence pack into rules-based long/short/watch/no-trade setups. | Outputs of the three engines above, plus runtime reliability and policy. | Per-ticker setup with action, conviction, score components, blockers, risk flags, entry plan. |
| **LLM Selection Engine** | Qualitative review of the same evidence pack. | The same JSON pack the deterministic engine sees. | Per-ticker LLM action, confidence, rationale, supporting factors, concerns, missing data. |

### 5.2 Aggregators

These don't produce independent signal; they combine engine outputs and apply policy. They still have data-sufficiency requirements and tests, but their tests are about *correct aggregation logic*, not *signal quality*.

| Aggregator | Mission | Primary Inputs | Primary Outputs |
|---|---|---|---|
| **Final Selection Aggregator** | Arbitrate between deterministic and LLM, apply policy gates. | Deterministic setup, LLM review, portfolio policy, risk snapshot, position state. | Final action per ticker, final conviction, policy gates, selection report. |
| **Risk Aggregator** | Block unsafe previews/submissions based on exposure, account, and runtime state. | Final setup, broker account, positions, orders, policy, runtime reliability. | Risk decision (allow/warn/block), exposure snapshot, reasons. |

### 5.3 Configuration & Infrastructure

Honest naming: these are services, not agents. They don't analyze; they support.

| Component | Purpose |
|---|---|
| **Universe Registry** | Maintain the allowed ticker list (S&P 100 + QQQ historical members), with identity and CIK mappings. PIT-aware. |
| **Portfolio Policy Service** | User-editable rules (target, drawdown, max positions, exposure caps, stop/target defaults), validated and exposed to aggregators. |
| **Runtime Reliability Service** | Per-source health, freshness, and rate-limit state. Read by every analytical engine. |
| **Data Provenance Service** | Wraps every external API call and every email/RSS ingest with timestamping, source labeling, and verification-level tagging. Returns provenance-wrapped values. |
| **PIT Data Store** | The point-in-time historical store. Every record has `timestamp_as_of`. Queries are PIT-correct by default. |

### 5.4 Operations & Feedback

| Component | Mission |
|---|---|
| **Execution Service** | Translate approved setups into Alpaca paper-order previews, gate submission behind explicit user approval. |
| **Portfolio Monitor** | Match held positions to current setups; classify hold / review / close-candidate. |
| **Learning Engine** | Compare decisions to outcomes; surface threshold and weight calibration suggestions only after sample size is sufficient. |

### 5.5 The Cycle

Each agency cycle, in order:

1. Universe Registry confirms allowed tickers.
2. Data Provenance Service refreshes per its source schedules; Runtime Reliability Service updates source health.
3. Fundamentals Engine, Market Regime Engine, and Signals Engine run in parallel.
4. Deterministic Selection Engine runs.
5. LLM Selection Engine runs (cheaper to run after deterministic so we can prompt with deterministic output).
6. Final Selection Aggregator runs.
7. Risk Aggregator runs on each final candidate.
8. Execution Service generates previews (no submission).
9. Portfolio Monitor updates against current setups.
10. Learning Engine logs decisions and (later) outcomes.

The dashboard reads from the audit and lifecycle tables — it doesn't trigger work itself.

---

## 6. Data Sources Catalog

This is the master inventory. Every source has a status (free / paid-existing / paid-pending-justification / blocked), a PIT quality assessment, and an ingestion method.

### 6.1 Free Sources (default)

| Source | Data | Ingestion | PIT Quality | Notes |
|---|---|---|---|---|
| **SEC EDGAR — Company Facts API** | Fundamentals, financial statements | HTTPS, official | Excellent (filing-date based) | Free, ToS-clean. Foundation of fundamentals. |
| **SEC EDGAR — Form 4** | Insider transactions | HTTPS, official | Excellent (filing-date based) | Free, ToS-clean. Insider buying/selling lane. |
| **SEC EDGAR — 13F** | Institutional holdings | HTTPS, official | Good (quarter-end based, lagged) | Free, ToS-clean. Institutional flow lane. |
| **Yahoo Finance via `yfinance`** | Daily OHLCV, dividends, splits, basic fundamentals | Library | Good for prices; fundamentals are revised (not PIT-clean) | Free, fragile (unofficial API). Use for prices; don't trust for PIT fundamentals. |
| **Alpaca free tier** | Daily and intraday bars, paper trading | REST + WebSocket | Good | Free with account. Primary broker; primary intraday source. |
| **FRED** | Macro time series | REST | Excellent | Free. Optional macro context. |
| **Yahoo Finance RSS** | Per-ticker news headlines | RSS | Headline-only, no full-article PIT | Free. Discovery only, not actionable on its own. |
| **Google News RSS** | News headlines | RSS | Headline-only, no historical PIT | Free, ToS-grey-area. Discovery only. |
| **Wikipedia historical S&P 100 / NASDAQ-100 lists** | Historical universe membership | Manual + scrape | PIT-reconstructable manually | Required for survivorship-bias-free backtests. |

### 6.2 Paid Existing Subscriptions

Per requirement: ingested via email + RSS, never server-scraped.

| Source | Data Lanes | Ingestion | Notes |
|---|---|---|---|
| **Seeking Alpha (Premium)** | Quant rank changes, earnings transcripts, analyst articles, ratings | Email digests + RSS feeds (per-symbol RSS, e.g. `/symbol/AAPL/rss`) | Quant rank changes are a high-value signal. Email-ingest captures provenance natively. |
| **Zacks** | Zacks Rank changes, stock recommendations, market commentary | Email alerts (Zacks emails subscribers on rank changes) | Email-ingest. Limited RSS. |
| **Investing.com** | Market news, stock news, economic calendar, technical analysis | RSS feeds (extensive) + email digests | RSS coverage is good here; lean on RSS, supplement with email. |
| **TradeVision.io** | Unusual options activity, dark-pool flow, block trades, unusual stock activity | Email alerts | Likely the primary route for confirmed unusual activity / block-trade evidence. Worth reviewing what alerts are actually configurable. |

### 6.3 Paid Pending Justification

These are *not* in v2 by default. Each requires written justification before adoption.

| Source | Capability | Approx. Cost | Justification Test |
|---|---|---|---|
| **Marketaux historical news** | News with PIT publish timestamps for backtesting | ~$30-50/mo | Research must show news lane adds measurable edge above SEC + price + paid-sub email lanes. |
| **X / Twitter Basic API** | Read access to followed accounts | $200/mo | Research must show X content adds measurable edge above the news lanes already available. |
| **Polygon.io** | Real-time + historical intraday, options data, trade prints | $30-200/mo depending on tier | Research must show intraday or options data is decisive. Alpaca + yfinance may suffice. |
| **Alpaca paid plans** | Better intraday data, lower latency | ~$9-99/mo | Only if free tier proves insufficient for the chosen strategy. |

### 6.4 Blocked

| Source | Reason |
|---|---|
| **Server-side scraping of Zacks/SA/Investing/TradeVision** | ToS violation. Paid subscriptions do not authorize automated content extraction. Use email + RSS only. |
| **Nitter / Twitter scraping bridges** | Unreliable and ToS-violating. |
| **Free-tier news APIs that lack PIT timestamps** | Cannot honor N8 (PIT discipline) for backtesting. |

---

## 7. Signals Taxonomy and Actionability Bar

The single biggest revision from v1. v1 had two complaints, both true: signals were not rich enough, and signals were not focused/actionable. v2 fixes the second by giving the signals layer real structure, then expands the lanes.

### 7.1 Taxonomy (every evidence document is tagged on five axes)

1. **Source tier** — Official filing > Confirmed trade print > Market data > Provider-linked news > Email from paid subscription > RSS-only headline > Inferred-from-bars > Social/crowd
2. **Type** — News, insider buying/selling, institutional flow, abnormal volume, block trade, options flow, sentiment, earnings, polarity reversal, analyst rating change, quant rank change
3. **Scope** — Stock-specific or market-level
4. **Direction** — Bullish, bearish, neutral, mixed
5. **Verification level** — Confirmed (event happened, source authoritative) or Inferred (derived from price/volume patterns or weak-source signal)

The schema rule: a signal can be high-tier in source but inferred in verification (e.g., bar-derived abnormal volume from a confirmed Alpaca data feed). Both fields are stored separately, never collapsed.

### 7.2 Actionability Bar

Every signal lane has explicit thresholds before it can fire as actionable:

- **Minimum independent sources.** A signal type fires actionable only when at least N independent sources corroborate it (N=2 default for stock-specific events, N=1 for official filings, N=3 for inferred-only signals).
- **Freshness window per type.** News: hours. Earnings: days. Insider transactions: weeks. SEC fundamentals: per filing period. Pre/post-market: same session.
- **Deduplication.** A Zacks Rank change, a Seeking Alpha article, and an X post about the same earnings beat is *one* event — collapsed at ingestion based on (ticker, event-type, ~24h window) key. The aggregated event carries all source URLs.
- **Inferred signals are never sole basis for action.** The deterministic engine's evidence-breadth gate requires at least one confirmed-verification-level signal in addition to any inferred ones.

### 7.3 Lanes (v1 + the additions you specified)

| Lane | Source(s) | Tier | Verification | Actionable threshold |
|---|---|---|---|---|
| **News (general)** | Yahoo RSS, Google News RSS | RSS-only | Confirmed | Multiple sources + ticker-relevance score above floor |
| **News (paid sub)** | SA, Zacks, Investing.com via email/RSS | Paid-sub email | Confirmed | Single source OK if explicitly ticker-tagged |
| **SA Quant Rank changes** | SA Premium emails | Paid-sub email | Confirmed | Single source OK |
| **Insider transactions** | SEC Form 4 | Official filing | Confirmed | Single source OK |
| **Institutional flow** | SEC 13F | Official filing | Confirmed | Single source OK; lagged to quarter-end |
| **Earnings** | SEC + paid-sub calendar | Official filing | Confirmed | Single source OK |
| **Block trades** | TradeVision email alerts | Paid-sub email | Confirmed | Single source OK |
| **Unusual options activity** | TradeVision email; possibly yfinance options chains | Paid-sub email / RSS-only | Confirmed (TV) / Inferred (yfinance) | Confirmed: single OK. Inferred: needs corroboration. |
| **Abnormal volume / velocity** | Alpaca + yfinance bar data | Inferred-from-bars | Inferred | Never sole basis; needs confirmed corroboration |
| **Pre/post-market price + volume** | Alpaca free tier, yfinance | Free-tier | Confirmed (data) but inferred (signal) | Magnitude threshold + corroboration |
| **Pre-market trade prints** | Alpaca | Free-tier (limited) | Confirmed where available | Test lane; may degrade to "inferred" if free tier insufficient |
| **Options chain / IV** | yfinance options | RSS-only | Confirmed (data) but inferred (signal) | Magnitude threshold + corroboration |
| **X / Twitter** | X Basic API ($) or skip | Social/crowd | Inferred | Pending research justification (§6.3) |
| **Sector tailwind/pressure** | Sector ETFs + top constituents | Free-tier | Confirmed (when ETF + breadth pass) | ETF + breadth gate (v1's lesson) |
| **Macro regime** | Index data + breadth | Free-tier | Confirmed | Multi-sector breadth required |

### 7.4 Output to Downstream Engines

The Signals Engine emits a structured `EvidencePack` per ticker and per cycle, containing the actionable signals (passing the actionability bar), context-only signals (logged but not weighted), and suppressed signals (logged for audit, not sent to selection). The deterministic engine and LLM engine both consume the same EvidencePack — there is no asymmetry.

---

## 8. Phase Structure

v2 is a sequential project with explicit phase gates. Each phase produces deliverables; the next phase doesn't start until those are accepted.

### Phase 0 — Setup (1 week)

- Workspace, repo, tooling. Postgres, FastAPI scaffold, Docker Compose.
- Schema folder skeleton. Provenance type definition.
- This `v2-plan.md` accepted; `research-brief.md` accepted.

**Phase gate:** repo runnable; can persist a provenance-wrapped value end-to-end.

### Phase 1 — Research (4-8 weeks)

The work described in `research-brief.md`. Acquires PIT data, tests hypotheses, validates which signals add edge, produces realistic strategy profile.

**Phase gate:** research findings document with: validated/rejected signal lanes, baseline strategy profile (Sharpe, CAGR, max DD), realistic threshold ranges, recommended changes to v2 architecture.

### Phase 2 — Design (2-3 weeks)

- Update v2 architecture based on research findings.
- Final agent topology and contracts.
- All schemas defined and reviewed.
- Dashboard wireframes prototyped using Claude design tools and the web-artifacts-builder skill.
- Test plan written: unit, integration, end-to-end fixtures designed.

**Phase gate:** design doc accepted; schemas finalized; test plan written.

### Phase 3 — Build (8-12 weeks)

- Built engine-by-engine, schema-first, test-first.
- Order of construction: Universe Registry → Provenance Service → PIT Data Store → Fundamentals Engine → Market Regime Engine → Signals Engine → Deterministic Selection → LLM Selection → Final Selection → Risk → Execution preview → Portfolio Monitor → Learning.
- Dashboard built incrementally as each engine comes online.

**Phase gate:** all three test layers (N2) green for all components; dashboard usable.

### Phase 4 — Validate (2-4 weeks)

- Paper-trade runs in test mode against live data.
- User testing of every screen.
- Compare live deterministic decisions to research-phase backtest expectations.
- Adjust thresholds, fix gaps.

**Phase gate:** N1-N10 all confirmed in production.

### Phase 5 — Operate (ongoing)

- Production paper trading.
- Learning Engine accumulates outcomes.
- Threshold and weight calibration based on realized data.
- Research findings continuously revisited as new data arrives.

---

## 9. Open Questions Parking Lot

These are real questions to resolve, not blockers. Each has an owner (you or me) and a phase by which it should be resolved.

| # | Question | Owner | Resolve by |
|---|---|---|---|
| Q1 | Which X accounts would we follow if X ingestion is justified? List of handles + reason each is worth following. | User | Phase 1 |
| Q2 | What specific TradeVision alerts are configurable, and which map to v2's signal lanes? | User | Phase 1 |
| Q3 | What specific Zacks email digests are you subscribed to? | User | Phase 1 |
| Q4 | What specific SA Premium alerts are configurable? Quant changes confirmed; what else? | User | Phase 1 |
| Q5 | Options data — signal-only (informing equity decisions) or eventually traded? Confirmed signal-only for v2; flag if changes. | User | Phase 1 |
| Q6 | Is there an existing dedicated email inbox for paid-sub ingestion, or do we provision one? | User | Phase 0 |
| Q7 | Cloud bucket for backups — preferred provider? (S3, R2, B2, GCS) | User | Phase 0 |
| Q8 | Pi specs — Pi 4 8 GB confirmed, or Pi 5? | User | Phase 0 |
| Q9 | Frontend — confirm htmx-first approach, or preference for React from day one? | User | Phase 2 |
| Q10 | Strategy revision authority — research findings can revise v1's signal lanes (confirmed); can they also change the universe (S&P 100 + QQQ → other)? | User | Phase 1 |
| Q11 | Backtest cloud VM — Hetzner / Fly / AWS / other? Or restrict all backtesting to the Pi? | Me to recommend, User to confirm | Phase 1 |
| Q12 | The 3% weekly target — when research produces a realistic estimate, does the planning target adjust to match, or stay aspirational? | User | Phase 1 |

---

## 10. Document Maintenance

This document is a living artifact. Update when:

- A non-negotiable changes (rare; treat with care).
- Architectural decisions change.
- New agents/engines/services are introduced.
- New data sources are added or moved between status tiers.
- Phase structure shifts.
- Open questions are resolved.

Companion `research-brief.md` updates more frequently as research findings accrue.

---

*End of v2 Plan.*
