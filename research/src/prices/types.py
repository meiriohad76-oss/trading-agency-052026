from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

import pandas as pd
from prices.storage import DateRange

Downloader = Callable[[str, DateRange], Awaitable[pd.DataFrame]]


class HistoryNormalizer(Protocol):
    def __call__(
        self,
        ticker: str,
        raw: pd.DataFrame,
        *,
        fetched_at: datetime,
    ) -> pd.DataFrame: ...
