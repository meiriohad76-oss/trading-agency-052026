# v2 Working Model

**Status:** Draft v0.1
**Owner:** Ohad Meiri
**Last updated:** 2026-05-06

How the human (you), OpenAI Codex (in VS Code), Claude Code (in VS Code), and me (in this Cowork session) collaborate to build v2. Read this first if you're picking up the project after a gap.

---

## 1. The Four Roles

### 1.1 Human (you)

- **Final authority on architecture, scope, and merge decisions.**
- Reviews every PR before merge to `main`.
- Resolves anything that requires judgment about your goals, your money, your risk tolerance, or your subscriptions.
- Owns the open-questions parking lot in `v2-plan.md` §9.
- Decides whether a ticket goes to Codex or Claude Code (default rules in §3 below).
- Drives the tickets queue: pulls a ticket, picks the executor, reviews the result, merges.

### 1.2 OpenAI Codex (heavy-lifting implementer)

Best for: clear specs, bounded scope, repetitive scaffolding, well-typed contracts, high-volume code.

- **Default executor for any ticket whose spec leaves no architectural ambiguity.**
- Bulk data pullers (yfinance, SEC EDGAR endpoints, sector ETFs).
- Per-lane signal generators (one per lane, given the formula spec).
- IC notebooks per lane (using utilities Claude Code wrote).
- Universe / horizon / threshold sweep runs.
- FastAPI route handlers, persistence layers, ETL plumbing.
- HTML templates, htmx interactions, dashboard widgets later.
- Routine refactoring inside an already-defined module.

Codex is excellent at *"do exactly this"* tasks. It is not the right tool for *"figure out how this should work."*

### 1.3 Claude Code (parallel architect + safety-critical implementer)

Best for: cross-cutting design, statistical correctness, components where one mistake invalidates downstream work.

- **Default executor for safety-critical or load-bearing components.**
- The PIT loader (every backtest depends on it being right).
- The Provenance type and external-API wrappers (every value carries provenance — getting this wrong silently corrupts the audit trail).
- IC computation, walk-forward backtest harness, cost/slippage model (statistical correctness, easy to get subtly wrong).
- Schema definitions and validators (the contracts both extensions reference).
- Risk gate, scarcity gate, broker submission gate (the bits that protect against bad trades).
- **Code review on every Codex PR.** Run Claude Code as a reviewer over each Codex branch before merge — fast feedback, second pair of eyes, catches the bugs the human reviewer would miss.

### 1.4 Me (Cowork session — planner and synthesizer)

- Writes ticket specs (in the format below) so Codex and Claude Code have unambiguous briefs.
- Synthesizes research findings at phase ends; updates `v2-plan.md` and `research-brief.md`.
- Refines architecture as findings come in.
- Prototypes UX surfaces using Claude design tools and the `web-artifacts-builder` skill when we reach Phase 2.
- Resolves cross-cutting questions and arbitrates between Codex and Claude Code outputs when they conflict.
- Does not write production code directly. (If a code spec needs sharpening, I sharpen the *spec*, not write the code.)

---

## 2. Repository Structure

Single Git repo. Branch protection on `main`.

```
stock-agency-v2/
  .github/
    workflows/        # CI: lint, type-check, test
  schemas/            # JSON Schemas for inter-agent contracts (canonical contracts)
  src/
    agency/           # production code, organized by engine/aggregator/service
    ...
  research/
    data/raw/         # raw API responses, raw RSS, raw emails (gitignored, large)
    data/parquet/     # cleaned, partitioned, columnar (gitignored, derived)
    data/manifests/   # one manifest per dataset (committed)
    src/
      pit/            # PIT data loader (THE source of truth for "what we knew when")
      signals/        # one signal-generator per lane
      backtests/      # walk-forward harness, performance metrics
      statistics/     # IC, IR, regression utilities
    notebooks/        # one notebook per hypothesis or per lane
    results/          # markdown writeups, plots, tables
  tickets/            # one .md per ticket; this is the backlog
  tests/              # pytest tests, organized by layer (unit / integration / e2e)
  docs/               # v2-plan.md, research-brief.md, working-model.md (this file)
  scripts/            # one-off utilities
  docker/             # Dockerfiles, docker-compose.yml
  .env.example        # config template
  pyproject.toml      # Python tooling (ruff, mypy, pytest)
  README.md
```

The four documents that live in `docs/`:

- `v2-plan.md` — strategic anchor (stable)
- `research-brief.md` — research phase plan (evolves weekly)
- `working-model.md` — this file (evolves as the working model is refined)
- (later) `findings.md` — research findings, produced at end of Phase 1

---

## 3. Branching and PRs

**Branch naming:**
- `feat/<ticket-id>-<slug>` for feature work (e.g. `feat/T07-sec-edgar-puller`)
- `fix/<short-slug>` for bug fixes
- `chore/<short-slug>` for non-functional changes (deps, lint, docs)

**Workflow:**
1. Pick a ticket from `tickets/` queue (lowest unblocked ID first; check `dependencies` field).
2. Decide executor: Codex by default; Claude Code if the ticket is marked `owner: claude-code` or it's safety-critical.
3. Create the branch.
4. Hand the ticket .md file to the chosen extension as the brief.
5. When the extension is done: review the diff yourself.
6. Run Claude Code as a reviewer over the branch (even if Codex wrote it). Fix anything flagged.
7. CI (`lint + type-check + test`) must pass.
8. PR to `main`. Title: `<ticket-id>: <ticket title>`.
9. Self-review the PR. Merge.
10. Mark the ticket completed (rename file: `T07-sec-edgar-puller.done.md` or move to `tickets/done/`).

**Conflict avoidance:**
- If two tickets touch the same file, the second one waits or is reassigned.
- Schema changes (`schemas/` folder) always go to Claude Code, never Codex, and are merged before any ticket that consumes the schema starts.
- The PIT loader is owned by Claude Code throughout Phase 1; Codex tickets that consume the loader treat it as a stable dependency.

---

## 4. Ticket Template

Every ticket in `tickets/` follows this shape:

```markdown
# T<NN>: <Imperative title>

**Owner:** codex | claude-code
**Phase:** 0 (setup) | 1 (research) | 2 (design) | 3 (build) | 4 (validate)
**Estimate:** small (< 2h) | medium (2-6h) | large (6h+)
**Dependencies:** T<NN>, T<NN>  (or "none")

## Goal
One sentence describing the outcome of the ticket.

## Context
Why this ticket exists and how it fits in the larger plan. Link to v2-plan.md or research-brief.md sections as needed.

## Inputs
- What data, files, or other artifacts the implementation reads or depends on.

## Outputs
- What this ticket produces: files, schemas, scripts, etc.
- Exact paths where outputs live.

## Acceptance Criteria
Specific, testable conditions that must be true for the ticket to be considered done. Numbered.

## Tests Required
- Unit tests: which functions, which edge cases.
- Integration tests (if applicable): which boundaries, which fixtures.
- Manual verification: steps the human runs to confirm the deliverable.

## Out of Scope
What this ticket explicitly does NOT do. (Prevents scope creep when handed to Codex.)

## Notes for Implementer
Anything Codex or Claude Code needs to know that isn't a spec but is important context (gotchas, prior decisions, source of truth links).
```

The template is the contract. If a ticket lacks any of these sections, it goes back to me to sharpen before being assigned.

---

## 5. Decision Rules — Codex vs Claude Code

When a ticket comes up, here's the routing default. The human can override.

| Ticket type | Default executor |
|---|---|
| Bulk data puller (one source) | Codex |
| Provenance type, schema definition | Claude Code |
| PIT loader, PIT-related infra | Claude Code |
| Per-lane signal generator (formula given) | Codex |
| IC computation, walk-forward harness | Claude Code |
| Notebook running an existing utility | Codex |
| Cost / slippage model | Claude Code |
| Risk gate, scarcity gate, submission gate | Claude Code |
| FastAPI routes, dashboard widgets | Codex |
| Refactor inside a defined module | Codex |
| Designing a new module's interface | Claude Code |
| Test fixtures and harnesses | Claude Code (design); Codex (additional cases) |
| Code review of Codex output | Claude Code |
| Code review of Claude Code output | Self-review + human |

If a ticket genuinely could go to either, prefer Codex (faster, cheaper, parallelizes well).

---

## 6. Schemas as the Source of Truth

Inter-engine contracts are versioned JSON Schemas in `schemas/`. Both extensions reference these as canonical.

**Rules:**
- Every schema has a `$id` and a semver version in the schema body.
- Schema changes are reviewed by Claude Code before merge, regardless of who proposed them.
- Schema PRs merge before any consumer of that schema starts work.
- Breaking changes bump the major version and cannot be merged while consumers are mid-work.

---

## 7. Testing Discipline

Three layers (from `v2-plan.md` non-negotiable N2). Phase 1 (research) doesn't exercise all three, but the harnesses for each are scaffolded in Phase 0 so tests can be added as production code lands.

**Layer 1 — Unit/integration:** `tests/unit/`, `tests/integration/`. Run on every PR. Required to merge.

**Layer 2 — Inter-agent data flow:** `tests/flow/`. One end-to-end ticker traversal per fixture. Run on every PR for components that touch boundaries.

**Layer 3 — User-flow / e2e:** `tests/e2e/`. Playwright (later, when dashboard exists). Run nightly.

---

## 8. Pre-Merge Checklist

Every PR must satisfy, before merge:

- [ ] Branch matches naming convention.
- [ ] Linked to a ticket; ticket's acceptance criteria all checked.
- [ ] CI green: lint, mypy/pyright, all relevant test layers.
- [ ] Claude Code review passed (if originally written by Codex).
- [ ] No new file > 500 lines without justification in PR description.
- [ ] No schema change without Claude Code review.
- [ ] No new external dependency without justification.
- [ ] No new paid data source without justification (per `v2-plan.md` N4).

---

## 9. Failure Modes To Watch

These are the ways this working model can go wrong. Read them before each major phase boundary.

- **Codex over-generating.** Codex will happily produce 3,000 lines when the ticket called for 300. Acceptance criteria + line-count discipline (item in §8) keep this in check.
- **Schema drift.** If a schema changes without all consumers updated, runtime errors appear days later. Schemas merge before consumers start, always.
- **PIT loader bypass.** A notebook that reads a parquet file directly will silently break PIT discipline. Tests in `tests/pit/` should fail any code that reads `research/data/parquet/` outside of the loader.
- **Two extensions touching the same file.** Avoid by single-writer-per-file rule per ticket; merge frequently.
- **Reviewer fatigue.** If you stop reading PRs because Codex produced 50 tickets in a week, the safety net is gone. Slow down the queue if needed.
- **Ticket bloat.** A ticket that takes more than its estimate by 2x is probably underspecified. Stop, return to me, sharpen the spec.

---

## 10. Working Cadence (suggested)

Daily: pull a ticket, hand it off, review the result, merge.
Weekly: review the tickets queue with me; reprioritize based on findings; update `research-brief.md` if findings change anything.
Phase boundary: full review of `v2-plan.md` for revisions; consolidated findings document; decide what's in the next phase's ticket batch.

---

*End of working model.*
