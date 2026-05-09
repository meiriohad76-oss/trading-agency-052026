from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

from subscription_email.monitor import (  # noqa: E402
    monitor_result_to_json,
    monitor_subscription_emails_once,
    watch_subscription_emails,
)


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = _parse_args()
    if args.once:
        result = monitor_subscription_emails_once(
            config_path=args.config,
            repo_root=ROOT,
            state_path=args.state_path,
            summary_root=args.summary_root,
        )
        print(monitor_result_to_json(result, ROOT), end="")
        return 0
    for result in watch_subscription_emails(
        config_path=args.config,
        repo_root=ROOT,
        state_path=args.state_path,
        summary_root=args.summary_root,
        poll_seconds=args.poll_seconds,
    ):
        print(monitor_result_to_json(result, ROOT), end="", flush=True)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor subscription emails and auto-analyze.")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "research" / "config" / "subscription-email.local.json",
    )
    parser.add_argument("--once", action="store_true", help="Run one monitor cycle and exit.")
    parser.add_argument("--poll-seconds", type=int, help="Polling interval for watch mode.")
    parser.add_argument(
        "--state-path",
        type=Path,
        help="Local monitor state JSON. Defaults under the configured email folder.",
    )
    parser.add_argument(
        "--summary-root",
        type=Path,
        default=ROOT / "research" / "results" / "latest-subscription-emails",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
