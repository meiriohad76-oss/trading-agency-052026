from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))

from data_refresh.active_universe_plan import (  # noqa: E402
    ActiveUniversePlanRequest,
    build_active_universe_refresh_plan,
    write_active_universe_refresh_plan,
)
from providers.massive_limits import current_usage  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    usage = current_usage()
    remaining = _optional_int_value(usage.get("requests_remaining"))
    plan = build_active_universe_refresh_plan(
        ActiveUniversePlanRequest(
            repo_root=ROOT,
            config_path=args.config,
            output_root=args.output_root,
            as_of=args.as_of,
            datasets=tuple(args.dataset) if args.dataset else None,
            batch_size=args.batch_size,
            massive_requests_remaining=remaining,
        )
    )
    plan["massive_usage"] = usage
    write_active_universe_refresh_plan(plan, args.output_root)
    print(
        json.dumps(
            {
                "active_universe_count": plan["active_universe_count"],
                "batch_count": len(plan["batches"]),
                "output_root": args.output_root.as_posix(),
                "requests_remaining_after_plan": plan[
                    "massive_requests_remaining_after_plan"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan safe refresh batches for the active S&P 100 + QQQ universe."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "research" / "config" / "live-refresh.local.json",
    )
    parser.add_argument("--as-of", type=_date)
    parser.add_argument(
        "--dataset",
        action="append",
        choices=("prices_daily", "sec_company_facts", "sec_form4", "stock_trades"),
    )
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "research" / "results" / "active-universe-refresh-plan",
    )
    return parser.parse_args()


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _int_value(value: object) -> int:
    if isinstance(value, int):
        return value
    return int(str(value))


def _optional_int_value(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "none", "unlimited"}:
        return None
    return _int_value(value)


if __name__ == "__main__":
    raise SystemExit(main())
