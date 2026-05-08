# T73: Actionability threshold calibration

**Owner:** codex
**Phase:** 1 research calibration
**Status:** done

## Goal

Use the first live H1 run to calibrate conservative actionability thresholds for
the first testable version.

## Delivered

- Ran live H1 over the T72-ready datasets for fundamentals, insider,
  institutional, sector momentum, abnormal volume, and news.
- Added compact T73 calibration artifacts under
  `research/results/t73-actionability-calibration/`.
- Raised the deterministic `WATCH` evidence-breadth default to two usable
  independent sources while keeping one confirmed signal required.
- Documented that no tested H1 lane is standalone-validated yet.

## Acceptance Notes

1. All tested H1 lanes are inconclusive after Bonferroni correction.
2. News did not produce enough ticker-tagged H1 observations and remains coverage work.
3. The runtime gate now blocks one-source `WATCH` decisions by default.
