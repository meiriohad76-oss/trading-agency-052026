from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from universe.membership import ChangeEvent


def _sp100_current(path: Path) -> list[str]:
    table = _table_with_columns(path, {"Symbol", "Name", "Sector"})
    return sorted(_ticker(value) for value in table["Symbol"])


def _nasdaq100_current(path: Path) -> list[str]:
    table = _table_with_columns(path, {"Ticker", "Company"})
    return sorted(_ticker(value) for value in table["Ticker"])


def _sp100_events(path: Path) -> list[ChangeEvent]:
    frame = pd.read_csv(path)
    events: list[ChangeEvent] = []
    for row in frame.to_dict("records"):
        events.append(
            ChangeEvent(
                effective_date=_date(row["effective_date"]),
                added_ticker=_optional_ticker(row["added_ticker"]),
                removed_ticker=_optional_ticker(row["removed_ticker"]),
                as_of_source=str(row["as_of_source"]),
            )
        )
    return events


def _nasdaq100_events(path: Path) -> list[ChangeEvent]:
    table = _table_with_columns(path, {"Date", "Added", "Removed"})
    table.columns = [
        "_".join(str(part) for part in column if str(part) != "nan").strip("_")
        if isinstance(column, tuple)
        else str(column)
        for column in table.columns
    ]
    events: list[ChangeEvent] = []
    for row in table.to_dict("records"):
        event_date = _date(row["Date_Date"])
        if event_date < date(2019, 1, 1):
            continue
        events.append(
            ChangeEvent(
                effective_date=event_date,
                added_ticker=_optional_ticker(row.get("Added_Ticker")),
                removed_ticker=_optional_ticker(row.get("Removed_Ticker")),
                as_of_source=f"https://en.wikipedia.org/wiki/Nasdaq-100#{event_date.isoformat()}",
            )
        )
    return events


def _table_with_columns(path: Path, required: set[str]) -> pd.DataFrame:
    for table in pd.read_html(path):
        column_names = {
            str(column[0] if isinstance(column, tuple) else column) for column in table.columns
        }
        if required.issubset(column_names):
            return table
    raise ValueError(f"No table in {path} had columns {sorted(required)}")


def _ticker(value: object) -> str:
    return str(value).strip().replace(".", ".").upper()


def _optional_ticker(value: object) -> str | None:
    if value is None:
        return None
    ticker = _ticker(value)
    if ticker in {"", "NAN"}:
        return None
    return ticker or None


def _date(value: object) -> date:
    return pd.Timestamp(str(value)).date()
