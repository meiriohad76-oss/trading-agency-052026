"""View-model constructors for the signals page."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import monotonic
from typing import cast

from agency.runtime.lane_promotion import load_lane_promotion_status
from agency.runtime.live_config_readiness import load_live_config_readiness
from agency.runtime.signal_evidence import enrich_signal_rows_with_evidence
from agency.services.signal_adapters import DIRECTION_EPSILON, SignalActionabilityConfig
from agency.views._shared import (
    SIGNALS_CONTEXT_CACHE_SECONDS,
    SIGNALS_RENDER_LIMIT,
    SIGNALS_REPORT_LIMIT,
    _clean_text,
    _clip_text,
    _dashboard_selection_reports,
    _direction_class,
    _float_field,
    _format_timestamp_label,
    _human_list,
    _int_field,
    _label_text,
    _latest_selection_cycle_id,
    _list_field,
    _mapping_field,
    _percent,
    _reason_summary,
    _row_text,
    _score_scale_label,
    _score_scale_tooltip,
    _score_text,
    _selection_reports_for_cycle,
    _service_label,
    _short_cycle_label,
    _sorted_signals,
    _string_list,
    dashboard_data_health,
    displayed_evidence_currentness,
    live_dashboard_data_load_status,
)

_signals_context_cache: dict[str, tuple[float, dict[str, object]]] = {}
_SIGNAL_ACTIONABILITY_CONFIG = SignalActionabilityConfig()


async def signals_context() -> dict[str, object]:
    from agency.views.final_selection import final_selection_rows
    reports = await _dashboard_selection_reports(limit=SIGNALS_REPORT_LIMIT)
    cycle_id = _latest_selection_cycle_id(reports)
    cycle_reports = _selection_reports_for_cycle(reports, cycle_id)
    live_config = load_live_config_readiness()
    runtime_signals = live_config.get("runtime_signals", [])
    configured_signals = (
        [str(item) for item in runtime_signals]
        if isinstance(runtime_signals, list)
        else []
    )
    promotion = load_lane_promotion_status(configured_signals)
    data_load_status = await live_dashboard_data_load_status()
    evidence_currentness = displayed_evidence_currentness(
        data_load_status,
        displayed_cycle_id=cycle_id,
        datasets=("prices_daily", "stock_trades", "news_rss", "subscription_emails"),
        lanes=tuple(configured_signals),
    )
    cache_key = _signals_cache_key(
        cycle_id,
        cycle_reports,
        configured_signals,
        promotion,
        evidence_currentness,
    )
    cached = _cached_signals_context(cache_key)
    if cached is not None:
        cached["data_health"] = dashboard_data_health(
            "Signals dashboard",
            data_load_status=data_load_status,
            datasets=("prices_daily", "stock_trades", "news_rss", "subscription_emails"),
            lanes=tuple(configured_signals),
            cycle_id=cycle_id,
        )
        cached["evidence_currentness"] = evidence_currentness
        return cached
    selection_rows = final_selection_rows(cycle_reports)
    all_signal_rows = signal_dashboard_rows(selection_rows)
    if evidence_currentness.get("is_current") is True:
        visible_source_rows = all_signal_rows[:SIGNALS_RENDER_LIMIT]
        signal_rows = enrich_signal_rows_with_evidence(visible_source_rows)
        rows_for_summary = all_signal_rows
    else:
        signal_rows = []
        rows_for_summary = []
    lane_rows = signal_lane_rows(rows_for_summary, promotion)
    context: dict[str, object] = {
        "active_nav": "signals",
        "evidence_currentness": evidence_currentness,
        "data_health": dashboard_data_health(
            "Signals dashboard",
            data_load_status=data_load_status,
            datasets=("prices_daily", "stock_trades", "news_rss", "subscription_emails"),
            lanes=tuple(configured_signals),
            cycle_id=cycle_id,
        ),
        "lane_rows": lane_rows,
        "signal_rows": signal_rows,
        "summary": signal_dashboard_summary(
            signal_rows=rows_for_summary,
            lane_rows=lane_rows,
            cycle_id=cycle_id,
            report_count=len(selection_rows),
            visible_signal_count=len(signal_rows),
            previous_signal_count=len(all_signal_rows),
            evidence_currentness=evidence_currentness,
        ),
    }
    _store_signals_context(cache_key, context)
    return context

def _cached_signals_context(key: str) -> dict[str, object] | None:
    cached = _signals_context_cache.get(key)
    if cached is None:
        return None
    cached_at, context = cached
    if monotonic() - cached_at > SIGNALS_CONTEXT_CACHE_SECONDS:
        _signals_context_cache.pop(key, None)
        return None
    return dict(context)

def _store_signals_context(key: str, context: dict[str, object]) -> None:
    _signals_context_cache.clear()
    _signals_context_cache[key] = (monotonic(), dict(context))

def _configured_signal_lanes_from_context(context: Mapping[str, object]) -> tuple[str, ...]:
    rows = context.get("lane_rows")
    if not isinstance(rows, list):
        return ()
    lanes = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("configured") is True:
            lanes.append(str(row.get("lane_key") or ""))
    return tuple(lane for lane in lanes if lane)

def _signals_cache_key(
    cycle_id: str | None,
    reports: Sequence[Mapping[str, object]],
    configured_signals: Sequence[str] = (),
    promotion: Mapping[str, object] | None = None,
    evidence_currentness: Mapping[str, object] | None = None,
) -> str:
    generated_values = [
        str(report.get("generated_at") or report.get("as_of") or "")
        for report in reports
    ]
    promotion_rows = promotion.get("lanes") if isinstance(promotion, Mapping) else []
    promotion_signature = ""
    if isinstance(promotion_rows, list):
        promotion_signature = ",".join(
            sorted(
                f"{row.get('lane')}:{row.get('state')}"
                for row in promotion_rows
                if isinstance(row, Mapping)
            )
        )
    return "|".join(
        [
            cycle_id or "none",
            str(len(reports)),
            max(generated_values) if generated_values else "",
            ",".join(sorted(str(lane) for lane in configured_signals)),
            promotion_signature,
            _evidence_currentness_cache_signature(evidence_currentness or {}),
        ]
    )

def _evidence_currentness_cache_signature(row: Mapping[str, object]) -> str:
    return "|".join(
        [
            str(row.get("display_mode") or ""),
            str(row.get("status_label") or ""),
            str(row.get("status_cycle_id") or ""),
            ",".join(str(item) for item in _list_field(row, "wip_lane_ids")),
        ]
    )

def signal_dashboard_rows(
    selection_rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    from agency.views.candidates import _mapping_rows
    rows: list[dict[str, object]] = []
    for report in selection_rows:
        for key in ("actionable_signals", "context_signals", "suppressed_signals"):
            for signal in _mapping_rows(report, key):
                row = dict(signal)
                row.update(
                    {
                        "ticker": str(report["ticker"]),
                        "candidate_href": f"/candidates/{report['ticker']}",
                        "report_action": str(report["action"]),
                        "report_conviction_pct": _int_field(report, "conviction_pct"),
                        "report_gate_status": str(report["gate_status"]),
                        "bucket": _signal_bucket_label(key),
                        "bucket_class": _signal_bucket_class(key),
                    }
                )
                row.update(_signal_inspection_fields(row, report))
                rows.append(row)
    return sorted(rows, key=_signal_dashboard_sort_key)

def signal_lane_rows(
    signal_rows: Sequence[Mapping[str, object]],
    promotion: Mapping[str, object],
) -> list[dict[str, object]]:
    from agency.views.candidates import _mapping_rows
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for row in signal_rows:
        grouped.setdefault(str(row["lane_key"]), []).append(row)
    rows: list[dict[str, object]] = []
    for lane in _mapping_rows(promotion, "lanes"):
        lane_key = str(lane["lane"])
        lane_signals = grouped.get(lane_key, [])
        rows.append(_signal_lane_row(lane=lane, signals=lane_signals))
    return sorted(rows, key=_signal_lane_sort_key)

def signal_dashboard_summary(
    *,
    signal_rows: Sequence[Mapping[str, object]],
    lane_rows: Sequence[Mapping[str, object]],
    cycle_id: str | None,
    report_count: int,
    visible_signal_count: int | None = None,
    previous_signal_count: int = 0,
    evidence_currentness: Mapping[str, object] | None = None,
) -> dict[str, object]:
    visible = len(signal_rows) if visible_signal_count is None else visible_signal_count
    currentness = evidence_currentness or {"is_current": True, "display_mode": "current"}
    is_current = currentness.get("is_current") is True
    actionable_count = sum(1 for row in signal_rows if row["bucket"] == "Actionable")
    context_count = sum(1 for row in signal_rows if row["bucket"] == "Context")
    suppressed_count = sum(1 for row in signal_rows if row["bucket"] == "Suppressed")
    bullish_count = sum(1 for row in signal_rows if row["direction"] == "BULLISH")
    bearish_count = sum(1 for row in signal_rows if row["direction"] == "BEARISH")
    lanes_with_data = sum(1 for row in lane_rows if _int_field(row, "signal_count") > 0)
    configured_lanes = sum(1 for row in lane_rows if row["configured"] is True)
    top_signal = _top_signal_summary(signal_rows)
    headline = _signals_headline(
        len(signal_rows),
        lanes_with_data,
        actionable_count=actionable_count,
        bullish_count=bullish_count,
        bearish_count=bearish_count,
        top_signal=top_signal,
    )
    detail = (
        f"Latest-cycle signal audit across {report_count} selection report(s): "
        f"{actionable_count} action-weighted, {context_count} context-only, "
        f"{suppressed_count} excluded. {top_signal or 'No strongest signal is available yet.'}"
    )
    topbar_label = f"{len(signal_rows)} signals / {lanes_with_data} active lanes"
    if not is_current:
        headline = "Signal analysis is still running; previous-cycle rows are hidden."
        detail = (
            f"{currentness.get('reason') or 'Current evidence is not ready yet'} "
            f"{previous_signal_count} previous persisted signal row(s) are not shown as current."
        )
        topbar_label = f"{currentness.get('status_label') or 'Evidence not current'}"
    return {
        "cycle_id": cycle_id or "None",
        "cycle_label": _short_cycle_label(cycle_id),
        "topbar_label": topbar_label,
        "headline": headline,
        "detail": detail,
        "signal_count": len(signal_rows),
        "previous_signal_count": previous_signal_count,
        "display_mode": str(currentness.get("display_mode") or "current"),
        "visible_signal_count": visible,
        "render_limit": SIGNALS_RENDER_LIMIT,
        "is_limited": visible < len(signal_rows),
        "render_label": (
            f"Showing {visible} highest-priority row(s) out of {len(signal_rows)}"
            if visible < len(signal_rows)
            else f"Showing all {len(signal_rows)} row(s)"
        ),
        "report_count": report_count,
        "lane_count": len(lane_rows),
        "lanes_with_data": lanes_with_data,
        "configured_lanes": configured_lanes,
        "actionable_count": actionable_count,
        "context_count": context_count,
        "suppressed_count": suppressed_count,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "actionable_description": (
            "Passed score, confidence, source, freshness, and lane-policy gates; can affect "
            "the deterministic decision score."
        ),
        "context_description": (
            "Useful evidence, but guarded because score, confidence, source breadth, or lane "
            "policy is not strong enough for direct weighting."
        ),
        "suppressed_description": (
            "Kept for audit only because a required source, freshness, duplicate, or policy "
            "gate failed."
        ),
    }

def _context_signal_rows(evidence_pack: Mapping[str, object]) -> list[dict[str, object]]:
    return _signal_rows(evidence_pack, "context_signals")

def _signal_rows(evidence_pack: Mapping[str, object], key: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in _list_field(evidence_pack, key):
        signal = cast(Mapping[str, object], item)
        provenance = _mapping_field(signal, "provenance")
        actionability = str(signal["actionability"])
        freshness = str(signal["freshness"])
        verification = str(signal["verification_level"])
        timestamp_as_of = str(provenance.get("timestamp_as_of") or "unknown")
        signal_as_of = str(signal["as_of"])
        lane_key = str(signal["lane"])
        display_name = _label_text(lane_key)
        rows.append(
            {
                "ticker": str(signal["ticker"]),
                "lane": display_name,
                "display_name": display_name,
                "lane_key": lane_key,
                "cycle_id": str(signal["cycle_id"]),
                "signal_as_of": signal_as_of,
                "signal_as_of_label": _format_timestamp_label(signal_as_of),
                "direction": str(signal["direction"]),
                "direction_class": _direction_class(str(signal["direction"])),
                "actionability": actionability,
                "actionability_label": _label_text(actionability),
                "actionability_class": _signal_actionability_class(actionability),
                "freshness": freshness,
                "freshness_class": _freshness_class(freshness),
                "verification_level": verification,
                "verification_label": _label_text(verification),
                "source_tier": str(signal["source_tier"]),
                "confidence_pct": _percent(signal, "confidence"),
                "score": _score_text(signal),
                "score_value": _float_field(signal, "score"),
                "score_scale": _score_scale_label(lane_key),
                "score_scale_tooltip": _score_scale_tooltip(lane_key),
                "score_context_text": _score_context_text(signal),
                "summary": _signal_summary(signal),
                "source": _signal_source(signal),
                "source_key": str(provenance.get("source") or ""),
                "source_id": str(provenance.get("source_id") or ""),
                "timestamp_as_of": timestamp_as_of,
                "timestamp_label": _format_timestamp_label(timestamp_as_of),
                "reason_text": _signal_reason_text(signal),
                "reason_codes_label": _signal_reason_codes_label(signal),
                "actionability_reason_text": _signal_actionability_reason_text(signal),
            }
        )
    return rows

def _signal_lane_row(
    *,
    lane: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    lane_key = str(lane["lane"])
    display_name = _label_text(lane_key)
    actionable = sum(1 for signal in signals if signal["bucket"] == "Actionable")
    context = sum(1 for signal in signals if signal["bucket"] == "Context")
    suppressed = sum(1 for signal in signals if signal["bucket"] == "Suppressed")
    bullish = sum(1 for signal in signals if signal["direction"] == "BULLISH")
    bearish = sum(1 for signal in signals if signal["direction"] == "BEARISH")
    neutral = sum(1 for signal in signals if signal["direction"] == "NEUTRAL")
    top = signals[0] if signals else None
    avg_confidence = _average_int(signals, "confidence_pct")
    avg_score = _average_float(signals, "score_value")
    state = str(lane["state"])
    return {
        "lane": display_name,
        "display_name": display_name,
        "lane_key": lane_key,
        "state": state,
        "state_label": _label_text(state),
        "state_class": _lane_state_class(state),
        "configured": lane["configured"] is True,
        "configured_label": "Configured" if lane["configured"] is True else "Not configured",
        "configured_class": "pass" if lane["configured"] is True else "neutral",
        "dataset": str(lane["dataset"]),
        "source": str(lane["source"]),
        "verification_level": str(lane["verification_level"]),
        "runtime_effect": str(lane["runtime_effect"]),
        "evidence_required": str(lane["evidence_required"]),
        "rationale": str(lane["rationale"]),
        "signal_count": len(signals),
        "actionable_count": actionable,
        "context_count": context,
        "suppressed_count": suppressed,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "neutral_count": neutral,
        "avg_confidence_pct": avg_confidence,
        "avg_score": f"{avg_score:+.2f}",
        "top_ticker": _row_text(top, "ticker", "None"),
        "top_summary": _row_text(top, "summary", "No latest-cycle signal rows."),
        "top_score": _row_text(top, "score", "No score"),
        "top_direction": _row_text(top, "direction", "NONE"),
        "top_direction_class": _row_text(top, "direction_class", "neutral"),
    }

def _signal_dashboard_sort_key(row: Mapping[str, object]) -> tuple[int, float, str, str]:
    bucket_priority = {"Actionable": 0, "Context": 1, "Suppressed": 2}
    return (
        bucket_priority.get(str(row["bucket"]), 3),
        -abs(_float_field(row, "score_value")),
        str(row["lane"]),
        str(row["ticker"]),
    )

def _signal_lane_sort_key(row: Mapping[str, object]) -> tuple[int, int, str]:
    configured_priority = 0 if row["configured"] is True else 1
    return (configured_priority, -_int_field(row, "signal_count"), str(row["lane"]))

def _signal_bucket_label(key: str) -> str:
    labels = {
        "actionable_signals": "Actionable",
        "context_signals": "Context",
        "suppressed_signals": "Suppressed",
    }
    return labels.get(key, _label_text(key))

def _signal_bucket_class(key: str) -> str:
    if key == "actionable_signals":
        return "pass"
    if key == "suppressed_signals":
        return "block"
    return "warn"

def _signal_actionability_class(actionability: str) -> str:
    if actionability == "ACTIONABLE":
        return "pass"
    if actionability == "SUPPRESSED":
        return "block"
    return "warn"

def _freshness_class(freshness: str) -> str:
    if freshness == "FRESH":
        return "pass"
    if freshness in {"AGING", "STALE"}:
        return "warn"
    return "block"

def _lane_state_class(state: str) -> str:
    if state == "action_weighted":
        return "pass"
    if state == "corroborating":
        return "warn"
    if state == "disabled":
        return "block"
    return "neutral"

def _signal_reason_text(signal: Mapping[str, object]) -> str:
    reason_codes = _string_list(signal, "reason_codes")
    if not reason_codes:
        return "No reason code recorded."
    return " ".join(_reason_summary(code) for code in reason_codes)

def _signal_reason_codes_label(signal: Mapping[str, object]) -> str:
    reason_codes = _string_list(signal, "reason_codes")
    if not reason_codes:
        return "None"
    return _human_list([_label_text(code) for code in reason_codes])

def _score_context_text(signal: Mapping[str, object]) -> str:
    lane_key = str(signal.get("lane_key") or signal.get("lane") or "")
    score = _signal_score_value(signal)
    scale = _score_scale_label(lane_key)
    detail = _score_scale_tooltip(lane_key)
    if abs(score) <= DIRECTION_EPSILON:
        return (
            f"{scale}: {detail} Direction is neutral because {score:+.2f} is inside "
            f"the +/-{DIRECTION_EPSILON:.2f} noise band."
        )
    direction = "bullish" if score > 0 else "bearish"
    return f"{scale}: {detail} The sign is {direction} because the score is {score:+.2f}."

def _signal_actionability_reason_text(signal: Mapping[str, object]) -> str:
    actionability = str(signal.get("actionability") or "")
    score = _signal_score_value(signal)
    confidence_pct = _signal_confidence_pct(signal)
    reason = _signal_reason_text(signal)
    actionable_score = _SIGNAL_ACTIONABILITY_CONFIG.actionable_score
    min_confidence_pct = round(_SIGNAL_ACTIONABILITY_CONFIG.min_confidence * 100)
    score_clause = (
        f"score {score:+.2f}; action-weighted threshold is +/-{actionable_score:.2f}"
    )
    confidence_clause = (
        f"confidence {confidence_pct}%; minimum for action-weighted use is {min_confidence_pct}%"
    )
    if actionability == "ACTIONABLE":
        return (
            f"Action-weighted because {score_clause} and {confidence_clause}, and the "
            "lane policy/source gates passed."
        )
    blockers: list[str] = []
    if abs(score) < actionable_score:
        blockers.append(f"score is below +/-{actionable_score:.2f}")
    if confidence_pct < min_confidence_pct:
        blockers.append(f"confidence is below {min_confidence_pct}%")
    if blockers:
        return f"Context/excluded because {', and '.join(blockers)}. {reason}"
    if reason and reason != "No reason code recorded.":
        return f"Actionability was limited by policy/source gates: {reason}"
    return (
        f"Actionability is {str(signal.get('actionability_label') or actionability or 'not recorded')}; "
        "no detailed gate reason was recorded."
    )

def _signal_confidence_pct(signal: Mapping[str, object]) -> int:
    if "confidence_pct" in signal:
        return _int_field(signal, "confidence_pct")
    return _percent(signal, "confidence")

def _signal_score_value(signal: Mapping[str, object]) -> float:
    if "score_value" in signal:
        return _float_field(signal, "score_value")
    return _float_field(signal, "score")

def _signal_inspection_fields(
    row: Mapping[str, object],
    report: Mapping[str, object],
) -> dict[str, str]:
    return {
        "interpretation_text": _signal_interpretation_text(row, report),
        "decision_effect_text": _signal_decision_effect_text(row, report),
        "decision_alignment_text": _signal_decision_alignment_text(row, report),
        "quality_text": _signal_quality_text(row),
        "provenance_text": _signal_provenance_text(row),
        "score_context_text": _score_context_text(row),
        "actionability_reason_text": _signal_actionability_reason_text(row),
        "score_scale": _score_scale_label(str(row.get("lane_key") or "")),
        "score_scale_tooltip": _score_scale_tooltip(str(row.get("lane_key") or "")),
    }

def _signal_interpretation_text(
    row: Mapping[str, object],
    report: Mapping[str, object],
) -> str:
    ticker = str(report["ticker"])
    lane = str(row["lane"])
    direction = str(row["direction"]).lower()
    bucket = str(row["bucket"])
    score = str(row["score"])
    source = str(row.get("source") or "source not recorded")
    timestamp = _format_timestamp_label(_row_text(row, "timestamp_as_of", "unknown"))
    reason = _clean_text(row.get("reason_text")) or _clean_text(row.get("reason_codes_label"))
    summary = _clean_text(row.get("summary"))
    bucket_meaning = {
        "Actionable": "the engine can use it in the weighted decision score",
        "Context": "the engine keeps it as explanation or corroboration only",
        "Suppressed": "the engine records it for audit but excludes it from scoring",
    }.get(bucket, "the engine records it for review")
    parts = [
        (
            f"{lane} evidence row for {ticker}: direction {direction}, score {score}, "
            f"source {source} as of {timestamp}; {bucket_meaning}."
        )
    ]
    if reason:
        parts.append(f"Reason calculation: {reason}")
    if summary:
        parts.append(f"Runtime summary: {summary}")
    return " ".join(parts)

def _signal_decision_effect_text(
    row: Mapping[str, object],
    report: Mapping[str, object],
) -> str:
    ticker = str(report["ticker"])
    action = str(report["action"])
    gate = str(report["gate_status"])
    conviction = _int_field(report, "conviction_pct")
    bucket = str(row["bucket"])
    reason = str(row["reason_text"])
    if bucket == "Actionable":
        return (
            f"Included in the latest {ticker} evidence pack used by the deterministic "
            f"rules. Current final action is {action}, conviction {conviction}%, "
            f"gate {gate}."
        )
    if bucket == "Context":
        return (
            f"Available to explain the latest {ticker} judgment, but guarded from "
            f"direct scoring. Main reason: {reason}"
        )
    return (
        f"Excluded from the latest {ticker} decision score. It remains visible so the "
        f"user can audit weak, refresh-needed, duplicated, or unavailable evidence. Main reason: {reason}"
    )

def _signal_decision_alignment_text(
    row: Mapping[str, object],
    report: Mapping[str, object],
) -> str:
    direction = str(row["direction"])
    action = str(report["action"])
    ticker = str(report["ticker"])
    if direction == "NEUTRAL":
        return f"Neutral for {ticker}; it neither supports nor opposes the current {action}."
    if action in {"WATCH", "BUY"} and direction == "BULLISH":
        return f"Supports the current {action} posture for {ticker}."
    if action in {"WATCH", "BUY"} and direction == "BEARISH":
        return f"Works against the current {action} posture and should be read as caution."
    if action in {"NO_TRADE", "CLOSE_REVIEW"} and direction == "BEARISH":
        return f"Supports caution or no-trade treatment for {ticker}."
    if action in {"NO_TRADE", "CLOSE_REVIEW"} and direction == "BULLISH":
        return f"Potentially conflicts with the current no-trade/caution posture for {ticker}."
    return f"Compare this {direction.lower()} reading with the current {action} posture."

def _signal_quality_text(row: Mapping[str, object]) -> str:
    return (
        f"{row['verification_label']} evidence, {row['freshness']} freshness, "
        f"{row['confidence_pct']}% confidence, source tier {row['source_tier']}."
    )

def _signal_provenance_text(row: Mapping[str, object]) -> str:
    source_id = _row_text(row, "source_id", "unknown")
    as_of = _format_timestamp_label(_row_text(row, "timestamp_as_of", "unknown"))
    return f"{row['source']} / source id {source_id} / as-of {as_of}."

def _average_int(rows: Sequence[Mapping[str, object]], key: str) -> int:
    if not rows:
        return 0
    return round(sum(_int_field(row, key) for row in rows) / len(rows))

def _average_float(rows: Sequence[Mapping[str, object]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(_float_field(row, key) for row in rows) / len(rows)

def _signals_headline(
    signal_count: int,
    lanes_with_data: int,
    *,
    actionable_count: int,
    bullish_count: int,
    bearish_count: int,
    top_signal: str | None,
) -> str:
    if signal_count == 0:
        return "No latest-cycle signal rows are available yet."
    tilt = "balanced"
    if bullish_count > bearish_count:
        tilt = "bullish-tilted"
    elif bearish_count > bullish_count:
        tilt = "bearish-tilted"
    top = f" {top_signal}" if top_signal else ""
    return (
        f"{signal_count} signal rows across {lanes_with_data} active lane(s); "
        f"{actionable_count} can affect decisions and the mix is {tilt}.{top}"
    )

def _top_signal_summary(signal_rows: Sequence[Mapping[str, object]]) -> str | None:
    if not signal_rows:
        return None
    top = _sorted_signals(signal_rows)[0]
    lane = str(top.get("lane") or top.get("display_name") or "Signal")
    ticker = str(top.get("ticker") or "")
    direction = str(top.get("direction") or "UNKNOWN").lower()
    score = str(top.get("score") or "no score")
    summary = _clip_text(str(top.get("summary") or ""), 140)
    base = f"Strongest visible item: {ticker} {lane} is {direction} ({score})."
    return f"{base} {summary}" if summary else base

def _decision_explanation(
    base: Mapping[str, object],
    deterministic: Mapping[str, object],
    data_quality: Mapping[str, object],
) -> str:
    action = str(base["action"])
    gate_status = str(base["gate_status"])
    deterministic_action = str(deterministic["action"])
    source_count = _int_field(data_quality, "source_count")
    confirmed_count = _int_field(data_quality, "confirmed_signal_count")
    freshness = str(data_quality["freshness"]).lower()
    if action == "NO_TRADE":
        return (
            "The engine is not asking for a trade right now. "
            f"It saw {source_count} independent source(s), {confirmed_count} confirmed "
            f"signal(s), and {freshness} evidence; the current gate state is {gate_status}."
        )
    return (
        f"The final action is {action} because the deterministic pass produced "
        f"{deterministic_action} with {source_count} independent source(s) and "
        f"{confirmed_count} confirmed signal(s). Gate state: {gate_status}."
    )

def _signal_group_summary(
    signals: Sequence[Mapping[str, object]],
    *,
    positive: bool,
) -> str:
    if not signals:
        return "No signal in this group is active for the latest report."
    top = _sorted_signals(signals)[0]
    lane = str(top["lane"])
    direction = str(top["direction"]).lower()
    score = str(top["score"])
    summary = str(top["summary"])
    if positive:
        return f"Strongest item: {lane} is {direction} ({score}). {summary}"
    return f"Main caution: {lane} is {direction} ({score}). {summary}"

def _signal_summary(signal: Mapping[str, object]) -> str:
    explicit = _clean_text(signal.get("summary"))
    if explicit:
        return _clip_text(explicit, 220)
    reason_codes = _string_list(signal, "reason_codes")
    if reason_codes:
        return " ".join(_reason_summary(code) for code in reason_codes)
    lane = _label_text(str(signal["lane"]))
    direction = str(signal["direction"]).lower()
    provenance = _mapping_field(signal, "provenance")
    source = _service_label(str(provenance.get("source") or signal.get("source_tier") or "source"))
    timestamp = _format_timestamp_label(str(provenance.get("timestamp_as_of") or "unknown"))
    return (
        f"{lane} {direction} evidence from {source} as of {timestamp}. "
        "Open Inspect to review the source metrics and policy gates."
    )

def _signal_source(signal: Mapping[str, object]) -> str:
    provenance = _mapping_field(signal, "provenance")
    source = _service_label(str(provenance.get("source") or signal.get("source_tier") or "source"))
    tier = _label_text(str(signal.get("source_tier") or provenance.get("source_tier") or "source"))
    return f"{source} / {tier}"
