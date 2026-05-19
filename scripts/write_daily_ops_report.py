from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

from providers.massive_limits import current_usage  # noqa: E402

from agency.broker import AlpacaBrokerError, broker_snapshot  # noqa: E402
from agency.runtime.daily_ops_report import (  # noqa: E402
    build_daily_ops_report,
    write_daily_ops_report,
)
from agency.runtime.provider_readiness import load_provider_readiness  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = _parse_args()
    report = build_daily_ops_report(
        report_date=args.report_date,
        operational_readiness=_load_json(args.operational_readiness),
        provider_readiness=_load_json(args.provider_readiness) or load_provider_readiness(),
        pipeline_summary=_pipeline_summary(args.pipeline_report),
        live_cycle_summary=_load_json(args.live_cycle_summary),
        paper_broker_summary=asyncio.run(_paper_broker_summary(args.paper_broker_summary)),
        massive_usage=current_usage(),
    )
    write_daily_ops_report(report, args.output_root)
    print(
        json.dumps(
            {
                "verdict": report["verdict"],
                "output_root": args.output_root.as_posix(),
                "blocker_count": _list_len(report["blockers"]),
                "warning_count": _list_len(report["warnings"]),
            },
            sort_keys=True,
        )
    )
    return 0


def _pipeline_summary(path: Path) -> dict[str, object]:
    payload = _load_json(path)
    summary = payload.get("summary") if isinstance(payload, dict) else None
    return dict(summary) if isinstance(summary, dict) else {}


def _load_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


async def _paper_broker_summary(path: Path) -> dict[str, object]:
    if _env_bool("AGENCY_ALPACA_BROKER_ENABLED"):
        try:
            snapshot = await broker_snapshot()
        except AlpacaBrokerError:
            pass
        else:
            return _normalized_broker_summary(snapshot)
    return _load_json(path)


def _normalized_broker_summary(snapshot: dict[str, object]) -> dict[str, object]:
    account = snapshot.get("account", {})
    account_status = account.get("status", "unknown") if isinstance(account, dict) else "unknown"
    return {
        "verdict": "paper_broker_live_snapshot",
        "broker": {
            "mode": snapshot.get("mode", "paper"),
            "account_status": account_status,
            "positions": _list_len(snapshot.get("positions")),
            "open_orders": _list_len(snapshot.get("orders")),
        },
    }


def _list_len(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write the local agency daily ops report.")
    parser.add_argument("--report-date", type=date.fromisoformat)
    parser.add_argument(
        "--operational-readiness",
        type=Path,
        default=ROOT / "research" / "results" / "latest-operational-readiness.json",
    )
    parser.add_argument(
        "--provider-readiness",
        type=Path,
        default=ROOT / "research" / "results" / "latest-provider-readiness.json",
    )
    parser.add_argument(
        "--pipeline-report",
        type=Path,
        default=ROOT
        / "research"
        / "results"
        / "latest-first-version-pipeline"
        / "first-version-pipeline.json",
    )
    parser.add_argument(
        "--live-cycle-summary",
        type=Path,
        default=ROOT
        / "research"
        / "results"
        / "latest-live-runtime-cycle"
        / "live-runtime-cycle-summary.json",
    )
    parser.add_argument(
        "--paper-broker-summary",
        type=Path,
        default=ROOT
        / "research"
        / "results"
        / "alpaca-paper-validation"
        / "paper-broker-validation.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "research" / "results" / "latest-daily-ops-report",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
