import logging
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from goszakup_ai.marts.definitions import MARTS

log = logging.getLogger(__name__)


async def build_marts(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for mart in reversed(MARTS):
            await conn.execute(text(f"DROP MATERIALIZED VIEW IF EXISTS mart.{mart.name} CASCADE"))
        for mart in MARTS:
            started = time.monotonic()
            await conn.execute(text(f"CREATE MATERIALIZED VIEW mart.{mart.name} AS {mart.sql}"))
            for i, columns in enumerate(mart.indexes):
                unique = columns.startswith("UNIQUE ")
                cols = columns.removeprefix("UNIQUE ")
                kind = "UNIQUE INDEX" if unique else "INDEX"
                await conn.execute(
                    text(f"CREATE {kind} ix_mart_{mart.name}_{i} ON mart.{mart.name} {cols}")
                )
            await conn.execute(text(f"ANALYZE mart.{mart.name}"))
            rows = await conn.scalar(text(f"SELECT count(*) FROM mart.{mart.name}"))
            log.info("mart.%s: %s rows in %.1fs", mart.name, rows, time.monotonic() - started)


async def refresh_marts(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for mart in MARTS:
            started = time.monotonic()
            await conn.execute(text(f"REFRESH MATERIALIZED VIEW mart.{mart.name}"))
            log.info("mart.%s refreshed in %.1fs", mart.name, time.monotonic() - started)
