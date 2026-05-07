from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from options.puller import pull_option_chains  # noqa: E402
from prices.puller import universe_tickers  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull forward yfinance option-chain snapshots.")
    parser.add_argument(
        "--universe",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "universe_membership.parquet",
    )
    parser.add_argument("--ticker", action="append", help="Ticker to pull; repeatable.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "options_chains",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "options_chains.json",
    )
    args = parser.parse_args()
    tickers = args.ticker or universe_tickers(args.universe)
    summary = asyncio.run(
        pull_option_chains(
            tickers=tickers,
            data_root=args.output_root,
            manifest_path=args.manifest,
        )
    )
    print(summary)


if __name__ == "__main__":
    main()
