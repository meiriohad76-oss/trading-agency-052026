from __future__ import annotations

from datetime import datetime

from pit.manifest import DatasetName


def effective_freshness_timestamp(
    dataset: DatasetName,
    timestamp_as_of: datetime,
    checked_at: datetime,
) -> datetime:
    if dataset is DatasetName.PRICES_DAILY and timestamp_as_of.date() == checked_at.date():
        return checked_at
    return timestamp_as_of
