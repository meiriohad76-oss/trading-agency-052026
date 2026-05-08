# T73 Actionability Calibration

Window: 2021-01-01 to 2025-12-31
Verdict: `keep_conservative_thresholds`

## Runtime Thresholds

- Minimum usable independent sources before WATCH: 2
- Minimum confirmed signals: 1
- Deterministic WATCH threshold: 0.5
- Inferred signals require confirmed corroboration: true
- News lane requires independent source count: 2

## H1 Recommendations

| Signal | H1 verdict | Best horizon | Mean IC | T-stat | Bonferroni p | Recommendation |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| fundamentals | inconclusive | 20 | 0.0522 | 1.1058 | 1.0000 | context_only_until_retest |
| insider | inconclusive | 5 | 0.0525 | 1.3829 | 1.0000 | context_only_until_retest |
| institutional | inconclusive | 5 | 0.0163 | 0.4926 | 1.0000 | context_only_until_retest |
| sector_momentum | inconclusive | 5 | -0.0986 | -2.5095 | 0.1209 | context_only_until_retest |
| abnormal_volume | inconclusive | 5 | 0.1080 | 2.6284 | 0.0858 | context_only_until_retest |
| news | not_evaluated | n/a | n/a | n/a | n/a | context_only_until_ticker_tagged_coverage |

Rationale: No requested H1 lane survived the Bonferroni-adjusted significance bar; the deterministic engine therefore requires at least two usable independent sources before emitting WATCH.
