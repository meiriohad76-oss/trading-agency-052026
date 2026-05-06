from __future__ import annotations

import pandas as pd


def subset_by_regime(returns: pd.Series, regime_dates: pd.DataFrame) -> dict[str, pd.Series]:
    """Split returns into named regime windows.

    `regime_dates` must contain `regime`, `start`, and `end` columns. Windows
    are inclusive and are evaluated against the returns index converted to
    pandas timestamps.
    """
    required = {"regime", "start", "end"}
    missing = required.difference(regime_dates.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    sorted_returns = returns.sort_index()
    output: dict[str, pd.Series] = {}
    for row in regime_dates.to_dict("records"):
        start = pd.Timestamp(str(row["start"]))
        end = pd.Timestamp(str(row["end"]))
        output[str(row["regime"])] = sorted_returns[
            (sorted_returns.index >= start) & (sorted_returns.index <= end)
        ]
    return output
