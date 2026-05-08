from __future__ import annotations

import argparse
import gzip
import subprocess
from pathlib import Path
from typing import Final

DEFAULT_CONTAINER: Final = "trading-agency-postgres"
DEFAULT_DATABASE: Final = "agency"
DEFAULT_USER: Final = "postgres"


def main() -> None:
    args = _parse_args()
    restore_database(
        input_path=args.input,
        container=args.container,
        database=args.database,
        user=args.user,
    )
    print(f"restored {args.input}")


def psql_restore_command(*, container: str, database: str, user: str) -> list[str]:
    return [
        "docker",
        "exec",
        "--interactive",
        container,
        "psql",
        "--username",
        user,
        "--dbname",
        database,
        "--set",
        "ON_ERROR_STOP=on",
    ]


def restore_database(
    *,
    input_path: Path,
    container: str = DEFAULT_CONTAINER,
    database: str = DEFAULT_DATABASE,
    user: str = DEFAULT_USER,
) -> None:
    if not input_path.is_file():
        raise FileNotFoundError(input_path)
    command = psql_restore_command(container=container, database=database, user=user)
    result = subprocess.run(
        command,
        input=_read_backup(input_path),
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"psql restore failed: {stderr}")


def _read_backup(input_path: Path) -> bytes:
    if input_path.suffix == ".gz":
        with gzip.open(input_path, "rb") as backup:
            return backup.read()
    return input_path.read_bytes()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore the local agency Postgres database.")
    parser.add_argument("input", type=Path, help="Input .sql or .sql.gz path.")
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--user", default=DEFAULT_USER)
    return parser.parse_args()


if __name__ == "__main__":
    main()
