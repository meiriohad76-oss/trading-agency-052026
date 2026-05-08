from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from evaluation.result_batch import ResearchBatchConfig, run_research_batch  # noqa: E402
from evaluation.signal_registry import SIGNALS  # noqa: E402


def main() -> None:
    args = _parse_args()
    result = run_research_batch(
        ResearchBatchConfig(
            start=date.fromisoformat(args.start),
            end=date.fromisoformat(args.end),
            signals=tuple(args.signal),
            horizons=tuple(args.horizon or (5, 20)),
            step_size_days=args.step_days,
            static_universe=(
                None if args.ticker is None else frozenset(ticker.upper() for ticker in args.ticker)
            ),
        ),
        output_root=args.output_root,
        manifest_root=ROOT / "research" / "data" / "manifests",
        parquet_root=ROOT / "research" / "data" / "parquet",
    )
    state = "ran" if result.h1_ran else "blocked"
    print(f"Research batch {state}; wrote {args.output_root}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the H1-H5 research result batch.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--signal", choices=sorted(SIGNALS), action="append", required=True)
    parser.add_argument("--horizon", type=int, action="append")
    parser.add_argument("--step-days", type=int, default=21)
    parser.add_argument("--ticker", action="append", help="Static universe ticker; repeatable.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "research" / "results" / "t66",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
