from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from agency.runtime.market_regime import load_market_regime_snapshot

AS_OF = date(2026, 5, 8)
BAR_COUNT = 70
EXPECTED_MEMBER_COUNT = 7


def test_market_regime_classifies_constructive_breadth() -> None:
    loader = _FakeLoader(
        sector_frame=_sector_frame(
            {
                "SPY": (100.0, 110.0),
                "QQQ": (100.0, 116.0),
                "IWM": (100.0, 106.0),
                "DIA": (100.0, 108.0),
                "XLK": (100.0, 124.0),
                "XLE": (100.0, 102.0),
                "XLF": (100.0, 112.0),
                "XLV": (100.0, 107.0),
                "XLI": (100.0, 111.0),
                "XLB": (100.0, 106.0),
                "XLY": (100.0, 118.0),
                "XLP": (100.0, 101.0),
                "XLU": (100.0, 96.0),
                "XLC": (100.0, 113.0),
                "XLRE": (100.0, 97.0),
            }
        ),
        universe={"AAPL", "MSFT", "NVDA", "AMZN", "META", "JPM", "UNH"},
        price_frame=_price_frame(
            {
                "AAPL": (50.0, 62.0),
                "MSFT": (50.0, 64.0),
                "NVDA": (50.0, 70.0),
                "AMZN": (50.0, 60.0),
                "META": (50.0, 63.0),
                "JPM": (60.0, 57.0),
                "UNH": (60.0, 56.0),
            }
        ),
    )

    snapshot = load_market_regime_snapshot(as_of=AS_OF, loader=loader)

    assert snapshot["summary"]["regime_label"] == "Risk On"
    assert snapshot["summary"]["status_class"] == "pass"
    assert snapshot["breadth"]["state_class"] == "pass"
    assert snapshot["sector_rows"][0]["ticker"] == "XLK"
    assert snapshot["sector_rows"][0]["stance"] == "Tailwind"
    assert snapshot["sector_rows"][-1]["stance"] == "Headwind"
    assert snapshot["universe"]["member_count"] == EXPECTED_MEMBER_COUNT


def test_market_regime_degrades_without_price_inputs() -> None:
    snapshot = load_market_regime_snapshot(as_of=AS_OF, loader=_BrokenLoader())

    assert snapshot["summary"]["regime_label"] == "Data Limited"
    assert snapshot["summary"]["status_class"] == "warn"
    assert snapshot["summary"]["confidence_pct"] == 0
    assert snapshot["benchmark_rows"][0]["return_20d"] == "n/a"
    assert snapshot["sector_rows"] == []
    assert any(row["status"] == "BLOCK" for row in snapshot["quality_rows"])


class _FakeLoader:
    def __init__(
        self,
        *,
        sector_frame: pl.DataFrame,
        universe: set[str],
        price_frame: pl.DataFrame,
    ) -> None:
        self._sector_frame = sector_frame
        self._universe = universe
        self._price_frame = price_frame

    def sector_etfs(self, as_of: date, lookback_days: int) -> pl.DataFrame:
        del as_of, lookback_days
        return self._sector_frame

    def universe_members(self, as_of: date) -> set[str]:
        del as_of
        return self._universe

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del as_of, lookback_days
        return self._price_frame.filter(pl.col("ticker").is_in(tickers))


class _BrokenLoader:
    def sector_etfs(self, as_of: date, lookback_days: int) -> pl.DataFrame:
        del as_of, lookback_days
        raise RuntimeError("fixture unavailable")

    def universe_members(self, as_of: date) -> set[str]:
        del as_of
        raise RuntimeError("fixture unavailable")

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del tickers, as_of, lookback_days
        raise RuntimeError("fixture unavailable")


def _sector_frame(paths: dict[str, tuple[float, float]]) -> pl.DataFrame:
    return _price_frame(paths)


def _price_frame(paths: dict[str, tuple[float, float]]) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    start_date = AS_OF - timedelta(days=BAR_COUNT - 1)
    for ticker, (start_price, end_price) in paths.items():
        for index in range(BAR_COUNT):
            close = start_price + (end_price - start_price) * index / (BAR_COUNT - 1)
            record_date = start_date + timedelta(days=index)
            rows.append(
                {
                    "ticker": ticker,
                    "date": record_date,
                    "close": close,
                    "adj_close": close,
                }
            )
    return pl.DataFrame(rows)
