from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated

import typer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from goszakup_ai.core.config import get_settings
from goszakup_ai.core.scope import TARGET_BINS, TARGET_YEARS
from goszakup_ai.db.session import make_engine, make_sessionmaker
from goszakup_ai.ingestion.pipeline import Ingestor
from goszakup_ai.marts.build import build_marts, refresh_marts
from goszakup_ai.ows import OwsClient
from goszakup_ai.quality.run import CheckResult, run_checks

app = typer.Typer(no_args_is_help=True, add_completion=False)
ingest_app = typer.Typer(no_args_is_help=True)
app.add_typer(ingest_app, name="ingest", help="Load data from OWS v3 into PostgreSQL")
marts_app = typer.Typer(no_args_is_help=True)
app.add_typer(marts_app, name="marts", help="Analytical marts (materialized views)")
dq_app = typer.Typer(no_args_is_help=True)
app.add_typer(dq_app, name="dq", help="Data quality checks")

STATUS_TABLES = (
    "core.subject",
    "core.plan_point",
    "core.plan_point_kato",
    "core.trd_buy",
    "core.lot",
    "core.lot_plan_point",
    "core.contract",
    "core.contract_unit",
    "core.ref_enstru",
    "core.ref_unit",
    "core.ref_kato",
    "core.ref_dict",
    "raw.ows_object",
)


@app.callback()
def _setup_logging(verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def _ingestor() -> AsyncIterator[Ingestor]:
    settings = get_settings()
    engine = make_engine(settings)
    try:
        async with OwsClient(settings) as client:
            yield Ingestor(
                client,
                make_sessionmaker(engine),
                years=TARGET_YEARS,
                concurrency=settings.ingest_concurrency,
            )
    finally:
        await engine.dispose()


async def _run(command: str, action: Callable[[Ingestor], Awaitable[None]]) -> int:
    async with _ingestor() as ingestor:
        run_id = await ingestor.start_run(command)
        try:
            await action(ingestor)
        except BaseException as e:
            await ingestor.finish_run(run_id, "failed", error=repr(e))
            raise
        await ingestor.finish_run(run_id, "ok")
        typer.echo(f"run {run_id} ok: {dict(ingestor.stats)}")
        return run_id


def _print_checks(results: list[CheckResult]) -> None:
    for r in results:
        mark = (
            "ok" if not r.failed else {"error": "FAIL", "warning": "warn"}.get(r.severity, "info")
        )
        typer.echo(
            f"{mark:<5}{r.severity:<8}{r.name:<36}{r.failed:>8,} / {r.total:<9,}"
            f"{100 * r.share:6.1f}%  {r.description}"
        )


@app.command("sync", help="Scheduled job: incremental ingest, refresh marts, run DQ checks")
def sync() -> None:
    async def job() -> None:
        run_id = await _run("ingest scope (sync)", lambda i: i.load_scope(list(TARGET_BINS)))
        engine = make_engine(get_settings())
        try:
            await refresh_marts(engine)
            _print_checks(await run_checks(engine, run_id))
        finally:
            await engine.dispose()

    asyncio.run(job())


@dq_app.command("run", help="Run data quality checks and store results")
def dq_run() -> None:
    async def job(engine: AsyncEngine) -> None:
        _print_checks(await run_checks(engine))

    asyncio.run(_with_engine(job))


@ingest_app.command("refs", help="Units, KATO, statuses, trade methods")
def ingest_refs() -> None:
    asyncio.run(_run("ingest refs", lambda i: i.load_refs()))


@ingest_app.command("scope", help="Plans, contracts, lots and announcements of the target BINs")
def ingest_scope(
    bins: Annotated[list[str] | None, typer.Option("--bin", help="Limit to these BINs")] = None,
    full: Annotated[bool, typer.Option("--full", help="Ignore saved sync state")] = False,
) -> None:
    selected = bins or list(TARGET_BINS)
    command = f"ingest scope{' --full' if full else ''} ({len(selected)} bins)"
    asyncio.run(_run(command, lambda i: i.load_scope(selected, full=full)))


@ingest_app.command("benchmark", help="Contracts of all customers for the top ENSTRU codes")
def ingest_benchmark(
    coverage: Annotated[
        float, typer.Option(help="Share of goods spend the codes must cover")
    ] = 0.95,
    max_contracts: Annotated[int, typer.Option(help="Most recent contracts per code")] = 200,
    full: Annotated[bool, typer.Option("--full", help="Ignore saved sync state")] = False,
) -> None:
    command = f"ingest benchmark coverage={coverage} max={max_contracts}"
    asyncio.run(
        _run(
            command,
            lambda i: i.load_benchmark(coverage=coverage, max_contracts=max_contracts, full=full),
        )
    )


@ingest_app.command("replay", help="Rebuild core tables from raw payloads without calling the API")
def ingest_replay(
    entities: Annotated[
        list[str] | None,
        typer.Option("--entity", help="plan_point, lot, contract, trd_buy, subject"),
    ] = None,
) -> None:
    selected = entities or ["subject", "plan_point", "lot", "trd_buy", "contract"]
    asyncio.run(_run(f"ingest replay {' '.join(selected)}", lambda i: i.replay(selected)))


@marts_app.command("build", help="Drop and recreate all marts")
def marts_build() -> None:
    asyncio.run(_with_engine(build_marts))


@marts_app.command("refresh", help="Refresh all marts with current core data")
def marts_refresh() -> None:
    asyncio.run(_with_engine(refresh_marts))


async def _with_engine(action: Callable[[AsyncEngine], Awaitable[None]]) -> None:
    engine = make_engine(get_settings())
    try:
        await action(engine)
    finally:
        await engine.dispose()


@app.command("status", help="Row counts and recent sync runs")
def status() -> None:
    asyncio.run(_status())


async def _status() -> None:
    engine = make_engine(get_settings())
    try:
        async with engine.connect() as conn:
            for table in STATUS_TABLES:
                count = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
                typer.echo(f"{table:<24} {count:>10,}")
            runs = await conn.execute(
                text(
                    "SELECT id, command, status, started_at, finished_at "
                    "FROM meta.sync_run ORDER BY id DESC LIMIT 5"
                )
            )
            typer.echo("\nrecent runs:")
            for run in runs:
                typer.echo(
                    f"  #{run.id} {run.status:<7} {run.started_at:%Y-%m-%d %H:%M} {run.command}"
                )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    app()
