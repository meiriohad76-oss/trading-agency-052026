# Continuous Learning: Near-Miss What-If Journal

The learning loop should evaluate three cohorts:

1. **Selected and approved** candidates that entered the normal review/trade path.
2. **Rejected/deferred** candidates that were reviewed by the user.
3. **Near misses** that were close to inclusion but missed the WATCH/action bar.

The near-miss journal is intentionally advisory. It helps answer: "Would the agency
have done better if this almost-selected stock had been included?" It does not
change thresholds automatically.

## Current Definition

A near miss is a selection report that was not finally selected for review/trade,
but:

- its deterministic score was positive and within the configured margin below
  the WATCH threshold, or
- it was demoted from an otherwise watchable setup into `CLOSE_REVIEW`.

The current defaults are:

- WATCH threshold: `0.50`
- Near-miss margin: `0.15`
- What-if horizons: 1, 5, and 20 trading days

## What Gets Logged

For each near miss, the learning artifact records:

- ticker, cycle, and as-of timestamp
- final action and deterministic score
- inclusion gap versus the WATCH threshold
- miss reason
- policy gate status
- source count and confirmed-signal count
- strongest evidence lanes
- forward what-if returns when daily price data is available

## How To Use It

Review the Learning dashboard after each paper cycle. If near misses consistently
outperform selected candidates over enough samples, that is evidence for a human
threshold review. If they underperform, that supports keeping the selection bar
conservative.

Any policy change still requires explicit review plus backtest/holdout support.
