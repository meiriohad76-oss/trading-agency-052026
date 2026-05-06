from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))

from universe.membership import build_universe_membership  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build historical universe membership parquet.")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=ROOT / "research" / "scripts" / "data" / "universe_membership",
    )
    parser.add_argument(
        "--parquet-path",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "universe_membership.parquet",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "universe_membership.json",
    )
    args = parser.parse_args()

    outputs = build_universe_membership(
        source_dir=args.source_dir,
        parquet_path=args.parquet_path,
        manifest_path=args.manifest_path,
    )
    print(
        f"wrote {outputs.row_count} rows to {outputs.parquet_path} "
        f"with checksum {outputs.checksum}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
