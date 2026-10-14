from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from goszakup_ai.db.models import Lot, LotPlanPoint, RawObject, RefUnit
from goszakup_ai.ingestion.mappers import lot_rows
from goszakup_ai.ingestion.store import replace_children, save_raw, upsert


async def test_upsert_inserts_updates_and_dedupes(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions.begin() as session:
        await upsert(session, RefUnit, [{"code": "796", "name_ru": "штука"}])
    async with sessions.begin() as session:
        written = await upsert(
            session,
            RefUnit,
            [{"code": "796", "name_ru": "Штука"}, {"code": "796", "name_ru": "Штука (шт)"}],
        )

    assert written == 1
    async with sessions() as session:
        assert await session.scalar(select(RefUnit.name_ru)) == "Штука (шт)"


async def test_replace_children_drops_stale_links(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    first = lot_rows({"id": 1, "pointList": [10, 11]})
    second = lot_rows({"id": 1, "pointList": [11, 12]})

    for bundle in (first, second):
        async with sessions.begin() as session:
            await upsert(session, Lot, [bundle.lot])
            await replace_children(session, LotPlanPoint, "lot_id", [1], bundle.plan_points)

    async with sessions() as session:
        points = await session.scalars(select(LotPlanPoint.plan_point_id).order_by("plan_point_id"))
        assert list(points) == [11, 12]


async def test_save_raw_tracks_payload_changes(sessions: async_sessionmaker[AsyncSession]) -> None:
    item = {"id": 5, "nameRu": "Лот", "indexDate": "2026-10-01 10:00:00"}
    async with sessions.begin() as session:
        await save_raw(session, "lot", [item])
    async with sessions() as session:
        first_hash = await session.scalar(select(RawObject.payload_hash))

    async with sessions.begin() as session:
        await save_raw(session, "lot", [{**item, "nameRu": "Лот 2"}])
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(RawObject)) == 1
        assert await session.scalar(select(RawObject.payload_hash)) != first_hash
