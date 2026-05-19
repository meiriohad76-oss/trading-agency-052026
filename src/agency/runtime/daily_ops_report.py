from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path


def build_daily_ops_report(
    *,
    report_date: date | None = None,
    operational_readiness: Mapping[str, object] | None = None,
    provider_readiness: Mapping[str, object] | None = None,
    pipeline_summary: Mapping[str, object] | None = None,
    live_cycle_summary: Mapping[str, object] | None = None,
    paper_broker_summary: Mapping[str, object] | None = None,
    massive_usage: Mapping[str, object] | None = None,
) -> dict[str, object]:
    operational = dict(operational_readiness or {})
    providers = dict(provider_readiness or {})
    pipeline = dict(pipeline_summary or {})
    live_cycle = dict(live_cycle_summary or {})
    broker = dict(paper_broker_summary or {})
    usage = dict(massive_usage or {})
    blockers = _blockers(operational, providers, pipeline, live_cycle, broker)
    warnings = _warnings(operational, providers, usage)
    return {
        "schema_version": "0.1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "report_date": (report_date or date.today()).isoformat(),
        "verdict": _verdict(blockers, warnings),
        "blockers": blockers,
        "warnings": warnings,
        "sections": {
            "operational_readiness": _readiness_section(operational),
            "provider_readiness": _provider_section(providers),
            "pipeline": _pipeline_section(pipeline),
            "live_cycle": _live_cycle_section(live_cycle),
            "paper_broker": _broker_section(broker),
            "massive_usage": _massive_section(usage),
        },
        "next_actions": _next_actions(blockers, warnings, operational),
    }


def write_daily_ops_report(report: Mapping[str, object], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "daily-ops-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "daily-ops-report.md").write_text(
        daily_ops_markdown(report),
        encoding="utf-8",
    )


def daily_ops_markdown(report: Mapping[str, object]) -> str:
    sections = _mapping(report.get("sections"))
    lines = [
        "# Daily Ops Report",
        "",
        f"Date: `{report['report_date']}`",
        f"Verdict: `{report['verdict']}`",
        "",
        "## Blockers",
        "",
        *_bullet_lines(_string_sequence(report.get("blockers")), empty="No blockers."),
        "",
        "## Warnings",
        "",
        *_bullet_lines(_string_sequence(report.get("warnings")), empty="No warnings."),
        "",
        "## Summary",
        "",
        _section_line("Operational", _mapping(sections.get("operational_readiness"))),
        _section_line("Providers", _mapping(sections.get("provider_readiness"))),
        _section_line("Pipeline", _mapping(sections.get("pipeline"))),
        _section_line("Live cycle", _mapping(sections.get("live_cycle"))),
        _section_line("Paper broker", _mapping(sections.get("paper_broker"))),
        _section_line("Massive usage", _mapping(sections.get("massive_usage"))),
        "",
        "## Next Actions",
        "",
        *_bullet_lines(_string_sequence(report.get("next_actions")), empty="No next actions."),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _readiness_section(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": payload.get("status_label", "Unknown"),
        "state": payload.get("state", "unknown"),
        "blockers": payload.get("blocker_count", 0),
        "warnings": payload.get("warning_count", 0),
    }


def _provider_section(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": payload.get("status_label", "Unknown"),
        "configured": payload.get("configured_count", 0),
        "providers": payload.get("provider_count", 0),
        "blockers": payload.get("blocker_count", 0),
    }


def _pipeline_section(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": payload.get("verdict", "not_run"),
        "completed": payload.get("successful_step_count", 0),
        "steps": payload.get("step_count", 0),
        "failed_step": payload.get("failed_step"),
    }


def _live_cycle_section(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "verdict": payload.get("verdict", "unknown"),
        "cycle_id": payload.get("cycle_id", "unknown"),
        "evidence_packs": payload.get("evidence_pack_count", payload.get("evidence_packs", 0)),
        "signals": payload.get("signal_count", payload.get("signals", 0)),
    }


def _broker_section(payload: Mapping[str, object]) -> dict[str, object]:
    broker = _mapping(payload.get("broker", payload))
    return {
        "verdict": payload.get("verdict", "unknown"),
        "mode": broker.get("mode", "paper"),
        "account_status": broker.get("account_status", "unknown"),
        "positions": broker.get("positions", 0),
        "open_orders": broker.get("open_orders", 0),
    }


def _massive_section(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "enabled": payload.get("enabled", False),
        "date": payload.get("date", "unknown"),
        "requests_made": payload.get("requests_made", 0),
        "requests_remaining": payload.get("requests_remaining", 0),
        "daily_request_budget": payload.get("daily_request_budget", 0),
    }


def _blockers(
    operational: Mapping[str, object],
    providers: Mapping[str, object],
    pipeline: Mapping[str, object],
    live_cycle: Mapping[str, object],
    broker: Mapping[str, object],
) -> list[str]:
    blockers: list[str] = []
    if operational.get("ready") is False:
        blockers.append("Operational readiness is blocked.")
    if providers.get("ready") is False:
        blockers.append("A required active provider key is missing.")
    if pipeline and pipeline.get("ok") is False:
        blockers.append(f"Pipeline failed at {pipeline.get('failed_step')}.")
    verdict = str(live_cycle.get("verdict", ""))
    if verdict.startswith("blocked"):
        blockers.append(f"Latest runtime cycle is {verdict}.")
    if broker and broker.get("verdict") == "paper_trade_attention_required":
        blockers.append("Paper broker validation needs manual attention.")
    return blockers


def _warnings(
    operational: Mapping[str, object],
    providers: Mapping[str, object],
    massive_usage: Mapping[str, object],
) -> list[str]:
    warnings: list[str] = []
    if _int_value(operational.get("warning_count")) > 0:
        warnings.append("Operational readiness has warnings.")
    if _int_value(providers.get("warning_count")) > 0:
        warnings.append("Provider readiness has planned or partial key warnings.")
    remaining = _int_value(massive_usage.get("requests_remaining"))
    budget = _int_value(massive_usage.get("daily_request_budget"))
    if budget > 0 and remaining <= max(2, budget // 10):
        warnings.append("Massive local request budget is almost exhausted.")
    return warnings


def _verdict(blockers: Sequence[str], warnings: Sequence[str]) -> str:
    if blockers:
        return "blocked"
    if warnings:
        return "ready_with_attention"
    return "ready"


def _next_actions(
    blockers: Sequence[str],
    warnings: Sequence[str],
    operational: Mapping[str, object],
) -> list[str]:
    configured = _string_sequence(operational.get("next_actions"))
    if configured:
        return configured
    if blockers:
        return list(blockers)
    if warnings:
        return list(warnings)
    return ["Run the paper review queue and record approve/defer/reject decisions."]


def _section_line(label: str, section: Mapping[str, object]) -> str:
    parts = [f"{key}={value}" for key, value in section.items()]
    return f"- {label}: " + ", ".join(parts)


def _bullet_lines(values: Sequence[str], *, empty: str) -> list[str]:
    if not values:
        return [f"- {empty}"]
    return [f"- {value}" for value in values]


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _string_sequence(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0
