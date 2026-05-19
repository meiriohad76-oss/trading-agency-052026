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
