from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import polars as pl
from prices.sector_etfs import SECTOR_ETF_TICKERS

from agency.provenance import Provenanced

from .exceptions import DataNotAvailableAt, LookaheadRequested
from .forward_views import (
    activity_alerts_from_loader,
    news_from_loader,
    option_chains_from_loader,
    stock_trades_from_loader,
    subscription_emails_from_loader,
)
from .manifest import DatasetName, ManifestRegistry
from .records import (
    ProvenancedTickerSet,
    date_to_utc,
    provenance_from_row,
    row_to_provenanced,
    rows,
)
from .sec_views import fundamentals_from_frame, institutional_holdings_from_frame


class PITLoader:
    """Canonical point-in-time access layer for research datasets.

    Every method rejects future `as_of` dates and filters records to
    `timestamp_as_of <= as_of`, so callers cannot accidentally read future
    revisions or direct parquet files.
    """

    def __init__(
        self,
        *,
        parquet_root: Path | str = Path("research/data/parquet"),
        manifest_root: Path | str = Path("research/data/manifests"),
        today: Callable[[], date] | None = None,
    ) -> None:
        self.parquet_root = Path(parquet_root)
        self.manifest_root = Path(manifest_root)
        self._today = today or date.today
        self._manifests = ManifestRegistry(
            self.manifest_root,
            self.parquet_root,
            clock=lambda: date_to_utc(self._today()),
        )

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        """Daily OHLCV for `tickers` with record dates and knowledge dates <= `as_of`."""
        self._ensure_not_future(as_of)
        self._ensure_positive_lookback(lookback_days)
        dataset = DatasetName.PRICES_DAILY
        frame = self._read(dataset, as_of)
        frame = self._with_date(frame, "date", "__record_date", dataset, as_of)
        frame = self._with_date(frame, "timestamp_as_of", "__as_of", dataset, as_of)
        start = as_of - timedelta(days=lookback_days - 1)
        filtered = frame.filter(
            pl.col("ticker").is_in([ticker.upper() for ticker in tickers]),
            pl.col("__record_date").is_between(start, as_of),
            pl.col("__as_of") <= as_of,
        ).drop(["__record_date", "__as_of"])
        if filtered.is_empty():
            raise DataNotAvailableAt(dataset.value, as_of, "no PIT rows matched")
        return filtered.sort(["ticker", "date"])

    def fundamentals(self, ticker: str, as_of: date) -> Provenanced[dict[str, object]]:
        """Latest SEC company-facts metrics filed on or before `as_of`."""
        frame = self._ticker_frame(DatasetName.SEC_COMPANY_FACTS, ticker, as_of)
        frame = self._with_date(
            frame,
            "period_end",
            "__period_end",
            DatasetName.SEC_COMPANY_FACTS,
            as_of,
        )
        return fundamentals_from_frame(frame, as_of=as_of)

    def insider_transactions(
        self,
        ticker: str,
        as_of: date,
        lookback_days: int,
    ) -> list[Provenanced[dict[str, object]]]:
        """Form 4 events filed on or before `as_of`, limited by filing-date lookback."""
        self._ensure_not_future(as_of)
        self._ensure_positive_lookback(lookback_days)
        frame = self._ticker_frame(DatasetName.SEC_FORM4, ticker, as_of)
        start = as_of - timedelta(days=lookback_days - 1)
        frame = frame.filter(pl.col("__as_of").is_between(start, as_of))
        return [
            row_to_provenanced(row, exclude={"ticker"}) for row in rows(frame.sort("__as_of"))
        ]

    def institutional_holdings(self, ticker: str, as_of: date) -> Provenanced[dict[str, object]]:
        """Most recent 13F-derived holdings row available on or before `as_of`."""
        frame = self._ticker_frame(DatasetName.SEC_13F, ticker, as_of)
        frame = self._with_date(
            frame,
            "quarter_end_date",
            "__quarter_end",
            DatasetName.SEC_13F,
            as_of,
        )
        return institutional_holdings_from_frame(frame, ticker=ticker, as_of=as_of)

    def universe_members(self, as_of: date) -> set[str]:
        """Historical S&P 100 + QQQ members where start_date <= `as_of` < end_date."""
        self._ensure_not_future(as_of)
        frame = self._read(DatasetName.UNIVERSE_MEMBERSHIP, as_of)
        for source, alias in (
            ("start_date", "__start_date"),
            ("end_date", "__end_date"),
            ("timestamp_as_of", "__as_of"),
        ):
            frame = self._with_date(frame, source, alias, DatasetName.UNIVERSE_MEMBERSHIP, as_of)
        filtered = frame.filter(
            pl.col("__start_date") <= as_of,
            pl.col("__end_date").is_null() | (pl.col("__end_date") > as_of),
            pl.col("__as_of") <= as_of,
        )
        if filtered.is_empty():
            raise DataNotAvailableAt(
                DatasetName.UNIVERSE_MEMBERSHIP.value,
                as_of,
                "no members matched",
            )
        row = rows(filtered.sort("__as_of", descending=True).head(1))[0]
        tickers = [str(value) for value in filtered.get_column("ticker").to_list()]
        return ProvenancedTickerSet(tickers, provenance_from_row(row))

    def sector_etfs(self, as_of: date, lookback_days: int) -> pl.DataFrame:
        """Sector ETF OHLCV with the last N available bars known by `as_of`."""
        self._ensure_not_future(as_of)
        self._ensure_positive_lookback(lookback_days)
        dataset = DatasetName.PRICES_DAILY
        frame = self._read(dataset, as_of)
        frame = self._with_date(frame, "date", "__record_date", dataset, as_of)
        frame = self._with_date(frame, "timestamp_as_of", "__as_of", dataset, as_of)
        filtered = frame.filter(
            pl.col("ticker").is_in(SECTOR_ETF_TICKERS),
            pl.col("__record_date") <= as_of,
            pl.col("__as_of") <= as_of,
        ).sort(["ticker", "__record_date"])
        if filtered.is_empty():
            raise DataNotAvailableAt(dataset.value, as_of, "no sector ETF rows matched")
        rows_by_ticker = filtered.partition_by("ticker", maintain_order=True)
        filtered = pl.concat([ticker_rows.tail(lookback_days) for ticker_rows in rows_by_ticker])
        filtered = filtered.drop(["__record_date", "__as_of"])
        return filtered.sort(["ticker", "date"])

    def news(
        self,
        as_of: date,
        lookback_days: int,
        tickers: list[str] | None = None,
    ) -> list[Provenanced[dict[str, object]]]:
        """Forward RSS/news items observed on or before `as_of`."""
        return news_from_loader(self, as_of, lookback_days, tickers)

    def option_chains(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        return option_chains_from_loader(self, tickers, as_of, lookback_days)

    def stock_trades(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        return stock_trades_from_loader(self, tickers, as_of, lookback_days)

    def activity_alerts(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> list[Provenanced[dict[str, object]]]:
        return activity_alerts_from_loader(self, tickers, as_of, lookback_days)

    def subscription_emails(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> list[Provenanced[dict[str, object]]]:
        return subscription_emails_from_loader(self, tickers, as_of, lookback_days)

    def prepost_bars(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        """Extended-hours bars placeholder until the pre/post puller lands."""
        del tickers, lookback_days
        self._ensure_not_future(as_of)
        raise DataNotAvailableAt("prepost_bars", as_of, "pre/post puller not implemented")

    def _ticker_frame(self, dataset: DatasetName, ticker: str, as_of: date) -> pl.DataFrame:
        self._ensure_not_future(as_of)
        frame = self._read(dataset, as_of)
        frame = self._with_date(frame, "timestamp_as_of", "__as_of", dataset, as_of)
        return frame.filter(pl.col("ticker") == ticker.upper(), pl.col("__as_of") <= as_of)

    def _read(self, dataset: DatasetName, as_of: date) -> pl.DataFrame:
        manifest = self._manifests.require(dataset, as_of=as_of)
        try:
            if manifest.path.is_dir():
                return self._read_partitioned(manifest.path)
            return pl.read_parquet(manifest.path)
        except Exception as exc:
            reason = f"could not read {manifest.path}"
            raise DataNotAvailableAt(dataset.value, as_of, reason) from exc

    @staticmethod
    def _read_partitioned(path: Path) -> pl.DataFrame:
        files = sorted(path.rglob("*.parquet"))
        if not files:
            return pl.DataFrame()
        frames = [frame for file in files if not (frame := pl.read_parquet(file)).is_empty()]
        if not frames:
            return pl.DataFrame()
        return pl.concat(frames, how="diagonal_relaxed")

    def _with_date(
        self,
        frame: pl.DataFrame,
        column: str,
        alias: str,
        dataset: DatasetName,
        as_of: date,
    ) -> pl.DataFrame:
        if column not in frame.columns:
            raise DataNotAvailableAt(dataset.value, as_of, f"missing column {column}")
        return frame.with_columns(pl.col(column).cast(pl.Date).alias(alias))

    def _ensure_not_future(self, as_of: date) -> None:
        today = self._today()
        if as_of > today:
            raise LookaheadRequested(as_of, today)

    @staticmethod
    def _ensure_positive_lookback(lookback_days: int) -> None:
        if lookback_days < 1:
            raise ValueError("lookback_days must be >= 1")
