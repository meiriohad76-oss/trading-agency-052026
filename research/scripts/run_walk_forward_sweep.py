from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from backtests.portfolio import CostModel  # noqa: E402
from backtests.walk_forward import WalkForwardConfig  # noqa: E402
from evaluation.signal_registry import SIGNALS  # noqa: E402
from evaluation.sweep import SweepPoint, run_parameter_sweep  # noqa: E402
from pit.loader import PITLoader  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run H5 walk-forward parameter sweep.")
    parser.add_argument("--signal", choices=sorted(SIGNALS), required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--step-days", type=int, action="append", required=True)
    parser.add_argument("--max-positions", type=int, action="append", required=True)
    parser.add_argument("--threshold", type=float, action="append")
    parser.add_argument("--bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument("--ticker", action="append", help="Static universe ticker; repeatable.")
    parser.add_argument("--output-csv", type=Path)
    args = parser.parse_args()

    base_config = WalkForwardConfig(
        static_universe=None if args.ticker is None else {ticker.upper() for ticker in args.ticker},
        cost_model=CostModel(bps_per_side=args.bps, slippage_bps=args.slippage_bps),
    )
    points = [
        SweepPoint(step_size_days=step, max_positions=max_pos, score_threshold=threshold)
        for step in args.step_days
        for max_pos in args.max_positions
        for threshold in (args.threshold or [0.0])
    ]
    sweep = run_parameter_sweep(
        name=args.signal,
        base_config=base_config,
        points=points,
        loader=PITLoader(),
        signal_fn=SIGNALS[args.signal],
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
    )
    if args.output_csv is not None:
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        sweep.to_csv(args.output_csv, index=False)
    print(sweep.to_string(index=False))


if __name__ == "__main__":
    main()
