from __future__ import annotations

from datetime import date, datetime, timedelta
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

    def _with_datetime(
        self,
        frame: pl.DataFrame,
        column: str,
        alias: str,
        dataset: DatasetName,
        as_of: date,
    ) -> pl.DataFrame: ...

    def _as_of_cutoff(self, as_of: date) -> datetime: ...


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
    frame = loader._with_datetime(
        frame,
        "timestamp_as_of",
        "__timestamp_as_of",
        dataset,
        as_of,
    ).with_columns(pl.col("__timestamp_as_of").dt.date().alias("__as_of"))
    filters = [
        pl.col("__as_of").is_between(as_of - timedelta(days=lookback_days - 1), as_of),
        pl.col("__timestamp_as_of") <= loader._as_of_cutoff(as_of),
    ]
    if tickers is not None:
        filters.append(pl.col("ticker").is_in([ticker.upper() for ticker in tickers]))
    filtered = frame.filter(*filters).sort("__timestamp_as_of").drop(
        ["__as_of", "__timestamp_as_of"]
    )
    if filtered.is_empty():
        raise DataNotAvailableAt(dataset.value, as_of, "no news rows matched")
    return [row_to_provenanced(row, exclude=set()) for row in rows(filtered)]


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
    frame = loader._with_datetime(
        frame,
        "timestamp_as_of",
        "__timestamp_as_of",
        dataset,
        as_of,
    )
    start = as_of - timedelta(days=lookback_days - 1)
    filtered = frame.filter(
        pl.col("ticker").is_in([ticker.upper() for ticker in tickers]),
        pl.col("__snapshot").is_between(start, as_of),
        pl.col("__timestamp_as_of") <= loader._as_of_cutoff(as_of),
    ).with_columns(pl.col("__timestamp_as_of").alias("timestamp_as_of")).drop(
        ["__snapshot", "__timestamp_as_of"]
    )
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
    frame = loader._with_datetime(
        frame,
        "timestamp_as_of",
        "__timestamp_as_of",
        dataset,
        as_of,
    )
    start = as_of - timedelta(days=lookback_days - 1)
    cutoff = loader._as_of_cutoff(as_of)
    filtered = frame.filter(
        pl.col("ticker").is_in([ticker.upper() for ticker in tickers]),
        pl.col("__trade_date").is_between(start, as_of),
        pl.col("__timestamp_as_of") <= cutoff,
    ).drop(["__trade_date", "__timestamp_as_of"])
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
    frame = loader._with_datetime(
        frame,
        "timestamp_as_of",
        "__timestamp_as_of",
        dataset,
        as_of,
    ).with_columns(pl.col("__timestamp_as_of").dt.date().alias("__as_of"))
    start = as_of - timedelta(days=lookback_days - 1)
    filtered = frame.filter(
        pl.col("ticker").is_in([ticker.upper() for ticker in tickers]),
        pl.col("__as_of").is_between(start, as_of),
        pl.col("__timestamp_as_of") <= loader._as_of_cutoff(as_of),
    ).sort("__timestamp_as_of").drop(["__as_of", "__timestamp_as_of"])
    if filtered.is_empty():
        raise DataNotAvailableAt(dataset.value, as_of, "no activity alert rows matched")
    return [row_to_provenanced(row, exclude=set()) for row in rows(filtered)]


def subscription_emails_from_loader(
    loader: ForwardLoaderSupport,
    tickers: list[str],
    as_of: date,
    lookback_days: int,
) -> list[Provenanced[dict[str, object]]]:
    loader._ensure_not_future(as_of)
    loader._ensure_positive_lookback(lookback_days)
    dataset = DatasetName.SUBSCRIPTION_EMAILS
    frame = _with_subscription_defaults(loader._read(dataset, as_of))
    frame = loader._with_datetime(
        frame,
        "timestamp_as_of",
        "__timestamp_as_of",
        dataset,
        as_of,
    ).with_columns(pl.col("__timestamp_as_of").dt.date().alias("__as_of"))
    start = as_of - timedelta(days=lookback_days - 1)
    filtered = frame.filter(
        pl.col("ticker").is_in([ticker.upper() for ticker in tickers]),
        pl.col("__as_of").is_between(start, as_of),
        pl.col("__timestamp_as_of") <= loader._as_of_cutoff(as_of),
    ).sort("__timestamp_as_of").drop(["__as_of", "__timestamp_as_of"])
    if filtered.is_empty():
        raise DataNotAvailableAt(dataset.value, as_of, "no subscription email rows matched")
    return [row_to_provenanced(row, exclude=set()) for row in rows(filtered)]


def _with_subscription_defaults(frame: pl.DataFrame) -> pl.DataFrame:
    defaults: dict[str, object] = {
        "source": "subscription-email",
        "source_tier": "PAID_SUB_EMAIL",
        "freshness": "FRESH",
        "linked_content_summary": None,
    }
    expressions = [
        pl.lit(value).alias(column)
        for column, value in defaults.items()
        if column not in frame.columns
    ]
    return frame.with_columns(expressions) if expressions else frame
