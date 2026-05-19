from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from activity_alerts.storage import write_manifest as write_activity_manifest
from news.storage import write_manifest as write_news_manifest
from options.storage import write_manifest as write_options_manifest
from subscription_email.storage import write_manifest as write_subscription_manifest

FETCHED_AT = datetime(2026, 5, 8, 14, 0, tzinfo=UTC)


def test_context_manifests_have_operational_stale_windows(tmp_path: Path) -> None:
    cases = [
        ("news.json", write_news_manifest, tmp_path / "news.parquet", timedelta(minutes=60)),
        ("options.json", write_options_manifest, tmp_path / "options", timedelta(minutes=30)),
        (
            "subscription.json",
            write_subscription_manifest,
            tmp_path / "subscription.parquet",
            timedelta(hours=4),
        ),
        (
            "activity.json",
            write_activity_manifest,
            tmp_path / "activity.parquet",
            timedelta(minutes=30),
        ),
    ]

    for filename, writer, data_path, expected_delta in cases:
        manifest_path = tmp_path / filename
        writer(manifest_path, data_path, fetched_at=FETCHED_AT)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))

        assert datetime.fromisoformat(payload["stale_after"]) == FETCHED_AT + expected_delta
