from __future__ import annotations

from datetime import UTC, datetime

from scripts.backup_postgres import default_backup_path, pg_dump_command
from scripts.check_local_runtime import metric_value
from scripts.restore_postgres import psql_restore_command

EXPECTED_SOURCE_HEALTH = 2.0


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
