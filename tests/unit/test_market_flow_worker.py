from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl
from market_flow.features import market_flow_feature_frame
from market_flow.worker import MarketFlowWorkerConfig, run_market_flow_worker

START = date(2026, 1, 1)
END = date(2026, 1, 12)


def test_market_flow_feature_frame_builds_worker_inputs() -> None:
    frame = market_flow_feature_frame(START, {"AAPL", "MSFT"}, _WorkerLoader())

    assert set(frame["ticker"]) == {"AAPL", "MSFT"}
    assert frame.loc[frame["ticker"] == "AAPL", "buy_sell_pressure"].iat[0] > 0
    assert frame.loc[frame["ticker"] == "MSFT", "block_trade_pressure"].iat[0] < 0


def test_market_flow_feature_frame_uses_stock_relative_block_thresholds() -> None:
    frame = market_flow_feature_frame(START, {"AAPL", "MSFT"}, _RelativeBlockLoader())
    by_ticker = frame.set_index("ticker")

    assert by_ticker.loc["AAPL", "relative_block_count"] == 1
    assert by_ticker.loc["AAPL", "block_trade_pressure"] > 0
    assert by_ticker.loc["MSFT", "absolute_block_count"] > 0
    assert by_ticker.loc["MSFT", "relative_block_count"] == 0
    assert by_ticker.loc["MSFT", "block_trade_pressure"] == 0.0


def test_market_flow_feature_frame_exposes_robust_activity_anomaly_metadata() -> None:
    frame = market_flow_feature_frame(START, {"AAPL"}, _ActivityAnomalyLoader())
    row = frame.iloc[0]

    assert row["trade_count_anomaly_ratio"] >= 2.0
    assert row["notional_anomaly_ratio"] >= 2.0
    assert row["volume_anomaly_ratio"] >= 2.0
    assert row["activity_anomaly_band"] in {"strong", "extreme"}
    assert row["market_flow_trend_participation"] > 0.0


def test_market_flow_feature_frame_preserves_verified_zero_activity_ticker() -> None:
    frame = market_flow_feature_frame(START, {"AAPL", "BK"}, _ZeroActivityLoader())
    by_ticker = frame.set_index("ticker")

    assert set(by_ticker.index) == {"AAPL", "BK"}
    assert by_ticker.loc["BK", "trade_count"] == 0
    assert by_ticker.loc["BK", "total_volume"] == 0.0
    assert by_ticker.loc["BK", "total_notional"] == 0.0
    assert by_ticker.loc["BK", "buy_sell_pressure"] == 0.0
    assert by_ticker.loc["BK", "block_trade_pressure"] == 0.0
    assert by_ticker.loc["BK", "unusual_trade_activity"] == 0.0
    assert by_ticker.loc["BK", "pre_market_unusual_activity"] == 0.0
    assert by_ticker.loc["BK", "market_flow_trend"] == 0.0
    assert by_ticker.loc["BK", "activity_anomaly_band"] == "normal"


def test_market_flow_worker_writes_calibration_artifacts(tmp_path: Path) -> None:
    result = run_market_flow_worker(
        config=MarketFlowWorkerConfig(
            start=START,
            end=END,
            tickers=("AAPL", "MSFT"),
            horizons=(1,),
            step_size_days=1,
            thresholds=(0.0, 0.2),
            min_train_observations=2,
            min_test_observations=1,
        ),
        loader=_WorkerLoader(),
        output_root=tmp_path,
    )

    calibration = json.loads((tmp_path / "market-flow-calibration.json").read_text())

    assert result.calibration["worker"] == "market_flow_analysis_worker"
    assert calibration["verdict"] == "market_flow_weight_eligible"
    assert calibration["runtime_guidance"]["buy_sell_pressure"]["suggested_weight"] > 0
    assert (tmp_path / "market-flow-features.csv").is_file()
    assert (tmp_path / "market-flow-calibration.md").is_file()


def test_market_flow_worker_stays_context_only_without_coverage(tmp_path: Path) -> None:
    result = run_market_flow_worker(
        config=MarketFlowWorkerConfig(
            start=START,
            end=START + timedelta(days=2),
            tickers=("AAPL", "MSFT"),
            horizons=(1,),
            step_size_days=1,
            min_train_observations=50,
            min_test_observations=50,
        ),
        loader=_WorkerLoader(),
        output_root=tmp_path,
    )

    assert result.calibration["verdict"] == "context_only_until_more_coverage"


def test_market_flow_worker_accepts_single_day_smoke_window(tmp_path: Path) -> None:
    result = run_market_flow_worker(
        config=MarketFlowWorkerConfig(
            start=START,
            end=START,
            tickers=("AAPL", "MSFT"),
            horizons=(1,),
            step_size_days=1,
        ),
        loader=_WorkerLoader(),
        output_root=tmp_path,
    )

    assert set(result.features["ticker"]) == {"AAPL", "MSFT"}
    assert result.calibration["verdict"] == "context_only_until_more_coverage"


class _WorkerLoader:
    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        del lookback_days
        rows: list[dict[str, object]] = []
        for offset in range((as_of - START).days + 1):
            value_date = START + timedelta(days=offset)
            if "AAPL" in tickers:
                rows.append({"ticker": "AAPL", "date": value_date, "adj_close": 100.0 + offset})
            if "MSFT" in tickers:
                rows.append({"ticker": "MSFT", "date": value_date, "adj_close": 100.0 - offset})
        return pl.DataFrame(rows)

    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame:
        del lookback_days
        rows: list[dict[str, object]] = []
        if "AAPL" in tickers:
            rows.append(_trade("AAPL", as_of, 1))
        if "MSFT" in tickers:
            rows.append(_trade("MSFT", as_of, -1))
        return pl.DataFrame(rows)


class _RelativeBlockLoader:
    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame:
        del lookback_days
        rows: list[dict[str, object]] = []
        if "AAPL" in tickers:
            rows.extend(_flow_trade("AAPL", as_of, 10_000.0, 100.0, 1) for _ in range(8))
            rows.append(_flow_trade("AAPL", as_of, 250_000.0, 100.0, 1))
        if "MSFT" in tickers:
            rows.extend(_flow_trade("MSFT", as_of, 250_000.0, 100.0, 1) for _ in range(8))
        return pl.DataFrame(rows)


class _ActivityAnomalyLoader:
    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame:
        del lookback_days
        rows: list[dict[str, object]] = []
        if "AAPL" in tickers:
            prior_day = as_of - timedelta(days=1)
            rows.extend(_flow_trade("AAPL", prior_day, 10_000.0, 100.0, 1) for _ in range(3))
            rows.extend(_flow_trade("AAPL", as_of, 10_000.0, 100.0, 1) for _ in range(9))
        return pl.DataFrame(rows)


class _ZeroActivityLoader:
    def stock_trade_activity_frames(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        del lookback_days
        total_rows: list[dict[str, object]] = []
        daily_rows: list[dict[str, object]] = []
        if "AAPL" in tickers:
            total_rows.append(
                {
                    "ticker": "AAPL",
                    "trade_count": 1,
                    "total_volume": 100.0,
                    "total_notional": 10_000.0,
                    "signed_volume": 100.0,
                    "signed_notional": 10_000.0,
                    "net_volume_pressure": 1.0,
                    "net_notional_pressure": 1.0,
                    "pre_market_volume": 0.0,
                    "pre_market_signed_volume": 0.0,
                    "focus_trade_count": 0,
                    "absolute_block_count": 0,
                    "relative_block_count": 0,
                    "block_count": 0,
                    "off_exchange_count": 0,
                    "block_notional_threshold": 1_000_000.0,
                    "block_size_threshold": 10_000.0,
                    "focus_notional": 0.0,
                    "signed_focus_notional": 0.0,
                }
            )
            daily_rows.append(
                {
                    "ticker": "AAPL",
                    "date": as_of,
                    "trade_count": 1,
                    "notional": 10_000.0,
                    "volume": 100.0,
                    "signed_notional": 10_000.0,
                    "net_notional_pressure": 1.0,
                    "pre_market_count": 0,
                    "pre_market_notional": 0.0,
                    "pre_market_volume": 0.0,
                    "pre_market_signed_notional": 0.0,
                    "pre_market_pressure": 0.0,
                }
            )
        if "BK" in tickers:
            total_rows.append(
                {
                    "ticker": "BK",
                    "trade_count": 0,
                    "total_volume": 0.0,
                    "total_notional": 0.0,
                    "signed_volume": 0.0,
                    "signed_notional": 0.0,
                    "net_volume_pressure": 0.0,
                    "net_notional_pressure": 0.0,
                    "pre_market_volume": 0.0,
                    "pre_market_signed_volume": 0.0,
                    "focus_trade_count": 0,
                    "absolute_block_count": 0,
                    "relative_block_count": 0,
                    "block_count": 0,
                    "off_exchange_count": 0,
                    "block_notional_threshold": 1_000_000.0,
                    "block_size_threshold": 10_000.0,
                    "focus_notional": 0.0,
                    "signed_focus_notional": 0.0,
                }
            )
        return pl.DataFrame(total_rows), pl.DataFrame(daily_rows)


def _flow_trade(
    ticker: str,
    trade_date: date,
    notional: float,
    price: float,
    direction: int,
) -> dict[str, object]:
    size = notional / price
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "trade_ts": f"{trade_date.isoformat()}T13:30:00Z",
        "price": price,
        "size": size,
        "notional": notional,
        "direction": direction,
        "signed_volume": direction * size,
        "signed_notional": direction * notional,
        "session": "REGULAR",
        "is_block_trade": notional >= 200_000.0 or size >= 10_000.0,
        "is_off_exchange": False,
        "sequence_number": 1,
        "source_id": f"{ticker}-{trade_date.isoformat()}-{notional}",
        "timestamp_as_of": trade_date,
    }


def _trade(ticker: str, trade_date: date, direction: int) -> dict[str, object]:
    notional = 1_500_000.0
    size = 15_000.0
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
        "session": "PRE_MARKET",
        "is_block_trade": True,
        "is_off_exchange": True,
        "sequence_number": 1,
        "source_id": f"{ticker}-{trade_date.isoformat()}",
        "timestamp_as_of": trade_date,
    }
