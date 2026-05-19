from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

from subscription_email.article_session import (  # noqa: E402
    BrowserSessionUnavailableError,
    article_login_preflight_providers,
    ensure_interactive_article_login,
    provider_for_url,
)
from subscription_email.config import (  # noqa: E402
    SubscriptionEmailConfig,
    load_subscription_email_config,
)
from subscription_email.ingest import ingest_subscription_email_config  # noqa: E402
from subscription_email.linked_content import allowed_article_fetch_links  # noqa: E402
from subscription_email.mailbox import preview_mailbox_emails  # noqa: E402
from subscription_email.types import EmailRecord  # noqa: E402


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    args = _parse_args()
    config = _config_with_overrides(args)
    if args.dry_run:
        preview = preview_mailbox_emails(config)
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "guardrails": {
                        "mailbox_unseen_only": config.mailbox_unseen_only,
                        "mailbox_max_messages": config.mailbox_max_messages,
                        "article_max_total_per_run": config.article_max_total_per_run,
                    },
                    "mailbox_preview": {
                        "mode": preview.mode,
                        "matched": preview.matched,
                        "sampled": preview.sampled,
                        "skipped": preview.skipped,
                        "failed": preview.failed,
                        "limited": preview.limited,
                        "reason": preview.reason,
                        "messages": preview.messages,
                    },
                },
                sort_keys=True,
            )
        )
        return 0
    try:
        result = ingest_subscription_email_config(
            config=config,
            config_path=args.config,
            repo_root=ROOT,
            news_path=args.news_output,
            news_manifest_path=args.news_manifest,
            activity_path=args.activity_output,
            activity_manifest_path=args.activity_manifest,
            event_path=args.event_output,
            event_manifest_path=args.event_manifest,
            summary_root=args.summary_root,
            source_paths=tuple(args.source_path) or None,
            article_login_preflight=lambda active_config, records: _run_article_login_preflight(
                active_config,
                args,
                records,
            ),
            article_login_handler=lambda active_config, url, record: _run_article_login_challenge(
                active_config,
                args,
                url,
                record,
            ),
        )
    except (BrowserSessionUnavailableError, EOFError) as exc:
        print(
            json.dumps(
                {
                    "status": "login_acknowledgement_required",
                    "reason": str(exc)
                    or "user login acknowledgement is required before article links open",
                    "next_step": (
                        "Open Chrome with remote debugging, log in to the provider, "
                        "then rerun this email/article agent command."
                    ),
                },
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "processed_emails": result.processed_emails,
                "news_rows": result.news_rows,
                "activity_rows": result.activity_rows,
                "event_rows": result.event_rows,
                "linked_content_attempted": result.linked_content_attempted,
                "linked_content_succeeded": result.linked_content_succeeded,
                "linked_content_failed": result.linked_content_failed,
                "linked_content_skipped": result.linked_content_skipped,
                "linked_content_login_required": result.linked_content_login_required,
                "linked_content_unavailable": result.linked_content_unavailable,
                "linked_content_status_counts": result.linked_content_status_counts,
                "mailbox_sync": result.mailbox_sync,
                "manual_review_count": result.manual_review_count,
                "ignored_count": result.ignored_count,
                "written_paths": list(result.written_paths),
            },
            sort_keys=True,
        )
    )
    return 0


def _config_with_overrides(args: argparse.Namespace) -> SubscriptionEmailConfig:
    config = load_subscription_email_config(args.config, repo_root=ROOT)
    if args.max_emails is not None:
        if args.max_emails < 1:
            raise ValueError("--max-emails must be >= 1")
        config = replace(config, mailbox_max_messages=args.max_emails)
    if args.max_article_links is not None:
        if args.max_article_links < 0:
            raise ValueError("--max-article-links must be >= 0")
        config = replace(config, article_max_total_per_run=args.max_article_links)
    if args.enable_article_llm_analysis is not None:
        config = replace(config, article_llm_analysis_enabled=args.enable_article_llm_analysis)
    if args.require_article_login is not None:
        config = replace(config, article_login_preflight_required=args.require_article_login)
    if args.include_seen:
        config = replace(config, mailbox_unseen_only=False)
    if args.unseen_only:
        config = replace(config, mailbox_unseen_only=True)
    if args.source_path:
        config = replace(config, mode="local_eml", input_path=args.source_path[0].parent)
    return config


def _run_article_login_preflight(
    config: SubscriptionEmailConfig,
    args: argparse.Namespace,
    records: list[EmailRecord],
) -> SubscriptionEmailConfig:
    if not config.article_login_preflight_required:
        return config
    verification_urls = _email_article_verification_urls(config, args, records)
    if not verification_urls:
        print(
            json.dumps(
                {
                    "article_login_preflight": [],
                    "reason": (
                        "no selected email article link required login preflight; "
                        "article links remain gated until a matching email link is selected"
                    ),
                },
                sort_keys=True,
            )
        )
        return config
    results = ensure_interactive_article_login(
        config,
        providers=tuple(verification_urls),
        verification_urls=verification_urls,
    )
    if results:
        print(
            json.dumps(
                {
                    "article_login_preflight": [result.as_dict() for result in results],
                    "reason": "article login confirmed; activating subscription email agent",
                },
                sort_keys=True,
            )
        )
        return replace(
            config,
            article_login_preflight_confirmed=all(result.confirmed for result in results),
        )
    return config


def _email_article_verification_urls(
    config: SubscriptionEmailConfig,
    args: argparse.Namespace,
    records: list[EmailRecord],
) -> dict[str, str]:
    providers = set(article_login_preflight_providers(
        config,
        tuple(args.article_login_service) or None,
    ))
    urls: dict[str, str] = {}
    for record in records:
        for url in allowed_article_fetch_links(record, config):
            provider = _provider_for_preflight_url(url)
            if provider is None or provider not in providers or provider in urls:
                continue
            urls[provider] = url
    return urls


def _provider_for_preflight_url(url: str) -> str | None:
    return provider_for_url(url)


def _run_article_login_challenge(
    config: SubscriptionEmailConfig,
    args: argparse.Namespace,
    url: str,
    record: EmailRecord,
) -> SubscriptionEmailConfig:
    del args
    provider = provider_for_url(url)
    if provider is None:
        return config
    print(
        json.dumps(
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
            },
            sort_keys=True,
        )
    )
    results = ensure_interactive_article_login(
        config,
        providers=(provider,),
        verification_urls={provider: url},
    )
    if not results or not all(result.confirmed for result in results):
        return config
    print(
        json.dumps(
            {
                "article_login_acknowledged": [result.as_dict() for result in results],
                "reason": "login verified; retrying the article link in the same ingest run",
            },
            sort_keys=True,
        )
    )
    return replace(config, article_login_preflight_confirmed=True)


def _safe_url_label(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, "", ""))


def _hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import user-authorized subscription emails.")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "research" / "config" / "subscription-email.example.json",
    )
    parser.add_argument(
        "--news-output",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "news_rss.parquet",
    )
    parser.add_argument(
        "--news-manifest",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "news_rss.json",
    )
    parser.add_argument(
        "--activity-output",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "unusual_activity_alerts.parquet",
    )
    parser.add_argument(
        "--activity-manifest",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "unusual_activity_alerts.json",
    )
    parser.add_argument(
        "--event-output",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "subscription_emails.parquet",
    )
    parser.add_argument(
        "--event-manifest",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "subscription_emails.json",
    )
    parser.add_argument(
        "--summary-root",
        type=Path,
        default=ROOT / "research" / "results" / "latest-subscription-emails",
    )
    parser.add_argument(
        "--source-path",
        type=Path,
        action="append",
        default=[],
        help=(
            "Analyze one or more already-saved .eml files without polling the mailbox. "
            "Useful for deterministic article-agent smoke tests."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview matched mailbox headers only; save no emails and open no article links.",
    )
    parser.add_argument(
        "--max-emails",
        type=int,
        default=None,
        help="Override mailbox_max_messages for this run.",
    )
    parser.add_argument(
        "--max-article-links",
        type=int,
        default=None,
        help="Override article_max_total_per_run for this run.",
    )
    parser.add_argument(
        "--enable-article-llm-analysis",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Use OpenAI to produce ticker-focused analysis for every opened article link.",
    )
    parser.add_argument(
        "--require-article-login",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Open provider login pages and wait for user confirmation before "
            "the email/article agent runs."
        ),
    )
    parser.add_argument(
        "--article-login-service",
        action="append",
        default=[],
        help="Provider to open for login preflight; repeatable. Defaults from config.",
    )
    seen_group = parser.add_mutually_exclusive_group()
    seen_group.add_argument(
        "--include-seen",
        action="store_true",
        help="Allow already-read emails returned by the mailbox search.",
    )
    seen_group.add_argument(
        "--unseen-only",
        action="store_true",
        help="Force UNSEEN into the mailbox search for this run.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
