# Leveraged Alternative Advisor

The leveraged alternative advisor is an advisory-only worker for exceptional
long candidates. It does not submit orders. It explains whether a high-conviction
stock candidate can be reviewed through a capped leveraged ETF or a defined-risk
option structure.

## Trigger

- Local policy must enable `AGENCY_LEVERAGED_ALTERNATIVES_ENABLED`.
- Candidate action must be `BUY` or `WATCH`.
- Final conviction must be at least `AGENCY_LEVERAGED_MIN_CONVICTION`, default
  `0.85`.
- Evidence must include at least two independent sources and two confirmed
  signals.
- Candidate must have no hard policy gate or risk blocker.
- Critical evidence cannot be stale or unavailable.

## Outputs

The service returns a review payload with trigger checks, baseline candidate
metrics, and advisory alternatives. The candidate detail page explains the
decision for one stock, and the execution preview page summarizes any triggered
reviews across the latest cycle.

## Guardrails

- Disabled by default.
- Advisory only; no automatic leveraged ETF or options submission.
- Separate leveraged position cap via `AGENCY_MAX_LEVERAGED_POSITION_PCT`.
- Defined-risk options are disabled unless `AGENCY_ALLOW_DEFINED_RISK_OPTIONS`
  is enabled.
- Naked option writing is blocked.

## Configuration

Copy `research/config/leveraged-alternatives.example.json` to a local file and
set `AGENCY_LEVERAGED_ALTERNATIVES_PATH` if you want to maintain a local ETF
catalog. The bundled catalog is a starter reference, not a broker availability
guarantee.
