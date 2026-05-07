# T19: News/headline signal lane

**Owner:** codex
**Phase:** 1 (H1 signal edge)
**Estimate:** medium (2-6h)
**Dependencies:** T18

## Goal
Implement a simple forward RSS headline signal over ticker-tagged news rows.

## Outputs
- `research/src/signals/news.py`
  - `news_score(as_of, universe, loader, lookback_days=3) -> dict[str, float]`
  - `news_factor_frame(as_of, universe, loader, lookback_days=3) -> pandas.DataFrame`

## Acceptance Criteria
1. Uses only `loader.news(as_of, lookback_days, tickers)`.
2. Missing news does not fail the cross-section.
3. Positive headline terms increase score; negative terms lower score.
4. Scores are deterministic and cross-sectionally normalized.

## Tests Required
- Unit: ranking fixture for positive/neutral/negative headlines.
- Unit: missing data returns an empty frame.
- Unit: deterministic uppercase output.

## Out of Scope
- LLM sentiment.
- Full article content.
- Actionability decisions.
