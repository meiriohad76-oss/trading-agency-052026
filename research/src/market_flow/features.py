from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, cast

import pandas as pd
import polars as pl
from pit.exceptions import DataNotAvailableAt
from signals.calibration import (
    DEFAULT_THRESHOLDS,
    anomaly_band,
    robust_mad_score,
    robust_z_score,
)

FEATURE_COLUMNS = (
    "buy_sell_pressure",
    "block_trade_pressure",
    "unusual_trade_activity",
    "pre_market_unusual_activity",
    "market_flow_trend",
)
DEFAULT_LOOKBACK_DAYS = 3
MIN_TREND_OBSERVATIONS = 2
ACTIVITY_FRAME_PAIR_LENGTH = 2
MarketFlowCacheKey = tuple[object, ...]


@dataclass(frozen=True)
class MarketFlowFeatureConfig:
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    pre_market_weight: float = 0.35
    net_notional_weight: float = 0.45
    net_volume_weight: float = 0.20
    block_absolute_shares_floor: float = DEFAULT_THRESHOLDS.block_absolute_shares_floor
    block_absolute_notional_floor: float = DEFAULT_THRESHOLDS.block_absolute_notional_floor
    block_relative_median_multiple: float = DEFAULT_THRESHOLDS.block_relative_median_multiple


class StockTradesLoader(Protocol):
    def stock_trades(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
    ) -> pl.DataFrame: ...


def market_flow_feature_frame(
    as_of: date,
    universe: Iterable[str],
    loader: StockTradesLoader,
    config: MarketFlowFeatureConfig | None = None,
) -> pd.DataFrame:
    normalized_config = config or MarketFlowFeatureConfig()
    if normalized_config.lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    tickers = sorted({item.upper() for item in universe})
    if not tickers:
        return _empty_frame()
    cache_key: MarketFlowCacheKey = (
        as_of,
        normalized_config.lookback_days,
        normalized_config.pre_market_weight,
        normalized_config.net_notional_weight,
        normalized_config.net_volume_weight,
        normalized_config.block_absolute_shares_floor,
        normalized_config.block_absolute_notional_floor,
        normalized_config.block_relative_median_multiple,
        tuple(tickers),
    )
    cached = _feature_cache_get(loader, cache_key)
    if cached is not None:
        return cached.copy()
    activity_frames = _loader_activity_frames(
        loader,
        tickers,
        as_of,
        normalized_config.lookback_days,
    )
    if activity_frames is None:
        try:
            raw = loader.stock_trades(tickers, as_of, normalized_config.lookback_days)
        except DataNotAvailableAt:
            return _empty_frame()
        if raw.is_empty():
            return _empty_frame()
        prepared = _prepared_trade_frame(raw, normalized_config)
        total_frame = _total_activity(prepared)
        daily_frame = _daily_activity_polars(prepared)
    else:
        total_frame, daily_frame = activity_frames
    totals = total_frame.to_pandas()
    daily = daily_frame.to_pandas()
    daily_by_ticker = {
        str(ticker): group.sort_values("date").reset_index(drop=True)
        for ticker, group in daily.groupby("ticker", sort=True)
    }
    rows = []
    for _, total in totals.iterrows():
        ticker = str(total["ticker"])
        total_volume = float(total["total_volume"])
        total_notional = float(total["total_notional"])
        ticker_daily = daily_by_ticker.get(ticker, pd.DataFrame())
        pre_market_volume = float(total["pre_market_volume"])
        pre_market_signed_volume = float(total["pre_market_signed_volume"])
        focus_trade_count = _int_from_row(total, "focus_trade_count")
        absolute_block_count = _int_from_row(
            total, "absolute_block_count", _int_from_row(total, "block_count")
        )
        relative_block_count = _int_from_row(total, "relative_block_count")
        focus_notional = _float_from_row(total, "focus_notional")
        signed_focus_notional = _float_from_row(total, "signed_focus_notional")
        directional_pressure = _ratio(signed_focus_notional, focus_notional)
        focus_notional_share = _ratio(focus_notional, total_notional)
        focus_activity_score = focus_notional_share * math.log1p(focus_trade_count)
        activity_metadata = _activity_anomaly_metadata(ticker_daily)
        trend_participation = _market_flow_trend_participation(ticker_daily)
        buy_sell_pressure = (
            normalized_config.net_notional_weight * _float_from_row(total, "net_notional_pressure")
            + normalized_config.net_volume_weight * _float_from_row(total, "net_volume_pressure")
            + normalized_config.pre_market_weight
            * _ratio(pre_market_signed_volume, pre_market_volume)
            * min(1.0, _ratio(pre_market_volume, total_volume) * 4.0)
        )
        block_trade_pressure = directional_pressure * focus_activity_score
        rows.append(
            {
                "ticker": ticker,
                "trade_count": int(total["trade_count"]),
                "total_volume": total_volume,
                "total_notional": total_notional,
                "net_volume_pressure": _float_from_row(total, "net_volume_pressure"),
                "net_notional_pressure": _float_from_row(total, "net_notional_pressure"),
                "latest_net_notional_pressure": _latest_metric(
                    ticker_daily,
                    "net_notional_pressure",
                ),
                "latest_pre_market_pressure": _latest_metric(
                    ticker_daily,
                    "pre_market_pressure",
                ),
                "pre_market_volume": pre_market_volume,
                "pre_market_volume_share": _ratio(pre_market_volume, total_volume),
                "pre_market_net_pressure": _ratio(pre_market_signed_volume, pre_market_volume),
                "focus_trade_count": focus_trade_count,
                "block_count": absolute_block_count,
                "absolute_block_count": absolute_block_count,
                "relative_block_count": relative_block_count,
                "off_exchange_count": _int_from_row(total, "off_exchange_count"),
                "trf_off_exchange_count": _int_from_row(total, "trf_off_exchange_count"),
                "trf_off_exchange_notional": _float_from_row(total, "trf_off_exchange_notional"),
                "trf_off_exchange_share": _ratio(
                    _float_from_row(total, "trf_off_exchange_notional"),
                    total_notional,
                ),
                "large_print_count": _int_from_row(total, "large_print_count"),
                "large_print_notional": _float_from_row(total, "large_print_notional"),
                "largest_focus_notional": _float_from_row(total, "largest_focus_notional"),
                "largest_focus_notional_multiple": _float_from_row(
                    total,
                    "largest_focus_notional_multiple",
                ),
                "focus_notional": focus_notional,
                "focus_notional_share": focus_notional_share,
                "signed_focus_notional": signed_focus_notional,
                "directional_pressure": directional_pressure,
                "focus_activity_score": focus_activity_score,
                "block_notional_threshold": _float_from_row(
                    total,
                    "block_notional_threshold",
                    normalized_config.block_absolute_notional_floor,
                ),
                "block_size_threshold": _float_from_row(
                    total,
                    "block_size_threshold",
                    normalized_config.block_absolute_shares_floor,
                ),
                "block_threshold_method": "absolute_floor_and_5x_ticker_median",
                "buy_sell_pressure": buy_sell_pressure,
                "block_trade_pressure": block_trade_pressure,
                **activity_metadata,
                "unusual_trade_activity": _unusual_trade_activity(ticker_daily),
                "pre_market_unusual_activity": _pre_market_unusual_activity(ticker_daily),
                "market_flow_trend": _market_flow_trend(ticker_daily),
                "market_flow_trend_participation": trend_participation,
            }
        )
    output = pd.DataFrame(rows)
    result = _empty_frame() if output.empty else output.sort_values("ticker").reset_index(drop=True)
    _feature_cache_set(loader, cache_key, result)
    return result.copy()


def _feature_cache_get(loader: object, key: MarketFlowCacheKey) -> pd.DataFrame | None:
    cache = getattr(loader, "_market_flow_feature_cache", None)
    if not isinstance(cache, dict):
        return None
    value = cache.get(key)
    return value if isinstance(value, pd.DataFrame) else None


def _feature_cache_set(loader: object, key: MarketFlowCacheKey, frame: pd.DataFrame) -> None:
    cache = getattr(loader, "_market_flow_feature_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        cast(Any, loader)._market_flow_feature_cache = cache
    cache[key] = frame.copy()


def _loader_activity_frames(
    loader: object,
    tickers: list[str],
    as_of: date,
    lookback_days: int,
) -> tuple[pl.DataFrame, pl.DataFrame] | None:
    method = getattr(loader, "stock_trade_activity_frames", None)
    if not callable(method):
        return None
    try:
        result = method(tickers, as_of, lookback_days)
    except DataNotAvailableAt:
        return None
    if (
        isinstance(result, tuple)
        and len(result) == ACTIVITY_FRAME_PAIR_LENGTH
        and isinstance(result[0], pl.DataFrame)
        and isinstance(result[1], pl.DataFrame)
    ):
        return result
    return None


def _prepared_trade_frame(raw: pl.DataFrame, config: MarketFlowFeatureConfig) -> pl.DataFrame:
    schema = raw.schema
    frame = raw.with_columns(
        pl.col("ticker").cast(pl.Utf8).str.to_uppercase().alias("ticker"),
        _numeric_expr(schema, "size", 0.0).alias("__size"),
        _notional_expr(schema).alias("__notional"),
        _signed_volume_expr(schema).alias("__signed_volume"),
        _signed_notional_expr(schema).alias("__signed_notional"),
        _date_expr(schema).alias("__date"),
        _session_expr(schema, "PRE_MARKET").alias("__is_pre_market"),
        _bool_expr(schema, "is_block_trade").alias("__source_block_trade"),
        _bool_expr(schema, "is_off_exchange").alias("__is_off_exchange"),
        _trf_off_exchange_expr(schema).alias("__is_trf_off_exchange"),
    )
    ticker_median_size = pl.col("__size").median().over("ticker")
    ticker_median_notional = pl.col("__notional").median().over("ticker")
    return frame.with_columns(
        (
            pl.col("__source_block_trade")
            | (pl.col("__size") >= config.block_absolute_shares_floor)
            | (pl.col("__notional") >= config.block_absolute_notional_floor)
        ).alias("__absolute_block"),
        (
            (
                (ticker_median_size > 0.0)
                & (pl.col("__size") >= ticker_median_size * config.block_relative_median_multiple)
            )
            | (
                (ticker_median_notional > 0.0)
                & (
                    pl.col("__notional")
                    >= ticker_median_notional * config.block_relative_median_multiple
                )
            )
        ).alias("__relative_block"),
        pl.max_horizontal(
            pl.lit(config.block_absolute_shares_floor),
            ticker_median_size * config.block_relative_median_multiple,
        ).alias("__block_size_threshold"),
        pl.max_horizontal(
            pl.lit(config.block_absolute_notional_floor),
            ticker_median_notional * config.block_relative_median_multiple,
        ).alias("__block_notional_threshold"),
        pl.when(ticker_median_notional > 0.0)
        .then(pl.col("__notional") / ticker_median_notional)
        .otherwise(0.0)
        .alias("__notional_multiple"),
    ).with_columns(
        pl.col("__absolute_block").alias("__is_block_trade"),
        (pl.col("__absolute_block") & pl.col("__relative_block")).alias("__large_print"),
        (
            pl.col("__is_off_exchange")
            | pl.col("__is_trf_off_exchange")
            | (pl.col("__absolute_block") & pl.col("__relative_block"))
        ).alias("__is_focus"),
    )


def _total_activity(prepared: pl.DataFrame) -> pl.DataFrame:
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
        _safe_ratio_expr("signed_volume", "total_volume").alias("net_volume_pressure"),
        _safe_ratio_expr("signed_notional", "total_notional").alias("net_notional_pressure"),
    ).sort("ticker")


def _daily_activity_polars(prepared: pl.DataFrame) -> pl.DataFrame:
    frame = prepared.group_by(["ticker", "__date"]).agg(
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
            pl.col("__date").alias("date"),
            _safe_ratio_expr("signed_notional", "notional").alias("net_notional_pressure"),
            _safe_ratio_expr("pre_market_signed_notional", "pre_market_notional").alias(
                "pre_market_pressure"
            ),
        )
        .drop("__date")
        .sort(["ticker", "date"])
    )


def _numeric_expr(schema: pl.Schema, column: str, default: float) -> pl.Expr:
    if column not in schema:
        return pl.lit(default)
    return pl.col(column).cast(pl.Float64, strict=False).fill_null(default)


def _notional_expr(schema: pl.Schema) -> pl.Expr:
    if "notional" in schema:
        return _numeric_expr(schema, "notional", 0.0)
    return _numeric_expr(schema, "price", 0.0) * _numeric_expr(schema, "size", 0.0)


def _signed_volume_expr(schema: pl.Schema) -> pl.Expr:
    if "signed_volume" in schema:
        return _numeric_expr(schema, "signed_volume", 0.0)
    if "direction" in schema:
        return _numeric_expr(schema, "direction", 0.0) * _numeric_expr(schema, "size", 0.0)
    return pl.lit(0.0)


def _signed_notional_expr(schema: pl.Schema) -> pl.Expr:
    if "signed_notional" in schema:
        return _numeric_expr(schema, "signed_notional", 0.0)
    if "direction" in schema:
        return _numeric_expr(schema, "direction", 0.0) * _notional_expr(schema)
    return pl.lit(0.0)


def _date_expr(schema: pl.Schema) -> pl.Expr:
    column = "trade_date" if "trade_date" in schema else "trade_ts"
    dtype = schema.get(column)
    if dtype == pl.Date:
        return pl.col(column)
    if dtype == pl.Utf8:
        return pl.col(column).str.to_datetime(strict=False, time_zone="UTC").dt.date()
    if isinstance(dtype, pl.Datetime):
        return pl.col(column).dt.date()
    return pl.col(column).cast(pl.Date, strict=False)


def _session_expr(schema: pl.Schema, session: str) -> pl.Expr:
    if "session" not in schema:
        return pl.lit(False)
    return (
        pl.col("session")
        .cast(pl.Utf8, strict=False)
        .str.to_uppercase()
        .eq(session)
        .fill_null(False)
    )


def _bool_expr(schema: pl.Schema, column: str) -> pl.Expr:
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


def _text_expr(schema: pl.Schema, column: str) -> pl.Expr:
    if column not in schema:
        return pl.lit("")
    return pl.col(column).cast(pl.Utf8, strict=False).str.strip_chars().fill_null("")


def _trf_off_exchange_expr(schema: pl.Schema) -> pl.Expr:
    explicit = _bool_expr(schema, "is_trf_off_exchange")
    inferred = _text_expr(schema, "exchange").is_in(["4", "4.0"]) & (
        _text_expr(schema, "trf_id") != ""
    )
    return (explicit | inferred).fill_null(False)


def _safe_ratio_expr(numerator: str, denominator: str) -> pl.Expr:
    return (
        pl.when(pl.col(denominator) > 0.0)
        .then(pl.col(numerator) / pl.col(denominator))
        .otherwise(0.0)
    )


def _feature_row(
    ticker: str,
    group: pd.DataFrame,
    config: MarketFlowFeatureConfig,
) -> dict[str, object] | None:
    prepared = group.assign(
        __size=_numeric(group, "size", 0.0),
        __notional=_notional(group),
        __signed_volume=_numeric(group, "signed_volume", 0.0),
        __signed_notional=_numeric(group, "signed_notional", 0.0),
    )
    total_volume = float(prepared["__size"].sum())
    total_notional = float(prepared["__notional"].sum())
    if total_volume <= 0.0 or total_notional <= 0.0:
        return None
    pre_market = prepared[_session_mask(prepared, "PRE_MARKET")]
    focus = prepared[_bool(prepared, "is_block_trade") | _bool(prepared, "is_off_exchange")]
    buy_sell_pressure = _buy_sell_pressure(prepared, pre_market, config, total_volume)
    block_trade_pressure = _block_trade_pressure(focus, total_notional)
    daily = _daily_activity(prepared)
    unusual_trade_activity = _unusual_trade_activity(daily)
    pre_market_unusual_activity = _pre_market_unusual_activity(daily)
    market_flow_trend = _market_flow_trend(daily)
    return {
        "ticker": ticker,
        "trade_count": len(prepared),
        "total_volume": total_volume,
        "total_notional": total_notional,
        "net_volume_pressure": _ratio(float(prepared["__signed_volume"].sum()), total_volume),
        "net_notional_pressure": _ratio(
            float(prepared["__signed_notional"].sum()),
            total_notional,
        ),
        "pre_market_volume": float(pre_market["__size"].sum()),
        "block_count": int(_bool(focus, "is_block_trade").sum()) if not focus.empty else 0,
        "off_exchange_count": int(_bool(focus, "is_off_exchange").sum()) if not focus.empty else 0,
        "focus_notional": float(focus["__notional"].sum()) if not focus.empty else 0.0,
        "buy_sell_pressure": buy_sell_pressure,
        "block_trade_pressure": block_trade_pressure,
        "unusual_trade_activity": unusual_trade_activity,
        "pre_market_unusual_activity": pre_market_unusual_activity,
        "market_flow_trend": market_flow_trend,
    }


def _buy_sell_pressure(
    prepared: pd.DataFrame,
    pre_market: pd.DataFrame,
    config: MarketFlowFeatureConfig,
    total_volume: float,
) -> float:
    total_notional = float(prepared["__notional"].sum())
    pre_market_volume = float(pre_market["__size"].sum())
    pre_market_share = _ratio(pre_market_volume, total_volume)
    return (
        config.net_notional_weight
        * _ratio(float(prepared["__signed_notional"].sum()), total_notional)
        + config.net_volume_weight * _ratio(float(prepared["__signed_volume"].sum()), total_volume)
        + config.pre_market_weight
        * _ratio(float(pre_market["__signed_volume"].sum()), pre_market_volume)
        * min(1.0, pre_market_share * 4.0)
    )


def _block_trade_pressure(focus: pd.DataFrame, total_notional: float) -> float:
    if focus.empty:
        return 0.0
    focus_notional = float(focus["__notional"].sum())
    directional_pressure = _ratio(float(focus["__signed_notional"].sum()), focus_notional)
    activity_share = _ratio(focus_notional, total_notional)
    return directional_pressure * activity_share * math.log1p(len(focus))


def _daily_activity(prepared: pd.DataFrame) -> pd.DataFrame:
    frame = prepared.copy()
    if "trade_date" in frame.columns:
        frame["__date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date
    elif "trade_ts" in frame.columns:
        frame["__date"] = pd.to_datetime(frame["trade_ts"], errors="coerce", utc=True).dt.date
    else:
        frame["__date"] = 0
    frame["__is_pre_market"] = _session_mask(frame, "PRE_MARKET")
    grouped = frame.groupby("__date", dropna=False, sort=True)
    rows: list[dict[str, object]] = []
    for day, group in grouped:
        notional = float(group["__notional"].sum())
        volume = float(group["__size"].sum())
        signed_notional = float(group["__signed_notional"].sum())
        pre_market = group[group["__is_pre_market"]]
        pre_market_notional = float(pre_market["__notional"].sum())
        pre_market_volume = float(pre_market["__size"].sum())
        rows.append(
            {
                "date": day,
                "trade_count": len(group),
                "notional": notional,
                "volume": volume,
                "signed_notional": signed_notional,
                "net_notional_pressure": _ratio(signed_notional, notional),
                "pre_market_count": len(pre_market),
                "pre_market_notional": pre_market_notional,
                "pre_market_volume": pre_market_volume,
                "pre_market_signed_notional": float(pre_market["__signed_notional"].sum()),
                "pre_market_pressure": _ratio(
                    float(pre_market["__signed_notional"].sum()),
                    pre_market_notional,
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def _unusual_trade_activity(daily: pd.DataFrame) -> float:
    if daily.empty:
        return 0.0
    latest = daily.iloc[-1]
    baseline = daily.iloc[:-1]
    pressure = float(latest["net_notional_pressure"])
    if baseline.empty:
        return pressure * math.log1p(float(latest["trade_count"])) / 4.0
    count_ratio = _activity_ratio(
        float(latest["trade_count"]),
        _positive_median(baseline["trade_count"]),
    )
    notional_ratio = _activity_ratio(
        float(latest["notional"]),
        _positive_median(baseline["notional"]),
    )
    volume_ratio = _activity_ratio(float(latest["volume"]), _positive_median(baseline["volume"]))
    anomaly = max(count_ratio, notional_ratio, volume_ratio) - 1.0
    return pressure * math.log1p(max(anomaly, 0.0))


def _pre_market_unusual_activity(daily: pd.DataFrame) -> float:
    if daily.empty:
        return 0.0
    latest = daily.iloc[-1]
    latest_volume = float(latest["pre_market_volume"])
    if latest_volume <= 0.0:
        return 0.0
    baseline = daily.iloc[:-1]
    pressure = float(latest["pre_market_pressure"])
    if baseline.empty:
        regular_volume = max(float(latest["volume"]) - latest_volume, 0.0)
        share = _ratio(latest_volume, regular_volume + latest_volume)
        return pressure * min(1.0, share * 4.0)
    volume_ratio = _activity_ratio(latest_volume, _positive_median(baseline["pre_market_volume"]))
    notional_ratio = _activity_ratio(
        float(latest["pre_market_notional"]),
        _positive_median(baseline["pre_market_notional"]),
    )
    anomaly = max(volume_ratio, notional_ratio) - 1.0
    return pressure * math.log1p(max(anomaly, 0.0))


def _market_flow_trend(daily: pd.DataFrame) -> float:
    if len(daily) < MIN_TREND_OBSERVATIONS:
        return 0.0
    latest = daily.iloc[-1]
    history = daily.iloc[:-1]
    latest_pressure = float(latest["net_notional_pressure"])
    prior_pressure = float(history["net_notional_pressure"].median())
    pressure_delta = latest_pressure - prior_pressure
    participation = _market_flow_trend_participation(daily)
    return latest_pressure * 0.65 + pressure_delta * 0.35 * max(participation, 0.25)


def _activity_anomaly_metadata(daily: pd.DataFrame) -> dict[str, object]:
    if daily.empty:
        return {
            "trade_count_anomaly_ratio": 0.0,
            "notional_anomaly_ratio": 0.0,
            "volume_anomaly_ratio": 0.0,
            "activity_anomaly_z_score": 0.0,
            "activity_anomaly_mad_score": 0.0,
            "activity_anomaly_band": "normal",
        }
    latest = daily.iloc[-1]
    baseline = daily.iloc[:-1]
    if baseline.empty:
        trade_count_ratio = 1.0
        notional_ratio = 1.0
        volume_ratio = 1.0
        z_score = 0.0
        mad_score = 0.0
    else:
        trade_count_ratio = _activity_ratio(
            float(latest["trade_count"]),
            _positive_median(baseline["trade_count"]),
        )
        notional_ratio = _activity_ratio(
            float(latest["notional"]),
            _positive_median(baseline["notional"]),
        )
        volume_ratio = _activity_ratio(
            float(latest["volume"]),
            _positive_median(baseline["volume"]),
        )
        z_scores = [
            robust_z_score(float(latest["trade_count"]), baseline["trade_count"]),
            robust_z_score(float(latest["notional"]), baseline["notional"]),
            robust_z_score(float(latest["volume"]), baseline["volume"]),
        ]
        mad_scores = [
            robust_mad_score(float(latest["trade_count"]), baseline["trade_count"]),
            robust_mad_score(float(latest["notional"]), baseline["notional"]),
            robust_mad_score(float(latest["volume"]), baseline["volume"]),
        ]
        z_score = max(z_scores, key=abs)
        mad_score = max(mad_scores, key=abs)
    max_ratio = max(trade_count_ratio, notional_ratio, volume_ratio)
    return {
        "trade_count_anomaly_ratio": trade_count_ratio,
        "notional_anomaly_ratio": notional_ratio,
        "volume_anomaly_ratio": volume_ratio,
        "activity_anomaly_z_score": z_score,
        "activity_anomaly_mad_score": mad_score,
        "activity_anomaly_band": anomaly_band(max_ratio, z_score, mad_score),
    }


def _market_flow_trend_participation(daily: pd.DataFrame) -> float:
    if len(daily) < MIN_TREND_OBSERVATIONS:
        return 0.0
    latest = daily.iloc[-1]
    history = daily.iloc[:-1]
    latest_notional = float(latest["notional"])
    prior_notional = _positive_median(history["notional"])
    return min(
        1.0,
        math.log1p(max(_activity_ratio(latest_notional, prior_notional) - 1.0, 0.0)),
    )


def _latest_metric(daily: pd.DataFrame, column: str) -> float:
    if daily.empty or column not in daily.columns:
        return 0.0
    value = daily.iloc[-1][column]
    try:
        parsed = float(value)
    except TypeError, ValueError:
        return 0.0
    return parsed if math.isfinite(parsed) else 0.0


def _numeric(frame: pd.DataFrame, column: str, default: float) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([default for _ in range(len(frame))], index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def _notional(frame: pd.DataFrame) -> pd.Series:
    if "notional" in frame.columns:
        return _numeric(frame, "notional", 0.0)
    return _numeric(frame, "price", 0.0) * _numeric(frame, "size", 0.0)


def _session_mask(frame: pd.DataFrame, session: str) -> pd.Series:
    if "session" not in frame.columns:
        return pd.Series([False for _ in range(len(frame))], index=frame.index)
    return frame["session"].astype(str).str.upper() == session


def _bool(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([False for _ in range(len(frame))], index=frame.index)
    return frame[column].map(_bool_value).fillna(False).astype(bool)


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value is pd.NA or value is pd.NaT:
        return False
    if isinstance(value, int | float):
        if isinstance(value, float) and pd.isna(value):
            return False
        return value != 0
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "t", "yes", "y"}
    return bool(value)


def _positive_median(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    values = values[values > 0.0]
    return 0.0 if values.empty else float(values.median())


def _ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return 0.0
    return numerator / denominator


def _activity_ratio(latest: float, baseline: float) -> float:
    if latest <= 0.0:
        return 0.0
    if baseline <= 0.0:
        return 2.0
    return latest / baseline


def _float_from_row(row: pd.Series, column: str, default: float = 0.0) -> float:
    value = row.get(column, default)
    try:
        parsed = float(value)
    except TypeError, ValueError:
        return default
    return parsed if math.isfinite(parsed) else default


def _int_from_row(row: pd.Series, column: str, default: int = 0) -> int:
    return int(_float_from_row(row, column, float(default)))


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "trade_count",
            "total_volume",
            "total_notional",
            "net_volume_pressure",
            "net_notional_pressure",
            "latest_net_notional_pressure",
            "latest_pre_market_pressure",
            "pre_market_volume",
            "pre_market_volume_share",
            "pre_market_net_pressure",
            "focus_trade_count",
            "block_count",
            "absolute_block_count",
            "relative_block_count",
            "off_exchange_count",
            "trf_off_exchange_count",
            "trf_off_exchange_notional",
            "trf_off_exchange_share",
            "large_print_count",
            "large_print_notional",
            "largest_focus_notional",
            "largest_focus_notional_multiple",
            "focus_notional",
            "focus_notional_share",
            "signed_focus_notional",
            "directional_pressure",
            "focus_activity_score",
            "block_notional_threshold",
            "block_size_threshold",
            "block_threshold_method",
            "trade_count_anomaly_ratio",
            "notional_anomaly_ratio",
            "volume_anomaly_ratio",
            "activity_anomaly_z_score",
            "activity_anomaly_mad_score",
            "activity_anomaly_band",
            *FEATURE_COLUMNS,
            "market_flow_trend_participation",
        ]
    )
