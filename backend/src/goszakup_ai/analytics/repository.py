from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from goszakup_ai.analytics.fair_price import (
    FairPriceParams,
    FairPriceResult,
    PriceAdjusters,
    PriceObs,
    Target,
    assess,
)
from goszakup_ai.transform.text import desc_text_sql

POOL_LINKS = ("direct", "version", "lot", "customer_code")

_KATO_COLUMNS = """
    rg.code AS region_code, rg.name_ru AS region_name,
    lc.code AS locality_code, lc.name_ru AS locality_name
"""
_KATO_JOINS = """
    LEFT JOIN core.ref_kato rg ON rg.code = left(k.kato_code, 2) || '0000000'
    LEFT JOIN core.ref_kato lc ON lc.code = CASE
        WHEN left(k.kato_code, 2) IN ('71', '75', '79') THEN left(k.kato_code, 2) || '0000000'
        ELSE left(k.kato_code, 4) || '00000' END
"""

FIND_LOT_SQL = """
SELECT id FROM core.lot
WHERE lot_number = :ref OR id::text = :ref
ORDER BY id DESC LIMIT 1
"""

CONTRACT_TARGETS_SQL = """
SELECT unit_id, lot_id, lot_number, contract_id, chain_id, trd_buy_id, customer_bin,
       customer_name, coalesce(item_name, enstru_name) AS item_name, enstru_code,
       unit_norm_code, unit_norm_name AS unit_name, unit_dimension, unit_comparable, plan_link,
       price_norm AS price, quantity_norm AS quantity, sign_date::date AS date,
       region_code, region_name, locality_code, locality_name,
       desc_key, subclass, subclass_label
FROM mart.price_observation
WHERE {where} AND enstru_code IS NOT NULL AND price_norm > 0 AND sign_date IS NOT NULL
"""

LOT_TARGET_SQL = f"""
SELECT l.id AS lot_id, l.lot_number, l.trd_buy_id, l.customer_bin, s.name_ru AS customer_name,
       coalesce(pp.name_ru, l.name_ru) AS item_name, pp.enstru_code,
       coalesce(n.canonical_code, pp.unit_code) AS unit_norm_code, u.name_ru AS unit_name,
       coalesce(n.dimension, 'unknown') AS unit_dimension, coalesce(n.comparable, true)
           AS unit_comparable,
       l.amount / nullif(l.quantity * coalesce(n.factor, 1), 0) AS price,
       l.quantity * coalesce(n.factor, 1) AS quantity,
       coalesce(t.publish_date, l.last_update_date)::date AS date,
       {_KATO_COLUMNS},
       md5({desc_text_sql("pp.extra_desc_ru")}) AS desc_key,
       sc.subclass, sc.label AS subclass_label
FROM core.lot l
LEFT JOIN core.trd_buy t ON t.id = l.trd_buy_id
LEFT JOIN core.subject s ON s.pid = l.customer_pid
LEFT JOIN LATERAL (
    SELECT p.* FROM core.lot_plan_point lp JOIN core.plan_point p ON p.id = lp.plan_point_id
    WHERE lp.lot_id = l.id ORDER BY p.amount DESC NULLS LAST LIMIT 1
) pp ON true
LEFT JOIN core.ref_unit_norm n ON n.unit_code = pp.unit_code
LEFT JOIN core.ref_unit u ON u.code = coalesce(n.canonical_code, pp.unit_code)
LEFT JOIN LATERAL (
    SELECT pk.kato_code FROM core.plan_point_kato pk
    WHERE pk.plan_point_id = pp.id ORDER BY pk.quantity DESC NULLS LAST LIMIT 1
) kp ON true
CROSS JOIN LATERAL (SELECT coalesce(kp.kato_code, s.kato_list[1]) AS kato_code) k
{_KATO_JOINS}
LEFT JOIN core.item_subclass sc
       ON sc.enstru_code = pp.enstru_code
      AND sc.text_key = md5({desc_text_sql("pp.extra_desc_ru")})
WHERE l.id = :lot_id
"""

POOL_SQL = """
SELECT o.unit_id, o.contract_id, o.chain_id, o.customer_bin, o.customer_name,
       o.sign_date::date AS sign_date, o.price_norm AS price, o.quantity_norm AS quantity,
       o.region_code, o.region_name, o.locality_code, o.trd_buy_id, o.subclass,
       1 - (it.embedding <=> te.embedding) AS similarity
FROM mart.price_observation o
LEFT JOIN core.item_text it ON it.text_key = o.desc_key
LEFT JOIN core.item_text te ON te.text_key = CAST(:desc_key AS text)
WHERE o.enstru_code = :enstru_code AND o.unit_norm_code = :unit_norm_code
  AND o.unit_comparable AND o.plan_link = ANY(:links)
  AND o.price_norm > 0 AND o.quantity_norm > 0
"""


class NotFoundError(LookupError):
    pass


async def load_adjusters(session: AsyncSession) -> PriceAdjusters:
    cpi = {
        r.month: float(r.idx)
        for r in await session.execute(text("SELECT month, idx FROM mart.cpi_index"))
    }
    region_k = {
        r.region_code: float(r.k)
        for r in await session.execute(text("SELECT region_code, k FROM mart.region_price_index"))
    }
    season = {
        r.month: float(r.factor)
        for r in await session.execute(text("SELECT month, factor FROM mart.season_index"))
    }
    return PriceAdjusters(cpi=cpi, region_k=region_k, season=season)


async def load_pool(session: AsyncSession, target: Target) -> list[PriceObs]:
    rows = await session.execute(
        text(POOL_SQL),
        {
            "enstru_code": target.enstru_code,
            "unit_norm_code": target.unit_norm_code,
            "desc_key": target.desc_key,
            "links": list(POOL_LINKS),
        },
    )
    return [
        PriceObs(
            unit_id=r.unit_id,
            contract_id=r.contract_id,
            chain_id=r.chain_id,
            customer_bin=r.customer_bin,
            customer_name=r.customer_name,
            sign_date=r.sign_date,
            price=float(r.price),
            quantity=float(r.quantity),
            region_code=r.region_code,
            region_name=r.region_name,
            locality_code=r.locality_code,
            trd_buy_id=r.trd_buy_id,
            subclass=r.subclass,
            similarity=float(r.similarity) if r.similarity is not None else None,
        )
        for r in rows
    ]


async def find_lot_id(session: AsyncSession, ref: str | int) -> int:
    lot_id = await session.scalar(text(FIND_LOT_SQL), {"ref": str(ref).strip()})
    if lot_id is None:
        raise NotFoundError(f"Лот {ref} не найден")
    return int(lot_id)


async def lot_targets(session: AsyncSession, lot_id: int) -> list[Target]:
    rows = (
        (
            await session.execute(
                text(CONTRACT_TARGETS_SQL.format(where="lot_id = :lot_id")), {"lot_id": lot_id}
            )
        )
        .mappings()
        .all()
    )
    targets = [Target(source="contract_unit", **_target_fields(r)) for r in rows]
    if targets:
        return targets
    row = (await session.execute(text(LOT_TARGET_SQL), {"lot_id": lot_id})).mappings().first()
    if row is None or row["enstru_code"] is None or not row["price"] or row["date"] is None:
        raise NotFoundError(f"По лоту {lot_id} нет данных о цене, единице или коде ЕНС ТРУ")
    return [Target(source="lot", plan_link="lot_announced", **_target_fields(row))]


async def unit_target(session: AsyncSession, unit_id: int) -> Target:
    row = (
        (
            await session.execute(
                text(CONTRACT_TARGETS_SQL.format(where="unit_id = :unit_id")), {"unit_id": unit_id}
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise NotFoundError(f"Позиция договора {unit_id} не найдена")
    return Target(source="contract_unit", **_target_fields(row))


def _target_fields(row: Any) -> dict[str, Any]:
    data: dict[str, Any] = dict(row)
    data.pop("unit_comparable", None)
    data["price"] = float(data["price"])
    if data.get("quantity") is not None:
        data["quantity"] = float(data["quantity"])
    if not isinstance(data.get("date"), date):
        data["date"] = date.today()
    return data


async def fair_price_for_lot(
    session: AsyncSession, lot_ref: str | int, params: FairPriceParams | None = None
) -> list[FairPriceResult]:
    lot_id = await find_lot_id(session, lot_ref)
    adjusters = await load_adjusters(session)
    results = []
    for target in await lot_targets(session, lot_id):
        pool = await load_pool(session, target)
        results.append(assess(target, pool, adjusters, params))
    return results


async def fair_price_for_unit(
    session: AsyncSession, unit_id: int, params: FairPriceParams | None = None
) -> FairPriceResult:
    target = await unit_target(session, unit_id)
    pool = await load_pool(session, target)
    return assess(target, pool, await load_adjusters(session), params)
