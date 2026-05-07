# T54: Candidate audit detail upgrade

**Owner:** codex
**Phase:** 2 (UX)
**Estimate:** small
**Dependencies:** T48, T51, T53

## Goal
Upgrade the candidate detail page into a mockup-inspired audit surface while keeping it
server-rendered and read-only.

## Outputs
- Candidate detail template converted to the shared shell.
- Selection report cards with deterministic, LLM, final, and risk summaries.
- Lifecycle audit timeline with JSON links for reports and events.
- Unit coverage for the upgraded empty state and helper output.

## Acceptance Criteria
1. `/candidates/{ticker}` keeps rendering empty report/event states.
2. The page shows report count, event count, latest action, and ticker.
3. Report rows expose deterministic and LLM decision details when present.
4. Existing JSON candidate timeline route remains untouched.
5. `ruff`, `mypy`, `pytest`, and PIT bypass guard pass.
