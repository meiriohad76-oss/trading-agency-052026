"""View-model constructors for the candidates page."""
from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode, urlsplit

import pandas as pd
from news.consumption import load_news_consumption_entries

from agency.runtime.signal_evidence import enrich_signal_rows_with_evidence
from agency.services import build_leveraged_alternative_review
from agency.views._shared import (
    EMAIL_ANALYZED_STATUSES,
    EMAIL_ASSET_DOMAIN_PREFIXES,
    EMAIL_ASSET_EXTENSIONS,
    EMAIL_EVENT_LABELS,
    EMAIL_EVENTS_PATH,
    EMAIL_HEADLINE_FOCUS_RE,
    EMAIL_LINKED_STATUS_PRIORITY,
    MIN_BRIEF_CONFIRMED_COUNT,
    MIN_BRIEF_SOURCE_COUNT,
    MIN_EMAIL_PAIR_SCORE,
    NEWS_RSS_PATH,
    OPEN_RISK_DECISIONS,
    _clean_text,
    _clip_text,
    _dashboard_candidate_timeline,
    _dashboard_risk_decisions,
    _dashboard_selection_reports,
    _decision_class,
    _dedupe_text,
    _direction_class,
    _float_field,
    _format_timestamp_label,
    _human_list,
    _human_review_index,
    _human_review_summary,
    _int_field,
    _label_text,
    _mapping_field,
    _matching_payload,
    _pair_text,
    _plural,
    _row_text,
    _runtime_payload_key,
    _same_pair_text,
    _service_label,
    _sorted_signals,
    _source_id_core,
    _string_list,
    _timestamp_sort_value,
    dashboard_data_health,
    live_dashboard_data_load_status,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
NEWS_CONSUMPTION_LEDGER_PATH = (
    REPO_ROOT / "research" / "data" / "state" / "news_rss_consumed.json"
)


async def candidate_detail_context(ticker: str) -> dict[str, object]:
    from agency.views.market_regime import broker_status_context
    normalized_ticker = ticker.upper()
    reports, timeline, risk_decisions, broker = await asyncio.gather(
        _dashboard_selection_reports(ticker=normalized_ticker, limit=5),
        _dashboard_candidate_timeline(ticker=normalized_ticker, limit=25),
        _dashboard_risk_decisions(ticker=normalized_ticker, limit=5),
        broker_status_context(),
    )
    report_rows = candidate_detail_report_rows(reports, review_events=timeline)
    latest_report = report_rows[0] if report_rows else None
    latest_raw_report = _matching_payload(reports, latest_report)
    latest_risk_decision = _matching_payload(risk_decisions, latest_report)
    email_evidence = candidate_email_evidence(normalized_ticker)
    email_evidence = candidate_email_evidence_with_judgement(
        normalized_ticker,
        email_evidence,
        latest_report,
    )
    news_evidence = candidate_news_evidence(normalized_ticker)
    review = candidate_review_summary(report_rows, timeline, risk_decisions=risk_decisions)
    data_load_status = await live_dashboard_data_load_status()
    return {
        "ticker": normalized_ticker,
        "decision_brief": candidate_decision_brief(
            normalized_ticker,
            latest_report,
            email_evidence,
            review,
            current_position=_candidate_current_position(normalized_ticker, broker),
        ),
        "data_health": dashboard_data_health(
            f"{normalized_ticker} candidate brief",
            data_load_status=data_load_status,
            datasets=(
                "prices_daily",
                "stock_trades",
                "sec_company_facts",
                "sec_form4",
                "sec_13f",
                "news_rss",
                "subscription_emails",
            ),
            cycle_id=str(latest_report.get("cycle_id") if latest_report else ""),
        ),
        "email_evidence": email_evidence,
        "news_evidence": news_evidence,
        "leveraged_review": build_leveraged_alternative_review(
            latest_raw_report or latest_report,
            risk_decision=latest_risk_decision,
        ),
        "latest_report": latest_report,
        "previous_reports": report_rows[1:],
        "reports": report_rows,
        "review": review,
        "timeline": timeline_rows(timeline),
        "summary": candidate_detail_summary(normalized_ticker, report_rows, timeline),
    }

def candidate_rows(reports: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [_candidate_row(report) for report in reports]

def candidate_detail_report_rows(
    reports: Sequence[Mapping[str, object]],
    *,
    review_events: Sequence[Mapping[str, object]] = (),
) -> list[dict[str, object]]:
    from agency.views.final_selection import _candidate_detail_sort_key, _final_selection_row
    review_index = _human_review_index(review_events)
    rows = sorted(
        [
            _final_selection_row(
                report,
                review_event=review_index.get(_runtime_payload_key(report)),
            )
            for report in reports
        ],
        key=_candidate_detail_sort_key,
    )
    if rows:
        rows[0] = _enrich_candidate_report_signals(rows[0])
    return rows

def _enrich_candidate_report_signals(row: Mapping[str, object]) -> dict[str, object]:
    output = dict(row)
    for key in ("actionable_signals", "context_signals", "suppressed_signals"):
        signal_rows = _mapping_rows(output, key)
        output[key] = enrich_signal_rows_with_evidence(signal_rows) if signal_rows else []
    return output

def candidate_detail_summary(
    ticker: str,
    reports: Sequence[Mapping[str, object]],
    timeline: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    latest_action = str(reports[0]["action"]) if reports else "None"
    latest = reports[0] if reports else None
    return {
        "ticker": ticker,
        "report_count": len(reports),
        "event_count": len(timeline),
        "latest_action": latest_action,
        "headline": _candidate_detail_headline(ticker, latest_action),
        "detail": _candidate_detail_text(ticker, latest),
    }

def candidate_review_summary(
    reports: Sequence[Mapping[str, object]],
    timeline: Sequence[Mapping[str, object]],
    *,
    risk_decisions: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    if not reports:
        return {
            "can_record": False,
            "cycle_id": "None",
            "as_of": "None",
            "decision": "No Report",
            "status_class": "neutral",
            "reason": "No selection report available for review.",
            "review_reason": "",
            "notes": "",
            "event_time": "None",
            "event_time_label": "Time unknown",
            "approve_action": "#",
            "defer_action": "#",
            "reject_action": "#",
            "caution_acknowledgement_required": False,
            "caution_acknowledgement_text": "",
            "caution_recommendation": "",
        }
    report = reports[0]
    ticker = str(report["ticker"])
    cycle_id = str(report["cycle_id"])
    as_of = str(report["as_of"])
    review_event = _human_review_index(timeline).get((cycle_id, ticker, as_of))
    review = _human_review_summary(review_event)
    caution = _review_caution(report, _matching_payload(risk_decisions, report))
    return {
        "can_record": True,
        "cycle_id": cycle_id,
        "as_of": as_of,
        "decision": review["decision"],
        "status_class": review["status_class"],
        "reason": review["reason"],
        "review_reason": review["review_reason"],
        "notes": review["notes"],
        "event_time": review["event_time"],
        "event_time_label": _format_timestamp_label(review["event_time"]),
        "caution_acknowledgement_required": caution["required"],
        "caution_acknowledgement_text": caution["text"],
        "caution_recommendation": caution["recommendation"],
        "approve_action": _review_action_url(
            ticker=ticker,
            cycle_id=cycle_id,
            as_of=as_of,
            decision="APPROVE",
        ),
        "defer_action": _review_action_url(
            ticker=ticker,
            cycle_id=cycle_id,
            as_of=as_of,
            decision="DEFER",
        ),
        "reject_action": _review_action_url(
            ticker=ticker,
            cycle_id=cycle_id,
            as_of=as_of,
            decision="REJECT",
        ),
    }

def timeline_rows(events: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "event_type": str(event["event_type"]),
            "event_time": str(event["event_time"]),
            "event_time_label": _format_timestamp_label(event["event_time"]),
            "status": str(event["status"]),
            "reason": event["reason"],
        }
        for event in events
    ]

def candidate_email_evidence(
    ticker: str,
    *,
    event_path: Path = EMAIL_EVENTS_PATH,
    news_path: Path = NEWS_RSS_PATH,
    limit: int = 5,
) -> dict[str, object]:
    normalized = ticker.upper()
    all_events = _candidate_email_event_rows(normalized, event_path=event_path, limit=None)
    events = all_events[:limit]
    all_feed_rows = _candidate_email_feed_rows(normalized, news_path=news_path, limit=None)
    feed_rows = all_feed_rows[:limit]
    service_counts = Counter(
        _row_text(row, "service", "Subscription") for row in all_events
    )
    direction_counts = Counter(
        _row_text(row, "direction", "NEUTRAL").upper() for row in all_events
    )
    status_counts = Counter(
        _row_text(row, "linked_content_status", "not_requested") for row in all_events
    )
    analyzed_count = sum(
        1
        for row in all_events
        if _is_email_article_analyzed_status(_row_text(row, "linked_content_status"))
    )
    event_count = len(all_events)
    feed_count = len(all_feed_rows)
    latest_at = _latest_text([*events, *feed_rows])
    status_label, status_class = _email_evidence_status(event_count, analyzed_count)
    insight_cards = _candidate_email_insight_cards(events, limit=3)
    return {
        "ticker": normalized,
        "event_count": event_count,
        "feed_count": feed_count,
        "analyzed_count": analyzed_count,
        "status_counts": dict(status_counts),
        "status_summary": _email_status_summary(status_counts),
        "latest_at": latest_at or "None",
        "direction_rows": _direction_count_rows(direction_counts),
        "direction_summary": _direction_summary(direction_counts),
        "meaning": _email_evidence_meaning(
            event_count,
            direction_counts,
            analyzed_count,
            status_counts,
        ),
        "service_summary": _service_summary(service_counts),
        "primary_takeaway": _email_primary_takeaway(
            event_count,
            direction_counts,
            analyzed_count,
            insight_cards,
            status_counts,
        ),
        "pipeline_summary": _email_pipeline_summary(
            event_count,
            analyzed_count,
            status_counts,
        ),
        "quality_summary": _email_quality_summary(
            event_count,
            feed_count,
            analyzed_count,
            status_counts,
        ),
        "insight_cards": insight_cards,
        "rows": events,
        "feed_rows": feed_rows,
        "paired_rows": _candidate_email_paired_rows(events, feed_rows, limit=limit),
        "status_label": status_label,
        "status_class": status_class,
        "detail": _email_evidence_detail(
            event_count,
            feed_count,
            analyzed_count,
            status_counts,
        ),
    }

def candidate_news_evidence(
    ticker: str,
    *,
    news_path: Path = NEWS_RSS_PATH,
    news_consumption_ledger_path: Path = NEWS_CONSUMPTION_LEDGER_PATH,
    limit: int = 5,
) -> dict[str, object]:
    normalized = ticker.upper()
    frame = _read_candidate_news_frame(news_path)
    consumption_entries = load_news_consumption_entries(news_consumption_ledger_path)
    if frame.empty:
        return {
            "ticker": normalized,
            "resolved_count": 0,
            "used_count": 0,
            "unused_resolved_count": 0,
            "unresolved_context_count": 0,
            "latest_at": "None",
            "status_label": "No RSS Evidence",
            "status_class": "neutral",
            "coverage_summary": "No RSS/news rows are available for this ticker.",
            "consumption_summary": "No RSS/news headline has been used for this ticker yet.",
            "context_summary": "No unresolved generic RSS rows are available for context.",
            "rows": [],
            "context_rows": [],
        }

    if "ticker" in frame.columns:
        ticker_values = frame["ticker"].astype(str).str.upper()
        ticker_mask = ticker_values.eq(normalized)
    else:
        ticker_mask = pd.Series(False, index=frame.index)
    status_values = (
        frame["ticker_match_status"].apply(_candidate_news_match_status)
        if "ticker_match_status" in frame.columns
        else pd.Series("feed_ticker", index=frame.index)
    )
    source_tier_values = (
        frame["source_tier"].astype(str)
        if "source_tier" in frame.columns
        else pd.Series("", index=frame.index)
    )
    scored_mask = ticker_mask & status_values.isin({"resolved", "feed_ticker"})
    scored_mask &= ~source_tier_values.eq("PAID_SUB_EMAIL")
    context_mask = status_values.isin({"unresolved", "ambiguous"})
    if "ticker" in frame.columns:
        clean_tickers = frame["ticker"].map(_clean_text)
        context_mask &= clean_tickers.isna()

    resolved_frame = frame[scored_mask].copy()
    context_frame = frame[context_mask].copy()
    if "timestamp_as_of" in resolved_frame.columns:
        resolved_frame = resolved_frame.sort_values("timestamp_as_of", ascending=False)
    if "timestamp_as_of" in context_frame.columns:
        context_frame = context_frame.sort_values("timestamp_as_of", ascending=False)
    used_count = _candidate_news_used_count(resolved_frame, consumption_entries)
    unused_resolved_count = max(0, len(resolved_frame) - used_count)

    rows = [
        _candidate_news_row(
            row,
            normalized,
            signal_use="Ticker news signal",
            consumption_entries=consumption_entries,
        )
        for row in _records(resolved_frame.head(limit))
    ]
    context_rows = [
        _candidate_news_row(
            row,
            normalized,
            signal_use="Context only",
            consumption_entries=consumption_entries,
        )
        for row in _records(context_frame.head(limit))
    ]
    latest_at = _latest_text([*rows, *context_rows])
    return {
        "ticker": normalized,
        "resolved_count": len(resolved_frame),
        "used_count": used_count,
        "unused_resolved_count": unused_resolved_count,
        "unresolved_context_count": len(context_frame),
        "latest_at": latest_at or "None",
        "status_label": "RSS Resolved" if len(resolved_frame) else "Context Only",
        "status_class": "pass" if len(resolved_frame) else "warn",
        "coverage_summary": _candidate_news_coverage_summary(
            normalized,
            resolved_count=len(resolved_frame),
            context_count=len(context_frame),
        ),
        "consumption_summary": _candidate_news_consumption_summary(
            normalized,
            used_count=used_count,
            unused_resolved_count=unused_resolved_count,
        ),
        "context_summary": _candidate_news_context_summary(normalized, len(context_frame)),
        "rows": rows,
        "context_rows": context_rows,
    }

def candidate_email_evidence_with_judgement(
    ticker: str,
    evidence: Mapping[str, object],
    latest_report: Mapping[str, object] | None,
) -> dict[str, object]:
    context = _email_judgement_context(ticker, latest_report)
    rows = [
        _email_event_with_judgement(row, context)
        for row in _mapping_rows(evidence, "rows")
    ]
    insight_cards = [
        _email_event_with_judgement(card, context)
        for card in _mapping_rows(evidence, "insight_cards")
    ]
    output = dict(evidence)
    output["rows"] = rows
    output["insight_cards"] = insight_cards
    output["judgement_summary"] = _email_judgement_summary(context, insight_cards)
    output["primary_takeaway"] = _email_primary_takeaway_with_judgement(
        str(evidence.get("primary_takeaway", "")),
        insight_cards,
    )
    output["paired_rows"] = _candidate_email_paired_rows(
        rows,
        _mapping_rows(evidence, "feed_rows"),
        limit=max(len(rows), 1),
    )
    return output

def _email_event_with_judgement(
    event: Mapping[str, object],
    context: Mapping[str, object],
) -> dict[str, object]:
    contribution, tone = _email_judgement_contribution(event, context)
    return {
        **dict(event),
        "judgement_label": f"Contribution To {context['ticker']} Judgment",
        "judgement_contribution": contribution,
        "judgement_class": tone,
    }

def _email_judgement_context(
    ticker: str,
    latest_report: Mapping[str, object] | None,
) -> dict[str, object]:
    normalized = ticker.upper()
    if latest_report is None:
        return {
            "ticker": normalized,
            "has_report": False,
            "action": "NONE",
            "action_label": "No current judgment",
            "state_label": "Waiting For Runtime",
            "gate_status": "UNKNOWN",
            "support": "",
            "caution": "",
            "judgement": (
                f"{normalized} has no current selection report, so email evidence is "
                "stored as research context only."
            ),
        }
    action = str(latest_report["action"])
    gate_status = str(latest_report["gate_status"])
    signals = [
        *_mapping_rows(latest_report, "actionable_signals"),
        *_mapping_rows(latest_report, "context_signals"),
        *_mapping_rows(latest_report, "suppressed_signals"),
    ]
    support = _first_signal_summary(signals, "BULLISH") or ""
    caution = _first_signal_summary(signals, "BEARISH") or ""
    conviction = _int_field(latest_report, "conviction_pct")
    return {
        "ticker": normalized,
        "has_report": True,
        "action": action,
        "action_label": _candidate_action_label(action),
        "state_label": _candidate_state_label(action, gate_status),
        "gate_status": gate_status,
        "support": support,
        "caution": caution,
        "judgement": (
            f"{normalized} current judgment is {_candidate_state_label(action, gate_status)} "
            f"({_candidate_action_label(action)}), conviction {conviction}%, gate {gate_status}."
        ),
    }

def _email_judgement_contribution(
    event: Mapping[str, object],
    context: Mapping[str, object],
) -> tuple[str, str]:
    ticker = str(context["ticker"])
    judgement = str(context["judgement"])
    status = _row_text(event, "linked_content_status", "not_requested")
    direction = _row_text(
        event,
        "article_direction",
        _row_text(event, "direction", "NEUTRAL"),
    ).upper()
    focus = _row_text(event, "article_focus")
    relevance = _row_text(event, "ticker_relevance", _row_text(event, "relevance"))
    catalysts = _row_text(event, "catalyst_text")
    risks = _row_text(event, "risk_text")
    if context.get("has_report") is not True:
        return (
            f"{judgement} This item cannot affect a judgment yet; it will be available "
            "as subscription context after the next runtime cycle.",
            "neutral",
        )
    if not _is_email_article_analyzed_status(status):
        return (
            f"{judgement} This email does not change the judgment yet because only the "
            f"mailbox headline was available for {ticker}. Open/analyze the linked article "
            "before using it as evidence.",
            "warn",
        )
    if "secondary context" in focus.lower():
        return _secondary_email_contribution(
            context=context,
            relevance=relevance,
            catalysts=catalysts,
            risks=risks,
        )
    return _direct_email_contribution(
        context=context,
        direction=direction,
        relevance=relevance,
        catalysts=catalysts,
        risks=risks,
    )

def _secondary_email_contribution(
    *,
    context: Mapping[str, object],
    relevance: str,
    catalysts: str,
    risks: str,
) -> tuple[str, str]:
    ticker = str(context["ticker"])
    action_label = str(context["action_label"])
    support = str(context["support"])
    caution = str(context["caution"])
    detail = (
        f"For the current {ticker} {action_label} judgment, this contributes only "
        f"secondary theme or basket context. {relevance}"
    )
    if catalysts:
        detail += f" It adds background drivers: {catalysts}."
    if risks:
        detail += f" It adds watch items: {risks}."
    if support:
        detail += f" It does not replace the direct driver already recorded: {support}"
    if caution:
        detail += f" Main caution still remains: {caution}"
    return detail, "warn"

def _direct_email_contribution(
    *,
    context: Mapping[str, object],
    direction: str,
    relevance: str,
    catalysts: str,
    risks: str,
) -> tuple[str, str]:
    ticker = str(context["ticker"])
    action = str(context["action"])
    action_label = str(context["action_label"])
    gate_status = str(context["gate_status"])
    support = str(context["support"])
    caution = str(context["caution"])
    relation, tone = _email_relation_to_judgement(action, direction)
    detail = (
        f"For the current {ticker} {action_label} judgment, this {relation}. "
        f"{relevance}"
    )
    if catalysts:
        detail += f" Contribution: adds {catalysts} to the stock-specific analysis."
    if risks:
        detail += f" Risk contribution: adds {risks} to the watch list."
    if support and direction == "BULLISH":
        detail += f" It reinforces existing constructive evidence: {support}"
    if caution and direction == "BEARISH":
        detail += f" It reinforces existing caution: {caution}"
    if gate_status == "BLOCK":
        detail += " It does not override the active blocking gate."
        tone = "block"
    return detail, tone

def _email_relation_to_judgement(action: str, direction: str) -> tuple[str, str]:
    constructive_actions = {"BUY", "WATCH", "HOLD", "COVER"}
    bearish_actions = {"SELL", "SHORT"}
    reject_actions = {"NO_TRADE", "CLOSE_REVIEW"}
    relation = "adds context to the judgment"
    tone = "neutral"
    if action in constructive_actions:
        if direction == "BULLISH":
            relation = "supports the judgment but remains context until corroborated"
            tone = "pass"
        elif direction == "BEARISH":
            relation = "weakens the judgment and raises the review burden"
            tone = "block"
    elif action in bearish_actions:
        if direction == "BEARISH":
            relation = "supports the bearish judgment but still needs corroboration"
            tone = "pass"
        elif direction == "BULLISH":
            relation = "conflicts with the bearish judgment and should be reviewed"
            tone = "warn"
    elif action in reject_actions:
        if direction == "BEARISH":
            relation = "supports the rejection or hold-back decision"
            tone = "pass"
        elif direction == "BULLISH":
            relation = "conflicts with the rejection but is not enough by itself to reverse it"
            tone = "warn"
    return relation, tone

def _email_judgement_summary(
    context: Mapping[str, object],
    insight_cards: Sequence[Mapping[str, object]],
) -> str:
    if not insight_cards:
        return f"{context['judgement']} No subscription article analysis is attached to this ticker yet."
    top = insight_cards[0]
    contribution = _row_text(top, "judgement_contribution")
    return _clip_text(contribution or str(context["judgement"]), 360)

def _email_primary_takeaway_with_judgement(
    primary_takeaway: str,
    insight_cards: Sequence[Mapping[str, object]],
) -> str:
    if not insight_cards:
        return primary_takeaway
    contribution = _row_text(insight_cards[0], "judgement_contribution")
    if not contribution:
        return primary_takeaway
    return _clip_text(f"{primary_takeaway} Judgment contribution: {contribution}", 520)

def _candidate_email_event_rows(
    ticker: str,
    *,
    event_path: Path,
    limit: int | None,
) -> list[dict[str, object]]:
    frame = _ticker_frame(event_path, ticker)
    if frame.empty:
        return []
    if "timestamp_as_of" in frame.columns:
        frame = frame.sort_values("timestamp_as_of", ascending=False)
    rows: list[dict[str, object]] = []
    for row in _records(frame):
        source_url = _clean_text(row.get("source_url"))
        linked_url = _clean_text(row.get("linked_content_url"))
        raw_status = _clean_text(row.get("linked_content_status")) or "not_requested"
        status = _normalized_linked_content_status(
            raw_status,
            source_url=source_url,
            linked_url=linked_url,
        )
        linked_summary = _clean_text(row.get("linked_content_summary"))
        title = _clean_text(row.get("title"))
        article_direction = (
            _clean_text(row.get("linked_content_direction"))
            or _clean_text(row.get("direction"))
            or "NEUTRAL"
        ).upper()
        direction = (_clean_text(row.get("direction")) or article_direction).upper()
        source_id = _clean_text(row.get("source_id"))
        message_id_hash = _clean_text(row.get("message_id_hash"))
        raw_thesis = _clean_text(row.get("linked_content_thesis")) or _legacy_linked_thesis(
            linked_summary
        )
        key_points = _object_strings(row.get("linked_content_key_points"))
        catalysts = _object_strings(row.get("linked_content_catalysts"))
        risks = _object_strings(row.get("linked_content_risk_flags"))
        decision_use = _email_dashboard_decision_use(
            ticker=ticker,
            title=title,
            status=status,
            direction=article_direction,
            default=_clean_text(row.get("linked_content_decision_use")),
        )
        event_type = _clean_text(row.get("event_type"))
        timestamp = _clean_text(row.get("timestamp_as_of")) or "unknown"
        ticker_relevance = _email_ticker_relevance(
            ticker=ticker,
            title=title,
            status=status,
            direction=article_direction,
            event_type=event_type,
            catalysts=catalysts,
            risks=risks,
        )
        thesis = _email_ticker_thesis(
            ticker=ticker,
            title=title,
            status=status,
            direction=article_direction,
            event_type=event_type,
            raw_thesis=raw_thesis,
            catalysts=catalysts,
            risks=risks,
        )
        rows.append(
            {
                "ticker": ticker,
                "service": _service_label(_clean_text(row.get("service")) or "subscription"),
                "event_type": _label_text(_clean_text(row.get("event_type")) or "email evidence"),
                "direction": direction,
                "direction_class": _direction_class(direction),
                "article_direction": article_direction,
                "linked_content_status": status,
                "linked_status_label": _linked_status_label(status),
                "linked_status_class": _linked_status_class(status),
                "timestamp": timestamp,
                "timestamp_label": _format_timestamp_label(timestamp),
                "detail": _linked_status_detail(status),
                "title": _clip_text(title or "Subscription email evidence", 120),
                "headline": _email_headline(title),
                "article_focus": _email_article_focus(title, ticker),
                "ticker_relevance": ticker_relevance,
                "article_summary": linked_summary or "",
                "thesis": thesis or "",
                "key_points": key_points,
                "key_point_text": _human_list(key_points),
                "catalysts": catalysts,
                "catalyst_text": _human_list([_email_taxonomy_label(item) for item in catalysts]),
                "risks": risks,
                "risk_text": _human_list([_email_taxonomy_label(item) for item in risks]),
                "decision_use": _sentence_case(decision_use),
                "signal_strength": _clean_text(row.get("linked_content_signal_strength")) or "",
                "context_chars": _int_or_none(row.get("linked_content_context_chars")),
                "summary": _mailbox_event_summary(
                    title=title,
                    status=status,
                    linked_summary=linked_summary,
                    direction=article_direction,
                    event_type=event_type,
                    ticker=ticker,
                    ticker_relevance=ticker_relevance,
                ),
                "source_id": source_id or "",
                "source_id_core": _source_id_core(source_id) or "",
                "source_url": source_url or "",
                "message_id_hash": message_id_hash or "",
                "event_type_raw": event_type or "",
            }
        )
    deduped = _dedupe_email_event_rows(rows)
    return deduped[:limit] if limit is not None else deduped

def _normalized_linked_content_status(
    status: str,
    *,
    source_url: str | None,
    linked_url: str | None,
) -> str:
    if status in {"article_fetch_limited", "article_fetch_failed"} and (
        _email_non_article_asset_url(linked_url)
        or _email_non_article_asset_url(source_url)
    ):
        return "non_article_link"
    return status

def _is_email_article_analyzed_status(status: str) -> bool:
    return status in EMAIL_ANALYZED_STATUSES

def _email_non_article_asset_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlsplit(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()
    if any(domain.startswith(prefix) for prefix in EMAIL_ASSET_DOMAIN_PREFIXES):
        return True
    return any(path.endswith(extension) for extension in EMAIL_ASSET_EXTENSIONS)

def _candidate_email_feed_rows(
    ticker: str,
    *,
    news_path: Path,
    limit: int | None,
) -> list[dict[str, object]]:
    frame = _ticker_frame(news_path, ticker)
    if frame.empty or "source_tier" not in frame.columns:
        return []
    frame = frame[frame["source_tier"].astype(str).eq("PAID_SUB_EMAIL")]
    if frame.empty:
        return []
    if "timestamp_as_of" in frame.columns:
        frame = frame.sort_values("timestamp_as_of", ascending=False)
    rows: list[dict[str, object]] = []
    for row in _records(frame):
        title = _clean_text(row.get("title"))
        summary = _clean_text(row.get("summary"))
        source_id = _clean_text(row.get("source_id"))
        source_url = _clean_text(row.get("source_url")) or _clean_text(row.get("url"))
        timestamp = _clean_text(row.get("timestamp_as_of")) or "unknown"
        rows.append(
            {
                "feed_name": _service_label(_clean_text(row.get("feed_name")) or "email feed"),
                "title": _clip_text(title or "Email-derived feed item", 110),
                "summary": _clip_text(summary or "No summary recorded", 180),
                "timestamp": timestamp,
                "timestamp_label": _format_timestamp_label(timestamp),
                "source_id": source_id or "",
                "source_id_core": _source_id_core(source_id) or "",
                "source_url": source_url or "",
            }
        )
    deduped = _dedupe_email_feed_rows(rows)
    return deduped[:limit] if limit is not None else deduped

def _read_candidate_news_frame(news_path: Path) -> pd.DataFrame:
    if not news_path.is_file():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(news_path)
    except (OSError, ValueError, ImportError):
        return pd.DataFrame()
    return frame

def _candidate_news_row(
    row: Mapping[str, object],
    ticker: str,
    *,
    signal_use: str,
    consumption_entries: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    timestamp = _clean_text(row.get("timestamp_as_of")) or "unknown"
    status = _candidate_news_match_status(row.get("ticker_match_status"))
    source_id = _clean_text(row.get("source_id")) or ""
    consumption_entry = consumption_entries.get(source_id, {})
    already_used = bool(consumption_entry)
    return {
        "ticker": _row_text(row, "ticker", ticker).upper(),
        "feed_name": _candidate_news_feed_label(row.get("feed_name")),
        "title": _clip_text(_clean_text(row.get("title")) or "RSS/news headline", 140),
        "summary": _clip_text(_clean_text(row.get("summary")) or "No summary recorded", 220),
        "timestamp": timestamp,
        "timestamp_label": _format_timestamp_label(timestamp),
        "source_id": source_id,
        "source_id_core": _source_id_core(source_id) or "",
        "source_url": _clean_text(row.get("source_url")) or _clean_text(row.get("url")) or "",
        "match_status_label": _candidate_news_status_label(status),
        "match_method_label": _candidate_news_method_label(row.get("ticker_match_method")),
        "match_confidence": _candidate_news_confidence(row.get("ticker_match_confidence")),
        "matched_text": _clean_text(row.get("matched_text")) or "",
        "match_reason": _clip_text(_clean_text(row.get("ticker_match_reason")) or "", 180),
        "match_explanation": _candidate_news_match_explanation(row, ticker),
        "signal_use": (
            "Already used in prior live decision"
            if already_used and signal_use == "Ticker news signal"
            else signal_use
        ),
        "already_used": already_used,
        "consumption_note": _candidate_news_consumption_note(consumption_entry),
    }

def _candidate_news_match_explanation(
    row: Mapping[str, object],
    ticker: str,
) -> str:
    feed = _candidate_news_feed_label(row.get("feed_name"))
    status = _candidate_news_match_status(row.get("ticker_match_status"))
    if status in {"unresolved", "ambiguous"}:
        reason = (
            "multiple possible ticker matches need review"
            if status == "ambiguous"
            else "no high-confidence ticker match was found"
        )
        return (
            f"Generic {feed} headline collected but not attached to {ticker} "
            f"because {reason}."
        )
    method = _candidate_news_method_label(row.get("ticker_match_method"))
    matched = _clean_text(row.get("matched_text"))
    confidence = _candidate_news_confidence(row.get("ticker_match_confidence"))
    if matched:
        return (
            f'{feed} matched {ticker} by {method} "{matched}"; '
            f"confidence {confidence:.2f}."
        )
    match_reason = _clean_text(row.get("ticker_match_reason"))
    if match_reason:
        return (
            f"{feed} matched {ticker} by {method}; confidence {confidence:.2f}. "
            f"{match_reason}"
        )
    return f"{feed} matched {ticker} by {method}; confidence {confidence:.2f}."

def _candidate_news_feed_label(value: object) -> str:
    return _clean_text(value) or "RSS/news"

def _candidate_news_match_status(value: object) -> str:
    status = (_clean_text(value) or "feed_ticker").lower()
    if status in {"resolved", "feed_ticker", "unresolved", "ambiguous"}:
        return status
    return "unresolved"

def _candidate_news_status_label(status: str) -> str:
    labels = {
        "resolved": "Ticker Matched",
        "feed_ticker": "Ticker Feed",
        "unresolved": "Context Only",
        "ambiguous": "Needs Review",
    }
    return labels.get(status, _label_text(status))

def _candidate_news_method_label(value: object) -> str:
    method = (_clean_text(value) or "feed ticker").lower()
    labels = {
        "legal_name": "legal name",
        "ticker_symbol": "ticker symbol",
        "feed_ticker": "ticker feed",
        "alias": "alias",
        "cik": "SEC CIK",
    }
    return labels.get(method, method.replace("_", " "))

def _candidate_news_confidence(value: object) -> float:
    if isinstance(value, bool) or value is None:
        return 1.0
    if not isinstance(value, int | float | str):
        return 1.0
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 1.0
    if pd.isna(confidence):
        return 1.0
    return max(0.0, min(confidence, 1.0))

def _candidate_news_coverage_summary(
    ticker: str,
    *,
    resolved_count: int,
    context_count: int,
) -> str:
    if resolved_count:
        return (
            f"{resolved_count} RSS/news headline(s) are attached to {ticker} "
            "with explicit ticker-match evidence."
        )
    if context_count:
        return (
            f"No RSS/news headline is attached to {ticker}. Generic headlines are "
            "shown as context only until a high-confidence ticker match exists."
        )
    return f"No RSS/news headline currently matches {ticker}."

def _candidate_news_used_count(
    frame: pd.DataFrame,
    consumption_entries: Mapping[str, Mapping[str, object]],
) -> int:
    if frame.empty or "source_id" not in frame.columns:
        return 0
    source_ids = {
        str(value).strip()
        for value in frame["source_id"].to_list()
        if str(value).strip()
    }
    return len(source_ids.intersection(consumption_entries))


def _candidate_news_consumption_summary(
    ticker: str,
    *,
    used_count: int,
    unused_resolved_count: int,
) -> str:
    if used_count:
        return (
            f"{used_count} resolved RSS/news headline(s) for {ticker} were already "
            f"used by prior live cycle(s). {unused_resolved_count} resolved headline(s) "
            "remain available for automatic news scoring."
        )
    if unused_resolved_count:
        return (
            f"{unused_resolved_count} resolved RSS/news headline(s) for {ticker} "
            "remain available for automatic news scoring."
        )
    return f"No resolved RSS/news headline for {ticker} has been consumed yet."


def _candidate_news_consumption_note(entry: Mapping[str, object]) -> str:
    if not entry:
        return "Not used by a prior live decision cycle."
    cycle_id = _clean_text(entry.get("cycle_id")) or "unknown cycle"
    used_at = _format_timestamp_label(entry.get("used_at"))
    return (
        f"Already used by cycle {cycle_id} at {used_at}; "
        "the live news lane will not reuse this headline automatically."
    )


def _candidate_news_context_summary(ticker: str, context_count: int) -> str:
    if context_count:
        return (
            f"{context_count} unresolved generic RSS headline(s) were collected, "
            f"but they are not used as {ticker} signals."
        )
    return "No unresolved generic RSS context rows are currently waiting for ticker resolution."

def _dedupe_email_event_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    selected: dict[tuple[str, ...], dict[str, object]] = {}
    for row in rows:
        row_dict = dict(row)
        key = _email_event_dedupe_key(row_dict)
        existing = selected.get(key)
        if existing is None or _email_event_priority(row_dict) > _email_event_priority(existing):
            selected[key] = row_dict
    return sorted(
        selected.values(),
        key=lambda row: _timestamp_sort_value(row.get("timestamp")),
        reverse=True,
    )

def _dedupe_email_feed_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    selected: dict[tuple[str, ...], dict[str, object]] = {}
    for row in rows:
        row_dict = dict(row)
        key = _email_feed_dedupe_key(row_dict)
        existing = selected.get(key)
        row_timestamp = _timestamp_sort_value(row_dict.get("timestamp"))
        existing_timestamp = (
            _timestamp_sort_value(existing.get("timestamp"))
            if existing is not None
            else 0.0
        )
        if existing is None or row_timestamp > existing_timestamp:
            selected[key] = row_dict
    return sorted(
        selected.values(),
        key=lambda row: _timestamp_sort_value(row.get("timestamp")),
        reverse=True,
    )

def _email_event_dedupe_key(row: Mapping[str, object]) -> tuple[str, ...]:
    ticker = _dedupe_text(_row_text(row, "ticker", "ticker"))
    title = _dedupe_text(_row_text(row, "headline", _row_text(row, "title")))
    message_hash = _dedupe_text(_row_text(row, "message_id_hash"))
    if message_hash and title:
        return (ticker, "message", message_hash, title)
    source_url = _dedupe_text(_row_text(row, "source_url"))
    if source_url and title:
        return (ticker, "url", source_url, title)
    source_id_core = _dedupe_text(_row_text(row, "source_id_core", _row_text(row, "source_id")))
    if source_id_core and title:
        return (ticker, "source", source_id_core, title)
    timestamp = _dedupe_text(_row_text(row, "timestamp"))
    return (ticker, "title", title or "untitled", timestamp or "unknown")

def _email_feed_dedupe_key(row: Mapping[str, object]) -> tuple[str, ...]:
    title = _dedupe_text(_row_text(row, "title"))
    source_id_core = _dedupe_text(_row_text(row, "source_id_core", _row_text(row, "source_id")))
    if source_id_core and title:
        return ("feed", "source", source_id_core, title)
    source_url = _dedupe_text(_row_text(row, "source_url"))
    if source_url and title:
        return ("feed", "url", source_url, title)
    timestamp = _dedupe_text(_row_text(row, "timestamp"))
    return ("feed", "title", title or "untitled", timestamp or "unknown")

def _email_event_priority(row: Mapping[str, object]) -> tuple[int, int, int, float]:
    status = _row_text(row, "linked_content_status", "not_requested")
    text_richness = sum(
        len(_row_text(row, key))
        for key in ("article_summary", "thesis", "ticker_relevance", "judgement_contribution")
    )
    return (
        EMAIL_LINKED_STATUS_PRIORITY.get(status, 0),
        _int_or_none(row.get("context_chars")) or 0,
        text_richness,
        _timestamp_sort_value(row.get("timestamp")),
    )

def _candidate_email_paired_rows(
    events: Sequence[Mapping[str, object]],
    feed_rows: Sequence[Mapping[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    unmatched_feeds = list(feed_rows)
    paired: list[dict[str, object]] = []
    for event in events:
        feed = _pop_best_email_feed_match(event, unmatched_feeds)
        paired.append(_candidate_email_pair_row(event=event, feed=feed))
    for feed in unmatched_feeds:
        if len(paired) >= limit:
            break
        paired.append(_candidate_email_pair_row(event=None, feed=feed))
    return sorted(paired, key=lambda row: str(row["timestamp"]), reverse=True)[:limit]

def _pop_best_email_feed_match(
    event: Mapping[str, object],
    feed_rows: list[Mapping[str, object]],
) -> Mapping[str, object] | None:
    best_index: int | None = None
    best_score = 0
    for index, feed in enumerate(feed_rows):
        score = _candidate_email_match_score(event, feed)
        if score > best_score:
            best_index = index
            best_score = score
    if best_index is None or best_score < MIN_EMAIL_PAIR_SCORE:
        return None
    return feed_rows.pop(best_index)

def _candidate_email_match_score(
    event: Mapping[str, object],
    feed: Mapping[str, object],
) -> int:
    score = 0
    if _same_pair_text(event.get("source_url"), feed.get("source_url")):
        score += 5
    if _same_pair_text(event.get("source_id_core"), feed.get("source_id_core")):
        score += 4
    message_hash = _pair_text(event.get("message_id_hash"))
    feed_source_id = _pair_text(feed.get("source_id"))
    if message_hash and feed_source_id and message_hash in feed_source_id:
        score += 4
    if _same_pair_text(event.get("title"), feed.get("title")):
        score += 3
    if _same_pair_text(event.get("timestamp"), feed.get("timestamp")):
        score += 2
    if _same_pair_text(event.get("service"), feed.get("feed_name")):
        score += 1
    return score

def _candidate_email_pair_row(
    *,
    event: Mapping[str, object] | None,
    feed: Mapping[str, object] | None,
) -> dict[str, object]:
    timestamp = _row_text(event, "timestamp") or _row_text(feed, "timestamp") or "unknown"
    timestamp_label = (
        _row_text(event, "timestamp_label")
        or _row_text(feed, "timestamp_label")
        or _format_timestamp_label(timestamp)
    )
    direction = (_row_text(event, "direction") or "NEUTRAL").upper()
    return {
        "timestamp": timestamp,
        "timestamp_label": timestamp_label,
        "direction": direction,
        "direction_class": _direction_class(direction),
        "has_mailbox": event is not None,
        "has_interpretation": feed is not None,
        "mailbox": _candidate_email_mailbox_cell(event, timestamp_label),
        "interpretation": _candidate_email_interpretation_cell(
            feed=feed,
            event=event,
            timestamp=timestamp_label,
        ),
    }

def _candidate_email_mailbox_cell(
    event: Mapping[str, object] | None,
    timestamp: str,
) -> dict[str, str]:
    if event is None:
        return {
            "title": "No matching mailbox alert",
            "meta": f"Feed row only / {timestamp}",
            "summary": (
                "A normalized evidence row exists, but its source email is not in the "
                "recent mailbox evidence set."
            ),
            "status_label": "Feed Only",
            "status_class": "neutral",
        }
    return {
        "title": _row_text(event, "title", "Subscription email evidence"),
        "meta": (
            f"{_row_text(event, 'service', 'Email')} / "
            f"{_row_text(event, 'event_type', 'Evidence')} / {timestamp}"
        ),
        "summary": _row_text(event, "summary", _linked_status_detail("not_requested")),
        "status_label": _row_text(event, "linked_status_label", "Email Matched"),
        "status_class": _row_text(event, "linked_status_class", "neutral"),
    }

def _candidate_email_interpretation_cell(
    *,
    feed: Mapping[str, object] | None,
    event: Mapping[str, object] | None,
    timestamp: str,
) -> dict[str, str]:
    if feed is None:
        contribution = _row_text(event, "judgement_contribution")
        summary = (
            contribution
            if contribution
            else (
                "This mailbox alert matched the ticker, but no recent email-derived "
                "feed row is available for it yet."
            )
        )
        return {
            "title": "Waiting for evidence row",
            "meta": f"Not normalized / {timestamp}",
            "summary": _clip_text(summary, 620),
            "status_label": "Pending",
            "status_class": "warn",
        }
    linked_status = _row_text(event, "linked_content_status", "not_requested")
    return {
        "title": _row_text(feed, "title", "Email-derived feed item"),
        "meta": f"{_row_text(feed, 'feed_name', 'Email Feed')} / {timestamp}",
        "summary": _email_interpretation_summary(feed=feed, event=event),
        "status_label": _email_interpretation_status_label(linked_status),
        "status_class": _email_interpretation_status_class(linked_status),
    }

def _email_interpretation_status_label(status: str) -> str:
    labels = {
        "article_analyzed": "Article Thesis",
        "article_analyzed_deterministic_fallback": "Keyword-Only Thesis",
        "article_analyzed_no_ticker_match": "No Ticker Match",
        "article_fetch_failed": "Open Failed",
        "article_fetch_limited": "Queued",
        "non_article_link": "Headline Row",
        "no_allowed_article_link": "Headline Row",
        "not_requested": "Headline Row",
    }
    return labels.get(status, "Evidence Row")

def _email_interpretation_status_class(status: str) -> str:
    if status == "article_analyzed_deterministic_fallback":
        return "warn"
    if _is_email_article_analyzed_status(status):
        return "pass"
    if status in {"article_fetch_failed", "article_fetch_limited"}:
        return "warn"
    return "neutral"

def _candidate_email_count(ticker: str, event_path: Path) -> int:
    return len(_ticker_frame(event_path, ticker))

def _candidate_email_analyzed_count(ticker: str, event_path: Path) -> int:
    frame = _ticker_frame(event_path, ticker)
    if frame.empty or "linked_content_status" not in frame.columns:
        return 0
    return int(frame["linked_content_status"].astype(str).isin(EMAIL_ANALYZED_STATUSES).sum())

def _candidate_email_feed_count(ticker: str, news_path: Path) -> int:
    frame = _ticker_frame(news_path, ticker)
    if frame.empty or "source_tier" not in frame.columns:
        return 0
    return int(frame[frame["source_tier"].astype(str).eq("PAID_SUB_EMAIL")].shape[0])

def _candidate_email_service_counts(ticker: str, event_path: Path) -> Counter[str]:
    frame = _ticker_frame(event_path, ticker)
    if frame.empty or "service" not in frame.columns:
        return Counter()
    return Counter(
        _service_label(_clean_text(service) or "subscription")
        for service in frame["service"].to_list()
    )

def _candidate_email_direction_counts(ticker: str, event_path: Path) -> Counter[str]:
    frame = _ticker_frame(event_path, ticker)
    if frame.empty or "direction" not in frame.columns:
        return Counter()
    return Counter(
        (_clean_text(direction) or "NEUTRAL").upper()
        for direction in frame["direction"].to_list()
    )

def _ticker_frame(path: Path, ticker: str) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    try:
        frame = pd.read_parquet(path)
    except (OSError, ValueError, ImportError):
        return pd.DataFrame()
    if "ticker" not in frame.columns:
        return pd.DataFrame()
    return frame[frame["ticker"].astype(str).str.upper().eq(ticker.upper())].copy()

def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], frame.to_dict(orient="records"))

def _latest_text(rows: Sequence[Mapping[str, object]]) -> str | None:
    values = [str(row["timestamp"]) for row in rows if row.get("timestamp")]
    return max(values) if values else None

def _service_summary(counts: Counter[str]) -> str:
    if not counts:
        return "No matching email services"
    return ", ".join(
        f"{_service_label(service)} {count}"
        for service, count in counts.most_common()
    )

def _direction_count_rows(counts: Counter[str]) -> list[dict[str, object]]:
    directions = ("BULLISH", "BEARISH", "NEUTRAL")
    return [
        {
            "label": direction.title(),
            "direction": direction,
            "count": counts.get(direction, 0),
            "status_class": _direction_class(direction),
        }
        for direction in directions
        if counts.get(direction, 0) > 0
    ]

def _direction_summary(counts: Counter[str]) -> str:
    rows = _direction_count_rows(counts)
    if not rows:
        return "No directional email evidence"
    return ", ".join(f"{row['label']} {row['count']}" for row in rows)

def _email_evidence_status(event_count: int, analyzed_count: int) -> tuple[str, str]:
    if analyzed_count:
        return "Article Thesis Ready", "pass"
    if event_count:
        return "Headline Evidence", "warn"
    return "No Email Evidence", "neutral"

def _email_status_summary(status_counts: Counter[str]) -> str:
    if not status_counts:
        return "No email article status"
    return ", ".join(
        f"{_linked_status_label(status)} {count}"
        for status, count in status_counts.most_common()
    )

def _email_analysis_gap_summary(status_counts: Counter[str]) -> str:
    parts: list[str] = []
    limited = status_counts.get("article_fetch_limited", 0)
    failed = status_counts.get("article_fetch_failed", 0)
    no_allowed = status_counts.get("no_allowed_article_link", 0)
    non_article = status_counts.get("non_article_link", 0)
    not_requested = status_counts.get("not_requested", 0)
    keyword_only = status_counts.get("article_analyzed_deterministic_fallback", 0)
    if keyword_only:
        parts.append(
            f"{keyword_only} {_plural('article', keyword_only)} used keyword-only analysis and need LLM/browser confirmation"
        )
    if limited:
        parts.append(
            f"{limited} {_plural('link', limited)} hit the safe per-run article limit"
        )
    if failed:
        parts.append(f"{failed} {_plural('link', failed)} failed to open")
    if no_allowed:
        parts.append(
            f"{no_allowed} {_plural('email', no_allowed)} had no allowlisted article link"
        )
    if non_article:
        parts.append(
            f"{non_article} {_plural('email', non_article)} exposed only static/non-article links"
        )
    if not_requested:
        parts.append(
            f"{not_requested} {_plural('email', not_requested)} remained headline-only"
        )
    other_count = sum(
        count
        for status, count in status_counts.items()
        if status
        not in {
            "article_analyzed",
            "article_analyzed_deterministic_fallback",
            "article_fetch_limited",
            "article_fetch_failed",
            "no_allowed_article_link",
            "non_article_link",
            "article_analyzed_no_ticker_match",
            "not_requested",
        }
    )
    if other_count:
        parts.append(f"{other_count} {_plural('email', other_count)} need review")
    return _human_list(parts)

def _email_analysis_gap_sentence(status_counts: Counter[str]) -> str:
    gap = _email_analysis_gap_summary(status_counts)
    if not gap:
        return ""
    return f"Pending link-analysis reason: {gap}."

def _candidate_email_insight_cards(
    events: Sequence[Mapping[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    prioritized = sorted(
        events,
        key=lambda row: (
            _is_email_article_analyzed_status(_row_text(row, "linked_content_status")),
            str(row.get("timestamp", "")),
        ),
        reverse=True,
    )
    cards: list[dict[str, object]] = []
    for event in prioritized[:limit]:
        direction = _row_text(event, "article_direction", _row_text(event, "direction", "NEUTRAL"))
        status = _row_text(event, "linked_content_status", "not_requested")
        thesis = _row_text(event, "thesis") or _headline_thesis(event)
        points = _object_strings(event.get("key_points"))
        cards.append(
            {
                "title": _row_text(event, "headline", "Subscription email alert"),
                "service": _row_text(event, "service", "Email"),
                "event_type": _row_text(event, "event_type", "Evidence"),
                "timestamp": _row_text(event, "timestamp", "unknown"),
                "timestamp_label": _row_text(
                    event,
                    "timestamp_label",
                    _format_timestamp_label(_row_text(event, "timestamp", "unknown")),
                ),
                "direction": direction.title(),
                "direction_class": _direction_class(direction.upper()),
                "article_direction": direction.upper(),
                "linked_content_status": status,
                "status_label": _row_text(event, "linked_status_label", "Headline Only"),
                "status_class": _row_text(event, "linked_status_class", "neutral"),
                "thesis": _clip_text(thesis, 260),
                "ticker_relevance": _row_text(event, "ticker_relevance", thesis),
                "relevance": _clip_text(
                    _row_text(event, "ticker_relevance", thesis),
                    360,
                ),
                "article_focus": _row_text(event, "article_focus", "Article focus unknown"),
                "key_points": points[:3],
                "key_point_text": _row_text(event, "key_point_text", "No catalyst bucket detected"),
                "catalyst_text": _row_text(event, "catalyst_text", "No catalyst bucket detected"),
                "risk_text": _row_text(event, "risk_text", "No explicit risk bucket detected"),
                "decision_use": _row_text(
                    event,
                    "decision_use",
                    _email_default_decision_use(status, direction),
                ),
            }
        )
    return cards

def _headline_thesis(event: Mapping[str, object]) -> str:
    direction = _row_text(event, "article_direction", _row_text(event, "direction", "NEUTRAL"))
    event_type = _email_event_label(_row_text(event, "event_type_raw"))
    headline = _row_text(event, "headline", "No headline recorded")
    status = _row_text(event, "linked_content_status", "not_requested")
    if status == "article_fetch_failed":
        prefix = (
            "The source email matched this ticker, but the linked article could not "
            "be analyzed"
        )
    elif status == "article_fetch_limited":
        prefix = (
            "The source email matched this ticker, but the safe article limit "
            "deferred analysis"
        )
    elif status == "no_allowed_article_link":
        prefix = "The source email matched this ticker without an allowlisted article link"
    else:
        prefix = "The source email is headline-level evidence"
    return f"{prefix}: {direction.lower()} {event_type}. Headline: {headline}"

def _email_primary_takeaway(
    event_count: int,
    direction_counts: Counter[str],
    analyzed_count: int,
    insight_cards: Sequence[Mapping[str, object]],
    status_counts: Counter[str],
) -> str:
    if event_count == 0:
        return "No paid subscription email evidence is attached to this ticker yet."
    balance = _email_balance_prefix(direction_counts)
    if insight_cards:
        top = insight_cards[0]
        direction = str(top["direction"]).lower()
        contradiction = _email_balance_contradicts_top(
            direction_counts,
            str(top["direction"]).upper(),
        )
        prefix = "However, the strongest" if contradiction else "Strongest"
        if analyzed_count:
            pending = _email_analysis_gap_sentence(status_counts)
            return _clip_text(
                f"{balance}{prefix} analyzed article signal is {direction}. "
                f"{_clip_text(str(top.get('relevance') or top['thesis']), 190)} "
                f"{pending}",
                520,
            )
        pending = _email_analysis_gap_sentence(status_counts)
        prefix = "However, the latest" if contradiction else "Latest"
        return _clip_text(
            f"{balance}{prefix} headline context is {direction}: "
            f"{_clip_text(str(top['thesis']), 170)} {pending}",
            520,
        )
    return _email_evidence_meaning(
        event_count,
        direction_counts,
        analyzed_count,
        status_counts,
    )

def _email_balance_prefix(direction_counts: Counter[str]) -> str:
    bullish = direction_counts.get("BULLISH", 0)
    bearish = direction_counts.get("BEARISH", 0)
    neutral = direction_counts.get("NEUTRAL", 0)
    if bullish > bearish:
        return f"Mailbox history leans bullish ({bullish} bullish vs {bearish} bearish). "
    if bearish > bullish:
        return f"Mailbox history leans bearish ({bearish} bearish vs {bullish} bullish). "
    if bullish or bearish:
        return f"Mailbox history is mixed ({bullish} bullish, {bearish} bearish). "
    return f"Mailbox history is mostly neutral ({neutral} neutral). "

def _email_balance_contradicts_top(direction_counts: Counter[str], top_direction: str) -> bool:
    bullish = direction_counts.get("BULLISH", 0)
    bearish = direction_counts.get("BEARISH", 0)
    return (
        (bullish > bearish and top_direction == "BEARISH")
        or (bearish > bullish and top_direction == "BULLISH")
    )

def _email_pipeline_summary(
    event_count: int,
    analyzed_count: int,
    status_counts: Counter[str],
) -> str:
    if analyzed_count:
        pending = _email_analysis_gap_sentence(status_counts)
        return _clip_text(
            "Analyzed article rows feed the subscription thesis context lane in the "
            "next runtime cycle. They help explain candidates but do not satisfy "
            f"evidence breadth by themselves. {pending}",
            420,
        )
    if event_count:
        pending = _email_analysis_gap_sentence(status_counts)
        return _clip_text(
            "Matched headlines are stored as paid-email evidence. The thesis lane waits "
            f"until an article body is analyzed. {pending}",
            420,
        )
    return "No subscription article thesis input is attached to this ticker yet."

def _email_quality_summary(
    event_count: int,
    feed_count: int,
    analyzed_count: int,
    status_counts: Counter[str],
) -> str:
    if event_count == 0:
        return "No mailbox matches, no normalized feed rows, and no linked article thesis."
    status_summary = _email_status_summary(status_counts)
    return (
        f"{event_count} {_plural('mailbox match', event_count)}, "
        f"{feed_count} normalized {_plural('feed row', feed_count)}, "
        f"{analyzed_count} analyzed article thesis {_plural('row', analyzed_count)}. "
        f"Status: {status_summary}."
    )

def _email_evidence_meaning(
    event_count: int,
    direction_counts: Counter[str],
    analyzed_count: int,
    status_counts: Counter[str],
) -> str:
    if event_count == 0:
        return "No subscription email intelligence is currently attached to this ticker."
    bullish = direction_counts.get("BULLISH", 0)
    bearish = direction_counts.get("BEARISH", 0)
    neutral = direction_counts.get("NEUTRAL", 0)
    if bullish > bearish:
        tilt = f"Email alerts lean bullish ({bullish} bullish vs {bearish} bearish)."
    elif bearish > bullish:
        tilt = f"Email alerts lean bearish ({bearish} bearish vs {bullish} bullish)."
    elif bullish or bearish:
        tilt = f"Email alerts are mixed ({bullish} bullish and {bearish} bearish)."
    else:
        tilt = f"Email alerts are mostly neutral ({neutral} neutral)."
    if analyzed_count == 0:
        pending = _email_analysis_gap_summary(status_counts)
        if pending:
            return (
                f"{tilt} No linked article thesis is ready yet: {pending}. "
                "Treat this as headline context until the email article agent analyzes "
                "those links."
            )
        return f"{tilt} No linked article thesis is ready yet, so this is context only."
    pending = _email_analysis_gap_sentence(status_counts)
    return _clip_text(
        f"{tilt} {analyzed_count} linked article thesis {_plural('row', analyzed_count)} "
        "ready for review. "
        f"{pending}",
        420,
    )

def _email_evidence_detail(
    event_count: int,
    feed_count: int,
    analyzed_count: int,
    status_counts: Counter[str],
) -> str:
    if event_count == 0:
        return "No subscription emails currently match this ticker."
    if analyzed_count:
        pending = _email_analysis_gap_sentence(status_counts)
        return _clip_text(
            f"{event_count} matching {_plural('email event', event_count)} and "
            f"{feed_count} {_plural('feed row', feed_count)}. "
            f"{analyzed_count} linked article thesis {_plural('row', analyzed_count)} "
            "ready for context review. "
            f"{pending}",
            420,
        )
    pending = _email_analysis_gap_summary(status_counts)
    gap = f" Reason: {pending}." if pending else ""
    return (
        f"{event_count} matching email events and {feed_count} feed rows. "
        f"No linked article thesis is ready yet, so these are shown as evidence only.{gap}"
    )

def _email_ticker_thesis(
    *,
    ticker: str,
    title: str | None,
    status: str,
    direction: str,
    event_type: str | None,
    raw_thesis: str | None,
    catalysts: Sequence[str],
    risks: Sequence[str],
) -> str:
    relevance = _email_ticker_relevance(
        ticker=ticker,
        title=title,
        status=status,
        direction=direction,
        event_type=event_type,
        catalysts=catalysts,
        risks=risks,
    )
    if not _is_email_article_analyzed_status(status):
        return relevance
    catalyst_text = _human_list([_email_taxonomy_label(item) for item in catalysts])
    risk_text = _human_list([_email_taxonomy_label(item) for item in risks])
    signal = f"{direction.title()} article signal"
    if catalyst_text:
        signal += f" from {catalyst_text}"
    watch = f"; watch {risk_text}" if risk_text else ""
    if raw_thesis and _email_focus_ticker(title) in {None, ticker.upper()}:
        return f"{relevance} {signal}{watch}. Source thesis: {raw_thesis}"
    return f"{relevance} {signal}{watch}."

def _email_ticker_relevance(
    *,
    ticker: str,
    title: str | None,
    status: str,
    direction: str,
    event_type: str | None,
    catalysts: Sequence[str],
    risks: Sequence[str],
) -> str:
    headline = _email_headline(title)
    focus_ticker = _email_focus_ticker(title)
    event_label = _email_event_label(event_type)
    topic = _email_topic_from_title(headline, event_type)
    if not _is_email_article_analyzed_status(status):
        if status == "non_article_link":
            return (
                f"{ticker} matched the mailbox alert for a {event_label}, but the "
                "only available link was a static asset or non-article page. Treat "
                f"this as headline-only {direction.lower()} context about {topic}; "
                "it is not a Zacks/Seeking Alpha article thesis."
            )
        return (
            f"{ticker} matched the mailbox alert for a {event_label}, but linked article "
            f"content is not available yet. Treat this as headline-only {direction.lower()} "
            f"context about {topic}."
        )
    if focus_ticker == ticker.upper():
        opener = (
            f"Direct relevance: the linked article headline is focused on {ticker} "
            f"and discusses {topic}."
        )
    elif focus_ticker is not None:
        opener = (
            f"Secondary relevance: the linked article headline is focused on "
            f"{focus_ticker}, while {ticker} was detected in the article or email context. "
            f"Use it as basket/theme evidence, not as a standalone {ticker} thesis."
        )
    else:
        opener = (
            f"Ticker relevance: {ticker} appears in the analyzed article/email context "
            f"for {topic}."
        )
    catalyst_text = _human_list([_email_taxonomy_label(item) for item in catalysts])
    risk_text = _human_list([_email_taxonomy_label(item) for item in risks])
    details = [opener, f"The article signal is {direction.lower()}."]
    if catalyst_text:
        details.append(f"Detected drivers: {catalyst_text}.")
    if risk_text:
        details.append(f"Risk/watch items: {risk_text}.")
    return " ".join(details)

def _email_dashboard_decision_use(
    *,
    ticker: str,
    title: str | None,
    status: str,
    direction: str,
    default: str | None,
) -> str:
    focus_ticker = _email_focus_ticker(title)
    if (
        _is_email_article_analyzed_status(status)
        and focus_ticker is not None
        and focus_ticker != ticker.upper()
    ):
        return (
            "Use as secondary basket/theme context only; require direct ticker "
            "confirmation before it can support a decision."
        )
    return default or _email_default_decision_use(status, direction)

def _email_article_focus(title: str | None, ticker: str) -> str:
    focus_ticker = _email_focus_ticker(title)
    if focus_ticker == ticker.upper():
        return f"Direct headline focus on {ticker}"
    if focus_ticker is not None:
        return f"Secondary context; headline focus is {focus_ticker}"
    return "No single headline ticker focus detected"

def _email_focus_ticker(title: str | None) -> str | None:
    cleaned = _clean_text(title)
    if cleaned is None:
        return None
    match = EMAIL_HEADLINE_FOCUS_RE.search(cleaned)
    return match.group(1).upper() if match is not None else None

def _email_topic_from_title(headline: str, event_type: str | None) -> str:
    lowered = headline.lower()
    if "quantum" in lowered:
        return "the quantum-computing theme"
    if "insider" in lowered:
        return "insider-trading activity"
    if "dark pool" in lowered or "block trade" in lowered:
        return "unusual trading activity"
    if "adds" in lowered or "exits" in lowered or "q1 moves" in lowered:
        return "fund holdings changes"
    if "earnings" in lowered or "transcript" in lowered:
        return "earnings or transcript context"
    return _email_event_label(event_type)

def _mailbox_event_summary(
    *,
    title: str | None,
    status: str,
    linked_summary: str | None,
    direction: str,
    event_type: str | None,
    ticker: str,
    ticker_relevance: str,
) -> str:
    if linked_summary:
        return _clip_text(
            f"Article opened for {ticker}. {ticker_relevance}",
            420,
        )
    headline = _email_headline(title)
    event_label = _email_event_label(event_type)
    direction_label = direction.lower()
    if status == "not_requested":
        message = (
            f"Headline-only {direction_label} {event_label}. Article body analysis "
            f"has not run for this row yet. Headline: {headline}"
        )
    elif status == "article_fetch_failed":
        message = (
            f"The article link could not be fetched, so the agency only has the "
            f"{direction_label} email headline for now. Headline: {headline}"
        )
    elif status == "article_fetch_limited":
        message = (
            f"The article link was not opened because the safe per-run article limit "
            f"was reached. Headline: {headline}"
        )
    elif status == "no_allowed_article_link":
        message = (
            f"The email matched this ticker, but no allowlisted article link was found. "
            f"Headline: {headline}"
        )
    elif status == "non_article_link":
        message = (
            f"The email matched this ticker, but the available link was a static "
            f"asset or non-article page. Headline-only {direction_label} "
            f"{event_label}. Headline: {headline}"
        )
    else:
        message = f"{_linked_status_detail(status)} Headline: {headline}"
    return _clip_text(message, 260 if status == "non_article_link" else 240)

def _email_interpretation_summary(
    *,
    feed: Mapping[str, object],
    event: Mapping[str, object] | None,
) -> str:
    if event is None:
        return _clip_text(_row_text(feed, "summary", "No summary recorded"), 240)
    thesis = _row_text(event, "thesis")
    if thesis:
        ticker = _row_text(event, "ticker", "ticker")
        decision_use = _row_text(event, "decision_use", "Use as context-only thesis evidence.")
        key_points = _row_text(event, "key_point_text")
        catalyst_text = _row_text(event, "catalyst_text")
        risk_text = _row_text(event, "risk_text")
        relevance = _row_text(event, "ticker_relevance", thesis)
        judgement_contribution = _row_text(event, "judgement_contribution")
        detail_parts = [
            f"Why relevant to {ticker}: {_sentence_fragment(relevance)}",
            f"Agency use: {_sentence_fragment(decision_use)}",
        ]
        if judgement_contribution:
            detail_parts.append(
                f"Judgment impact: {_sentence_fragment(judgement_contribution)}"
            )
        if catalyst_text:
            detail_parts.append(f"Evidence detected: {_sentence_fragment(catalyst_text)}")
        if key_points:
            detail_parts.append(f"Article takeaway: {_sentence_fragment(key_points)}")
        if risk_text:
            detail_parts.append(f"Watch: {_sentence_fragment(risk_text)}")
        return _clip_text(". ".join(detail_parts) + ".", 820)
    article_summary = _row_text(event, "article_summary")
    if article_summary:
        return _clip_text(
            f"Use as subscription thesis context: {article_summary}",
            260,
        )
    service = _row_text(event, "service", _row_text(feed, "feed_name", "Email"))
    direction = _row_text(event, "direction", "NEUTRAL").lower()
    event_type = _email_event_label(_row_text(event, "event_type_raw"))
    headline = _row_text(event, "headline", _email_headline(_row_text(feed, "title")))
    status = _row_text(event, "linked_content_status", "not_requested")
    status_note = _email_status_note(status)
    return _clip_text(
        f"{service} produced a {direction} {event_type}. The agency can count the "
        f"alert as paid-subscription context, but {status_note}. Headline: {headline}",
        280,
    )

def _email_status_note(status: str) -> str:
    notes = {
        "article_fetch_failed": "article fetch failed, so this is headline-level evidence only",
        "article_fetch_limited": "the safe per-run article limit was reached",
        "not_requested": (
            "article body has not been analyzed yet, so this is headline-level evidence"
        ),
        "no_allowed_article_link": (
            "no allowlisted article link was found, so this is headline-level evidence"
        ),
        "non_article_link": (
            "only static or non-article links were found, so this is headline-level "
            "evidence"
        ),
    }
    return notes.get(status, _linked_status_detail(status).rstrip(".").lower())

def _linked_status_label(status: str) -> str:
    labels = {
        "article_analyzed": "Article Analyzed",
        "article_analyzed_deterministic_fallback": "Keyword-Only Analysis",
        "article_analyzed_no_ticker_match": "No Ticker Match",
        "article_fetch_failed": "Link Failed",
        "article_fetch_limited": "Limit Reached",
        "non_article_link": "Non-Article Link",
        "no_allowed_article_link": "No Article Link",
        "not_requested": "Headline Only",
    }
    return labels.get(status, _label_text(status))

def _linked_status_class(status: str) -> str:
    if status == "article_analyzed_deterministic_fallback":
        return "warn"
    if _is_email_article_analyzed_status(status):
        return "pass"
    if status == "article_fetch_failed":
        return "warn"
    return "neutral"

def _linked_status_detail(status: str) -> str:
    if status == "article_analyzed_deterministic_fallback":
        return (
            "The linked article was analyzed with keyword-only fallback and needs "
            "LLM/browser confirmation before acting."
        )
    if _is_email_article_analyzed_status(status):
        return "The linked article was analyzed and can appear as a thesis context signal."
    if status == "article_analyzed_no_ticker_match":
        return (
            "The linked article was analyzed, but it did not materially mention this "
            "ticker, so it remains headline-level context."
        )
    if status == "article_fetch_failed":
        return "The email matched this ticker, but the linked page could not be analyzed."
    if status == "article_fetch_limited":
        return "The linked article was not opened because the per-run article limit was reached."
    if status == "non_article_link":
        return (
            "The email exposed only a static asset or non-article URL, so there is no "
            "article body to analyze."
        )
    if status == "no_allowed_article_link":
        return "The email matched this ticker, but no allowlisted article link was found."
    return "The email matched this ticker; linked article analysis was not available for this row."

def _legacy_linked_thesis(summary: str | None) -> str | None:
    if summary is None:
        return None
    if not summary.startswith("Linked content thesis:"):
        return summary
    cleaned = summary.removeprefix("Linked content thesis:").strip()
    for marker in (
        ". Why it matters:",
        " Why it matters:",
        " Context:",
        "; tickers=",
        "; direction=",
    ):
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0]
            break
    return _clean_text(cleaned.strip(" ."))

def _object_strings(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, float) and pd.isna(value):
        return []
    if isinstance(value, str):
        cleaned = _clean_text(value)
        return [cleaned] if cleaned else []
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, list | tuple | set):
        return []
    return [
        cleaned
        for item in value
        for cleaned in [_clean_text(item)]
        if cleaned is not None
    ]

def _email_taxonomy_label(value: str) -> str:
    labels = {
        "analyst_rating": "analyst/rating",
        "earnings": "earnings/guidance",
        "execution": "execution risk",
        "legal_or_regulatory": "legal/regulatory risk",
        "macro": "macro",
        "negative_revision": "negative revisions",
        "quant_rating": "quant rating",
        "rank_change": "rank change",
        "unusual_activity": "unusual activity",
        "valuation": "valuation",
    }
    return labels.get(value, _label_text(value).lower())

def _email_default_decision_use(status: str, direction: str) -> str:
    normalized_direction = direction.upper()
    if _is_email_article_analyzed_status(status) and normalized_direction == "BULLISH":
        return "Use as context-only bullish thesis; require independent confirmation."
    if _is_email_article_analyzed_status(status) and normalized_direction == "BEARISH":
        return "Use as caution context and raise the review burden."
    if _is_email_article_analyzed_status(status):
        return "Use as neutral context for the next runtime cycle."
    return "Use as headline-level context until the linked article is analyzed."

def _sentence_case(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        return cleaned
    return cleaned[0].upper() + cleaned[1:]

def _sentence_fragment(value: str) -> str:
    return " ".join(value.split()).rstrip(" .")

def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and not pd.isna(value):
        return int(value)
    return None

def _email_headline(title: str | None) -> str:
    cleaned = _clean_text(title) or "No email headline recorded"
    if " - " in cleaned:
        return cleaned.split(" - ", 1)[1]
    return cleaned

def _email_event_label(event_type: str | None) -> str:
    cleaned = _clean_text(event_type)
    if cleaned is None:
        return "subscription email alert"
    return EMAIL_EVENT_LABELS.get(cleaned, _label_text(cleaned).lower())

def candidate_decision_brief(
    ticker: str,
    latest_report: Mapping[str, object] | None,
    email_evidence: Mapping[str, object],
    review: Mapping[str, object],
    current_position: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if latest_report is None:
        return _empty_decision_brief(ticker, email_evidence, current_position=current_position)
    action = str(latest_report["action"])
    gate_status = str(latest_report["gate_status"])
    conviction_pct = _int_field(latest_report, "conviction_pct")
    actionable = _mapping_rows(latest_report, "actionable_signals")
    context = _mapping_rows(latest_report, "context_signals")
    suppressed = _mapping_rows(latest_report, "suppressed_signals")
    all_signals = [*actionable, *context, *suppressed]
    direction_counts = _signal_direction_counts(all_signals)
    state_class = _candidate_state_class(action, gate_status)
    return {
        "ticker": ticker,
        "action": action,
        "action_label": _candidate_action_label(action),
        "state_label": _candidate_state_label(action, gate_status),
        "state_class": state_class,
        "headline": _candidate_brief_headline(ticker, action, gate_status),
        "detail": _candidate_brief_detail(action, actionable, context, suppressed),
        "next_step": _candidate_next_step(action, gate_status, review),
        "conviction_pct": conviction_pct,
        "conviction_style": f"--meter-value: {conviction_pct}%",
        "gate_status": gate_status,
        "gate_class": gate_status.lower(),
        "generated_at": str(latest_report["generated_at"]),
        "source_count": _int_field(latest_report, "source_count"),
        "confirmed_signal_count": _int_field(latest_report, "confirmed_signal_count"),
        "signal_counts": _signal_count_cards(actionable, context, suppressed),
        "signal_balance": _signal_balance(direction_counts),
        "support_cards": _signal_driver_cards(actionable, "BULLISH", default_tone="pass"),
        "caution_cards": _signal_driver_cards(all_signals, "BEARISH", default_tone="block"),
        "decision_points": _decision_points(latest_report),
        "signal_mix_note": _signal_mix_note(actionable, context, suppressed),
        "email_takeaway": str(email_evidence["meaning"]),
        "email_status_class": str(email_evidence["status_class"]),
        "currently_holding": current_position is not None,
        "holding_label": _current_holding_label(current_position),
    }

def _empty_decision_brief(
    ticker: str,
    email_evidence: Mapping[str, object],
    *,
    current_position: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "action": "NONE",
        "action_label": "No Report",
        "state_label": "Waiting For Runtime",
        "state_class": "neutral",
        "headline": f"{ticker} has not been evaluated yet.",
        "detail": "Run a runtime cycle to produce a decision brief and evidence summary.",
        "next_step": "Run the live runtime cycle, then review the generated candidate report.",
        "conviction_pct": 0,
        "conviction_style": "--meter-value: 0%",
        "gate_status": "UNKNOWN",
        "gate_class": "unknown",
        "generated_at": "None",
        "source_count": 0,
        "confirmed_signal_count": 0,
        "signal_counts": _signal_count_cards([], [], []),
        "signal_balance": _signal_balance(Counter()),
        "support_cards": [],
        "caution_cards": [],
        "decision_points": [
            {
                "label": "No selection report",
                "detail": "There is no persisted decision for this ticker yet.",
                "tone": "neutral",
            },
            {
                "label": "Email context",
                "detail": str(email_evidence["detail"]),
                "tone": str(email_evidence["status_class"]),
            },
        ],
        "signal_mix_note": "No current signal mix is available yet.",
        "email_takeaway": str(email_evidence["meaning"]),
        "email_status_class": str(email_evidence["status_class"]),
        "currently_holding": current_position is not None,
        "holding_label": _current_holding_label(current_position),
    }

def _candidate_current_position(
    ticker: str,
    broker: Mapping[str, object],
) -> Mapping[str, object] | None:
    positions = broker.get("positions", [])
    if not isinstance(positions, list):
        return None
    for position in positions:
        if not isinstance(position, Mapping):
            continue
        symbol = str(position.get("ticker") or position.get("symbol") or "").upper()
        if symbol == ticker.upper():
            return position
    return None

def _current_holding_label(position: Mapping[str, object] | None) -> str:
    if position is None:
        return "No current Alpaca paper position detected"
    quantity = _clean_text(position.get("qty")) or _clean_text(position.get("quantity")) or "size unknown"
    side = _clean_text(position.get("side")) or "position"
    market_value = _clean_text(position.get("market_value"))
    if market_value:
        return f"Currently holding {quantity} {side} / ${market_value}"
    return f"Currently holding {quantity} {side}"

def _mapping_rows(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = payload.get(key, [])
    if not isinstance(value, list):
        return []
    return [cast(Mapping[str, object], item) for item in value if isinstance(item, Mapping)]

def _candidate_state_class(action: str, gate_status: str) -> str:
    if gate_status == "BLOCK" or action in {"NO_TRADE", "CLOSE_REVIEW"}:
        return "block"
    if action == "WATCH":
        return "warn"
    if action in {"BUY", "SELL", "SHORT", "COVER", "HOLD"}:
        return "pass"
    return "neutral"

def _candidate_state_label(action: str, gate_status: str) -> str:
    if gate_status == "BLOCK":
        return "Blocked By Policy"
    if action == "WATCH":
        return "Selected For Review"
    if action in {"NO_TRADE", "CLOSE_REVIEW"}:
        return "Rejected For Now"
    if action in {"BUY", "SELL", "SHORT", "COVER"}:
        return "Trade Candidate"
    if action == "HOLD":
        return "Hold / Monitor"
    return "No Decision"

def _candidate_action_label(action: str) -> str:
    labels = {
        "WATCH": "Watch",
        "NO_TRADE": "No Trade",
        "CLOSE_REVIEW": "Close Review",
        "BUY": "Buy Candidate",
        "SELL": "Sell Candidate",
        "SHORT": "Short Candidate",
        "COVER": "Cover Candidate",
        "HOLD": "Hold",
    }
    return labels.get(action, _label_text(action))

def _candidate_brief_headline(ticker: str, action: str, gate_status: str) -> str:
    if gate_status == "BLOCK":
        return f"{ticker} was blocked by policy gates."
    headlines = {
        "WATCH": f"{ticker} is selected for human review, not automatic trading.",
        "NO_TRADE": f"{ticker} was rejected for now.",
        "CLOSE_REVIEW": f"{ticker} needs closer review before any action.",
        "HOLD": f"{ticker} is a hold/monitor candidate.",
    }
    if action in {"BUY", "SELL", "SHORT", "COVER"}:
        return f"{ticker} is a {action.lower()} candidate pending risk review."
    return headlines.get(action, f"{ticker} has a recorded decision.")

def _candidate_brief_detail(
    action: str,
    actionable: Sequence[Mapping[str, object]],
    context: Sequence[Mapping[str, object]],
    suppressed: Sequence[Mapping[str, object]],
) -> str:
    support = _first_signal_summary([*actionable, *context], "BULLISH")
    caution = _first_signal_summary([*actionable, *context, *suppressed], "BEARISH")
    if action == "WATCH":
        if support and caution:
            return f"Selected because {support} Main caution: {caution}"
        if support:
            return f"Selected because {support}"
    if action in {"NO_TRADE", "CLOSE_REVIEW"} and caution:
        return f"Rejected or held back because {caution}"
    if support:
        return f"Primary constructive evidence: {support}"
    if caution:
        return f"Primary caution: {caution}"
    return "The latest report did not surface a strong directional driver."

def _first_signal_summary(
    signals: Sequence[Mapping[str, object]],
    direction: str,
) -> str | None:
    for signal in _sorted_signals(signals):
        if str(signal.get("direction")) == direction:
            return str(signal["summary"])
    return None

def _candidate_next_step(
    action: str,
    gate_status: str,
    review: Mapping[str, object],
) -> str:
    if gate_status == "BLOCK":
        return "Do not approve. Fix the blocking gate or wait for stronger evidence."
    if action == "WATCH":
        decision = str(review.get("decision", "Pending"))
        if decision == "Pending":
            return "Review the drivers below, then approve, defer, or reject the paper candidate."
        return f"Human review is recorded as {decision}; monitor the next runtime cycle."
    if action in {"NO_TRADE", "CLOSE_REVIEW"}:
        return "No trade. Revisit only if a later cycle adds stronger independent evidence."
    if action in {"BUY", "SELL", "SHORT", "COVER"}:
        return "Send to risk review and paper preview before any broker action."
    return "Monitor the next refresh for a clearer setup."

def _signal_count_cards(
    actionable: Sequence[Mapping[str, object]],
    context: Sequence[Mapping[str, object]],
    suppressed: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            "label": "Actionable",
            "value": len(actionable),
            "detail": "can drive the decision",
            "tone": "pass" if actionable else "neutral",
        },
        {
            "label": "Context",
            "value": len(context),
            "detail": "useful but not decisive",
            "tone": "warn" if context else "neutral",
        },
        {
            "label": "Suppressed",
            "value": len(suppressed),
            "detail": "ignored or too weak",
            "tone": "block" if suppressed else "pass",
        },
    ]

def _signal_direction_counts(signals: Sequence[Mapping[str, object]]) -> Counter[str]:
    return Counter(str(signal.get("direction", "NEUTRAL")) for signal in signals)

def _signal_balance(counts: Counter[str]) -> list[dict[str, object]]:
    total = sum(counts.values())
    if total == 0:
        return [
            {
                "label": "No signals",
                "count": 0,
                "tone": "neutral",
                "style": "width: 100%",
            }
        ]
    rows: list[dict[str, object]] = []
    for direction, tone in (("BULLISH", "pass"), ("BEARISH", "block"), ("NEUTRAL", "neutral")):
        count = counts.get(direction, 0)
        if count == 0:
            continue
        pct = round((count / total) * 100, 2)
        rows.append(
            {
                "label": direction.title(),
                "count": count,
                "tone": tone,
                "style": f"width: {pct}%",
            }
        )
    return rows

def _signal_driver_cards(
    signals: Sequence[Mapping[str, object]],
    direction: str,
    *,
    default_tone: str,
    limit: int = 3,
) -> list[dict[str, object]]:
    rows = [
        signal
        for signal in _sorted_signals(signals)
        if str(signal.get("direction")) == direction
    ][:limit]
    if not rows and direction == "BEARISH":
        return [
            {
                "label": "No major negative driver",
                "detail": "The latest report did not surface a bearish actionable driver.",
                "meta": "risk check",
                "tone": "pass",
            }
        ]
    cards: list[dict[str, object]] = [
        {
            "label": str(signal["lane"]),
            "detail": _signal_driver_detail(signal),
            "meta": _signal_driver_meta(signal),
            "tone": default_tone,
        }
        for signal in rows
    ]
    return cards

def _signal_driver_detail(signal: Mapping[str, object]) -> str:
    summary = _clean_text(signal.get("trigger_headline")) or _clean_text(signal.get("summary"))
    trigger_detail = _clean_text(signal.get("trigger_detail"))
    score = _clean_text(signal.get("score")) or "score unavailable"
    confidence = _clean_text(signal.get("confidence_pct")) or "0"
    source_label = _clean_text(signal.get("source")) or "source unknown"
    source_key = _clean_text(signal.get("source_key"))
    source = f"{source_key} ({source_label})" if source_key else source_label
    timestamp = _format_timestamp_label(signal.get("timestamp_as_of"))
    reason = _clean_text(signal.get("reason_codes_label")) or _clean_text(signal.get("reason_text"))
    parts = [
        summary or "Signal summary unavailable.",
        f"Hard evidence: score {score}, {confidence}% confidence, source {source}, as of {timestamp}.",
    ]
    if trigger_detail:
        parts.append(trigger_detail)
    if reason:
        parts.append(f"Reason code: {reason}.")
    return " ".join(parts)

def _signal_driver_meta(signal: Mapping[str, object]) -> str:
    bucket = _clean_text(signal.get("bucket")) or _clean_text(signal.get("actionability_label"))
    freshness = _clean_text(signal.get("freshness")) or "freshness unknown"
    verification = _clean_text(signal.get("verification_label")) or _clean_text(
        signal.get("verification_level")
    )
    source_tier = _clean_text(signal.get("source_tier"))
    pieces = [piece for piece in (bucket, freshness, verification, source_tier) if piece]
    return " / ".join(pieces) if pieces else "signal provenance"

def _signal_mix_note(
    actionable: Sequence[Mapping[str, object]],
    context: Sequence[Mapping[str, object]],
    suppressed: Sequence[Mapping[str, object]],
) -> str:
    actionable_bullish = sum(1 for signal in actionable if signal.get("direction") == "BULLISH")
    actionable_bearish = sum(1 for signal in actionable if signal.get("direction") == "BEARISH")
    advisory_bullish = sum(
        1 for signal in [*context, *suppressed] if signal.get("direction") == "BULLISH"
    )
    advisory_bearish = sum(
        1 for signal in [*context, *suppressed] if signal.get("direction") == "BEARISH"
    )
    return (
        "Conviction is driven by actionable signals only. Advisory and score-excluded signals "
        "are shown as caution/context, so bearish advisory rows can coexist with a "
        f"bullish review state. Current mix: {actionable_bullish} actionable bullish, "
        f"{actionable_bearish} actionable bearish, {advisory_bullish} advisory bullish, "
        f"{advisory_bearish} advisory bearish."
    )

def _decision_points(latest_report: Mapping[str, object]) -> list[dict[str, object]]:
    from agency.views.signals import _decision_explanation
    action = str(latest_report["action"])
    gate_status = str(latest_report["gate_status"])
    source_count = _int_field(latest_report, "source_count")
    confirmed = _int_field(latest_report, "confirmed_signal_count")
    actionable_count = len(_mapping_rows(latest_report, "actionable_signals"))
    context_count = len(_mapping_rows(latest_report, "context_signals"))
    suppressed_count = len(_mapping_rows(latest_report, "suppressed_signals"))
    points: list[dict[str, object]] = [
        {
            "label": _candidate_state_label(action, gate_status),
            "detail": _decision_explanation(
                latest_report,
                {"action": str(latest_report["deterministic_action"])},
                {
                    "source_count": source_count,
                    "confirmed_signal_count": confirmed,
                    "freshness": str(latest_report["freshness"]),
                },
            ),
            "tone": _candidate_state_class(action, gate_status),
        },
        {
            "label": "Evidence breadth",
            "detail": f"{source_count} independent source(s), {confirmed} confirmed signal(s).",
            "tone": (
                "pass"
                if source_count >= MIN_BRIEF_SOURCE_COUNT
                and confirmed >= MIN_BRIEF_CONFIRMED_COUNT
                else "warn"
            ),
        },
        {
            "label": "Primary signal mix",
            "detail": (
                f"{actionable_count} actionable signal(s), {context_count} context "
                f"signal(s), and {suppressed_count} suppressed signal(s). "
                "Subscription email evidence is shown separately below."
            ),
            "tone": "pass" if actionable_count > 0 else "warn",
        },
    ]
    if gate_status == "PASS":
        points.append(
            {
                "label": "Policy gates",
                "detail": "No blocking policy gate is active for the latest report.",
                "tone": "pass",
            }
        )
    else:
        points.append(
            {
                "label": "Policy gates",
                "detail": f"Latest policy gate state is {gate_status}.",
                "tone": "block" if gate_status == "BLOCK" else "warn",
            }
        )
    return points

def _paper_review_row(
    report: Mapping[str, object],
    risk_decision: Mapping[str, object] | None,
    human_review_event: Mapping[str, object] | None,
) -> dict[str, object]:
    candidate = _candidate_row(report)
    deterministic = _optional_mapping_field(report, "deterministic")
    llm_review = _optional_mapping_field(report, "llm_review")
    evidence_pack = _mapping_field(report, "evidence_pack")
    data_quality = _mapping_field(evidence_pack, "data_quality")
    decision = "PENDING"
    decision_class = "neutral"
    reason = "waiting for risk decision"
    if risk_decision is not None:
        decision = str(risk_decision["decision"])
        decision_class = _decision_class(decision)
        reasons = _string_list(risk_decision, "reasons")
        reason = reasons[0] if reasons else "risk decision recorded"
    ticker = str(candidate["ticker"])
    human_review = _human_review_summary(human_review_event)
    caution = _review_caution(report, risk_decision)
    return {
        **candidate,
        "company": str(report.get("company") or report.get("name") or candidate["ticker"]),
        "sector": str(report.get("sector") or ""),
        "final_conviction": _float_field(report, "final_conviction"),
        "deterministic": dict(deterministic),
        "llm_review": dict(llm_review),
        "evidence_hash": str(report.get("evidence_hash") or ""),
        "cycle_id": str(report["cycle_id"]),
        "candidate_href": f"/candidates/{ticker}",
        "risk_href": "/risk",
        "final_selection_href": "/final-selection",
        "approve_review_action": _review_action_url(
            ticker=ticker,
            cycle_id=str(report["cycle_id"]),
            as_of=str(report["as_of"]),
            decision="APPROVE",
        ),
        "defer_review_action": _review_action_url(
            ticker=ticker,
            cycle_id=str(report["cycle_id"]),
            as_of=str(report["as_of"]),
            decision="DEFER",
        ),
        "reject_review_action": _review_action_url(
            ticker=ticker,
            cycle_id=str(report["cycle_id"]),
            as_of=str(report["as_of"]),
            decision="REJECT",
        ),
        "risk_decision": decision,
        "risk_class": decision_class,
        "review_state": _paper_review_state(decision),
        "review_class": _paper_review_class(decision),
        "human_review_decision": human_review["decision"],
        "human_review_class": human_review["status_class"],
        "human_review_reason": human_review["reason"],
        "human_review_time": human_review["event_time"],
        "human_review_time_label": _format_timestamp_label(human_review["event_time"]),
        "reason": reason,
        "caution_acknowledgement_required": caution["required"],
        "caution_acknowledgement_text": caution["text"],
        "caution_recommendation": caution["recommendation"],
        "source_count": _int_field(data_quality, "source_count"),
        "confirmed_signal_count": _int_field(data_quality, "confirmed_signal_count"),
    }

def _candidate_row(report: Mapping[str, object]) -> dict[str, object]:
    from agency.views.risk import _gate_status, _risk_flag_count
    conviction = _float_field(report, "final_conviction")
    return {
        "ticker": str(report["ticker"]),
        "action": str(report["final_action"]),
        "conviction_pct": round(conviction * 100),
        "gate_status": _gate_status(report),
        "as_of": str(report["as_of"]),
        "as_of_label": _format_timestamp_label(report["as_of"]),
        "risk_flag_count": _risk_flag_count(report),
    }


def _optional_mapping_field(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}

def _candidate_review_redirect_url(*, ticker: str, decision: str) -> str:
    if decision.upper() == "APPROVE":
        return "/execution-preview#execution-followup-heading"
    return f"/candidates/{ticker.upper()}"

def _review_action_url(
    *,
    ticker: str,
    cycle_id: str,
    as_of: str,
    decision: str,
    caution_acknowledged: bool = False,
) -> str:
    query_values = {"cycle_id": cycle_id, "as_of": as_of, "decision": decision}
    if caution_acknowledged:
        query_values["caution_acknowledged"] = "true"
    query = urlencode(query_values)
    return f"/candidates/{ticker}/reviews?{query}"


def _review_caution(
    report: Mapping[str, object],
    risk_decision: Mapping[str, object] | None,
) -> dict[str, object]:
    action = str(report.get("action") or report.get("final_action") or "")
    decision = str((risk_decision or {}).get("decision") or "")
    reasons = _string_list(risk_decision, "reasons") if risk_decision is not None else []
    reason = next((item for item in reasons if item.startswith("Caution:")), "")
    required = bool(action in {"WATCH", "HOLD"} and decision == "WARN" and reason)
    recommendation = (
        "Approve only if you accept this as a research/watch-list decision. Before "
        "trading, check the named gate, confirm the data is fresh, and wait for a "
        "later cycle to create an orderable BUY, SELL, SHORT, or COVER recommendation."
        if required
        else ""
    )
    text = f"{reason} {recommendation}".strip() if required else ""
    return {
        "required": required,
        "text": text,
        "recommendation": recommendation,
    }

def _paper_review_sort_key(row: Mapping[str, object]) -> tuple[int, int, str]:
    decision = str(row["risk_decision"])
    if decision in OPEN_RISK_DECISIONS:
        priority = 0
    elif decision == "PENDING":
        priority = 1
    else:
        priority = 2
    return (priority, -_int_field(row, "conviction_pct"), str(row["ticker"]))

def _candidate_detail_headline(ticker: str, latest_action: str) -> str:
    if latest_action == "None":
        return f"{ticker} has no persisted selection reports yet."
    return f"{ticker} latest action: {latest_action}."

def _candidate_detail_text(ticker: str, latest_report: Mapping[str, object] | None) -> str:
    if latest_report is None:
        return f"{ticker} will show decision evidence after the first runtime cycle persists."
    action = str(latest_report["action"])
    conviction = _int_field(latest_report, "conviction_pct")
    source_count = _int_field(latest_report, "source_count")
    confirmed_count = _int_field(latest_report, "confirmed_signal_count")
    gate_status = str(latest_report["gate_status"])
    return (
        f"Latest report is {action} at {conviction}% conviction, backed by "
        f"{source_count} independent source(s) and {confirmed_count} confirmed signal(s). "
        f"Policy gate state is {gate_status}."
    )

def _paper_review_state(decision: str) -> str:
    if decision in OPEN_RISK_DECISIONS:
        return "Ready"
    if decision == "PENDING":
        return "Waiting"
    return "Blocked"

def _paper_review_class(decision: str) -> str:
    if decision in OPEN_RISK_DECISIONS:
        return _decision_class(decision)
    if decision == "PENDING":
        return "neutral"
    return "block"

def _review_progress_status_label(total_count: int, pending_count: int) -> str:
    if total_count == 0:
        return "No Queue"
    if pending_count == 0:
        return "Review Complete"
    return f"{pending_count} Pending"

def _review_progress_status_class(total_count: int, pending_count: int) -> str:
    if total_count == 0:
        return "neutral"
    if pending_count == 0:
        return "pass"
    return "warn"

def _review_progress_detail(total_count: int, pending_count: int) -> str:
    if total_count == 0:
        return "No latest-cycle paper candidates are waiting for review."
    reviewed_count = total_count - pending_count
    if pending_count == 0:
        return f"All {total_count} queued paper candidates have a recorded review state."
    return (
        f"{reviewed_count} of {total_count} queued paper candidates have a recorded "
        "review state."
    )
