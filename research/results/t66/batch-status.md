# Research Batch Status

Window: 2021-01-01 to 2025-12-31
Signals: fundamentals, insider, institutional, sector_momentum, abnormal_volume, news, options_flow

## Dataset Readiness

| Dataset | Status | Reason |
| --- | --- | --- |
| news_rss | missing | missing research/data/manifests/news_rss.json |
| options_chains | missing | missing research/data/manifests/options_chains.json |
| prices_daily | missing | missing research/data/manifests/prices_daily.json |
| sec_13f | missing | missing research/data/manifests/sec_13f.json |
| sec_company_facts | missing | missing research/data/manifests/sec_company_facts.json |
| sec_form4 | missing | missing research/data/manifests/sec_form4.json |
| universe_membership | ready | dynamic H1 evaluation universe; 285 row(s) |

## Hypothesis Artifacts

| Hypothesis | Status | Reason |
| --- | --- | --- |
| H1 | blocked | missing required datasets: news_rss, options_chains, prices_daily, sec_13f, sec_company_facts, sec_form4 |
| H2 | blocked | requires accepted H1 lane verdicts |
| H3 | blocked | requires deterministic profile/AB input rows |
| H4/H5 | blocked | requires H1 surviving lanes and price data |
