from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

ALEMBIC_VERSION_NUM_LENGTH = 128


def ensure_alembic_version_table_capacity(
    connection: Connection,
    *,
    version_length: int = ALEMBIC_VERSION_NUM_LENGTH,
) -> bool:
    """Make Alembic's version table fit this repo's long revision identifiers."""
    if connection.dialect.name != "postgresql":
        return False

    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR({version_length}) NOT NULL,
                CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
            )
            """
        )
    )
    connection.execute(
        text(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = 'alembic_version'
                      AND column_name = 'version_num'
                      AND character_maximum_length < {version_length}
                ) THEN
                    ALTER TABLE alembic_version
                    ALTER COLUMN version_num TYPE VARCHAR({version_length});
                END IF;
            END
            $$;
            """
        )
    )
    return True


def prepare_migration_connection(connection: Connection) -> bool:
    changed = ensure_alembic_version_table_capacity(connection)
    if changed and connection.in_transaction():
        connection.commit()
    return changed
