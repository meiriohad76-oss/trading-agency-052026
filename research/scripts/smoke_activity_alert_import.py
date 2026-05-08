from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

from activity_alerts.local_csv import read_activity_alert_csv  # noqa: E402
from activity_alerts.storage import write_activity_alert_frame, write_manifest  # noqa: E402
from activity_alerts.summary import (  # noqa: E402
    build_activity_alert_summary,
    write_activity_alert_summary,
)


def main() -> int:
    args = _parse_args()
    fetched_at = datetime.now(UTC)
    parquet_path = args.output_root / "parquet" / "unusual_activity_alerts.parquet"
    manifest_path = args.output_root / "manifests" / "unusual_activity_alerts.json"
    frame = read_activity_alert_csv(
        args.input,
        fetched_at=fetched_at,
        default_source=args.default_source,
    )
    rows_written = write_activity_alert_frame(parquet_path, frame)
    write_manifest(manifest_path, parquet_path, fetched_at=fetched_at)
    stored = pd.read_parquet(parquet_path)
    summary = build_activity_alert_summary(
        stored,
        input_path=args.input,
        parquet_path=parquet_path,
        manifest_path=manifest_path,
        rows_written=rows_written,
    )
    write_activity_alert_summary(summary, args.output_root)
    print(
        json.dumps(
            {
                "output_root": args.output_root.as_posix(),
                "row_count": summary["row_count"],
                "verdict": summary["verdict"],
            },
            sort_keys=True,
        )
    )
    return 0 if summary["verdict"] == "ready_for_research_batch" else 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test a local unusual-activity CSV import in an isolated output folder."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "research" / "results" / "t82-activity-alert-import",
    )
    parser.add_argument("--default-source", default="local-activity-alerts")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
