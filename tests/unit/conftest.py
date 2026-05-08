from __future__ import annotations

from collections.abc import Iterator

import pytest

from agency.db import REQUIRED_DB_ENV, get_sessionmaker


@pytest.fixture(autouse=True)
def isolate_unit_tests_from_local_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep unit tests deterministic when a local Postgres container is running."""
    get_sessionmaker.cache_clear()
    for name in REQUIRED_DB_ENV:
        monkeypatch.setenv(name, "")
    yield
    get_sessionmaker.cache_clear()
