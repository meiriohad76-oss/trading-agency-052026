from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

from agency.runtime.email_evidence_refresh import (  # noqa: E402
    sync_email_evidence_and_run_mini_cycles,
)


def main() -> int:
    args = _parse_args()
    result = sync_email_evidence_and_run_mini_cycles(
        root=args.agent_root,
        parquet_path=args.parquet_path,
        manifest_path=args.manifest_path,
        summary_root=args.summary_root,
        status_path=args.status_path,
        config_path=args.config,
        output_root=args.output_root,
        run_mini_cycles=args.run_mini_cycles,
        mini_cycle_timeout_seconds=args.mini_cycle_timeout_seconds,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if str(result.get("status")) != "mini_analysis_failed" else 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sync Portfolio News Agent evidence, then run ticker-scoped mini-cycles "
            "for newly affected stock summaries."
        ),
    )
    parser.add_argument("--agent-root", type=Path, default=None)
    parser.add_argument(
        "--parquet-path",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "subscription_emails.parquet",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "subscription_emails.json",
    )
    parser.add_argument(
        "--summary-root",
        type=Path,
        default=ROOT / "research" / "results" / "latest-subscription-emails",
    )
    parser.add_argument(
        "--status-path",
        type=Path,
        default=(
            ROOT
            / "research"
            / "results"
            / "latest-subscription-emails"
            / "subscription-email-mini-cycle-status.json"
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "research" / "config" / "live-refresh.local.json",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=(
            ROOT
            / "research"
            / "results"
            / "latest-mini-runtime-cycle"
            / "subscription_email"
        ),
    )
    parser.add_argument("--run-mini-cycles", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--mini-cycle-timeout-seconds", type=int, default=300)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
