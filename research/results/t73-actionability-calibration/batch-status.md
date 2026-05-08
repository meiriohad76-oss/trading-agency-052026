# Research Batch Status

Window: 2021-01-01 to 2025-12-31
Signals: fundamentals, insider, institutional, sector_momentum, abnormal_volume, news

## Dataset Readiness

| Dataset | Status | Reason |
| --- | --- | --- |
| news_rss | ready | news signal inputs; 80 row(s) |
| prices_daily | ready | forward returns, H4 profile, and H5 sweep; 31375 row(s) |
| sec_13f | ready | institutional signal inputs; 624 row(s) |
| sec_company_facts | ready | fundamentals signal inputs; 9843 row(s) |
| sec_form4 | ready | insider signal inputs; 4163 row(s) |

## Hypothesis Artifacts

| Hypothesis | Status | Reason |
| --- | --- | --- |
| H1 | written | H1 IC and verdict files written |
| H2 | blocked | requires accepted H1 lane verdicts |
| H3 | blocked | requires deterministic profile/AB input rows |
| H4/H5 | blocked | requires H1 surviving lanes and price data |
