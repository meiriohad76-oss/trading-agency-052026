from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from agency.migration_support import ALEMBIC_VERSION_NUM_LENGTH


class _Dialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _Connection:
    def __init__(self, dialect_name: str = "postgresql") -> None:
        self.dialect = _Dialect(dialect_name)
        self.statements: list[str] = []
        self.commit_count = 0
        self.transaction_open = True

    def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))

    def in_transaction(self) -> bool:
        return self.transaction_open

    def commit(self) -> None:
        self.commit_count += 1
        self.transaction_open = False


def test_postgres_alembic_version_table_is_widened_before_migrations() -> None:
    from agency.migration_support import ensure_alembic_version_table_capacity

    connection = _Connection()

    changed = ensure_alembic_version_table_capacity(connection)

    assert changed is True
    assert len(connection.statements) == 2
    assert "CREATE TABLE IF NOT EXISTS alembic_version" in connection.statements[0]
    assert f"VARCHAR({ALEMBIC_VERSION_NUM_LENGTH})" in connection.statements[0]
    alter_statement = " ".join(connection.statements[1].split())
    assert "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE" in alter_statement
    assert f"VARCHAR({ALEMBIC_VERSION_NUM_LENGTH})" in connection.statements[1]


def test_non_postgres_alembic_version_table_is_left_to_alembic() -> None:
    from agency.migration_support import ensure_alembic_version_table_capacity

    connection = _Connection("sqlite")

    changed = ensure_alembic_version_table_capacity(connection)

    assert changed is False
    assert connection.statements == []


def test_migration_connection_preparation_commits_postgres_capacity_transaction() -> None:
    from agency.migration_support import prepare_migration_connection

    connection = _Connection()

    changed = prepare_migration_connection(connection)

    assert changed is True
    assert connection.commit_count == 1
    assert connection.transaction_open is False


def test_migration_connection_preparation_does_not_commit_when_nothing_changed() -> None:
    from agency.migration_support import prepare_migration_connection

    connection = _Connection("sqlite")

    changed = prepare_migration_connection(connection)

    assert changed is False
    assert connection.commit_count == 0
    assert connection.transaction_open is True


def test_all_revision_ids_fit_the_configured_alembic_version_column() -> None:
    revision_lengths = [
        len(str(_load_migration(path).revision))
        for path in sorted((Path("migrations") / "versions").glob("*.py"))
    ]

    assert revision_lengths
    assert max(revision_lengths) <= ALEMBIC_VERSION_NUM_LENGTH


def _load_migration(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_under_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load migration spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
