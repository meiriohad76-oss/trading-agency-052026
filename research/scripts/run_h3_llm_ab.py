from __future__ import annotations

import argparse
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from backtests.portfolio import CostModel  # noqa: E402
from backtests.walk_forward import WalkForwardConfig  # noqa: E402
from evaluation.h3_llm_comparison import llm_ab_summary_to_markdown, summarize_llm_ab  # noqa: E402
from evaluation.llm_ab import ReviewDecision, run_llm_ab  # noqa: E402
from evaluation.signal_registry import SIGNALS  # noqa: E402
from pit.loader import PITLoader  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run H3 LLM A/B comparison.")
    parser.add_argument("--signal", choices=sorted(SIGNALS), required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--step-days", type=int, default=5)
    parser.add_argument("--max-positions", type=int, default=10)
    parser.add_argument("--bps", type=float, default=5.0)
    parser.add_argument(
        "--reviewer",
        choices=["mock_approve_all", "mock_random"],
        default="mock_approve_all",
    )
    parser.add_argument("--mock-approval-rate", type=float, default=0.7)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--ticker", action="append", help="Static universe ticker; repeatable.")
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()

    if args.reviewer == "mock_approve_all":
        reviewer = lambda as_of, ticker, score, evidence: ReviewDecision(approved=True)
    else:
        rng = random.Random(42)
        rate = args.mock_approval_rate

        def reviewer(as_of, ticker, score, evidence):
            return ReviewDecision(approved=rng.random() < rate)

    config = WalkForwardConfig(
        step_size_days=args.step_days,
        max_positions=args.max_positions,
        cost_model=CostModel(bps_per_side=args.bps),
        static_universe=None if args.ticker is None else {t.upper() for t in args.ticker},
    )
    loader = PITLoader()
    ab_results = run_llm_ab(
        name=args.signal,
        config=config,
        loader=loader,
        signal_fn=SIGNALS[args.signal],
        reviewer=reviewer,
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        repeats=args.repeats,
    )
    summary = summarize_llm_ab(ab_results)
    markdown = llm_ab_summary_to_markdown(summary)
    if args.output_csv is not None:
        args.output_csv.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(args.output_csv, index=False)
    if args.output_md is not None:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
