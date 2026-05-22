from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd
import polars as pl
from signals._common import float_or_none
from signals.chart_patterns import _bounded_confidence, chart_pattern_summary
from signals.technical_analysis import (
    _bounded,
    technical_analysis_contexts,
    technical_analysis_frame,
    technical_analysis_score,
)

AS_OF = date(2026, 5, 6)
LOOKBACK_ROWS = 80
START_DATE = AS_OF - timedelta(days=LOOKBACK_ROWS - 1)
BULLISH_STEP = 0.75
BEARISH_STEP = -0.55
BENCHMARK_STEP = 0.20
BASE_VOLUME = 1_000_000.0
LAST_VOLUME_MULTIPLIER = 3.0
BULLISH_NOTIONAL = 250_000.0
BEARISH_NOTIONAL = 200_000.0
DOUBLE_BOTTOM_ROWS = (
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    100.0,
    98.0,
    95.0,
    92.0,
    90.0,
    92.0,
    96.0,
    100.0,
    104.0,
    106.0,
    104.0,
    101.0,
    98.0,
    95.0,
    91.0,
    93.0,
    98.0,
    102.0,
    107.0,
    108.0,
    109.0,
)


def test_technical_analysis_bounding_neutralizes_non_finite_scores() -> None:
    assert _bounded(math.nan) == 0.0
    assert _bounded(math.inf) == 0.0
    assert _bounded(-math.inf) == 0.0
    assert float_or_none(math.inf) is None
    assert _bounded_confidence(math.nan) == 0.0
    assert _bounded_confidence(math.inf) == 0.0


class FakeTechnicalAnalysisLoader:
    def __init__(self, prices: pl.DataFrame, trades: pl.DataFrame | None = None) -> None:
        self._prices = prices
        self._trades = trades if trades is not None else pl.DataFrame()

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del as_of, lookback_days
        return self._prices.filter(pl.col("ticker").is_in(tickers))

    def stock_trades(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del as_of, lookback_days
        if self._trades.is_empty():
            return self._trades
        return self._trades.filter(pl.col("ticker").is_in(tickers))


def test_technical_analysis_scores_bullish_setups_above_bearish_setups() -> None:
    loader = FakeTechnicalAnalysisLoader(_price_frame(), _trade_frame())

    scores = technical_analysis_score(AS_OF, {"AAPL", "MSFT"}, loader)
    frame = technical_analysis_frame(AS_OF, {"AAPL", "MSFT"}, loader)

    assert scores["AAPL"] > scores["MSFT"]
    assert frame.iloc[0]["ticker"] == "AAPL"
    assert frame.loc[frame["ticker"] == "AAPL", "trade_pressure_score"].iloc[0] > 0.0
    assert frame.loc[frame["ticker"] == "MSFT", "trade_pressure_score"].iloc[0] < 0.0
    assert "external_indicator_score" in frame.columns
    assert frame["external_indicator_score"].between(-1.0, 1.0).all()


def test_technical_analysis_context_explains_chart_and_candle_evidence() -> None:
    loader = FakeTechnicalAnalysisLoader(_price_frame(), _trade_frame())

    contexts = {
        context.ticker: context
        for context in technical_analysis_contexts(AS_OF, {"AAPL", "MSFT"}, loader)
    }
    aapl = contexts["AAPL"]
    msft = contexts["MSFT"]

    assert "Technical analysis: AAPL" in aapl.summary
    assert "Massive trade pressure" in aapl.summary
    assert "Optional indicator pack" in aapl.summary
    assert "blue/pink last 5 sessions" in aapl.summary
    assert "Support/invalidation zone starts" in aapl.summary
    assert "technical_analysis_bullish" in aapl.reason_codes
    assert "technical_analysis_bearish" in msft.reason_codes


def test_chart_pattern_engine_detects_confirmed_double_bottom() -> None:
    close = pd.Series(DOUBLE_BOTTOM_ROWS)
    summary = chart_pattern_summary(
        close=close,
        high=close + 0.5,
        low=close - 0.5,
        volume=pd.Series([BASE_VOLUME for _ in DOUBLE_BOTTOM_ROWS]),
    )

    assert summary.primary is not None
    assert summary.primary.name == "double_bottom"
    assert summary.primary.direction == "bullish"
    assert summary.primary.status == "confirmed"
    assert summary.score > 0.0
    assert "technical_pattern_double_bottom" in summary.reason_codes


def test_chart_pattern_engine_detects_cup_and_handle() -> None:
    close = pd.Series(_cup_and_handle_rows())
    summary = chart_pattern_summary(
        close=close,
        high=close + 0.5,
        low=close - 0.5,
        volume=pd.Series([BASE_VOLUME for _ in close]),
    )

    assert summary.primary is not None
    assert summary.primary.name == "cup_and_handle"
    assert summary.primary.direction == "bullish"
    assert "cup and handle" in summary.summary_fragment


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
    for offset in range(LOOKBACK_ROWS):
        record_date = START_DATE + timedelta(days=offset)
        close = start + step * offset
        bullish = step >= 0.0
        open_price = close - 0.4 if bullish else close + 0.4
        volume = BASE_VOLUME
        if offset == LOOKBACK_ROWS - 1:
            volume *= LAST_VOLUME_MULTIPLIER
        rows.append(
            {
                "ticker": ticker,
                "date": record_date,
                "open": open_price,
                "high": max(open_price, close) + 0.6,
                "low": min(open_price, close) - 0.6,
                "close": close,
                "volume": volume,
                "timestamp_as_of": record_date,
            }
        )
    return rows


def _trade_frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            _trade("AAPL", BULLISH_NOTIONAL, direction=1),
            _trade("MSFT", BEARISH_NOTIONAL, direction=-1),
        ]
    )


def _trade(ticker: str, notional: float, *, direction: int) -> dict[str, object]:
    return {
        "ticker": ticker,
        "trade_date": AS_OF,
        "trade_ts": f"{AS_OF.isoformat()}T13:30:00Z",
        "price": 100.0,
        "size": notional / 100.0,
        "notional": notional,
        "direction": direction,
        "signed_notional": direction * notional,
        "session": "REGULAR",
        "source_id": f"{ticker}-technical-flow",
        "timestamp_as_of": AS_OF,
    }


def _cup_and_handle_rows() -> list[float]:
    left_rim = [100.0 + offset * 0.2 for offset in range(20)]
    cup_left = [104.0 - offset * 0.8 for offset in range(25)]
    cup_right = [84.0 + offset * 0.8 for offset in range(25)]
    handle = [104.0 - offset * 0.4 for offset in range(10)]
    recovery = [100.0 + offset * 1.2 for offset in range(5)]
    return [*left_rim, *cup_left, *cup_right, *handle, *recovery]
