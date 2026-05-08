from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence

DEGRADED_SOURCE_STATUSES = {"DEGRADED", "STALE", "UNAVAILABLE", "RATE_LIMITED"}


def runtime_metrics_text(
    *,
    source_health: Sequence[Mapping[str, object]],
    selection_reports: Sequence[Mapping[str, object]],
    risk_decisions: Sequence[Mapping[str, object]],
) -> str:
    """Render runtime counters and gauges in Prometheus text format."""
    lines = [
        "# HELP agency_source_health_total Runtime data-source health rows.",
        "# TYPE agency_source_health_total gauge",
        f"agency_source_health_total {len(source_health)}",
        "# HELP agency_source_degraded_total Runtime data sources needing attention.",
        "# TYPE agency_source_degraded_total gauge",
        f"agency_source_degraded_total {_degraded_source_count(source_health)}",
        "# HELP agency_selection_reports_total Recent selection reports visible to runtime.",
        "# TYPE agency_selection_reports_total gauge",
        f"agency_selection_reports_total {len(selection_reports)}",
        "# HELP agency_risk_decisions_total Recent risk decisions visible to runtime.",
        "# TYPE agency_risk_decisions_total gauge",
        f"agency_risk_decisions_total {len(risk_decisions)}",
    ]
    lines.extend(
        _labeled_counter("agency_final_action_total", _counter(selection_reports, "final_action"))
    )
    lines.extend(
        _labeled_counter("agency_risk_decision_total", _counter(risk_decisions, "decision"))
    )
    return "\n".join(lines) + "\n"


def _degraded_source_count(source_health: Sequence[Mapping[str, object]]) -> int:
    return sum(
        1 for source in source_health if str(source.get("status")) in DEGRADED_SOURCE_STATUSES
    )


def _counter(payloads: Sequence[Mapping[str, object]], key: str) -> Counter[str]:
    return Counter(str(payload[key]) for payload in payloads if key in payload)


def _labeled_counter(metric: str, values: Counter[str]) -> list[str]:
    if not values:
        return [f'{metric}{{value="none"}} 0']
    return [
        f'{metric}{{value="{_escape_label(label)}"}} {count}'
        for label, count in sorted(values.items())
    ]


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
