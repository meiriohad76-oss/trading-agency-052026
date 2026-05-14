from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from evaluation.combination import SignalWeight, combined_signal_fn, weights_from_ic  # noqa: E402
from evaluation.h1_ic import H1ICConfig, evaluate_signal_ic  # noqa: E402
from evaluation.signal_registry import SIGNALS  # noqa: E402
from evaluation.verdicts import (  # noqa: E402
    summarize_signal_verdicts,
    synthesize_horizon_verdicts,
    verdicts_to_markdown,
)
from pit.loader import PITLoader  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run H2 weighted-combination signal evaluation.")
    parser.add_argument("--h1-csv", type=Path, required=True, help="CSV from run_h1_ic.py.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--horizon", type=int, action="append")
    parser.add_argument("--step-days", type=int, default=1)
    parser.add_argument("--ticker", action="append", help="Static universe ticker; repeatable.")
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    parser.add_argument("--min-weight", type=float, default=0.0)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()

    ic_results = pd.read_csv(args.h1_csv)
    weights = weights_from_ic(ic_results, weight_column="information_ratio")

    surviving = {name: w for name, w in weights.items() if w >= args.min_weight}
    if not surviving:
        print("no surviving signals; combination not evaluable")
        raise SystemExit(0)

    components = [
        SignalWeight(name=name, signal_fn=SIGNALS[name], weight=weight)
        for name, weight in sorted(surviving.items())
        if name in SIGNALS
    ]
    if not components:
        print("no surviving signals; combination not evaluable")
        raise SystemExit(0)

    signal_fn = combined_signal_fn(components)

    config = H1ICConfig(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        horizons=tuple(args.horizon or (5, 20)),
        step_size_days=args.step_days,
        static_universe=None if args.ticker is None else {ticker.upper() for ticker in args.ticker},
        bootstrap_iterations=args.bootstrap_iterations,
    )
    loader = PITLoader()
    report = evaluate_signal_ic(
        signal_name="combined",
        signal_fn=signal_fn,
        loader=loader,
        config=config,
    )
    horizon_verdicts = synthesize_horizon_verdicts(report.results)
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
