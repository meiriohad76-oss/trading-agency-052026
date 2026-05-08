from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from data_refresh.live_config import load_refresh_config  # noqa: E402
from live_runtime.config import DEFAULT_RUNTIME_SIGNALS, LANE_CONFIGS  # noqa: E402
from live_runtime.cycle import build_live_pit_runtime_cycle  # noqa: E402
from live_runtime.summary import (  # noqa: E402
    build_live_runtime_summary,
    write_live_runtime_summary,
)

from agency.db import get_session  # noqa: E402
from agency.services import persist_runtime_cycle  # noqa: E402


async def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    config = load_refresh_config(args.config, repo_root=ROOT) if args.config else None
    tickers = _tickers(args, config)
    as_of = args.as_of or (config.end if config and config.end else date.today())
    generated_at = datetime.now(UTC)
    cycle = build_live_pit_runtime_cycle(
        cycle_id=args.cycle_id or _cycle_id(as_of, generated_at),
        as_of=as_of,
        tickers=set(tickers[: args.max_tickers]),
        manifest_root=args.manifest_root,
        parquet_root=args.parquet_root,
        lanes=tuple(args.signal or DEFAULT_RUNTIME_SIGNALS),
        generated_at=generated_at,
    )
    persisted = False
    if args.persist:
        async with get_session() as session:
            await persist_runtime_cycle(session, cycle, audit_trigger=args.audit_trigger)
            await session.commit()
        persisted = True
    summary = build_live_runtime_summary(cycle, persisted=persisted)
    write_live_runtime_summary(summary, args.output_root)
    print(f"Live runtime cycle {summary['verdict']}; wrote {args.output_root}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a PIT-backed local paper runtime cycle.")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "research/config/live-refresh.local.json",
    )
    parser.add_argument("--ticker", action="append", default=[])
    parser.add_argument("--signal", choices=sorted(LANE_CONFIGS), action="append")
    parser.add_argument("--as-of", type=_date)
    parser.add_argument("--cycle-id")
    parser.add_argument(
        "--audit-trigger",
        choices=("MANUAL", "SCHEDULED", "API", "SYSTEM", "TEST"),
        default="MANUAL",
    )
    parser.add_argument("--max-tickers", type=int, default=10)
    parser.add_argument("--persist", action=argparse.BooleanOptionalAction, default=True)
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
        default=ROOT / "research/results/t83-live-runtime-cycle",
    )
    return parser.parse_args()


def _tickers(args: argparse.Namespace, config: object | None) -> list[str]:
    values = list(args.ticker)
    if not values and config is not None:
        values = list(config.tickers)
    if not values:
        raise ValueError("provide --ticker or a config file with tickers")
    return [ticker.upper() for ticker in values]


def _cycle_id(as_of: date, generated_at: datetime) -> str:
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    return f"live-pit-{as_of.isoformat()}-{stamp}"


def _date(value: str) -> date:
    return date.fromisoformat(value)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
