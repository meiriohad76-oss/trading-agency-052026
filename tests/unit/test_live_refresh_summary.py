from __future__ import annotations

import json
from pathlib import Path

from data_refresh.live_summary import write_live_refresh_summary


def test_write_live_refresh_summary_renders_compact_artifacts(tmp_path: Path) -> None:
    status_path = tmp_path / "status.json"
    manifest_root = tmp_path / "manifests"
    output_root = tmp_path / "summary"
    _write_status(status_path)
    _write_manifest(manifest_root / "prices_daily.json")

    summary = write_live_refresh_summary(
        status_path=status_path,
        manifest_root=manifest_root,
        output_root=output_root,
    )

    assert summary["verdict"] == "ready_for_research_batch"
    assert (output_root / "live-refresh-summary.json").is_file()
    markdown = (output_root / "live-refresh-summary.md").read_text(encoding="utf-8")
    assert "| prices_daily | 10 | 0 | 2025-12-31T00:00:00+00:00 |" in markdown


def _write_status(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "blocked": False,
                "failed": False,
                "config": {
                    "start": "2021-01-01",
                    "end": "2025-12-31",
                    "datasets": ["prices_daily"],
                    "tickers": ["AAPL"],
                    "rss_feed_count": 0,
                    "filer_ciks": [],
                },
                "jobs": [
                    {
                        "dataset": "prices_daily",
                        "status": "passed",
                        "reason": "refresh command completed",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "dataset": "prices_daily",
                "row_count": 10,
                "issues": [],
                "max_timestamp_as_of": "2025-12-31T00:00:00+00:00",
                "checksum": "abc123",
                "source_url": "https://finance.yahoo.com",
            }
        ),
        encoding="utf-8",
    )
