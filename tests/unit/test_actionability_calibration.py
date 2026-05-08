from __future__ import annotations

import json
from pathlib import Path

from evaluation.actionability_calibration import write_actionability_calibration

EXPECTED_MINIMUM_SOURCE_COUNT = 2


def test_write_actionability_calibration_records_conservative_thresholds(tmp_path: Path) -> None:
    h1_path = tmp_path / "h1-verdicts.csv"
    status_path = tmp_path / "batch-status.json"
    output_root = tmp_path / "calibration"
    _write_h1_verdicts(h1_path)
    _write_batch_status(status_path)

    calibration = write_actionability_calibration(
        h1_verdicts_path=h1_path,
        batch_status_path=status_path,
        output_root=output_root,
    )

    assert calibration["verdict"] == "keep_conservative_thresholds"
    assert (
        calibration["runtime_thresholds"]["minimum_source_count"]
        == EXPECTED_MINIMUM_SOURCE_COUNT
    )
    assert calibration["surviving_lanes"] == []
    markdown = (output_root / "actionability-calibration.md").read_text(encoding="utf-8")
    assert "| news | not_evaluated | n/a | n/a | n/a | n/a |" in markdown


def _write_h1_verdicts(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "signal,best_horizon,mean_ic,t_stat,information_ratio,p_value_bonferroni,verdict",
                "fundamentals,20,0.05,1.1,0.12,1.0,inconclusive",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_batch_status(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "config": {
                    "start": "2021-01-01",
                    "end": "2025-12-31",
                    "signals": ["fundamentals", "news"],
                },
            }
        ),
        encoding="utf-8",
    )
