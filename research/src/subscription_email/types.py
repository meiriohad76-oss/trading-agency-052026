from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EmailRecord:
    message_id: str
    sender: str
    sender_domain: str
    subject: str
    received_at: datetime
    body_text: str
    source_path: str | None = None


@dataclass(frozen=True)
class ClassifiedEmailRows:
    news_rows: list[dict[str, object]]
    activity_rows: list[dict[str, object]]
    event_rows: list[dict[str, object]]
    manual_review: list[dict[str, object]]
    ignored: list[dict[str, object]]


@dataclass(frozen=True)
class SubscriptionEmailIngestResult:
    processed_emails: int
    news_rows: int
    activity_rows: int
    event_rows: int
    manual_review_count: int
    ignored_count: int
    service_counts: dict[str, int]
    written_paths: tuple[str, ...]
