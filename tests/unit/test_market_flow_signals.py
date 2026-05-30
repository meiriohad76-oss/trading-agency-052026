from __future__ import annotations

import math
from datetime import date

import pandas as pd
import polars as pl
from signals._common import directional_rank_score
from signals.block_trade_pressure import block_trade_pressure_frame, block_trade_pressure_score
from signals.buy_sell_pressure import buy_sell_pressure_frame, buy_sell_pressure_score
from signals.market_flow_activity import (
    market_flow_trend_frame,
    market_flow_trend_score,
    pre_market_unusual_activity_frame,
    pre_market_unusual_activity_score,
    unusual_trade_activity_frame,
    unusual_trade_activity_score,
)

AS_OF = date(2026, 5, 6)


class FakeStockTradesLoader:
    def __init__(self, frame: pl.DataFrame) -> None:
        self.frame = frame
        self.requests: list[tuple[tuple[str, ...], date, int]] = []

    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame:
        self.requests.append((tuple(tickers), as_of, lookback_days))
        return self.frame.filter(pl.col("ticker").is_in(tickers))


def test_buy_sell_pressure_rewards_positive_print_pressure() -> None:
    scores = buy_sell_pressure_score(AS_OF, {"AAPL", "MSFT"}, FakeStockTradesLoader(_frame()))

    assert scores["AAPL"] > scores["MSFT"]


def test_buy_sell_pressure_preserves_bearish_sign_when_all_tickers_are_bearish() -> None:
    scores = buy_sell_pressure_score(
        AS_OF,
        {"AAPL", "MSFT"},
        FakeStockTradesLoader(
            pl.DataFrame(
                [
                    _trade("AAPL", 100_000.0, -1, "REGULAR"),
                    _trade("AAPL", 80_000.0, 1, "REGULAR"),
                    _trade("MSFT", 200_000.0, -1, "REGULAR"),
                ]
            )
        ),
    )

    assert scores["AAPL"] < 0
    assert scores["MSFT"] < 0
    assert scores["MSFT"] < scores["AAPL"]


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


def test_block_trade_pressure_tracks_trf_and_relative_large_print_metrics() -> None:
    frame = block_trade_pressure_frame(
        AS_OF,
        {"AAPL"},
        FakeStockTradesLoader(
            pl.DataFrame(
                [
                    _trade("AAPL", 20_000.0, 1, "REGULAR"),
                    _trade("AAPL", 25_000.0, 1, "REGULAR"),
                    _trade(
                        "AAPL",
                        250_000.0,
                        1,
                        "REGULAR",
                        block=True,
                        off_exchange=True,
                        trf=True,
                    ),
                ]
            )
        ),
    )

    row = frame.iloc[0]
    assert row["trf_off_exchange_count"] == 1
    assert row["trf_off_exchange_notional"] == 250_000.0
    assert row["trf_off_exchange_share"] > 0.8
    assert row["large_print_count"] == 1
    assert row["largest_focus_notional"] == 250_000.0
    assert row["largest_focus_notional_multiple"] >= 10.0
    assert row["focus_activity_score"] > 0.0
    assert row["block_trade_pressure"] > 0.0


def test_block_trade_pressure_defaults_to_current_live_slice() -> None:
    loader = FakeStockTradesLoader(_frame())

    block_trade_pressure_frame(AS_OF, {"AAPL"}, loader)

    assert loader.requests[0][2] == 1


def test_block_trade_pressure_reports_neutral_when_no_focus_trades_exist() -> None:
    frame = block_trade_pressure_frame(
        AS_OF,
        {"AAPL"},
        FakeStockTradesLoader(
            pl.DataFrame(
                [
                    {
                        **_trade("AAPL", 100_000.0, 1, "REGULAR"),
                        "is_block_trade": "False",
                        "is_off_exchange": "False",
                    }
                ]
            )
        ),
    )

    assert frame.iloc[0]["ticker"] == "AAPL"
    assert frame.iloc[0]["focus_trade_count"] == 0
    assert frame.iloc[0]["block_count"] == 0
    assert frame.iloc[0]["off_exchange_count"] == 0
    assert frame.iloc[0]["block_trade_pressure"] == 0.0
    assert frame.iloc[0]["block_trade_pressure_score"] == 0.0


def test_unusual_trade_activity_rewards_directional_activity_spike() -> None:
    scores = unusual_trade_activity_score(
        AS_OF,
        {"AAPL", "MSFT"},
        FakeStockTradesLoader(_multi_day_frame()),
    )
    frame = unusual_trade_activity_frame(AS_OF, {"AAPL"}, FakeStockTradesLoader(_multi_day_frame()))

    assert scores["AAPL"] > scores["MSFT"]
    assert frame.iloc[0]["unusual_trade_activity"] > 0


def test_pre_market_unusual_activity_rewards_pre_market_spike() -> None:
    scores = pre_market_unusual_activity_score(
        AS_OF,
        {"AAPL", "MSFT"},
        FakeStockTradesLoader(_multi_day_frame()),
    )
    frame = pre_market_unusual_activity_frame(
        AS_OF,
        {"AAPL"},
        FakeStockTradesLoader(_multi_day_frame()),
    )

    assert scores["AAPL"] > scores["MSFT"]
    assert frame.iloc[0]["pre_market_unusual_activity"] > 0


def test_market_flow_trend_rewards_improving_signed_pressure() -> None:
    scores = market_flow_trend_score(
        AS_OF,
        {"AAPL", "MSFT"},
        FakeStockTradesLoader(_multi_day_frame()),
    )
    frame = market_flow_trend_frame(AS_OF, {"AAPL"}, FakeStockTradesLoader(_multi_day_frame()))

    assert scores["AAPL"] > scores["MSFT"]
    assert frame.iloc[0]["market_flow_trend"] > 0


def test_directional_rank_score_ignores_non_finite_values() -> None:
    scores = directional_rank_score(pd.Series([math.inf, -math.inf, math.nan, 5.0, -2.0]))

    assert scores.iloc[0] == 0.0
    assert scores.iloc[1] == 0.0
    assert scores.iloc[2] == 0.0
    assert scores.iloc[3] > 0.0
    assert scores.iloc[4] < 0.0


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        [
            _trade("AAPL", 100_000.0, 1, "PRE_MARKET", block=True, off_exchange=True),
            _trade("AAPL", 10_000.0, 1, "REGULAR"),
            _trade("MSFT", 90_000.0, -1, "PRE_MARKET", block=True, off_exchange=True),
            _trade("MSFT", 10_000.0, -1, "REGULAR"),
        ]
    )


def _multi_day_frame() -> pl.DataFrame:
    yesterday = date(2026, 5, 5)
    two_days_ago = date(2026, 5, 4)
    return pl.DataFrame(
        [
            _trade("AAPL", 10_000.0, -1, "REGULAR", trade_date=two_days_ago),
            _trade("AAPL", 12_000.0, 0, "PRE_MARKET", trade_date=yesterday),
            _trade("AAPL", 120_000.0, 1, "PRE_MARKET", trade_date=AS_OF),
            _trade("AAPL", 80_000.0, 1, "REGULAR", trade_date=AS_OF),
            _trade("MSFT", 10_000.0, 1, "REGULAR", trade_date=two_days_ago),
            _trade("MSFT", 12_000.0, 0, "PRE_MARKET", trade_date=yesterday),
            _trade("MSFT", 120_000.0, -1, "PRE_MARKET", trade_date=AS_OF),
            _trade("MSFT", 80_000.0, -1, "REGULAR", trade_date=AS_OF),
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
    trf: bool = False,
    trade_date: date = AS_OF,
) -> dict[str, object]:
    size = 1000.0
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "trade_ts": f"{trade_date.isoformat()}T13:30:00Z",
        "price": notional / size,
        "size": size,
        "notional": notional,
        "direction": direction,
        "signed_volume": direction * size,
        "signed_notional": direction * notional,
        "session": session,
        "is_block_trade": block,
        "is_off_exchange": off_exchange,
        "is_trf_off_exchange": trf,
        "trf_venue": "FINRA/NYSE TRF" if trf else "",
        "sequence_number": 1,
        "source_id": f"{ticker}-{session}",
        "timestamp_as_of": trade_date,
    }
