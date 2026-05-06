from __future__ import annotations

from datetime import date
from typing import cast

import pandas as pd

BASE_DATE = date(2019, 1, 1)


def active_members(frame: pd.DataFrame, as_of: date, index_name: str) -> set[str]:
    active = frame[
        (frame["index_name"] == index_name)
        & (frame["start_date"] <= as_of)
        & (frame["end_date"].isna() | (frame["end_date"] > as_of))
    ]
    return set(active["ticker"].astype(str))


def validate_membership(frame: pd.DataFrame) -> None:
    closed = frame[frame["end_date"].notna()]
    if not (closed["start_date"] < closed["end_date"]).all():
        raise ValueError("closed rows must have start_date < end_date")
    for index_name, group in frame.groupby("index_name"):
        _validate_index_counts(frame, str(index_name))
        for ticker, rows in group.groupby("ticker"):
            ordered = rows.sort_values("start_date")
            last_end: date | None = None
            for row in ordered.to_dict("records"):
                start_date = cast(date, row["start_date"])
                if last_end is not None and start_date < last_end:
                    raise ValueError(f"overlap for {index_name}/{ticker}")
                last_end = cast(date | None, row["end_date"])


def _validate_index_counts(frame: pd.DataFrame, index_name: str) -> None:
    floor = 95 if index_name == "NASDAQ100" else 98
    for as_of in (BASE_DATE, date(2022, 6, 15), date(2026, 5, 6)):
        count = len(active_members(frame, as_of, index_name))
        if count < floor:
            raise ValueError(f"{index_name} has only {count} active members at {as_of}")
