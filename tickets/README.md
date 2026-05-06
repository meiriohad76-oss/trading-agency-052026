# Tickets Queue

Each `.md` file in this folder is a paste-ready ticket for Codex or Claude Code. Format follows the template in `docs/working-model.md` §4.

## Status convention

- `T<NN>-<slug>.md` — open ticket, ready to work
- `T<NN>-<slug>.in-progress.md` — currently being worked
- `T<NN>-<slug>.done.md` — merged to main; PR linked in commit

(Or move done tickets to `tickets/done/` if you prefer a folder split.)

## Dependency graph (current batch)

```
T01 (repo scaffold) ──┬─→ T02 (postgres+docker) [setup]
                      │
                      ├─→ T03 (provenance type) ──┬─→ T04 (PIT loader) ──┬─→ T05 (universe history)
                      │                            │                       │
                      │                            │                       ├─→ T06 (yfinance puller) ──→ T08 (sector ETFs)
                      │                            │                       │
                      │                            │                       └─→ T07 (SEC EDGAR puller suite)
                      │                            │
                      │                            └─→ T09 (IC utilities) ──→ T10 (walk-forward harness)
                      │
                      └─→ T09 (IC utilities also depends on T01)
```

## Current batch (Phase 0 + Days 1-8 of compressed research sprint)

| # | Title | Owner | Estimate | Phase | Depends |
|---|---|---|---|---|---|
| T01 | Scaffold the v2 repository | codex | small | 0 | none |
| T02 | Postgres + Docker Compose | codex | small | 0 | T01 |
| T03 | Provenance type and external-API wrapper | claude-code | medium | 0 | T01 |
| T04 | PIT data loader scaffold | claude-code | large | 1 | T01, T03 |
| T05 | Universe history reconstruction | codex | medium | 1 | T01, T04 |
| T06 | yfinance daily OHLCV bulk puller | codex | medium | 1 | T01, T03, T04, T05 |
| T07 | SEC EDGAR puller suite | codex | large | 1 | T01, T03, T04, T05 |
| T08 | Sector ETF puller | codex | small | 1 | T06 |
| T09 | IC and statistical utilities | claude-code | medium | 1 | T01, T04 |
| T10 | Walk-forward backtest harness | claude-code | large | 1 | T04, T09 |

## Suggested execution order with parallelism

**Wave 1 (start immediately, parallel):**
- T01 → unblocks everything else.

**Wave 2 (after T01, parallel):**
- T02 (codex)
- T03 (claude-code)

**Wave 3 (after T03, parallel):**
- T04 (claude-code) — sequential bottleneck for the data tickets
- T09 (claude-code) — can start in parallel with T04 since it only needs T01

**Wave 4 (after T04, heavy parallel):**
- T05 (codex)
- T06 (codex)
- T07 (codex)
- T08 (codex, after T06)
- T10 (claude-code, after T09)

If you push on Wave 4, T05+T06+T07 can run as three parallel Codex sessions. T10 runs in Claude Code at the same time. That's where the compressed timeline buys you the most days.

## Next batches (preview, not yet written)

- **T11-T20:** H1 signal generators — one ticket per lane (fundamentals factors, insider, institutional, sector momentum, abnormal volume, pre/post-market, options chains, news sentiment, paid-sub email parsers). All Codex once formulae are specified.
- **T21-T22:** H1 IC notebook generator + verdict synthesis tool.
- **T23-T25:** H4/H5 backtest runs and result writeups.
- **T26-T27:** H3 LLM-vs-deterministic comparison.
- **T28:** Phase 1 findings document + v2 Plan revision.

These will be drafted after the human has reviewed the first batch and confirmed the format works in practice.

## How to assign a ticket

1. Check the dependency column; only pick from tickets whose dependencies are completed (merged to main).
2. Open the ticket file; copy the entire contents.
3. Paste into Codex or Claude Code (per the `Owner:` field) as the brief.
4. Create branch: `feat/T<NN>-<slug>`.
5. Implement, review, merge per `working-model.md` §3.
6. Rename ticket to `.done.md` and commit.
