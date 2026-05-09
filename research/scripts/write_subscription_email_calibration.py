from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))

from subscription_email.calibration import write_subscription_email_calibration  # noqa: E402


def main() -> int:
    args = _parse_args()
    report = write_subscription_email_calibration(
        ingest_summary_path=args.ingest_summary,
        output_root=args.output_root,
    )
    print(json.dumps({"output_root": args.output_root.as_posix(), "verdict": report["verdict"]}))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write the T104 subscription email calibration.")
    parser.add_argument(
        "--ingest-summary",
        type=Path,
        default=(
            ROOT
            / "research"
            / "results"
            / "latest-subscription-emails"
            / "subscription-email-ingest.json"
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "research" / "results" / "latest-subscription-email-calibration",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
