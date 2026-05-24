from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from signals.abnormal_volume import abnormal_volume_frame, abnormal_volume_score

AS_OF = date(2023, 1, 31)
LOOKBACK_DAYS = 20


def test_abnormal_volume_score_rewards_up_volume_and_penalizes_down_volume() -> None:
    loader = _FakePriceLoader(
        [
            *_history("AAPL", 100.0, 100),
            _price("AAPL", AS_OF, 105.0, 1_000),
            *_history("MSFT", 100.0, 100),
            _price("MSFT", AS_OF, 100.0, 100),
            *_history("TSLA", 100.0, 100),
            _price("TSLA", AS_OF, 95.0, 1_000),
        ]
    )

    scores = abnormal_volume_score(AS_OF, {"tsla", "AAPL", "MSFT"}, loader)

    assert list(scores) == ["AAPL", "MSFT", "TSLA"]
    assert scores["AAPL"] > scores["MSFT"] > scores["TSLA"]


def test_abnormal_volume_frame_skips_incomplete_histories() -> None:
    loader = _FakePriceLoader(
        [
            *_history("AAPL", 100.0, 100),
            _price("AAPL", AS_OF, 105.0, 1_000),
            _price("BAD", AS_OF, 10.0, 1_000),
            *_history("NOVOL", 50.0, 0),
            _price("NOVOL", AS_OF, 51.0, 1_000),
        ]
    )

    frame = abnormal_volume_frame(AS_OF, {"AAPL", "BAD", "NOVOL"}, loader)

    assert frame["ticker"].to_list() == ["AAPL"]
    assert frame.iloc[0]["abnormal_volume_score"] == pytest.approx(0.0)


def test_abnormal_volume_score_is_deterministic_uppercases_and_forwards_lookback() -> None:
    loader = _FakePriceLoader(
        [
            *_history("AAPL", 100.0, 100),
            _price("AAPL", AS_OF, 105.0, 1_000),
            *_history("MSFT", 100.0, 100),
            _price("MSFT", AS_OF, 100.0, 100),
        ]
    )

    first = abnormal_volume_score(AS_OF, {"msft", "aapl"}, loader, LOOKBACK_DAYS)
    second = abnormal_volume_score(AS_OF, {"aapl", "msft"}, loader, LOOKBACK_DAYS)

    assert first == second
    assert set(first) == {"AAPL", "MSFT"}
    assert loader.calls == [
        (["AAPL", "MSFT"], AS_OF, LOOKBACK_DAYS),
        (["AAPL", "MSFT"], AS_OF, LOOKBACK_DAYS),
    ]


def test_abnormal_volume_frame_exposes_rvol_band_and_trend_confluence() -> None:
    loader = _FakePriceLoader(
        [
            _price("AAPL", date(2023, 1, 27), 100.0, 100),
            _price("AAPL", date(2023, 1, 28), 102.0, 100),
            _price("AAPL", date(2023, 1, 29), 104.0, 100),
            _price("AAPL", date(2023, 1, 30), 106.0, 100),
            _price("AAPL", AS_OF, 110.0, 300),
        ]
    )

    frame = abnormal_volume_frame(AS_OF, {"AAPL"}, loader, LOOKBACK_DAYS)
    row = frame.iloc[0]

    assert row["volume_signal_band"] == "extreme"
    assert row["trend_agreement"] == "uptrend_confirmed"
    assert row["rvol_z_score"] > 0.0
    assert row["rvol_mad_score"] > 0.0
    assert row["signal_confidence"] > 0.75


class _FakePriceLoader:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.calls: list[tuple[list[str], date, int]] = []

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        self.calls.append((tickers, as_of, lookback_days))
        requested = set(tickers)
        return pl.DataFrame([row for row in self._rows if row["ticker"] in requested])


def _history(ticker: str, close: float, volume: int) -> list[dict[str, object]]:
    return [
        _price(ticker, date(2023, 1, 29), close, volume),
        _price(ticker, date(2023, 1, 30), close, volume),
    ]


def _price(ticker: str, value_date: date, close: float, volume: int) -> dict[str, object]:
    return {
        "ticker": ticker,
        "date": value_date,
        "close": close,
        "volume": volume,
    }
