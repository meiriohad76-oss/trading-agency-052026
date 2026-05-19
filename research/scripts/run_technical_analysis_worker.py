from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from pit.loader import PITLoader  # noqa: E402
from technical_analysis.worker import (  # noqa: E402
    TechnicalAnalysisWorkerConfig,
    run_technical_analysis_worker,
)


def main() -> int:
    args = _parse_args()
    config = TechnicalAnalysisWorkerConfig(
        start=args.start,
        end=args.end,
        tickers=tuple(ticker.upper() for ticker in args.ticker),
        horizons=tuple(args.horizon or (5, 20)),
        step_size_days=args.step_days,
        thresholds=tuple(args.threshold or (0.15, 0.30, 0.50)),
        lookback_days=args.lookback_days,
        min_train_observations=args.min_train_observations,
        min_test_observations=args.min_test_observations,
    )
    loader = PITLoader(parquet_root=args.parquet_root, manifest_root=args.manifest_root)
    result = run_technical_analysis_worker(
        config=config,
        loader=loader,
        output_root=args.output_root,
    )
    print(
        json.dumps(
            {
                "output_root": args.output_root.as_posix(),
                "verdict": result.calibration["verdict"],
                "written_paths": result.written_paths,
            },
            sort_keys=True,
        )
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the technical-analysis worker.")
    parser.add_argument("--start", type=_date, required=True)
    parser.add_argument("--end", type=_date, required=True)
    parser.add_argument("--ticker", action="append", required=True)
    parser.add_argument("--horizon", type=int, action="append")
    parser.add_argument("--threshold", type=float, action="append")
    parser.add_argument("--step-days", type=int, default=21)
    parser.add_argument("--lookback-days", type=int, default=260)
    parser.add_argument("--min-train-observations", type=int, default=20)
    parser.add_argument("--min-test-observations", type=int, default=10)
    parser.add_argument(
        "--manifest-root",
        type=Path,
        default=ROOT / "research" / "data" / "manifests",
    )
    parser.add_argument(
        "--parquet-root",
        type=Path,
        default=ROOT / "research" / "data" / "parquet",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "research" / "results" / "latest-technical-analysis-worker",
    )
    return parser.parse_args()


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
