from __future__ import annotations

from datetime import date


class PITLoaderError(RuntimeError):
    """Base error for point-in-time data loading failures."""


class DataNotAvailableAt(PITLoaderError):  # noqa: N818 - ticket names this exception.
    def __init__(self, dataset: str, as_of: date | None, reason: str) -> None:
        when = f" at {as_of.isoformat()}" if as_of is not None else ""
        super().__init__(f"{dataset} data is not available{when}: {reason}")
        self.dataset = dataset
        self.as_of = as_of
        self.reason = reason


class LookaheadRequested(PITLoaderError):  # noqa: N818 - ticket names this exception.
    def __init__(self, as_of: date, today: date) -> None:
        super().__init__(
            f"as_of={as_of.isoformat()} is in the future; today is {today.isoformat()}"
        )
        self.as_of = as_of
        self.today = today
