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

REQUIRED_DB_ENV = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


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
        )


def _env_bool(value: str | None) -> bool:
    return value is not None and value.lower() in {"1", "true", "yes", "on"}


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


def create_engine(settings: DatabaseSettings | None = None) -> AsyncEngine:
    db_settings = DatabaseSettings.from_env() if settings is None else settings
    return create_async_engine(
        build_database_url(db_settings),
        echo=db_settings.echo,
        pool_pre_ping=True,
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
