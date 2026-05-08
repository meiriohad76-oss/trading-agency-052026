from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))

from data_refresh.output_validation import validate_live_refresh_outputs  # noqa: E402


def main() -> int:
    args = _parse_args()
    rows = validate_live_refresh_outputs(
        status_path=args.status_path,
        manifest_root=args.manifest_root,
        datasets=tuple(args.dataset),
    )
    print(json.dumps(rows, indent=2, sort_keys=True))
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate live data refresh outputs.")
    parser.add_argument(
        "--status-path",
        type=Path,
        default=ROOT / "research" / "results" / "t72-live" / "data-refresh-status.json",
    )
    parser.add_argument(
        "--manifest-root",
        type=Path,
        default=ROOT / "research" / "data" / "manifests",
    )
    parser.add_argument("--dataset", action="append", default=[])
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
