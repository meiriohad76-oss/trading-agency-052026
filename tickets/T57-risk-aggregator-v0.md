# T57: Risk aggregator v0

**Owner:** codex
**Phase:** 2 (build)
**Estimate:** small
**Dependencies:** T50, T56

## Goal
Add a conservative risk decision service that evaluates final selection reports before
any execution preview is shown.

## Outputs
- `risk-decision` JSON Schema contract.
- `PortfolioPolicy` defaults and `build_risk_decision(s)` service.
- Lifecycle audit event for `RISK_DECISION`.
- Unit tests for allowed, warned, policy-blocked, and exposure-cap cases.

## Acceptance Criteria
1. Risk decisions validate against the contract.
2. Blocking policy gates force `BLOCK`.
3. Degraded runtime sources produce `WARN`.
4. Gross exposure cap breaches produce `BLOCK`.
5. No broker call or approval action is performed.
