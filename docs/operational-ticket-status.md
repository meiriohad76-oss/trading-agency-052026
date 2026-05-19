# Operational Ticket Status

Last updated: 2026-05-11

Scope: implement the first operational agency plan except T129-T132.

## Ticket Status

| Ticket | Status | Definition of Done | Test Status |
| --- | --- | --- | --- |
| T115 Persisted Runtime Validation | Implemented earlier; retained as operational gate | `run_live_runtime_cycle.py` can persist source health, evidence packs, selection reports, risk decisions, execution previews, lifecycle events, risk snapshots, execution states, and prompt audits when Postgres is available. | Covered by `test_runtime_cycle.py`; live Postgres rehearsal still requires Docker running. |
| T116 LLM Review Live Fix | Hardened and live-smoked | LLM review is opt-in, redacts prompts, writes prompt audit rows, fails safely to `NO_REVIEW`, and has a no-secret live diagnostic for key/model/provider failures. | Covered by `test_llm_review_service.py` and `test_openai_llm_check.py`; live check and bounded runtime smoke succeeded with the repo `.env` key. |
| T117 Alpaca Paper Execution Validation | Implemented earlier; guarded | Alpaca paper reads, snapshot persistence, paper-order submit/cancel/cleanup path, and broker audit events exist behind explicit env gates. | Covered by `test_alpaca_broker.py`, `test_broker_audit_service.py`, and `test_paper_broker_validation_script.py`; live market-hours trade test is manual/intentional. |
| T118 First-Version Paper Runbook | Hardened | The first-version pipeline now writes a durable JSON/Markdown run report for the operational runbook. | `test_ops_scripts.py` passed. |
| T119 Massive Active-Universe Coverage | Implemented earlier | Active-universe refresh planning is quota-aware and writes batch commands by dataset. | Covered by `test_active_universe_refresh_plan.py`; widening live data remains quota-paced. |
| T120 Market-Flow Calibration | Implemented earlier | Market-flow worker writes feature, IC, threshold, holdout, and calibration artifacts. | Covered by `test_market_flow_worker.py` and `test_market_flow_signals.py`; full validation waits for broader Massive history. |
| T121 Technical Analysis Calibration | Implemented earlier | TA worker writes feature, IC, threshold, pattern, and calibration artifacts. | Covered by `test_technical_analysis_worker.py`, `test_technical_analysis_signal.py`, and indicator tests. |
| T122 Email Evidence Agent v2 | Implemented earlier; still needs real-world quality passes | Email/article summaries are ticker-specific, distinguish direct vs secondary relevance, and feed `subscription_thesis` as context-only evidence. | Covered by `test_subscription_email_agents.py` and `test_subscription_thesis_signal.py`; more real email QA recommended. |
| T123 Signal Weight Promotion Gate | Implemented | `/status/lane-promotion` lists every lane as disabled, context-only, corroborating, or action-weighted with evidence needed for promotion. | `test_lane_promotion.py` passed. |
| T124 Agency Orchestrator v1 | Hardened | `run_first_version_pipeline.py` runs bounded email ingest, optional data refresh, runtime cycle, readiness check, and writes an auditable pipeline report. | `test_ops_scripts.py` passed. |
| T125 Scheduler / Monitor Service | Hardened | Scheduler has due-job execution and a machine-readable run summary; email monitor already supports once/continuous modes. | `test_runtime_scheduler.py` passed. |
| T126 Paper Decision Journal | Hardened | Human review events now accept reviewer reason and notes while preserving append-only candidate lifecycle audit semantics. | `test_human_review_service.py` and dashboard post test passed. |
| T127 Learning Feedback Agent | Hardened | Learning output now summarizes reviewed outcomes, return metrics, decision counts, and advisory recommendations while keeping auto-tuning disabled. | `test_portfolio_and_learning_services.py` passed. |
| T128 Portfolio Policy Controls | Hardened | Risk policy is env plus optional local JSON backed, and the Policy page displays the loaded controls used by runtime risk/execution previews. | `test_portfolio_and_learning_services.py` and `test_fastapi_app.py` passed. |
| T133 Secrets and Provider Health Console | Hardened | Operational key checks now explicitly require Massive/Polygon when Massive is active; provider readiness remains no-secret. | `test_operational_readiness.py` and `test_provider_readiness.py` passed. |
| T134 Daily Ops Report | Implemented | `write_daily_ops_report.py` writes a JSON/Markdown report covering readiness, providers, pipeline, latest cycle, broker validation, Massive quota, blockers, warnings, and next actions. | `test_daily_ops_report.py` passed. |

## Remaining Operational Caveats

- Docker/Postgres must be running to prove a new persisted cycle live from this shell.
- Live LLM review requires a valid OpenAI platform `OPENAI_API_KEY`; the checker
  blocks non-OpenAI-shaped values before runtime cycles and now makes the repo
  `.env` file win over stale shell/machine variables.
- Paper order submission stays disabled until the user intentionally enables the paper-submit env gates.
- Market-flow and technical-analysis promotion beyond corroborating/context levels requires wider Massive history and holdout evidence.
