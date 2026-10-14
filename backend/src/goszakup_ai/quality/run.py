from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncEngine

from goszakup_ai.db.models import DqCheckResult
from goszakup_ai.quality.checks import CHECKS, FRESHNESS_SQL, check_sql


@dataclass(frozen=True)
class CheckResult:
    name: str
    entity: str
    severity: str
    description: str
    failed: int
    total: int
    sample: list[Any]

    @property
    def share(self) -> float:
        return self.failed / self.total if self.total else 0.0


async def run_checks(engine: AsyncEngine, run_id: int | None = None) -> list[CheckResult]:
    results: list[CheckResult] = []
    async with engine.begin() as conn:
        for check in CHECKS:
            row = (await conn.execute(text(check_sql(check)))).one()
            results.append(
                CheckResult(
                    check.name,
                    check.entity,
                    check.severity,
                    check.description,
                    row.failed,
                    row.total,
                    list(row.sample),
                )
            )
        fresh = (await conn.execute(text(FRESHNESS_SQL))).one()
        results.append(
            CheckResult(
                "sync_older_than_24h",
                "sync_run",
                "error",
                "Последняя успешная синхронизация старше 24 часов (в sample — часы)",
                fresh.failed,
                fresh.total,
                [float(x) for x in fresh.sample],
            )
        )
        await conn.execute(
            insert(DqCheckResult),
            [
                {
                    "run_id": run_id,
                    "check_name": r.name,
                    "entity": r.entity,
                    "severity": r.severity,
                    "failed_count": r.failed,
                    "total_count": r.total,
                    "sample": r.sample,
                }
                for r in results
            ],
        )
    return results
