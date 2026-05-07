# Data Refresh Batch Status

Window: 2021-01-01 to 2025-12-31
Mode: dry-run

| Dataset | Status | Reason |
| --- | --- | --- |
| prices_daily | planned | dry-run only |
| sec_company_facts | blocked | missing SEC_USER_AGENT |
| sec_form4 | blocked | missing SEC_USER_AGENT |
| sec_13f | blocked | missing SEC_USER_AGENT; missing 13F filer CIKs; missing 13F CUSIP map |
| news_rss | blocked | missing RSS feed specs |
| options_chains | planned | dry-run only |

## Commands

### prices_daily

`$PYTHON research/scripts/pull_yfinance_daily.py --start 2021-01-01 --end 2025-12-31 --workers 1 --include-etfs`

### sec_company_facts

`$PYTHON research/scripts/pull_sec_company_facts.py`

### sec_form4

`$PYTHON research/scripts/pull_sec_form4.py --start 2021-01-01 --end 2025-12-31`

### sec_13f

`$PYTHON research/scripts/pull_sec_13f.py --start 2021-01-01 --end 2025-12-31`

### news_rss

`$PYTHON research/scripts/pull_news_rss.py`

### options_chains

`$PYTHON research/scripts/pull_yfinance_options.py`
