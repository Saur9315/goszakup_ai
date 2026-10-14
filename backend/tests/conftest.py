import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from goszakup_ai.core.config import Settings
from goszakup_ai.db import models  # noqa: F401
from goszakup_ai.db.base import SCHEMAS, Base


def _test_db_url() -> URL | None:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return make_url(explicit)
    try:
        url = make_url(Settings().database_url.get_secret_value())
    except Exception:
        return None
    return url.set(database=f"{url.database}_test")


async def _ensure_database(url: URL) -> None:
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        await admin.dispose()


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    url = _test_db_url()
    if url is None:
        pytest.skip("no database configured")
    try:
        await _ensure_database(url)
    except OSError:
        pytest.skip("database is not reachable")
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        for schema in SCHEMAS:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessions(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db_engine, expire_on_commit=False)
