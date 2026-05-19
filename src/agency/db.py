from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

REQUIRED_DB_ENV = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")
DEFAULT_CONNECT_TIMEOUT_SECONDS = 1.0
DEFAULT_SQLITE_DATABASE_URL = "sqlite+aiosqlite:///./agency_local.db"


class MissingDatabaseConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    host: str
    port: int
    name: str
    user: str
    password: str
    echo: bool = False
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DatabaseSettings:
        if env is None:
            load_dotenv()
        values = os.environ if env is None else env
        missing = [name for name in REQUIRED_DB_ENV if not values.get(name)]
        if missing:
            joined = ", ".join(missing)
            msg = f"Missing required database environment variables: {joined}"
            raise MissingDatabaseConfigurationError(msg)

        return cls(
            host=values["DB_HOST"],
            port=int(values["DB_PORT"]),
            name=values["DB_NAME"],
            user=values["DB_USER"],
            password=values["DB_PASSWORD"],
            echo=_env_bool(values.get("DB_ECHO")),
            connect_timeout_seconds=_env_float(
                values.get("DB_CONNECT_TIMEOUT_SECONDS"),
                default=DEFAULT_CONNECT_TIMEOUT_SECONDS,
            ),
        )


def _env_bool(value: str | None) -> bool:
    return value is not None and value.lower() in {"1", "true", "yes", "on"}


def _env_float(value: str | None, *, default: float) -> float:
    if value is None:
        return default
    return float(value)


def build_database_url(settings: DatabaseSettings | None = None) -> URL:
    db_settings = DatabaseSettings.from_env() if settings is None else settings
    return URL.create(
        "postgresql+asyncpg",
        username=db_settings.user,
        password=db_settings.password,
        host=db_settings.host,
        port=db_settings.port,
        database=db_settings.name,
    )


def _effective_database_url(
    settings: DatabaseSettings | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    if settings is not None:
        return build_database_url(settings).render_as_string(hide_password=False)
    if env is None:
        load_dotenv()
    values = os.environ if env is None else env
    database_url = values.get("DATABASE_URL", "").strip()
    if database_url:
        return _normalize_async_database_url(database_url)
    if all(values.get(name) for name in REQUIRED_DB_ENV):
        return build_database_url(DatabaseSettings.from_env(values)).render_as_string(
            hide_password=False
        )
    return DEFAULT_SQLITE_DATABASE_URL


def create_engine(settings: DatabaseSettings | None = None) -> AsyncEngine:
    url = _effective_database_url(settings)
    echo = settings.echo if settings is not None else _env_bool(os.environ.get("DB_ECHO"))
    timeout = (
        settings.connect_timeout_seconds
        if settings is not None
        else _env_float(
            os.environ.get("DB_CONNECT_TIMEOUT_SECONDS"),
            default=DEFAULT_CONNECT_TIMEOUT_SECONDS,
        )
    )
    kwargs: dict[str, object] = {
        "echo": echo,
        "poolclass": NullPool,
        "pool_pre_ping": True,
    }
    if not _is_sqlite_database_url(url):
        kwargs["connect_args"] = {"timeout": timeout}
    return create_async_engine(
        url,
        **kwargs,
    )


def create_sessionmaker(
    settings: DatabaseSettings | None = None,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(create_engine(settings), expire_on_commit=False)


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker()


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


def _is_sqlite_database_url(url: str) -> bool:
    return url.strip().lower().startswith("sqlite")


def _normalize_async_database_url(url: str) -> str:
    value = url.strip()
    if value.lower().startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + value.split("sqlite:///", maxsplit=1)[1]
    return value
