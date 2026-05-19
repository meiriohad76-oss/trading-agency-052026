# T136: Leveraged Alternative Review Advisor

**Owner:** codex
**Phase:** 4 (operate)
**Estimate:** medium
**Dependencies:** T90, T95, T117, T128
**Status:** backlog

## Goal
When a stock candidate has very high buy conviction and strong evidence, present
the user with supervised leveraged alternatives for review: available 2x/3x
single-stock leveraged ETFs where listed, or defined-risk option structures that
approximate leveraged exposure.

## Context
The agency currently focuses on stock paper-review candidates and guarded Alpaca
paper execution previews. For exceptional long candidates, the user wants the
agency to show higher-beta alternatives without automatically increasing risk.

Leveraged ETFs and options are materially riskier than stock purchases. This
ticket must keep the feature advisory and paper-only until the user explicitly
approves strategy, broker support, sizing rules, and risk limits. The default
implementation should prefer explainable, bounded-risk alternatives and should
never suggest naked option writing as an automatic action.

## Trigger Conditions
- Candidate final action is `BUY` or an approved/promotable `WATCH`.
- Final conviction is at least `0.85`.
- Evidence pack has strong signal breadth:
  - at least 2 independent usable sources
  - at least 2 confirmed or corroborating signals
  - no hard policy gate blockers
  - source freshness is `FRESH` or explicitly accepted by policy
- Portfolio policy allows leveraged-alternative review.

## Inputs
- Latest `SelectionReport`, `EvidencePack`, `RiskDecision`, and human review
  state for the candidate.
- Portfolio policy values from `.env` and/or
  `research/config/portfolio-policy.local.json`.
- Broker account and positions from Alpaca paper.
- Leveraged ETF mapping data:
  - static curated mapping file for known single-stock 2x/3x ETF products, and
  - optional provider-backed symbol search later.
- Option-chain data for the underlying stock when option alternatives are
  enabled.

## Outputs
- New service, for example
  `src/agency/services/leveraged_alternatives.py`.
- Optional config file, for example
  `research/config/leveraged-alternatives.example.json`.
- Dashboard display on candidate detail and execution preview pages:
  - stock baseline order
  - 2x/3x ETF alternatives when available
  - defined-risk option alternatives when available
  - why each alternative is or is not eligible
  - leverage/risk warnings and estimated max loss
- New schema or typed payload if needed, for example
  `schemas/leveraged-alternative.schema.json`.
- Unit tests for eligibility, ETF lookup, option-strategy construction, and
  risk blocking.

## Alternative Types
- **Leveraged single-stock ETF:** show ticker, leverage factor, issuer, expense
  ratio when known, daily-reset warning, liquidity warning, and whether the
  product is available to the broker.
- **Defined-risk long option exposure:** show long call or call debit spread
  candidates with estimated premium, max loss, breakeven, expiration, delta,
  spread width, and liquidity checks.
- **Option writing:** only allow covered or cash-secured examples if explicitly
  enabled by policy. Naked short calls/puts are out of scope and must be
  blocked.

## Acceptance Criteria
1. Candidates below 85% conviction never show leveraged alternatives.
2. Candidates with hard risk blockers never show orderable leveraged
   alternatives.
3. Candidate detail page explains why leveraged alternatives are available or
   unavailable.
4. Execution preview never auto-submits leveraged ETF or option alternatives.
5. Risk policy can disable the feature globally.
6. Alternative sizing is capped separately from normal stock sizing.
7. The service blocks naked option writing.
8. Unit tests cover:
   - conviction threshold
   - strong-signal threshold
   - no ETF available
   - ETF available but illiquid or disabled
   - option chain missing
   - defined-risk option candidate
   - naked option write blocked
9. Dashboard smoke tests confirm the panel renders without layout overflow.

## Tests Required
- Unit tests for leveraged-alternative eligibility.
- Unit tests for ETF mapping lookup.
- Unit tests for option strategy filtering and risk metrics.
- FastAPI/dashboard test for candidate detail panel.
- Execution-preview test proving leveraged alternatives are advisory unless
  explicitly selected and approved.

## Out of Scope
- Live options broker execution.
- Naked option writing.
- Automatic leverage escalation.
- Provider-backed real-time options flow.
- Tax, suitability, or legal advice.

## Notes for Implementer
- Use a conservative policy default: feature disabled until explicitly enabled.
- Add separate policy keys such as:
  - `AGENCY_LEVERAGED_ALTERNATIVES_ENABLED`
  - `AGENCY_LEVERAGED_MIN_CONVICTION`
  - `AGENCY_MAX_LEVERAGED_POSITION_PCT`
  - `AGENCY_ALLOW_DEFINED_RISK_OPTIONS`
  - `AGENCY_ALLOW_COVERED_OPTION_WRITES`
- Treat leveraged ETF availability as point-in-time reference data where
  possible. Do not hard-code broker availability as a trading guarantee.
- Add clear copy explaining that leveraged ETFs reset daily and can diverge from
  the underlying over multi-day periods.
