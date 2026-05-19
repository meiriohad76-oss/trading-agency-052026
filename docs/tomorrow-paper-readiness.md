# Tomorrow Paper Readiness

Date: 2026-05-11

## Verified

- Unit/e2e suite: `575 passed, 1 skipped`.
- Static quality: `ruff check .` passed; `mypy src research/src` passed.
- Full active-universe no-persist runtime cycle passed:
  - Output: `research/results/tomorrow-readiness/live-runtime-cycle-full-nopersist`
  - Evidence packs: 168
  - Signals: 719
  - WATCH candidates: 37
- UX smoke passed on desktop and mobile:
  - Output: `research/results/tomorrow-readiness/ux-smoke`
  - 12 route/viewport checks, no console errors, no horizontal overflow.
- Alpaca paper broker read passed:
  - Mode: paper
  - Account: ACTIVE
  - Exposure: 0%
  - Positions: 0
  - Open orders: 0
- LLM review guard smoke passed:
  - Output: `research/results/llm-review-live-fix`
  - Current `.env` key loaded successfully after repo-local dotenv override.
  - Bounded runtime smoke: `llm_prompt_status_counts={"succeeded": 1}`.
- Massive quota guard is working.
  - 2026-05-11 usage after readiness work: 87/100 requests used, 13 remaining.

## Data State

- `prices_daily`: active-universe coverage completed for runtime readiness.
- `stock_trades`: 17/168 active tickers covered, focused on liquid names:
  AAPL, MSFT, AMAT, AMD, AMZN, AVGO, COST, GOOG, GOOGL, HD, JPM, META, NFLX, NVDA, PLTR, TSLA, UNH.
- `sec_company_facts`: effectively complete, with one unresolved active-universe edge case.
- `sec_form4`: still partial at 10/168.
- `subscription_emails`: 108 retained evidence rows in parquet; latest narrow mailbox run produced manual-review rows but did not delete retained evidence.

## Blockers

- Docker Desktop/Postgres is not running from this shell. The app can serve directly, but persisted runtime cycles and the paper-review queue need Postgres.
- OpenAI LLM review is wired and passed a bounded live smoke. Keep candidate
  count low while testing because each reviewed candidate consumes tokens.
- `AGENCY_BROKER_SUBMIT_ENABLED=false`, so the agency will not submit paper orders until this is intentionally enabled.

## Pre-Market Steps

1. Start Docker Desktop from Windows with permission to run the Docker service.
2. Run `.\scripts\start_local_runtime.ps1` without `-SeedDemo`.
3. Confirm `http://127.0.0.1:8000/status/operational-readiness` is not blocked.
4. Run a persisted cycle:
   `.\.venv\Scripts\python scripts\run_live_runtime_cycle.py --config research\config\live-refresh.local.json --as-of 2026-05-08 --max-tickers 168 --persist --no-enable-llm-review`
5. Optional LLM sanity check:
   `.\.venv\Scripts\python scripts\check_openai_llm_review.py`.
6. Review the paper queue in the dashboard.
7. Keep live trading disabled. Enable paper submission only when ready:
   `AGENCY_BROKER_SUBMIT_ENABLED=true`,
   `AGENCY_REQUIRE_HUMAN_APPROVAL_FOR_ORDERS=true`,
   `ALPACA_ALLOW_LIVE_TRADING=false`.
