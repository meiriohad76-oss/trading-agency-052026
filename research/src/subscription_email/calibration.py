from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_subscription_email_calibration(
    *,
    ingest_summary_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    report = build_subscription_email_calibration(ingest_summary_path=ingest_summary_path)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "subscription-email-calibration.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "subscription-email-calibration.md").write_text(
        calibration_to_markdown(report),
        encoding="utf-8",
    )
    return report


def build_subscription_email_calibration(*, ingest_summary_path: Path) -> dict[str, Any]:
    summary = _json_object(ingest_summary_path)
    return {
        "schema_version": "0.1.0",
        "source_artifacts": {"ingest_summary": ingest_summary_path.as_posix()},
        "coverage": {
            "event_rows": _int(summary, "event_rows"),
            "news_rows": _int(summary, "news_rows"),
            "activity_rows": _int(summary, "activity_rows"),
            "manual_review_count": _int(summary, "manual_review_count"),
            "service_counts": _dict(summary, "service_counts"),
        },
        "runtime_guidance": {
            "news": "context_only_until_forward_validation",
            "activity_alerts": "context_only_until_forward_validation",
        },
        "verdict": "context_only_until_forward_validation",
        "rationale": (
            "Subscription emails can corroborate news and unusual-activity evidence, "
            "but action weighting should wait for forward validation on real mailbox coverage."
        ),
    }


def calibration_to_markdown(report: dict[str, Any]) -> str:
    coverage = _dict(report, "coverage")
    guidance = _dict(report, "runtime_guidance")
    lines = [
        "# T104 Subscription Email Calibration",
        "",
        f"Verdict: `{report['verdict']}`",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Deduped events | {coverage['event_rows']} |",
        f"| News rows | {coverage['news_rows']} |",
        f"| Activity rows | {coverage['activity_rows']} |",
        f"| Manual review | {coverage['manual_review_count']} |",
        "",
        "| Runtime lane | Guidance |",
        "| --- | --- |",
    ]
    for lane, value in sorted(guidance.items()):
        lines.append(f"| {lane} | {value} |")
    lines.extend(["", f"Rationale: {report['rationale']}", ""])
    return "\n".join(lines)


def _json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return payload


def _int(payload: dict[str, Any], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return int(value)


def _dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} must be an object")
    return value
