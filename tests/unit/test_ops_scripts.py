from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.backup_postgres import default_backup_path, pg_dump_command
from scripts.check_local_runtime import metric_value
from scripts.check_paper_review_status import check_paper_review_status
from scripts.restore_postgres import psql_restore_command

EXPECTED_SOURCE_HEALTH = 2.0
EXPECTED_REVIEW_QUEUE_COUNT = 4
EXPECTED_REVIEWED_COUNT = 1
EXPECTED_PENDING_COUNT = 3


def test_default_backup_path_uses_timestamped_postgres_directory() -> None:
    path = default_backup_path(datetime(2026, 5, 8, 10, 30, 5, tzinfo=UTC))

    assert path.as_posix() == "backups/postgres/agency-20260508-103005.sql.gz"


def test_backup_command_targets_local_postgres_container() -> None:
    command = pg_dump_command(
        container="trading-agency-postgres",
        database="agency",
        user="postgres",
    )

    assert command == [
        "docker",
        "exec",
        "trading-agency-postgres",
        "pg_dump",
        "--username",
        "postgres",
        "--dbname",
        "agency",
        "--format",
        "plain",
        "--clean",
        "--if-exists",
    ]


def test_restore_command_reads_sql_from_stdin() -> None:
    command = psql_restore_command(
        container="trading-agency-postgres",
        database="agency",
        user="postgres",
    )

    assert command == [
        "docker",
        "exec",
        "--interactive",
        "trading-agency-postgres",
        "psql",
        "--username",
        "postgres",
        "--dbname",
        "agency",
        "--set",
        "ON_ERROR_STOP=on",
    ]


def test_metric_value_parses_prometheus_gauge() -> None:
    metrics = "# HELP demo Demo\nagency_source_health_total 2\n"

    assert metric_value(metrics, "agency_source_health_total") == EXPECTED_SOURCE_HEALTH


def test_check_paper_review_status_summarizes_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        assert path == "/status/paper-review"
        return {
            "cycle_id": "cycle-1",
            "verdict": "ready_for_paper_validation",
            "progress": {
                "total_count": EXPECTED_REVIEW_QUEUE_COUNT,
                "reviewed_count": EXPECTED_REVIEWED_COUNT,
                "pending_count": EXPECTED_PENDING_COUNT,
                "approve_count": 0,
                "defer_count": 1,
                "reject_count": 0,
            },
            "queue": [{}, {}, {}, {}],
        }

    monkeypatch.setattr(
        "scripts.check_paper_review_status._fetch_json",
        fake_fetch_json,
    )

    summary = check_paper_review_status(min_queue=4, min_reviewed=1, max_pending=3)

    assert summary == {
        "cycle_id": "cycle-1",
        "verdict": "ready_for_paper_validation",
        "total_count": EXPECTED_REVIEW_QUEUE_COUNT,
        "reviewed_count": EXPECTED_REVIEWED_COUNT,
        "pending_count": EXPECTED_PENDING_COUNT,
        "approve_count": 0,
        "defer_count": 1,
        "reject_count": 0,
    }
