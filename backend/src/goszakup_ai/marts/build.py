import hashlib
import logging
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from goszakup_ai.marts.definitions import MARTS, Mart

log = logging.getLogger(__name__)


def definition_hash(mart: Mart) -> str:
    return hashlib.sha256("\n".join((mart.sql, *mart.indexes)).encode()).hexdigest()[:16]


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
            await conn.execute(
                text(f"COMMENT ON MATERIALIZED VIEW mart.{mart.name} IS '{definition_hash(mart)}'")
            )
            await conn.execute(text(f"ANALYZE mart.{mart.name}"))
            rows = await conn.scalar(text(f"SELECT count(*) FROM mart.{mart.name}"))
            log.info("mart.%s: %s rows in %.1fs", mart.name, rows, time.monotonic() - started)


async def marts_outdated(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT c.relname, obj_description(c.oid, 'pg_class') AS hash FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'mart' AND c.relkind = 'm'"
            )
        )
        current = {r.relname: r.hash for r in rows}
    return [m.name for m in MARTS if current.get(m.name) != definition_hash(m)]


async def refresh_marts(engine: AsyncEngine) -> None:
    outdated = await marts_outdated(engine)
    if outdated:
        log.info("mart definitions changed (%s): rebuilding", ", ".join(outdated))
        await build_marts(engine)
        return
    async with engine.begin() as conn:
        for mart in MARTS:
            started = time.monotonic()
            await conn.execute(text(f"REFRESH MATERIALIZED VIEW mart.{mart.name}"))
            log.info("mart.%s refreshed in %.1fs", mart.name, time.monotonic() - started)
