from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import pandas as pd
import polars as pl
from market_flow.features import MarketFlowFeatureConfig, market_flow_feature_frame
from pit.exceptions import DataNotAvailableAt
from signals._common import float_or_none, score_dict
from signals.chart_patterns import ChartPatternSummary, chart_pattern_summary
from technical_analysis.indicator_engine import (
    ExternalIndicatorSnapshot,
    external_indicator_snapshot,
)

DEFAULT_LOOKBACK_DAYS = 260
TRADE_LOOKBACK_DAYS = 3
MIN_OBSERVATIONS = 40
MIN_PAIR_OBSERVATIONS = 2
BENCHMARK_RETURN_DAYS = 20
SHORT_WINDOW_DAYS = 20
MEDIUM_WINDOW_DAYS = 50
LONG_WINDOW_DAYS = 200
RSI_WINDOW_DAYS = 14
RSI_NEUTRAL = 50.0
CANDLE_LOOKBACK_DAYS = 5
VOLUME_BASELINE_DAYS = 21
RECENT_ACCUMULATION_DAYS = 10
ATR_WINDOW_DAYS = 14
SETUP_VOLUME_CONFIRMATION_MIN = 0.2
SETUP_TREND_CONTINUATION_MIN = 0.35
SETUP_MOMENTUM_CONFIRMATION_MIN = 0.15
SETUP_PULLBACK_TREND_MIN = 0.25
SETUP_PULLBACK_DISTANCE_MAX = 0.03
SETUP_DISTRIBUTION_TREND_MAX = -0.3
SETUP_DISTRIBUTION_VOLUME_MAX = -0.2
SETUP_OVEREXTENDED_RISK_MAX = -0.75
OVEREXTENDED_PRICE_EXTENSION = 0.12
OVEREXTENDED_ATR_PCT = 0.08
ORDERLY_EXTENSION_MAX = 0.06
ORDERLY_ATR_PCT_MAX = 0.045
BROKEN_SUPPORT_EXTENSION = -0.08
SUMMARY_DIRECTION_THRESHOLD = 0.2
REASON_DIRECTION_THRESHOLD = 0.05
MIN_INVALIDATION_BUFFER = 0.015
BENCHMARK_TICKERS = ("SPY", "QQQ")


@dataclass(frozen=True)
class TechnicalAnalysisContext:
    ticker: str
    score: float
    summary: str
    reason_codes: list[str]


@dataclass(frozen=True)
class CandleRegime:
    latest_color: str
    blue_count_5d: int
    pink_count_5d: int
    flip: str
    score: float


class TechnicalAnalysisLoader(Protocol):
    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame: ...

    def stock_trades(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame: ...


def technical_analysis_score(
    as_of: date,
    universe: set[str],
    loader: TechnicalAnalysisLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return a PIT-safe technical setup score using OHLCV and optional trade prints."""
    return score_dict(
        technical_analysis_frame(as_of, universe, loader, lookback_days),
        "technical_analysis_score",
    )


def technical_analysis_contexts(
    as_of: date,
    universe: Iterable[str],
    loader: TechnicalAnalysisLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[TechnicalAnalysisContext]:
    frame = technical_analysis_frame(as_of, universe, loader, lookback_days)
    contexts: list[TechnicalAnalysisContext] = []
    for _, row in frame.iterrows():
        score = float_or_none(row["technical_analysis_score"]) or 0.0
        setup_label = str(row["setup_label"])
        contexts.append(
            TechnicalAnalysisContext(
                ticker=str(row["ticker"]),
                score=score,
                summary=str(row["summary"]),
                reason_codes=[
                    *_reason_codes(setup_label, score),
                    *_string_list(row.get("pattern_reason_codes")),
                    *_string_list(row.get("external_indicator_reason_codes")),
                ],
            )
        )
    return contexts


def technical_analysis_frame(
    as_of: date,
    universe: Iterable[str],
    loader: TechnicalAnalysisLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    if lookback_days < MIN_OBSERVATIONS:
        raise ValueError(f"lookback_days must be >= {MIN_OBSERVATIONS}")
    tickers = sorted({item.upper() for item in universe})
    if not tickers:
        return _empty_frame()
    try:
        raw = loader.prices([*tickers, *BENCHMARK_TICKERS], as_of, lookback_days)
    except DataNotAvailableAt:
        return _empty_frame()
    if raw.is_empty():
        return _empty_frame()
    frame = raw.to_pandas()
    frame["ticker"] = frame["ticker"].astype(str).str.upper()
    price_column = _price_column(frame)
    benchmark_return = _benchmark_return(frame, price_column)
    trade_pressure = _trade_pressure_by_ticker(loader, tickers, as_of)
    rows = [
        row
        for ticker, group in frame[frame["ticker"].isin(tickers)].groupby("ticker", sort=True)
        if (
            row := _factor_row(
                str(ticker),
                group,
                price_column,
                benchmark_return,
                trade_pressure.get(str(ticker), 0.0),
            )
        )
        is not None
    ]
    if not rows:
        return _empty_frame()
    return pd.DataFrame(rows).sort_values(
        ["technical_analysis_score", "ticker"],
        ascending=[False, True],
    ).reset_index(drop=True)


def _factor_row(
    ticker: str,
    group: pd.DataFrame,
    price_column: str,
    benchmark_return: float,
    trade_pressure: float,
) -> dict[str, object] | None:
    ordered = group.sort_values("date") if "date" in group.columns else group.copy()
    ordered = ordered.reset_index(drop=True)
    if len(ordered) < MIN_OBSERVATIONS:
        return None
    close = pd.to_numeric(ordered[price_column], errors="coerce").reset_index(drop=True)
    valid_close = close.notna()
    ordered = ordered.loc[valid_close].reset_index(drop=True)
    close = close.loc[valid_close].reset_index(drop=True)
    if len(close) < MIN_OBSERVATIONS:
        return None
    open_price = _series_or_fallback(ordered, "open", close)
    high = _series_or_fallback(ordered, "high", close)
    low = _series_or_fallback(ordered, "low", close)
    volume = _series_or_fallback(
        ordered,
        "volume",
        pd.Series([0.0 for _ in close], index=close.index),
    )
    latest_close = float(close.iloc[-1])
    previous_close = float(close.iloc[-2])
    sma20 = _sma(close, SHORT_WINDOW_DAYS)
    sma50 = _sma(close, MEDIUM_WINDOW_DAYS)
    sma200 = _sma(close, LONG_WINDOW_DAYS)
    ema20 = _ema(close, SHORT_WINDOW_DAYS)
    rsi14 = _rsi(close, RSI_WINDOW_DAYS)
    macd_hist = _macd_histogram(close)
    atr_pct = _atr_pct(high, low, close)
    trend_score = _trend_score(close, sma20, sma50, sma200)
    momentum_score = _momentum_score(close, rsi14, macd_hist)
    volume_score = _volume_score(close, volume)
    relative_strength_score = _relative_strength_score(close, benchmark_return)
    volatility_risk_score = _volatility_risk_score(latest_close, sma20, atr_pct)
    candle = _candle_regime(open_price, close, ema20, rsi14, macd_hist, volume)
    patterns = chart_pattern_summary(close=close, high=high, low=low, volume=volume)
    external = external_indicator_snapshot(
        close=close,
        high=high,
        low=low,
        volume=volume,
    )
    setup_label = _setup_label(
        close=close,
        trend_score=trend_score,
        momentum_score=momentum_score,
        volume_score=volume_score,
        volatility_risk_score=volatility_risk_score,
        candle_score=candle.score,
    )
    score = _bounded(
        0.20 * trend_score
        + 0.16 * momentum_score
        + 0.12 * volume_score
        + 0.12 * relative_strength_score
        + 0.09 * candle.score
        + 0.09 * trade_pressure
        + 0.07 * patterns.score
        + 0.05 * volatility_risk_score
        + 0.10 * external.score
    )
    support = _support_level(latest_close, sma20, sma50)
    resistance = _rolling_high(close, SHORT_WINDOW_DAYS)
    latest_return = 0.0 if previous_close <= 0.0 else latest_close / previous_close - 1.0
    return {
        "ticker": ticker,
        "latest_close": latest_close,
        "latest_return": latest_return,
        "sma20": _latest_positive(sma20),
        "sma50": _latest_positive(sma50),
        "sma200": _latest_positive(sma200),
        "rsi14": _latest_positive(rsi14),
        "atr_pct": atr_pct,
        "trend_score": trend_score,
        "momentum_score": momentum_score,
        "volume_confirmation_score": volume_score,
        "relative_strength_score": relative_strength_score,
        "volatility_risk_score": volatility_risk_score,
        "trade_pressure_score": trade_pressure,
        "chart_pattern_score": patterns.score,
        "chart_pattern_name": _pattern_field(patterns, "name"),
        "chart_pattern_direction": _pattern_field(patterns, "direction"),
        "chart_pattern_confidence": _pattern_confidence(patterns),
        "chart_pattern_status": _pattern_field(patterns, "status"),
        "chart_pattern_breakout_level": _pattern_level(patterns, "breakout_level"),
        "chart_pattern_invalidation_level": _pattern_level(patterns, "invalidation_level"),
        "chart_pattern_target_level": _pattern_level(patterns, "target_level"),
        "pattern_reason_codes": patterns.reason_codes,
        "external_indicator_status": external.status,
        "external_indicator_score": external.score,
        "external_indicator_trend_score": external.trend_score,
        "external_indicator_momentum_score": external.momentum_score,
        "external_indicator_channel_score": external.channel_score,
        "external_indicator_volume_score": external.volume_score,
        "external_indicator_reason_codes": external.reason_codes,
        **_external_indicator_values(external),
        "latest_candle_color": candle.latest_color,
        "blue_candle_count_5d": candle.blue_count_5d,
        "pink_candle_count_5d": candle.pink_count_5d,
        "candle_flip": candle.flip,
        "setup_label": setup_label,
        "support_level": support,
        "resistance_level": resistance,
        "invalidation_level": support * (1.0 - max(atr_pct, MIN_INVALIDATION_BUFFER)),
        "technical_analysis_score": score,
        "summary": _summary(
            ticker=ticker,
            setup_label=setup_label,
            score=score,
            trend_score=trend_score,
            momentum_score=momentum_score,
            volume_score=volume_score,
            relative_strength_score=relative_strength_score,
            trade_pressure=trade_pressure,
            patterns=patterns,
            external=external,
            candle=candle,
            support=support,
            resistance=resistance,
            atr_pct=atr_pct,
        ),
    }


def _trade_pressure_by_ticker(
    loader: TechnicalAnalysisLoader,
    tickers: list[str],
    as_of: date,
) -> dict[str, float]:
    frame = market_flow_feature_frame(
        as_of,
        tickers,
        loader,
        MarketFlowFeatureConfig(lookback_days=TRADE_LOOKBACK_DAYS),
    )
    if frame.empty:
        return {}
    return {
        str(row["ticker"]): _bounded(float(row["net_notional_pressure"]))
        for row in frame[["ticker", "net_notional_pressure"]].to_dict("records")
    }


def _trend_score(close: pd.Series, sma20: pd.Series, sma50: pd.Series, sma200: pd.Series) -> float:
    latest = float(close.iloc[-1])
    score = 0.0
    score += 0.25 if latest > _latest_positive(sma20) else -0.25
    score += 0.25 if latest > _latest_positive(sma50) else -0.25
    if _latest_positive(sma200) > 0.0:
        score += 0.20 if latest > _latest_positive(sma200) else -0.20
    score += 0.15 if _slope(sma20) > 0.0 else -0.15
    score += 0.15 if _slope(sma50) > 0.0 else -0.15
    return _bounded(score)


def _momentum_score(close: pd.Series, rsi14: pd.Series, macd_hist: pd.Series) -> float:
    rsi_value = _latest_positive(rsi14, fallback=RSI_NEUTRAL)
    rsi_component = _bounded((rsi_value - RSI_NEUTRAL) / 25.0)
    macd_component = 0.0
    if len(macd_hist.dropna()) >= MIN_PAIR_OBSERVATIONS:
        latest = float(macd_hist.iloc[-1])
        previous = float(macd_hist.iloc[-2])
        macd_component = _bounded((latest - previous) / max(abs(previous), 0.01))
    roc20 = _period_return(close, SHORT_WINDOW_DAYS)
    return _bounded(0.45 * rsi_component + 0.30 * macd_component + 0.25 * _bounded(roc20 * 8.0))


def _volume_score(close: pd.Series, volume: pd.Series) -> float:
    latest_volume = _latest_positive(volume)
    baseline = _median_positive(volume.tail(VOLUME_BASELINE_DAYS).iloc[:-1])
    if latest_volume <= 0.0 or baseline <= 0.0:
        return 0.0
    latest_return = float(close.iloc[-1]) / float(close.iloc[-2]) - 1.0
    latest_pressure = _sign(latest_return) * min(1.0, max(latest_volume / baseline - 1.0, 0.0))
    recent = close.tail(RECENT_ACCUMULATION_DAYS).pct_change().fillna(0.0)
    recent_volume = volume.tail(RECENT_ACCUMULATION_DAYS)
    accumulation = _sign(float((recent * recent_volume).sum()))
    return _bounded(0.70 * latest_pressure + 0.30 * accumulation)


def _relative_strength_score(close: pd.Series, benchmark_return: float) -> float:
    if benchmark_return == 0.0:
        return 0.0
    excess = _period_return(close, BENCHMARK_RETURN_DAYS) - benchmark_return
    return _bounded(excess * 10.0)


def _volatility_risk_score(latest_close: float, sma20: pd.Series, atr_pct: float) -> float:
    extension = latest_close / _latest_positive(sma20, fallback=latest_close) - 1.0
    if extension > OVEREXTENDED_PRICE_EXTENSION or atr_pct > OVEREXTENDED_ATR_PCT:
        return -1.0
    if 0.0 <= extension <= ORDERLY_EXTENSION_MAX and atr_pct <= ORDERLY_ATR_PCT_MAX:
        return 0.5
    if extension < BROKEN_SUPPORT_EXTENSION:
        return -0.5
    return 0.0


def _candle_regime(
    open_price: pd.Series,
    close: pd.Series,
    ema20: pd.Series,
    rsi14: pd.Series,
    macd_hist: pd.Series,
    volume: pd.Series,
) -> CandleRegime:
    rows: list[str] = []
    baseline_volume = _median_positive(volume.tail(VOLUME_BASELINE_DAYS).iloc[:-1])
    for index in range(max(0, len(close) - CANDLE_LOOKBACK_DAYS), len(close)):
        rsi_value = float_or_none(rsi14.iloc[index]) or RSI_NEUTRAL
        hist = float_or_none(macd_hist.iloc[index]) or 0.0
        previous_hist = float_or_none(macd_hist.iloc[index - 1]) or 0.0 if index > 0 else hist
        closes_up = float(close.iloc[index]) >= float(open_price.iloc[index])
        above_trend = float(close.iloc[index]) >= float(ema20.iloc[index])
        volume_ok = baseline_volume <= 0.0 or float(volume.iloc[index]) >= baseline_volume * 0.8
        if (
            closes_up
            and above_trend
            and rsi_value >= RSI_NEUTRAL
            and hist >= previous_hist
            and volume_ok
        ):
            rows.append("blue")
        elif (not closes_up or not above_trend) and (
            rsi_value < RSI_NEUTRAL or hist < previous_hist
        ):
            rows.append("pink")
        else:
            rows.append("neutral")
    latest = rows[-1] if rows else "neutral"
    previous = rows[-2] if len(rows) >= MIN_PAIR_OBSERVATIONS else latest
    score = rows.count("blue") / max(len(rows), 1) - rows.count("pink") / max(len(rows), 1)
    return CandleRegime(
        latest_color=latest,
        blue_count_5d=rows.count("blue"),
        pink_count_5d=rows.count("pink"),
        flip=f"{previous}_to_{latest}" if latest != previous else "none",
        score=_bounded(score),
    )


def _setup_label(
    *,
    close: pd.Series,
    trend_score: float,
    momentum_score: float,
    volume_score: float,
    volatility_risk_score: float,
    candle_score: float,
) -> str:
    latest = float(close.iloc[-1])
    prior_high = _rolling_high(close.iloc[:-1], SHORT_WINDOW_DAYS)
    previous = float(close.iloc[-2])
    sma20 = float(_sma(close, SHORT_WINDOW_DAYS).iloc[-1])
    distance_from_sma20 = 0.0 if sma20 <= 0.0 else abs(latest / sma20 - 1.0)
    setup_label = "range_bound"
    if latest > prior_high and volume_score > SETUP_VOLUME_CONFIRMATION_MIN:
        setup_label = "breakout"
    elif previous > prior_high and latest < prior_high and volume_score < 0.0:
        setup_label = "failed_breakout"
    elif (
        trend_score > SETUP_TREND_CONTINUATION_MIN
        and momentum_score > SETUP_MOMENTUM_CONFIRMATION_MIN
        and candle_score >= 0.0
    ):
        setup_label = "trend_continuation"
    elif (
        trend_score > SETUP_PULLBACK_TREND_MIN
        and distance_from_sma20 <= SETUP_PULLBACK_DISTANCE_MAX
    ):
        setup_label = "pullback_to_support"
    elif (
        trend_score < SETUP_DISTRIBUTION_TREND_MAX
        and volume_score < SETUP_DISTRIBUTION_VOLUME_MAX
    ):
        setup_label = "distribution"
    elif (
        volatility_risk_score < SETUP_OVEREXTENDED_RISK_MAX
        and momentum_score > SETUP_VOLUME_CONFIRMATION_MIN
    ):
        setup_label = "overextended"
    return setup_label


def _summary(
    *,
    ticker: str,
    setup_label: str,
    score: float,
    trend_score: float,
    momentum_score: float,
    volume_score: float,
    relative_strength_score: float,
    trade_pressure: float,
    patterns: ChartPatternSummary,
    external: ExternalIndicatorSnapshot,
    candle: CandleRegime,
    support: float,
    resistance: float,
    atr_pct: float,
) -> str:
    bias = (
        "supportive"
        if score > SUMMARY_DIRECTION_THRESHOLD
        else "risky"
        if score < -SUMMARY_DIRECTION_THRESHOLD
        else "mixed"
    )
    return (
        f"Technical analysis: {ticker} has a {setup_label.replace('_', ' ')} setup "
        f"with {bias} chart evidence. Trend {trend_score:+.2f}, momentum "
        f"{momentum_score:+.2f}, volume {volume_score:+.2f}, relative strength "
        f"{relative_strength_score:+.2f}, Massive trade pressure {trade_pressure:+.2f}. "
        f"Latest agency candle is {candle.latest_color}; blue/pink last 5 sessions "
        f"{candle.blue_count_5d}/{candle.pink_count_5d} with flip {candle.flip}. "
        f"{patterns.summary_fragment} "
        f"{external.summary_fragment} "
        f"Support/invalidation zone starts near {support:.2f}; resistance near "
        f"{resistance:.2f}; ATR risk {atr_pct:.1%}."
    )


def _reason_codes(setup_label: str, score: float) -> list[str]:
    direction = (
        "bullish"
        if score > REASON_DIRECTION_THRESHOLD
        else "bearish"
        if score < -REASON_DIRECTION_THRESHOLD
        else "neutral"
    )
    return [f"technical_analysis_{direction}", f"technical_setup_{setup_label}"]


def _pattern_field(patterns: ChartPatternSummary, field_name: str) -> str | None:
    if patterns.primary is None:
        return None
    return str(getattr(patterns.primary, field_name))


def _pattern_confidence(patterns: ChartPatternSummary) -> float | None:
    return None if patterns.primary is None else patterns.primary.confidence


def _pattern_level(patterns: ChartPatternSummary, field_name: str) -> float | None:
    if patterns.primary is None:
        return None
    value = getattr(patterns.primary, field_name)
    return float(value) if isinstance(value, int | float) else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _external_indicator_values(external: ExternalIndicatorSnapshot) -> dict[str, float | None]:
    return {
        f"external_{name}": value
        for name, value in external.values.items()
    }


def _benchmark_return(frame: pd.DataFrame, price_column: str) -> float:
    for ticker in BENCHMARK_TICKERS:
        group = frame[frame["ticker"] == ticker]
        if len(group) >= BENCHMARK_RETURN_DAYS:
            return _period_return(
                pd.to_numeric(group[price_column], errors="coerce").dropna(),
                BENCHMARK_RETURN_DAYS,
            )
    return 0.0


def _period_return(series: pd.Series, periods: int) -> float:
    values = series.dropna()
    if len(values) <= periods:
        return 0.0
    start = float(values.iloc[-periods - 1])
    end = float(values.iloc[-1])
    return 0.0 if start <= 0.0 else end / start - 1.0


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=min(window, MIN_OBSERVATIONS)).mean()


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0).rolling(window=window, min_periods=window).mean()
    loss = (-delta.clip(upper=0.0)).rolling(window=window, min_periods=window).mean()
    relative = gain / loss.replace(0.0, pd.NA)
    rsi = 100.0 - (100.0 / (1.0 + relative))
    rsi = rsi.mask((loss == 0.0) & (gain > 0.0), 100.0)
    rsi = rsi.mask((gain == 0.0) & (loss > 0.0), 0.0)
    return rsi.mask((gain == 0.0) & (loss == 0.0), RSI_NEUTRAL)


def _macd_histogram(close: pd.Series) -> pd.Series:
    macd = _ema(close, 12) - _ema(close, 26)
    signal = _ema(macd, 9)
    return macd - signal


def _atr_pct(high: pd.Series, low: pd.Series, close: pd.Series) -> float:
    previous_close = close.shift(1)
    true_range = pd.concat(
        [(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = float(
        true_range.rolling(window=ATR_WINDOW_DAYS, min_periods=MIN_PAIR_OBSERVATIONS)
        .mean()
        .iloc[-1]
    )
    latest = float(close.iloc[-1])
    return 0.0 if latest <= 0.0 else atr / latest


def _series_or_fallback(frame: pd.DataFrame, column: str, fallback: pd.Series) -> pd.Series:
    if column not in frame.columns:
        return fallback.reset_index(drop=True)
    values = pd.to_numeric(frame[column], errors="coerce").reset_index(drop=True)
    return values.fillna(fallback.reset_index(drop=True))


def _numeric(frame: pd.DataFrame, column: str, default: float) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([default for _ in range(len(frame))], index=frame.index)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def _price_column(frame: pd.DataFrame) -> str:
    for column in ("adj_close", "close"):
        if column in frame.columns:
            return column
    raise ValueError("price frame must include adj_close or close")


def _latest_positive(series: pd.Series, fallback: float = 0.0) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    values = values[values > 0.0]
    return fallback if values.empty else float(values.iloc[-1])


def _median_positive(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    values = values[values > 0.0]
    return 0.0 if values.empty else float(values.median())


def _rolling_high(series: pd.Series, window: int) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna().tail(window)
    return 0.0 if values.empty else float(values.max())


def _slope(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) < MIN_PAIR_OBSERVATIONS:
        return 0.0
    return float(values.iloc[-1] - values.iloc[-2])


def _support_level(latest_close: float, sma20: pd.Series, sma50: pd.Series) -> float:
    candidates = [
        value
        for value in (_latest_positive(sma20), _latest_positive(sma50), latest_close)
        if value > 0.0
    ]
    return min(candidates) if candidates else latest_close


def _sign(value: float) -> float:
    if value > 0.0:
        return 1.0
    if value < 0.0:
        return -1.0
    return 0.0


def _bounded(value: float) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        return 0.0
    return max(-1.0, min(1.0, parsed))


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "latest_close",
            "latest_return",
            "sma20",
            "sma50",
            "sma200",
            "rsi14",
            "atr_pct",
            "trend_score",
            "momentum_score",
            "volume_confirmation_score",
            "relative_strength_score",
            "volatility_risk_score",
            "trade_pressure_score",
            "chart_pattern_score",
            "chart_pattern_name",
            "chart_pattern_direction",
            "chart_pattern_confidence",
            "chart_pattern_status",
            "chart_pattern_breakout_level",
            "chart_pattern_invalidation_level",
            "chart_pattern_target_level",
            "pattern_reason_codes",
            "external_indicator_status",
            "external_indicator_score",
            "external_indicator_trend_score",
            "external_indicator_momentum_score",
            "external_indicator_channel_score",
            "external_indicator_volume_score",
            "external_indicator_reason_codes",
            "external_adx14",
            "external_aroon25",
            "external_cci20",
            "external_bollinger_percent_b",
            "external_bollinger_width",
            "external_keltner_percent_b",
            "external_donchian_percent_b",
            "external_cmf20",
            "external_mfi14",
            "external_obv_slope_20",
            "external_vwap_distance",
            "external_stochrsi14",
            "external_williams_r14",
            "latest_candle_color",
            "blue_candle_count_5d",
            "pink_candle_count_5d",
            "candle_flip",
            "setup_label",
            "support_level",
            "resistance_level",
            "invalidation_level",
            "technical_analysis_score",
            "summary",
        ]
    )
