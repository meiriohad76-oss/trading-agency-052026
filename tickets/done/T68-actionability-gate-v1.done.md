# T68: Actionability gate v1

**Owner:** codex
**Phase:** 2/3 provisional runtime scaffolding
**Status:** done

## Goal

Apply explicit actionability rules before signals enter deterministic and LLM selection.

## Delivered

- Added `src/agency/services/actionability_gate.py`.
- Wired the gate into `build_evidence_pack`.
- Enforced per-lane source-count rules, stale/unavailable freshness downgrades,
  duplicate source suppression, and confirmed corroboration for inferred signals.
- Updated evidence-pack data quality to summarize usable evidence only.
- Added focused unit tests for official lanes, news corroboration, duplicates,
  stale/unavailable handling, inferred corroboration, and custom lane rules.

## Acceptance Notes

1. Official filing lanes can pass with one confirmed source.
2. News requires two independent sources before it is actionable.
3. Inferred signals cannot be actionable without confirmed corroboration.
4. Suppressed duplicate/unavailable signals remain in the audit trail.
