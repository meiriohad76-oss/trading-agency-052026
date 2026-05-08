from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))

from evaluation.actionability_calibration import write_actionability_calibration  # noqa: E402


def main() -> int:
    args = _parse_args()
    calibration = write_actionability_calibration(
        h1_verdicts_path=args.h1_verdicts,
        batch_status_path=args.batch_status,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {"output_root": args.output_root.as_posix(), "verdict": calibration["verdict"]}
        )
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write the T73 actionability calibration report.")
    parser.add_argument(
        "--h1-verdicts",
        type=Path,
        default=ROOT / "research" / "results" / "t73-actionability-calibration" / "h1-verdicts.csv",
    )
    parser.add_argument(
        "--batch-status",
        type=Path,
        default=(
            ROOT
            / "research"
            / "results"
            / "t73-actionability-calibration"
            / "batch-status.json"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "research" / "results" / "t73-actionability-calibration",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
