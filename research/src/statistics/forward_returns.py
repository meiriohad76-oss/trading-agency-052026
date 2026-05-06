from __future__ import annotations

import pandas as pd

DATE_COLUMN = "date"
TICKER_COLUMN = "ticker"
PRICE_COLUMN = "adj_close"
RETURN_PREFIX = "forward_return_"


def compute_forward_returns(prices: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Compute PIT-safe forward returns from adjusted close prices.

    For a row at date D and horizon h, the result is
    `adj_close(D + h trading rows) / adj_close(D) - 1`. The function sorts
    independently within each ticker and never uses prices before D to compute
    the label at D. Rows that do not have a future close h rows ahead receive
    `NaN` for that horizon.
    """
    _validate_horizons(horizons)
    _require_columns(prices, {DATE_COLUMN, TICKER_COLUMN, PRICE_COLUMN})
    ordered = prices[[DATE_COLUMN, TICKER_COLUMN, PRICE_COLUMN]].copy()
    ordered[DATE_COLUMN] = pd.to_datetime(ordered[DATE_COLUMN])
    ordered = ordered.sort_values([TICKER_COLUMN, DATE_COLUMN]).reset_index(drop=True)
    grouped = ordered.groupby(TICKER_COLUMN, sort=False)[PRICE_COLUMN]
    output = ordered[[DATE_COLUMN, TICKER_COLUMN]].copy()
    for horizon in horizons:
        future_price = grouped.shift(-horizon)
        output[f"{RETURN_PREFIX}{horizon}"] = future_price / ordered[PRICE_COLUMN] - 1.0
    return output


def _validate_horizons(horizons: list[int]) -> None:
    if not horizons:
        raise ValueError("horizons must not be empty")
    if any(horizon < 1 for horizon in horizons):
        raise ValueError("all horizons must be >= 1")
    if len(horizons) != len(set(horizons)):
        raise ValueError("horizons must be unique")


def _require_columns(frame: pd.DataFrame, columns: set[str]) -> None:
    missing = columns.difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
