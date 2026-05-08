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
from data_refresh.live_config import RefreshConfigOverrides, load_refresh_config  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    overrides = _load_overrides(args.config)
    config = _batch_config(args, overrides)
    result = run_refresh_batch(config)
    state = _result_state(failed=result.failed, blocked=result.blocked)
    print(f"Data refresh batch {state}; wrote {config.output_root}")
    if result.failed:
        return 1
    if result.blocked and not args.dry_run:
        return 2
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local research data refresh batch.")
    parser.add_argument("--config", type=Path, help="Optional JSON config file.")
    parser.add_argument("--start", type=_date)
    parser.add_argument("--end", type=_date)
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
    parser.add_argument("--workers", type=int)
    parser.add_argument("--include-etfs", action=argparse.BooleanOptionalAction)
    parser.add_argument("--refresh", action=argparse.BooleanOptionalAction)
    parser.add_argument("--dry-run", action=argparse.BooleanOptionalAction)
    parser.add_argument(
        "--output-root",
        type=Path,
    )
    return parser.parse_args()


def _load_overrides(path: Path | None) -> RefreshConfigOverrides:
    if path is None:
        return RefreshConfigOverrides()
    return load_refresh_config(path, repo_root=ROOT)


def _batch_config(
    args: argparse.Namespace,
    overrides: RefreshConfigOverrides,
) -> RefreshBatchConfig:
    sec_user_agent = (
        args.sec_user_agent or overrides.sec_user_agent or os.environ.get("SEC_USER_AGENT")
    )
    if sec_user_agent:
        os.environ["SEC_USER_AGENT"] = sec_user_agent
    return RefreshBatchConfig(
        repo_root=ROOT,
        output_root=args.output_root or ROOT / "research" / "results" / "t67",
        start=args.start or overrides.start or date(2019, 1, 1),
        end=args.end or overrides.end or date.today(),
        datasets=tuple(args.dataset or overrides.datasets or DATASETS),
        tickers=tuple(args.ticker or overrides.tickers),
        rss_feeds=tuple(args.rss_feed or overrides.rss_feeds),
        filer_ciks=tuple(args.filer_cik or overrides.filer_ciks),
        cusip_map=args.cusip_map or overrides.cusip_map,
        sec_user_agent=sec_user_agent,
        python_executable=sys.executable,
        workers=args.workers or overrides.workers or 1,
        include_etfs=_bool_value(args.include_etfs, overrides.include_etfs, default=True),
        refresh=_bool_value(args.refresh, overrides.refresh, default=False),
        dry_run=_bool_value(args.dry_run, overrides.dry_run, default=False),
    )


def _bool_value(value: bool | None, override: bool | None, *, default: bool) -> bool:
    if value is not None:
        return value
    if override is not None:
        return override
    return default


def _result_state(*, failed: bool, blocked: bool) -> str:
    if failed:
        return "failed"
    if blocked:
        return "blocked"
    return "ready"


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(main())
