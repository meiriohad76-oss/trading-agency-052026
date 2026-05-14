"""Shared constants and utility helpers for dashboard view modules."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from dotenv import load_dotenv
from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError
from typing import cast
import os
import pandas as pd
import re

from agency.api.candidates import RuntimeCandidateTimelineUnavailable, runtime_candidate_timeline
from agency.api.reports import RuntimeSelectionReportsUnavailable, runtime_selection_reports
from agency.api.risk import RuntimeRiskDecisionsUnavailable, runtime_risk_decisions
from agency.db import MissingDatabaseConfigurationError, get_session
from agency.runtime import list_candidate_lifecycle_events

REPO_ROOT = Path(__file__).resolve().parents[2]
EMAIL_EVENTS_PATH = REPO_ROOT / "research" / "data" / "parquet" / "subscription_emails.parquet"
NEWS_RSS_PATH = REPO_ROOT / "research" / "data" / "parquet" / "news_rss.parquet"
PRICES_DAILY_ROOT = REPO_ROOT / "research" / "data" / "parquet" / "prices_daily"
ACTIONABLE_ACTIONS = {"BUY", "SELL", "SHORT", "COVER", "WATCH", "HOLD"}
OPEN_RISK_DECISIONS = {"ALLOW", "WARN"}
DEGRADED_SOURCE_STATUSES = {"DEGRADED", "STALE", "UNAVAILABLE", "RATE_LIMITED"}
DEGRADED_FRESHNESS = {"AGING", "STALE", "UNAVAILABLE"}
FINAL_SELECTION_REPORT_LIMIT = 1000
SIGNALS_REPORT_LIMIT = 300
SIGNALS_CONTEXT_CACHE_SECONDS = 300.0
MARKET_REGIME_CONTEXT_CACHE_SECONDS = 300.0
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
) -> list[dict[str, object]]:
    try:
        kwargs: dict[str, object] = {"limit": limit}
        if ticker is not None:
            kwargs["ticker"] = ticker
        try:
            return await runtime_selection_reports(**kwargs, validate_payloads=False)
        except TypeError as exc:
            if "validate_payloads" not in str(exc):
                raise
            return await runtime_selection_reports(**kwargs)
    except RuntimeSelectionReportsUnavailable:
        return []

async def _dashboard_risk_decisions(
    *,
    ticker: str | None = None,
    limit: int = FINAL_SELECTION_REPORT_LIMIT,
) -> list[dict[str, object]]:
    try:
        kwargs: dict[str, object] = {"limit": limit}
        if ticker is not None:
            kwargs["ticker"] = ticker
        try:
            return await runtime_risk_decisions(**kwargs, validate_payloads=False)
        except TypeError as exc:
            if "validate_payloads" not in str(exc):
                raise
            return await runtime_risk_decisions(**kwargs)
    except RuntimeRiskDecisionsUnavailable:
        return []

async def _dashboard_candidate_timeline(
    *,
    ticker: str,
    cycle_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    try:
        kwargs: dict[str, object] = {"ticker": ticker, "limit": limit}
        if cycle_id is not None:
            kwargs["cycle_id"] = cycle_id
        return await runtime_candidate_timeline(**kwargs)
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
            events = await list_candidate_lifecycle_events(
                session,
                cycle_id=cycle_id,
                limit=limit,
            )
    except (MissingDatabaseConfigurationError, SQLAlchemyError, RuntimeError, TypeError):
        events = await _timeline_lifecycle_events_for_reports(
            tickers=tickers,
            cycle_id=cycle_id,
            limit=limit_per_ticker,
        )
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
    for report in reports:
        cycle_id = _clean_text(report.get("cycle_id"))
        if cycle_id is not None and cycle_id.startswith(LIVE_SELECTION_CYCLE_PREFIXES):
            return cycle_id
    for report in reports:
        cycle_id = _clean_text(report.get("cycle_id"))
        if cycle_id is not None:
            return cycle_id
    return None

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
        "stale_evidence": "Evidence is stale, so it is context only.",
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
        key = _human_review_key(event)
        if all(key) and key not in indexed:
            indexed[key] = event
    return indexed

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
