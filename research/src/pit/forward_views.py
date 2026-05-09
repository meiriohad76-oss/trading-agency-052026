from __future__ import annotations

from datetime import date, timedelta
from typing import Protocol

import polars as pl

from agency.provenance import Provenanced

from .exceptions import DataNotAvailableAt
from .manifest import DatasetName
from .records import row_to_provenanced, rows


class ForwardLoaderSupport(Protocol):
    def _ensure_not_future(self, as_of: date) -> None: ...

    def _ensure_positive_lookback(self, lookback_days: int) -> None: ...

    def _read(self, dataset: DatasetName, as_of: date) -> pl.DataFrame: ...

    def _with_date(
        self,
        frame: pl.DataFrame,
        column: str,
        alias: str,
        dataset: DatasetName,
        as_of: date,
    ) -> pl.DataFrame: ...


def news_from_loader(
    loader: ForwardLoaderSupport,
    as_of: date,
    lookback_days: int,
    tickers: list[str] | None,
) -> list[Provenanced[dict[str, object]]]:
    loader._ensure_not_future(as_of)
    loader._ensure_positive_lookback(lookback_days)
    dataset = DatasetName.NEWS_RSS
    frame = loader._read(dataset, as_of)
    frame = loader._with_date(frame, "timestamp_as_of", "__as_of", dataset, as_of)
    filters = [pl.col("__as_of").is_between(as_of - timedelta(days=lookback_days - 1), as_of)]
    if tickers is not None:
        filters.append(pl.col("ticker").is_in([ticker.upper() for ticker in tickers]))
    filtered = frame.filter(*filters)
    if filtered.is_empty():
        raise DataNotAvailableAt(dataset.value, as_of, "no news rows matched")
    return [row_to_provenanced(row, exclude=set()) for row in rows(filtered.sort("__as_of"))]


def option_chains_from_loader(
    loader: ForwardLoaderSupport,
    tickers: list[str],
    as_of: date,
    lookback_days: int,
) -> pl.DataFrame:
    loader._ensure_not_future(as_of)
    loader._ensure_positive_lookback(lookback_days)
    dataset = DatasetName.OPTIONS_CHAINS
    frame = loader._read(dataset, as_of)
    frame = loader._with_date(frame, "snapshot_date", "__snapshot", dataset, as_of)
    frame = loader._with_date(frame, "timestamp_as_of", "__as_of", dataset, as_of)
    start = as_of - timedelta(days=lookback_days - 1)
    filtered = frame.filter(
        pl.col("ticker").is_in([ticker.upper() for ticker in tickers]),
        pl.col("__snapshot").is_between(start, as_of),
        pl.col("__as_of") <= as_of,
    ).drop(["__snapshot", "__as_of"])
    if filtered.is_empty():
        raise DataNotAvailableAt(dataset.value, as_of, "no option rows matched")
    return filtered.sort(["ticker", "snapshot_date", "expiration", "option_type", "strike"])


def stock_trades_from_loader(
    loader: ForwardLoaderSupport,
    tickers: list[str],
    as_of: date,
    lookback_days: int,
) -> pl.DataFrame:
    loader._ensure_not_future(as_of)
    loader._ensure_positive_lookback(lookback_days)
    dataset = DatasetName.STOCK_TRADES
    frame = loader._read(dataset, as_of)
    frame = loader._with_date(frame, "trade_date", "__trade_date", dataset, as_of)
    frame = loader._with_date(frame, "timestamp_as_of", "__as_of", dataset, as_of)
    start = as_of - timedelta(days=lookback_days - 1)
    filtered = frame.filter(
        pl.col("ticker").is_in([ticker.upper() for ticker in tickers]),
        pl.col("__trade_date").is_between(start, as_of),
        pl.col("__as_of") <= as_of,
    ).drop(["__trade_date", "__as_of"])
    if filtered.is_empty():
        raise DataNotAvailableAt(dataset.value, as_of, "no stock trade rows matched")
    return filtered.sort(["ticker", "trade_ts", "sequence_number", "source_id"])


def activity_alerts_from_loader(
    loader: ForwardLoaderSupport,
    tickers: list[str],
    as_of: date,
    lookback_days: int,
) -> list[Provenanced[dict[str, object]]]:
    loader._ensure_not_future(as_of)
    loader._ensure_positive_lookback(lookback_days)
    dataset = DatasetName.UNUSUAL_ACTIVITY_ALERTS
    frame = loader._read(dataset, as_of)
    frame = loader._with_date(frame, "timestamp_as_of", "__as_of", dataset, as_of)
    start = as_of - timedelta(days=lookback_days - 1)
    filtered = frame.filter(
        pl.col("ticker").is_in([ticker.upper() for ticker in tickers]),
        pl.col("__as_of").is_between(start, as_of),
    )
    if filtered.is_empty():
        raise DataNotAvailableAt(dataset.value, as_of, "no activity alert rows matched")
    return [row_to_provenanced(row, exclude=set()) for row in rows(filtered.sort("__as_of"))]
