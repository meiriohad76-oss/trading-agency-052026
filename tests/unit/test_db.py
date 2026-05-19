from __future__ import annotations

import pytest

import agency.db as db_module
from agency.db import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DatabaseSettings,
    _effective_database_url,
    create_engine,
)

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


def test_effective_database_url_prefers_database_url() -> None:
    url = _effective_database_url(
        env={
            **_env(),
            "DATABASE_URL": "sqlite+aiosqlite:///./preferred.db",
        }
    )

    assert url == "sqlite+aiosqlite:///./preferred.db"


def test_effective_database_url_normalizes_sync_sqlite_database_url() -> None:
    url = _effective_database_url(env={"DATABASE_URL": "sqlite:///./local.db"})

    assert url == "sqlite+aiosqlite:///./local.db"


def test_effective_database_url_uses_postgres_parts_when_complete() -> None:
    url = _effective_database_url(env=_env())

    assert url == "postgresql+asyncpg://agency_app:agency@localhost:5432/agency"


def test_effective_database_url_falls_back_to_local_sqlite() -> None:
    url = _effective_database_url(env={})

    assert url == "sqlite+aiosqlite:///./agency_local.db"


def test_create_engine_omits_asyncpg_connect_args_for_sqlite_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("DATABASE_URL", "")

    def fake_create_async_engine(url: object, **kwargs: object) -> object:
        captured["url"] = str(url)
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(db_module, "create_async_engine", fake_create_async_engine)

    engine = create_engine()

    assert engine is not None
    assert captured["url"] == "sqlite+aiosqlite:///./agency_local.db"
    assert "connect_args" not in captured["kwargs"]


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
