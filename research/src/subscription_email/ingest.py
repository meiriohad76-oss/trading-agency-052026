from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
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
    ArticleFetcher,
    LinkedContentStats,
    enrich_records_with_linked_content,
)
from subscription_email.parser import read_local_emails
from subscription_email.storage import (
    write_event_frame,
    write_summary,
)
from subscription_email.storage import (
    write_manifest as write_event_manifest,
)
from subscription_email.types import EmailRecord, SubscriptionEmailIngestResult

from agency.provenance import SourceTier


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
) -> SubscriptionEmailIngestResult:
    fetched_at = _utc_now(clock)
    records = _records(config)
    eligible, filtered = _eligible_records(records, config=config, fetched_at=fetched_at)
    link_result = enrich_records_with_linked_content(
        eligible,
        config=config,
        fetcher=article_fetcher,
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
    return SubscriptionEmailIngestResult(
        processed_emails=len(eligible),
        news_rows=len(classified.news_rows),
        activity_rows=len(classified.activity_rows),
        event_rows=len(classified.event_rows),
        linked_content_attempted=link_result.stats.attempted,
        linked_content_succeeded=link_result.stats.succeeded,
        linked_content_failed=link_result.stats.failed,
        linked_content_skipped=link_result.stats.skipped,
        manual_review_count=len(classified.manual_review),
        ignored_count=len(ignored),
        service_counts=_service_counts(classified.event_rows),
        written_paths=tuple(_display_path(path, repo_root) for path in paths),
    )


def _records(config: SubscriptionEmailConfig) -> list[EmailRecord]:
    if config.mode != "local_eml":
        raise NotImplementedError(
            f"subscription email mode {config.mode!r} is configured but not implemented yet"
        )
    if not config.input_path.exists():
        raise FileNotFoundError(config.input_path)
    return read_local_emails(config.input_path)


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
        },
        "manual_review_count": len(manual_review),
        "ignored_count": len(ignored),
        "service_counts": service_counts,
        "source_health": _source_health_rows(config, service_counts, fetched_at),
        "manual_review": manual_review,
        "ignored": ignored,
        "redaction": "raw email bodies are excluded; message ids are stored as hashes",
        "verdict": _verdict(event_rows, manual_review),
        "fetched_at": fetched_at.isoformat(),
    }


def _source_health_rows(
    config: SubscriptionEmailConfig,
    service_counts: dict[str, int],
    fetched_at: datetime,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for service in config.enabled_services:
        count = service_counts.get(service, 0)
        rows.append(
            {
                "source": f"subscription-email-{service}",
                "source_tier": SourceTier.PAID_SUB_EMAIL.value,
                "status": "HEALTHY" if count else "STALE",
                "freshness": "FRESH" if count else "UNAVAILABLE",
                "last_success_at": fetched_at.isoformat() if count else None,
                "event_count": count,
                "notes": ["local email ingest completed without exposing raw bodies"],
            }
        )
    return rows


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


def _verdict(event_rows: list[dict[str, object]], manual_review: list[dict[str, object]]) -> str:
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
