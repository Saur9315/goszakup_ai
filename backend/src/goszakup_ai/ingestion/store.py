from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Table, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from goszakup_ai.db.models import RawObject
from goszakup_ai.ingestion.mappers import Row, parse_dt

# asyncpg allows at most 32767 bind parameters per statement
_MAX_PARAMS = 30_000


def _table(model: type[DeclarativeBase]) -> Table:
    table = model.__table__
    assert isinstance(table, Table)
    return table


def _dedupe(rows: Iterable[Row], key: Sequence[str]) -> list[Row]:
    unique: dict[tuple[Any, ...], Row] = {}
    for row in rows:
        unique[tuple(row[k] for k in key)] = row
    # stable key order keeps concurrent upserts from deadlocking on shared rows
    return [unique[k] for k in sorted(unique)]


async def upsert(
    session: AsyncSession,
    model: type[DeclarativeBase],
    rows: Iterable[Row],
    *,
    update: bool = True,
) -> int:
    table = _table(model)
    key = [c.name for c in table.primary_key.columns]
    batch = _dedupe(rows, key)
    if not batch:
        return 0
    columns = list(batch[0])
    chunk = max(1, _MAX_PARAMS // len(columns))
    for start in range(0, len(batch), chunk):
        stmt = pg_insert(table).values(batch[start : start + chunk])
        to_update = {c: stmt.excluded[c] for c in columns if c not in key}
        if update and to_update:
            stmt = stmt.on_conflict_do_update(index_elements=key, set_=to_update)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=key)
        await session.execute(stmt)
    return len(batch)


async def replace_children(
    session: AsyncSession,
    model: type[DeclarativeBase],
    parent_column: str,
    parent_ids: Sequence[int],
    rows: Iterable[Row],
) -> int:
    if not parent_ids:
        return 0
    table = _table(model)
    await session.execute(delete(table).where(table.c[parent_column].in_(parent_ids)))
    return await upsert(session, model, rows)


def payload_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def save_raw(
    session: AsyncSession,
    entity: str,
    items: Sequence[Row],
    *,
    key: str = "id",
    index_field: str | None = "indexDate",
) -> int:
    now = datetime.now(UTC)
    rows = [
        {
            "entity": entity,
            "source_key": str(item[key]),
            "payload": item,
            "payload_hash": payload_hash(item),
            "index_date": parse_dt(item.get(index_field)) if index_field else None,
            "fetched_at": now,
        }
        for item in items
    ]
    return await upsert(session, RawObject, rows)
