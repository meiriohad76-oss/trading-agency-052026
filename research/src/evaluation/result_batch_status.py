from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evaluation.result_batch import ResearchBatchResult


def result_to_markdown(result: ResearchBatchResult) -> str:
    """Render compact status for `research/results/` and docs/findings.md."""
    lines = [
        "# Research Batch Status",
        "",
        f"Window: {result.config.start.isoformat()} to {result.config.end.isoformat()}",
        f"Signals: {', '.join(result.config.signals)}",
        "",
        "## Dataset Readiness",
        "",
        "| Dataset | Status | Reason |",
        "| --- | --- | --- |",
        *list(_dataset_rows(result)),
        "",
        "## Hypothesis Artifacts",
        "",
        "| Hypothesis | Status | Reason |",
        "| --- | --- | --- |",
        _hypothesis_line("H1", "written" if result.h1_ran else "blocked", _h1_reason(result)),
        _hypothesis_line("H2", "blocked", "requires accepted H1 lane verdicts"),
        _hypothesis_line("H3", "blocked", "requires deterministic profile/AB input rows"),
        _hypothesis_line("H4/H5", "blocked", "requires H1 surviving lanes and price data"),
    ]
    return "\n".join(lines) + "\n"


def result_to_json(result: ResearchBatchResult) -> str:
    payload = {
        "config": {
            **asdict(result.config),
            "start": result.config.start.isoformat(),
            "end": result.config.end.isoformat(),
            "static_universe": (
                None
                if result.config.static_universe is None
                else sorted(result.config.static_universe)
            ),
        },
        "dataset_checks": [asdict(check) for check in result.dataset_checks],
        "h1_ran": result.h1_ran,
        "written_paths": list(result.written_paths),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _dataset_rows(result: ResearchBatchResult) -> tuple[str, ...]:
    return tuple(
        f"| {check.dataset} | {'ready' if check.available else 'missing'} | {check.reason} |"
        for check in result.dataset_checks
    )


def _h1_reason(result: ResearchBatchResult) -> str:
    if result.h1_ran:
        return "H1 IC and verdict files written"
    missing = [check.dataset for check in result.dataset_checks if not check.available]
    return "missing required datasets: " + ", ".join(missing)


def _hypothesis_line(name: str, status: str, reason: str) -> str:
    return f"| {name} | {status} | {reason} |"
