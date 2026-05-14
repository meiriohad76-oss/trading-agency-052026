from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from evaluation.h1_ic import H1ICConfig, evaluate_signal_ic  # noqa: E402
from evaluation.signal_registry import SIGNALS  # noqa: E402
from evaluation.verdicts import (  # noqa: E402
    summarize_signal_verdicts,
    synthesize_horizon_verdicts,
    verdicts_to_markdown,
)
from pit.loader import PITLoader  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run H1 signal IC evaluation.")
    parser.add_argument("--signal", choices=sorted(SIGNALS), action="append", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--horizon", type=int, action="append")
    parser.add_argument("--step-days", type=int, default=1)
    parser.add_argument("--ticker", action="append", help="Static universe ticker; repeatable.")
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()

    config = H1ICConfig(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        horizons=tuple(args.horizon or (5, 20)),
        step_size_days=args.step_days,
        static_universe=None if args.ticker is None else {ticker.upper() for ticker in args.ticker},
    )
    loader = PITLoader()
    results = [
        evaluate_signal_ic(
            signal_name=name,
            signal_fn=SIGNALS[name],
            loader=loader,
            config=config,
        ).results
        for name in args.signal
    ]
    horizon_verdicts = synthesize_horizon_verdicts(pd.concat(results))
    summary = summarize_signal_verdicts(horizon_verdicts)
    if args.output_csv is not None:
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        horizon_verdicts.to_csv(args.output_csv, index=False)
    markdown = verdicts_to_markdown(summary)
    if args.output_md is not None:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
