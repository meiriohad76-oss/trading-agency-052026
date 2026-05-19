from __future__ import annotations

import argparse
import hashlib
import json
import msvcrt
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

LOCK_FILE = ROOT / "research" / "data" / ".email-watch.lock"
_lock_fd = None  # module-level so file handle stays open while process runs

from subscription_email.article_session import (  # noqa: E402
    BrowserSessionUnavailableError,
    article_login_preflight_providers,
    ensure_interactive_article_login,
    provider_for_url,
)
from subscription_email.config import load_subscription_email_config  # noqa: E402
from subscription_email.linked_content import allowed_article_fetch_links  # noqa: E402
from subscription_email.monitor import (  # noqa: E402
    monitor_result_to_json,
    monitor_subscription_emails_once,
    watch_subscription_emails,
)
from subscription_email.types import EmailRecord  # noqa: E402


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
    config = load_subscription_email_config(args.config, repo_root=ROOT)
    if args.require_article_login is not None:
        config = replace(
            config,
            article_login_preflight_required=args.require_article_login,
        )
    if not args.once:
        print(
            json.dumps({
                "event": "email_watch_started",
                "mode": "watch",
                "started_at": datetime.now(UTC).isoformat(),
            }),
            flush=True,
        )
    login_confirmed = config.article_login_preflight_confirmed

    def article_login_preflight(active_config, records):
        nonlocal login_confirmed
        if login_confirmed:
            return replace(active_config, article_login_preflight_confirmed=True)
        checked_config = _run_article_login_preflight(active_config, args, records)
        login_confirmed = checked_config.article_login_preflight_confirmed
        return checked_config

    def article_login_handler(active_config, url, record):
        nonlocal login_confirmed
        checked_config = _run_article_login_challenge(active_config, url, record)
        login_confirmed = checked_config.article_login_preflight_confirmed
        return checked_config

    try:
        if args.once:
            result = monitor_subscription_emails_once(
                config_path=args.config,
                repo_root=ROOT,
                state_path=args.state_path,
                summary_root=args.summary_root,
                config=config,
                article_login_preflight=article_login_preflight,
                article_login_handler=article_login_handler,
            )
            print(monitor_result_to_json(result, ROOT), end="")
            return 0
        for result in watch_subscription_emails(
            config_path=args.config,
            repo_root=ROOT,
            state_path=args.state_path,
            summary_root=args.summary_root,
            poll_seconds=args.poll_seconds,
            config=config,
            article_login_preflight=article_login_preflight,
            article_login_handler=article_login_handler,
        ):
            print(monitor_result_to_json(result, ROOT), end="", flush=True)
    except (BrowserSessionUnavailableError, EOFError) as exc:
        print(
            monitor_result_to_json_like(
                {
                    "status": "login_acknowledgement_required",
                    "reason": str(exc)
                    or "user login acknowledgement is required before article links open",
                    "next_step": (
                        "Open Chrome with remote debugging, log in to the provider, "
                        "then rerun the email monitor."
                    ),
                }
            ),
            end="",
        )
        return 2
    return 0


def _run_article_login_preflight(
    config,
    args: argparse.Namespace,
    records: list[EmailRecord],
):
    if not config.article_login_preflight_required:
        return config
    verification_urls = _email_article_verification_urls(config, args, records)
    if not verification_urls:
        print(
            monitor_result_to_json_like(
                {
                    "article_login_preflight": [],
                    "reason": (
                        "no selected email article link required login preflight; "
                        "article links remain gated until a matching email link is selected"
                    ),
                }
            ),
            end="",
        )
        return config
    results = ensure_interactive_article_login(
        config,
        providers=tuple(verification_urls),
        verification_urls=verification_urls,
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
        return replace(
            config,
            article_login_preflight_confirmed=all(result.confirmed for result in results),
        )
    return config


def _email_article_verification_urls(
    config,
    args: argparse.Namespace,
    records: list[EmailRecord],
) -> dict[str, str]:
    providers = set(
        article_login_preflight_providers(
            config,
            tuple(args.article_login_service) or None,
        )
    )
    urls: dict[str, str] = {}
    for record in records:
        for url in allowed_article_fetch_links(record, config):
            provider = provider_for_url(url)
            if provider is None or provider not in providers or provider in urls:
                continue
            urls[provider] = url
    return urls


def _run_article_login_challenge(config, url: str, record: EmailRecord):
    provider = provider_for_url(url)
    if provider is None:
        return config
    print(
        monitor_result_to_json_like(
            {
                "article_login_required": {
                    "provider": provider,
                    "message_id_hash": _hash(record.message_id),
                    "subject": record.subject,
                    "verification_url": _safe_url_label(url),
                },
                "reason": (
                    "article link opened to a login or human-verification page; "
                    "opening provider login and waiting for user acknowledgment"
                ),
            }
        ),
        end="",
    )
    results = ensure_interactive_article_login(
        config,
        providers=(provider,),
        verification_urls={provider: url},
    )
    if not results or not all(result.confirmed for result in results):
        return config
    print(
        monitor_result_to_json_like(
            {
                "article_login_acknowledged": [result.as_dict() for result in results],
                "reason": "login verified; retrying the article link in the same monitor run",
            }
        ),
        end="",
    )
    return replace(config, article_login_preflight_confirmed=True)


def _safe_url_label(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, "", ""))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


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
