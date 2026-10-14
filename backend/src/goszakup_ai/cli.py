from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated

import typer
from sqlalchemy import text

from goszakup_ai.core.config import get_settings
from goszakup_ai.core.scope import TARGET_BINS, TARGET_YEARS
from goszakup_ai.db.session import make_engine, make_sessionmaker
from goszakup_ai.ingestion.pipeline import Ingestor
from goszakup_ai.ows import OwsClient

app = typer.Typer(no_args_is_help=True, add_completion=False)
ingest_app = typer.Typer(no_args_is_help=True)
app.add_typer(ingest_app, name="ingest", help="Load data from OWS v3 into PostgreSQL")

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


async def _run(command: str, action: Callable[[Ingestor], Awaitable[None]]) -> None:
    async with _ingestor() as ingestor:
        run_id = await ingestor.start_run(command)
        try:
            await action(ingestor)
        except BaseException as e:
            await ingestor.finish_run(run_id, "failed", error=repr(e))
            raise
        await ingestor.finish_run(run_id, "ok")
        typer.echo(f"run {run_id} ok: {dict(ingestor.stats)}")


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
