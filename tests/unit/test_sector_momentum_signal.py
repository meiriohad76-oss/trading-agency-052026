from __future__ import annotations

from datetime import date

import polars as pl
import pytest
from signals.sector_momentum import sector_momentum_frame, sector_momentum_score

AS_OF = date(2023, 1, 31)
LOOKBACK_DAYS = 20


def test_sector_momentum_score_ranks_recent_etf_returns() -> None:
    loader = _FakeSectorETFLoader(
        [
            _price("XLK", date(2023, 1, 1), 100.0),
            _price("XLK", AS_OF, 112.0),
            _price("XLF", date(2023, 1, 1), 100.0),
            _price("XLF", AS_OF, 106.0),
            _price("SPY", date(2023, 1, 1), 100.0),
            _price("SPY", AS_OF, 104.0),
            _price("XLU", date(2023, 1, 1), 100.0),
            _price("XLU", AS_OF, 100.0),
        ]
    )

    scores = sector_momentum_score(AS_OF, {"xlu", "xlk", "xlf", "spy"}, loader)

    assert list(scores) == ["XLK", "XLF", "SPY", "XLU"]
    assert scores["XLK"] > scores["XLF"] > scores["SPY"] > scores["XLU"]


def test_sector_momentum_frame_skips_incomplete_histories() -> None:
    loader = _FakeSectorETFLoader(
        [
            _price("XLK", date(2023, 1, 1), 100.0),
            _price("XLK", AS_OF, 112.0),
            _price("XLE", AS_OF, 80.0),
        ]
    )

    frame = sector_momentum_frame(AS_OF, {"XLK", "XLE"}, loader)

    assert frame["ticker"].to_list() == ["XLK"]
    assert frame.iloc[0]["sector_momentum_score"] == pytest.approx(0.0)


def test_sector_momentum_score_is_deterministic_uppercases_and_forwards_lookback() -> None:
    loader = _FakeSectorETFLoader(
        [
            _price("XLK", date(2023, 1, 1), 100.0),
            _price("XLK", AS_OF, 112.0),
            _price("XLF", date(2023, 1, 1), 100.0),
            _price("XLF", AS_OF, 106.0),
        ]
    )

    first = sector_momentum_score(AS_OF, {"xlf", "xlk"}, loader, LOOKBACK_DAYS)
    second = sector_momentum_score(AS_OF, {"xlk", "xlf"}, loader, LOOKBACK_DAYS)

    assert first == second
    assert set(first) == {"XLK", "XLF"}
    assert loader.calls == [(AS_OF, LOOKBACK_DAYS), (AS_OF, LOOKBACK_DAYS)]


class _FakeSectorETFLoader:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.calls: list[tuple[date, int]] = []

    def sector_etfs(self, as_of: date, lookback_days: int) -> pl.DataFrame:
        self.calls.append((as_of, lookback_days))
        return pl.DataFrame(self._rows)


def _price(ticker: str, value_date: date, close: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "date": value_date,
        "close": close,
        "volume": 1_000,
    }
