# Technical Analysis Worker

The technical-analysis worker is the research-side agent for chart and setup
quality. It converts PIT daily OHLCV and optional Massive/Polygon trade prints
into technical features, checks those features against forward returns, sweeps
thresholds, and writes runtime guidance.

It does not submit trades. It tells the agency whether technical-analysis
features should stay as context, become corroborating evidence, or receive more
runtime weight after holdout validation.

## Inputs

- `prices_daily` parquet and manifest from the selected market-data provider.
- Optional `stock_trades` parquet and manifest from Massive/Polygon.
- A static ticker list for the calibration run.

## Features

- Trend: price location versus 20, 50, and 200 day moving averages.
- Momentum: RSI, MACD histogram change, and 20 day rate of change.
- Volume confirmation: recent volume expansion and accumulation pressure.
- Relative strength: excess 20 day return versus SPY or QQQ.
- Volatility risk: overextension and ATR risk.
- Agency candle regime: recent blue/pink candle state and flips.
- Massive trade pressure: signed notional pressure when stock trades exist.
- Named patterns: double bottom, double top, head and shoulders, inverse head
  and shoulders, and cup and handle.
- Optional third-party indicator pack from `bukosabino/ta`: ADX, Aroon, CCI,
  Bollinger/Keltner/Donchian channel position, CMF, MFI, OBV slope, VWAP
  distance, StochRSI, and Williams %R.

The optional indicator pack is isolated behind an adapter. If `ta` is not
installed, the worker keeps running and records a neutral
`external_indicator_score`.

To enable the optional pack locally:

```powershell
.\.venv\Scripts\python -m pip install ".[technical]"
```

## Command

```powershell
.\.venv\Scripts\python research\scripts\run_technical_analysis_worker.py `
  --start 2025-01-01 `
  --end 2026-05-08 `
  --ticker AAPL `
  --ticker MSFT `
  --ticker NVDA `
  --horizon 5 `
  --horizon 20 `
  --step-days 21 `
  --threshold 0.15 `
  --threshold 0.30 `
  --threshold 0.50 `
  --output-root research\results\latest-technical-analysis-worker
```

Useful controls:

- `--lookback-days`: daily bars used for each as-of feature row.
- `--step-days`: evaluation cadence.
- `--threshold`: repeatable positive feature thresholds to test.
- `--min-train-observations` and `--min-test-observations`: coverage floors
  before any runtime-weight recommendation is allowed.

## Outputs

- `technical-analysis-features.csv`: feature panel by date and ticker.
- `technical-analysis-ic.csv`: IC rows for each feature and horizon.
- `technical-analysis-threshold-sweep.csv`: train/test threshold checks.
- `technical-analysis-calibration.json`: machine-readable runtime guidance.
- `technical-analysis-calibration.md`: human-readable summary.

## Runtime Use

The runtime lane is `technical_analysis`. It emits one signal per ticker with a
plain-English summary covering setup, trend, momentum, volume, relative
strength, trade pressure, candle regime, named pattern, support, resistance, and
ATR risk.

Treat `technical_weight_eligible` as permission to run a reviewed paper test,
not as permission to trade live. Keep pattern and trade-pressure fields
contextual until the worker has enough holdout coverage across the full ticker
universe. The optional `external_indicator_score` follows the same rule: it can
support explanations immediately, but it earns decision weight only after
holdout calibration supports it.
