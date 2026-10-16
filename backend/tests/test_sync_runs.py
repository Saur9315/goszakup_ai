from typing import cast

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from goszakup_ai.db.models import SyncRun
from goszakup_ai.db.models.meta import SYNC_LOCK_CLASS
from goszakup_ai.ingestion.pipeline import Ingestor
from goszakup_ai.ows import OwsClient


async def test_start_run_closes_only_dead_runs(db_engine: AsyncEngine) -> None:
    ingestor = Ingestor(cast(OwsClient, None), db_engine, years=[2025], concurrency=1)
    async with ingestor.sessions.begin() as session:
        dead, alive = SyncRun(command="dead"), SyncRun(command="alive")
        session.add_all([dead, alive])
    async with db_engine.connect() as holder:
        await holder.execute(
            text("SELECT pg_advisory_lock(:c, CAST(:id AS int))"),
            {"c": SYNC_LOCK_CLASS, "id": alive.id},
        )
        await holder.commit()

        run_id = await ingestor.start_run("sync")
        await ingestor.finish_run(run_id, "ok")

        async with ingestor.sessions() as session:
            status = dict((await session.execute(select(SyncRun.command, SyncRun.status))).all())
        await holder.execute(text("SELECT pg_advisory_unlock_all()"))
        await holder.commit()

    assert status == {"dead": "interrupted", "alive": "running", "sync": "ok"}
