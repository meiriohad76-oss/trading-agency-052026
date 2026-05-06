import os

import asyncpg
import pytest
from dotenv import load_dotenv
from sqlalchemy import text

from agency.db import get_session

load_dotenv()

pytestmark = pytest.mark.skipif(
    os.getenv("DB_HOST") is None,
    reason="DB_HOST is not set",
)


async def test_db_connection_select_one() -> None:
    try:
        async with get_session() as session:
            result = await session.execute(text("SELECT 1"))
    except (ConnectionRefusedError, OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"database is not reachable: {exc}")

    assert result.scalar_one() == 1
