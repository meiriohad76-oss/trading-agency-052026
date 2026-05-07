from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from data_refresh.batch import DATASETS, RefreshBatchConfig, run_refresh_batch  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    if args.sec_user_agent:
        os.environ["SEC_USER_AGENT"] = args.sec_user_agent
    result = run_refresh_batch(
        RefreshBatchConfig(
            repo_root=ROOT,
            output_root=args.output_root,
            start=args.start,
            end=args.end,
            datasets=tuple(args.dataset or DATASETS),
            tickers=tuple(args.ticker or ()),
            rss_feeds=tuple(args.rss_feed or ()),
            filer_ciks=tuple(args.filer_cik or ()),
            cusip_map=args.cusip_map,
            sec_user_agent=os.environ.get("SEC_USER_AGENT"),
            python_executable=sys.executable,
            workers=args.workers,
            include_etfs=args.include_etfs,
            refresh=args.refresh,
            dry_run=args.dry_run,
        )
    )
    state = "failed" if result.failed else "blocked" if result.blocked else "ready"
    print(f"Data refresh batch {state}; wrote {args.output_root}")
    if result.failed:
        return 1
    if result.blocked and not args.dry_run:
        return 2
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local research data refresh batch.")
    parser.add_argument("--start", type=_date, default=date(2019, 1, 1))
    parser.add_argument("--end", type=_date, default=date.today())
    parser.add_argument("--dataset", choices=DATASETS, action="append")
    parser.add_argument("--ticker", action="append", help="Ticker to refresh; repeatable.")
    parser.add_argument(
        "--rss-feed",
        action="append",
        help="Feed as SOURCE,URL or SOURCE,TICKER,URL.",
    )
    parser.add_argument("--filer-cik", action="append", help="13F filer CIK; repeatable.")
    parser.add_argument("--cusip-map", type=Path, help="JSON map of CUSIP to ticker for 13F rows.")
    parser.add_argument("--sec-user-agent", help="SEC-compliant User-Agent override.")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--include-etfs", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "research" / "results" / "t67",
    )
    return parser.parse_args()


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
