from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol

import pandas as pd
from pit.exceptions import DataNotAvailableAt
from signals._common import float_or_none, payload_dict, positive_float, score_dict, zscore


class InstitutionalHoldingsLoader(Protocol):
    def institutional_holdings(self, ticker: str, as_of: date) -> object: ...


def institutional_score(
    as_of: date,
    universe: set[str],
    loader: InstitutionalHoldingsLoader,
) -> dict[str, float]:
    """Return a PIT-safe institutional accumulation/distribution score."""
    return score_dict(institutional_factor_frame(as_of, universe, loader), "institutional_score")


def institutional_factor_frame(
    as_of: date,
    universe: Iterable[str],
    loader: InstitutionalHoldingsLoader,
) -> pd.DataFrame:
    """Build the 13F institutional flow cross-section known at `as_of`."""
    rows = []
    for ticker in sorted({item.upper() for item in universe}):
        try:
            payload = payload_dict(loader.institutional_holdings(ticker, as_of), "holdings")
        except DataNotAvailableAt:
            continue
        row = _factor_row(ticker, payload)
        if row is not None:
            rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return _empty_frame()
    for column in ("total_change_from_prev_quarter", "change_ratio"):
        frame[f"{column}_z"] = zscore(frame[column])
    z_columns = ["total_change_from_prev_quarter_z", "change_ratio_z"]
    frame["institutional_score"] = frame[z_columns].mean(axis=1)
    return frame.sort_values(
        ["institutional_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)


def _factor_row(ticker: str, payload: dict[str, object]) -> dict[str, object] | None:
    quarterly_change = float_or_none(payload.get("total_change_from_prev_quarter"))
    if quarterly_change is None:
        return None
    total_shares = positive_float(payload.get("total_shares_held")) or 0.0
    holder_count = positive_float(payload.get("holder_count")) or 0.0
    change_ratio = quarterly_change / total_shares if total_shares > 0.0 else 0.0
    return {
        "ticker": ticker,
        "quarter_end_date": payload.get("quarter_end_date"),
        "holder_count": holder_count,
        "total_shares_held": total_shares,
        "total_change_from_prev_quarter": quarterly_change,
        "change_ratio": change_ratio,
    }


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "quarter_end_date",
            "holder_count",
            "total_shares_held",
            "total_change_from_prev_quarter",
            "change_ratio",
            "total_change_from_prev_quarter_z",
            "change_ratio_z",
            "institutional_score",
        ]
    )
