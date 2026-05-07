from __future__ import annotations

import pytest

from agency.db import DEFAULT_CONNECT_TIMEOUT_SECONDS, DatabaseSettings

CUSTOM_TIMEOUT_SECONDS = 2.5


def test_database_settings_use_default_connect_timeout() -> None:
    settings = DatabaseSettings.from_env(_env())

    assert settings.connect_timeout_seconds == DEFAULT_CONNECT_TIMEOUT_SECONDS


def test_database_settings_read_connect_timeout_override() -> None:
    settings = DatabaseSettings.from_env(
        _env({"DB_CONNECT_TIMEOUT_SECONDS": str(CUSTOM_TIMEOUT_SECONDS)})
    )

    assert settings.connect_timeout_seconds == CUSTOM_TIMEOUT_SECONDS


def test_database_settings_reject_missing_values() -> None:
    env = _env()
    del env["DB_PASSWORD"]

    with pytest.raises(RuntimeError, match="DB_PASSWORD"):
        DatabaseSettings.from_env(env)


def _env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    values = {
        "DB_HOST": "localhost",
        "DB_PORT": "5432",
        "DB_NAME": "agency",
        "DB_USER": "agency_app",
        "DB_PASSWORD": "agency",
    }
    if overrides:
        values.update(overrides)
    return values
