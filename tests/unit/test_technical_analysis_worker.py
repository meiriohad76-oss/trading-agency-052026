from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import polars as pl
from technical_analysis.worker import (
    TechnicalAnalysisWorkerConfig,
    run_technical_analysis_worker,
)

START = date(2026, 1, 1)
END = date(2026, 5, 30)
ROW_COUNT = 150
BULLISH_STEP = 0.5
BEARISH_STEP = -0.3
BENCHMARK_STEP = 0.1
EXPECTED_TICKER_COUNT = 2


class FakeTechnicalWorkerLoader:
    def __init__(self, prices: pl.DataFrame) -> None:
        self._prices = prices

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        start = as_of - timedelta(days=lookback_days - 1)
        return self._prices.filter(
            pl.col("ticker").is_in(tickers)
            & (pl.col("date") >= start)
            & (pl.col("date") <= as_of)
        )

    def stock_trades(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del tickers, as_of, lookback_days
        return pl.DataFrame()


def test_technical_analysis_worker_writes_calibration_artifacts(tmp_path: Path) -> None:
    config = TechnicalAnalysisWorkerConfig(
        start=date(2026, 3, 15),
        end=END,
        tickers=("AAPL", "MSFT"),
        horizons=(5,),
        step_size_days=10,
        thresholds=(0.0, 0.15),
        lookback_days=80,
        min_train_observations=1,
        min_test_observations=1,
    )

    result = run_technical_analysis_worker(
        config=config,
        loader=FakeTechnicalWorkerLoader(_price_frame()),
        output_root=tmp_path,
    )

    assert result.features["ticker"].nunique() == EXPECTED_TICKER_COUNT
    assert "technical_analysis_score" in result.features.columns
    assert "external_indicator_score" in result.features.columns
    assert result.calibration["worker"] == "technical_analysis_worker"
    assert (tmp_path / "technical-analysis-features.csv").is_file()
    assert (tmp_path / "technical-analysis-calibration.md").is_file()


def test_technical_analysis_worker_accepts_single_day_smoke_window(tmp_path: Path) -> None:
    result = run_technical_analysis_worker(
        config=TechnicalAnalysisWorkerConfig(
            start=date(2026, 5, 1),
            end=date(2026, 5, 1),
            tickers=("AAPL", "MSFT"),
            horizons=(5,),
            lookback_days=80,
        ),
        loader=FakeTechnicalWorkerLoader(_price_frame()),
        output_root=tmp_path,
    )

    assert result.features["ticker"].nunique() == EXPECTED_TICKER_COUNT
    assert result.calibration["verdict"] == "context_only_until_more_coverage"


def _price_frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            *_price_rows("AAPL", start=100.0, step=BULLISH_STEP),
            *_price_rows("MSFT", start=150.0, step=BEARISH_STEP),
            *_price_rows("SPY", start=450.0, step=BENCHMARK_STEP),
        ]
    )


def _price_rows(ticker: str, *, start: float, step: float) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for offset in range(ROW_COUNT):
        record_date = START + timedelta(days=offset)
        close = start + step * offset
        rows.append(
            {
                "ticker": ticker,
                "date": record_date,
                "open": close - 0.3 if step >= 0.0 else close + 0.3,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "adj_close": close,
                "volume": 1_000_000,
                "timestamp_as_of": record_date,
            }
        )
    return rows
