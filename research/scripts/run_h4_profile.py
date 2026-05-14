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
from evaluation.profile import profile_strategy, profile_to_frame  # noqa: E402
from evaluation.signal_registry import SIGNALS  # noqa: E402
from pit.loader import PITLoader  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run H4 strategy profile.")
    parser.add_argument("--signal", choices=sorted(SIGNALS), required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--step-days", type=int, default=5)
    parser.add_argument("--max-positions", type=int, default=10)
    parser.add_argument("--score-threshold", type=float, default=0.0)
    parser.add_argument("--bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--ticker", action="append", help="Static universe ticker; repeatable.")
    parser.add_argument("--output-csv", type=Path)
    args = parser.parse_args()

    config = WalkForwardConfig(
        step_size_days=args.step_days,
        max_positions=args.max_positions,
        cost_model=CostModel(bps_per_side=args.bps, slippage_bps=args.slippage_bps),
        static_universe=None if args.ticker is None else {t.upper() for t in args.ticker},
    )
    loader = PITLoader()
    profile = profile_strategy(
        name=args.signal,
        config=config,
        loader=loader,
        signal_fn=SIGNALS[args.signal],
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
    )
    frame = profile_to_frame(profile)

    display_columns = [
        col
        for col in [
            "name",
            "start",
            "end",
            "cagr",
            "sharpe",
            "max_drawdown",
            "weekly_return",
            "weekly_target",
            "weekly_target_gap",
            "turnover",
        ]
        if col in frame.columns
    ]
    print(frame[display_columns].to_string(index=False))

    gap = float(frame["weekly_target_gap"].iloc[0])
    direction = "above" if gap >= 0 else "below"
    print(f"weekly_target_gap = {gap:.4f} ({direction} target)")

    if args.output_csv is not None:
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(args.output_csv, index=False)


if __name__ == "__main__":
    main()
