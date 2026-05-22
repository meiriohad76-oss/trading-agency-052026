from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from activity_alerts.storage import (
    write_activity_alert_frame,
)
from activity_alerts.storage import (
    write_manifest as write_activity_manifest,
)
from news.storage import write_manifest as write_news_manifest
from news.storage import write_news_frame
from subscription_email.classifiers import classify_subscription_emails
from subscription_email.config import SubscriptionEmailConfig, load_subscription_email_config
from subscription_email.linked_content import (
    ARTICLE_UNAVAILABLE_STATUS,
    LOGIN_GATED_LINK_STATUS,
    LOGIN_PREFLIGHT_REQUIRED_STATUS,
    ArticleAnalyzer,
    ArticleFetcher,
    ArticleLoginHandler,
    LinkedContentStats,
    enrich_records_with_linked_content,
)
from subscription_email.mailbox import (
    ImapFactory,
    MailboxSyncResult,
    mark_mailbox_emails_seen,
    sync_mailbox_emails,
)
from subscription_email.parser import parse_email_file, read_local_emails
from subscription_email.storage import (
    write_event_frame,
    write_summary,
)
from subscription_email.storage import (
    write_manifest as write_event_manifest,
)
from subscription_email.types import EmailRecord, SubscriptionEmailIngestResult

from agency.provenance import SourceTier

ArticleLoginPreflight = Callable[
    [SubscriptionEmailConfig, list[EmailRecord]],
    SubscriptionEmailConfig,
]


def ingest_subscription_emails(
    *,
    config_path: Path,
    repo_root: Path,
    news_path: Path | None = None,
    news_manifest_path: Path | None = None,
    activity_path: Path | None = None,
    activity_manifest_path: Path | None = None,
    event_path: Path | None = None,
    event_manifest_path: Path | None = None,
    summary_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    article_fetcher: ArticleFetcher | None = None,
    article_analyzer: ArticleAnalyzer | None = None,
    article_login_preflight: ArticleLoginPreflight | None = None,
    article_login_handler: ArticleLoginHandler | None = None,
    source_paths: tuple[Path, ...] | None = None,
    imap_factory: ImapFactory | None = None,
    env: Mapping[str, str] | None = None,
) -> SubscriptionEmailIngestResult:
    config = load_subscription_email_config(config_path, repo_root=repo_root)
    return ingest_subscription_email_config(
        config=config,
        config_path=config_path,
        repo_root=repo_root,
        news_path=news_path,
        news_manifest_path=news_manifest_path,
        activity_path=activity_path,
        activity_manifest_path=activity_manifest_path,
        event_path=event_path,
        event_manifest_path=event_manifest_path,
        summary_root=summary_root,
        clock=clock,
        article_fetcher=article_fetcher,
        article_analyzer=article_analyzer,
        article_login_preflight=article_login_preflight,
        article_login_handler=article_login_handler,
        source_paths=source_paths,
        imap_factory=imap_factory,
        env=env,
    )


def ingest_subscription_email_config(
    *,
    config: SubscriptionEmailConfig,
    config_path: Path,
    repo_root: Path,
    news_path: Path | None = None,
    news_manifest_path: Path | None = None,
    activity_path: Path | None = None,
    activity_manifest_path: Path | None = None,
    event_path: Path | None = None,
    event_manifest_path: Path | None = None,
    summary_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    article_fetcher: ArticleFetcher | None = None,
    article_analyzer: ArticleAnalyzer | None = None,
    article_login_preflight: ArticleLoginPreflight | None = None,
    article_login_handler: ArticleLoginHandler | None = None,
    source_paths: tuple[Path, ...] | None = None,
    imap_factory: ImapFactory | None = None,
    env: Mapping[str, str] | None = None,
) -> SubscriptionEmailIngestResult:
    fetched_at = _utc_now(clock)
    mailbox_sync = (
        _source_path_mailbox_sync(config, source_paths)
        if source_paths
        else sync_mailbox_emails(config, env=env, imap_factory=imap_factory)
    )
    records_config = replace(config, mode="local_eml") if config.mode != "local_eml" else config
    record_paths = source_paths or _mailbox_source_paths(config, mailbox_sync)
    records = _records(records_config, source_paths=record_paths)
    eligible, filtered = _eligible_records(records, config=config, fetched_at=fetched_at)
    if article_login_preflight is not None:
        config = article_login_preflight(config, eligible)
    link_result = enrich_records_with_linked_content(
        eligible,
        config=config,
        fetcher=article_fetcher,
        analyzer=article_analyzer,
        article_login_handler=article_login_handler,
    )
    classified = classify_subscription_emails(
        link_result.records,
        config=config,
        fetched_at=fetched_at,
    )
    ignored = [*filtered, *classified.ignored]
    paths = _write_outputs(
        repo_root=repo_root,
        config_path=config_path,
        config=config,
        fetched_at=fetched_at,
        processed_emails=len(eligible),
        news_rows=classified.news_rows,
        activity_rows=classified.activity_rows,
        event_rows=classified.event_rows,
        link_stats=link_result.stats,
        mailbox_sync=mailbox_sync,
        manual_review=classified.manual_review,
        ignored=ignored,
        news_path=news_path,
        news_manifest_path=news_manifest_path,
        activity_path=activity_path,
        activity_manifest_path=activity_manifest_path,
        event_path=event_path,
        event_manifest_path=event_manifest_path,
        summary_root=summary_root,
    )
    if config.mailbox_mark_seen and mailbox_sync.selected_uids:
        mark_mailbox_emails_seen(
            config,
            mailbox_sync.selected_uids,
            env=env,
            imap_factory=imap_factory,
        )
    return SubscriptionEmailIngestResult(
        processed_emails=len(eligible),
        news_rows=len(classified.news_rows),
        activity_rows=len(classified.activity_rows),
        event_rows=len(classified.event_rows),
        linked_content_attempted=link_result.stats.attempted,
        linked_content_succeeded=link_result.stats.succeeded,
        linked_content_failed=link_result.stats.failed,
        linked_content_skipped=link_result.stats.skipped,
        linked_content_login_required=link_result.stats.login_required,
        linked_content_unavailable=link_result.stats.unavailable,
        linked_content_status_counts=dict(link_result.stats.status_counts),
        manual_review_count=len(classified.manual_review),
        ignored_count=len(ignored),
        service_counts=_service_counts(classified.event_rows),
        written_paths=tuple(_display_path(path, repo_root) for path in paths),
        mailbox_sync=_mailbox_sync_payload(mailbox_sync, repo_root),
    )


def _source_path_mailbox_sync(
    config: SubscriptionEmailConfig,
    source_paths: tuple[Path, ...] | None,
) -> MailboxSyncResult:
    selected_paths = tuple(source_paths or ())
    return MailboxSyncResult(
        mode="local_eml",
        attempted=len(selected_paths),
        saved=0,
        skipped=0,
        failed=0,
        output_path=config.input_path,
        reason="source paths supplied; mailbox sync skipped",
        matched=len(selected_paths),
        limited=False,
        saved_paths=(),
        selected_paths=selected_paths,
        selected_uids=(),
    )


def _records(
    config: SubscriptionEmailConfig,
    *,
    source_paths: tuple[Path, ...] | None = None,
) -> list[EmailRecord]:
    if config.mode != "local_eml":
        raise NotImplementedError(
            f"subscription email mode {config.mode!r} is configured but not implemented yet"
        )
    if source_paths is not None:
        return [parse_email_file(path) for path in sorted(source_paths)]
    if not config.input_path.exists():
        raise FileNotFoundError(config.input_path)
    return read_local_emails(config.input_path)


def _mailbox_source_paths(
    config: SubscriptionEmailConfig,
    mailbox_sync: MailboxSyncResult,
) -> tuple[Path, ...] | None:
    if config.mode == "local_eml":
        return None
    return tuple(mailbox_sync.selected_paths)


def _eligible_records(
    records: list[EmailRecord],
    *,
    config: SubscriptionEmailConfig,
    fetched_at: datetime,
) -> tuple[list[EmailRecord], list[dict[str, object]]]:
    oldest = fetched_at - timedelta(days=config.lookback_days)
    eligible: list[EmailRecord] = []
    ignored: list[dict[str, object]] = []
    for record in records:
        if record.received_at > fetched_at:
            ignored.append(_ignored_record(record, "future_email"))
        elif record.received_at < oldest:
            ignored.append(_ignored_record(record, "outside_lookback_window"))
        else:
            eligible.append(record)
    return eligible, ignored


def _write_outputs(
    *,
    repo_root: Path,
    config_path: Path,
    config: SubscriptionEmailConfig,
    fetched_at: datetime,
    processed_emails: int,
    news_rows: list[dict[str, object]],
    activity_rows: list[dict[str, object]],
    event_rows: list[dict[str, object]],
    link_stats: LinkedContentStats,
    mailbox_sync: MailboxSyncResult,
    manual_review: list[dict[str, object]],
    ignored: list[dict[str, object]],
    news_path: Path | None,
    news_manifest_path: Path | None,
    activity_path: Path | None,
    activity_manifest_path: Path | None,
    event_path: Path | None,
    event_manifest_path: Path | None,
    summary_root: Path | None,
) -> list[Path]:
    paths: list[Path] = []
    resolved_news_path = (
        news_path or repo_root / "research" / "data" / "parquet" / "news_rss.parquet"
    )
    resolved_news_manifest = (
        news_manifest_path or repo_root / "research" / "data" / "manifests" / "news_rss.json"
    )
    resolved_activity_path = (
        activity_path
        or repo_root / "research" / "data" / "parquet" / "unusual_activity_alerts.parquet"
    )
    resolved_activity_manifest = (
        activity_manifest_path
        or repo_root / "research" / "data" / "manifests" / "unusual_activity_alerts.json"
    )
    resolved_event_path = (
        event_path or repo_root / "research" / "data" / "parquet" / "subscription_emails.parquet"
    )
    resolved_event_manifest = (
        event_manifest_path
        or repo_root / "research" / "data" / "manifests" / "subscription_emails.json"
    )
    if news_rows:
        write_news_frame(resolved_news_path, pd.DataFrame(news_rows))
        write_news_manifest(resolved_news_manifest, resolved_news_path, fetched_at=fetched_at)
        paths.extend([resolved_news_path, resolved_news_manifest])
    if activity_rows:
        write_activity_alert_frame(resolved_activity_path, pd.DataFrame(activity_rows))
        write_activity_manifest(
            resolved_activity_manifest,
            resolved_activity_path,
            fetched_at=fetched_at,
        )
        paths.extend([resolved_activity_path, resolved_activity_manifest])
    if event_rows:
        write_event_frame(resolved_event_path, pd.DataFrame(event_rows))
        write_event_manifest(
            resolved_event_manifest,
            resolved_event_path,
            fetched_at=fetched_at,
            issues=[],
        )
        paths.extend([resolved_event_path, resolved_event_manifest])
    summary_paths = write_summary(
        summary_root or repo_root / "research" / "results" / "latest-subscription-emails",
        _summary_payload(
            repo_root=repo_root,
            config_path=config_path,
            config=config,
            fetched_at=fetched_at,
            processed_emails=processed_emails,
            news_rows=news_rows,
            activity_rows=activity_rows,
            event_rows=event_rows,
            link_stats=link_stats,
            mailbox_sync=mailbox_sync,
            manual_review=manual_review,
            ignored=ignored,
        ),
    )
    paths.extend(summary_paths)
    return paths


def _summary_payload(
    *,
    repo_root: Path,
    config_path: Path,
    config: SubscriptionEmailConfig,
    fetched_at: datetime,
    processed_emails: int,
    news_rows: list[dict[str, object]],
    activity_rows: list[dict[str, object]],
    event_rows: list[dict[str, object]],
    link_stats: LinkedContentStats,
    mailbox_sync: MailboxSyncResult,
    manual_review: list[dict[str, object]],
    ignored: list[dict[str, object]],
) -> dict[str, Any]:
    service_counts = _service_counts(event_rows)
    return {
        "schema_version": "0.1.0",
        "config_path": _display_path(config_path, repo_root),
        "mode": config.mode,
        "enabled_services": list(config.enabled_services),
        "input_path": _display_path(config.input_path, repo_root),
        "processed_emails": processed_emails,
        "news_rows": len(news_rows),
        "activity_rows": len(activity_rows),
        "event_rows": len(event_rows),
        "linked_content": {
            "enabled": config.follow_article_links,
            "attempted": link_stats.attempted,
            "succeeded": link_stats.succeeded,
            "failed": link_stats.failed,
            "skipped": link_stats.skipped,
            "cache_hits": link_stats.cached,
            "login_required": link_stats.login_required,
            "unavailable": link_stats.unavailable,
            "status_counts": dict(link_stats.status_counts),
        },
        "guardrails": {
            "mailbox_unseen_only": config.mailbox_unseen_only,
            "mailbox_max_messages": config.mailbox_max_messages,
            "article_max_links_per_email": config.article_max_links_per_email,
            "article_max_total_per_run": config.article_max_total_per_run,
            "mailbox_mark_seen": config.mailbox_mark_seen,
        },
        "mailbox_sync": _mailbox_sync_payload(mailbox_sync, repo_root),
        "manual_review_count": len(manual_review),
        "ignored_count": len(ignored),
        "service_counts": service_counts,
        "source_health": _source_health_rows(
            config,
            service_counts,
            fetched_at,
            link_stats=link_stats,
            event_rows=event_rows,
            ignored=ignored,
        ),
        "recent_evidence": _recent_evidence(event_rows),
        "manual_review": manual_review,
        "ignored": ignored,
        "redaction": "raw email bodies are excluded; message ids are stored as hashes",
        "verdict": _verdict(event_rows, manual_review, link_stats),
        "fetched_at": fetched_at.isoformat(),
    }


def _source_health_rows(
    config: SubscriptionEmailConfig,
    service_counts: dict[str, int],
    fetched_at: datetime,
    *,
    link_stats: LinkedContentStats,
    event_rows: list[dict[str, object]],
    ignored: list[dict[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    linked_status_by_service = _linked_status_counts_by_service(event_rows, ignored)
    login_issue_services = set(config.article_login_preflight_services or config.enabled_services)
    for service in config.enabled_services:
        count = service_counts.get(service, 0)
        linked_status_counts = linked_status_by_service.get(service, {})
        needs_login = _needs_article_login(
            service,
            linked_status_counts,
            link_stats=link_stats,
            login_issue_services=login_issue_services,
        )
        article_unavailable = linked_status_counts.get(ARTICLE_UNAVAILABLE_STATUS, 0) > 0
        status = "HEALTHY" if count else "STALE"
        freshness = "FRESH" if count else "UNAVAILABLE"
        notes = ["local email ingest completed without exposing raw bodies"]
        if needs_login:
            status = "DEGRADED"
            freshness = "UNAVAILABLE"
            notes.append("linked article access needs login confirmation")
        elif article_unavailable:
            status = "DEGRADED"
            notes.append("one or more linked articles were unavailable")
        rows.append(
            {
                "source": f"subscription-email-{service}",
                "source_tier": SourceTier.PAID_SUB_EMAIL.value,
                "status": status,
                "freshness": freshness,
                "checked_at": fetched_at.isoformat(),
                "last_success_at": fetched_at.isoformat() if count else None,
                "event_count": count,
                "needs_login": needs_login,
                "linked_content_status_counts": dict(linked_status_counts),
                "notes": notes,
            }
        )
    return rows


def _linked_status_counts_by_service(
    event_rows: list[dict[str, object]],
    ignored: list[dict[str, object]],
) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {}
    for row in [*event_rows, *ignored]:
        service = str(row.get("service") or "")
        status = str(row.get("linked_content_status") or row.get("reason") or "not_requested")
        if not service:
            continue
        counts.setdefault(service, Counter())[status] += 1
    return {service: dict(counter) for service, counter in counts.items()}


def _needs_article_login(
    service: str,
    linked_status_counts: dict[str, int],
    *,
    link_stats: LinkedContentStats,
    login_issue_services: set[str],
) -> bool:
    if (
        linked_status_counts.get(LOGIN_GATED_LINK_STATUS, 0) > 0
        or linked_status_counts.get(LOGIN_PREFLIGHT_REQUIRED_STATUS, 0) > 0
    ):
        return True
    return link_stats.login_required > 0 and service in login_issue_services


def _recent_evidence(
    event_rows: list[dict[str, object]],
    limit: int = 5,
) -> list[dict[str, object]]:
    recent = sorted(
        event_rows,
        key=lambda row: str(row.get("timestamp_as_of") or ""),
        reverse=True,
    )[:limit]
    return [
        {
            "ticker": str(row.get("ticker") or ""),
            "service": str(row.get("service") or ""),
            "event_type": str(row.get("event_type") or ""),
            "direction": str(row.get("direction") or "NEUTRAL"),
            "linked_content_status": str(row.get("linked_content_status") or "not_requested"),
            "thesis": _safe_text(
                row.get("linked_content_thesis")
                or _legacy_linked_thesis(row.get("linked_content_summary")),
            ),
            "key_points": _string_items(row.get("linked_content_key_points"))[:3],
            "decision_use": _sentence_case(_safe_text(row.get("linked_content_decision_use"))),
            "timestamp_as_of": str(row.get("timestamp_as_of") or ""),
        }
        for row in recent
    ]


def _mailbox_sync_payload(
    mailbox_sync: MailboxSyncResult,
    repo_root: Path,
) -> dict[str, object]:
    return {
        **asdict(mailbox_sync),
        "output_path": _display_path(mailbox_sync.output_path, repo_root),
        "saved_paths": [
            _display_path(path, repo_root)
            for path in mailbox_sync.saved_paths
        ],
        "selected_paths": [
            _display_path(path, repo_root)
            for path in mailbox_sync.selected_paths
        ],
        "selected_uids": list(mailbox_sync.selected_uids),
    }


def _service_counts(event_rows: list[dict[str, object]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in event_rows:
        services = row.get("services")
        if isinstance(services, list):
            counts.update(str(service) for service in services)
        else:
            counts[str(row.get("service"))] += 1
    return dict(sorted(counts.items()))


def _ignored_record(record: EmailRecord, reason: str) -> dict[str, object]:
    return {
        "service": None,
        "reason": reason,
        "message_id_hash": _hash(record.message_id),
        "sender_domain": record.sender_domain,
        "received_at": record.received_at.isoformat(),
    }


def _verdict(
    event_rows: list[dict[str, object]],
    manual_review: list[dict[str, object]],
    link_stats: LinkedContentStats,
) -> str:
    if link_stats.login_required:
        return "needs_article_login"
    if (
        link_stats.attempted > 0
        and link_stats.succeeded == 0
        and (link_stats.unavailable > 0 or link_stats.failed > 0)
    ):
        return "linked_content_unavailable"
    if event_rows:
        return "ready_for_research_batch"
    if manual_review:
        return "needs_manual_review"
    return "no_matching_subscription_evidence"


def _utc_now(clock: Callable[[], datetime] | None) -> datetime:
    value = clock() if clock is not None else datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return path.as_posix()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _safe_text(value: object, max_chars: int = 240) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def _sentence_case(value: str | None) -> str | None:
    if value is None:
        return None
    return value[0].upper() + value[1:] if value else value


def _legacy_linked_thesis(value: object) -> str | None:
    summary = _safe_text(value, max_chars=1_000)
    if summary is None:
        return None
    if not summary.startswith("Linked content thesis:"):
        return summary
    cleaned = summary.removeprefix("Linked content thesis:").strip()
    for marker in (". Why it matters:", " Context:", "; tickers=", "; direction="):
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0]
            break
    return _safe_text(cleaned.strip(" ."))


def _string_items(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in (_safe_text(raw, max_chars=120) for raw in value) if item]
