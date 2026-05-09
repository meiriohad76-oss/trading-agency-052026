from __future__ import annotations

from datetime import date

import polars as pl
from signals.block_trade_pressure import block_trade_pressure_frame, block_trade_pressure_score
from signals.buy_sell_pressure import buy_sell_pressure_frame, buy_sell_pressure_score

AS_OF = date(2026, 5, 6)


class FakeStockTradesLoader:
    def __init__(self, frame: pl.DataFrame) -> None:
        self.frame = frame

    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame:
        del as_of, lookback_days
        return self.frame.filter(pl.col("ticker").is_in(tickers))


def test_buy_sell_pressure_rewards_positive_print_pressure() -> None:
    scores = buy_sell_pressure_score(AS_OF, {"AAPL", "MSFT"}, FakeStockTradesLoader(_frame()))

    assert scores["AAPL"] > scores["MSFT"]


def test_buy_sell_pressure_frame_tracks_pre_market_contribution() -> None:
    frame = buy_sell_pressure_frame(AS_OF, {"AAPL"}, FakeStockTradesLoader(_frame()))

    assert frame.iloc[0]["ticker"] == "AAPL"
    assert frame.iloc[0]["pre_market_volume"] > 0
    assert frame.iloc[0]["buy_sell_pressure"] > 0


def test_block_trade_pressure_rewards_positive_large_off_exchange_prints() -> None:
    scores = block_trade_pressure_score(AS_OF, {"AAPL", "MSFT"}, FakeStockTradesLoader(_frame()))

    assert scores["AAPL"] > scores["MSFT"]


def test_block_trade_pressure_frame_tracks_focus_counts() -> None:
    frame = block_trade_pressure_frame(AS_OF, {"AAPL"}, FakeStockTradesLoader(_frame()))

    assert frame.iloc[0]["block_count"] == 1
    assert frame.iloc[0]["off_exchange_count"] == 1
    assert frame.iloc[0]["block_trade_pressure"] > 0


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            _trade("AAPL", 100_000.0, 1, "PRE_MARKET", block=True, off_exchange=True),
            _trade("AAPL", 10_000.0, 1, "REGULAR"),
            _trade("MSFT", 90_000.0, -1, "PRE_MARKET", block=True, off_exchange=True),
            _trade("MSFT", 10_000.0, -1, "REGULAR"),
        ]
    )


def _trade(
    ticker: str,
    notional: float,
    direction: int,
    session: str,
    *,
    block: bool = False,
    off_exchange: bool = False,
) -> dict[str, object]:
    size = 1000.0
    return {
        "ticker": ticker,
        "trade_date": AS_OF,
        "trade_ts": f"{AS_OF.isoformat()}T13:30:00Z",
        "price": notional / size,
        "size": size,
        "notional": notional,
        "direction": direction,
        "signed_volume": direction * size,
        "signed_notional": direction * notional,
        "session": session,
        "is_block_trade": block,
        "is_off_exchange": off_exchange,
        "sequence_number": 1,
        "source_id": f"{ticker}-{session}",
        "timestamp_as_of": AS_OF,
    }
