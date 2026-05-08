from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

from activity_alerts.local_csv import read_activity_alert_csv  # noqa: E402
from activity_alerts.storage import write_activity_alert_frame, write_manifest  # noqa: E402


def main() -> int:
    args = _parse_args()
    fetched_at = datetime.now(UTC)
    frame = read_activity_alert_csv(
        args.input,
        fetched_at=fetched_at,
        default_source=args.default_source,
    )
    rows_written = write_activity_alert_frame(args.output_path, frame)
    write_manifest(args.manifest_path, args.output_path, fetched_at=fetched_at)
    print(
        json.dumps(
            {
                "dataset": "unusual_activity_alerts",
                "rows_written": rows_written,
                "output_path": args.output_path.as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import local unusual-activity alert CSV.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--output-path",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "unusual_activity_alerts.parquet",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "unusual_activity_alerts.json",
    )
    parser.add_argument("--default-source", default="local-activity-alerts")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
