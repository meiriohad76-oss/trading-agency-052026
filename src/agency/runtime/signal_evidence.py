from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from inspect import signature
from typing import Any, cast

import pandas as pd
import polars as pl
from market_flow.features import market_flow_feature_frame
from pit.exceptions import DataNotAvailableAt
from pit.loader import PITLoader
from signals.abnormal_volume import abnormal_volume_frame
from signals.fundamentals import fundamental_factor_frame
from signals.insider import insider_factor_frame
from signals.institutional import institutional_factor_frame
from signals.news import news_factor_frame
from signals.options_anomaly import options_anomaly_frame
from signals.options_flow import options_flow_frame
from signals.technical_analysis import technical_analysis_frame

from agency.paths import REPO_ROOT

DEFAULT_PARQUET_ROOT = REPO_ROOT / "research" / "data" / "parquet"
DEFAULT_MANIFEST_ROOT = REPO_ROOT / "research" / "data" / "manifests"
LOGGER = logging.getLogger(__name__)

MARKET_FLOW_LANES = frozenset(
    {
        "buy_sell_pressure",
        "block_trade_pressure",
        "unusual_trade_activity",
        "pre_market_unusual_activity",
        "market_flow_trend",
    }
)
UNUSUAL_TRADE_LANES = frozenset({"unusual_trade_activity", "pre_market_unusual_activity"})
MONEY_BILLION = 1_000_000_000
MONEY_MILLION = 1_000_000
MONEY_THOUSAND = 1_000
SCORE_TONE_THRESHOLD = 0.05

LANE_EXPLANATIONS = {
    "abnormal_volume": (
        "Compares the latest daily volume with the recent median baseline, then gives "
        "the move a bullish or bearish sign from the latest price return."
    ),
    "technical_analysis": (
        "Blends trend, momentum, volume confirmation, relative strength, candle color, "
        "chart patterns, trade pressure, and volatility risk."
    ),
    "fundamentals": (
        "Ranks net margin, free-cash-flow margin, and balance-sheet leverage against "
        "the current universe."
    ),
    "insider": (
        "Aggregates recent Form 4 purchase and sale transactions into net insider "
        "transaction value."
    ),
    "institutional": (
        "Uses 13F holder count, total shares held, and quarterly share change to detect "
        "institutional accumulation or distribution."
    ),
    "news": (
        "Counts ticker-tagged headlines and simple bullish/bearish terms across the "
        "recent news window."
    ),
    "buy_sell_pressure": (
        "Uses confirmed delayed trade prints to estimate whether signed notional and "
        "volume pressure lean buy-side or sell-side."
    ),
    "block_trade_pressure": (
        "Focuses on block and off-exchange prints, measuring directional notional "
        "pressure and the size of focused activity."
    ),
    "unusual_trade_activity": (
        "Compares latest trade count, volume, and notional activity with recent daily "
        "baselines, then applies the signed notional direction."
    ),
    "pre_market_unusual_activity": (
        "Checks whether pre-market volume or notional is unusually large and whether "
        "that activity is buy- or sell-pressured."
    ),
    "market_flow_trend": (
        "Compares latest signed notional pressure with prior pressure to detect whether "
        "market-flow trend is improving or deteriorating."
    ),
    "activity_alerts": (
        "Uses upstream activity-alert rows that already compared volume, notional, or "
        "trade count with a ticker baseline; this dashboard preserves the stored alert "
        "summary and provenance."
    ),
    "options_flow": (
        "Uses option-chain context when available: call-side versus put-side premium, "
        "volume, and open-interest balance. This inspector shows the persisted runtime "
        "summary, direction, source ID, confidence, and timestamp for the option-chain "
        "row so the user can audit what was counted."
    ),
    "options_anomaly": (
        "Uses option-chain anomaly context when available: unusual call-side or put-side "
        "premium, volume, or open-interest change versus baseline. This inspector shows "
        "the persisted anomaly summary, direction, source ID, confidence, and timestamp "
        "for audit."
    ),
    "prepost": (
        "Uses extended-hours activity context: pre/post-market volume or notional plus "
        "signed pressure. The panel keeps the stored extended-hours summary, direction, "
        "timestamp, and source ID as audit evidence."
    ),
    "sector_momentum": (
        "Compares the stock's sector or benchmark group with recent return baselines; "
        "the stored row explains whether sector context supports or weakens the ticker."
    ),
    "subscription_thesis": (
        "Uses analyzed subscription-email/article thesis events mapped to this ticker; "
        "the stored summary should name the article thesis, direction, and confidence."
    ),
}


def enrich_signal_rows_with_evidence(
    rows: Sequence[Mapping[str, object]],
    *,
    loader: Any | None = None,
) -> list[dict[str, object]]:
    if not rows:
        return []
    active_loader = _CachedPriceWindowLoader(
        loader
        or PITLoader(
            parquet_root=DEFAULT_PARQUET_ROOT,
            manifest_root=DEFAULT_MANIFEST_ROOT,
        )
    )
    as_of = _dashboard_as_of(rows)
    tickers = sorted({str(row["ticker"]).upper() for row in rows})
    frames = _detail_frames(active_loader, as_of, tickers, rows)
    enriched: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        next_row = dict(row)
        next_row["inspect_id"] = (
            f"signal-inspect-{index}-{_slug(str(row['ticker']))}-{_slug(str(row['lane_key']))}"
        )
        next_row["sort_direction"] = _direction_sort_value(str(row["direction"]))
        next_row.update(_evidence_for_row(next_row, frames, as_of))
        _apply_concrete_inspection_text(next_row)
        enriched.append(next_row)
    return enriched


def _detail_frames(
    loader: Any,
    as_of: date,
    tickers: list[str],
    rows: Sequence[Mapping[str, object]],
) -> dict[str, pd.DataFrame]:
    lanes = {str(row["lane_key"]) for row in rows}
    frames: dict[str, pd.DataFrame] = {}
    if "technical_analysis" in lanes:
        frames["technical_analysis"] = _safe_frame(technical_analysis_frame, as_of, tickers, loader)
    if "abnormal_volume" in lanes:
        frames["abnormal_volume"] = _safe_frame(abnormal_volume_frame, as_of, tickers, loader)
    if "fundamentals" in lanes:
        frames["fundamentals"] = _safe_frame(fundamental_factor_frame, as_of, tickers, loader)
    if "insider" in lanes:
        frames["insider"] = _safe_frame(insider_factor_frame, as_of, tickers, loader)
    if "institutional" in lanes:
        frames["institutional"] = _safe_frame(institutional_factor_frame, as_of, tickers, loader)
    if "news" in lanes:
        frames["news"] = _safe_frame(news_factor_frame, as_of, tickers, loader)
    if "options_flow" in lanes:
        frames["options_flow"] = _safe_frame(options_flow_frame, as_of, tickers, loader)
    if "options_anomaly" in lanes:
        frames["options_anomaly"] = _safe_frame(options_anomaly_frame, as_of, tickers, loader)
    if lanes & MARKET_FLOW_LANES:
        frames["market_flow"] = _safe_frame(
            market_flow_feature_frame,
            as_of,
            tickers,
            _market_flow_loader_for_rows(loader, as_of, rows),
        )
    return frames


class _CachedPriceWindowLoader:
    def __init__(self, loader: Any) -> None:
        self._loader = loader
        self._price_windows: list[
            tuple[date, int, tuple[str, ...], pd.Timestamp, pl.DataFrame]
        ] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._loader, name)

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame:
        normalized = tuple(sorted({ticker.upper() for ticker in tickers}))
        start = as_of - timedelta(days=lookback_days - 1)
        cached = self._cached_price_window(normalized, as_of, lookback_days, start)
        if cached is not None:
            return cached
        frame = self._loader.prices(list(normalized), as_of, lookback_days)
        self._price_windows.append((as_of, lookback_days, normalized, pd.Timestamp(start), frame))
        return frame

    def _cached_price_window(
        self,
        tickers: tuple[str, ...],
        as_of: date,
        lookback_days: int,
        start: date,
    ) -> pl.DataFrame | None:
        requested = set(tickers)
        for cached_as_of, cached_lookback, cached_tickers, cached_start, frame in reversed(
            self._price_windows
        ):
            if cached_as_of != as_of or cached_lookback < lookback_days:
                continue
            if not requested.issubset(set(cached_tickers)):
                continue
            if "date" not in frame.columns or "ticker" not in frame.columns:
                continue
            if cached_start > pd.Timestamp(start):
                continue
            try:
                return frame.filter(
                    pl.col("ticker").cast(pl.Utf8).str.to_uppercase().is_in(list(tickers)),
                    pl.col("date") >= start,
                    pl.col("date") <= as_of,
                )
            except Exception:
                return None
        return None


class _KnowledgeCutoffMarketFlowLoader:
    def __init__(self, loader: Any, knowledge_as_of: date) -> None:
        self._loader = loader
        self._knowledge_as_of = knowledge_as_of

    def __getattr__(self, name: str) -> Any:
        return getattr(self._loader, name)

    def stock_trade_activity_frames(
        self,
        tickers: list[str],
        as_of: date,
        lookback_days: int,
        *,
        allow_partial_coverage: bool = False,
    ) -> tuple[pl.DataFrame, pl.DataFrame]:
        complete_tickers = self._complete_tickers(tickers, as_of, lookback_days)
        if not complete_tickers:
            raise DataNotAvailableAt(
                "stock_trades",
                as_of,
                "no requested ticker has usable stock-trade coverage for dashboard evidence",
            )
        method = getattr(self._loader, "stock_trade_activity_frames_for_trade_window", None)
        if callable(method) and self._knowledge_as_of > as_of:
            return method(
                complete_tickers,
                trade_end=as_of,
                knowledge_as_of=self._knowledge_as_of,
                lookback_days=lookback_days,
                **_optional_partial_coverage(method, True),
            )
        method = self._loader.stock_trade_activity_frames
        return method(
            complete_tickers,
            as_of,
            lookback_days,
            **_optional_partial_coverage(method, allow_partial_coverage or True),
        )

    def _complete_tickers(self, tickers: list[str], as_of: date, lookback_days: int) -> list[str]:
        normalized = sorted({ticker.upper() for ticker in tickers})
        method = getattr(self._loader, "complete_stock_trade_tickers", None)
        if not callable(method):
            return normalized
        try:
            result = method(
                normalized,
                as_of,
                lookback_days,
                **_optional_partial_coverage(method, True),
            )
        except DataNotAvailableAt:
            return []
        return sorted({str(ticker).upper() for ticker in result})


def _market_flow_loader_for_rows(
    loader: Any,
    as_of: date,
    rows: Sequence[Mapping[str, object]],
) -> Any:
    knowledge_as_of = _market_flow_knowledge_as_of(rows)
    if knowledge_as_of is None:
        return loader
    has_activity_method = callable(getattr(loader, "stock_trade_activity_frames", None))
    has_window_method = callable(getattr(loader, "stock_trade_activity_frames_for_trade_window", None))
    if not has_activity_method and not (has_window_method and knowledge_as_of > as_of):
        return loader
    return _KnowledgeCutoffMarketFlowLoader(loader, knowledge_as_of)


def _optional_partial_coverage(method: Any, value: bool) -> dict[str, bool]:
    try:
        parameters = signature(method).parameters
    except (TypeError, ValueError):
        return {}
    if "allow_partial_coverage" not in parameters:
        return {}
    return {"allow_partial_coverage": value}


def _evidence_for_row(
    row: Mapping[str, object],
    frames: Mapping[str, pd.DataFrame],
    as_of: date,
) -> dict[str, object]:
    lane = str(row["lane_key"])
    ticker = str(row["ticker"]).upper()
    detail_frame = frames.get(lane)
    detail_row = _frame_row(detail_frame, ticker)
    if lane in MARKET_FLOW_LANES:
        detail_frame = frames.get("market_flow")
        detail_row = _frame_row(detail_frame, ticker)
    if detail_row is None:
        return _fallback_evidence(row, as_of, reconstruction_error=_frame_error(detail_frame))
    if lane in MARKET_FLOW_LANES:
        return _market_flow_evidence(row, detail_row, as_of)
    builders = {
        "abnormal_volume": _abnormal_volume_evidence,
        "technical_analysis": _technical_analysis_evidence,
        "fundamentals": _fundamentals_evidence,
        "insider": _insider_evidence,
        "institutional": _institutional_evidence,
        "news": _news_evidence,
        "options_flow": _options_flow_evidence,
        "options_anomaly": _options_anomaly_evidence,
        "sec_filing_analysis": _sec_filing_evidence,
    }
    builder = builders.get(lane, _fallback_evidence_from_detail)
    return builder(row, detail_row, as_of)


def _abnormal_volume_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    ratio = _float(detail.get("volume_ratio"))
    latest_return = _float(detail.get("latest_return"))
    baseline_count = _float(detail.get("baseline_observation_count"))
    lookback_days = _float(detail.get("lookback_days"))
    score = _float(row.get("score_value")) or 0.0
    direction = "bullish" if score > 0.0 else "bearish"
    headline = (
        f"{row['ticker']} triggered abnormal volume because latest volume was "
        f"{_ratio_label(ratio)} the median of {_bar_count(baseline_count)} and "
        f"{_price_change_phrase(latest_return)} on the same daily bar."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            f"The signal is {direction}: {_volume_price_meaning(latest_return)} "
            f"Baseline volume is a median, not a simple average, from {_bar_count(baseline_count)} "
            f"returned by the {_day_count(lookback_days)} price lookback, excluding the trigger bar. "
            "The displayed score is a cross-sectional z-score versus the current universe."
        ),
        cards=[
            _card(
                "Latest volume",
                _integer(detail.get("latest_volume")),
                "Actual volume on the trigger bar.",
            ),
            _card(
                "Baseline volume",
                _integer(detail.get("baseline_volume")),
                (
                    f"Median volume across {_bar_count(baseline_count)} returned by the "
                    f"{_day_count(lookback_days)} price lookback; trigger bar excluded."
                ),
            ),
            _card(
                "Baseline window",
                _short_bar_count(baseline_count),
                (
                    f"Baseline uses the median, not a simple average, of prior daily bars in the "
                    f"{_day_count(lookback_days)} price lookback."
                ),
            ),
            _card(
                "Volume ratio",
                _ratio_label(ratio),
                "Latest volume divided by baseline volume.",
                _tone(ratio, 1.5),
            ),
            _card(
                "Latest return",
                _pct(latest_return),
                (
                    f"{_price_change_phrase(latest_return).capitalize()} on the same daily bar "
                    f"as the abnormal volume; {_volume_price_meaning(latest_return)}"
                ),
                _return_tone(latest_return),
            ),
            _card(
                "Signed pressure",
                _number(detail.get("signed_volume_pressure")),
                "Volume shock signed by price direction.",
            ),
            _card(
                "Abnormal score",
                _number(detail.get("abnormal_volume_score")),
                "Universe-normalized abnormal-volume score.",
            ),
        ],
    )


def _technical_analysis_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    setup = _text(detail.get("setup_label"), "unknown setup").replace("_", " ")
    pattern = _text(detail.get("chart_pattern_name"), "none")
    driver_mix = _technical_driver_mix_detail(detail)
    headline = (
        f"{row['ticker']} technical setup is {setup}; latest close is "
        f"{_money(detail.get('latest_close'))}, RSI is {_number(detail.get('rsi14'))}, "
        f"trend contribution {_number(detail.get('trend_score'))}, momentum "
        f"{_number(detail.get('momentum_score'))}, and model score "
        f"{_number(detail.get('technical_analysis_score'))}."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            f"The score blends concrete technical drivers: {driver_mix} "
            f"Latest close versus SMA stack is {_price_vs_sma_phrase(detail)}. "
            "Positive values help bullish review; negative values add caution."
        ),
        cards=[
            _card("Setup", setup.title(), "Primary chart setup classification."),
            _card(
                "SMA levels",
                (
                    f"{_money(detail.get('sma20'))} / {_money(detail.get('sma50'))} / "
                    f"{_money(detail.get('sma200'))}"
                ),
                (
                    "SMA20/SMA50/SMA200 trend stack. Close above rising averages is "
                    "bullish; close below them is caution."
                ),
                _score_tone(detail.get("trend_score")),
            ),
            _card(
                "Price vs SMA stack",
                _price_vs_sma_value(detail),
                _price_vs_sma_detail(detail),
                _score_tone(detail.get("trend_score")),
            ),
            _card(
                "Trend",
                _number(detail.get("trend_score")),
                _trend_score_detail(detail),
                _score_tone(detail.get("trend_score")),
            ),
            _card(
                "Momentum",
                _number(detail.get("momentum_score")),
                (
                    f"RSI14 {_plain_number(detail.get('rsi14'))}; momentum combines "
                    "RSI, MACD histogram change, and recent rate of change."
                ),
                _score_tone(detail.get("momentum_score")),
            ),
            _card(
                "Volume confirmation",
                _number(detail.get("volume_confirmation_score")),
                "Whether volume confirms the move.",
                _score_tone(detail.get("volume_confirmation_score")),
            ),
            _card(
                "Relative strength",
                _number(detail.get("relative_strength_score")),
                "Performance versus SPY/QQQ benchmark context.",
                _score_tone(detail.get("relative_strength_score")),
            ),
            _card(
                "Trade pressure",
                _number(detail.get("trade_pressure_score")),
                "Massive trade-print pressure used as a 9% technical-score input.",
                _score_tone(detail.get("trade_pressure_score")),
            ),
            _card(
                "Volatility risk",
                _number(detail.get("volatility_risk_score")),
                (
                    f"ATR {_pct(detail.get('atr_pct'))}; overextension or high ATR subtracts "
                    "from the setup because risk/reward is less favorable."
                ),
                _score_tone(detail.get("volatility_risk_score")),
            ),
            _card(
                "Driver mix",
                _number(detail.get("technical_analysis_score")),
                driver_mix,
                _score_tone(detail.get("technical_analysis_score")),
            ),
            _card(
                "Latest candle",
                _candle_label(detail),
                "Blue/pink candle regime over the latest five bars.",
            ),
            _card(
                "Support / resistance",
                f"{_money(detail.get('support_level'))} / {_money(detail.get('resistance_level'))}",
                "Nearby risk/reference levels.",
            ),
            _card("Pattern", pattern.title(), _pattern_detail(detail)),
            _card(
                "Methodology",
                "TA engine",
                _text(detail.get("ta_methodology"), "technical methodology was not reported"),
            ),
        ],
    )


def _fundamentals_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    period = _filing_period_label(detail)
    form = _text(detail.get("filing_form"), "form unknown")
    composite = _number(detail.get("composite_score"))
    forward_status = _forward_fundamentals_status_label(detail.get("forward_data_status"))
    bias = _fundamentals_bias(detail)
    driver_headline = _fundamentals_driver_headline(detail)
    trend_detail = _fundamentals_trend_detail(detail)
    headline = (
        f"{row['ticker']} fundamentals are {bias} (score {composite}) from {period} {form}: "
        f"{driver_headline}"
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            f"{_fundamentals_period_alignment_sentence(detail)} "
            f"{trend_detail} The agency treats positive margins and growth as bullish, negative "
            "cash generation as bearish, and high leverage as bearish because it leaves less "
            f"balance-sheet cushion. {forward_status}"
        ),
        cards=[
            _card(
                "Main drivers",
                bias,
                _fundamentals_driver_detail(detail),
                _score_tone(detail.get("composite_score")),
            ),
            _card(
                "YoY trend",
                _fundamentals_trend_value(detail),
                trend_detail,
                _fundamentals_trend_tone(detail),
            ),
            _card(
                "Gross margin",
                _pct(detail.get("gross_margin")),
                _ratio_metric_detail(
                    "Gross profit",
                    "revenue",
                    detail.get("gross_margin"),
                    positive_meaning=(
                        "bullish because higher gross margin leaves more revenue after direct costs"
                    ),
                    negative_meaning=(
                        "bearish because negative gross margin means direct costs exceed revenue"
                    ),
                ),
                _positive_tone(detail.get("gross_margin")),
            ),
            _card(
                "Operating margin",
                _pct(detail.get("operating_margin")),
                _ratio_metric_detail(
                    "Operating income",
                    "revenue",
                    detail.get("operating_margin"),
                    positive_meaning=(
                        "bullish because core operations are profitable before interest and taxes"
                    ),
                    negative_meaning=(
                        "bearish because core operations lost money before interest and taxes"
                    ),
                ),
                _positive_tone(detail.get("operating_margin")),
            ),
            _card(
                "Net margin",
                _pct(detail.get("net_margin")),
                _ratio_metric_detail(
                    "Net income",
                    "revenue",
                    detail.get("net_margin"),
                    positive_meaning=(
                        "bullish because net income is positive after all reported expenses"
                    ),
                    negative_meaning=(
                        "bearish because negative net margin means the period was unprofitable"
                    ),
                ),
                _positive_tone(detail.get("net_margin")),
            ),
            _card(
                "FCF margin",
                _pct(detail.get("fcf_margin")),
                _fcf_margin_detail(detail.get("fcf_margin")),
                _positive_tone(detail.get("fcf_margin")),
            ),
            _card(
                "ROE",
                _pct(detail.get("roe")),
                _ratio_metric_detail(
                    "Net income",
                    "total equity",
                    detail.get("roe"),
                    positive_meaning=(
                        "bullish because equity generated profit for shareholders"
                    ),
                    negative_meaning="bearish because equity generated losses",
                ),
                _positive_tone(detail.get("roe")),
            ),
            _card(
                "ROA",
                _pct(detail.get("roa")),
                _ratio_metric_detail(
                    "Net income",
                    "total assets",
                    detail.get("roa"),
                    positive_meaning="bullish because assets generated profit",
                    negative_meaning="bearish because assets generated a loss",
                ),
                _positive_tone(detail.get("roa")),
            ),
            _card(
                "Leverage",
                _pct(detail.get("leverage")),
                _leverage_detail(detail.get("leverage")),
                _leverage_tone(detail.get("leverage")),
            ),
            _card(
                "Revenue growth YoY",
                _pct(detail.get("revenue_growth_yoy")),
                _growth_detail("Revenue", detail.get("revenue_growth_yoy")),
                _positive_tone(detail.get("revenue_growth_yoy")),
            ),
            _card(
                "Net income growth YoY",
                _pct(detail.get("net_income_growth_yoy")),
                _growth_detail("Net income", detail.get("net_income_growth_yoy")),
                _positive_tone(detail.get("net_income_growth_yoy")),
            ),
            _card(
                "FCF growth YoY",
                _pct(detail.get("fcf_growth_yoy")),
                _growth_detail("Free cash flow", detail.get("fcf_growth_yoy")),
                _positive_tone(detail.get("fcf_growth_yoy")),
            ),
            _card(
                "Trailing P/E",
                _plain_number(detail.get("trailing_pe")),
                _valuation_multiple_detail("Trailing P/E", detail.get("trailing_pe")),
                _valuation_multiple_tone(detail.get("trailing_pe")),
            ),
            _card(
                "Forward P/E",
                _plain_number(detail.get("forward_pe")),
                _forward_pe_detail(detail.get("forward_pe"), detail.get("forward_data_status")),
                _valuation_multiple_tone(detail.get("forward_pe")),
            ),
            _card(
                "EPS beat rate",
                _pct(detail.get("eps_beat_rate")),
                _eps_beat_rate_detail(detail.get("eps_beat_rate")),
                _positive_tone(detail.get("eps_beat_rate")),
            ),
            _card(
                "Analyst count",
                _integer(detail.get("analyst_count")),
                _analyst_count_detail(detail.get("analyst_count")),
            ),
            _card(
                "Composite score",
                composite,
                _composite_score_detail(detail.get("composite_score")),
                _score_tone(detail.get("composite_score")),
            ),
            _card(
                "Filing period",
                period,
                _filing_period_detail(detail, form),
            ),
        ],
    )


def _insider_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    buy_value = detail.get("buy_value")
    sell_value = detail.get("sell_value")
    net_value = detail.get("net_transaction_value")
    buy_count = detail.get("buy_count")
    sell_count = detail.get("sell_count")
    headline = (
        f"{row['ticker']} insider signal compared purchase value {_money(buy_value)} "
        f"versus sale value {_money(sell_value)}; net Form 4 value was "
        f"{_money(net_value)} across {_integer(detail.get('directional_transactions'))} "
        "directional transaction(s)."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "Open-market purchases add positive value; sales subtract value. This uses a "
            "90-day Form 4 lookback, then normalizes net value across the current universe. "
            "A positive net value is bullish insider accumulation; a negative net value is "
            "insider distribution pressure."
        ),
        cards=[
            _card(
                "Buy / sell value",
                f"{_money(buy_value)} / {_money(sell_value)}",
                "Estimated purchase dollars versus sale dollars from directional Form 4 rows.",
                _money_tone(net_value),
            ),
            _card("Buy value", _money(buy_value), "Estimated purchase value."),
            _card("Sell value", _money(sell_value), "Estimated sale value."),
            _card(
                "Net value",
                _money(net_value),
                "Purchases minus sales.",
                _money_tone(net_value),
            ),
            _card(
                "Net shares", _integer(detail.get("net_shares")), "Signed shares bought minus sold."
            ),
            _card(
                "Directional transactions",
                _integer(detail.get("directional_transactions")),
                f"{_integer(buy_count)} purchase(s), {_integer(sell_count)} sale(s) counted.",
            ),
            _card(
                "Filers", _integer(detail.get("unique_filers")), "Unique insiders/filers counted."
            ),
            _card(
                "Largest purchase",
                _money(detail.get("largest_buy_value")),
                "Largest single purchase value in the reconstructed Form 4 rows.",
            ),
            _card(
                "Largest sale",
                _money(detail.get("largest_sell_value")),
                "Largest single sale value in the reconstructed Form 4 rows.",
            ),
            _card(
                "Latest transaction",
                _text(detail.get("latest_transaction_date"), "not reported"),
                "Most recent directional transaction date in the lookback window.",
            ),
        ],
    )


def _institutional_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    holder_changes = _holder_changes(detail.get("holder_changes"))
    top_holder_summary = _holder_change_summary(holder_changes, limit=2)
    if top_holder_summary:
        headline = (
            f"{row['ticker']} 13F net change was "
            f"{_signed_integer(detail.get('total_change_from_prev_quarter'))} shares across "
            f"{_integer(detail.get('holder_count'))} tracked holder(s); top changes: "
            f"{top_holder_summary}."
        )
    else:
        headline = (
            f"{row['ticker']} 13F net change was "
            f"{_signed_integer(detail.get('total_change_from_prev_quarter'))} shares across "
            f"{_integer(detail.get('holder_count'))} tracked holder(s)."
        )
    total_value_dollars = _thousands_to_dollars(detail.get("total_value_usd_thousands"))
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "13F holdings are delayed quarterly SEC filings, usually available up to 45 days "
            "after quarter end. Treat this as historical ownership context, not live "
            "institutional flow. The change ratios below are share-count ratios, not price "
            "returns."
        ),
        cards=[
            _card(
                "Quarter end",
                _text(detail.get("quarter_end_date"), "unknown"),
                "Latest mapped 13F reporting quarter available to the PIT loader.",
            ),
            _card(
                "Holder count",
                _integer(detail.get("holder_count")),
                "Unique 13F institutional filers mapped to this ticker.",
            ),
            _card(
                "Current shares",
                _integer(detail.get("total_shares_held")),
                "Total shares reported in mapped 13F rows for this quarter.",
            ),
            _card(
                "Previous shares",
                _integer(detail.get("previous_shares_held")),
                "Current shares minus the reported net quarterly share change.",
            ),
            _card(
                "Net shares changed",
                _signed_integer(detail.get("total_change_from_prev_quarter")),
                "Aggregate share increase or decrease versus the previous reported quarter.",
                _money_tone(detail.get("total_change_from_prev_quarter")),
            ),
            _card(
                "Position size change",
                _pct(detail.get("net_change_current_share_ratio") or detail.get("change_ratio")),
                (
                    "Net shares changed divided by currently reported shares. This measures "
                    "reported position-size change, not stock-price return."
                ),
            ),
            _card(
                "Prior-basis change",
                _pct(detail.get("net_change_prior_share_ratio")),
                "Net share change divided by estimated previous shares held.",
            ),
            _card(
                "Top holder changes",
                _holder_change_count(holder_changes),
                _holder_change_detail(holder_changes),
            ),
            _card(
                "Total 13F value",
                _money(total_value_dollars),
                "Sum of filing-reported position values; 13F values are reported in USD thousands.",
            ),
            _card(
                "Institutional score",
                _number(detail.get("institutional_score")),
                "Universe-normalized accumulation score used by the selection model.",
            ),
        ],
    )


def _news_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    dominant = _event_type_label(detail.get("dominant_event_type"))
    headline = (
        f"{row['ticker']} news signal counted {_integer(detail.get('headline_count'))} "
        f"ticker-tagged headline(s), with {_integer(detail.get('positive_count'))} positive "
        f"and {_integer(detail.get('negative_count'))} negative cue(s); dominant event "
        f"{dominant}."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "This is a headline-level context lane. Ticker mapping is confidence-weighted, "
            "event taxonomy separates guidance, earnings, litigation/regulatory, SEC filing, "
            "analyst action, M&A, product, and general headlines. Stronger article/email "
            "analysis lives on candidate pages. This is keyword taxonomy, not full article "
            "LLM sentiment, so it should be treated as low-conviction context unless "
            "corroborated."
        ),
        cards=[
            _card(
                "Headlines",
                _integer(detail.get("headline_count")),
                "Ticker-tagged headlines in the lookback window.",
            ),
            _card(
                "Weighted headlines",
                _plain_number(detail.get("weighted_headline_count")),
                "Sum of confidence-weighted ticker matches; lower-confidence matches count less.",
            ),
            _card(
                "Match confidence",
                _unsigned_pct(detail.get("match_confidence_avg")),
                "Average ticker-resolution confidence for the headlines used by this signal.",
            ),
            _card(
                "Dominant event",
                dominant.title(),
                "Most frequent event taxonomy bucket in the matched headlines.",
            ),
            _card(
                "Event mix",
                _event_mix_value(detail.get("event_type_counts")),
                _event_mix_detail(detail.get("event_type_counts")),
            ),
            _card("Sources", _integer(detail.get("source_count")), "Distinct feeds/sources."),
            _card(
                "Positive cues", _integer(detail.get("positive_count")), "Matched bullish terms."
            ),
            _card(
                "Negative cues", _integer(detail.get("negative_count")), "Matched bearish terms."
            ),
            _card(
                "Sentiment sum",
                _number(detail.get("sentiment_score")),
                "Positive cue count minus negative cue count.",
            ),
            _card(
                "News score", _number(detail.get("news_score")), "Universe-normalized news score."
            ),
            _card(
                "Source IDs",
                _source_id_count(detail.get("source_ids")),
                _source_id_detail(detail.get("source_ids")),
            ),
        ],
    )


def _sec_filing_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    sentiment = _text(detail.get("sentiment"), "NEUTRAL")
    filing_form = _text(detail.get("filing_form"), "filing")
    filing_date = _text(detail.get("filing_date"), "unknown")
    headline_sentence = _text(detail.get("headline_sentence"), "SEC filing analyzed.")
    confidence = _float(detail.get("confidence"))
    positives = detail.get("key_positives") or []
    risks = detail.get("key_risks") or []
    first_positive = str(positives[0]) if positives else "n/a"
    first_risk = str(risks[0]) if risks else "n/a"

    def _sentiment_tone(s: str) -> str:
        return {"BULLISH": "pass", "BEARISH": "block"}.get(s.upper(), "neutral")

    def _surprise_tone(s: str) -> str:
        return {"BEAT": "pass", "MISS": "block"}.get(s.upper(), "neutral")

    def _guidance_tone(s: str) -> str:
        return {"RAISED": "pass", "LOWERED": "block"}.get(s.upper(), "neutral")

    return _detail_payload(
        row,
        as_of,
        headline=f"{row['ticker']} {filing_form} filed {filing_date} — {headline_sentence}",
        detail=(
            f"LLM analysis of the official SEC {filing_form} filing text. "
            f"Score confidence: {_pct(confidence)}. "
            "Source: SEC EDGAR official filing."
        ),
        cards=[
            _card("Sentiment",            sentiment,
                  "Overall tone of the filing.",
                  _sentiment_tone(sentiment)),
            _card("EPS vs. estimate",      _text(detail.get("eps_vs_estimate"), "UNKNOWN"),
                  "Actual EPS vs. analyst consensus at time of filing.",
                  _surprise_tone(_text(detail.get("eps_vs_estimate"), ""))),
            _card("Revenue vs. estimate",  _text(detail.get("revenue_vs_estimate"), "UNKNOWN"),
                  "Actual revenue vs. analyst consensus.",
                  _surprise_tone(_text(detail.get("revenue_vs_estimate"), ""))),
            _card("Guidance",              _text(detail.get("guidance_change"), "UNKNOWN"),
                  "Whether the company raised, maintained, or lowered guidance.",
                  _guidance_tone(_text(detail.get("guidance_change"), ""))),
            _card("Key positive",          first_positive,
                  "Top positive factor extracted from the filing.",
                  "pass" if first_positive != "n/a" else "neutral"),
            _card("Key risk",              first_risk,
                  "Top risk factor extracted from the filing.",
                  "warn" if first_risk != "n/a" else "neutral"),
        ],
    )


def _options_flow_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    headline = (
        f"{row['ticker']} options flow used call volume {_integer(detail.get('call_volume'))} "
        f"versus put volume {_integer(detail.get('put_volume'))}; put/call volume ratio "
        f"{_plain_number(detail.get('put_call_volume_ratio'))}."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "This reconstructs the latest option-chain snapshot. Call-heavy volume is "
            "bullish context; put-heavy volume is bearish context. The lane remains "
            "disabled unless a real options provider is configured."
        ),
        cards=[
            _card(
                "Call volume",
                _integer(detail.get("call_volume")),
                "Total call contract volume in the latest snapshot.",
            ),
            _card(
                "Put volume",
                _integer(detail.get("put_volume")),
                "Total put contract volume in the latest snapshot.",
            ),
            _card(
                "Put/call volume ratio",
                _plain_number(detail.get("put_call_volume_ratio")),
                "Put volume divided by call volume; above 1.0 means puts traded more than calls.",
            ),
            _card(
                "Call share",
                _unsigned_pct(detail.get("call_share")),
                "Call volume divided by total option volume.",
            ),
            _card(
                "Open interest",
                _integer(detail.get("open_interest")),
                "Total open interest across contracts in the snapshot.",
            ),
            _card(
                "Mean IV",
                _unsigned_pct(detail.get("mean_implied_volatility")),
                "Average implied volatility for contracts with IV values.",
            ),
            _card(
                "Options pressure",
                _number(detail.get("options_pressure")),
                "Signed call/put pressure before universe ranking.",
                _score_tone(detail.get("options_pressure")),
            ),
            _card(
                "Options score",
                _number(detail.get("options_flow_score")),
                "Universe rank score for options flow pressure.",
                _score_tone(detail.get("options_flow_score")),
            ),
        ],
    )


def _options_anomaly_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    headline = (
        f"{row['ticker']} options anomaly detected gross option premium "
        f"{_money(detail.get('gross_premium'))}, net premium {_money(detail.get('net_premium'))}, "
        f"and volume/OI {_plain_number(detail.get('volume_to_open_interest'))}."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "This reconstructs unusual option activity from premium, volume, and open "
            "interest. Positive net premium means call-side premium dominated; negative "
            "means put-side premium dominated."
        ),
        cards=[
            _card(
                "Call premium",
                _money(detail.get("call_premium")),
                "Estimated call premium: contract price times volume times 100.",
            ),
            _card(
                "Put premium",
                _money(detail.get("put_premium")),
                "Estimated put premium: contract price times volume times 100.",
            ),
            _card(
                "Net premium",
                _money(detail.get("net_premium")),
                "Call premium minus put premium.",
                _money_tone(detail.get("net_premium")),
            ),
            _card(
                "Gross premium",
                _money(detail.get("gross_premium")),
                "Call premium plus put premium.",
            ),
            _card(
                "Option volume",
                _integer(detail.get("total_option_volume")),
                "Total contracts traded in the latest snapshot.",
            ),
            _card(
                "Open interest",
                _integer(detail.get("total_open_interest")),
                "Total open interest across contracts.",
            ),
            _card(
                "Volume/OI",
                _plain_number(detail.get("volume_to_open_interest")),
                "Total option volume divided by open interest; high values indicate unusual activity.",
            ),
            _card(
                "Unusual contracts",
                _integer(detail.get("unusual_contract_count")),
                (
                    "Contracts with volume at least 100 and volume/open-interest at least "
                    "2.0, or no open interest."
                ),
            ),
            _card(
                "Anomaly score",
                _number(detail.get("options_anomaly_score")),
                "Universe rank score for unusual options pressure.",
                _score_tone(detail.get("options_anomaly_score")),
            ),
        ],
    )


def _market_flow_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    lane = str(row["lane_key"])
    selected = _number(detail.get(lane))
    if lane in UNUSUAL_TRADE_LANES:
        return _unusual_trade_evidence(row, detail, as_of, selected)
    if lane == "buy_sell_pressure":
        return _buy_sell_pressure_evidence(row, detail, as_of, selected)
    if lane == "block_trade_pressure":
        return _block_trade_evidence(row, detail, as_of, selected)
    if lane == "market_flow_trend":
        return _market_flow_trend_evidence(row, detail, as_of, selected)
    headline = (
        f"{row['ticker']} {str(row['lane']).lower()} signal used "
        f"{_integer(detail.get('trade_count'))} delayed trade print(s), "
        f"{_money(detail.get('total_notional'))} total notional, and selected feature "
        f"score {selected}."
    )
    detail_text = LANE_EXPLANATIONS.get(
        lane, "Market-flow feature reconstructed from delayed trades."
    )
    cards = [
        _card("Selected feature", selected, _feature_detail(lane), _score_tone(detail.get(lane))),
        _card("Trade count", _integer(detail.get("trade_count")), "Delayed trade prints counted."),
        _card(
            "Total notional",
            _money(detail.get("total_notional")),
            "Dollar value represented by prints.",
        ),
        _card(
            "Net notional pressure",
            _pct(detail.get("net_notional_pressure")),
            "Signed notional divided by total notional.",
            _return_tone(detail.get("net_notional_pressure")),
        ),
        _card(
            "Block / off-exchange",
            (
                f"{_integer(detail.get('block_count'))} / "
                f"{_integer(detail.get('off_exchange_count'))}"
            ),
            "Block and off-exchange prints.",
        ),
        _card(
            "Pre-market volume",
            _integer(detail.get("pre_market_volume")),
            "Volume printed before the regular session.",
        ),
    ]
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=detail_text,
        cards=cards,
    )


def _market_flow_trend_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
    selected: str,
) -> dict[str, object]:
    ticker = str(row["ticker"])
    latest_pressure = detail.get("latest_net_notional_pressure")
    prior_pressure = detail.get("prior_net_notional_pressure_median")
    delta = detail.get("net_notional_pressure_delta")
    direction = _flow_direction_label(delta)
    headline = (
        f"{ticker} market-flow trend changed because latest signed notional pressure "
        f"{_pct(latest_pressure)} versus prior median {_pct(prior_pressure)} "
        f"created a pressure delta of {_pct(delta)}; selected feature score {selected}."
    )
    detail_text = (
        "This lane compares the newest signed notional pressure with the recent daily "
        "median pressure, then scales the move by participation so a tiny notional sample "
        "does not overstate conviction. A positive delta means flow improved versus the "
        "baseline; a negative delta means flow deteriorated."
    )
    cards = [
        _card(
            "Selected feature",
            selected,
            _feature_detail("market_flow_trend"),
            _score_tone(detail.get("market_flow_trend")),
        ),
        _card("Trade count", _integer(detail.get("trade_count")), "Delayed trade prints analyzed."),
        _card(
            "Total notional",
            _money(detail.get("total_notional")),
            "Dollar value across all analyzed prints for this ticker.",
        ),
        _card(
            "Latest pressure",
            _pct(latest_pressure),
            "Signed notional divided by latest-period notional.",
            _return_tone(latest_pressure),
        ),
        _card(
            "Prior pressure median",
            _pct(prior_pressure),
            "Median signed notional pressure across the prior analyzed daily periods.",
            _return_tone(prior_pressure),
        ),
        _card(
            "Pressure delta",
            _pct(delta),
            (
                "latest pressure minus prior median pressure; positive is improving "
                "buyer-side pressure, negative is deteriorating or seller-side pressure."
            ),
            _return_tone(delta),
        ),
        _card(
            "Trend participation",
            _unsigned_pct(detail.get("market_flow_trend_participation")),
            "Participation scaling from latest notional versus recent median notional.",
        ),
        _card(
            "Directional read",
            direction,
            _activity_pressure_meaning(direction),
            _flow_direction_tone(direction),
        ),
    ]
    return _detail_payload(row, as_of, headline=headline, detail=detail_text, cards=cards)


def _buy_sell_pressure_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
    selected: str,
) -> dict[str, object]:
    ticker = str(row["ticker"])
    total_notional = detail.get("total_notional")
    signed_notional = _signed_notional_from_pressure(detail)
    direction = _flow_direction_label(signed_notional)
    buy_notional, sell_notional = _buy_sell_notional_split(total_notional, signed_notional)
    headline = (
        f"{ticker} buy/sell pressure is {_flow_direction_bias(direction)}: "
        f"{_money(total_notional)} total analyzed notional, not off-exchange-only, "
        f"with {_signed_money(signed_notional)} {direction} signed notional "
        f"({_pct(detail.get('net_notional_pressure'))} net notional pressure); "
        f"selected feature score {selected}."
    )
    detail_text = (
        f"The signal is {_flow_direction_bias(direction)} because trade signing inference "
        f"estimated {direction} pressure: inferred buy notional {_money(buy_notional)} versus "
        f"sell notional {_money(sell_notional)}. This is not a confirmed buyer identity; "
        "it is a directional reconstruction from delayed Massive trade prints. Total analyzed "
        "notional includes all delayed prints in the slice, not just off-exchange prints."
    )
    cards = [
        _card("Selected feature", selected, _feature_detail("buy_sell_pressure"), _score_tone(detail.get("buy_sell_pressure"))),
        _card("Trade count", _integer(detail.get("trade_count")), "Delayed trade prints analyzed."),
        _card(
            "Total analyzed notional",
            _money(total_notional),
            "Dollar value across all delayed prints, not off-exchange-only dollars.",
        ),
        _card(
            "Signed notional",
            _signed_money(signed_notional),
            "Buy-inferred notional minus sell-inferred notional from trade signing inference.",
            _money_tone(signed_notional),
        ),
        _card(
            "Inferred buy/sell notional",
            f"{_money(buy_notional)} / {_money(sell_notional)}",
            "Split derived from total notional and signed notional; it is directional inference.",
            _flow_direction_tone(direction),
        ),
        _card(
            "Net notional pressure",
            _pct(detail.get("net_notional_pressure")),
            "Signed notional divided by total analyzed notional.",
            _return_tone(detail.get("net_notional_pressure")),
        ),
        _card(
            "Analyzed volume",
            _integer(detail.get("total_volume")),
            "Share volume represented by all analyzed delayed prints.",
        ),
        _card(
            "Signed volume",
            _signed_integer(_signed_volume_from_pressure(detail)),
            "Buy-inferred shares minus sell-inferred shares from trade signing inference.",
            _return_tone(detail.get("net_volume_pressure")),
        ),
        _card(
            "Large/off-exchange subset",
            _money(detail.get("focus_notional")),
            (
                f"{_integer(detail.get('focus_trade_count'))} block/TRF/off-exchange focused "
                f"print(s), {_pct(detail.get('focus_notional_share'))} of total analyzed notional; "
                "this is the subset of total analyzed notional."
            ),
            _money_tone(detail.get("signed_focus_notional")),
        ),
        _card(
            "Block / off-exchange counts",
            (
                f"{_integer(detail.get('block_count'))} / "
                f"{_integer(detail.get('off_exchange_count'))}"
            ),
            "These are counts, not dollar amount; total analyzed notional is all prints.",
        ),
        _card(
            "TRF/off-exchange",
            (
                f"{_integer(detail.get('trf_off_exchange_count'))} / "
                f"{_money(detail.get('trf_off_exchange_notional'))}"
            ),
            "TRF subset reported through FINRA TRF; useful context, not venue proof.",
        ),
        _card(
            "Pre-market volume",
            _integer(detail.get("pre_market_volume")),
            "Share volume printed before the regular session.",
        ),
    ]
    return _detail_payload(row, as_of, headline=headline, detail=detail_text, cards=cards)


def _block_trade_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
    selected: str,
) -> dict[str, object]:
    ticker = str(row["ticker"])
    direction = _flow_direction_label(detail.get("signed_focus_notional"))
    focus_count = detail.get("focus_trade_count")
    focus_notional = detail.get("focus_notional")
    signed_focus = detail.get("signed_focus_notional")
    focus_share = _float(detail.get("focus_notional_share"))
    trf_count = detail.get("trf_off_exchange_count")
    trf_notional = detail.get("trf_off_exchange_notional")
    largest = detail.get("largest_focus_notional")
    multiple = detail.get("largest_focus_notional_multiple")
    headline = (
        f"{ticker} block trade pressure is {_flow_direction_bias(direction)}: "
        f"{_integer(focus_count)} focused large/off-exchange print(s) carried "
        f"{_money(signed_focus)} {direction} focused notional "
        f"({_abs_pct(focus_share or 0.0)} of analyzed notional), including "
        f"{_integer(trf_count)} TRF/off-exchange print(s) totaling {_money(trf_notional)}; "
        f"largest focused print {_money(largest)} ({_ratio_label(multiple)} ticker-median print)."
    )
    detail_text = (
        f"The signal is {_flow_direction_bias(direction)} because focused block/off-exchange "
        f"notional was {direction}: {_signed_money(signed_focus)} signed focused notional "
        f"out of {_money(focus_notional)} focused notional. Focused prints represented "
        f"{_abs_pct(focus_share or 0.0)} of all analyzed notional, so the large-print lane "
        "treated this as meaningful pressure. TRF/off-exchange means reported through FINRA "
        "TRF; it is useful large-print evidence, not proof of a dark-pool venue."
    )
    cards = [
        _card("Selected feature", selected, _feature_detail("block_trade_pressure"), _score_tone(detail.get("block_trade_pressure"))),
        _card("Trade count", _integer(detail.get("trade_count")), "Delayed trade prints analyzed for this ticker/session."),
        _card("Analyzed volume", _integer(detail.get("total_volume")), "Share volume represented by the analyzed prints."),
        _card("Total notional", _money(detail.get("total_notional")), "Dollar value represented by all analyzed prints."),
        _card(
            "Average print price",
            _money(_safe_divide(detail.get("total_notional"), detail.get("total_volume"))),
            "Total notional divided by analyzed volume; this is not the largest block price.",
        ),
        _card(
            "Focused notional",
            _money(focus_notional),
            (
                f"{_integer(focus_count)} block/TRF/off-exchange focused print(s), "
                f"{_abs_pct(focus_share or 0.0)} of all analyzed notional."
            ),
            _money_tone(signed_focus),
        ),
        _card(
            "Directional read",
            direction,
            (
                f"{_signed_money(signed_focus)} signed focused notional / "
                f"{_money(focus_notional)} focused notional; "
                f"{_flow_direction_meaning(direction)}"
            ),
            _flow_direction_tone(direction),
        ),
        _card(
            "Net notional pressure",
            _pct(detail.get("net_notional_pressure")),
            "Signed notional divided by total notional across all analyzed prints.",
            _return_tone(detail.get("net_notional_pressure")),
        ),
        _card(
            "Block / off-exchange",
            (
                f"{_integer(detail.get('block_count'))} / "
                f"{_integer(detail.get('off_exchange_count'))}"
            ),
            "Counts of absolute block prints and off-exchange prints inside the analyzed set.",
        ),
        _card(
            "TRF/off-exchange",
            f"{_integer(trf_count)} / {_money(trf_notional)}",
            "Prints reported through FINRA TRF; useful off-exchange evidence, not venue proof.",
        ),
        _card(
            "Largest focused print",
            _money(largest),
            "Largest block/TRF/off-exchange print in the focused set.",
            _money_tone(signed_focus),
        ),
        _card(
            "Largest multiple",
            _ratio_label(multiple),
            "Largest focused notional divided by the ticker median print notional.",
        ),
        _card(
            "Threshold basis",
            _block_threshold_value(detail),
            _block_threshold_detail(detail),
        ),
        _card(
            "Pre-market volume",
            _integer(detail.get("pre_market_volume")),
            "Volume printed before the regular session.",
        ),
    ]
    return _detail_payload(row, as_of, headline=headline, detail=detail_text, cards=cards)


def _unusual_trade_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
    selected: str,
) -> dict[str, object]:
    lane = str(row["lane_key"])
    ticker = str(row["ticker"])
    lane_label = (
        "pre-market unusual activity"
        if lane == "pre_market_unusual_activity"
        else "unusual trade activity"
    )
    identified = (
        "Strong pre-market unusual activity"
        if lane == "pre_market_unusual_activity"
        else "Strong unusual trade activity"
    )
    meaning = _meaning_label(row)
    pressure_key = (
        "latest_pre_market_pressure"
        if lane == "pre_market_unusual_activity"
        else "latest_net_notional_pressure"
    )
    pressure = detail.get(pressure_key)
    if _float(pressure) is None:
        pressure = detail.get("net_notional_pressure")
    latest_notional_key = (
        "latest_pre_market_notional"
        if lane == "pre_market_unusual_activity"
        else "latest_activity_notional"
    )
    pressure_direction = _flow_direction_label(
        _signed_value_from_pressure(detail.get(latest_notional_key), pressure)
    )
    most_unusual = _most_unusual_activity_label(detail)
    if lane == "pre_market_unusual_activity":
        headline = (
            f"{ticker} identified {lane_label}: pre-market volume "
            f"{_ratio_label(detail.get('pre_market_volume_anomaly_ratio'))}, "
            f"pre-market notional {_ratio_label(detail.get('pre_market_notional_anomaly_ratio'))}, "
            f"pre-market trade count {_ratio_label(detail.get('pre_market_trade_count_anomaly_ratio'))}, "
            f"and pre-market pressure {_pct(pressure)} {pressure_direction}."
        )
    else:
        headline = (
            f"{ticker} identified {lane_label}: {most_unusual.lower()} was most unusual; "
            f"trade count {_ratio_label(detail.get('trade_count_anomaly_ratio'))}, notional "
            f"{_ratio_label(detail.get('notional_anomaly_ratio'))}, share volume "
            f"{_ratio_label(detail.get('volume_anomaly_ratio'))}, and detected-period pressure "
            f"{_pct(pressure)} {pressure_direction}."
        )
    pressure_sentence = (
        _pre_market_pressure_sentence(detail, pressure)
        if lane == "pre_market_unusual_activity"
        else _activity_pressure_sentence(detail, pressure)
    )
    detail_text = (
        f"This is {meaning.lower()} because the unusual activity is signed by net notional "
        f"pressure: {pressure_sentence} Positive pressure means "
        "buyer-side activity dominated the detected prints; negative pressure means "
        "seller-side activity dominated. The score shown is the selected market-flow "
        f"feature value {selected}."
    )
    cards = [
        _card(
            "What was identified",
            identified,
            _unusual_activity_identification_detail(lane),
            _score_tone(detail.get(lane)),
        ),
        _card(
            "Data source",
            str(row.get("source") or "unknown"),
            "Source lane used for this detection.",
        ),
        _card(
            "Evidence time",
            _timestamp_label(row.get("timestamp_as_of")),
            "Latest source timestamp used by this signal.",
        ),
        _card(
            "Conviction",
            _confidence_label(row.get("confidence_pct")),
            "Configured lane confidence for this runtime signal.",
            _confidence_tone(row.get("confidence_pct")),
        ),
        _card(
            "Meaning",
            meaning,
            "Bullish means buyer-side pressure; bearish means seller-side pressure.",
            _meaning_tone(meaning),
        ),
        _card(
            "Timing role",
            _activity_timing_value(lane),
            _activity_timing_detail(lane),
        ),
        _card(
            "Most unusual metric",
            most_unusual,
            _most_unusual_activity_detail(detail),
            _ratio_tone(_most_unusual_activity_ratio(detail)),
        ),
        _card(
            "Trade count anomaly",
            _ratio_label(detail.get("trade_count_anomaly_ratio")),
            _activity_count_detail(detail),
            _ratio_tone(detail.get("trade_count_anomaly_ratio")),
        ),
        _card(
            "Notional anomaly",
            _ratio_label(detail.get("notional_anomaly_ratio")),
            _activity_notional_detail(detail),
            _ratio_tone(detail.get("notional_anomaly_ratio")),
        ),
        _card(
            "Volume anomaly",
            _ratio_label(detail.get("volume_anomaly_ratio")),
            _activity_volume_detail(detail),
            _ratio_tone(detail.get("volume_anomaly_ratio")),
        ),
        _card(
            "Block/off-exchange role",
            _activity_block_role_value(detail),
            _activity_block_role_detail(),
        ),
        _card(
            "Net notional pressure",
            _pct(pressure),
            _activity_pressure_detail(detail, pressure),
            _return_tone(pressure),
        ),
    ]
    if lane == "pre_market_unusual_activity":
        cards = [
            card
            for card in cards
            if card["label"]
            not in {
                "Most unusual metric",
                "Trade count anomaly",
                "Notional anomaly",
                "Volume anomaly",
                "Net notional pressure",
            }
        ]
        cards.extend(
            [
                _card(
                    "Pre-market trade count anomaly",
                    _ratio_label(detail.get("pre_market_trade_count_anomaly_ratio")),
                    _pre_market_count_detail(detail),
                    _ratio_tone(detail.get("pre_market_trade_count_anomaly_ratio")),
                ),
                _card(
                    "Pre-market notional anomaly",
                    _ratio_label(detail.get("pre_market_notional_anomaly_ratio")),
                    _pre_market_notional_detail(detail),
                    _ratio_tone(detail.get("pre_market_notional_anomaly_ratio")),
                ),
                _card(
                    "Pre-market volume anomaly",
                    _ratio_label(detail.get("pre_market_volume_anomaly_ratio")),
                    _pre_market_volume_detail(detail),
                    _ratio_tone(detail.get("pre_market_volume_anomaly_ratio")),
                ),
                _card(
                    "Pre-market pressure",
                    _pct(pressure),
                    _pre_market_pressure_detail(detail, pressure),
                    _return_tone(pressure),
                ),
                _card(
                    "Pre-market volume",
                    _integer(detail.get("pre_market_volume")),
                    "Total pre-market shares printed before the regular session.",
                ),
            ]
        )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=detail_text,
        cards=cards,
    )


def _fallback_evidence(
    row: Mapping[str, object],
    as_of: date,
    *,
    reconstruction_error: str | None = None,
) -> dict[str, object]:
    lane = str(row["lane_key"])
    row_summary = _text(row.get("summary"), "")
    detail = LANE_EXPLANATIONS.get(
        lane,
        (
            "This lane does not have a dedicated metric reconstructor in the inspector yet; "
            "the row is still auditable through its stored summary, direction, score, "
            "source timestamp, and reason code."
        ),
    )
    if row_summary:
        detail = f"{detail} Stored signal summary: {row_summary}"
    cards = [
        _card(
            "Stored summary",
            _text(row.get("summary"), "not recorded"),
            "Persisted signal explanation from the runtime cycle.",
        ),
        _card(
            "Score",
            str(row["score"]),
            "Signed signal strength; positive supports bullish review, negative adds caution.",
        ),
        _card(
            "Direction",
            str(row.get("direction") or "UNKNOWN"),
            "Persisted signal direction after the lane interpreted its source data.",
        ),
        _card(
            "Reason",
            str(row["reason_codes_label"]),
            "Reason code recorded by the selection engine for audit and policy gates.",
        ),
        _card(
            "Source as-of",
            _timestamp_label(row.get("timestamp_as_of")),
            "Latest source timestamp used by the signal.",
        ),
        _card(
            "Source ID",
            _text(row.get("source_id"), "not recorded"),
            "Stored provenance source identifier for this signal.",
        ),
        _card("Confidence", f"{row['confidence_pct']}%", "Lane confidence configured for runtime."),
    ]
    if reconstruction_error:
        detail = (
            f"{detail} Local metric reconstruction failed; using stored provenance "
            "and reason codes."
        )
        cards.append(
            _card(
                "Reconstruction",
                "Unavailable",
                reconstruction_error,
                "warn",
            )
        )
    return _detail_payload(
        row,
        as_of,
        headline=(
            f"{row['ticker']} {row['lane']} stored evidence from {row['source']}: "
            f"{row_summary or row.get('reason_codes_label') or 'summary not recorded'} "
            f"(score {row['score']})."
        ),
        detail=detail,
        cards=cards,
    )


def _fallback_evidence_from_detail(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    del detail
    return _fallback_evidence(row, as_of)


def _detail_payload(
    row: Mapping[str, object],
    as_of: date,
    *,
    headline: str,
    detail: str,
    cards: list[dict[str, str]],
) -> dict[str, object]:
    return {
        "trigger_headline": headline,
        "trigger_detail": detail,
        "trigger_window": (
            f"Signal cycle as-of {_timestamp_label(row.get('signal_as_of'))}; "
            f"source data as-of {_timestamp_label(row.get('timestamp_as_of'))}; "
            f"reconstructed locally for {as_of.isoformat()}."
        ),
        "trigger_cards": cards,
    }


def _apply_concrete_inspection_text(row: dict[str, object]) -> None:
    headline = _text(row.get("trigger_headline"), "")
    if not headline:
        return
    ticker = _text(row.get("ticker"), "ticker").upper()
    lane = _text(row.get("lane") or row.get("display_name"), "Signal")
    direction = _text(row.get("direction"), "UNKNOWN").lower()
    score = _text(row.get("score"), "no score")
    detail = _text(row.get("trigger_detail"), "")
    concise_detail = f" {_clip_sentence(detail)}" if detail else ""
    row["interpretation_text"] = (
        f"{lane} hard evidence for {ticker}: {headline}{concise_detail} "
        f"Direction is {direction}; score {score}. {_score_context_sentence(row)}"
    )
    row["summary"] = _clip_sentence(headline, max_chars=220)
    row["decision_effect_text"] = _concrete_decision_effect_text(row, headline)
    row["quality_text"] = _concrete_quality_text(row)
    if "provenance_text" in row:
        row["provenance_text"] = _concrete_provenance_text(row)


def _concrete_decision_effect_text(row: Mapping[str, object], headline: str) -> str:
    ticker = _text(row.get("ticker"), "ticker").upper()
    bucket = _text(row.get("bucket"), "Signal")
    action = _text(row.get("report_action"), "unknown action")
    gate = _text(row.get("report_gate_status"), "unknown gate")
    conviction = _text(row.get("report_conviction_pct"), "n/a")
    reason = _text(row.get("reason_text") or row.get("reason_codes_label"), "reason not recorded")
    if bucket == "Actionable":
        effect = "included in the weighted decision score"
    elif bucket == "Context":
        effect = "kept as corroborating context, not direct score weight"
    elif bucket == "Suppressed":
        effect = "excluded from the decision score and shown for audit"
    else:
        effect = "recorded for review"
    return (
        f"{bucket} signal for {ticker}: {effect}. Current report action {action}, "
        f"conviction {conviction}%, gate {gate}. {_actionability_context_sentence(row)} "
        f"Evidence: {headline} Reason: {reason}"
    )


def _score_context_sentence(row: Mapping[str, object]) -> str:
    lane = _text(row.get("lane_key") or row.get("lane"), "signal").replace("_", " ")
    score = _float(row.get("score_value"))
    if score is None:
        return f"The {lane} score is lane-specific and should be read with the evidence cards."
    if abs(score) <= SCORE_TONE_THRESHOLD:
        return (
            f"The {lane} score is near neutral because it is between "
            f"-{SCORE_TONE_THRESHOLD:.2f} and +{SCORE_TONE_THRESHOLD:.2f}."
        )
    direction = "bullish" if score > 0.0 else "bearish"
    return (
        f"The {lane} score is lane-specific; its sign is {direction}, and the cards show "
        "the underlying units."
    )


def _actionability_context_sentence(row: Mapping[str, object]) -> str:
    bucket = _text(row.get("bucket"), "")
    actionability = _text(row.get("actionability_label") or row.get("actionability"), bucket)
    if bucket == "Actionable":
        return f"Actionability is {actionability}: this evidence can affect the decision score."
    if bucket == "Context":
        return (
            f"Actionability is {actionability}: use the evidence as context, not direct score "
            "weight."
        )
    if bucket == "Suppressed":
        return f"Actionability is {actionability}: this evidence is kept for audit only."
    return f"Actionability is {actionability}: review the lane policy and evidence cards."


def _concrete_quality_text(row: Mapping[str, object]) -> str:
    verification = _text(row.get("verification_label"), _text(row.get("verification_level"), "verification unknown"))
    freshness = _text(row.get("freshness"), "freshness unknown")
    confidence = _text(row.get("confidence_pct"), "n/a")
    source_tier = _text(row.get("source_tier"), "source tier unknown")
    signal_as_of = _timestamp_label(row.get("signal_as_of"))
    source_as_of = _timestamp_label(row.get("timestamp_as_of"))
    return (
        f"{verification} evidence from {source_tier}; freshness {freshness}; "
        f"confidence {confidence}%; signal cycle {signal_as_of}; source data {source_as_of}."
    )


def _concrete_provenance_text(row: Mapping[str, object]) -> str:
    source = _text(row.get("source"), "source unknown")
    source_id = _text(row.get("source_id"), "not recorded")
    return (
        f"{source}; source id {source_id}; source data as-of "
        f"{_timestamp_label(row.get('timestamp_as_of'))}."
    )


def _clip_sentence(
    value: str,
    *,
    limit: int = 360,
    max_chars: int | None = None,
) -> str:
    if max_chars is not None:
        limit = max_chars
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    clipped = value[:limit].rsplit(" ", 1)[0].rstrip(".,;")
    return f"{clipped}."


def _safe_frame(function: Any, as_of: date, tickers: list[str], loader: Any) -> pd.DataFrame:
    try:
        frame = function(as_of, set(tickers), loader)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        LOGGER.warning(
            "signal evidence detail reconstruction failed",
            extra={
                "function": getattr(function, "__name__", str(function)),
                "as_of": as_of.isoformat(),
                "ticker_count": len(tickers),
                "error": error,
            },
        )
        return _empty_detail_frame(error)
    if not isinstance(frame, pd.DataFrame):
        return _empty_detail_frame(
            f"{getattr(function, '__name__', 'detail builder')} returned {type(frame).__name__}"
        )
    return frame


def _empty_detail_frame(error: str) -> pd.DataFrame:
    frame = pd.DataFrame()
    frame.attrs["reconstruction_error"] = error
    return frame


def _frame_error(frame: pd.DataFrame | None) -> str | None:
    if frame is None:
        return None
    value = frame.attrs.get("reconstruction_error")
    return str(value) if value else None


def _frame_row(frame: pd.DataFrame | None, ticker: str) -> Mapping[str, object] | None:
    if frame is None or frame.empty or "ticker" not in frame.columns:
        return None
    selected = frame[frame["ticker"].astype(str).str.upper() == ticker.upper()]
    if selected.empty:
        return None
    return cast(Mapping[str, object], selected.iloc[0].to_dict())


def _dashboard_as_of(rows: Sequence[Mapping[str, object]]) -> date:
    for key in ("signal_as_of", "timestamp_as_of"):
        dates = [_date_from(row.get(key)) for row in rows]
        usable = [item for item in dates if item is not None]
        if usable:
            return max(usable)
    return date.today()


def _market_flow_knowledge_as_of(rows: Sequence[Mapping[str, object]]) -> date | None:
    dates = [
        _date_from(row.get("timestamp_as_of"))
        for row in rows
        if str(row.get("lane_key") or "") in MARKET_FLOW_LANES
    ]
    usable = [item for item in dates if item is not None]
    return max(usable) if usable else None


def _date_from(value: object) -> date | None:
    timestamp = _datetime_from(value)
    return timestamp.date() if timestamp is not None else None


def _timestamp_label(value: object) -> str:
    timestamp = _datetime_from(value)
    if timestamp is None:
        return "unknown"
    return timestamp.strftime("%Y-%m-%d %H:%M UTC")


def _datetime_from(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=UTC)
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _card(label: str, value: str, detail: str, tone: str = "neutral") -> dict[str, str]:
    return {"label": label, "value": value, "detail": detail, "tone": tone}


def _float(value: object) -> float | None:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    try:
        parsed = float(str(value))
    except TypeError, ValueError:
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _number(value: object) -> str:
    parsed = _float(value)
    return "n/a" if parsed is None else f"{parsed:+.2f}"


def _plain_number(value: object) -> str:
    parsed = _float(value)
    return "n/a" if parsed is None else f"{parsed:.2f}"


def _pct(value: object) -> str:
    parsed = _float(value)
    return "n/a" if parsed is None else f"{parsed:+.1%}"


def _unsigned_pct(value: object) -> str:
    parsed = _float(value)
    return "n/a" if parsed is None else f"{parsed:.1%}"


def _ratio_label(value: object) -> str:
    parsed = _float(value)
    return "n/a" if parsed is None else f"{parsed:.2f}x"


def _bar_count(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "prior daily bars"
    count = max(round(parsed), 0)
    noun = "bar" if count == 1 else "bars"
    return f"{count:,} prior daily {noun}"


def _short_bar_count(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "n/a"
    count = max(round(parsed), 0)
    noun = "bar" if count == 1 else "bars"
    return f"{count:,} {noun}"


def _day_count(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "configured"
    count = max(round(parsed), 0)
    return f"{count:,}-day"


def _price_change_phrase(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "price move was n/a"
    if parsed > 0.0:
        return f"price increased {_pct(parsed)}"
    if parsed < 0.0:
        return f"price decreased {_pct(parsed)}"
    return "price was flat"


def _volume_price_meaning(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "Price direction was unavailable, so the volume shock has no directional read."
    if parsed > 0.0:
        return "high volume with price up is interpreted as accumulation pressure."
    if parsed < 0.0:
        return "high volume with price down is interpreted as distribution pressure."
    return "high volume with a flat price is treated as neutral until direction confirms."


def _technical_driver_mix_detail(detail: Mapping[str, object]) -> str:
    return (
        f"trend {_number(detail.get('trend_score'))}, "
        f"momentum {_number(detail.get('momentum_score'))}, "
        f"volume {_number(detail.get('volume_confirmation_score'))}, "
        f"relative strength {_number(detail.get('relative_strength_score'))}, "
        f"trade pressure {_number(detail.get('trade_pressure_score'))}, "
        f"pattern {_number(detail.get('chart_pattern_score'))}, "
        f"volatility risk {_number(detail.get('volatility_risk_score'))}, "
        f"external indicators {_number(detail.get('external_indicator_score'))}."
    )


def _price_vs_sma_phrase(detail: Mapping[str, object]) -> str:
    close = _float(detail.get("latest_close"))
    sma20 = _float(detail.get("sma20"))
    sma50 = _float(detail.get("sma50"))
    sma200 = _float(detail.get("sma200"))
    if close is None:
        return "not available"
    above = [
        label
        for label, value in (("SMA20", sma20), ("SMA50", sma50), ("SMA200", sma200))
        if value is not None and close > value
    ]
    below = [
        label
        for label, value in (("SMA20", sma20), ("SMA50", sma50), ("SMA200", sma200))
        if value is not None and close <= value
    ]
    parts = []
    if above:
        parts.append(f"above {', '.join(above)}")
    if below:
        parts.append(f"not above {', '.join(below)}")
    return "; ".join(parts) if parts else "SMA comparison unavailable"


def _price_vs_sma_value(detail: Mapping[str, object]) -> str:
    return f"{_money(detail.get('latest_close'))} close"


def _price_vs_sma_detail(detail: Mapping[str, object]) -> str:
    return (
        f"Latest close {_money(detail.get('latest_close'))} is {_price_vs_sma_phrase(detail)}; "
        f"SMA20 {_money(detail.get('sma20'))}, SMA50 {_money(detail.get('sma50'))}, "
        f"SMA200 {_money(detail.get('sma200'))}."
    )


def _trend_score_detail(detail: Mapping[str, object]) -> str:
    return (
        "Trend score checks close above/below SMA20, SMA50, SMA200 and whether SMA20/SMA50 "
        f"are rising. {_price_vs_sma_detail(detail)}"
    )


def _integer(value: object) -> str:
    parsed = _float(value)
    return "n/a" if parsed is None else f"{round(parsed):,}"


def _signed_integer(value: object) -> str:
    parsed = _float(value)
    return "n/a" if parsed is None else f"{round(parsed):+,}"


def _money(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "n/a"
    sign = "-" if parsed < 0 else ""
    absolute = abs(parsed)
    if absolute >= MONEY_BILLION:
        return f"{sign}${absolute / MONEY_BILLION:.2f}B"
    if absolute >= MONEY_MILLION:
        return f"{sign}${absolute / MONEY_MILLION:.2f}M"
    if absolute >= MONEY_THOUSAND:
        return f"{sign}${absolute / MONEY_THOUSAND:.1f}K"
    return f"{sign}${absolute:,.2f}"


def _signed_money(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "n/a"
    if parsed > 0.0:
        return f"+{_money(parsed)}"
    return _money(parsed)


def _text(value: object, default: str) -> str:
    if value is None or value is pd.NA or value is pd.NaT:
        return default
    text = " ".join(str(value).split())
    return text if text and text.lower() not in {"nan", "none", "nat"} else default


def _thousands_to_dollars(value: object) -> float | None:
    parsed = _float(value)
    return None if parsed is None else parsed * 1000.0


def _holder_changes(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _holder_change_count(holder_changes: Sequence[Mapping[str, object]]) -> str:
    if not holder_changes:
        return "n/a"
    return f"{len(holder_changes)} shown"


def _holder_change_summary(
    holder_changes: Sequence[Mapping[str, object]],
    *,
    limit: int,
) -> str:
    return ", ".join(_holder_change_phrase(item) for item in holder_changes[:limit])


def _holder_change_detail(holder_changes: Sequence[Mapping[str, object]]) -> str:
    if not holder_changes:
        return "No per-holder 13F changes were available in the reconstructed detail frame."
    return "; ".join(_holder_change_phrase(item, include_position=True) for item in holder_changes)


def _holder_change_phrase(
    holder: Mapping[str, object],
    *,
    include_position: bool = False,
) -> str:
    name = _text(holder.get("holder_name") or holder.get("holder_cik"), "Unknown holder")
    change = _signed_integer(holder.get("change_from_prev_quarter"))
    current = _integer(holder.get("current_shares"))
    previous = _integer(holder.get("previous_shares"))
    value = _money(_thousands_to_dollars(holder.get("value_usd_thousands")))
    if not include_position:
        return f"{name} {change}"
    return f"{name} {change} shares ({previous} -> {current}; filing value {value})"


def _confidence_label(value: object) -> str:
    parsed = _float(value)
    return "n/a" if parsed is None else f"{round(parsed):.0f}%"


def _tone(value: object, threshold: float) -> str:
    parsed = _float(value)
    if parsed is None:
        return "neutral"
    return "pass" if parsed >= threshold else "warn"


def _ratio_tone(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "neutral"
    if parsed >= 2.0:
        return "pass"
    if parsed >= 1.5:
        return "warn"
    return "neutral"


def _confidence_tone(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "neutral"
    if parsed >= 75:
        return "pass"
    if parsed >= 50:
        return "warn"
    return "neutral"


def _return_tone(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "neutral"
    if parsed > 0.0:
        return "pass"
    if parsed < 0.0:
        return "block"
    return "neutral"


def _score_tone(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "neutral"
    if parsed >= SCORE_TONE_THRESHOLD:
        return "pass"
    if parsed <= -SCORE_TONE_THRESHOLD:
        return "block"
    return "neutral"


def _money_tone(value: object) -> str:
    return _return_tone(value)


def _positive_tone(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "neutral"
    if parsed > 0.0:
        return "pass"
    if parsed < 0.0:
        return "block"
    return "neutral"


def _leverage_tone(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "neutral"
    if parsed >= 0.75:
        return "block"
    if parsed >= 0.5:
        return "warn"
    return "pass"


def _valuation_multiple_tone(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "neutral"
    if parsed <= 20.0:
        return "pass"
    if parsed <= 35.0:
        return "warn"
    return "block"


def _filing_period_label(detail: Mapping[str, object]) -> str:
    period = _text(detail.get("filing_period"), "period unknown")
    year = _text(detail.get("filing_year"), "")
    return f"{period} {year}".strip()


def _fundamentals_period_alignment_sentence(detail: Mapping[str, object]) -> str:
    status = _text(detail.get("period_alignment_status"), "unknown")
    period = _filing_period_label(detail)
    if status == "aligned":
        return f"Using SEC metrics from one aligned reporting period: {period}."
    if status == "incomplete_period":
        return (
            f"SEC metrics for {period} were incomplete, so ratio scores that need matching "
            "revenue and income are not used."
        )
    return f"SEC period alignment could not be fully verified for {period}."


def _fundamentals_bias(detail: Mapping[str, object]) -> str:
    score = _float(detail.get("composite_score"))
    if score is not None:
        if score > SCORE_TONE_THRESHOLD:
            return "bullish"
        if score < -SCORE_TONE_THRESHOLD:
            return "bearish"
    return "mixed"


def _fundamentals_driver_headline(detail: Mapping[str, object]) -> str:
    drivers = _fundamentals_driver_phrases(detail)
    if drivers:
        return f"{'; '.join(drivers[:3])}."
    return (
        f"net margin {_pct(detail.get('net_margin'))}, revenue growth YoY "
        f"{_pct(detail.get('revenue_growth_yoy'))}, and leverage {_pct(detail.get('leverage'))}."
    )


def _fundamentals_driver_detail(detail: Mapping[str, object]) -> str:
    bearish = _fundamentals_bearish_drivers(detail)
    bullish = _fundamentals_bullish_drivers(detail)
    sections: list[str] = []
    if bearish:
        sections.append(f"Bearish drivers: {', '.join(bearish)}.")
    if bullish:
        sections.append(f"Bullish offsets: {', '.join(bullish)}.")
    return " ".join(sections) or "No clear fundamental driver stood out in the detail frame."


def _fundamentals_driver_phrases(detail: Mapping[str, object]) -> list[str]:
    phrases: list[str] = []
    fcf_margin = _float(detail.get("fcf_margin"))
    leverage = _float(detail.get("leverage"))
    net_margin = _float(detail.get("net_margin"))
    revenue_growth = _float(detail.get("revenue_growth_yoy"))
    fcf_growth = _float(detail.get("fcf_growth_yoy"))

    if fcf_margin is not None and fcf_margin < 0.0:
        phrases.append(f"FCF margin {_pct(fcf_margin)} signals cash burn")
    if leverage is not None and leverage >= 0.75:
        phrases.append(f"leverage {_pct(leverage)} is high")
    if net_margin is not None and net_margin > 0.0:
        phrases.append(f"net margin {_pct(net_margin)} is profitable")
    if revenue_growth is not None and revenue_growth < 0.0:
        phrases.append(f"revenue YoY {_pct(revenue_growth)} shows contraction")
    if fcf_growth is not None and fcf_growth < 0.0:
        phrases.append(f"free-cash-flow YoY {_pct(fcf_growth)} shows deterioration")
    return phrases


def _fundamentals_bearish_drivers(detail: Mapping[str, object]) -> list[str]:
    drivers: list[str] = []
    fcf_margin = _float(detail.get("fcf_margin"))
    leverage = _float(detail.get("leverage"))
    revenue_growth = _float(detail.get("revenue_growth_yoy"))
    net_income_growth = _float(detail.get("net_income_growth_yoy"))
    fcf_growth = _float(detail.get("fcf_growth_yoy"))
    if fcf_margin is not None and fcf_margin < 0.0:
        drivers.append(f"cash burn (FCF margin {_pct(fcf_margin)})")
    if leverage is not None and leverage >= 0.75:
        drivers.append(f"high leverage ({_pct(leverage)} liabilities/assets)")
    if revenue_growth is not None and revenue_growth < 0.0:
        drivers.append(f"revenue contraction ({_pct(revenue_growth)} YoY)")
    if net_income_growth is not None and net_income_growth < 0.0:
        drivers.append(f"net income contraction ({_pct(net_income_growth)} YoY)")
    if fcf_growth is not None and fcf_growth < 0.0:
        drivers.append(f"free-cash-flow contraction ({_pct(fcf_growth)} YoY)")
    return drivers


def _fundamentals_bullish_drivers(detail: Mapping[str, object]) -> list[str]:
    drivers: list[str] = []
    net_margin = _float(detail.get("net_margin"))
    fcf_margin = _float(detail.get("fcf_margin"))
    revenue_growth = _float(detail.get("revenue_growth_yoy"))
    net_income_growth = _float(detail.get("net_income_growth_yoy"))
    fcf_growth = _float(detail.get("fcf_growth_yoy"))
    if net_margin is not None and net_margin > 0.0:
        drivers.append(f"profitable net margin ({_pct(net_margin)})")
    if fcf_margin is not None and fcf_margin > 0.0:
        drivers.append(f"positive FCF margin ({_pct(fcf_margin)})")
    if revenue_growth is not None and revenue_growth > 0.0:
        drivers.append(f"revenue growth ({_pct(revenue_growth)} YoY)")
    if net_income_growth is not None and net_income_growth > 0.0:
        drivers.append(f"net income growth ({_pct(net_income_growth)} YoY)")
    if fcf_growth is not None and fcf_growth > 0.0:
        drivers.append(f"free-cash-flow growth ({_pct(fcf_growth)} YoY)")
    return drivers


def _fundamentals_trend_value(detail: Mapping[str, object]) -> str:
    return f"revenue {_pct(detail.get('revenue_growth_yoy'))}"


def _fundamentals_trend_detail(detail: Mapping[str, object]) -> str:
    changes = [
        _change_sentence("Revenue", detail.get("revenue_growth_yoy")),
        _change_sentence("net income", detail.get("net_income_growth_yoy")),
        _change_sentence("free cash flow", detail.get("fcf_growth_yoy")),
    ]
    usable = [item for item in changes if item]
    if not usable:
        return "Year-over-year trend was not available in the reconstructed detail frame."
    return f"{'; '.join(usable)} versus the same period last year."


def _fundamentals_trend_tone(detail: Mapping[str, object]) -> str:
    values = [
        _float(detail.get("revenue_growth_yoy")),
        _float(detail.get("net_income_growth_yoy")),
        _float(detail.get("fcf_growth_yoy")),
    ]
    usable = [value for value in values if value is not None]
    if not usable:
        return "neutral"
    total = sum(1 if value > 0.0 else -1 if value < 0.0 else 0 for value in usable)
    if total > 0:
        return "pass"
    if total < 0:
        return "block"
    return "neutral"


def _change_sentence(label: str, value: object) -> str | None:
    parsed = _float(value)
    if parsed is None:
        return None
    if parsed > 0.0:
        return f"{label} increased {_abs_pct(parsed)}"
    if parsed < 0.0:
        return f"{label} decreased {_abs_pct(parsed)}"
    return f"{label} was flat"


def _ratio_metric_detail(
    numerator_label: str,
    denominator_label: str,
    value: object,
    *,
    positive_meaning: str,
    negative_meaning: str,
) -> str:
    parsed = _float(value)
    if parsed is None:
        return f"{numerator_label} divided by {denominator_label}; value was not available."
    meaning = positive_meaning if parsed >= 0.0 else negative_meaning
    return f"{numerator_label} is {_pct(parsed)} of {denominator_label}; {meaning}."


def _fcf_margin_detail(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "Free cash flow divided by revenue; value was not available."
    if parsed < 0.0:
        return (
            f"Free cash flow is {_pct(parsed)} of revenue; bearish because free cash flow is "
            "negative, meaning cash burn relative to sales."
        )
    return (
        f"Free cash flow is {_pct(parsed)} of revenue; bullish because operations generated "
        "cash after capital spending."
    )


def _leverage_detail(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return "Total liabilities divided by total assets; value was not available."
    if parsed >= 0.75:
        return (
            f"Liabilities are {_pct(parsed)} of assets; bearish when high and caution because "
            "liabilities are a large share of assets, leaving less balance-sheet cushion."
        )
    if parsed >= 0.5:
        return (
            f"Liabilities are {_pct(parsed)} of assets; caution because liabilities are "
            "meaningful and can limit flexibility."
        )
    return (
        f"Liabilities are {_pct(parsed)} of assets; bullish balance-sheet input because "
        "lower leverage supports flexibility."
    )


def _growth_detail(label: str, value: object) -> str:
    sentence = _change_sentence(label, value)
    if sentence is None:
        return f"{label} versus the same period last year; value was not available."
    meaning = "bullish trend input" if (_float(value) or 0.0) > 0.0 else "bearish trend input"
    if (_float(value) or 0.0) == 0.0:
        meaning = "neutral trend input"
    return f"{sentence} versus the same period last year; {meaning}."


def _valuation_multiple_detail(label: str, value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return (
            f"{label} divides market value by earnings; value was not available, so "
            "valuation does not add conviction."
        )
    if parsed <= 20.0:
        return (
            f"{label} is {_plain_number(parsed)}; bullish valuation input because the "
            "earnings multiple is below the 20x value-friendly threshold used by this "
            "dashboard."
        )
    if parsed <= 35.0:
        return (
            f"{label} is {_plain_number(parsed)}; valuation caution because the multiple "
            "is above 20x but below the 35x expensive threshold."
        )
    return (
        f"{label} is {_plain_number(parsed)}; bearish valuation input because the "
        "multiple is above the 35x expensive threshold."
    )


def _forward_pe_detail(value: object, status: object) -> str:
    parsed = _float(value)
    status_text = _forward_fundamentals_status_label(status).rstrip(".")
    if parsed is None:
        return (
            f"Forward P/E divides price by expected earnings; value was not available. "
            f"{status_text}, so this forward valuation input is not used."
        )
    base = _valuation_multiple_detail("Forward P/E", parsed).replace(
        "valuation caution",
        "forward valuation caution",
    ).replace(
        "bullish valuation input",
        "bullish forward valuation input",
    ).replace(
        "bearish valuation input",
        "bearish forward valuation input",
    )
    return f"{base} {status_text}."


def _eps_beat_rate_detail(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return (
            "EPS beat rate is the share of recent earnings reports that beat estimates; "
            "value was not available, so execution quality is not confirmed."
        )
    if parsed >= 0.6:
        return (
            f"EPS beat rate is {_pct(parsed)}; bullish execution quality because most "
            "recent reported quarters beat analyst estimates."
        )
    if parsed >= 0.4:
        return (
            f"EPS beat rate is {_pct(parsed)}; neutral execution quality because beats "
            "and misses are mixed."
        )
    return (
        f"EPS beat rate is {_pct(parsed)}; bearish execution quality because recent "
        "quarters usually missed estimates."
    )


def _analyst_count_detail(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return (
            "Analyst count measures how many forward estimates support optional forward "
            "fundamentals; value was not available, so estimate reliability is unknown."
        )
    count = _integer(parsed)
    if parsed >= 10.0:
        return (
            f"{count} analyst estimates support the forward fields; reliability input, "
            "not a bullish or bearish signal by itself."
        )
    if parsed > 0.0:
        return (
            f"{count} analyst estimate(s) support the forward fields; caution because "
            "thin estimate coverage is less reliable, and it is not directional by itself."
        )
    return (
        "No analyst estimates support the forward fields; caution because forward "
        "valuation is not independently covered."
    )


def _composite_score_detail(value: object) -> str:
    parsed = _float(value)
    if parsed is None:
        return (
            "Composite score combines quality, growth, valuation, and forward inputs; "
            "value was not available."
        )
    if parsed > SCORE_TONE_THRESHOLD:
        return (
            f"Composite score {_number(parsed)} is a bullish composite because quality, "
            "growth, valuation, and forward inputs net positive."
        )
    if parsed < -SCORE_TONE_THRESHOLD:
        return (
            f"Composite score {_number(parsed)} is a bearish composite because quality, "
            "growth, valuation, and forward inputs net negative."
        )
    return (
        f"Composite score {_number(parsed)} is mixed because the fundamentals inputs "
        "nearly offset each other."
    )


def _filing_period_detail(detail: Mapping[str, object], form: str) -> str:
    period_end = _text(detail.get("filing_period_end"), "unknown")
    alignment = _text(detail.get("period_alignment_status"), "unknown")
    return (
        f"SEC form {form}; period ended {period_end}. This is official SEC filing "
        f"context, not directional by itself; alignment status {alignment} tells whether "
        "the period matches the latest usable filing."
    )


def _event_type_label(value: object) -> str:
    return _text(value, "general").replace("_", " ")


def _event_counts(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    counts: dict[str, int] = {}
    for key, count in value.items():
        parsed = _float(count)
        if parsed is not None:
            counts[_event_type_label(key)] = round(parsed)
    return counts


def _event_mix_value(value: object) -> str:
    counts = _event_counts(value)
    if not counts:
        return "not reported"
    total = sum(counts.values())
    noun = "headline" if total == 1 else "headlines"
    return f"{total} {noun}"


def _event_mix_detail(value: object) -> str:
    counts = _event_counts(value)
    if not counts:
        return "No event taxonomy counts were available in the detail frame."
    return "; ".join(f"{key}: {count}" for key, count in sorted(counts.items())) + "."


def _source_id_values(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    return [str(item) for item in value if str(item).strip()]


def _source_id_count(value: object) -> str:
    ids = _source_id_values(value)
    if not ids:
        return "not recorded"
    noun = "source id" if len(ids) == 1 else "source ids"
    return f"{len(ids)} {noun}"


def _source_id_detail(value: object) -> str:
    ids = _source_id_values(value)
    if not ids:
        return "No resolved source identifiers were available for these headlines."
    visible = ", ".join(ids[:5])
    suffix = f"; {len(ids) - 5} more" if len(ids) > 5 else ""
    return f"Resolved source IDs: {visible}{suffix}."


def _abs_pct(value: float) -> str:
    return f"{abs(value):.1%}"


def _safe_divide(numerator: object, denominator: object) -> float | None:
    parsed_numerator = _float(numerator)
    parsed_denominator = _float(denominator)
    if parsed_numerator is None or parsed_denominator is None or parsed_denominator <= 0.0:
        return None
    return parsed_numerator / parsed_denominator


def _signed_notional_from_pressure(detail: Mapping[str, object]) -> float | None:
    return _signed_value_from_pressure(
        detail.get("total_notional"),
        detail.get("net_notional_pressure"),
    )


def _signed_volume_from_pressure(detail: Mapping[str, object]) -> float | None:
    return _signed_value_from_pressure(
        detail.get("total_volume"),
        detail.get("net_volume_pressure"),
    )


def _signed_value_from_pressure(total_value: object, pressure: object) -> float | None:
    parsed_total = _float(total_value)
    parsed_pressure = _float(pressure)
    if parsed_total is None or parsed_pressure is None:
        return None
    return parsed_total * parsed_pressure


def _buy_sell_notional_split(
    total_notional: object,
    signed_notional: object,
) -> tuple[float | None, float | None]:
    total = _float(total_notional)
    signed = _float(signed_notional)
    if total is None or signed is None:
        return None, None
    bounded_signed = max(min(signed, total), -total)
    buy_notional = (total + bounded_signed) / 2.0
    sell_notional = (total - bounded_signed) / 2.0
    return buy_notional, sell_notional


def _forward_fundamentals_status_label(value: object) -> str:
    status = _text(value, "missing")
    labels = {
        "ready": "Forward fundamentals ready.",
        "missing": "Forward fundamentals missing; SEC-backed fundamentals remain usable.",
        "expired": "Forward fundamentals needs refresh; SEC-backed fundamentals remain usable.",
        "not_configured": (
            "Forward fundamentals not configured; optional analyst/estimate evidence is not used."
        ),
        "provider_error": (
            "Forward fundamentals provider error; optional analyst/estimate evidence is not used."
        ),
    }
    return labels.get(status, f"Forward fundamentals status: {status}.")


def _meaning_label(row: Mapping[str, object]) -> str:
    direction = str(row.get("direction") or "").upper()
    if direction == "BULLISH":
        return "Bullish"
    if direction == "BEARISH":
        return "Bearish"
    score = _float(row.get("score_value"))
    if score is not None:
        if score > 0.0:
            return "Bullish"
        if score < 0.0:
            return "Bearish"
    return "Neutral"


def _meaning_tone(meaning: str) -> str:
    if meaning == "Bullish":
        return "pass"
    if meaning == "Bearish":
        return "block"
    return "neutral"


def _candle_label(detail: Mapping[str, object]) -> str:
    return (
        f"{_text(detail.get('latest_candle_color'), 'unknown')} "
        f"({_integer(detail.get('blue_candle_count_5d'))} blue / "
        f"{_integer(detail.get('pink_candle_count_5d'))} pink)"
    )


def _pattern_detail(detail: Mapping[str, object]) -> str:
    status = _text(detail.get("chart_pattern_status"), "status unknown")
    confidence = _text(detail.get("chart_pattern_confidence"), "confidence unknown")
    target = _money(detail.get("chart_pattern_target_level"))
    invalidation = _money(detail.get("chart_pattern_invalidation_level"))
    return f"{status}; confidence {confidence}; target {target}; invalidation {invalidation}."


def _feature_detail(lane: str) -> str:
    return {
        "buy_sell_pressure": (
            "Composite signed pressure from volume, notional, and pre-market prints."
        ),
        "block_trade_pressure": "Directional pressure from block/off-exchange focused notional.",
        "unusual_trade_activity": "Latest activity anomaly signed by notional pressure.",
        "pre_market_unusual_activity": "Pre-market anomaly signed by pre-market pressure.",
        "market_flow_trend": "Latest pressure plus change versus recent baseline pressure.",
    }.get(lane, "Selected market-flow feature value.")


def _flow_direction_label(value: object) -> str:
    parsed = _float(value)
    if parsed is None or parsed == 0.0:
        return "neutral"
    return "buy-leaning" if parsed > 0.0 else "sell-leaning"


def _flow_direction_bias(direction: str) -> str:
    if direction == "buy-leaning":
        return "bullish"
    if direction == "sell-leaning":
        return "bearish"
    return "mixed"


def _flow_direction_tone(direction: str) -> str:
    if direction == "buy-leaning":
        return "pass"
    if direction == "sell-leaning":
        return "block"
    return "neutral"


def _flow_direction_meaning(direction: str) -> str:
    if direction == "buy-leaning":
        return "large focused prints leaned buy-side, so this supports bullish pressure."
    if direction == "sell-leaning":
        return "large focused prints leaned sell-side, so this supports bearish pressure."
    return "focused prints were directionally mixed, so this is context rather than pressure."


def _block_threshold_value(detail: Mapping[str, object]) -> str:
    notional = _money(detail.get("block_notional_threshold"))
    shares = _integer(detail.get("block_size_threshold"))
    return f"{notional} / {shares} sh"


def _block_threshold_detail(detail: Mapping[str, object]) -> str:
    method = _text(detail.get("block_threshold_method"), "absolute_floor_and_5x_ticker_median")
    label = method.replace("_", " ")
    return (
        f"Block classification used {label}: absolute notional floor "
        f"{_money(detail.get('block_notional_threshold'))}, absolute share floor "
        f"{_integer(detail.get('block_size_threshold'))}, and relative detection against "
        "the ticker median print."
    )


def _most_unusual_activity_label(detail: Mapping[str, object]) -> str:
    ratios = _activity_ratios(detail)
    if not ratios:
        return "Activity"
    max_ratio = max(ratio for _, ratio in ratios)
    winners = [label for label, ratio in ratios if abs(ratio - max_ratio) < 0.01]
    if winners == ["Notional", "Share volume"]:
        return "Notional and share volume"
    if len(winners) == 1:
        return winners[0]
    return ", ".join(winners[:-1]) + f", and {winners[-1]}"


def _most_unusual_activity_ratio(detail: Mapping[str, object]) -> float | None:
    ratios = _activity_ratios(detail)
    return max((ratio for _, ratio in ratios), default=None)


def _most_unusual_activity_detail(detail: Mapping[str, object]) -> str:
    label = _most_unusual_activity_label(detail)
    normalized_label = label.lower()
    parts: list[str] = []
    if "notional" in normalized_label:
        parts.append(
            f"notional {_money(detail.get('latest_activity_notional'))} latest vs "
            f"{_money(detail.get('baseline_activity_notional_median'))} median"
        )
    if "share volume" in normalized_label:
        parts.append(
            f"share volume {_integer(detail.get('latest_activity_volume'))} latest vs "
            f"{_integer(detail.get('baseline_activity_volume_median'))} median"
        )
    if "trade count" in normalized_label:
        parts.append(
            f"trade count {_integer(detail.get('latest_activity_trade_count'))} latest vs "
            f"{_integer(detail.get('baseline_activity_trade_count_median'))} median"
        )
    if parts:
        return "; ".join(parts) + "."
    return "The highest latest-to-baseline activity ratio drove this detection."


def _activity_ratios(detail: Mapping[str, object]) -> list[tuple[str, float]]:
    candidates = [
        ("Trade count", _float(detail.get("trade_count_anomaly_ratio"))),
        ("Notional", _float(detail.get("notional_anomaly_ratio"))),
        ("Share volume", _float(detail.get("volume_anomaly_ratio"))),
    ]
    return [(label, ratio) for label, ratio in candidates if ratio is not None]


def _activity_count_detail(detail: Mapping[str, object]) -> str:
    return (
        f"{_integer(detail.get('latest_activity_trade_count'))} latest-period trades versus "
        f"{_integer(detail.get('baseline_activity_trade_count_median'))} median baseline trades."
    )


def _activity_notional_detail(detail: Mapping[str, object]) -> str:
    return (
        f"{_money(detail.get('latest_activity_notional'))} latest-period notional versus "
        f"{_money(detail.get('baseline_activity_notional_median'))} median baseline notional."
    )


def _activity_volume_detail(detail: Mapping[str, object]) -> str:
    return (
        f"{_integer(detail.get('latest_activity_volume'))} latest-period shares versus "
        f"{_integer(detail.get('baseline_activity_volume_median'))} median baseline shares."
    )


def _activity_timing_value(lane: str) -> str:
    if lane == "pre_market_unusual_activity":
        return "Pre-market activity period"
    return "Latest activity period"


def _activity_timing_detail(lane: str) -> str:
    if lane == "pre_market_unusual_activity":
        return (
            "This timing-specific lane checks pre-market prints, then compares that "
            "activity with the ticker baseline."
        )
    return (
        "This is not a clock-time anomaly; it compares the latest analyzed activity "
        "period with the ticker's recent baseline."
    )


def _unusual_activity_identification_detail(lane: str) -> str:
    if lane == "pre_market_unusual_activity":
        return (
            "The agent checks pre-market trade count, dollar notional, and share volume "
            "against this ticker's recent pre-market median baseline."
        )
    return (
        "The agent checks latest-period trade count, dollar notional, and share volume "
        "against this ticker's recent median baseline."
    )


def _activity_block_role_value(detail: Mapping[str, object]) -> str:
    return (
        f"{_integer(detail.get('block_count'))} block / "
        f"{_integer(detail.get('off_exchange_count'))} off-exchange"
    )


def _activity_block_role_detail() -> str:
    return (
        "This unusual-trade lane flags activity intensity. It is not the separate "
        "block-trade signal; use block_trade_pressure for block/TRF/off-exchange "
        "directional pressure."
    )


def _activity_pressure_sentence(detail: Mapping[str, object], pressure: object) -> str:
    signed = _signed_value_from_pressure(detail.get("latest_activity_notional"), pressure)
    direction = _flow_direction_label(signed)
    return (
        f"detected-period signed notional was {_signed_money(signed)} "
        f"({_pct(pressure)}), which is {direction}. "
    )


def _pre_market_pressure_sentence(detail: Mapping[str, object], pressure: object) -> str:
    signed = _signed_value_from_pressure(detail.get("latest_pre_market_notional"), pressure)
    direction = _flow_direction_label(signed)
    return (
        f"pre-market signed notional was {_signed_money(signed)} "
        f"({_pct(pressure)}), which is {direction}. "
    )


def _activity_pressure_detail(detail: Mapping[str, object], pressure: object) -> str:
    latest_notional = detail.get("latest_activity_notional")
    signed = _signed_value_from_pressure(latest_notional, pressure)
    buy_notional, sell_notional = _buy_sell_notional_split(latest_notional, signed)
    direction = _flow_direction_label(signed)
    return (
        f"Signed notional divided by latest-period notional: {_signed_money(signed)} / "
        f"{_money(latest_notional)} = {_pct(pressure)}. This implies inferred buy notional "
        f"{_money(buy_notional)} versus sell notional {_money(sell_notional)} "
        f"(buy-side share {_notional_share_pct(buy_notional, latest_notional)}; "
        f"sell-side share {_notional_share_pct(sell_notional, latest_notional)}) from "
        f"trade-signing inference; {direction} pressure means "
        f"{_activity_pressure_meaning(direction)}"
    )


def _pre_market_count_detail(detail: Mapping[str, object]) -> str:
    return (
        f"{_integer(detail.get('latest_pre_market_trade_count'))} latest pre-market trades "
        f"versus {_integer(detail.get('baseline_pre_market_trade_count_median'))} "
        "median pre-market baseline trades."
    )


def _pre_market_notional_detail(detail: Mapping[str, object]) -> str:
    return (
        f"{_money(detail.get('latest_pre_market_notional'))} latest pre-market notional "
        f"versus {_money(detail.get('baseline_pre_market_notional_median'))} "
        "median pre-market baseline."
    )


def _pre_market_volume_detail(detail: Mapping[str, object]) -> str:
    return (
        f"{_integer(detail.get('latest_pre_market_volume'))} latest pre-market shares "
        f"versus {_integer(detail.get('baseline_pre_market_volume_median'))} "
        "median pre-market baseline shares."
    )


def _pre_market_pressure_detail(detail: Mapping[str, object], pressure: object) -> str:
    latest_notional = detail.get("latest_pre_market_notional")
    signed = _signed_value_from_pressure(latest_notional, pressure)
    buy_notional, sell_notional = _buy_sell_notional_split(latest_notional, signed)
    direction = _flow_direction_label(signed)
    return (
        f"Signed pre-market notional divided by latest pre-market notional: "
        f"{_signed_money(signed)} / {_money(latest_notional)} = {_pct(pressure)}. "
        f"This implies inferred buy notional {_money(buy_notional)} versus sell notional "
        f"{_money(sell_notional)} (buy-side share {_notional_share_pct(buy_notional, latest_notional)}; "
        f"sell-side share {_notional_share_pct(sell_notional, latest_notional)}) from "
        f"trade-signing inference; {direction} pressure means "
        f"{_activity_pressure_meaning(direction)}"
    )


def _notional_share_pct(value: object, total: object) -> str:
    parsed_value = _float(value)
    parsed_total = _float(total)
    if parsed_value is None or parsed_total in (None, 0.0):
        return "n/a"
    return f"{parsed_value / parsed_total:.1%}"


def _activity_pressure_meaning(direction: str) -> str:
    if direction == "buy-leaning":
        return (
            "inferred buyer-side notional dominated the detected period, so this supports "
            "bullish pressure."
        )
    if direction == "sell-leaning":
        return (
            "inferred seller-side notional dominated the detected period, so this supports "
            "bearish pressure."
        )
    return (
        "inferred buyer-side and seller-side notional were balanced, so this is context "
        "rather than directional pressure."
    )


def _direction_sort_value(direction: str) -> int:
    return {"BULLISH": 2, "NEUTRAL": 1, "BEARISH": 0}.get(direction.upper(), 1)


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
