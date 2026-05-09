from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from subscription_email.config import load_subscription_email_config
from subscription_email.ingest import ingest_subscription_email_config
from subscription_email.linked_content import ArticleFetcher
from subscription_email.mailbox import ImapFactory, MailboxSyncResult, sync_mailbox_emails

MIN_MONITOR_POLL_SECONDS = 5


@dataclass(frozen=True)
class MonitorRunResult:
    status: str
    reason: str
    changed_files: int
    mailbox_sync: MailboxSyncResult
    ingest: dict[str, object] | None
    state_path: Path


def monitor_subscription_emails_once(
    *,
    config_path: Path,
    repo_root: Path,
    state_path: Path | None = None,
    summary_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    imap_factory: ImapFactory | None = None,
    article_fetcher: ArticleFetcher | None = None,
) -> MonitorRunResult:
    config = load_subscription_email_config(config_path, repo_root=repo_root)
    get_now = clock or (lambda: datetime.now(UTC))
    mailbox_sync = sync_mailbox_emails(config, imap_factory=imap_factory)
    resolved_state_path = state_path or config.input_path / ".subscription-email-monitor.json"
    before = _read_state(resolved_state_path)
    snapshot = _snapshot(config.input_path)
    changed_files = _changed_files(before.get("files", []), snapshot)
    if not changed_files:
        result = MonitorRunResult(
            status="skipped",
            reason="no new or changed email files",
            changed_files=0,
            mailbox_sync=mailbox_sync,
            ingest=None,
            state_path=resolved_state_path,
        )
    else:
        ingest = ingest_subscription_email_config(
            config=replace(config, mode="local_eml"),
            config_path=config_path,
            repo_root=repo_root,
            summary_root=summary_root,
            clock=get_now,
            article_fetcher=article_fetcher,
            source_paths=tuple(config.input_path / path for path in changed_files),
        )
        result = MonitorRunResult(
            status="analyzed",
            reason="new or changed email files detected",
            changed_files=len(changed_files),
            mailbox_sync=mailbox_sync,
            ingest={
                "processed_emails": ingest.processed_emails,
                "news_rows": ingest.news_rows,
                "activity_rows": ingest.activity_rows,
                "event_rows": ingest.event_rows,
                "linked_content_attempted": ingest.linked_content_attempted,
                "linked_content_succeeded": ingest.linked_content_succeeded,
                "manual_review_count": ingest.manual_review_count,
                "ignored_count": ingest.ignored_count,
            },
            state_path=resolved_state_path,
        )
    _write_state(
        resolved_state_path,
        {
            "schema_version": "0.1.0",
            "updated_at": _utc(get_now()).isoformat(),
            "files": snapshot,
            "last_result": _result_payload(result, repo_root),
        },
    )
    return result


def watch_subscription_emails(
    *,
    config_path: Path,
    repo_root: Path,
    state_path: Path | None = None,
    summary_root: Path | None = None,
    poll_seconds: int | None = None,
) -> Iterable[MonitorRunResult]:
    config = load_subscription_email_config(config_path, repo_root=repo_root)
    interval = poll_seconds or config.monitor_poll_seconds
    if interval < MIN_MONITOR_POLL_SECONDS:
        raise ValueError("poll_seconds must be >= 5")
    while True:
        yield monitor_subscription_emails_once(
            config_path=config_path,
            repo_root=repo_root,
            state_path=state_path,
            summary_root=summary_root,
        )
        time.sleep(interval)


def monitor_result_to_json(result: MonitorRunResult, repo_root: Path) -> str:
    return json.dumps(_result_payload(result, repo_root), indent=2, sort_keys=True) + "\n"


def _snapshot(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows = []
    for file in sorted(path.rglob("*.eml")):
        stat = file.stat()
        rows.append(
            {
                "path": file.relative_to(path).as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    return rows


def _changed_count(previous: object, current: list[dict[str, object]]) -> int:
    return len(_changed_files(previous, current))


def _changed_files(previous: object, current: list[dict[str, object]]) -> list[Path]:
    if not isinstance(previous, list):
        return [Path(str(item["path"])) for item in current if _has_path(item)]
    old = {json.dumps(item, sort_keys=True) for item in previous if isinstance(item, dict)}
    return [
        Path(str(item["path"]))
        for item in current
        if _has_path(item) and json.dumps(item, sort_keys=True) not in old
    ]


def _has_path(item: object) -> bool:
    return isinstance(item, dict) and isinstance(item.get("path"), str)


def _read_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _result_payload(result: MonitorRunResult, repo_root: Path) -> dict[str, object]:
    return {
        "status": result.status,
        "reason": result.reason,
        "changed_files": result.changed_files,
        "mailbox_sync": {
            **asdict(result.mailbox_sync),
            "output_path": _display_path(result.mailbox_sync.output_path, repo_root),
        },
        "ingest": result.ingest,
        "state_path": _display_path(result.state_path, repo_root),
    }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return path.as_posix()
