from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from functools import partial
from typing import Any

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from goszakup_ai.db.models import (
    Contract,
    ContractUnit,
    Lot,
    LotPlanPoint,
    PlanPoint,
    PlanPointKato,
    RawObject,
    RefDict,
    RefEnstru,
    RefKato,
    RefUnit,
    ScopeBin,
    Subject,
    SyncRun,
    SyncState,
    TrdBuy,
)
from goszakup_ai.db.models.meta import SYNC_LOCK_CLASS
from goszakup_ai.db.session import make_sessionmaker
from goszakup_ai.ingestion.mappers import (
    Row,
    contract_rows,
    lot_rows,
    parse_dt,
    plan_point_rows,
    ref_dict_row,
    ref_kato_row,
    ref_unit_row,
    subject_row,
    trd_buy_row,
)
from goszakup_ai.ingestion.queries import (
    BENCHMARK_CONTRACT_QUERY,
    CONTRACT,
    LOT,
    PLAN_POINT,
    SUBJECT,
    TRD_BUY,
    EntitySpec,
)
from goszakup_ai.ingestion.store import replace_children, save_raw, upsert
from goszakup_ai.ows import OwsClient

log = logging.getLogger(__name__)

LOTS_UPDATED_SINCE = "2023-07-01"
OPEN_END = "2100-01-01"
ID_BATCH = 200
GAP_RETRY_DAYS = 7
REPLAY_BATCH = 2000
BENCHMARK_ENTITY = "contract_bench"

BENCHMARK_CODES_SQL = """
    WITH spend AS (
        SELECT enstru_code, sum(amount_kzt) AS amount
        FROM mart.price_observation
        WHERE in_scope AND unit_comparable AND enstru_code IS NOT NULL AND amount_kzt > 0
        GROUP BY enstru_code
    ),
    ranked AS (
        SELECT enstru_code, amount,
               sum(amount) OVER (ORDER BY amount DESC, enstru_code) / sum(amount) OVER () AS cum
        FROM spend
    )
    SELECT enstru_code FROM ranked
    WHERE cum - amount / (SELECT sum(amount) FROM spend) < :coverage
    ORDER BY cum
"""

REF_DICTS = {
    "ref_buy_status": "buy_status",
    "ref_lots_status": "lot_status",
    "ref_contract_status": "contract_status",
    "ref_pln_point_status": "plan_point_status",
    "ref_subject_type": "subject_type",
    "ref_trade_methods": "trade_method",
}

GAP_QUERIES = {
    LOT.name: """
        SELECT DISTINCT cu.lot_id AS id FROM core.contract_unit cu
        LEFT JOIN core.lot l ON l.id = cu.lot_id
        WHERE cu.lot_id IS NOT NULL AND l.id IS NULL
    """,
    PLAN_POINT.name: """
        SELECT DISTINCT cu.plan_point_id AS id FROM core.contract_unit cu
        LEFT JOIN core.plan_point p ON p.id = cu.plan_point_id
        WHERE cu.plan_point_id IS NOT NULL AND p.id IS NULL
    """,
    TRD_BUY.name: """
        SELECT DISTINCT x.id FROM (
            SELECT trd_buy_id AS id FROM core.lot
            UNION SELECT trd_buy_id FROM core.contract
        ) x
        LEFT JOIN core.trd_buy t ON t.id = x.id
        WHERE x.id IS NOT NULL AND t.id IS NULL
    """,
}


async def apply_subjects(session: AsyncSession, items: Sequence[Row]) -> None:
    await upsert(session, Subject, [subject_row(i) for i in items])


async def apply_plan_points(session: AsyncSession, items: Sequence[Row]) -> None:
    bundles = [plan_point_rows(i) for i in items]
    await upsert(session, PlanPoint, [b.plan_point for b in bundles])
    await replace_children(
        session,
        PlanPointKato,
        "plan_point_id",
        [b.plan_point["id"] for b in bundles],
        [k for b in bundles for k in b.katos],
    )
    await upsert(session, RefEnstru, [b.enstru for b in bundles if b.enstru])


async def apply_contracts(session: AsyncSession, items: Sequence[Row]) -> None:
    bundles = [contract_rows(i) for i in items]
    await upsert(session, Subject, [s for b in bundles for s in b.subjects])
    await upsert(session, Contract, [b.contract for b in bundles])
    await upsert(session, ContractUnit, [u for b in bundles for u in b.units])


async def apply_benchmark_contracts(session: AsyncSession, items: Sequence[Row]) -> None:
    plans = [u["Plans"] for c in items for u in c.get("ContractUnits") or [] if u.get("Plans")]
    await apply_contracts(session, items)
    await apply_plan_points(session, plans)


def keep_units(contract: Row, enstru_code: str) -> Row:
    units = [
        u
        for u in contract.get("ContractUnits") or []
        if enstru_code in (u.get("refEnstruCode") or [])
    ]
    return {**contract, "ContractUnits": units}


async def apply_lots(session: AsyncSession, items: Sequence[Row]) -> None:
    bundles = [lot_rows(i) for i in items]
    await upsert(session, Lot, [b.lot for b in bundles])
    await replace_children(
        session,
        LotPlanPoint,
        "lot_id",
        [b.lot["id"] for b in bundles],
        [p for b in bundles for p in b.plan_points],
    )


async def apply_trd_buys(session: AsyncSession, items: Sequence[Row]) -> None:
    await upsert(session, TrdBuy, [trd_buy_row(i) for i in items])


APPLY: dict[str, Callable[[AsyncSession, Sequence[Row]], Awaitable[None]]] = {
    SUBJECT.name: apply_subjects,
    PLAN_POINT.name: apply_plan_points,
    CONTRACT.name: apply_contracts,
    LOT.name: apply_lots,
    TRD_BUY.name: apply_trd_buys,
    BENCHMARK_ENTITY: apply_benchmark_contracts,
}


class Ingestor:
    def __init__(
        self,
        client: OwsClient,
        engine: AsyncEngine,
        *,
        years: Sequence[int],
        concurrency: int,
    ) -> None:
        self.client = client
        self.engine = engine
        self.sessions = make_sessionmaker(engine)
        self._run_lock: AsyncConnection | None = None
        self.years = tuple(years)
        self.stats: Counter[str] = Counter()
        self._semaphore = asyncio.Semaphore(concurrency)

    async def load_refs(self) -> None:
        await self._load_ref("ref_units", RefUnit, ref_unit_row, key="code")
        await self._load_ref("ref_kato", RefKato, ref_kato_row, key="code")
        for source, name in REF_DICTS.items():
            await self._load_ref(source, RefDict, partial(ref_dict_row, name), key="id")

    async def load_scope(self, bins: Sequence[str], *, full: bool = False) -> None:
        await self._load_subjects(bins)
        results = await asyncio.gather(
            *(self._load_bin(b, full=full) for b in bins), return_exceptions=True
        )
        failed = [(b, r) for b, r in zip(bins, results, strict=True) if isinstance(r, Exception)]
        for bin_, error in failed:
            log.error("bin %s failed: %r", bin_, error)
        await self.fill_gaps()
        if failed:
            raise RuntimeError(f"{len(failed)} of {len(bins)} BINs failed")

    async def load_benchmark(
        self, *, coverage: float, max_contracts: int, full: bool = False
    ) -> None:
        async with self.sessions() as session:
            codes = list(
                (await session.execute(text(BENCHMARK_CODES_SQL), {"coverage": coverage})).scalars()
            )
        log.info(
            "benchmark: %d ENSTRU codes cover %.0f%% of goods spend", len(codes), 100 * coverage
        )
        done = 0

        async def one(code: str) -> None:
            nonlocal done
            async with self._semaphore:
                await self._load_benchmark_code(code, max_contracts=max_contracts, full=full)
            done += 1
            if done % 50 == 0 or done == len(codes):
                log.info("benchmark progress: %d/%d codes", done, len(codes))

        results = await asyncio.gather(*(one(c) for c in codes), return_exceptions=True)
        failed = [(c, r) for c, r in zip(codes, results, strict=True) if isinstance(r, Exception)]
        for code, error in failed[:10]:
            log.error("benchmark %s failed: %r", code, error)
        if failed:
            raise RuntimeError(f"{len(failed)} of {len(codes)} benchmark codes failed")

    async def _load_benchmark_code(self, code: str, *, max_contracts: int, full: bool) -> None:
        for year in self.years:
            await self._load_benchmark_code_year(code, year, max_contracts=max_contracts, full=full)

    async def _load_benchmark_code_year(
        self, code: str, year: int, *, max_contracts: int, full: bool
    ) -> None:
        scope_key = f"bench:{code}:{year}"
        since = None if full else await self._last_index_date(BENCHMARK_ENTITY, scope_key)
        flt: dict[str, Any] = {"signDate": [f"{year}-01-01", f"{year}-12-31"]}
        if since is not None:
            flt["indexDate"] = [since.strftime("%Y-%m-%d %H:%M:%S"), OPEN_END]
        variables = {
            "filter": flt,
            "units": {"refEnstruCode": [code]},
            "limit": min(200, max_contracts),
        }
        total = 0
        max_index: datetime | None = None
        async for page in self.client.graphql_pages(
            BENCHMARK_CONTRACT_QUERY, "Contract", variables
        ):
            items = [keep_units(c, code) for c in page]
            async with self.sessions.begin() as session:
                await save_raw(session, BENCHMARK_ENTITY, items)
                await apply_benchmark_contracts(session, items)
            total += len(items)
            max_index = max(
                [d for d in (parse_dt(i.get("indexDate")) for i in items) if d]
                + ([max_index] if max_index else []),
                default=None,
            )
            if total >= max_contracts:
                break
        self.stats[BENCHMARK_ENTITY] += total
        await self._save_state(BENCHMARK_ENTITY, scope_key, max_index or since, total)

    async def fill_gaps(self) -> None:
        for spec in (LOT, PLAN_POINT, TRD_BUY):
            gaps = GAP_QUERIES[spec.name]
            async with self.sessions() as session:
                ids = list(
                    (
                        await session.execute(
                            text(
                                f"SELECT g.id FROM ({gaps}) g WHERE NOT EXISTS ("
                                "SELECT 1 FROM meta.gap_miss m WHERE m.entity = :entity "
                                "AND m.id = g.id "
                                "AND m.checked_at > now() - make_interval(days => :days))"
                            ),
                            {"entity": spec.name, "days": GAP_RETRY_DAYS},
                        )
                    ).scalars()
                )
            loaded = 0
            for start in range(0, len(ids), ID_BATCH):
                loaded += (await self._fetch(spec, {"id": ids[start : start + ID_BATCH]}))[0]
            if ids:
                async with self.sessions.begin() as session:
                    await session.execute(
                        text(
                            "INSERT INTO meta.gap_miss (entity, id) "
                            f"SELECT :entity, g.id FROM ({gaps}) g WHERE g.id = ANY(:ids) "
                            "ON CONFLICT (entity, id) DO UPDATE SET checked_at = now()"
                        ),
                        {"entity": spec.name, "ids": ids},
                    )
            self.stats[f"gap_{spec.name}"] += loaded
            log.info("gap fill %s: %d missing, %d loaded", spec.name, len(ids), loaded)

    async def replay(self, entities: Sequence[str]) -> None:
        for entity in entities:
            apply = APPLY[entity]
            last_key = ""
            total = 0
            while True:
                async with self.sessions.begin() as session:
                    rows = (
                        await session.execute(
                            select(RawObject.source_key, RawObject.payload)
                            .where(RawObject.entity == entity, RawObject.source_key > last_key)
                            .order_by(RawObject.source_key)
                            .limit(REPLAY_BATCH)
                        )
                    ).all()
                    if not rows:
                        break
                    await apply(session, [r.payload for r in rows])
                last_key = rows[-1].source_key
                total += len(rows)
            self.stats[f"replay_{entity}"] += total
            log.info("replay %s: %d rows", entity, total)

    async def start_run(self, command: str) -> int:
        await self._close_stale_runs()
        conn = await self.engine.connect()
        run_id = (
            await conn.execute(insert(SyncRun).values(command=command).returning(SyncRun.id))
        ).scalar_one()
        await conn.execute(
            text("SELECT pg_advisory_lock(:c, CAST(:id AS int))"),
            {"c": SYNC_LOCK_CLASS, "id": run_id},
        )
        await conn.commit()
        self._run_lock = conn
        return run_id

    async def _close_stale_runs(self) -> None:
        async with self.engine.connect() as conn:
            running = (
                await conn.execute(select(SyncRun.id).where(SyncRun.status == "running"))
            ).scalars()
            stale = [
                run_id
                for run_id in running
                if await conn.scalar(
                    text("SELECT pg_try_advisory_lock(:c, CAST(:id AS int))"),
                    {"c": SYNC_LOCK_CLASS, "id": run_id},
                )
            ]
            if stale:
                await conn.execute(
                    update(SyncRun)
                    .where(SyncRun.id.in_(stale))
                    .values(
                        status="interrupted",
                        finished_at=func.now(),
                        error="process stopped before finishing",
                    )
                )
            await conn.execute(text("SELECT pg_advisory_unlock_all()"))
            await conn.commit()
        for run_id in stale:
            log.warning("sync run %d was interrupted earlier", run_id)

    async def _release_run_lock(self) -> None:
        conn, self._run_lock = self._run_lock, None
        if conn is None:
            return
        try:
            await conn.execute(text("SELECT pg_advisory_unlock_all()"))
            await conn.commit()
        except Exception:
            await conn.invalidate()
        finally:
            await conn.close()

    async def finish_run(self, run_id: int, status: str, error: str | None = None) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                update(SyncRun)
                .where(SyncRun.id == run_id)
                .values(
                    status=status,
                    finished_at=func.now(),
                    stats=dict(self.stats),
                    error=error,
                )
            )
        await self._release_run_lock()

    async def _load_ref(
        self,
        source: str,
        model: type[DeclarativeBase],
        mapper: Callable[[Row], Row],
        *,
        key: str,
    ) -> None:
        total = 0
        async for page in self.client.rest_pages(f"/v3/refs/{source}"):
            items = page.get("items") or []
            async with self.sessions.begin() as session:
                await save_raw(session, source, items, key=key, index_field=None)
                await upsert(session, model, [mapper(i) for i in items])
            total += len(items)
        self.stats[source] += total
        log.info("%s: %d rows", source, total)

    async def _load_subjects(self, bins: Sequence[str]) -> None:
        for bin_ in bins:
            await self._fetch(SUBJECT, {"bin": bin_})
        async with self.sessions.begin() as session:
            rows = await session.execute(
                select(Subject.bin, Subject.name_ru).where(Subject.bin.in_(bins))
            )
            names: dict[str | None, str | None] = {b: n for b, n in rows.tuples()}
            await upsert(session, ScopeBin, [{"bin": b, "name_ru": names.get(b)} for b in bins])

    async def _load_bin(self, bin_: str, *, full: bool) -> None:
        async with self._semaphore:
            await self._sync(
                PLAN_POINT, bin_, {"subjectBiin": bin_, "plnPointYear": list(self.years)}, full
            )
            for year in self.years:
                key = f"{bin_}:{year}"
                await self._sync(CONTRACT, key, {"customerBin": bin_, "finYear": year}, full)
                await self._sync(TRD_BUY, key, {"orgBin": bin_, "finYear": year}, full)
            await self._sync(
                LOT,
                bin_,
                {"customerBin": bin_, "lastUpdateDate": [LOTS_UPDATED_SINCE, OPEN_END]},
                full,
            )

    async def _sync(
        self, spec: EntitySpec, scope_key: str, base_filter: dict[str, Any], full: bool
    ) -> None:
        since = None if full else await self._last_index_date(spec.name, scope_key)
        flt = dict(base_filter)
        if since is not None:
            flt["indexDate"] = [since.strftime("%Y-%m-%d %H:%M:%S"), OPEN_END]
        total, max_index = await self._fetch(spec, flt)
        await self._save_state(spec.name, scope_key, max_index or since, total)
        mode = "incremental" if since else "full"
        log.info("%s %s: %d rows (%s)", spec.name, scope_key, total, mode)

    async def _fetch(self, spec: EntitySpec, flt: dict[str, Any]) -> tuple[int, datetime | None]:
        total = 0
        max_index: datetime | None = None
        async for items in self.client.graphql_pages(spec.query, spec.root_field, {"filter": flt}):
            async with self.sessions.begin() as session:
                await save_raw(session, spec.name, items, key=spec.key)
                await APPLY[spec.name](session, items)
            total += len(items)
            for item in items:
                index_date = parse_dt(item.get("indexDate"))
                if index_date and (max_index is None or index_date > max_index):
                    max_index = index_date
        self.stats[spec.name] += total
        return total, max_index

    async def _last_index_date(self, entity: str, scope_key: str) -> datetime | None:
        async with self.sessions() as session:
            state = await session.get(SyncState, (entity, scope_key))
            return state.last_index_date if state else None

    async def _save_state(
        self, entity: str, scope_key: str, last_index_date: datetime | None, rows: int
    ) -> None:
        async with self.sessions.begin() as session:
            await upsert(
                session,
                SyncState,
                [
                    {
                        "entity": entity,
                        "scope_key": scope_key,
                        "last_index_date": last_index_date,
                        "last_success_at": datetime.now(UTC),
                        "rows_loaded": rows,
                    }
                ],
            )
