from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import polars as pl
from market_flow.storage import coverage_key, load_stock_trade_coverage_metadata
from prices.sector_etfs import SECTOR_ETF_TICKERS

from agency.provenance import Provenance, Provenanced

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
    provenance_from_row,
    row_to_provenanced,
    rows,
)
from .sec_views import fundamentals_from_frame, institutional_holdings_from_frame

STALE_CONTEXT_READ_DATASETS = {DatasetName.SUBSCRIPTION_EMAILS}
STOCK_TRADE_BLOCK_ABSOLUTE_SHARES_FLOOR = 10_000.0
STOCK_TRADE_BLOCK_ABSOLUTE_NOTIONAL_FLOOR = 200_000.0
STOCK_TRADE_BLOCK_RELATIVE_MEDIAN_MULTIPLE = 5.0


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
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.parquet_root = Path(parquet_root)
        self.manifest_root = Path(manifest_root)
        self._today = today or date.today
        self._clock = clock or (lambda: datetime.now(UTC))
        self._manifests = ManifestRegistry(
            self.manifest_root,
            self.parquet_root,
            clock=self._clock,
        )
        self._read_cache: dict[tuple[DatasetName, date, str, str, str], pl.DataFrame] = {}
        self._stock_trade_activity_cache: dict[
            tuple[object, ...],
            tuple[pl.DataFrame, pl.DataFrame],
        ] = {}

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        """Daily OHLCV for `tickers` with record dates and knowledge dates <= `as_of`."""
        self._ensure_not_future(as_of)
        self._ensure_positive_lookback(lookback_days)
        dataset = DatasetName.PRICES_DAILY
        frame = self._read(dataset, as_of)
        frame = self._with_date(frame, "date", "__record_date", dataset, as_of)
        frame = self._with_datetime(
            frame,
            "timestamp_as_of",
            "__timestamp_as_of",
            dataset,
            as_of,
        )
        start = as_of - timedelta(days=lookback_days - 1)
        cutoff = self._as_of_cutoff(as_of)
        filtered = frame.filter(
            pl.col("ticker").is_in([ticker.upper() for ticker in tickers]),
            pl.col("__record_date").is_between(start, as_of),
            pl.col("__timestamp_as_of") <= cutoff,
        ).drop(["__record_date", "__timestamp_as_of"])
        if filtered.is_empty():
            return filtered
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
        return [row_to_provenanced(row, exclude={"ticker"}) for row in rows(frame.sort("__as_of"))]

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
        ):
            frame = self._with_date(frame, source, alias, DatasetName.UNIVERSE_MEMBERSHIP, as_of)
        frame = self._with_datetime(
            frame,
            "timestamp_as_of",
            "__timestamp_as_of",
            DatasetName.UNIVERSE_MEMBERSHIP,
            as_of,
        )
        cutoff = self._as_of_cutoff(as_of)
        filtered = frame.filter(
            pl.col("__start_date") <= as_of,
            pl.col("__end_date").is_null() | (pl.col("__end_date") > as_of),
            pl.col("__timestamp_as_of") <= cutoff,
        )
        if filtered.is_empty():
            raise DataNotAvailableAt(
                DatasetName.UNIVERSE_MEMBERSHIP.value,
                as_of,
                "no members matched",
            )
        member_rows = rows(filtered.sort("__timestamp_as_of", descending=True))
        tickers = [str(value) for value in filtered.get_column("ticker").to_list()]
        return ProvenancedTickerSet(tickers, _ticker_set_provenance(member_rows))

    def sector_etfs(self, as_of: date, lookback_days: int) -> pl.DataFrame:
        """Sector ETF OHLCV with the last N available bars known by `as_of`."""
        self._ensure_not_future(as_of)
        self._ensure_positive_lookback(lookback_days)
        dataset = DatasetName.PRICES_DAILY
        frame = self._read(dataset, as_of)
        frame = self._with_date(frame, "date", "__record_date", dataset, as_of)
        frame = self._with_datetime(
            frame,
            "timestamp_as_of",
            "__timestamp_as_of",
            dataset,
            as_of,
        )
        cutoff = self._as_of_cutoff(as_of)
        filtered = frame.filter(
            pl.col("ticker").is_in(SECTOR_ETF_TICKERS),
            pl.col("__record_date") <= as_of,
            pl.col("__timestamp_as_of") <= cutoff,
        ).sort(["ticker", "__record_date"])
        if filtered.is_empty():
            return filtered.drop(["__record_date", "__timestamp_as_of"])
        rows_by_ticker = filtered.partition_by("ticker", maintain_order=True)
        filtered = pl.concat([ticker_rows.tail(lookback_days) for ticker_rows in rows_by_ticker])
        filtered = filtered.drop(["__record_date", "__timestamp_as_of"])
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
        self._ensure_not_future(as_of)
        self._ensure_positive_lookback(lookback_days)
        normalized_tickers = tuple(sorted({ticker.upper() for ticker in tickers}))
        if not normalized_tickers:
            raise DataNotAvailableAt(DatasetName.STOCK_TRADES.value, as_of, "no tickers requested")
        manifest = self._manifests.require(DatasetName.STOCK_TRADES, as_of=as_of)
        try:
            return self._read_stock_trade_partitions(
                tickers=list(normalized_tickers),
                as_of=as_of,
                lookback_days=lookback_days,
            )
        except DataNotAvailableAt as exc:
            if manifest.path.is_dir():
                raise exc
            return stock_trades_from_loader(self, list(normalized_tickers), as_of, lookback_days)

    def stock_trade_activity_frames(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
        *,
        allow_partial_coverage: bool = False,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Ticker and daily trade summaries without materializing raw tape rows."""
        self._ensure_not_future(as_of)
        self._ensure_positive_lookback(lookback_days)
        normalized_tickers = tuple(sorted({ticker.upper() for ticker in tickers}))
        if not normalized_tickers:
            raise DataNotAvailableAt(DatasetName.STOCK_TRADES.value, as_of, "no tickers requested")
        manifest = self._manifests.require(DatasetName.STOCK_TRADES, as_of=as_of)
        cache_key = (
            as_of,
            lookback_days,
            normalized_tickers,
            str(allow_partial_coverage),
            manifest.checksum,
            manifest.fetched_at.isoformat(),
            str(manifest.path),
        )
        cached = self._stock_trade_activity_cache.get(cache_key)
        if cached is not None:
            return cached
        frames = self._read_stock_trade_activity_partitions(
            tickers=list(normalized_tickers),
            as_of=as_of,
            lookback_days=lookback_days,
            allow_partial_coverage=allow_partial_coverage,
        )
        self._stock_trade_activity_cache[cache_key] = frames
        return frames

    def stock_trade_activity_frames_for_trade_window(
        self,
        tickers: list[str],
        *,
        trade_end: date,
        knowledge_as_of: date,
        lookback_days: int,
        allow_partial_coverage: bool = False,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        """Trade summaries for a closed trade-date window using a later knowledge cutoff."""
        self._ensure_not_future(knowledge_as_of)
        self._ensure_positive_lookback(lookback_days)
        if trade_end > knowledge_as_of:
            raise LookaheadRequested(trade_end, knowledge_as_of)
        normalized_tickers = tuple(sorted({ticker.upper() for ticker in tickers}))
        if not normalized_tickers:
            raise DataNotAvailableAt(
                DatasetName.STOCK_TRADES.value, trade_end, "no tickers requested"
            )
        manifest = self._manifests.require(DatasetName.STOCK_TRADES, as_of=knowledge_as_of)
        cache_key = (
            trade_end,
            lookback_days,
            normalized_tickers,
            str(allow_partial_coverage),
            manifest.checksum,
            manifest.fetched_at.isoformat(),
            str(manifest.path),
            knowledge_as_of.isoformat(),
        )
        cached = self._stock_trade_activity_cache.get(cache_key)
        if cached is not None:
            return cached
        frames = self._read_stock_trade_activity_partitions(
            tickers=list(normalized_tickers),
            as_of=trade_end,
            lookback_days=lookback_days,
            allow_partial_coverage=allow_partial_coverage,
            knowledge_as_of=knowledge_as_of,
        )
        self._stock_trade_activity_cache[cache_key] = frames
        return frames

    def complete_stock_trade_tickers(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
        *,
        allow_partial_coverage: bool = False,
    ) -> tuple[str, ...]:
        """Return requested tickers with verified coverage for the full lookback window."""
        self._ensure_not_future(as_of)
        self._ensure_positive_lookback(lookback_days)
        normalized_tickers = tuple(sorted({ticker.upper() for ticker in tickers}))
        if not normalized_tickers:
            return ()
        dataset = DatasetName.STOCK_TRADES
        manifest = self._manifests.require(dataset, as_of=as_of)
        if not manifest.path.is_dir():
            return ()
        coverage = load_stock_trade_coverage_metadata(manifest.path)
        if not coverage:
            return ()
        start = as_of - timedelta(days=lookback_days - 1)
        complete: list[str] = []
        for ticker in normalized_tickers:
            try:
                self._ensure_complete_stock_trade_coverage(
                    manifest.path,
                    tickers=[ticker],
                    start=start,
                    end=as_of,
                    allow_partial_coverage=allow_partial_coverage,
                )
            except DataNotAvailableAt:
                continue
            complete.append(ticker)
        return tuple(complete)

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
        frame = self._with_datetime(
            frame,
            "timestamp_as_of",
            "__timestamp_as_of",
            dataset,
            as_of,
        )
        return frame.filter(
            pl.col("ticker") == ticker.upper(),
            pl.col("__timestamp_as_of") <= self._as_of_cutoff(as_of),
        )

    def _read(self, dataset: DatasetName, as_of: date) -> pl.DataFrame:
        manifest = self._manifests.require(
            dataset,
            as_of=as_of,
            allow_stale=dataset in STALE_CONTEXT_READ_DATASETS,
        )
        cache_key = (
            dataset,
            as_of,
            manifest.checksum,
            manifest.fetched_at.isoformat(),
            str(manifest.path),
        )
        cached = self._read_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            if manifest.path.is_dir():
                frame = self._read_partitioned(manifest.path)
            else:
                frame = pl.read_parquet(manifest.path)
        except Exception as exc:
            reason = f"could not read {manifest.path}"
            raise DataNotAvailableAt(dataset.value, as_of, reason) from exc
        self._read_cache[cache_key] = frame
        return frame

    @staticmethod
    def _read_partitioned(path: Path) -> pl.DataFrame:
        files = sorted(path.rglob("*.parquet"))
        if not files:
            return pl.DataFrame()
        frames = [frame for file in files if not (frame := pl.read_parquet(file)).is_empty()]
        if not frames:
            return pl.DataFrame()
        return pl.concat(frames, how="diagonal_relaxed")

    def _read_stock_trade_partitions(
        self,
        *,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame:
        dataset = DatasetName.STOCK_TRADES
        manifest = self._manifests.require(dataset, as_of=as_of)
        if not manifest.path.is_dir():
            raise DataNotAvailableAt(dataset.value, as_of, "stock trades are not partitioned")
        start = as_of - timedelta(days=lookback_days - 1)
        cutoff = self._as_of_cutoff(as_of)
        self._ensure_complete_stock_trade_coverage(
            manifest.path,
            tickers=tickers,
            start=start,
            end=as_of,
        )
        files = self._stock_trade_partition_files(manifest.path, tickers, start, as_of)
        if not files:
            raise DataNotAvailableAt(dataset.value, as_of, "no stock trade partitions matched")
        try:
            schema = pl.scan_parquet(files[0]).collect_schema()
            lazy = pl.scan_parquet(files)
            filtered = (
                lazy.with_columns(
                    self._lazy_date_expression("trade_date", schema).alias("__trade_date"),
                    self._lazy_datetime_expression("timestamp_as_of", schema).alias(
                        "__timestamp_as_of"
                    ),
                )
                .filter(
                    pl.col("ticker").is_in(tickers),
                    pl.col("__trade_date").is_between(start, as_of),
                    pl.col("__timestamp_as_of") <= cutoff,
                )
                .drop(["__trade_date", "__timestamp_as_of"])
                .sort(["ticker", "trade_ts", "sequence_number", "source_id"])
                .collect()
            )
        except Exception as exc:
            reason = f"could not read stock trade partitions under {manifest.path}"
            raise DataNotAvailableAt(dataset.value, as_of, reason) from exc
        if filtered.is_empty():
            raise DataNotAvailableAt(dataset.value, as_of, "no stock trade rows matched")
        return filtered

    def _read_stock_trade_activity_partitions(
        self,
        *,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
        allow_partial_coverage: bool = False,
        knowledge_as_of: date | None = None,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        dataset = DatasetName.STOCK_TRADES
        manifest = self._manifests.require(dataset, as_of=knowledge_as_of or as_of)
        if not manifest.path.is_dir():
            raise DataNotAvailableAt(dataset.value, as_of, "stock trades are not partitioned")
        start = as_of - timedelta(days=lookback_days - 1)
        cutoff = self._as_of_cutoff(knowledge_as_of or as_of)
        self._ensure_complete_stock_trade_coverage(
            manifest.path,
            tickers=tickers,
            start=start,
            end=as_of,
            allow_partial_coverage=allow_partial_coverage,
        )
        zero_activity_tickers = self._covered_zero_stock_trade_tickers(
            manifest.path,
            tickers=tickers,
            start=start,
            end=as_of,
        )
        files = self._stock_trade_partition_files(manifest.path, tickers, start, as_of)
        if not files:
            if zero_activity_tickers:
                return (
                    self._zero_stock_trade_total_activity(zero_activity_tickers),
                    self._empty_stock_trade_daily_activity(),
                )
            raise DataNotAvailableAt(dataset.value, as_of, "no stock trade partitions matched")
        try:
            schema = pl.scan_parquet(files[0]).collect_schema()
            ticker_median_size = pl.col("__size").median().over("ticker")
            ticker_median_notional = pl.col("__notional").median().over("ticker")
            prepared = (
                pl.scan_parquet(files)
                .with_columns(
                    pl.col("ticker").cast(pl.Utf8).str.to_uppercase().alias("ticker"),
                    self._lazy_numeric_expression(schema, "size", 0.0).alias("__size"),
                    self._lazy_notional_expression(schema).alias("__notional"),
                    self._lazy_signed_volume_expression(schema).alias("__signed_volume"),
                    self._lazy_signed_notional_expression(schema).alias("__signed_notional"),
                    self._lazy_date_expression("trade_date", schema).alias("__trade_date"),
                    self._lazy_datetime_expression("timestamp_as_of", schema).alias(
                        "__timestamp_as_of"
                    ),
                    self._lazy_session_expression(schema, "PRE_MARKET").alias("__is_pre_market"),
                    self._lazy_bool_expression(schema, "is_block_trade").alias(
                        "__source_block_trade"
                    ),
                    self._lazy_bool_expression(schema, "is_off_exchange").alias(
                        "__is_off_exchange"
                    ),
                    self._lazy_trf_off_exchange_expression(schema).alias("__is_trf_off_exchange"),
                )
                .with_columns(
                    (
                        pl.col("__source_block_trade")
                        | (pl.col("__size") >= STOCK_TRADE_BLOCK_ABSOLUTE_SHARES_FLOOR)
                        | (pl.col("__notional") >= STOCK_TRADE_BLOCK_ABSOLUTE_NOTIONAL_FLOOR)
                    ).alias("__absolute_block"),
                    (
                        (
                            (ticker_median_size > 0.0)
                            & (
                                pl.col("__size")
                                >= ticker_median_size * STOCK_TRADE_BLOCK_RELATIVE_MEDIAN_MULTIPLE
                            )
                        )
                        | (
                            (ticker_median_notional > 0.0)
                            & (
                                pl.col("__notional")
                                >= ticker_median_notional
                                * STOCK_TRADE_BLOCK_RELATIVE_MEDIAN_MULTIPLE
                            )
                        )
                    ).alias("__relative_block"),
                    pl.max_horizontal(
                        pl.lit(STOCK_TRADE_BLOCK_ABSOLUTE_SHARES_FLOOR),
                        ticker_median_size * STOCK_TRADE_BLOCK_RELATIVE_MEDIAN_MULTIPLE,
                    ).alias("__block_size_threshold"),
                    pl.max_horizontal(
                        pl.lit(STOCK_TRADE_BLOCK_ABSOLUTE_NOTIONAL_FLOOR),
                        ticker_median_notional * STOCK_TRADE_BLOCK_RELATIVE_MEDIAN_MULTIPLE,
                    ).alias("__block_notional_threshold"),
                    pl.when(ticker_median_notional > 0.0)
                    .then(pl.col("__notional") / ticker_median_notional)
                    .otherwise(0.0)
                    .alias("__notional_multiple"),
                )
                .with_columns(
                    pl.col("__absolute_block").alias("__is_block_trade"),
                    (pl.col("__absolute_block") & pl.col("__relative_block")).alias(
                        "__large_print"
                    ),
                    (
                        pl.col("__is_off_exchange")
                        | pl.col("__is_trf_off_exchange")
                        | (pl.col("__absolute_block") & pl.col("__relative_block"))
                    ).alias("__is_focus"),
                )
                .filter(
                    pl.col("ticker").is_in(tickers),
                    pl.col("__trade_date").is_between(start, as_of),
                    pl.col("__timestamp_as_of") <= cutoff,
                )
            )
            total_lazy = self._stock_trade_total_activity(prepared)
            daily_lazy = self._stock_trade_daily_activity(prepared)
            total, daily = pl.collect_all([total_lazy, daily_lazy])
        except Exception as exc:
            reason = f"could not summarize stock trade partitions under {manifest.path}"
            raise DataNotAvailableAt(dataset.value, as_of, reason) from exc
        observed_tickers = (
            set(total.get_column("ticker").to_list()) if not total.is_empty() else set()
        )
        missing_zero_tickers = [
            ticker for ticker in zero_activity_tickers if ticker not in observed_tickers
        ]
        if missing_zero_tickers:
            total = pl.concat(
                [total, self._zero_stock_trade_total_activity(missing_zero_tickers)],
                how="vertical_relaxed",
            ).sort("ticker")
        if total.is_empty():
            raise DataNotAvailableAt(dataset.value, as_of, "no stock trade rows matched")
        return total, daily

    @classmethod
    def _stock_trade_total_activity(cls, prepared: pl.LazyFrame) -> pl.LazyFrame:
        frame = prepared.group_by("ticker").agg(
            pl.len().alias("trade_count"),
            pl.col("__size").sum().alias("total_volume"),
            pl.col("__notional").sum().alias("total_notional"),
            pl.col("__signed_volume").sum().alias("signed_volume"),
            pl.col("__signed_notional").sum().alias("signed_notional"),
            pl.when(pl.col("__is_pre_market"))
            .then(pl.col("__size"))
            .otherwise(0.0)
            .sum()
            .alias("pre_market_volume"),
            pl.when(pl.col("__is_pre_market"))
            .then(pl.col("__signed_volume"))
            .otherwise(0.0)
            .sum()
            .alias("pre_market_signed_volume"),
            pl.col("__is_focus").sum().alias("focus_trade_count"),
            pl.col("__absolute_block").sum().alias("absolute_block_count"),
            pl.col("__relative_block").sum().alias("relative_block_count"),
            pl.col("__absolute_block").sum().alias("block_count"),
            pl.col("__is_off_exchange").sum().alias("off_exchange_count"),
            pl.col("__is_trf_off_exchange").sum().alias("trf_off_exchange_count"),
            pl.when(pl.col("__is_trf_off_exchange"))
            .then(pl.col("__notional"))
            .otherwise(0.0)
            .sum()
            .alias("trf_off_exchange_notional"),
            pl.col("__large_print").sum().alias("large_print_count"),
            pl.when(pl.col("__large_print"))
            .then(pl.col("__notional"))
            .otherwise(0.0)
            .sum()
            .alias("large_print_notional"),
            pl.col("__block_notional_threshold").max().alias("block_notional_threshold"),
            pl.col("__block_size_threshold").max().alias("block_size_threshold"),
            pl.when(pl.col("__is_focus"))
            .then(pl.col("__notional"))
            .otherwise(0.0)
            .sum()
            .alias("focus_notional"),
            pl.when(pl.col("__is_focus"))
            .then(pl.col("__signed_notional"))
            .otherwise(0.0)
            .sum()
            .alias("signed_focus_notional"),
            pl.when(pl.col("__is_focus"))
            .then(pl.col("__notional"))
            .otherwise(0.0)
            .max()
            .alias("largest_focus_notional"),
            pl.when(pl.col("__is_focus"))
            .then(pl.col("__notional_multiple"))
            .otherwise(0.0)
            .max()
            .alias("largest_focus_notional_multiple"),
        )
        return frame.with_columns(
            cls._lazy_safe_ratio_expression("signed_volume", "total_volume").alias(
                "net_volume_pressure"
            ),
            cls._lazy_safe_ratio_expression("signed_notional", "total_notional").alias(
                "net_notional_pressure"
            ),
        ).sort("ticker")

    @classmethod
    def _stock_trade_daily_activity(cls, prepared: pl.LazyFrame) -> pl.LazyFrame:
        frame = prepared.group_by(["ticker", "__trade_date"]).agg(
            pl.len().alias("trade_count"),
            pl.col("__notional").sum().alias("notional"),
            pl.col("__size").sum().alias("volume"),
            pl.col("__signed_notional").sum().alias("signed_notional"),
            pl.col("__is_pre_market").sum().alias("pre_market_count"),
            pl.when(pl.col("__is_pre_market"))
            .then(pl.col("__notional"))
            .otherwise(0.0)
            .sum()
            .alias("pre_market_notional"),
            pl.when(pl.col("__is_pre_market"))
            .then(pl.col("__size"))
            .otherwise(0.0)
            .sum()
            .alias("pre_market_volume"),
            pl.when(pl.col("__is_pre_market"))
            .then(pl.col("__signed_notional"))
            .otherwise(0.0)
            .sum()
            .alias("pre_market_signed_notional"),
        )
        return (
            frame.with_columns(
                pl.col("__trade_date").alias("date"),
                cls._lazy_safe_ratio_expression("signed_notional", "notional").alias(
                    "net_notional_pressure"
                ),
                cls._lazy_safe_ratio_expression(
                    "pre_market_signed_notional",
                    "pre_market_notional",
                ).alias("pre_market_pressure"),
            )
            .drop("__trade_date")
            .sort(["ticker", "date"])
        )

    @staticmethod
    def _stock_trade_partition_files(
        root: Path,
        tickers: list[str],
        start: date,
        end: date,
    ) -> list[str]:
        years = range(start.year, end.year + 1)
        files: list[str] = []
        for ticker in tickers:
            for year in years:
                path = root / f"ticker={ticker}" / f"year={year}" / "trades.parquet"
                if path.is_file():
                    files.append(str(path))
        return files

    @staticmethod
    def _covered_zero_stock_trade_tickers(
        root: Path,
        *,
        tickers: list[str],
        start: date,
        end: date,
    ) -> list[str]:
        coverage = load_stock_trade_coverage_metadata(root)
        zero_tickers: list[str] = []
        for ticker in tickers:
            current = start
            seen_days = 0
            zero_days = 0
            while current <= end:
                if current.weekday() >= 5:
                    current += timedelta(days=1)
                    continue
                seen_days += 1
                row = coverage.get(coverage_key(ticker, current))
                if row is not None and PITLoader._stock_trade_complete_zero_row(row):
                    zero_days += 1
                current += timedelta(days=1)
            if seen_days > 0 and zero_days == seen_days:
                zero_tickers.append(ticker)
        return zero_tickers

    @staticmethod
    def _stock_trade_complete_zero_row(row: Mapping[str, object]) -> bool:
        if str(row.get("coverage_status")).lower() != "complete":
            return False
        row_count_keys = ("downloaded_row_count", "row_count", "rows_written")
        reported_counts = [row.get(key) for key in row_count_keys if key in row]
        if not reported_counts:
            return False
        return all(PITLoader._positive_int(value) == 0 for value in reported_counts)

    @staticmethod
    def _zero_stock_trade_total_activity(tickers: list[str]) -> pl.DataFrame:
        return pl.DataFrame(
            [
                {
                    "ticker": ticker,
                    "trade_count": 0,
                    "total_volume": 0.0,
                    "total_notional": 0.0,
                    "signed_volume": 0.0,
                    "signed_notional": 0.0,
                    "pre_market_volume": 0.0,
                    "pre_market_signed_volume": 0.0,
                    "focus_trade_count": 0,
                    "absolute_block_count": 0,
                    "relative_block_count": 0,
                    "block_count": 0,
                    "off_exchange_count": 0,
                    "trf_off_exchange_count": 0,
                    "trf_off_exchange_notional": 0.0,
                    "large_print_count": 0,
                    "large_print_notional": 0.0,
                    "block_notional_threshold": 0.0,
                    "block_size_threshold": 0.0,
                    "focus_notional": 0.0,
                    "signed_focus_notional": 0.0,
                    "largest_focus_notional": 0.0,
                    "largest_focus_notional_multiple": 0.0,
                    "net_volume_pressure": 0.0,
                    "net_notional_pressure": 0.0,
                }
                for ticker in sorted(tickers)
            ]
        )

    @staticmethod
    def _empty_stock_trade_daily_activity() -> pl.DataFrame:
        return pl.DataFrame(
            schema={
                "ticker": pl.Utf8,
                "trade_count": pl.UInt32,
                "notional": pl.Float64,
                "volume": pl.Float64,
                "signed_notional": pl.Float64,
                "pre_market_count": pl.UInt32,
                "pre_market_notional": pl.Float64,
                "pre_market_volume": pl.Float64,
                "pre_market_signed_notional": pl.Float64,
                "date": pl.Date,
                "net_notional_pressure": pl.Float64,
                "pre_market_pressure": pl.Float64,
            }
        )

    @staticmethod
    def _ensure_complete_stock_trade_coverage(
        root: Path,
        *,
        tickers: list[str],
        start: date,
        end: date,
        allow_partial_coverage: bool = False,
    ) -> None:
        coverage = load_stock_trade_coverage_metadata(root)
        if not coverage:
            raise DataNotAvailableAt(
                DatasetName.STOCK_TRADES.value,
                end,
                "missing stock trade coverage metadata",
            )
        incomplete: list[str] = []
        for ticker in tickers:
            current = start
            usable_days = 0
            seen_days = 0
            while current <= end:
                if current.weekday() >= 5:
                    current += timedelta(days=1)
                    continue
                seen_days += 1
                key = coverage_key(ticker, current)
                row = coverage.get(key)
                if row is None:
                    if not allow_partial_coverage or current == end:
                        incomplete.append(f"{ticker}|{current}:missing")
                elif (
                    str(row.get("coverage_status")) == "complete"
                    or allow_partial_coverage
                    and PITLoader._stock_trade_partial_row_usable(row)
                ):
                    usable_days += 1
                else:
                    incomplete.append(f"{ticker}|{current}:{row.get('coverage_status')}")
                current += timedelta(days=1)
            if allow_partial_coverage and seen_days > 0 and usable_days == 0:
                incomplete.append(f"{ticker}|{start}..{end}:missing")
        if incomplete:
            raise DataNotAvailableAt(
                DatasetName.STOCK_TRADES.value,
                end,
                f"incomplete stock trade coverage: {', '.join(incomplete[:3])}",
            )

    @staticmethod
    def _stock_trade_partial_row_usable(row: Mapping[str, object]) -> bool:
        if str(row.get("coverage_status")).lower() != "partial":
            return False
        downloaded = PITLoader._positive_int(row.get("downloaded_row_count"))
        pages = PITLoader._positive_int(row.get("pages_downloaded"))
        order = str(row.get("order") or "").lower()
        return downloaded > 0 and pages > 0 and order == "desc"

    @staticmethod
    def _positive_int(value: object) -> int:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return max(value, 0)
        if isinstance(value, float):
            return max(round(value), 0)
        return 0

    @staticmethod
    def _lazy_date_expression(column: str, schema: pl.Schema) -> pl.Expr:
        dtype = schema.get(column)
        if dtype == pl.Date:
            return pl.col(column)
        if dtype == pl.Utf8:
            return pl.col(column).str.to_datetime(strict=False, time_zone="UTC").dt.date()
        if isinstance(dtype, pl.Datetime):
            return pl.col(column).dt.date()
        return pl.col(column).cast(pl.Date, strict=False)

    @staticmethod
    def _lazy_numeric_expression(schema: pl.Schema, column: str, default: float) -> pl.Expr:
        if column not in schema:
            return pl.lit(default)
        return pl.col(column).cast(pl.Float64, strict=False).fill_null(default)

    @classmethod
    def _lazy_notional_expression(cls, schema: pl.Schema) -> pl.Expr:
        if "notional" in schema:
            return cls._lazy_numeric_expression(schema, "notional", 0.0)
        return cls._lazy_numeric_expression(schema, "price", 0.0) * cls._lazy_numeric_expression(
            schema,
            "size",
            0.0,
        )

    @classmethod
    def _lazy_signed_volume_expression(cls, schema: pl.Schema) -> pl.Expr:
        if "signed_volume" in schema:
            return cls._lazy_numeric_expression(schema, "signed_volume", 0.0)
        if "direction" in schema:
            return cls._lazy_numeric_expression(
                schema,
                "direction",
                0.0,
            ) * cls._lazy_numeric_expression(schema, "size", 0.0)
        return pl.lit(0.0)

    @classmethod
    def _lazy_signed_notional_expression(cls, schema: pl.Schema) -> pl.Expr:
        if "signed_notional" in schema:
            return cls._lazy_numeric_expression(schema, "signed_notional", 0.0)
        if "direction" in schema:
            return cls._lazy_numeric_expression(
                schema,
                "direction",
                0.0,
            ) * cls._lazy_notional_expression(schema)
        return pl.lit(0.0)

    @staticmethod
    def _lazy_session_expression(schema: pl.Schema, session: str) -> pl.Expr:
        if "session" not in schema:
            return pl.lit(False)
        return (
            pl.col("session")
            .cast(pl.Utf8, strict=False)
            .str.to_uppercase()
            .eq(session)
            .fill_null(False)
        )

    @staticmethod
    def _lazy_bool_expression(schema: pl.Schema, column: str) -> pl.Expr:
        if column not in schema:
            return pl.lit(False)
        dtype = schema[column]
        if dtype == pl.Boolean:
            return pl.col(column).fill_null(False)
        if dtype.is_numeric():
            return (pl.col(column).fill_null(0) != 0).fill_null(False)
        return (
            pl.col(column)
            .cast(pl.Utf8, strict=False)
            .str.to_lowercase()
            .str.strip_chars()
            .is_in(["1", "true", "t", "yes", "y"])
            .fill_null(False)
        )

    @staticmethod
    def _lazy_text_expression(schema: pl.Schema, column: str) -> pl.Expr:
        if column not in schema:
            return pl.lit("")
        return pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars().fill_null("")

    @classmethod
    def _lazy_trf_off_exchange_expression(cls, schema: pl.Schema) -> pl.Expr:
        explicit = cls._lazy_bool_expression(schema, "is_trf_off_exchange")
        inferred = cls._lazy_text_expression(schema, "exchange").is_in(["4", "4.0"]) & (
            cls._lazy_text_expression(schema, "trf_id") != ""
        )
        return (explicit | inferred).fill_null(False)

    @staticmethod
    def _lazy_safe_ratio_expression(numerator: str, denominator: str) -> pl.Expr:
        return (
            pl.when(pl.col(denominator) > 0.0)
            .then(pl.col(numerator) / pl.col(denominator))
            .otherwise(0.0)
        )

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
        dtype = frame.schema[column]
        if dtype == pl.Date:
            expression = pl.col(column)
        elif dtype == pl.Utf8:
            expression = pl.col(column).str.to_datetime(strict=False, time_zone="UTC").dt.date()
        elif isinstance(dtype, pl.Datetime):
            expression = pl.col(column).dt.date()
        else:
            expression = pl.col(column).cast(pl.Date, strict=False)
        return frame.with_columns(expression.alias(alias))

    def _with_datetime(
        self,
        frame: pl.DataFrame,
        column: str,
        alias: str,
        dataset: DatasetName,
        as_of: date,
    ) -> pl.DataFrame:
        if column not in frame.columns:
            raise DataNotAvailableAt(dataset.value, as_of, f"missing column {column}")
        dtype = frame.schema[column]
        if isinstance(dtype, pl.Datetime):
            expression = pl.col(column)
        elif dtype == pl.Date:
            expression = pl.col(column).cast(pl.Datetime(time_zone="UTC"), strict=False)
        elif dtype == pl.Utf8:
            expression = pl.col(column).str.to_datetime(strict=False, time_zone="UTC")
        else:
            expression = pl.col(column).cast(pl.Datetime(time_zone="UTC"), strict=False)
        return frame.with_columns(expression.alias(alias))

    def _as_of_cutoff(self, as_of: date) -> datetime:
        current = self._clock()
        if current.tzinfo is None or current.utcoffset() is None:
            current = current.replace(tzinfo=UTC)
        current = current.astimezone(UTC)
        if as_of == self._today() and current.date() == as_of:
            return current
        return datetime.combine(as_of, time.max, tzinfo=UTC)

    @staticmethod
    def _lazy_datetime_expression(column: str, schema: pl.Schema) -> pl.Expr:
        if column not in schema:
            return pl.lit(None, dtype=pl.Datetime(time_zone="UTC"))
        dtype = schema[column]
        if isinstance(dtype, pl.Datetime):
            expression = pl.col(column)
        elif dtype == pl.Date:
            expression = pl.col(column).cast(pl.Datetime(time_zone="UTC"), strict=False)
        elif dtype == pl.Utf8:
            expression = pl.col(column).str.to_datetime(strict=False, time_zone="UTC")
        else:
            expression = pl.col(column).cast(pl.Datetime(time_zone="UTC"), strict=False)
        return (
            expression.dt.replace_time_zone("UTC")
            if getattr(dtype, "time_zone", None) is None
            else expression
        )

    def _ensure_not_future(self, as_of: date) -> None:
        today = self._today()
        if as_of > today:
            raise LookaheadRequested(as_of, today)

    @staticmethod
    def _ensure_positive_lookback(lookback_days: int) -> None:
        if lookback_days < 1:
            raise ValueError("lookback_days must be >= 1")


def _ticker_set_provenance(member_rows: list[Mapping[str, object]]) -> Provenance:
    if not member_rows:
        raise DataNotAvailableAt(DatasetName.UNIVERSE_MEMBERSHIP.value, None, "no members matched")
    provenance = provenance_from_row(member_rows[0])
    if len(member_rows) == 1:
        return provenance
    identity_parts = sorted(
        "|".join(
            (
                str(row.get("ticker") or ""),
                str(row.get("source_id") or ""),
                str(row.get("timestamp_as_of") or ""),
            )
        )
        for row in member_rows
    )
    digest = hashlib.sha256("\n".join(identity_parts).encode("utf-8")).hexdigest()[:16]
    return provenance.model_copy(
        update={
            "source_id": f"universe-membership:{len(member_rows)}:{digest}",
            "source_url": None,
        }
    )
