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
    linked_content_summary: str | None = None
    linked_content_status: str = "not_requested"
    linked_content_url: str | None = None
    linked_content_title_hash: str | None = None
    linked_content_direction: str | None = None
    linked_content_thesis: str | None = None
    linked_content_catalysts: tuple[str, ...] = ()
    linked_content_risk_flags: tuple[str, ...] = ()
    linked_content_key_points: tuple[str, ...] = ()
    linked_content_tickers: tuple[str, ...] = ()
    linked_content_decision_use: str | None = None
    linked_content_signal_strength: str | None = None
    linked_content_context_chars: int | None = None
    linked_content_confidence: float | None = None


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
    linked_content_attempted: int
    linked_content_succeeded: int
    linked_content_failed: int
    linked_content_skipped: int
    linked_content_login_required: int
    linked_content_unavailable: int
    linked_content_status_counts: dict[str, int]
    manual_review_count: int
    ignored_count: int
    service_counts: dict[str, int]
    written_paths: tuple[str, ...]
    mailbox_sync: dict[str, object] | None = None
