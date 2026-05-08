from __future__ import annotations

import argparse
import gzip
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

DEFAULT_CONTAINER: Final = "trading-agency-postgres"
DEFAULT_DATABASE: Final = "agency"
DEFAULT_USER: Final = "postgres"


def main() -> None:
    args = _parse_args()
    output = backup_database(
        output_path=args.output or default_backup_path(),
        container=args.container,
        database=args.database,
        user=args.user,
    )
    print(f"wrote {output}")


def default_backup_path(timestamp: datetime | None = None) -> Path:
    current_time = timestamp or datetime.now(UTC)
    stamp = current_time.strftime("%Y%m%d-%H%M%S")
    return Path("backups") / "postgres" / f"agency-{stamp}.sql.gz"


def pg_dump_command(*, container: str, database: str, user: str) -> list[str]:
    return [
        "docker",
        "exec",
        container,
        "pg_dump",
        "--username",
        user,
        "--dbname",
        database,
        "--format",
        "plain",
        "--clean",
        "--if-exists",
    ]


def backup_database(
    *,
    output_path: Path,
    container: str = DEFAULT_CONTAINER,
    database: str = DEFAULT_DATABASE,
    user: str = DEFAULT_USER,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = pg_dump_command(container=container, database=database, user=user)
    with gzip.open(output_path, "wb") as backup:
        result = subprocess.run(
            command,
            stdout=backup,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode != 0:
        output_path.unlink(missing_ok=True)
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"pg_dump failed: {stderr}")
    return output_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Back up the local agency Postgres database.")
    parser.add_argument("output", nargs="?", type=Path, help="Output .sql.gz path.")
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--user", default=DEFAULT_USER)
    return parser.parse_args()


if __name__ == "__main__":
    main()
