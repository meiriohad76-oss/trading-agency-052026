from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime

from agency.contracts import validate_contract

DEFAULT_REQUIRED_SAMPLE_COUNT = 50
DEFAULT_NEAR_MISS_MARGIN = 0.15
DEFAULT_WATCH_THRESHOLD = 0.5
DEFAULT_WHAT_IF_HORIZONS = (1, 5, 20)
DEFAULT_NEAR_MISS_LIMIT = 25


def build_learning_outcome(
    outcomes: Sequence[Mapping[str, object]] | None = None,
    *,
    selection_reports: Sequence[Mapping[str, object]] = (),
    price_history: Sequence[Mapping[str, object]] = (),
    generated_at: str | None = None,
    required_sample_count: int = DEFAULT_REQUIRED_SAMPLE_COUNT,
    near_miss_margin: float = DEFAULT_NEAR_MISS_MARGIN,
) -> dict[str, object]:
    """Build a conservative learning snapshot from closed paper outcomes."""
    sample_count = len(outcomes or [])
    status = "READY" if sample_count >= required_sample_count else "PREMATURE"
    metrics = _outcome_metrics(outcomes or [])
    near_miss_journal = build_near_miss_journal(
        selection_reports,
        price_history=price_history,
        near_miss_margin=near_miss_margin,
    )
    snapshot: dict[str, object] = {
        "schema_version": "0.1.0",
        "generated_at": generated_at or _now_utc(),
        "status": status,
        "sample_count": sample_count,
        "required_sample_count": required_sample_count,
        "message": _message(status, sample_count, required_sample_count),
        "requirements": _requirements(sample_count, required_sample_count),
        "metrics": metrics,
        "recommendations": _recommendations(status, metrics),
        "near_miss_journal": near_miss_journal,
    }
    validate_contract("learning-outcome", snapshot)
    return snapshot


def build_near_miss_journal(
    selection_reports: Sequence[Mapping[str, object]],
    *,
    price_history: Sequence[Mapping[str, object]] = (),
    watch_threshold: float = DEFAULT_WATCH_THRESHOLD,
    near_miss_margin: float = DEFAULT_NEAR_MISS_MARGIN,
    horizons: Sequence[int] = DEFAULT_WHAT_IF_HORIZONS,
    limit: int = DEFAULT_NEAR_MISS_LIMIT,
) -> dict[str, object]:
    """Log almost-selected candidates and their forward what-if returns."""
    price_index = _price_index(price_history)
    rows = [
        _near_miss_row(
            report,
            price_index=price_index,
            watch_threshold=watch_threshold,
            horizons=horizons,
        )
        for report in selection_reports
        if _is_near_miss(
            report,
            watch_threshold=watch_threshold,
            near_miss_margin=near_miss_margin,
        )
    ]
    limited = sorted(rows, key=_near_miss_sort_key)[:limit]
    return {
        "schema_version": "0.1.0",
        "watch_threshold": watch_threshold,
        "near_miss_margin": near_miss_margin,
        "near_miss_count": len(limited),
        "summary": _near_miss_summary(limited, horizons),
        "rows": limited,
    }


def _requirements(sample_count: int, required_sample_count: int) -> list[dict[str, str]]:
    sample_status = "PASS" if sample_count >= required_sample_count else "WARN"
    return [
        {
            "name": "closed_trade_samples",
            "status": sample_status,
            "reason": f"{sample_count} of {required_sample_count} required samples",
        },
        {
            "name": "backtest_validation",
            "status": "WARN",
            "reason": "research validation is still the authority for threshold changes",
        },
        {
            "name": "audit_persistence",
            "status": "WARN",
            "reason": "learning changes are not persisted or applied automatically",
        },
    ]


def _message(status: str, sample_count: int, required_sample_count: int) -> str:
    if status == "READY":
        return "Learning sample size is ready for review; automatic tuning remains disabled."
    return f"Sample size {sample_count} is below the {required_sample_count} outcome threshold."


def _outcome_metrics(outcomes: Sequence[Mapping[str, object]]) -> dict[str, object]:
    returns = [_float_value(outcome.get("return_pct")) for outcome in outcomes]
    known_returns = [value for value in returns if value is not None]
    wins = sum(1 for value in known_returns if value > 0.0)
    losses = sum(1 for value in known_returns if value < 0.0)
    return {
        "known_return_count": len(known_returns),
        "unknown_return_count": len(outcomes) - len(known_returns),
        "win_count": wins,
        "loss_count": losses,
        "flat_count": sum(1 for value in known_returns if value == 0.0),
        "mean_return_pct": _mean(known_returns),
        "win_rate": None if not known_returns else wins / len(known_returns),
        "decision_counts": _decision_counts(outcomes),
    }


def _recommendations(status: str, metrics: Mapping[str, object]) -> list[dict[str, str]]:
    recommendations = [
        {
            "name": "auto_tuning",
            "status": "DISABLED",
            "reason": "Learning output is advisory; thresholds require explicit review.",
        }
    ]
    if status != "READY":
        recommendations.append(
            {
                "name": "collect_more_paper_outcomes",
                "status": "WARN",
                "reason": "More reviewed paper outcomes are required before threshold review.",
            }
        )
    elif _float_or_none(metrics.get("win_rate")) is None:
        recommendations.append(
            {
                "name": "record_realized_returns",
                "status": "WARN",
                "reason": "Reviewed samples exist, but realized return fields are missing.",
            }
        )
    else:
        recommendations.append(
            {
                "name": "threshold_review",
                "status": "READY",
                "reason": "Sample size is ready for human-reviewed threshold analysis.",
            }
        )
    return recommendations


def _near_miss_row(
    report: Mapping[str, object],
    *,
    price_index: Mapping[str, Sequence[tuple[date, float]]],
    watch_threshold: float,
    horizons: Sequence[int],
) -> dict[str, object]:
    deterministic = _mapping_value(report.get("deterministic"))
    evidence_pack = _mapping_value(report.get("evidence_pack"))
    data_quality = _mapping_value(evidence_pack.get("data_quality"))
    ticker = str(report.get("ticker", "")).upper()
    score = _coerced_float(deterministic.get("score")) or 0.0
    as_of = str(report.get("as_of", ""))
    what_if = _what_if_returns(
        ticker=ticker,
        as_of=as_of,
        price_index=price_index,
        horizons=horizons,
    )
    return {
        "cycle_id": str(report.get("cycle_id", "")),
        "ticker": ticker,
        "as_of": as_of,
        "final_action": str(report.get("final_action", "")),
        "final_conviction": _coerced_float(report.get("final_conviction")),
        "deterministic_score": round(score, 6),
        "inclusion_gap": round(max(0.0, watch_threshold - score), 6),
        "miss_reason": _near_miss_reason(report, score, watch_threshold),
        "policy_gate_status": _policy_gate_status(report),
        "source_count": _coerced_int(data_quality.get("source_count")),
        "confirmed_signal_count": _coerced_int(data_quality.get("confirmed_signal_count")),
        "strongest_lanes": _strongest_lanes(evidence_pack),
        "what_if": what_if,
    }


def _is_near_miss(
    report: Mapping[str, object],
    *,
    watch_threshold: float,
    near_miss_margin: float,
) -> bool:
    action = str(report.get("final_action", ""))
    if action in {"BUY", "SELL", "SHORT", "COVER", "WATCH", "HOLD"}:
        return False
    deterministic = _mapping_value(report.get("deterministic"))
    score = _coerced_float(deterministic.get("score")) or 0.0
    if action == "CLOSE_REVIEW" and score >= watch_threshold:
        return True
    return score > 0 and (watch_threshold - score) <= near_miss_margin


def _near_miss_reason(
    report: Mapping[str, object],
    score: float,
    watch_threshold: float,
) -> str:
    if str(report.get("final_action")) == "CLOSE_REVIEW":
        return "LLM or policy demoted an otherwise watchable setup."
    blockers = _string_values(_mapping_value(report.get("deterministic")).get("blockers"))
    if blockers:
        return f"Blocked by {blockers[0]}."
    reason_codes = _string_values(_mapping_value(report.get("deterministic")).get("reason_codes"))
    if reason_codes:
        return f"Missed inclusion because {reason_codes[0]}."
    gap = max(0.0, watch_threshold - score)
    return f"Score was {gap:.2f} below the WATCH threshold."


def _policy_gate_status(report: Mapping[str, object]) -> str:
    statuses = [
        str(gate.get("status", "UNKNOWN"))
        for gate in _mapping_sequence(report.get("policy_gates"))
    ]
    if "BLOCK" in statuses:
        return "BLOCK"
    if "WARN" in statuses:
        return "WARN"
    if "PASS" in statuses:
        return "PASS"
    return "UNKNOWN"


def _strongest_lanes(evidence_pack: Mapping[str, object]) -> list[str]:
    signals = [
        signal
        for key in ("actionable_signals", "context_signals", "suppressed_signals")
        for signal in _mapping_sequence(evidence_pack.get(key))
    ]
    ranked = sorted(signals, key=lambda signal: abs(_coerced_float(signal.get("score")) or 0.0))
    return [
        str(signal.get("lane", "unknown"))
        for signal in reversed(ranked[-3:])
    ]


def _what_if_returns(
    *,
    ticker: str,
    as_of: str,
    price_index: Mapping[str, Sequence[tuple[date, float]]],
    horizons: Sequence[int],
) -> dict[str, object]:
    rows = list(price_index.get(ticker, ()))
    start_date = _date_from_text(as_of)
    if start_date is None or not rows:
        return {"status": "pending", "entry_date": None, "entry_close": None, "horizons": []}
    entry_index = _first_price_index_at_or_after(rows, start_date)
    if entry_index is None:
        return {"status": "pending", "entry_date": None, "entry_close": None, "horizons": []}
    entry_date, entry_close = rows[entry_index]
    horizon_rows = []
    complete = False
    for horizon in horizons:
        target_index = entry_index + horizon
        if target_index >= len(rows):
            horizon_rows.append(
                {"horizon_days": horizon, "status": "pending", "return_pct": None}
            )
            continue
        exit_date, exit_close = rows[target_index]
        complete = True
        horizon_rows.append(
            {
                "horizon_days": horizon,
                "status": "complete",
                "exit_date": exit_date.isoformat(),
                "exit_close": exit_close,
                "return_pct": round((exit_close / entry_close - 1.0) * 100.0, 4),
            }
        )
    return {
        "status": "complete" if complete else "pending",
        "entry_date": entry_date.isoformat(),
        "entry_close": entry_close,
        "horizons": horizon_rows,
    }


def _near_miss_summary(
    rows: Sequence[Mapping[str, object]],
    horizons: Sequence[int],
) -> dict[str, object]:
    preferred_horizon = horizons[0] if horizons else 1
    returns = [
        value
        for row in rows
        for value in [_what_if_return_for_horizon(row, preferred_horizon)]
        if value is not None
    ]
    return {
        "evaluated_count": len(returns),
        "pending_count": len(rows) - len(returns),
        "preferred_horizon_days": preferred_horizon,
        "mean_return_pct": _mean(returns),
        "win_rate": (
            None
            if not returns
            else sum(1 for value in returns if value > 0) / len(returns)
        ),
    }


def _what_if_return_for_horizon(row: Mapping[str, object], horizon: int) -> float | None:
    what_if = _mapping_value(row.get("what_if"))
    for item in _mapping_sequence(what_if.get("horizons")):
        if _coerced_int(item.get("horizon_days")) == horizon:
            return _coerced_float(item.get("return_pct"))
    return None


def _near_miss_sort_key(row: Mapping[str, object]) -> tuple[float, str]:
    gap = _coerced_float(row.get("inclusion_gap")) or 0.0
    score = _coerced_float(row.get("deterministic_score")) or 0.0
    return (gap, f"{-score:.6f}:{row.get('ticker', '')}")


def _price_index(
    price_history: Sequence[Mapping[str, object]],
) -> dict[str, list[tuple[date, float]]]:
    indexed: dict[str, list[tuple[date, float]]] = {}
    for row in price_history:
        ticker = str(row.get("ticker", "")).upper()
        value_date = _date_from_text(row.get("date") or row.get("timestamp_as_of"))
        close = _coerced_float(row.get("close"))
        if not ticker or value_date is None or close is None or close <= 0:
            continue
        indexed.setdefault(ticker, []).append((value_date, close))
    return {ticker: sorted(values) for ticker, values in indexed.items()}


def _first_price_index_at_or_after(
    rows: Sequence[tuple[date, float]],
    start_date: date,
) -> int | None:
    for index, (value_date, _close) in enumerate(rows):
        if value_date >= start_date:
            return index
    return None


def _decision_counts(outcomes: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for outcome in outcomes:
        decision = str(outcome.get("review_decision", "UNKNOWN")).upper()
        counts[decision] = counts.get(decision, 0) + 1
    return counts


def _mapping_value(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_sequence(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_values(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return []
    return [str(item) for item in value]


def _coerced_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    return float(value)


def _coerced_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _date_from_text(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None


def _float_value(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _float_or_none(value: object) -> float | None:
    return value if isinstance(value, float) else None


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
