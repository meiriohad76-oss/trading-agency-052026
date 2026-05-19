# Operational Gap Analysis

**Status:** first-version paper workflow ready for review  
**Last updated:** 2026-05-10

## Working Now

- Local FastAPI dashboard, API health, metrics, audit, risk, execution preview,
  and candidate detail pages are running in paper-only mode.
- Live config readiness is green for the current local stack: Alpaca, SEC EDGAR,
  RSS, 13F CUSIP map, and Gmail subscription-email agents.
- A bounded subscription-email ingest path reads authorized Gmail messages,
  opens a capped number of linked articles, summarizes article thesis, and feeds
  `subscription_thesis` into the runtime as context-only evidence.
- The latest PIT runtime cycle is persisted and reviewable:
  `ready_for_paper_validation`, 10 selection reports, 5 WATCH candidates, and 0
  active source-health blockers.
- The Command dashboard now exposes an operational checklist and a readable
  card-based paper review queue.
- Alpaca paper-broker reads are implemented behind
  `AGENCY_ALPACA_BROKER_ENABLED`; the portfolio monitor can use real Alpaca
  paper positions, account equity, buying power, open orders, and exposure.
- Alpaca paper-order submission is implemented behind
  `AGENCY_BROKER_SUBMIT_ENABLED` and human-review approval. It remains disabled
  by default.

## Remaining Gaps

- Human review decisions are still pending for the latest paper queue. This is
  the only current operational-readiness warning.
- Market-flow lanes need real Massive/Polygon historical coverage before they
  can move beyond context-only guidance. T115 is the queued backtest.
- Options and dark-pool activity remain optional provider lanes. They should
  stay in backlog until a paid provider/export source is selected and validated.
- The LLM reviewer is still a future supervised review component. Current
  selection remains deterministic plus context summaries.
- Portfolio policy is still env/static rather than user-editable in the UI.
  Alpaca positions are read live; long-term position snapshots are not yet
  persisted as their own table.
- Production operation on the Pi still needs a final deployment rehearsal,
  backup check, and scheduled paper-cycle runbook.
- The learning loop needs several reviewed paper cycles before its outputs can
  affect thresholds or recommendations.

## Next Best Steps

1. Use the Command review queue to approve, defer, or reject the 5 current WATCH
   candidates.
2. Run the guarded pipeline after new data or subscription emails arrive:

   ```powershell
   .\.venv\Scripts\python scripts\run_first_version_pipeline.py `
     --email-max-emails 1 `
     --email-max-article-links 1 `
     --check-dashboard
   ```

3. After a Massive/Polygon key is available, run T115 on a small ticker/date
   sample, then widen only if coverage and cost look acceptable.
4. Keep activity/options providers planned until there is a concrete provider
   choice and a repeatable export/API path.
