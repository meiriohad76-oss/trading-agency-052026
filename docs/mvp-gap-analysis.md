# Trading Agency v2 — MVP Gap Analysis & Implementation Plan
**Date:** 2026-05-16  
**Scope:** Independent cross-domain audit vs. full paper-trading MVP  
**Source:** 5 parallel audit agents + attached process-agent status report  

---

## Executive Summary

The agency runtime is **structurally complete**: all templates, routes, API endpoints, and startup scripts exist. A live paper cycle is running (168 tickers, 2026-05-16). However, **zero orders are submittable** due to three layered gates that are all closed simultaneously:

1. **No ALLOW risk decisions** — WATCH candidates are permanently WARN by design; no promotion path exists
2. **broker_submit_enabled = False** — policy gate hardcoded off
3. **DB session unavailable** — Supabase credentials missing; paper review recording and portfolio persistence fail silently

Beyond the execution gate, 12 of 16 signal lanes are blocked by missing data manifests, and the LLM reviewer is inactive (env gate + API key not set). The dashboard itself is MVP-ready with no missing routes or templates.

**Verdict:** Not yet a full paper-trading MVP. Estimated 6–8 focused implementation tasks to reach end-to-end paper trade submission.

---

## P0 — Critical: Blocks Paper Trading Entirely

### P0-A: No code path from WATCH → ALLOW (risk decision promotion)

**Problem:** All 17 WATCH candidates have `risk_decision = WARN` (not ALLOW), producing `submit_enabled = False` on all 168 previews. This is by design in `risk.py:415-416`:
```python
if action in REVIEW_ACTIONS:  # WATCH, HOLD
    return _check("final_action", "WARN", f"{action} is review-only")
```
WARN decisions produce BLOCKED previews in `execution_preview.py:185-190`. Only ALLOW → READY → submit_enabled=True.

**Root cause files:**
- `src/agency/services/risk.py:335-417` — `build_risk_decision()`; no ALLOW path for WATCH
- `src/agency/services/execution_preview.py:185-190` — `_preview_state()` only returns READY on ALLOW
- `src/agency/services/human_review.py:42,144-182` — `build_order_approval_event()` exists but has no consumer that flips risk decision

**What Codex must implement:**
1. Add a `promote_watch_to_allow(ticker, cycle_id)` function in `risk.py` that takes a recorded APPROVE review event and upgrades the risk decision from WARN to ALLOW in the selection report or a side-table.
2. Wire this promotion into the human review POST handler in `src/agency/api/dashboard.py` (the `/candidates/{ticker}` POST route) — after recording an APPROVE event, call `promote_watch_to_allow`, re-compute the execution preview, and persist the new submit_enabled=True preview.
3. Update `execution_preview.py` to accept an overridden risk decision when a human approval is on record.

**Acceptance criteria:**
- Approving a WATCH candidate in the dashboard changes its preview to `submit_enabled=True`
- The paper_broker_validation script reports ≥1 orderable preview after approving 1 WATCH candidate

---

### P0-B: broker_submit_enabled defaults to False — no policy toggle path

**Problem:** `PortfolioPolicy.broker_submit_enabled` defaults False (`risk.py:51`). Even if a candidate reaches READY state, `submit_enabled` in `execution_preview.py:120-127` stays False because the policy gate is never True. The dashboard policy edit UI exists but the DB persistence path for this field is gated behind Supabase being available (P0-C).

**Root cause files:**
- `src/agency/services/risk.py:51` — default `broker_submit_enabled = False`
- `src/agency/services/execution_preview.py:120-127` — ANDs policy gate into submit_enabled
- `src/agency/api/dashboard.py` (risk/policy POST routes) — updates policy JSON but requires DB

**What Codex must implement:**
1. Add a `AGENCY_BROKER_SUBMIT_ENABLED=true` env var override that bypasses the DB policy field for local paper testing (fallback for when DB is unavailable)
2. Ensure the policy edit UI on `/policy` correctly persists `broker_submit_enabled` to DB once DB is live (verify `_patch_portfolio_policy()` in dashboard API covers this field)
3. Document the exact env var in `docs/deployment.md` and `scripts/start_local_runtime.ps1`

**Acceptance criteria:**
- Setting `AGENCY_BROKER_SUBMIT_ENABLED=true` in `.env` and restarting produces `broker_submit_enabled: true` in policy
- Policy page toggle also persists change when Supabase is available

---

### P0-C: Database session unavailable — portfolio persistence and paper review fail

**Problem:** `persist_portfolio_snapshot()` and paper review event recording both silently fail when Supabase credentials are not set. `record_portfolio_snapshot()` and all session-dependent services throw `MissingDatabaseConfigurationError` or SQLAlchemy connection errors. This means review decisions never persist, and the APPROVE flow (needed for P0-A) cannot work.

**Root cause files:**
- `src/agency/services/broker_audit.py:201-209` — DB session gate
- `scripts/run_paper_broker_validation.py:273-283` — catches OSError, SQLAlchemy error, returns "unavailable"
- `src/agency/database.py` or `alembic.ini` — Supabase URL configuration

**What Codex must implement:**
1. Add a SQLite fallback for local dev when `DATABASE_URL` is not set to a Postgres/Supabase URL — use `sqlite:///./trading_agency_local.db` as default
2. Run Alembic migrations against the SQLite database on startup so all tables exist
3. Document in `docs/deployment.md`: "For local paper testing without Supabase, set `DATABASE_URL=sqlite:///./trading_agency_local.db`"

**Acceptance criteria:**
- `scripts/start_local_runtime.ps1` starts without requiring Supabase credentials
- Paper review APPROVE event is persisted to DB (SQLite or Supabase)
- Portfolio snapshot is recorded after running `run_paper_broker_validation.py`

---

## P1 — High: Major Feature Gaps

### P1-A: 12/16 signal lanes blocked — 4 missing data manifests

**Problem:** `ManifestRegistry.require()` (called at signal evaluation time) has no bypass — it throws `DataNotAvailableAt` immediately if the manifest JSON does not exist. Four datasets have no manifest:

| Dataset | Signals blocked |
|---------|----------------|
| `sector_etfs` | sector_momentum |
| `insider_transactions` | insider, subscription_thesis |
| `fundamentals` | fundamentals |
| `institutional_holdings` | institutional |

Additionally: `options_anomaly`, `options_flow`, `news`, `activity_alerts` are blocked (likely manifests missing or data absent).

**Root cause files:**
- `research/src/pit/loader.py` — `ManifestRegistry.require()` and default paths
- `research/data/manifests/` — only 8 manifests exist: `prices_daily.json`, `stock_trades.json`, `sec_form4.json`, `news_rss.json`, `sec_company_facts.json`, `sec_13f.json`, `universe_membership.json`, `subscription_emails.json`

**What Codex must implement:**
1. Write a `scripts/generate_manifests.py` script that scans `research/data/parquet/{dataset}/` directories and generates the missing manifest JSON files with correct `row_count`, `max_timestamp_as_of`, `fetched_at`, and `stale_after` fields. Manifest schema: `{"dataset": str, "path": str, "schema_version": str, "row_count": int, "checksum": str, "fetched_at": ISO8601, "max_timestamp_as_of": ISO8601, "stale_after": int_seconds, "source_url": str}`
2. Create stub manifests for datasets that have no parquet data yet (sector_etfs, insider_transactions, fundamentals, institutional_holdings) with `row_count: 0` and `stale_after: 0` so ManifestRegistry can load them without error (mark as STALE, not crash)
3. Update ManifestRegistry to treat row_count=0 as a "data absent, lane disabled" result rather than a hard exception — return `DataAbsent` signal result instead of raising

**Acceptance criteria:**
- `python research/scripts/run_h1_ic.py --all-signals --start 2022-01-01 --end 2025-12-31` runs to completion without ManifestRegistry exceptions
- Signals with no backing data return a DataAbsent result (not crash)
- Signals with data (abnormal_volume, technical_analysis, block_trade_pressure) produce IC results

---

### P1-B: LLM reviewer inactive — all 168 candidates show NO_REVIEW

**Problem:** LLM review is gated behind `AGENCY_ENABLE_LLM_REVIEW=true` env var AND a valid `OPENAI_API_KEY`. Both are unset. `build_llm_review_stub()` in `llm_review.py:269` is the active code path, always returning `NO_REVIEW`. This means the LLM reasoning column in candidate detail is always empty and no signal promotion via LLM occurs.

**Root cause files:**
- `src/agency/services/llm_review.py:113-121` — env gate
- `src/agency/services/llm_review.py:29-32` — API key check
- `src/agency/services/final_selection.py:106-111` — uses stub return

**What Codex must implement:**
1. Add `AGENCY_ENABLE_LLM_REVIEW` and `OPENAI_API_KEY` to `.env.example` with clear instructions
2. Add a `/status/llm-review` health endpoint that returns current LLM provider state (enabled/disabled/no-key) — surface this on the Command dashboard
3. When LLM is disabled, show "LLM review disabled — set AGENCY_ENABLE_LLM_REVIEW=true" placeholder text in the candidate detail LLM reasoning section instead of blank

**Acceptance criteria:**
- Setting `AGENCY_ENABLE_LLM_REVIEW=true` + `OPENAI_API_KEY=sk-...` in `.env` produces non-empty LLM review results in the next cycle
- `/status/llm-review` returns `{"enabled": false, "reason": "env gate off"}` when disabled

---

### P1-C: HTTP app reports "Connection refused :8000" in status doc

**Problem:** The attached status report shows `http_app: Connection refused :8000`. The startup script `scripts/start_local_runtime.ps1` requires Docker Postgres and runs Alembic migrations before starting uvicorn. If Docker is not running or Postgres health check times out, uvicorn never starts.

**What Codex must implement:**
1. Add `scripts/start_local_dev.ps1` — a lighter startup script that starts uvicorn directly without Docker dependency (using SQLite fallback from P0-C), for fast local iteration
2. Add a `/health` smoke check to `start_local_runtime.ps1` that prints a clear error message if uvicorn fails to start (currently times out silently)
3. Add `make dev` / `make start` convenience targets in a `Makefile` or `README.md` quickstart section

**Acceptance criteria:**
- `python -m uvicorn src.agency.app:app --port 8000` starts successfully without Docker when `DATABASE_URL=sqlite:///...` is set
- `/health` returns 200 within 5 seconds

---

### P1-D: Massive lane target accounting — incorrect ticker count in runtime

**Problem:** Status report notes "Massive lane target accounting incorrect." Runtime uses 168 tickers but parquet price data covers 243 tickers. Universe membership JSON governs which tickers enter the cycle, but Live Config readiness reports coverage warnings.

**Root cause files:**
- `research/data/manifests/universe_membership.json` — ticker universe definition
- `research/src/live_runtime/config.py` — runtime_universe and runtime_max_tickers settings
- `research/src/live_runtime/freshness.py` — coverage reporting

**What Codex must implement:**
1. Reconcile `universe_membership.json` with actual parquet price data coverage — run `python scripts/generate_manifests.py` (from P1-A) and update the universe membership to include all 243 tickers with prices data
2. Set `runtime_max_tickers=243` in `research/config/live-refresh.example.json` to match actual data coverage
3. Add a warning in the Live Config readiness check when `runtime_max_tickers > len(tickers_with_prices_data)` or vice versa

**Acceptance criteria:**
- Live Config readiness shows no universe coverage warning
- Runtime cycle covers all tickers present in prices parquet data

---

## P2 — Medium: Important But Not Blocking

### P2-A: sec_form4 timeout — insider signal unreliable

**Problem:** Status doc reports `sec_form4: timeout` during live data refresh. The SEC EDGAR client hits rate limits or network timeouts for bulk Form 4 fetches.

**Root cause files:**
- `research/src/sec/client.py` — EDGAR HTTP client, timeout settings
- `research/src/sec/form4.py` — Form 4 fetch loop

**What Codex must implement:**
1. Add exponential backoff with jitter to `research/src/sec/client.py` HTTP calls (currently no retry logic assumed)
2. Add per-request timeout of 30s and a maximum total runtime cap of 5 minutes for the sec_form4 refresh job
3. Write partial results to parquet on timeout rather than discarding the batch

**Acceptance criteria:**
- `run_data_refresh_batch.py` completes the sec_form4 job without hanging indefinitely
- Partial Form 4 data is preserved if a timeout occurs midway

---

### P2-B: Article browser session not configured — paid subscription fetch fails

**Problem:** `BrowserArticleSession.__init__()` raises `BrowserSessionUnavailableError` immediately when neither `article_browser_state_dir` nor `article_browser_cdp_url` is configured. Subscription email article fetching (Seeking Alpha, TradeVision, Zacks) is entirely disabled.

**Root cause files:**
- `research/src/subscription_email/article_session.py:78-79`
- `research/config/subscription-email.example.json` — config keys

**What Codex must implement:**
1. Add `ARTICLE_BROWSER_CDP_URL` and `ARTICLE_BROWSER_STATE_DIR` to `.env.example` with placeholder values and instructions for setting up a local Playwright session
2. Add a `scripts/setup_browser_session.py` helper that launches a headed Chromium browser and saves the authenticated session state to `article_browser_state_dir`
3. When browser session is unavailable, the subscription email pipeline should degrade gracefully — skip article body fetch and use subject/snippet only (currently crashes the lane)

**Acceptance criteria:**
- Subscription email pipeline runs without exception when browser session is unconfigured (degrades to subject-only)
- `scripts/setup_browser_session.py` produces a valid session state file for Playwright reuse

---

### P2-C: PITLoader data path — RESOLVED by Audit 1

**Finding:** Audit 1 (data sources) confirmed PITLoader correctly uses `research/data/parquet` and `research/data/manifests` as defaults, and data IS present there. Audit 1 verified `prices_daily.json` manifest exists and 242 tickers are present. The earlier session investigation error (`missing research\data\manifests\prices_daily.json`) may have been caused by running from a different working directory.

**What Codex must implement:**
1. Add a guard in `research/scripts/run_h1_ic.py` that prints a clear error if the working directory is not the repo root (i.e., `research/data/parquet` is not found relative to CWD) rather than raising a raw exception
2. Add `assert_data_root()` helper at top of all `run_*.py` scripts that validates `parquet_root` exists

**Acceptance criteria:**
- Running `research/scripts/run_h1_ic.py` from any directory produces a clear "run from repo root" message if data path is wrong

---

### P2-D: N2 test plan references 4 non-existent test files

**Problem:** Audit 5 found that `docs/n2-test-plan.md` lists these files as ✅ but they do not exist on disk:
- `test_pit_integration.py`
- `test_buy_sell_pressure_signal.py`
- `test_block_trade_pressure_signal.py`
- `test_activity_alerts_signal.py`

These were likely consolidated into broader test files (`test_market_flow_signals.py`, etc.) during a refactor.

**What Codex must implement:**
1. Update `docs/n2-test-plan.md` to reflect actual test file names (map to `test_market_flow_signals.py`, `test_activity_alert_signal.py`, etc.)
2. Add `test_pit_integration.py` as an actual integration test that loads PITLoader with real parquet files and validates row count / date range
3. Mark `result_batch.py` integration test gap as P2 open ticket

**Acceptance criteria:**
- Every ✅ in N2 test plan maps to a file that exists on disk
- `python -m pytest tests/integration/test_pit_integration.py` passes

---

### P2-E: result_batch.py has no integration test against real parquet data

**Problem:** `research/src/evaluation/result_batch.py` is covered only by unit mocks. N2 plan documents this gap as open. The batch runner is on the H1 IC critical path.

**What Codex must implement:**
1. Write `tests/integration/test_result_batch_integration.py` that:
   - Loads a real signal result from `data/parquet/prices_daily/` (or test fixture parquet)
   - Runs `result_batch.py` batch evaluation
   - Asserts output schema matches expected columns (ticker, date, ic, t_stat)

**Acceptance criteria:**
- Integration test passes with real parquet data
- CI pipeline runs the test (pytest finds it in `tests/integration/`)

---

### P2-F: Backtest trade tape at 17% coverage — 839 ticker-days unrepaired

**Problem:** Audit 1 found the backtest stock-trade tape has only 17% parquet coverage, with 839 ticker-days flagged as requiring repair. This blocks historical backtests (H1 IC evaluation) for block_trade_pressure and related market-flow signals across the full date range.

**Root cause:** Massive historical trade pull likely failed or was only partially completed. `_coverage.json` tracks repair-needed entries.

**What Codex must implement:**
1. Run `python research/scripts/pull_massive_stock_trades.py --repair` (or equivalent repair flag) to fill the 839 missing ticker-days
2. Add a coverage health check to `scripts/check_operational_readiness.py` that fails when backtest tape coverage < 80%
3. After repair, regenerate `research/data/manifests/stock_trades.json` via `generate_manifests.py`

**Acceptance criteria:**
- Backtest tape coverage ≥ 80% (measured by `_coverage.json`)
- H1 IC evaluation for `block_trade_pressure` runs to completion with ≥ 2 years of data

---

### P2-G: SEC 13F institutional data 3+ months stale

**Problem:** Audit 1 found `sec_13f` manifest shows last data as 2026-02-17 (fetched 2026-05-09 — the data itself is 3+ months behind). The institutional signal relies on 13F filings to detect large position changes. With data this stale, the signal produces no meaningful current-quarter positioning.

**Root cause files:**
- `research/src/sec/client.py` — EDGAR 13F fetcher
- `research/data/manifests/sec_13f.json` — stale timestamp

**What Codex must implement:**
1. Add 13F to the scheduled weekly refresh in `research/scripts/run_data_refresh_batch.py`
2. Update `research/src/sec/client.py` to fetch the most recent available 13F quarter (2025 Q4 or 2026 Q1 if available)
3. Add staleness alert to `docs/data-provider-recommendations.md`: "13F data is quarterly; set `stale_after` to 90 days"

**Acceptance criteria:**
- `sec_13f` manifest shows `max_timestamp_as_of` within the last 90 days
- `institutional` signal evaluation produces non-zero row count for recent quarters

---

### P2-H: Massive lane coverage mismatch — premarket/block at 50 tickers vs 168 target

**Problem:** Audit 1 found:
- `massive_live_trade_slices`: 94/168 tickers
- `massive_premarket_trade_slices`: 50/168 tickers  
- `massive_block_trade_feed`: 50/168 tickers

If MVP requires full 168-ticker visibility for premarket gaps and block print signals, these lanes are incomplete for 118 tickers (70%).

**What Codex must implement:**
1. Expand coverage through lane-owned jobs: `massive_premarket_trade_slices` for premarket latest slices, `massive_live_trade_slices` for current-day prints, and `massive_block_trade_feed` derived from the live slice lane.
2. Update `_coverage.json` tracking to show per-mode coverage %
3. Document minimum coverage threshold (suggest: ≥ 80% of target universe) in `docs/data-provider-recommendations.md`

**Acceptance criteria:**
- Premarket and block trade coverage ≥ 80% of 168-ticker target universe
- Coverage reported in `/status/live-readiness` or `check_operational_readiness.py`

---

## P3 — Low: Quality and Completeness

### P3-A: T126 documentation fix — already DONE in CI

**Problem:** `docs/phase-status.md` and `docs/n2-test-plan.md` list T126 (PIT bypass guard as hard CI failure) as still open. Audit 5 confirmed CI `.github/workflows/ci.yml` runs `scripts/check_pit_bypass.py` and fails on exit code 1. T126 is complete.

**What Codex must implement:**
1. Update `docs/n2-test-plan.md` T126 entry from open → ✅
2. Update `docs/phase-status.md` Open Gaps list to remove T126

---

### P3-B: LLM review disabled state not surfaced in dashboard

**Problem:** The Command dashboard shows no indicator when LLM review is inactive. Users see 168 empty LLM columns with no explanation.

**What Codex must implement:**
1. Add an `llm_review_status` field to `dashboard_context()` in `command.py`
2. Show a one-line warning banner in `dashboard.html` when `llm_review_status.enabled == false`

---

### P3-C: No paper submission endpoint exists

**Problem:** Audit 2 found that `build_order_approval_event()` in `human_review.py` exists but there is no function that consumes it and submits a paper order to Alpaca. The execution chain is: preview → approval event → ??? → Alpaca paper order.

**Note:** This is lower priority than P0-A because P0-A (WATCH→ALLOW promotion) must exist first. Once a candidate reaches READY + submit_enabled=True, this endpoint completes the chain.

**What Codex must implement:**
1. Add `submit_paper_order(order_approval_event) -> OrderResult` in `src/agency/services/broker_audit.py`
2. Wire it to a POST `/execution-preview/{ticker}/submit` endpoint in `execution.py` view
3. Guard with `broker_submit_enabled` check and human approval event hash verification (already defined in `build_order_approval_event()`)
4. Log paper order to execution audit history

**Acceptance criteria:**
- End-to-end: WATCH candidate → human APPROVE → ALLOW risk → READY preview → submit → Alpaca paper order logged

---

## Implementation Order for Codex

Execute in this order to unlock the critical path soonest:

```
P0-C → P0-A → P0-B → P1-C → P1-A → P1-B → P1-D → P2-F → P2-H → P3-C → P2-A → P2-B → P2-G → P2-D → P2-E → P2-C → P3-A → P3-B
```

**First milestone** (P0-C + P0-A + P0-B + P1-C): Server starts locally without Docker, DB persists review events, one WATCH candidate can be approved and reaches submit_enabled=True.

**Second milestone** (+P2-C + P1-A): All runnable signals produce IC results; H1 can be evaluated end-to-end.

**Third milestone** (+P1-B + P1-D + P3-C): LLM reviewer active, universe reconciled, paper orders submit to Alpaca.

---

## Verified Facts (Audit Cross-Check vs Status Doc)

| Claim in status doc | Audit finding |
|---------------------|---------------|
| 168 tickers, 17 WATCH, 151 NO_TRADE | ✅ Confirmed via `live-runtime-cycle-summary.json` |
| 0 orderable previews | ✅ Confirmed — root cause: WATCH→WARN, no ALLOW path |
| 8 WARN, 160 BLOCK risk decisions | ✅ Confirmed |
| HTTP app Connection refused :8000 | ✅ Confirmed — Docker/uvicorn startup dependency |
| sec_form4 timeout | ✅ Confirmed — no retry/backoff in client |
| Paid article login failure | ✅ Confirmed — browser session not configured |
| DB session unavailable | ✅ Confirmed — Supabase credentials missing |
| T126 (PIT bypass guard) still open | ❌ **INCORRECT** — CI enforces it; T126 is complete |
| 941 tests green | ⚠️ Partially: 4 test files in N2 plan don't exist; likely consolidated |
| Portfolio snapshot persistence "unavailable" | ✅ Confirmed — DB session gate |
