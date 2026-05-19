from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pandas as pd

EVENT_COLUMNS = [
    "ticker",
    "service",
    "services",
    "event_type",
    "event_types",
    "direction",
    "title",
    "source_refs",
    "source",
    "source_tier",
    "source_id",
    "source_url",
    "message_id_hash",
    "sender_domain",
    "received_at",
    "linked_content_status",
    "linked_content_url",
    "linked_content_title_hash",
    "linked_content_summary",
    "linked_content_direction",
    "linked_content_thesis",
    "linked_content_catalysts",
    "linked_content_risk_flags",
    "linked_content_key_points",
    "linked_content_tickers",
    "linked_content_decision_use",
    "linked_content_signal_strength",
    "linked_content_context_chars",
    "linked_content_confidence",
    "timestamp_observed",
    "timestamp_as_of",
    "freshness",
    "confidence",
    "verification_level",
]
SUBSCRIPTION_EMAIL_STALE_AFTER = timedelta(hours=4)


def write_event_frame(path: Path, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    output = _with_event_defaults(frame)[EVENT_COLUMNS].copy()
    if path.exists():
        existing = _with_event_defaults(pd.read_parquet(path))[EVENT_COLUMNS]
        output = pd.concat([existing, output], ignore_index=True)
    output["_dedupe_key"] = output.apply(_dedupe_key, axis=1)
    output = (
        output.drop_duplicates(subset=["_dedupe_key"], keep="last")
        .drop(columns=["_dedupe_key"])
        .sort_values(["timestamp_as_of", "ticker", "source_id"])
        .reset_index(drop=True)
    )
    output.to_parquet(path, engine="pyarrow", compression="snappy", index=False)
    return len(frame)


def _dedupe_key(row: pd.Series) -> str:
    ticker = str(row.get("ticker") or "").upper()
    source_url = _normalize_url(str(row.get("source_url") or ""))
    if ticker and source_url and source_url.startswith(("http://", "https://")):
        return f"url:{ticker}:{source_url}"
    return f"source:{row.get('source_id')}"


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or parts.path
    return urlunsplit((parts.scheme.lower(), netloc, path, "", ""))


def _with_event_defaults(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    defaults: dict[str, str | None] = {
        "source": "subscription-email",
        "source_tier": "PAID_SUB_EMAIL",
        "freshness": "FRESH",
        "linked_content_summary": None,
        "linked_content_direction": None,
        "linked_content_thesis": None,
        "linked_content_decision_use": None,
        "linked_content_signal_strength": None,
        "linked_content_confidence": None,
    }
    for column, value in defaults.items():
        if column not in output.columns:
            output[column] = value
    for column in (
        "linked_content_catalysts",
        "linked_content_risk_flags",
        "linked_content_key_points",
        "linked_content_tickers",
    ):
        if column not in output.columns:
            output[column] = [[] for _ in range(len(output))]
    if "linked_content_context_chars" not in output.columns:
        output["linked_content_context_chars"] = None
    return output


def write_manifest(
    manifest_path: Path,
    parquet_path: Path,
    *,
    fetched_at: datetime,
    issues: list[dict[str, object]] | None = None,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    stats = _stats(parquet_path)
    manifest = {
        "dataset": "subscription_emails",
        "path": parquet_path.name,
        "schema_version": 1,
        "row_count": stats["row_count"],
        "checksum": _checksum(parquet_path),
        "fetched_at": fetched_at.isoformat(),
        "max_timestamp_as_of": stats["max_timestamp_as_of"],
        "stale_after": (fetched_at + SUBSCRIPTION_EMAIL_STALE_AFTER).isoformat(),
        "source_url": None,
        "issues": issues or [],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def write_summary(
    output_root: Path,
    summary: dict[str, Any],
) -> tuple[Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "subscription-email-ingest.json"
    md_path = output_root / "subscription-email-ingest.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(summary_to_markdown(summary), encoding="utf-8")
    return json_path, md_path


def summary_to_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Subscription Email Ingest",
        "",
        f"Config: `{summary['config_path']}`",
        f"Mode: `{summary['mode']}`",
        f"Verdict: `{summary['verdict']}`",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| Processed emails | {summary['processed_emails']} |",
        f"| News rows | {summary['news_rows']} |",
        f"| Activity rows | {summary['activity_rows']} |",
        f"| Deduped events | {summary['event_rows']} |",
        f"| Mailbox messages checked | {_mailbox_count(summary, 'attempted')} |",
        f"| Real emails saved | {_mailbox_count(summary, 'saved')} |",
        f"| Linked content attempts | {_linked_count(summary, 'attempted')} |",
        f"| Linked content analyzed | {_linked_count(summary, 'succeeded')} |",
        f"| Mailbox max messages | {_guardrail_count(summary, 'mailbox_max_messages')} |",
        f"| Article max links/run | {_guardrail_count(summary, 'article_max_total_per_run')} |",
        f"| Manual review | {summary['manual_review_count']} |",
        f"| Ignored | {summary['ignored_count']} |",
        "",
        "| Service | Events |",
        "| --- | ---: |",
    ]
    service_counts = summary.get("service_counts", {})
    if isinstance(service_counts, dict) and service_counts:
        for service, count in sorted(service_counts.items()):
            lines.append(f"| {service} | {count} |")
    else:
        lines.append("| none | 0 |")
    lines.extend(["", "## Recent Evidence", ""])
    recent = summary.get("recent_evidence", [])
    if isinstance(recent, list) and recent:
        lines.extend(
            [
                "| Ticker | Direction | Status | Thesis | Agency Use |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in recent:
            if not isinstance(item, dict):
                continue
            lines.append(
                "| "
                f"{_markdown_cell(item.get('ticker'))} | "
                f"{_markdown_cell(item.get('direction'))} | "
                f"{_markdown_cell(item.get('linked_content_status'))} | "
                f"{_markdown_cell(item.get('thesis'))} | "
                f"{_markdown_cell(item.get('decision_use'))} |"
            )
    else:
        lines.append("No recent evidence rows were written.")
    lines.append("")
    return "\n".join(lines)


def _linked_count(summary: dict[str, Any], key: str) -> object:
    linked = summary.get("linked_content")
    if not isinstance(linked, dict):
        return 0
    return linked.get(key, 0)


def _mailbox_count(summary: dict[str, Any], key: str) -> object:
    mailbox = summary.get("mailbox_sync")
    if not isinstance(mailbox, dict):
        return 0
    return mailbox.get(key, 0)


def _guardrail_count(summary: dict[str, Any], key: str) -> object:
    guardrails = summary.get("guardrails")
    if not isinstance(guardrails, dict):
        return 0
    return guardrails.get(key, 0)


def _markdown_cell(value: object) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text.replace("|", "\\|")


def _stats(path: Path) -> dict[str, int | str]:
    if not path.exists():
        now = datetime.now(UTC).isoformat()
        return {"row_count": 0, "max_timestamp_as_of": now}
    frame = pd.read_parquet(path, columns=["timestamp_as_of"])
    max_date = pd.to_datetime(frame["timestamp_as_of"]).max().to_pydatetime()
    if max_date.tzinfo is None or max_date.utcoffset() is None:
        max_date = max_date.replace(tzinfo=UTC)
    return {"row_count": len(frame), "max_timestamp_as_of": max_date.isoformat()}


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    if path.exists():
        digest.update(path.read_bytes())
    return digest.hexdigest()
