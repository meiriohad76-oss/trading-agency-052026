# T03: Provenance type and external-API wrapper

**Owner:** claude-code
**Phase:** 0 (setup)
**Estimate:** medium (2-6h)
**Dependencies:** T01

## Goal
Define the canonical Provenance type that every value in v2 carries, along with an `instrumented_call` wrapper that all external API/RSS/email-ingest code must use to produce provenance-wrapped values.

## Context
Non-negotiable N7 in `v2-plan.md` makes Provenance a first-class type. Every data value the system stores or acts on carries `(value, source, timestamp_observed, timestamp_as_of, freshness, confidence, verification_level)`. This is the base layer everything else builds on. A subtle bug here corrupts the audit trail silently, which is why this is Claude Code's, not Codex's.

## Inputs
- `v2-plan.md` §4.4 and N7 for the contract.
- `v2-plan.md` §7.1 for verification-level vocabulary.

## Outputs
- `src/agency/provenance/types.py`: pydantic v2 models for:
  - `SourceTier` enum: `OFFICIAL_FILING | CONFIRMED_TRADE_PRINT | PROVIDER_NEWS | PAID_SUB_EMAIL | RSS_HEADLINE | INFERRED_FROM_BARS | SOCIAL_CROWD`
  - `VerificationLevel` enum: `CONFIRMED | INFERRED`
  - `FreshnessStatus` enum: `FRESH | AGING | STALE | UNAVAILABLE`
  - `Provenance` model with all the N7 fields plus a `source_url: str | None` and a `source_id: str` (provider-specific identifier).
  - `Provenanced[T]` generic wrapper: `value: T` + `provenance: Provenance`.
- `src/agency/provenance/freshness.py`: `compute_freshness(timestamp_as_of, domain)` returning `FreshnessStatus`. Domains: `pricing`, `news`, `sec_fundamentals`, `sec_form4`, `sec_13f`, `broker`, `learning`. Each has its own freshness window (see `v2-plan.md` §7.1 of the v1 doc for windows; v2 freshness windows are defined in this module's docstring).
- `src/agency/provenance/instrumented_call.py`: an async context manager / decorator that wraps an external call, captures `timestamp_observed` and (optionally) `timestamp_as_of`, attaches the source metadata, and returns a `Provenanced[T]`.
- `schemas/provenance.schema.json`: JSON Schema mirroring the pydantic types for use across the OpenAPI contract.

## Acceptance Criteria
1. `Provenanced[T]` is generic and pickle-safe.
2. Every field of `Provenance` is required except `source_url` (nullable).
3. `compute_freshness` is pure (no I/O, no clock reads — clock is injected).
4. `instrumented_call` produces a `Provenanced[T]` with `timestamp_observed` set to the wall-clock time the call returned (not started).
5. `timestamp_as_of` defaults to `timestamp_observed` for live data; can be explicitly overridden for historical data (e.g., when ingesting an SEC filing dated 2022-06-30, `timestamp_as_of=2022-06-30`).
6. Round-trip: `Provenanced.model_dump()` → JSON → `Provenanced.model_validate()` is lossless.
7. JSON Schema in `schemas/` validates a serialized `Provenanced[dict]` instance.

## Tests Required
- Unit tests in `tests/unit/test_provenance.py`:
  - All enum values round-trip through JSON.
  - `compute_freshness` returns expected status across boundary cases (1 second old, 1 day old, 1 month old) per domain.
  - `instrumented_call` correctly records `timestamp_observed` and `timestamp_as_of`.
  - `Provenanced[int]`, `Provenanced[dict]`, `Provenanced[BaseModel]` all serialize/deserialize.
  - A `Provenanced` value with `verification_level=INFERRED` and `source_tier=OFFICIAL_FILING` is REJECTED at validation time (sanity rule: official filings are always confirmed; spell out the allowed combinations and enforce).
- Manual: write a one-liner that wraps `httpx.get(...)` with `instrumented_call` and prints the resulting `Provenanced` JSON.

## Out of Scope
- Persisting provenance to the database (separate ticket — schema design).
- The actual external API clients (yfinance, SEC EDGAR, etc.) — they consume this module.
- Audit history table (separate ticket).

## Notes for Implementer
- pydantic v2 is required (not v1). Use `model_validator` for the (source_tier, verification_level) compatibility rule.
- The freshness windows should be configurable via env vars but have sensible defaults (e.g., pricing fresh < 5 min, news fresh < 4 hours, SEC fundamentals fresh within current filing period).
- Use `datetime` with `tzinfo=timezone.utc` everywhere. No naive datetimes.
- Make `Provenanced` a `Generic[T]` using `typing.Generic` + pydantic v2 generics. Test the typing.
- Add a `__repr__` that shows the value and a short provenance summary, not the full provenance blob.
