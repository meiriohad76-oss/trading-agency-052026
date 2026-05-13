from __future__ import annotations

import argparse
import json
import msvcrt
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

LOCK_FILE = ROOT / "research" / "data" / ".email-watch.lock"
_lock_fd = None  # module-level so file handle stays open while process runs

from subscription_email.article_session import ensure_interactive_article_login  # noqa: E402
from subscription_email.config import load_subscription_email_config  # noqa: E402
from subscription_email.monitor import (  # noqa: E402
    monitor_result_to_json,
    monitor_subscription_emails_once,
    watch_subscription_emails,
)


def _acquire_lock() -> None:
    """Exit if another email ingest process is already running (Windows file lock)."""
    global _lock_fd
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    _lock_fd = open(LOCK_FILE, "w")  # noqa: SIM115
    try:
        msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        _lock_fd.close()
        print(
            f"ERROR: Another email ingest process is already running "
            f"(lock: {LOCK_FILE}). Exiting.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def main() -> int:
    _acquire_lock()
    load_dotenv(ROOT / ".env", override=True)
    args = _parse_args()
    if not args.once:
        print(
            json.dumps({
                "event": "email_watch_started",
                "mode": "watch",
                "started_at": datetime.now(UTC).isoformat(),
            }),
            flush=True,
        )
    _run_article_login_preflight(args)
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


def _run_article_login_preflight(args: argparse.Namespace) -> None:
    config = load_subscription_email_config(args.config, repo_root=ROOT)
    require_login = (
        config.article_login_preflight_required
        if args.require_article_login is None
        else args.require_article_login
    )
    if not require_login:
        return
    results = ensure_interactive_article_login(
        config,
        providers=tuple(args.article_login_service) or None,
    )
    if results:
        print(
            monitor_result_to_json_like(
                {
                    "article_login_preflight": [result.as_dict() for result in results],
                    "reason": "article login confirmed; activating subscription email monitor",
                }
            ),
            end="",
        )


def monitor_result_to_json_like(payload: dict[str, object]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


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
        "--require-article-login",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Run the interactive article-login preflight before monitoring.",
    )
    parser.add_argument(
        "--article-login-service",
        action="append",
        default=[],
        help="Provider to open for login preflight; repeatable. Defaults from config.",
    )
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
