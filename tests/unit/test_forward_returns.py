from __future__ import annotations

import math
from datetime import date
from statistics.forward_returns import compute_forward_returns

import pandas as pd
import pytest

ONE_DAY_AAPL = 0.10
TWO_DAY_AAPL = 0.21
ONE_DAY_MSFT = 0.05
TWO_DAY_MSFT = 0.1025


def test_compute_forward_returns_uses_future_adjusted_close_by_ticker() -> None:
    prices = pd.DataFrame(
        [
            _price("AAPL", date(2022, 1, 1), 100.0),
            _price("MSFT", date(2022, 1, 1), 200.0),
            _price("AAPL", date(2022, 1, 2), 110.0),
            _price("MSFT", date(2022, 1, 2), 210.0),
            _price("AAPL", date(2022, 1, 3), 121.0),
            _price("MSFT", date(2022, 1, 3), 220.5),
        ]
    )

    result = compute_forward_returns(prices, [1, 2])

    first_aapl = _row(result, "AAPL", "2022-01-01")
    first_msft = _row(result, "MSFT", "2022-01-01")
    last_day = result[result["date"] == pd.Timestamp("2022-01-03")]

    assert first_aapl["forward_return_1"].item() == pytest.approx(ONE_DAY_AAPL)
    assert first_aapl["forward_return_2"].item() == pytest.approx(TWO_DAY_AAPL)
    assert first_msft["forward_return_1"].item() == pytest.approx(ONE_DAY_MSFT)
    assert first_msft["forward_return_2"].item() == pytest.approx(TWO_DAY_MSFT)
    assert math.isnan(last_day["forward_return_1"].iloc[0])


def test_compute_forward_returns_rejects_bad_horizons() -> None:
    with pytest.raises(ValueError, match="horizons"):
        compute_forward_returns(pd.DataFrame(columns=["date", "ticker", "adj_close"]), [0])


def _price(ticker: str, value_date: date, adj_close: float) -> dict[str, object]:
    return {"ticker": ticker, "date": value_date, "adj_close": adj_close}


def _row(frame: pd.DataFrame, ticker: str, value_date: str) -> pd.DataFrame:
    return frame[(frame["ticker"] == ticker) & (frame["date"] == pd.Timestamp(value_date))]
