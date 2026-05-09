from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

from subscription_email.ingest import ingest_subscription_emails  # noqa: E402


def main() -> int:
    args = _parse_args()
    result = ingest_subscription_emails(
        config_path=args.config,
        repo_root=ROOT,
        news_path=args.news_output,
        news_manifest_path=args.news_manifest,
        activity_path=args.activity_output,
        activity_manifest_path=args.activity_manifest,
        event_path=args.event_output,
        event_manifest_path=args.event_manifest,
        summary_root=args.summary_root,
    )
    print(
        json.dumps(
            {
                "processed_emails": result.processed_emails,
                "news_rows": result.news_rows,
                "activity_rows": result.activity_rows,
                "event_rows": result.event_rows,
                "manual_review_count": result.manual_review_count,
                "ignored_count": result.ignored_count,
                "written_paths": list(result.written_paths),
            },
            sort_keys=True,
        )
    )
    return 0


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
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
