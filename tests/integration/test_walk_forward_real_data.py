from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from backtests.portfolio import CostModel
from backtests.walk_forward import WalkForward, WalkForwardConfig
from pit.loader import PITLoader


def test_walk_forward_buy_and_hold_spy_when_real_prices_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    required = root / "research" / "data" / "manifests" / "prices_daily.json"
    if not required.exists():
        pytest.skip("real prices_daily dataset is populated by data-pull tickets")

    config = WalkForwardConfig(
        step_size_days=30,
        max_positions=1,
        static_universe={"SPY"},
        cost_model=CostModel(bps_per_side=0.0),
    )
    loader = PITLoader(today=lambda: date(2026, 5, 6))
    portfolio = WalkForward(config, loader, _long_spy).run(date(2022, 1, 3), date(2022, 3, 31))
    spy_prices = loader.prices(["SPY"], date(2022, 3, 31), lookback_days=120).to_pandas()
    spy_prices = spy_prices.sort_values("date")
    window = spy_prices[
        (spy_prices["date"] >= date(2022, 1, 3)) & (spy_prices["date"] <= date(2022, 3, 31))
    ]
    expected = window["adj_close"].iloc[-1] / window["adj_close"].iloc[0] - 1.0

    assert portfolio.equity_curve.iloc[-1] / portfolio.equity_curve.iloc[0] - 1.0 == pytest.approx(
        expected,
        abs=0.01,
    )


def _long_spy(as_of: date, universe: set[str], loader: object) -> dict[str, float]:
    del as_of, universe, loader
    return {"SPY": 1.0}
