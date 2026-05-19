from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd
from market_flow.features import market_flow_feature_frame
from pit.loader import PITLoader
from signals.abnormal_volume import abnormal_volume_frame
from signals.fundamentals import fundamental_factor_frame
from signals.insider import insider_factor_frame
from signals.institutional import institutional_factor_frame
from signals.news import news_factor_frame
from signals.technical_analysis import technical_analysis_frame

REPO_ROOT = Path(__file__).resolve().parents[3]
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
}


def enrich_signal_rows_with_evidence(
    rows: Sequence[Mapping[str, object]],
    *,
    loader: Any | None = None,
) -> list[dict[str, object]]:
    if not rows:
        return []
    active_loader = loader or PITLoader(
        parquet_root=DEFAULT_PARQUET_ROOT,
        manifest_root=DEFAULT_MANIFEST_ROOT,
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
    if "abnormal_volume" in lanes:
        frames["abnormal_volume"] = _safe_frame(abnormal_volume_frame, as_of, tickers, loader)
    if "technical_analysis" in lanes:
        frames["technical_analysis"] = _safe_frame(technical_analysis_frame, as_of, tickers, loader)
    if "fundamentals" in lanes:
        frames["fundamentals"] = _safe_frame(fundamental_factor_frame, as_of, tickers, loader)
    if "insider" in lanes:
        frames["insider"] = _safe_frame(insider_factor_frame, as_of, tickers, loader)
    if "institutional" in lanes:
        frames["institutional"] = _safe_frame(institutional_factor_frame, as_of, tickers, loader)
    if "news" in lanes:
        frames["news"] = _safe_frame(news_factor_frame, as_of, tickers, loader)
    if lanes & MARKET_FLOW_LANES:
        frames["market_flow"] = _safe_frame(market_flow_feature_frame, as_of, tickers, loader)
    return frames


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
    score = _float(row.get("score_value")) or 0.0
    direction = "bullish" if score > 0.0 else "bearish"
    headline = (
        f"{row['ticker']} triggered abnormal volume because latest volume was "
        f"{_ratio_label(ratio)} its median baseline and the latest price move was "
        f"{_pct(latest_return)}."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            f"The signal is {direction}: high volume on an up day is accumulation pressure; "
            "high volume on a down day is distribution pressure. The displayed score is a "
            "cross-sectional z-score versus the current universe."
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
                "Median prior-window volume.",
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
                "Price move on the same trigger bar.",
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
    headline = (
        f"{row['ticker']} technical setup is {setup}; latest close is "
        f"{_money(detail.get('latest_close'))}, RSI is {_number(detail.get('rsi14'))}, "
        f"and the model score is {_number(detail.get('technical_analysis_score'))}."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "The score blends trend, momentum, volume confirmation, relative strength, "
            "trade pressure, candle regime, pattern evidence, and volatility risk. "
            "Positive values help bullish review; negative values add caution."
        ),
        cards=[
            _card("Setup", setup.title(), "Primary chart setup classification."),
            _card(
                "Trend",
                _number(detail.get("trend_score")),
                "SMA alignment and trend direction.",
                _score_tone(detail.get("trend_score")),
            ),
            _card(
                "Momentum",
                _number(detail.get("momentum_score")),
                "RSI/MACD momentum contribution.",
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
        ],
    )


def _fundamentals_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    headline = (
        f"{row['ticker']} fundamentals score reflects net margin {_pct(detail.get('net_margin'))}, "
        f"free-cash-flow margin {_pct(detail.get('fcf_margin'))}, and leverage "
        f"{_pct(detail.get('leverage'))}."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "The factor ranks profitability and cash generation positively, while lower "
            "balance-sheet leverage scores better."
        ),
        cards=[
            _card("Net margin", _pct(detail.get("net_margin")), "Net income divided by revenue."),
            _card(
                "FCF margin", _pct(detail.get("fcf_margin")), "Free cash flow divided by revenue."
            ),
            _card(
                "Leverage",
                _pct(detail.get("leverage")),
                "Total liabilities divided by total assets.",
            ),
            _card(
                "Composite score",
                _number(detail.get("composite_score")),
                "Cross-sectional fundamentals score.",
            ),
        ],
    )


def _insider_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    headline = (
        f"{row['ticker']} insider signal is based on net transaction value of "
        f"{_money(detail.get('net_transaction_value'))} across "
        f"{_integer(detail.get('directional_transactions'))} directional Form 4 transactions."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "Open-market purchases add positive value; sales subtract value. The lane then "
            "normalizes net value across the current universe."
        ),
        cards=[
            _card("Buy value", _money(detail.get("buy_value")), "Estimated purchase value."),
            _card("Sell value", _money(detail.get("sell_value")), "Estimated sale value."),
            _card(
                "Net value",
                _money(detail.get("net_transaction_value")),
                "Purchases minus sales.",
                _money_tone(detail.get("net_transaction_value")),
            ),
            _card(
                "Net shares", _integer(detail.get("net_shares")), "Signed shares bought minus sold."
            ),
            _card(
                "Transactions",
                _integer(detail.get("directional_transactions")),
                "Directional Form 4 transactions counted.",
            ),
            _card(
                "Filers", _integer(detail.get("unique_filers")), "Unique insiders/filers counted."
            ),
        ],
    )


def _institutional_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    headline = (
        f"{row['ticker']} institutional signal is based on quarterly share change of "
        f"{_integer(detail.get('total_change_from_prev_quarter'))} shares across "
        f"{_integer(detail.get('holder_count'))} tracked holders."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "Positive quarterly change suggests accumulation; negative change "
            "suggests distribution."
        ),
        cards=[
            _card(
                "Quarter end",
                _text(detail.get("quarter_end_date"), "unknown"),
                "13F reporting quarter.",
            ),
            _card(
                "Holder count",
                _integer(detail.get("holder_count")),
                "Tracked institutional holders.",
            ),
            _card(
                "Shares held",
                _integer(detail.get("total_shares_held")),
                "Total shares in mapped 13F rows.",
            ),
            _card(
                "Quarterly change",
                _integer(detail.get("total_change_from_prev_quarter")),
                "Change from previous quarter.",
                _money_tone(detail.get("total_change_from_prev_quarter")),
            ),
            _card(
                "Change ratio",
                _pct(detail.get("change_ratio")),
                "Quarterly change divided by total shares held.",
            ),
            _card(
                "Institutional score",
                _number(detail.get("institutional_score")),
                "Universe-normalized accumulation score.",
            ),
        ],
    )


def _news_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    headline = (
        f"{row['ticker']} news signal counted {_integer(detail.get('headline_count'))} "
        f"ticker-tagged headline(s), with {_integer(detail.get('positive_count'))} positive "
        f"and {_integer(detail.get('negative_count'))} negative cue(s)."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=(
            "This is a headline-level context lane; stronger article/email analysis "
            "lives on candidate pages."
        ),
        cards=[
            _card(
                "Headlines",
                _integer(detail.get("headline_count")),
                "Ticker-tagged headlines in the lookback window.",
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
        ],
    )


def _market_flow_evidence(
    row: Mapping[str, object],
    detail: Mapping[str, object],
    as_of: date,
) -> dict[str, object]:
    lane = str(row["lane_key"])
    selected = _number(detail.get(lane))
    headline = (
        f"{row['ticker']} {str(row['lane']).lower()} signal used "
        f"{_integer(detail.get('trade_count'))} delayed trade print(s), "
        f"{_money(detail.get('total_notional'))} total notional, and selected feature "
        f"score {selected}."
    )
    return _detail_payload(
        row,
        as_of,
        headline=headline,
        detail=LANE_EXPLANATIONS.get(
            lane, "Market-flow feature reconstructed from delayed trades."
        ),
        cards=[
            _card(
                "Selected feature", selected, _feature_detail(lane), _score_tone(detail.get(lane))
            ),
            _card(
                "Trade count", _integer(detail.get("trade_count")), "Delayed trade prints counted."
            ),
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
        ],
    )


def _fallback_evidence(
    row: Mapping[str, object],
    as_of: date,
    *,
    reconstruction_error: str | None = None,
) -> dict[str, object]:
    lane = str(row["lane_key"])
    detail = LANE_EXPLANATIONS.get(
        lane,
        (
            "Detailed metric reconstruction is not available for this lane yet; "
            "use provenance and reason codes."
        ),
    )
    cards = [
        _card("Score", str(row["score"]), "Signed signal strength."),
        _card("Reason", str(row["reason_codes_label"]), "Recorded reason code."),
        _card(
            "Source as-of",
            _timestamp_label(row.get("timestamp_as_of")),
            "Latest source timestamp used by the signal.",
        ),
        _card(
            "Confidence", f"{row['confidence_pct']}%", "Lane confidence configured for runtime."
        ),
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
            f"{row['ticker']} {row['lane']} signal was recorded from "
            f"{row['source']} with score {row['score']}."
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


def _pct(value: object) -> str:
    parsed = _float(value)
    return "n/a" if parsed is None else f"{parsed:+.1%}"


def _ratio_label(value: object) -> str:
    parsed = _float(value)
    return "n/a" if parsed is None else f"{parsed:.2f}x"


def _integer(value: object) -> str:
    parsed = _float(value)
    return "n/a" if parsed is None else f"{round(parsed):,}"


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


def _text(value: object, default: str) -> str:
    if value is None or value is pd.NA or value is pd.NaT:
        return default
    text = " ".join(str(value).split())
    return text if text and text.lower() not in {"nan", "none", "nat"} else default


def _tone(value: object, threshold: float) -> str:
    parsed = _float(value)
    if parsed is None:
        return "neutral"
    return "pass" if parsed >= threshold else "warn"


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


def _direction_sort_value(direction: str) -> int:
    return {"BULLISH": 2, "NEUTRAL": 1, "BEARISH": 0}.get(direction.upper(), 1)


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
