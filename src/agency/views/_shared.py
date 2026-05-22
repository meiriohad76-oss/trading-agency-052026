"""Shared constants and utility helpers for dashboard view modules."""
from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy.exc import SQLAlchemyError

from agency.api.candidates import RuntimeCandidateTimelineUnavailable, runtime_candidate_timeline
from agency.api.reports import RuntimeSelectionReportsUnavailable, runtime_selection_reports
from agency.api.risk import RuntimeRiskDecisionsUnavailable, runtime_risk_decisions
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import list_candidate_lifecycle_events
from agency.runtime.artifact_fallbacks import runtime_lifecycle_event_artifacts

REPO_ROOT = Path(__file__).resolve().parents[2]
EMAIL_EVENTS_PATH = REPO_ROOT / "research" / "data" / "parquet" / "subscription_emails.parquet"
NEWS_RSS_PATH = REPO_ROOT / "research" / "data" / "parquet" / "news_rss.parquet"
PRICES_DAILY_ROOT = REPO_ROOT / "research" / "data" / "parquet" / "prices_daily"
ACTIONABLE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER", "WATCH", "HOLD"}
OPEN_RISK_DECISIONS = {"ALLOW", "WARN"}
DEGRADED_SOURCE_STATUSES = {"DEGRADED", "STALE", "UNAVAILABLE", "RATE_LIMITED"}
DEGRADED_FRESHNESS = {"AGING", "STALE", "UNAVAILABLE"}
REFRESHABLE_MASSIVE_LANES = {
    "massive_daily_bars": "Refresh Daily Bars",
    "prices_daily": "Refresh Daily Bars",
    "daily-market-bars": "Refresh Daily Bars",
    "massive_live_trade_slices": "Refresh Live Trade Slices",
    "massive-stock-trades": "Refresh Live Trade Slices",
    "stock_trades": "Refresh Live Trade Slices",
    "massive_premarket_trade_slices": "Refresh Premarket Trade Slices",
    "massive_block_trade_feed": "Refresh Block Trade Feed",
    "massive_options_flow": "Refresh Options Flow",
    "massive_reference": "Refresh Massive Reference",
    "massive_backtest_trade_tape": "Refresh Backtest Trade Tape",
}
REFRESHABLE_DATASET_TO_LANE = {
    "prices_daily": "massive_daily_bars",
    "daily-market-bars": "massive_daily_bars",
    "massive-stock-trades": "massive_live_trade_slices",
    "stock_trades": "massive_live_trade_slices",
}
FINAL_SELECTION_REPORT_LIMIT = 1000
SIGNALS_REPORT_LIMIT = 300
SIGNALS_RENDER_LIMIT = 50
SIGNALS_CONTEXT_CACHE_SECONDS = 300.0
BROKER_STATUS_CONTEXT_CACHE_SECONDS = 30.0
MARKET_REGIME_CONTEXT_CACHE_SECONDS = 300.0
DASHBOARD_HEALTH_QUERY_TIMEOUT_SECONDS = 5.0
DASHBOARD_LIFECYCLE_QUERY_TIMEOUT_SECONDS = 1.0
LIVE_PIT_CYCLE_PREFIX = "live-pit-"
LIVE_READY_CYCLE_PREFIX = "live-ready-"
LIVE_SELECTION_CYCLE_PREFIXES = (LIVE_PIT_CYCLE_PREFIX, LIVE_READY_CYCLE_PREFIX)
MAX_FULL_CYCLE_LABEL_LENGTH = 28
CYCLE_LABEL_SUFFIX_LENGTH = 25
MIN_BRIEF_SOURCE_COUNT = 2
MIN_BRIEF_CONFIRMED_COUNT = 1
MIN_EMAIL_PAIR_SCORE = 2
EMAIL_FEED_SOURCE_ID_PARTS = 5
EMAIL_FEED_SOURCE_ID_CORE_PARTS = 4
HUMAN_LIST_PAIR_COUNT = 2
EMAIL_LINKED_STATUS_PRIORITY = {
    "article_analyzed": 50,
    "article_analyzed_deterministic_fallback": 48,
    "article_fetch_failed": 40,
    "article_fetch_limited": 30,
    "non_article_link": 25,
    "no_allowed_article_link": 20,
    "article_analyzed_no_ticker_match": 15,
    "not_requested": 10,
}
EMAIL_ANALYZED_STATUSES = {
    "article_analyzed",
    "article_analyzed_deterministic_fallback",
}
EMAIL_ASSET_EXTENSIONS = {
    ".avif",
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".png",
    ".svg",
    ".webp",
}
EMAIL_ASSET_DOMAIN_PREFIXES = ("assets.", "images.", "img.", "static.", "staticx.")
EMAIL_HEADLINE_FOCUS_RE = re.compile(r"(?: - |Email:\s+)\$?([A-Z]{1,5})(?=\s*:|\s+)")
EMAIL_EVENT_LABELS = {
    "sa_analyst_article": "analyst article",
    "sa_earnings_or_transcript": "earnings/transcript alert",
    "sa_news": "news alert",
    "sa_quant_rating_change": "quant rating change",
    "zacks_analyst_recommendation": "analyst recommendation",
    "zacks_news": "news alert",
    "zacks_rank_change": "rank change",
    "zacks_rating_change": "rating change",
}


async def _dashboard_selection_reports(
    *,
    ticker: str | None = None,
    limit: int = FINAL_SELECTION_REPORT_LIMIT,
    raise_on_unavailable: bool = False,
) -> list[dict[str, object]]:
    try:
        try:
            if ticker is None:
                return await runtime_selection_reports(
                    limit=limit,
                    validate_payloads=False,
                )
            return await runtime_selection_reports(
                ticker=ticker,
                limit=limit,
                validate_payloads=False,
            )
        except TypeError as exc:
            if "validate_payloads" not in str(exc):
                raise
            if ticker is None:
                return await runtime_selection_reports(limit=limit)
            return await runtime_selection_reports(ticker=ticker, limit=limit)
    except RuntimeSelectionReportsUnavailable:
        if raise_on_unavailable:
            raise
        return []

async def _dashboard_risk_decisions(
    *,
    ticker: str | None = None,
    limit: int = FINAL_SELECTION_REPORT_LIMIT,
    raise_on_unavailable: bool = False,
) -> list[dict[str, object]]:
    try:
        try:
            if ticker is None:
                return await runtime_risk_decisions(
                    limit=limit,
                    validate_payloads=False,
                )
            return await runtime_risk_decisions(
                ticker=ticker,
                limit=limit,
                validate_payloads=False,
            )
        except TypeError as exc:
            if "validate_payloads" not in str(exc):
                raise
            if ticker is None:
                return await runtime_risk_decisions(limit=limit)
            return await runtime_risk_decisions(ticker=ticker, limit=limit)
    except RuntimeRiskDecisionsUnavailable:
        if raise_on_unavailable:
            raise
        return []

async def _dashboard_candidate_timeline(
    *,
    ticker: str,
    cycle_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    try:
        if cycle_id is None:
            return await runtime_candidate_timeline(ticker=ticker, limit=limit)
        return await runtime_candidate_timeline(
            ticker=ticker,
            cycle_id=cycle_id,
            limit=limit,
        )
    except RuntimeCandidateTimelineUnavailable:
        return []

async def _lifecycle_events_for_reports(
    reports: Sequence[Mapping[str, object]],
    readiness: Mapping[str, object],
    *,
    event_type: str,
    limit_per_ticker: int,
) -> list[dict[str, object]]:
    cycle_id = readiness.get("cycle_id")
    if not isinstance(cycle_id, str) or not cycle_id:
        return []
    tickers = sorted(
        {
            str(report["ticker"])
            for report in reports
            if report.get("cycle_id") == cycle_id
        }
    )
    if not tickers:
        return []
    limit = max(len(tickers) * limit_per_ticker, limit_per_ticker)
    try:
        async with get_session() as session:
            events = await asyncio.wait_for(
                list_candidate_lifecycle_events(
                    session,
                    cycle_id=cycle_id,
                    limit=limit,
                ),
                timeout=DASHBOARD_LIFECYCLE_QUERY_TIMEOUT_SECONDS,
            )
    except (MissingDatabaseConfigurationError, SQLAlchemyError, RuntimeError, TimeoutError, TypeError, OSError):
        events = runtime_lifecycle_event_artifacts(cycle_id=cycle_id, limit=limit)
        if not events:
            try:
                events = await asyncio.wait_for(
                    _timeline_lifecycle_events_for_reports(
                        tickers=tickers,
                        cycle_id=cycle_id,
                        limit=limit_per_ticker,
                    ),
                    timeout=DASHBOARD_LIFECYCLE_QUERY_TIMEOUT_SECONDS,
                )
            except (RuntimeError, TimeoutError, TypeError, OSError, SQLAlchemyError):
                events = []
    ticker_set = set(tickers)
    return [
        event
        for event in events
        if event.get("event_type") == event_type
        and str(event.get("ticker", "")).upper() in ticker_set
    ]

async def _timeline_lifecycle_events_for_reports(
    *,
    tickers: Sequence[str],
    cycle_id: str,
    limit: int,
) -> list[dict[str, object]]:
    timelines = []
    for ticker in tickers:
        timelines.append(
            await _dashboard_candidate_timeline(ticker=ticker, cycle_id=cycle_id, limit=limit)
        )
    return [
        event
        for timeline in timelines
        for event in timeline
    ]

def _latest_selection_cycle_id(
    reports: Sequence[Mapping[str, object]],
) -> str | None:
    live_cycle_id = _latest_cycle_id_by_timestamp(
        [
            report
            for report in reports
            if (_clean_text(report.get("cycle_id")) or "").startswith(
                LIVE_SELECTION_CYCLE_PREFIXES
            )
        ]
    )
    if live_cycle_id is not None:
        return live_cycle_id
    fallback_cycle_id = _latest_cycle_id_by_timestamp(reports)
    if fallback_cycle_id is not None:
        return fallback_cycle_id
    return None


def _latest_cycle_id_by_timestamp(
    reports: Sequence[Mapping[str, object]],
) -> str | None:
    best_report: Mapping[str, object] | None = None
    best_key: tuple[datetime, int] | None = None
    for index, report in enumerate(reports):
        cycle_id = _clean_text(report.get("cycle_id"))
        if cycle_id is None:
            continue
        key = (_cycle_timestamp(report), -index)
        if best_key is None or key > best_key:
            best_report = report
            best_key = key
    if best_report is None:
        return None
    return _clean_text(best_report.get("cycle_id"))


def _cycle_timestamp(report: Mapping[str, object]) -> datetime:
    for key in ("generated_at", "as_of", "timestamp_as_of", "created_at"):
        value = report.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return datetime.min.replace(tzinfo=UTC)

def _selection_reports_for_cycle(
    reports: Sequence[Mapping[str, object]],
    cycle_id: str | None,
) -> list[Mapping[str, object]]:
    if cycle_id is None:
        return []
    return [report for report in reports if report.get("cycle_id") == cycle_id]

def _active_cycle_reports(
    reports: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    cycle_id = _latest_selection_cycle_id(reports)
    return _selection_reports_for_cycle(reports, cycle_id)

def _risk_decisions_for_reports(
    risk_decisions: Sequence[Mapping[str, object]],
    reports: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    report_keys = {_runtime_payload_key(report) for report in reports}
    return [
        decision
        for decision in risk_decisions
        if _runtime_payload_key(decision) in report_keys
    ]

def _human_list(values: Sequence[str]) -> str:
    cleaned = [item for item in values if item]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == HUMAN_LIST_PAIR_COUNT:
        return f"{cleaned[0]} and {cleaned[1]}"
    return ", ".join(cleaned[:-1]) + f", and {cleaned[-1]}"

def _service_label(value: str) -> str:
    cleaned = value.replace("-email", "").replace("_", " ").replace("-", " ").strip()
    if cleaned.lower() == "seeking alpha email":
        return "Seeking Alpha"
    return cleaned.title() if cleaned else "Email"

def _sorted_signals(signals: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return sorted(
        signals,
        key=lambda signal: abs(_numeric_value(signal.get("score_value"))),
        reverse=True,
    )

def _numeric_value(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    return 0.0

def _score_text(signal: Mapping[str, object]) -> str:
    score = _float_field(signal, "score")
    if score > 0:
        bias = "bullish"
    elif score < 0:
        bias = "bearish"
    else:
        bias = "neutral"
    return f"{score:+.2f} {bias}"

def _reason_summary(reason_code: str) -> str:
    summaries = {
        "abnormal_volume_bullish": "Volume activity is constructive.",
        "abnormal_volume_bearish": "Volume activity is negative.",
        "activity_alerts_bullish": "Unusual activity alerts are constructive.",
        "activity_alerts_bearish": "Unusual activity alerts are negative.",
        "bearish_action_not_enabled": "Bearish actions are not enabled in this runtime.",
        "below_actionability_threshold": "Signal is below the actionability threshold.",
        "block_trade_pressure_bullish": "Block-trade pressure is constructive.",
        "block_trade_pressure_bearish": "Block-trade pressure is negative.",
        "buy_sell_pressure_bullish": "Buy/sell pressure is constructive.",
        "buy_sell_pressure_bearish": "Buy/sell pressure is negative.",
        "duplicate_signal_source": "Duplicate source was ignored.",
        "fundamentals_bullish": "Fundamental metrics are constructive.",
        "fundamentals_bearish": "Fundamental metrics are negative.",
        "insider_bullish": "Insider activity is constructive.",
        "insider_bearish": "Insider activity is negative.",
        "institutional_bullish": "Institutional positioning is constructive.",
        "institutional_bearish": "Institutional positioning is negative.",
        "insufficient_confirmed_sources": "Needs more confirmed corroboration.",
        "insufficient_independent_sources": "Needs more independent source coverage.",
        "market_flow_trend_bullish": "Market-flow trend is improving.",
        "market_flow_trend_bearish": "Market-flow trend is deteriorating.",
        "news_bullish": "News flow is constructive.",
        "news_bearish": "News flow is negative.",
        "not_actionable": "Useful context, but not actionable by itself.",
        "options_anomaly_bullish": "Options anomaly activity is constructive.",
        "options_anomaly_bearish": "Options anomaly activity is negative.",
        "options_flow_bullish": "Options flow is constructive.",
        "options_flow_bearish": "Options flow is negative.",
        "prepost_bullish": "Pre/post-market activity is constructive.",
        "prepost_bearish": "Pre/post-market activity is negative.",
        "pre_market_unusual_activity_bullish": "Pre-market unusual activity is constructive.",
        "pre_market_unusual_activity_bearish": "Pre-market unusual activity is negative.",
        "requires_confirmed_corroboration": "Inferred signal needs confirmed corroboration.",
        "sector_momentum_bullish": "Sector momentum is constructive.",
        "sector_momentum_bearish": "Sector momentum is negative.",
        "signal_strength_below_threshold": "Combined signal strength is below threshold.",
        "source_unavailable": "Source was unavailable.",
        "stale_evidence": "Evidence needs refresh, so it is context only.",
        "subscription_thesis_context_only": "Subscription article thesis is context only.",
        "technical_analysis_bullish": "Technical setup is constructive.",
        "technical_analysis_bearish": "Technical setup is negative.",
        "technical_analysis_neutral": "Technical setup is mixed.",
        "technical_pattern_bearish": "Named chart pattern is bearish.",
        "technical_pattern_bullish": "Named chart pattern is bullish.",
        "technical_pattern_confirmed": "Named chart pattern is confirmed.",
        "technical_pattern_cup_and_handle": "Cup-and-handle pattern is active.",
        "technical_pattern_double_bottom": "Double-bottom pattern is active.",
        "technical_pattern_double_top": "Double-top pattern is active.",
        "technical_pattern_forming": "Named chart pattern is still forming.",
        "technical_pattern_head_and_shoulders": "Head-and-shoulders pattern is active.",
        "technical_pattern_inverse_head_and_shoulders": (
            "Inverse head-and-shoulders pattern is active."
        ),
        "technical_setup_breakout": "Chart setup is a breakout.",
        "technical_setup_distribution": "Chart setup shows distribution risk.",
        "technical_setup_failed_breakout": "Chart setup shows a failed breakout.",
        "technical_setup_overextended": "Chart setup is overextended.",
        "technical_setup_pullback_to_support": "Chart setup is pulling back to support.",
        "technical_setup_range_bound": "Chart setup is range-bound.",
        "technical_setup_trend_continuation": "Chart setup shows trend continuation.",
        "unusual_trade_activity_bullish": "Unusual trade activity is constructive.",
        "unusual_trade_activity_bearish": "Unusual trade activity is negative.",
        "zero_confidence": "Signal confidence is zero.",
    }
    return summaries.get(reason_code, f"{_label_text(reason_code)}.")

def _is_actionable_candidate(candidate: Mapping[str, object]) -> bool:
    return str(candidate["action"]) in ACTIONABLE_ACTIONS and candidate["gate_status"] != "BLOCK"

def _human_review_index(
    review_events: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str, str], Mapping[str, object]]:
    indexed: dict[tuple[str, str, str], Mapping[str, object]] = {}
    for event in review_events:
        if not _is_human_review_event(event):
            continue
        key = _human_review_key(event)
        if all(key) and key not in indexed:
            indexed[key] = event
    return indexed

def _is_human_review_event(event: Mapping[str, object]) -> bool:
    payload = _mapping_field(event, "payload")
    event_type = str(event.get("event_type") or "").upper()
    return event_type == "HUMAN_REVIEW" or "review_decision" in payload

def _runtime_payload_key(payload: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(payload.get("cycle_id", "")),
        str(payload.get("ticker", "")),
        str(payload.get("as_of", "")),
    )

def _matching_payload(
    payloads: Sequence[Mapping[str, object]],
    reference: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if reference is None:
        return None
    key = _runtime_payload_key(reference)
    if not all(key):
        return None
    return next((payload for payload in payloads if _runtime_payload_key(payload) == key), None)

def _human_review_key(event: Mapping[str, object]) -> tuple[str, str, str]:
    payload = event.get("payload", {})
    as_of = ""
    if isinstance(payload, Mapping):
        as_of = str(payload.get("as_of", ""))
    return (
        str(event.get("cycle_id", "")),
        str(event.get("ticker", "")),
        as_of,
    )

def _human_review_summary(event: Mapping[str, object] | None) -> dict[str, str]:
    if event is None:
        return {
            "decision": "Pending",
            "status_class": "neutral",
            "reason": "no human review recorded",
            "review_reason": "",
            "notes": "",
            "event_time": "None",
        }
    payload = _mapping_field(event, "payload")
    decision = str(payload.get("review_decision", "RECORDED"))
    status = str(event["status"])
    return {
        "decision": _label_text(decision),
        "status_class": _human_review_status_class(status),
        "reason": str(event["reason"]),
        "review_reason": _clean_text(payload.get("review_reason")) or "",
        "notes": _clean_text(payload.get("notes")) or "",
        "event_time": str(event["event_time"]),
    }

def _source_is_degraded(source: Mapping[str, object]) -> bool:
    return (
        str(source["status"]) in DEGRADED_SOURCE_STATUSES
        or str(source["freshness"]) in DEGRADED_FRESHNESS
    )

def _label_text(value: str) -> str:
    return value.replace("_", " ").title()

def _clip_text(value: str, max_chars: int) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."

def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = " ".join(str(value).split())
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    return text

def _row_text(
    row: Mapping[str, object] | None,
    key: str,
    default: str = "",
) -> str:
    if row is None:
        return default
    return _clean_text(row.get(key)) or default

def _format_timestamp_label(value: object) -> str:
    timestamp = _parse_dashboard_timestamp(value)
    if timestamp is None:
        return "Time unknown"
    return timestamp.strftime("%Y-%m-%d %H:%M UTC")

def _format_timestamp_or_text(value: object, default: str = "not recorded") -> str:
    text = _clean_text(value)
    if text is None:
        return default
    timestamp = _parse_dashboard_timestamp(text)
    if timestamp is None:
        return text
    return timestamp.strftime("%Y-%m-%d %H:%M UTC")

def _timestamp_sort_value(value: object) -> float:
    timestamp = _parse_dashboard_timestamp(value)
    return timestamp.timestamp() if timestamp is not None else 0.0

def _parse_dashboard_timestamp(value: object) -> datetime | None:
    text = _clean_text(value)
    if text is None or text.lower() == "unknown":
        return None
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)

def _dedupe_text(value: object) -> str:
    text = _clean_text(value)
    if text is None:
        return ""
    return re.sub(r"\s+", " ", text).strip().casefold()

def _source_id_core(value: object) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    if text.startswith("subscription_email:"):
        return text.removeprefix("subscription_email:")
    parts = text.split(":")
    if len(parts) >= EMAIL_FEED_SOURCE_ID_PARTS:
        return ":".join(parts[:EMAIL_FEED_SOURCE_ID_CORE_PARTS])
    return text

def _same_pair_text(left: object, right: object) -> bool:
    left_text = _pair_text(left)
    right_text = _pair_text(right)
    return left_text is not None and left_text == right_text

def _pair_text(value: object) -> str | None:
    text = _clean_text(value)
    return text.casefold() if text is not None else None

def _plural(label: str, count: int) -> str:
    return label if count == 1 else f"{label}s"

def _short_cycle_label(cycle_id: str | None) -> str:
    if cycle_id is None:
        return "None"
    if len(cycle_id) <= MAX_FULL_CYCLE_LABEL_LENGTH:
        return cycle_id
    return f"...{cycle_id[-CYCLE_LABEL_SUFFIX_LENGTH:]}"

def _decision_class(decision: str) -> str:
    if decision == "ALLOW":
        return "pass"
    if decision == "WARN":
        return "warn"
    return "block"

def _direction_class(direction: str) -> str:
    if direction == "BULLISH":
        return "pass"
    if direction == "BEARISH":
        return "block"
    return "neutral"

def _human_review_status_class(status: str) -> str:
    if status == "PASSED":
        return "pass"
    if status == "WARN":
        return "warn"
    if status == "BLOCKED":
        return "block"
    return "neutral"

def _reason_text(payload: Mapping[str, object]) -> str:
    reasons = _string_list(payload, "reason_codes")
    return ", ".join(reasons) if reasons else "none"

def _string_list(payload: Mapping[str, object], key: str) -> list[str]:
    return [str(item) for item in _list_field(payload, key)]

def _list_field(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return value

def _mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return cast(Mapping[str, object], value)

def _mapping_list_field(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    return [cast(Mapping[str, object], item) for item in _list_field(payload, key)]

def _optional_float_field(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)

def _float_field(payload: Mapping[str, object], key: str) -> float:
    value = payload[key]
    if not isinstance(value, int | float):
        raise TypeError(f"{key} must be numeric")
    return float(value)

def _int_field(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return value

def _percent(payload: Mapping[str, object], key: str) -> int:
    return round(_float_field(payload, key) * 100)

def _env_bool_text(name: str, *, default: bool = False) -> bool:
    load_dotenv()
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

def _now_utc_text() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")

_SECONDS_TOKEN_RE = re.compile(r"\b(\d{3,})s\b")
_ISO_TIMESTAMP_TOKEN_RE = re.compile(
    r"(?<!\d)\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})(?!\d)"
)

def _humanize_seconds_in_text(value: str) -> str:
    with_durations = _SECONDS_TOKEN_RE.sub(
        lambda match: _duration_label(int(match.group(1))),
        value,
    )
    return _ISO_TIMESTAMP_TOKEN_RE.sub(
        lambda match: _format_timestamp_or_text(match.group(0), default=match.group(0)),
        with_durations,
    )

def _duration_label(seconds: int) -> str:
    if seconds >= 86_400:
        days, remainder = divmod(seconds, 86_400)
        hours = remainder // 3_600
        return f"{days}d {hours}h" if hours else f"{days}d"
    if seconds >= 3_600:
        hours, remainder = divmod(seconds, 3_600)
        minutes = remainder // 60
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if seconds >= 60:
        minutes, remainder = divmod(seconds, 60)
        return f"{minutes}m {remainder}s" if remainder else f"{minutes}m"
    return f"{seconds}s"

def dashboard_data_health(
    page_label: str,
    *,
    datasets: Sequence[str] = (),
    lanes: Sequence[str] = (),
    data_load_status: Mapping[str, object] | None = None,
    provider_label: str | None = None,
    cycle_id: str | None = None,
    extra_rows: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Build a compact, plain-English data health model for dashboard pages."""
    status = dict(data_load_status or _load_dashboard_data_load_status())
    health_monitor = _mapping_object(status.get("health_monitor"))
    dataset_rows = _matching_health_rows(
        _optional_mapping_rows(status.get("datasets")),
        key="dataset",
        wanted=datasets,
    )
    lane_rows = _matching_health_rows(
        _optional_mapping_rows(status.get("lanes")),
        key="lane",
        wanted=lanes,
    )
    rows = _ordered_data_health_rows([
        _health_monitor_data_health_row(health_monitor),
        *_dashboard_dataset_health_rows(dataset_rows),
        *_dashboard_lane_health_rows(lane_rows),
        *[_normal_data_health_row(row) for row in extra_rows],
    ])
    status_class = _worst_health_class(rows)
    resolved_cycle_id = cycle_id or _clean_text(status.get("cycle_id")) or "None"
    resolved_provider = (
        provider_label
        or _provider_label_from_status(status)
        or "provider unavailable"
    )
    raw_monitor_label = str(health_monitor.get("status_label") or "Not verified")
    monitor_live = health_monitor.get("live") is True
    overall_percent = _bounded_percent(status.get("overall_percent"))
    issue_label = _data_health_issue_label(rows)
    health_state = _data_health_state(rows, health_monitor)
    monitor_label = (
        _data_health_status_label(status_class, health_state)
        if health_state in {"health_proof_needs_refresh", "health_proof_unavailable"}
        else _operator_text(raw_monitor_label)
    )
    status_label = _data_health_status_label(status_class, health_state)
    primary_issue = _data_health_primary_issue(rows, health_state)
    primary_blocker = _data_health_primary_blocker_label(primary_issue, health_state)
    primary_blocker_detail = _data_health_primary_blocker_detail(primary_issue)
    recommended_action = _data_health_recommended_action(
        primary_issue,
        health_state,
    )
    meaning = _data_health_meaning(
        page_label,
        status_label,
        primary_issue,
        health_state,
    )
    last_verified_label = _format_timestamp_or_text(
        health_monitor.get("latest_checked_at"),
        default=_format_timestamp_or_text(
            status.get("status_checked_at"),
            default="not checked",
        ),
    )
    return {
        "page_label": page_label,
        "status_label": status_label,
        "status_class": status_class,
        "headline": _data_health_headline(page_label, status_class, issue_label, health_state),
        "detail": _data_health_detail(meaning, recommended_action, primary_blocker_detail),
        "meaning": meaning,
        "recommended_action": recommended_action,
        "primary_blocker": primary_blocker,
        "primary_blocker_detail": primary_blocker_detail,
        "last_verified_label": last_verified_label,
        "tooltip": _data_health_tooltip(health_monitor, health_state),
        "provider_label": resolved_provider,
        "monitor_label": monitor_label,
        "monitor_live": monitor_live,
        "cycle_id": resolved_cycle_id,
        "as_of": _format_timestamp_or_text(status.get("as_of")),
        "checked_at": _format_timestamp_or_text(
            status.get("status_checked_at"),
            default=_format_timestamp_or_text(_now_utc_text()),
        ),
        "overall_percent": overall_percent,
        "progress_style": f"width: {overall_percent}%",
        "rows": rows,
        "row_count": len(rows),
        "visible_row_count": len(rows),
        "hidden_row_count": 0,
        "issue_label": issue_label,
        "action_buttons": _data_health_action_buttons(primary_issue, health_state),
        "summary_items": [
            {"label": "As of", "value": _format_timestamp_or_text(status.get("as_of"))},
            {"label": "Decision status", "value": status_label},
            {
                "label": "Blocking reason",
                "value": primary_blocker,
                "tooltip": primary_blocker_detail,
            },
            {
                "label": "Data coverage",
                "value": f"{overall_percent}%",
                "tooltip": "Percent of displayed required data inputs that are loaded and usable.",
            },
            {
                "label": "Last verified",
                "value": last_verified_label,
                "tooltip": _health_monitor_tooltip(health_monitor),
            },
            {
                "label": "Next action",
                "value": recommended_action,
                "tooltip": recommended_action,
            },
        ],
        "diagnostics_items": [
            {"label": "Cycle", "value": _short_cycle_label(resolved_cycle_id)},
            {"label": "Provider/cache", "value": resolved_provider},
            {"label": "Runtime mode", "value": str(status.get("mode_label") or status.get("status_label") or "runtime mode unknown")},
            {
                "label": "Monitor status",
                "value": monitor_label,
                "tooltip": _health_monitor_tooltip(health_monitor),
            },
            {
                "label": "Monitor proof",
                "value": _data_health_proof_label(health_state),
                "tooltip": "Timestamped monitor proof used to trust or block the visible badge.",
            },
            {
                "label": "Monitor origin",
                "value": _clean_text(health_monitor.get("origin")) or "not verified",
            },
        ],
    }

def _load_dashboard_data_load_status() -> Mapping[str, object]:
    try:
        from agency.runtime.data_load_status import load_data_load_status
    except ModuleNotFoundError:
        return {}
    return load_data_load_status(
        source_health_rows=[],
        source_health_origin="live source-health monitor unavailable",
    )

async def live_dashboard_data_load_status() -> dict[str, object]:
    """Build data-load status from live source-health rows whenever possible."""
    try:
        from agency.runtime.data_load_status import load_data_load_status
    except ModuleNotFoundError:
        return {}
    source_health = await live_runtime_source_health_rows()
    return load_data_load_status(
        source_health_rows=source_health,
        source_health_origin=_source_health_origin_label(source_health),
    )

async def live_runtime_source_health_rows(
    reader: Callable[[], Awaitable[Sequence[Mapping[str, object]]]] | None = None,
) -> list[Mapping[str, object]]:
    """Read live source-health rows with the same timeout/fallback on every page."""
    try:
        from agency.api.health import (
            runtime_data_source_status,
            unavailable_data_source_status,
        )
    except ModuleNotFoundError:
        return []
    source_reader = runtime_data_source_status if reader is None else reader
    try:
        rows = await asyncio.wait_for(
            source_reader(),
            timeout=DASHBOARD_HEALTH_QUERY_TIMEOUT_SECONDS,
        )
        resolved = list(rows)
        if not resolved:
            return [
                cast(Mapping[str, object], row)
                for row in unavailable_data_source_status(
                    "live source-health reader returned no monitored provider rows"
                )
            ]
        return resolved
    except Exception:  # noqa: BLE001
        return [
            cast(Mapping[str, object], row)
            for row in unavailable_data_source_status(
                "live source-health reader timed out or failed"
            )
        ]

def _source_health_origin_label(source_health: Sequence[Mapping[str, object]]) -> str:
    if any(str(row.get("source") or "") == "source-health-monitor" for row in source_health):
        return "source-health monitor unavailable"
    if any(_has_artifact_fallback_note(row) for row in source_health):
        return "runtime artifact fallback"
    return "live runtime source-health reader"

def _has_artifact_fallback_note(payload: Mapping[str, object]) -> bool:
    notes = payload.get("notes", [])
    if not isinstance(notes, list):
        return False
    return "runtime_artifact_fallback" in {str(note) for note in notes}

def _ordered_data_health_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Keep blockers visible first without hiding any displayed-data input."""
    priority = {"block": 0, "warn": 1, "warning": 1, "neutral": 2, "pass": 3}
    return sorted(
        [dict(row) for row in rows],
        key=lambda row: (
            priority.get(str(row.get("status_class") or "neutral"), 2),
            0 if row.get("kind") == "Health monitor" else 1,
            str(row.get("kind") or ""),
            str(row.get("name") or ""),
        ),
    )

def _matching_health_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    key: str,
    wanted: Sequence[str],
) -> list[Mapping[str, object]]:
    wanted_set = {item for item in wanted if item}
    if not wanted_set:
        return list(rows)
    return [row for row in rows if str(row.get(key) or "") in wanted_set]

def _operator_text(value: object, default: str = "") -> str:
    """Translate backend health terms into operator-facing wording."""
    text = _humanize_seconds_in_text(str(value or default))
    if not text:
        return default
    replacements = (
        (r"\bcheck[- ]stale\b", "health proof needs refresh"),
        (r"\bhealth check stale\b", "health proof needs refresh"),
        (r"\bhealth monitor stale\b", "health proof needs refresh"),
        (r"\bcritical stale source\b", "critical source needs refresh"),
        (r"\bare stale\b", "need refresh"),
        (r"\bis stale\b", "needs refresh"),
        (r"\bstale source\b", "source that needs refresh"),
        (r"\bstale data\b", "data that needs refresh"),
        (r"\bdata stale\b", "data needs refresh"),
        (r"\bstale\b", "needs refresh"),
    )
    cleaned = text
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return cleaned

def _refresh_lane_id_for_row(row: Mapping[str, object]) -> str:
    raw = str(
        row.get("refresh_lane_id")
        or row.get("lane")
        or row.get("dataset")
        or row.get("source")
        or row.get("source_dataset")
        or ""
    ).strip()
    return REFRESHABLE_DATASET_TO_LANE.get(raw, raw)

def _operator_issue_state(
    row: Mapping[str, object],
    *,
    kind: str,
    status_class: str,
    detail: str,
) -> str:
    status = str(row.get("status") or "").upper()
    freshness = str(row.get("source_freshness") or row.get("freshness") or "").upper()
    status_label = str(row.get("status_label") or "").casefold()
    detail_lc = detail.casefold()
    row_count = _safe_int(row.get("row_count"))
    produced_count = _safe_int(row.get("produced_count"))
    expected_count = _safe_int(row.get("expected_count") or row.get("expected_ticker_count"))
    usable_count = _safe_int(
        row.get("usable_ticker_count")
        or row.get("active_usable_ticker_count")
        or row.get("source_usable_ticker_count")
    )

    if kind == "Health monitor":
        if "stale" in status_label or "older than" in detail_lc or status == "STALE":
            return "health_proof_needs_refresh"
        if status in {"MISSING", "UNAVAILABLE"} or any(
            token in status_label for token in ("missing", "unavailable", "unverified")
        ):
            return "health_proof_unavailable"
        return "verified_current" if status_class == "pass" else "unverified"

    if status_class in {"warn", "warning"} and (
        usable_count > 0
        or row_count > 0
        or "partial_usable" in detail_lc
        or "ticker(s) usable" in detail_lc
    ):
        if freshness == "STALE" or status == "STALE" or "older than" in detail_lc:
            return "refresh_recommended"
        return "usable_with_gaps"

    unavailable_tokens = (
        "unavailable",
        "missing",
        "failed",
        "timeout",
        "login required",
        "credential",
        "permission",
        "rate limit",
        "rate-limited",
        "manifest is missing",
    )
    if freshness == "UNAVAILABLE" or status in {"UNAVAILABLE", "MISSING", "FAILED", "RATE_LIMITED"}:
        return "data_unavailable"
    if any(token in status_label or token in detail_lc for token in unavailable_tokens):
        return "data_unavailable"

    if kind == "Agent lane" and (
        produced_count == 0
        or (expected_count > 0 and row_count == 0 and "produced" in detail_lc)
        or "no analysis rows" in status_label
        or "produced 0 rows" in detail_lc
    ):
        return "waiting_for_analysis"

    if freshness == "STALE" or status == "STALE" or "stale" in status_label or "stale" in detail_lc:
        return "refresh_recommended"
    if "older than" in detail_lc and "source-health row" not in detail_lc:
        return "refresh_recommended"
    if status_class == "block":
        return "data_blocked"
    if status_class in {"warn", "warning"}:
        return "usable_with_gaps"
    if status_class == "pass":
        return "verified_current"
    return "unverified"

def _operator_row_status_label(
    row: Mapping[str, object],
    *,
    kind: str,
    issue_state: str,
) -> str:
    if issue_state == "health_proof_needs_refresh":
        return "Health proof needs refresh"
    if issue_state == "health_proof_unavailable":
        return "Health proof unavailable"
    if issue_state == "data_unavailable":
        return "Data unavailable"
    if issue_state == "waiting_for_analysis":
        return "Waiting for analysis"
    if issue_state == "refresh_recommended":
        return "Refresh recommended"
    raw = str(row.get("status_label") or row.get("status") or "Unknown")
    if kind == "Health monitor" and raw == "Unknown":
        raw = "Health Monitor Unverified"
    return _operator_text(raw)

def _operator_freshness_label(value: object) -> str:
    freshness = str(value or "not checked")
    normalized = freshness.upper()
    if normalized == "STALE":
        return "Needs refresh"
    if normalized == "AGING":
        return "Aging"
    if normalized == "UNAVAILABLE":
        return "Unavailable"
    return _operator_text(freshness)

def _operator_issue_reason(
    issue_state: str,
    *,
    name: str,
    kind: str,
    status_class: str,
    detail: str,
) -> str:
    if issue_state == "data_unavailable":
        return f"{name} is unavailable. {_operator_text(detail)}"
    if issue_state == "waiting_for_analysis":
        return (
            f"{name} has source data available, but the agent has not produced "
            "analysis rows yet."
        )
    if issue_state == "refresh_recommended":
        return (
            f"{name} was analyzed, but the result is no longer current enough "
            "for the policy window."
        )
    if issue_state == "health_proof_needs_refresh":
        return f"{name} needs a newer health-monitor check before execution."
    if issue_state == "health_proof_unavailable":
        return f"{name} cannot currently prove dashboard data health."
    return _row_blocking_reason(name, status_class, detail)

def _operator_recommended_action(
    issue_state: str,
    *,
    kind: str,
    name: str,
    status_class: str,
) -> str:
    if issue_state == "data_unavailable":
        return (
            f"Fix access for {name}, then refresh that source and reload this dashboard."
        )
    if issue_state == "waiting_for_analysis":
        return f"Run the {name} lane, then re-run the affected candidate cycle."
    if issue_state == "refresh_recommended":
        return f"Refresh {name}, then re-run the affected candidate cycle."
    if issue_state in {"health_proof_needs_refresh", "health_proof_unavailable"}:
        return "Refresh source-health monitoring, then reload this dashboard."
    return _row_recommended_action(kind, name, status_class)

def _dashboard_dataset_health_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in rows:
        name = str(row.get("label") or row.get("dataset") or "Unknown dataset")
        detail = _humanize_seconds_in_text(
            str(row.get("detail") or "No dataset detail recorded.")
        )
        status_class = str(row.get("status_class") or "neutral")
        issue_state = _operator_issue_state(
            row,
            kind="Dataset",
            status_class=status_class,
            detail=detail,
        )
        freshness_label = _dataset_freshness_label(row)
        health_row: dict[str, object] = {
            "kind": "Dataset",
            "name": name,
            "status_label": _operator_row_status_label(
                row,
                kind="Dataset",
                issue_state=issue_state,
            ),
            "status_class": status_class,
            "coverage_label": _coverage_label(row),
            "freshness_label": _operator_freshness_label(freshness_label),
            "last_update": _format_timestamp_or_text(
                row.get("source_last_success_at") or row.get("max_as_of")
            ),
            "detail": _row_display_detail("Dataset", name, status_class, _operator_text(detail)),
            "diagnostic_detail": _operator_text(detail),
            "blocking_reason": _operator_issue_reason(
                issue_state,
                name=name,
                kind="Dataset",
                status_class=status_class,
                detail=detail,
            ),
            "recommended_action": _operator_recommended_action(
                issue_state,
                kind="Dataset",
                name=name,
                status_class=status_class,
            ),
            "why_it_matters": _row_why_it_matters("Dataset", name),
            "tooltip": _dataset_health_tooltip(row),
            "issue_state": issue_state,
            "refresh_lane_id": _refresh_lane_id_for_row(row),
        }
        output.append(health_row)
    return output

def _dashboard_lane_health_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in rows:
        name = str(row.get("label") or row.get("lane") or "Unknown lane")
        detail = _humanize_seconds_in_text(
            str(row.get("detail") or "No lane detail recorded.")
        )
        status_class = str(row.get("status_class") or "neutral")
        issue_state = _operator_issue_state(
            row,
            kind="Agent lane",
            status_class=status_class,
            detail=detail,
        )
        health_row: dict[str, object] = {
            "kind": "Agent lane",
            "name": name,
            "status_label": _operator_row_status_label(
                row,
                kind="Agent lane",
                issue_state=issue_state,
            ),
            "status_class": status_class,
            "coverage_label": _coverage_label(row),
            "freshness_label": _operator_freshness_label(row.get("source_freshness") or "not checked"),
            "last_update": _format_timestamp_or_text(
                row.get("source_last_success_at")
                or row.get("max_as_of")
                or row.get("source_dataset")
                or "runtime signal output"
            ),
            "detail": _row_display_detail("Agent lane", name, status_class, _operator_text(detail)),
            "diagnostic_detail": _operator_text(detail),
            "blocking_reason": _operator_issue_reason(
                issue_state,
                name=name,
                kind="Agent lane",
                status_class=status_class,
                detail=detail,
            ),
            "recommended_action": _operator_recommended_action(
                issue_state,
                kind="Agent lane",
                name=name,
                status_class=status_class,
            ),
            "why_it_matters": _row_why_it_matters("Agent lane", name),
            "tooltip": _lane_health_tooltip(row),
            "issue_state": issue_state,
            "refresh_lane_id": _refresh_lane_id_for_row(row),
        }
        output.append(health_row)
    return output

def _health_monitor_data_health_row(monitor: Mapping[str, object]) -> dict[str, object]:
    row_count = _safe_int(monitor.get("row_count"))
    max_age = monitor.get("max_age_seconds")
    age_label = (
        f"{_duration_label(max_age)} max age"
        if isinstance(max_age, int) and max_age >= 0
        else "age not verified"
    )
    origin = str(monitor.get("origin") or "unknown source-health origin")
    live = "live" if monitor.get("live") is True else "not live"
    reliable = "reliable" if monitor.get("reliable") is True else "unreliable"
    status_class = str(monitor.get("status_class") or "block")
    detail = _humanize_seconds_in_text(
        f"{monitor.get('detail') or 'Health monitor detail is unavailable.'} "
        f"Origin: {origin}; monitor is {live} and {reliable}."
    )
    issue_state = _operator_issue_state(
        monitor,
        kind="Health monitor",
        status_class=status_class,
        detail=detail,
    )
    return {
        "kind": "Health monitor",
        "name": "Source-health reliability",
        "status_label": _operator_row_status_label(
            monitor,
            kind="Health monitor",
            issue_state=issue_state,
        ),
        "status_class": status_class,
        "coverage_label": f"{row_count} source-health row(s)",
        "freshness_label": age_label,
        "last_update": _format_timestamp_or_text(
            monitor.get("latest_checked_at"),
            default="not checked",
        ),
        "detail": _row_display_detail(
            "Health monitor",
            "Source-health reliability",
            status_class,
            _operator_text(detail),
        ),
        "diagnostic_detail": _operator_text(detail),
        "blocking_reason": _operator_issue_reason(
            issue_state,
            name="Source-health reliability",
            kind="Health monitor",
            status_class=status_class,
            detail=detail,
        ),
        "recommended_action": _operator_recommended_action(
            issue_state,
            kind="Health monitor",
            name="Source-health reliability",
            status_class=status_class,
        ),
        "why_it_matters": _row_why_it_matters("Health monitor", "Source-health reliability"),
        "tooltip": _health_monitor_tooltip(monitor),
        "issue_state": issue_state,
    }

def _normal_data_health_row(row: Mapping[str, object]) -> dict[str, object]:
    kind = str(row.get("kind") or "Source")
    name = str(row.get("name") or row.get("label") or "Runtime source")
    status_class = str(row.get("status_class") or "neutral")
    detail = _humanize_seconds_in_text(
        str(row.get("detail") or "No source detail recorded.")
    )
    issue_state = _operator_issue_state(
        row,
        kind=kind,
        status_class=status_class,
        detail=detail,
    )
    return {
        "kind": kind,
        "name": name,
        "status_label": _operator_row_status_label(
            row,
            kind=kind,
            issue_state=issue_state,
        ),
        "status_class": status_class,
        "coverage_label": str(row.get("coverage_label") or row.get("coverage") or "not tracked"),
        "freshness_label": _operator_freshness_label(
            row.get("freshness_label") or row.get("freshness") or "not checked"
        ),
        "last_update": _format_timestamp_or_text(row.get("last_update") or row.get("checked_at")),
        "detail": _row_display_detail(kind, name, status_class, _operator_text(detail)),
        "diagnostic_detail": _operator_text(detail),
        "blocking_reason": _operator_issue_reason(
            issue_state,
            name=name,
            kind=kind,
            status_class=status_class,
            detail=detail,
        ),
        "recommended_action": str(
            row.get("recommended_action")
            or _operator_recommended_action(
                issue_state,
                kind=kind,
                name=name,
                status_class=status_class,
            )
        ),
        "why_it_matters": str(row.get("why_it_matters") or _row_why_it_matters(kind, name)),
        "tooltip": _humanize_seconds_in_text(
            _operator_text(row.get("tooltip") or row.get("detail") or "No source detail recorded.")
        ),
        "issue_state": issue_state,
        "refresh_lane_id": _refresh_lane_id_for_row(row),
    }

def _row_display_detail(
    kind: str,
    name: str,
    status_class: str,
    detail: str,
) -> str:
    if status_class == "block":
        return f"{name} is blocking this view. {detail}"
    if status_class in {"warn", "warning"}:
        return f"{name} is usable with a caution. {detail}"
    if status_class == "pass":
        return f"{name} passed the displayed-data checks. {detail}"
    return f"{kind} status is not fully verified. {detail}"

def _data_health_action_buttons(
    primary_issue: Mapping[str, object] | None,
    health_state: str,
) -> list[dict[str, str]]:
    issue_status_class = (
        str(primary_issue.get("status_class") or "").lower()
        if primary_issue is not None
        else ""
    )
    issue_text = " ".join(
        str(primary_issue.get(key) or "")
        for key in (
            "name",
            "detail",
            "diagnostic_detail",
            "blocking_reason",
            "recommended_action",
            "tooltip",
        )
    ).lower() if primary_issue is not None else ""
    buttons: list[dict[str, str]] = []
    refresh_lane_id = (
        str(primary_issue.get("refresh_lane_id") or "")
        if primary_issue is not None
        else ""
    )
    if refresh_lane_id in REFRESHABLE_MASSIVE_LANES:
        buttons.append(
            {
                "label": REFRESHABLE_MASSIVE_LANES[refresh_lane_id],
                "action": f"/scheduler/massive-lanes/{refresh_lane_id}/refresh",
                "method": "post",
                "detail": (
                    "Runs the trade-aware lane refresh, then updates runtime health proof."
                ),
            }
        )
    elif "massive-stock-trades" in issue_text or "live trade" in issue_text:
        buttons.append(
            {
                "label": "Refresh Live Trade Slices",
                "action": "/scheduler/massive-lanes/massive_live_trade_slices/refresh",
                "method": "post",
                "detail": (
                    "Runs the trade-aware Massive live trade slice refresh, then updates "
                    "runtime health proof."
                ),
            }
        )
    elif "daily-market-bars" in issue_text or "daily bar" in issue_text:
        buttons.append(
            {
                "label": "Refresh Daily Bars",
                "action": "/scheduler/massive-lanes/massive_daily_bars/refresh",
                "method": "post",
                "detail": (
                    "Runs the trade-aware Massive daily bar refresh, then updates "
                    "runtime health proof."
                ),
            }
        )
    if (
        health_state in {
            "health_proof_needs_refresh",
            "health_proof_unavailable",
            "data_unavailable",
            "waiting_for_analysis",
            "refresh_recommended",
            "data_blocked",
        }
        or issue_status_class in {"warn", "warning", "block"}
    ):
        buttons.append(
            {
                "label": "Open Refresh Queue",
                "href": "/#scheduler-heading",
                "method": "get",
                "detail": "Opens Command at the scheduler and lane refresh controls.",
            }
        )
    return buttons

def _row_blocking_reason(name: str, status_class: str, detail: str) -> str:
    cleaned = detail.strip()
    lowered = cleaned.lower()
    if status_class == "block":
        if cleaned:
            if lowered.startswith("blocked") or " is blocked because " in lowered:
                return f"{cleaned[:1].upper()}{cleaned[1:]}"
            return f"Blocked because {cleaned}"
        return f"Blocked because {name} did not pass a freshness or coverage gate."
    if status_class in {"warn", "warning"}:
        return cleaned if cleaned else f"{name} is usable but has a warning."
    return "No blocking reason; this input passed the displayed-data checks."

def _row_recommended_action(kind: str, name: str, status_class: str) -> str:
    if status_class == "block":
        if kind == "Agent lane":
            return f"Refresh the {name} lane, then re-run the affected candidate cycle."
        if kind == "Dataset":
            return f"Refresh the {name} data source, then reload this dashboard."
        if kind == "Health monitor":
            return "Refresh source-health monitoring before treating any dashboard status as tradable."
        return f"Refresh {name}, then reload this dashboard."
    if status_class in {"warn", "warning"}:
        return f"Review the caution for {name}; refresh it before paper execution if it affects the trade."
    if status_class == "pass":
        return "No action required for this input."
    return f"Verify {name} before using this dashboard for execution."

def _row_why_it_matters(kind: str, name: str) -> str:
    if kind == "Agent lane":
        return (
            f"{name} can change the evidence, conviction, and actionability shown "
            "to the reviewer."
        )
    if kind == "Dataset":
        return (
            f"{name} feeds one or more signal lanes. Missing coverage can make "
            "scores, gates, or explanations incomplete."
        )
    if kind == "Health monitor":
        return (
            "This proves whether the health badges themselves are live and reliable. "
            "An old monitor check means the page cannot prove its own freshness."
        )
    return f"{name} contributes to the displayed decision context."

def _coverage_label(row: Mapping[str, object]) -> str:
    coverage = _bounded_percent(row.get("coverage_pct"))
    count = _health_count_label(row)
    return f"{coverage}% / {count}" if count else f"{coverage}%"

def _health_count_label(row: Mapping[str, object]) -> str:
    usable = row.get("usable_ticker_count")
    loaded = row.get("loaded_ticker_count")
    produced = row.get("produced_count")
    expected = row.get("expected_ticker_count") or row.get("expected_count")
    row_count = row.get("row_count")
    if isinstance(usable, int) and isinstance(expected, int):
        return f"{usable}/{expected} tickers usable"
    if isinstance(loaded, int) and isinstance(expected, int):
        return f"{loaded}/{expected} tickers loaded"
    if isinstance(produced, int) and isinstance(expected, int):
        return f"{produced}/{expected} rows"
    if isinstance(row_count, int):
        return f"{row_count:,} rows"
    return ""

def _dataset_freshness_label(row: Mapping[str, object]) -> str:
    source_freshness = str(row.get("source_freshness") or "UNKNOWN")
    coverage_as_of = _clean_text(row.get("coverage_as_of"))
    if coverage_as_of:
        return f"{source_freshness}; coverage {_format_timestamp_or_text(coverage_as_of)}"
    return source_freshness

def _worst_health_class(rows: Sequence[Mapping[str, object]]) -> str:
    classes = [str(row.get("status_class") or "neutral") for row in rows]
    if "block" in classes:
        return "block"
    if "warn" in classes or "warning" in classes:
        return "warn"
    if "pass" in classes:
        return "pass"
    return "neutral"

def _data_health_status_label(status_class: str, health_state: str = "") -> str:
    if health_state == "health_proof_needs_refresh":
        return "Health proof needs refresh"
    if health_state == "health_proof_unavailable":
        return "Health proof unavailable"
    if health_state == "data_unavailable":
        return "Data unavailable"
    if health_state == "waiting_for_analysis":
        return "Waiting for analysis"
    if health_state == "refresh_recommended":
        return "Refresh recommended"
    if health_state == "data_blocked":
        return "Blocked"
    return {
        "pass": "Verified Current",
        "warn": "Usable With Gaps",
        "block": "Blocked",
        "neutral": "Displayed Data Unverified",
    }.get(status_class, "Displayed Data Unverified")

def _data_health_headline(
    page_label: str,
    status_class: str,
    issue_label: str,
    health_state: str = "",
) -> str:
    if health_state == "health_proof_needs_refresh":
        return (
            f"{page_label} data is mostly loaded, but the health proof needs refresh "
            "before execution."
        )
    if health_state == "health_proof_unavailable":
        return f"{page_label} cannot prove displayed data health because monitoring is unavailable."
    if health_state == "data_unavailable":
        return f"{page_label} cannot load one required data source."
    if health_state == "waiting_for_analysis":
        return f"{page_label} has source data available, but an agent still needs to analyze it."
    if health_state == "refresh_recommended":
        return f"{page_label} has analyzed data that needs refresh before acting."
    if health_state == "data_blocked":
        return f"{page_label} has blocked data; refresh before acting."
    if status_class == "pass":
        return f"{page_label} is using verified-current, usable data."
    if status_class == "warn":
        return f"{page_label} is usable, but {issue_label}."
    if status_class == "block":
        return f"{page_label} needs health verification before execution."
    return f"{page_label} data health is not fully verified yet."

def _data_health_detail(
    meaning: str,
    recommended_action: str,
    primary_blocker_detail: str,
) -> str:
    if primary_blocker_detail and primary_blocker_detail != "No blocker detected.":
        return f"{meaning} {recommended_action} Reason: {primary_blocker_detail}"
    return f"{meaning} {recommended_action}"

def _data_health_primary_issue(
    rows: Sequence[Mapping[str, object]],
    health_state: str,
) -> Mapping[str, object] | None:
    target_issue = {
        "health_proof_needs_refresh": "health_proof_needs_refresh",
        "health_proof_unavailable": "health_proof_unavailable",
        "data_unavailable": "data_unavailable",
        "waiting_for_analysis": "waiting_for_analysis",
        "refresh_recommended": "refresh_recommended",
    }.get(health_state)
    if target_issue:
        for row in rows:
            if row.get("issue_state") == target_issue:
                return row
    if health_state == "data_blocked":
        for row in rows:
            if row.get("kind") != "Health monitor" and str(row.get("status_class") or "") == "block":
                return row
        for row in rows:
            if row.get("kind") != "Health monitor" and str(row.get("status_class") or "") in {"warn", "warning"}:
                return row
    for row in rows:
        if str(row.get("status_class") or "") == "block":
            return row
    for row in rows:
        if str(row.get("status_class") or "") in {"warn", "warning"}:
            return row
    return None

def _data_health_primary_blocker_label(
    primary_issue: Mapping[str, object] | None,
    health_state: str,
) -> str:
    if primary_issue is None:
        return "No blocker detected."
    name = str(primary_issue.get("name") or "Displayed data")
    status = str(primary_issue.get("status_label") or primary_issue.get("status_class") or "").strip()
    if health_state == "health_proof_needs_refresh":
        return f"{name} health proof needs refresh"
    if health_state == "health_proof_unavailable":
        return f"{name} health check is unavailable"
    if health_state in {"data_unavailable", "waiting_for_analysis", "refresh_recommended"}:
        return f"{name} - {_data_health_status_label('', health_state)}"
    return f"{name} - {status}" if status else name

def _data_health_primary_blocker_detail(
    primary_issue: Mapping[str, object] | None,
) -> str:
    if primary_issue is None:
        return "No blocker detected."
    return str(
        primary_issue.get("blocking_reason")
        or primary_issue.get("detail")
        or "No detailed reason was recorded."
    )

def _data_health_meaning(
    page_label: str,
    status_label: str,
    primary_issue: Mapping[str, object] | None,
    health_state: str,
) -> str:
    issue_name = str(primary_issue.get("name") or "one required input") if primary_issue else "all required inputs"
    if health_state == "data_unavailable":
        return (
            f"This dashboard is not execution-ready because {issue_name} has a "
            "problem reaching or loading its data."
        )
    if health_state == "waiting_for_analysis":
        return (
            f"This dashboard is not execution-ready because {issue_name} has source "
            "data, but its agent has not produced analysis rows yet."
        )
    if health_state == "refresh_recommended":
        return (
            f"This dashboard has analyzed data for {issue_name}, but the result is "
            "not current enough for the policy window."
        )
    if health_state == "data_blocked":
        return (
            f"This dashboard is not execution-ready because {issue_name} is blocked. "
            "Use it for review context only until the blocker is cleared."
        )
    if health_state == "health_proof_needs_refresh":
        return (
            "The displayed data may be usable for review, but the dashboard needs "
            "a newer health-monitor proof before execution."
        )
    if health_state == "health_proof_unavailable":
        return (
            "The page cannot prove whether the displayed data is current because "
            "source-health monitoring is unavailable."
        )
    if status_label == "Verified Current":
        return "This dashboard is using data that passed the displayed-data checks."
    return f"This dashboard is in {status_label} state for the visible data inputs."

def _data_health_recommended_action(
    primary_issue: Mapping[str, object] | None,
    health_state: str,
) -> str:
    if primary_issue is not None:
        row_action = str(primary_issue.get("recommended_action") or "").strip()
        if row_action:
            return _operator_text(row_action)
    if health_state == "data_unavailable":
        return "Fix the data access problem, refresh that source, then reload this dashboard."
    if health_state == "waiting_for_analysis":
        return "Run the relevant agent lane, then re-run the affected candidate cycle."
    if health_state == "refresh_recommended":
        return "Refresh the relevant data lane, then re-run the affected candidate cycle."
    if health_state == "data_blocked":
        return "Refresh the relevant data lane, then reload the dashboard before acting."
    if health_state in {"health_proof_needs_refresh", "health_proof_unavailable"}:
        return "Refresh source-health monitoring, then reload this dashboard."
    return "No immediate action required; continue normal review."


def _data_health_state(
    rows: Sequence[Mapping[str, object]],
    health_monitor: Mapping[str, object],
) -> str:
    monitor_status = str(health_monitor.get("status") or "").casefold()
    monitor_label = str(health_monitor.get("status_label") or "").casefold()
    if not monitor_status:
        if "stale" in monitor_label:
            monitor_status = "stale"
        elif "unavailable" in monitor_label:
            monitor_status = "unavailable"
        elif "missing" in monitor_label:
            monitor_status = "missing"
        elif "unverified" in monitor_label:
            monitor_status = "unverified"
    data_rows = [row for row in rows if row.get("kind") != "Health monitor"]
    data_blocked = any(str(row.get("status_class") or "") == "block" for row in data_rows)
    data_unavailable = any(row.get("issue_state") == "data_unavailable" for row in data_rows)
    waiting_for_analysis = any(row.get("issue_state") == "waiting_for_analysis" for row in data_rows)
    refresh_recommended = any(row.get("issue_state") == "refresh_recommended" for row in data_rows)
    if monitor_status == "stale":
        return "health_proof_needs_refresh"
    if monitor_status in {"missing", "unavailable", "unverified"}:
        return "health_proof_unavailable"
    if data_unavailable:
        return "data_unavailable"
    if waiting_for_analysis:
        return "waiting_for_analysis"
    if refresh_recommended:
        return "refresh_recommended"
    if data_blocked:
        return "data_blocked"
    return "verified_current" if rows else "unverified"


def _data_health_proof_label(health_state: str) -> str:
    return {
        "health_proof_needs_refresh": "proof needs refresh",
        "health_proof_unavailable": "proof unavailable",
        "data_unavailable": "data unavailable",
        "waiting_for_analysis": "waiting for analysis",
        "refresh_recommended": "refresh recommended",
        "data_blocked": "monitor current; data blocked",
        "data_needs_refresh": "monitor current; data needs refresh",
        "verified_current": "monitor current",
    }.get(health_state, "unverified")


def _data_health_tooltip(
    health_monitor: Mapping[str, object],
    health_state: str,
) -> str:
    checked = _format_timestamp_or_text(
        health_monitor.get("latest_checked_at"),
        default="not checked",
    )
    max_age = health_monitor.get("max_age_seconds")
    max_age_label = _duration_label(max_age) if isinstance(max_age, int) else "not configured"
    state_label = _data_health_status_label(
        str(health_monitor.get("status_class") or "neutral"),
        health_state,
    )
    return (
        f"{state_label}: data freshness is the source data timestamp; health proof is "
        f"the dashboard monitor check. Latest health check: {checked}. "
        f"Allowed monitor age: {max_age_label}."
    )


def _health_monitor_tooltip(monitor: Mapping[str, object]) -> str:
    checked = _format_timestamp_or_text(monitor.get("latest_checked_at"), default="not checked")
    origin = _clean_text(monitor.get("origin")) or "unknown"
    max_age = monitor.get("max_age_seconds")
    max_age_label = _duration_label(max_age) if isinstance(max_age, int) else "not configured"
    return (
        f"Health monitor origin: {origin}. Latest check: {checked}. "
        f"Monitor SLA: {max_age_label}. An old monitor check gates execution confidence "
        "even when source data may still be usable for review."
    )


def _dataset_health_tooltip(row: Mapping[str, object]) -> str:
    return _humanize_seconds_in_text(
        _operator_text(
            "Dataset health combines source status, source freshness, coverage, last "
            f"success, and ticker coverage. Source freshness: {row.get('source_freshness', 'unknown')}; "
            "last success: "
            f"{_format_timestamp_or_text(row.get('source_last_success_at') or row.get('max_as_of'))}. "
            f"{row.get('detail') or ''}"
        )
    )


def _lane_health_tooltip(row: Mapping[str, object]) -> str:
    return _humanize_seconds_in_text(
        _operator_text(
            "Signal worker readiness requires produced rows and a passing source freshness "
            f"gate. Source dataset: {row.get('source_dataset', 'unknown')}; "
            f"coverage: {row.get('coverage_pct', 'not tracked')}%; "
            f"freshness: {row.get('source_freshness', 'unknown')}. "
            f"{row.get('detail') or ''}"
        )
    )

def _data_health_issue_label(rows: Sequence[Mapping[str, object]]) -> str:
    warn_or_block = [
        str(row.get("name") or "one source")
        for row in rows
        if str(row.get("status_class") or "") in {"warn", "block", "warning"}
    ]
    if not warn_or_block:
        return "all displayed inputs are fresh"
    if len(warn_or_block) == 1:
        return f"{warn_or_block[0]} needs attention"
    return f"{len(warn_or_block)} displayed inputs need attention"

def _provider_label_from_status(status: Mapping[str, object]) -> str | None:
    live_config = status.get("live_config")
    if isinstance(live_config, Mapping):
        provider = _clean_text(live_config.get("provider"))
        if provider:
            return provider
    return None

def _mapping_object(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}

def _optional_mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [
        cast(Mapping[str, object], item)
        for item in value
        if isinstance(item, Mapping)
    ]

def _safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return 0

def _bounded_percent(value: object) -> int:
    return max(0, min(100, _safe_int(value)))
