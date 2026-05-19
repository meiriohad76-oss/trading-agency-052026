# Full-Circle Agency Review - 2026-05-18

Review window: 2026-05-18, approximately 06:30-07:58 UTC.

Scope: command dashboard, all main dashboard screens, public status/API surfaces, agents/workers, Massive data lanes, paper-trading process, broker connection, LLM readiness, data freshness, UI health, and operational process behavior.

## Executive Summary

The agency is running with real configured sources and the Alpaca paper broker connected, but it is not cleanly paper-tradable at this review moment because multiple readiness surfaces disagree about execution readiness.

The most important finding is a readiness conflict:

- Full-live readiness reports `ready=true`, `review_operational_ready=true`, `tradable_ready=true`, `full_universe_tradable=true`, and `Ready For Full Live Cycle`.
- The scheduler execution gate reports `Context Only` because `daily-market-bars` and `massive-stock-trades` source-health rows are about 1h 35m old.
- Paper-review status reports `context_only_source_health`.

Until this is resolved, the command dashboard should be treated as the source of truth for execution gating, not full-live readiness alone.

## Evidence Commands

Fresh checks run during this review:

```powershell
.\.venv\Scripts\python scripts\check_operational_readiness.py --min-queue 1
.\.venv\Scripts\python scripts\check_paper_review_status.py --min-queue 1
.\.venv\Scripts\python scripts\check_openai_llm_review.py
.\.venv\Scripts\python -m pytest tests\unit\test_scheduler_work_queue.py tests\unit\test_scheduler_runner.py tests\unit\test_data_load_status.py tests\unit\test_full_live_readiness.py tests\unit\test_alpaca_broker.py tests\unit\test_execution_preview_service.py tests\unit\test_risk_service.py tests\unit\test_paper_trade_promotion.py -q
.\.venv\Scripts\python scripts\check_dashboard_live_data_qa.py
```

Observed results:

- Targeted unit tests: `163 passed`.
- OpenAI LLM diagnostic: `ready=true`, `status=succeeded`, model `gpt-4.1-mini`.
- Dashboard UI/live-data QA: one run failed due `/learning` timeout under load; immediate rerun passed with `failure_count=0`.
- Operational readiness: `ready=true`, `status_label=Operational With Attention`, `warning_count=3`.
- Paper-review status: `total_count=20`, `reviewed_count=2`, `pending_count=18`, `approve_count=2`, `verdict=context_only_source_health`.
- Broker: Alpaca paper connected, account `ACTIVE`, cash `98999.99`, buying power `198980.11`, one paper position in `CPRT`, no open orders.

## Critical Findings

| ID | Area | Severity | Finding | Evidence | Recommended Action |
| --- | --- | --- | --- | --- | --- |
| FCR-001 | Readiness gating | Critical | Readiness surfaces conflict. Full-live says tradable, scheduler and paper-review say context-only due source-health staleness. | Full-live `tradable_ready=true`; scheduler `Context Only`; paper-review `context_only_source_health`. | Make one execution-readiness truth source. Full-live readiness must include scheduler execution freshness gate, or clearly label itself as data coverage only. |
| FCR-002 | Source health | Critical | Critical source-health proof for `daily-market-bars` and `massive-stock-trades` aged out even though data-load says those datasets are ready. | Scheduler freshness checks block both critical sources at ~1h 35m old. | Refresh source-health heartbeat independently from data pulls; do not require a full data pull to prove closed-market freshness. |
| FCR-003 | Scheduler/process stability | High | Uvicorn stopped responding during review. Port 8000 had no listener and process 21424 was gone. Logs did not show a final fatal traceback. | `Test-NetConnection` failed; no listener; server restart required. | Add supervisor/restart wrapper and crash reason logging. Treat missing app heartbeat as a dashboard blocker. |
| FCR-004 | Scheduler concurrency | High | Scheduler logs show missed interval executions and `maximum number of running instances reached`. | Runtime stderr had missed jobs and max-instance skip. | Add explicit long-running tick state, command ETA, and backpressure policy in dashboard. Avoid starting new ticks while dashboard checks are heavy. |
| FCR-005 | Execution readiness | High | Execution preview has 0 orderable paper previews. Research approvals exist, but no paper order can be submitted. | Execution page shows `0 orderable paper previews`; submit gate closed; approved WATCH rows are research-only. | Keep this clear in command dashboard. Next paper trade requires source-health freshness, promotable BUY/SELL action, risk pass/warn, order sizing, hash-bound order approval, then broker submit. |

## Dashboard and Screen Review

| Screen | Status | Findings |
| --- | --- | --- |
| Command Dashboard `/` | Works, but needs attention | Page loads and health panels render. It correctly shows scheduler `Context Only`, Massive lanes, and refresh controls. The top-level operational wording can still confuse users because other readiness panels report tradable. |
| Signals `/signals` | Works, slow/heavy | Sequential load passed, but earlier timing was about 8.4s and page size about 844 KB. Needs pagination/lazy render. Health panel passed QA. |
| Universe & Market `/market-regime` | Works | Loads quickly and has data-health rows. Must surface that source-health proof may be stale even if daily bars are complete for the last closed market day. |
| Final Selection `/final-selection` | Works, heavy | Page size about 795 KB. Latest auto-refresh selection rows show `llm_action=null`, so current automatic cycle did not include LLM review even though OpenAI diagnostic is ready. |
| Candidate Detail `/candidates/NVDA` | Works | Health panel passes QA. Needs continued review for evidence specificity, but no rendering failure in this pass. |
| Risk `/risk` | Works | Sequential API is fast. Concurrent audit run timed out once, indicating server saturation risk under multi-page refresh. |
| Execution Preview `/execution-preview` | Works, context-only | Shows paper broker status and 168 paper artifacts, but 0 orderable previews. This is correct under current gates but should be prominent as a process blocker. |
| Portfolio Monitor `/portfolio-monitor` | Works | Alpaca paper broker reads are live and show one CPRT paper position. Portfolio data is real paper account data. |
| Learning `/learning` | Works after retry | Timed out once during concurrent Playwright audit, passed on rerun. Log as performance/concurrency risk. |
| Audit `/audit` | Works | Audit page renders. `/audit/agent-runs` timed out under concurrent review but sequentially recovered. |
| Policy `/policy` | Works | Renders with data-health panel. Needs alignment with execution gate wording so policy readiness is not mistaken for orderability. |

## Agent and Worker Review

| Agent / Worker | Current Status | Findings |
| --- | --- | --- |
| Scheduler work queue | Running after restart; context-only for execution | Automatic scheduler starts, but missed ticks and max-instance skips were logged. It currently reports 10 due jobs, 8 live-critical due, 3 support due, 2 repair due, and 1 Massive lane due. |
| Massive lane orchestrator | Partially ready | Lane model is active. Per-lane refresh button exists. `massive_premarket_trade_slices` is due and refresh-enabled. |
| Data load/readiness worker | Operational with attention | Core data coverage is 100%, but subscription emails are degraded/aging. Source-health freshness is not aligned with data-load readiness. |
| Alpaca broker worker | Connected | Paper account is ACTIVE, positions/open orders load, no live-trading evidence seen. |
| Portfolio monitor | Connected | Reads current paper account and position. No issue in this pass. |
| Human review worker | Operational | Queue has 20 candidates, 2 approved, 18 pending. Verdict is context-only due source health. |
| Risk worker | Operational | Risk service tests passed. Execution submit remains closed because no orderable rows and source-health gate is closed. |
| Execution preview / paper trade promotion | Functional but no executable trades | Produces previews, but all current rows are disabled/research-only or blocked from orderability. |
| LLM reviewer | Connected, not active in latest auto cycle | OpenAI diagnostic succeeded, but latest automatic selection rows show `llm_action=null`. Scheduler/runtime LLM enablement needs explicit confirmation. |
| Technical analysis worker | Ready/corroborating | `technical_analysis` lane is ready, sourced from Massive daily bars, but remains corroborating/inferred pending wider validation. |
| Market-flow workers | Data usable, derived-lane mismatch | Live trade slices show 168 fresh tickers, but several derived signal requirements still show `WAITING` on `massive_live_trade_slices`. This looks like a status interpretation bug or stale derived requirement view. |
| SEC company facts | Ready with small coverage gap | 167/168 active tickers loaded. Need identify the missing ticker and decide whether it is acceptable. |
| SEC Form 4 | Ready | 29,729 rows; ticker coverage is partial by nature. No blocker in this pass. |
| SEC 13F | Ready | 667 rows; not row-by-row universe coverage. No blocker in this pass. |
| RSS/news | Mostly ready but inconsistent | Data-load says `news_rss` ready; earlier data-source status showed `rss-news` stale. Needs freshness wording alignment. |
| Subscription email/article worker | Warning | `subscription_emails` degraded/aging, checked about 58,000 seconds ago. Article/login flow should be re-run before relying on this lane. |
| Options workers | Disabled | `options_flow` and `options_anomaly` are disabled until a real options provider is configured. Not a current blocker if policy treats them optional. |
| Activity alerts worker | Context-only/not configured | Importer exists, but no reliable provider selected. |

## Data Lane Review

| Lane | Status | Finding |
| --- | --- | --- |
| `massive_daily_bars` | Loaded / no pull needed | 168/168 coverage through 2026-05-15. Display health still says health check needed, and scheduler freshness gate says source-health row is stale. |
| `massive_live_trade_slices` | Loaded / no pull needed | 168/168 fresh tickers, manifest partial usable, 1,239,948 trade rows. Source-health proof still aged out. |
| `massive_premarket_trade_slices` | Refresh due | 10 fresh / 20 pending in next safe batch, refresh button enabled. This is the main active lane action. |
| `massive_block_trade_feed` | Ready from raw | Manifest partial usable. Derived signal requirement still says waiting on live slices, which conflicts with live slices status. |
| `massive_backtest_trade_tape` | Disabled / partial | 17% manifest coverage. Not a live blocker, but incomplete for research/backtesting. |
| `massive_reference` | Deferred | No reference puller is scheduled in the live decision loop yet. |
| `massive_options_flow` | Disabled | Options chains are not enabled in live config. |
| `subscription_emails` | Warning | Degraded/aging. Needs login/article extraction cycle. |
| `news_rss` | Ready in data-load | Freshness/status wording conflicts with earlier source-health row. |
| `sec_company_facts` | Ready, partial universe | 167/168 active tickers. Identify missing ticker. |

## Process Review

| Process | Status | Findings |
| --- | --- | --- |
| Live data extraction | Partially operational | Data is present and usable, but source-health heartbeat is stale. Premarket lane is due. |
| Full active-universe cycle | Present but not current-trading clean | Latest cycle is `auto-lane-refresh-20260518T062053Z` / `live-pit-2026-05-17-20260517T171449Z`; data as-of is 2026-05-15. This is acceptable for a closed-market baseline, but execution gate needs fresh proof. |
| Paper-review process | Context-only | Queue is populated, user approvals are recorded, but current source-health verdict prevents treating it as executable. |
| Paper execution process | Not orderable now | Broker is connected, but there are no orderable paper previews. |
| LLM process | Diagnostic ready | LLM can run, but latest automatic runtime artifacts do not show LLM review fields. |
| UI health | Mostly passed | Final Playwright QA pass found no forbidden terms, horizontal overflow, clipped controls, or missing health fields. One earlier run timed out under load. |
| Runtime supervision | Incomplete | Server process exited once without a clear fatal log. Needs a durable supervisor for live operation. |

## Prioritized Fix Plan

1. **Unify Execution Readiness**
   - Definition of done: full-live readiness, paper-review, scheduler gate, execution preview, and command dashboard all return the same execution-ready/context-only verdict for the same evidence snapshot.
   - Tests: add a unit/integration test where stale source-health makes all readiness surfaces context-only.

2. **Refresh Source-Health Heartbeats Without Full Pulls**
   - Definition of done: closed-market daily bars and latest trade-slice manifests can renew health proof when data is complete for the latest valid market session.
   - Tests: source-health rows remain fresh after heartbeat refresh; no Massive over-pull.

3. **Fix Market-Flow Derived Lane Requirement Status**
   - Definition of done: if `massive_live_trade_slices` is loaded/no-pull-needed with 168/168 fresh tickers, derived lanes that require it do not show `WAITING` unless there is a concrete missing manifest condition.
   - Tests: scheduler view rows for buy/sell pressure, unusual activity, market-flow trend, and block trade pressure reflect raw lane readiness correctly.

4. **Make Scheduler Runtime Durable**
   - Definition of done: app auto-restarts or clearly reports stopped state; Uvicorn crash/exit reason is persisted; dashboard shows app heartbeat and server process state.
   - Tests: simulated process restart updates dashboard health; missing heartbeat is a blocker.

5. **Turn On or Clearly Label LLM in Automatic Cycles**
   - Definition of done: automatic cycle either includes `llm_action`/`llm_confidence` when enabled, or dashboards explicitly label rows as deterministic/no-LLM.
   - Tests: a scheduler-triggered runtime cycle with LLM enabled writes prompt audit and selection report LLM fields.

6. **Resolve Subscription Email Aging**
   - Definition of done: user-login gated article extraction runs for the current session, updates manifest health, and writes ticker-specific article theses.
   - Tests: locked article triggers login-required workflow; successful login resumes article analysis.

7. **Performance Pass for Heavy Pages**
   - Definition of done: `/signals`, `/final-selection`, `/risk`, and `/execution-preview` load under 2 seconds locally and do not render hundreds of KB of unnecessary rows above the fold.
   - Tests: page timing script with budget thresholds; Playwright QA with concurrent polling.

8. **Complete Backtest and Optional Provider Lanes**
   - Definition of done: `massive_backtest_trade_tape` has a clear repair ETA and coverage goal; options lanes remain explicitly optional or are connected to a real provider.
   - Tests: lane manifests and dashboard status match configured policy.

## Current Operational Verdict

Review-operational: yes.

Paper-trading operational right now: not cleanly. Broker is connected, data coverage exists, and review queue is populated, but execution should remain context-only until the source-health/readiness disagreement is fixed and orderable previews are generated.

The next immediate operational action is to refresh or repair source-health proof for `daily-market-bars`, `massive-stock-trades`, and the due `massive_premarket_trade_slices` lane, then rerun the readiness checks and confirm every readiness surface agrees.
