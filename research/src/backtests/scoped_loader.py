from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import polars as pl
from pit.exceptions import LookaheadRequested


class LoaderLike(Protocol):
    def universe_members(self, as_of: date) -> set[str]: ...

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame: ...

    def fundamentals(self, ticker: str, as_of: date) -> object: ...

    def insider_transactions(
        self,
        ticker: str,
        as_of: date,
        lookback_days: int,
    ) -> Sequence[object]: ...

    def institutional_holdings(self, ticker: str, as_of: date) -> object: ...

    def sector_etfs(self, as_of: date, lookback_days: int) -> pl.DataFrame: ...


SignalFn = Callable[[date, set[str], LoaderLike], dict[str, float]]


@dataclass(frozen=True)
class ScopedPITLoader:
    """Loader wrapper that rejects signal-time requests after the scoped date."""

    loader: LoaderLike
    as_of: date

    def universe_members(self, as_of: date) -> set[str]:
        self._ensure_in_scope(as_of)
        return self.loader.universe_members(as_of)

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        self._ensure_in_scope(as_of)
        return self.loader.prices(tickers, as_of, lookback_days)

    def fundamentals(self, ticker: str, as_of: date) -> object:
        self._ensure_in_scope(as_of)
        return self.loader.fundamentals(ticker, as_of)

    def insider_transactions(
        self,
        ticker: str,
        as_of: date,
        lookback_days: int,
    ) -> Sequence[object]:
        self._ensure_in_scope(as_of)
        return self.loader.insider_transactions(ticker, as_of, lookback_days)

    def institutional_holdings(self, ticker: str, as_of: date) -> object:
        self._ensure_in_scope(as_of)
        return self.loader.institutional_holdings(ticker, as_of)

    def sector_etfs(self, as_of: date, lookback_days: int) -> pl.DataFrame:
        self._ensure_in_scope(as_of)
        return self.loader.sector_etfs(as_of, lookback_days)

    def _ensure_in_scope(self, requested: date) -> None:
        if requested > self.as_of:
            raise LookaheadRequested(requested, self.as_of)
