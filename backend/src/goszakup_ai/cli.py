from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import typer
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from goszakup_ai.analytics.anomalies import price_anomalies, volume_anomalies
from goszakup_ai.analytics.cpi import fetch_cpi_from_taldau, read_cpi_csv
from goszakup_ai.analytics.repository import fair_price_for_lot
from goszakup_ai.core.config import get_settings
from goszakup_ai.core.scope import TARGET_BINS, TARGET_YEARS
from goszakup_ai.db.models import RefCpi
from goszakup_ai.db.session import make_engine, make_sessionmaker
from goszakup_ai.ingestion.pipeline import Ingestor
from goszakup_ai.ingestion.store import upsert
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
analyze_app = typer.Typer(no_args_is_help=True)
app.add_typer(analyze_app, name="analyze", help="Run analytics and print JSON results")

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
                engine,
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


async def _sync() -> None:
    run_id = await _run("ingest scope (sync)", lambda i: i.load_scope(list(TARGET_BINS)))
    engine = make_engine(get_settings())
    try:
        await refresh_marts(engine)
        _print_checks(await run_checks(engine, run_id))
    finally:
        await engine.dispose()


@app.command("sync", help="Scheduled job: incremental ingest, refresh marts, run DQ checks")
def sync() -> None:
    asyncio.run(_sync())


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
    max_contracts: Annotated[
        int, typer.Option(help="Most recent contracts per code and year")
    ] = 100,
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


async def _load_cpi(taldau: bool = True) -> None:
    async def job(engine: AsyncEngine) -> None:
        rows = read_cpi_csv()
        if taldau:
            latest = max(r["month"] for r in rows)
            try:
                fresh = [r for r in await fetch_cpi_from_taldau(latest) if r["month"] > latest]
            except Exception as e:
                fresh = []
                typer.echo(f"taldau unavailable, using bundled CSV only: {e!r}")
            rows += fresh
            typer.echo(f"taldau: {len(fresh)} new months")
        async with AsyncSession(engine) as session, session.begin():
            await upsert(session, RefCpi, rows)
        typer.echo(f"cpi: {len(rows)} months, {rows[0]['month']} .. {rows[-1]['month']}")

    await _with_engine(job)


@ingest_app.command("cpi", help="Monthly CPI: bundled CSV, then newer months from Taldau")
def ingest_cpi(
    taldau: Annotated[bool, typer.Option(help="Fetch months after the CSV from Taldau")] = True,
) -> None:
    asyncio.run(_load_cpi(taldau))


async def _analyze(
    action: Callable[[AsyncSession], Awaitable[BaseModel | list[BaseModel]]],
) -> None:
    async def job(engine: AsyncEngine) -> None:
        async with AsyncSession(engine) as session:
            result = await action(session)
        items = result if isinstance(result, list) else [result]
        for item in items:
            typer.echo(item.model_dump_json(indent=2))

    await _with_engine(job)


@analyze_app.command("fair-price", help="Fair Price of a lot (lot number like 54949500-ЗЦП4 or id)")
def analyze_fair_price(lot: str) -> None:
    asyncio.run(_analyze(lambda s: fair_price_for_lot(s, lot)))  # type: ignore[arg-type,return-value]


@analyze_app.command("price-anomalies", help="Prices deviating from the ENSTRU weighted average")
def analyze_price_anomalies(
    threshold: float = 0.3,
    direction: Annotated[str, typer.Option(help="above, below or both")] = "above",
    bin_: Annotated[str | None, typer.Option("--bin")] = None,
    year: int | None = None,
    enstru: str | None = None,
    confirm_z: float = 2.0,
    all_: Annotated[
        bool, typer.Option("--all", help="Include unconfirmed (formal) matches")
    ] = False,
    limit: int = 20,
) -> None:
    dir_: Literal["above", "below", "both"] = direction  # type: ignore[assignment]
    asyncio.run(
        _analyze(
            lambda s: price_anomalies(
                s,
                threshold=threshold,
                direction=dir_,
                customer_bins=[bin_] if bin_ else None,
                years=[year] if year else None,
                enstru_codes=[enstru] if enstru else None,
                confirm_z=confirm_z,
                only_confirmed=not all_,
                limit=limit,
            )
        )
    )


@analyze_app.command(
    "volume-anomalies", help="Unusual growth of purchased quantity vs previous years"
)
def analyze_volume_anomalies(
    min_ratio: float = 1.5,
    bin_: Annotated[str | None, typer.Option("--bin")] = None,
    year: int | None = None,
    min_extra_amount: float = 0.0,
    confirmed_only: bool = False,
    limit: int = 20,
) -> None:
    asyncio.run(
        _analyze(
            lambda s: volume_anomalies(
                s,
                min_ratio=min_ratio,
                customer_bins=[bin_] if bin_ else None,
                years=[year] if year else None,
                min_extra_amount=min_extra_amount,
                only_confirmed=confirmed_only,
                limit=limit,
            )
        )
    )


@app.command("ask", help="Ask the AI agent a question (RU/KZ)")
def ask(
    question: str,
    thread: Annotated[str | None, typer.Option("--thread", help="Continue a dialog")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full JSON answer")] = False,
) -> None:
    from goszakup_ai.agent.graph import open_agent

    async def job(engine: AsyncEngine) -> None:
        settings = get_settings()
        url = settings.database_url.get_secret_value()
        async with open_agent(settings, make_sessionmaker(engine), url) as agent:
            answer = await agent.ask(question, thread)
        if as_json:
            typer.echo(answer.model_dump_json(indent=2))
            return
        typer.echo(answer.markdown)
        typer.echo(
            f"\nthread {answer.thread_id} · run {answer.run_id} · {answer.model} · "
            f"{answer.latency_ms} ms · intent={answer.params.intent} · {answer.kind}"
        )

    asyncio.run(_with_engine(job))


@app.command("chat", help="Interactive dialog with the agent (empty line to exit)")
def chat(thread: Annotated[str | None, typer.Option("--thread")] = None) -> None:
    import uuid

    from goszakup_ai.agent.graph import open_agent

    thread_id = thread or str(uuid.uuid4())

    async def job(engine: AsyncEngine) -> None:
        settings = get_settings()
        url = settings.database_url.get_secret_value()
        async with open_agent(settings, make_sessionmaker(engine), url) as agent:
            typer.echo(f"thread {thread_id}")
            while question := (await asyncio.to_thread(input, "\n> ")).strip():
                answer = await agent.ask(question, thread_id)
                typer.echo(answer.markdown if answer.kind == "answer" else answer.verdict)

    asyncio.run(_with_engine(job))


db_app = typer.Typer(no_args_is_help=True)
app.add_typer(db_app, name="db", help="Database administration")


@db_app.command("migrate", help="Apply migrations and create the API login user")
def db_migrate() -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    ini = Path.cwd() / "alembic.ini"
    if not ini.exists():
        raise typer.BadParameter(f"{ini} not found: run from the backend directory")
    command.upgrade(Config(str(ini)), "head")
    if get_settings().api_database_url is not None:
        create_api_user()


@db_app.command("create-api-user", help="Create the login user from API_DATABASE_URL")
def create_api_user() -> None:
    from sqlalchemy import make_url

    settings = get_settings()
    if settings.api_database_url is None:
        raise typer.BadParameter("API_DATABASE_URL is not set")
    url = make_url(settings.api_database_url.get_secret_value())

    async def job(engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            params = {"u": url.username, "p": url.password}
            exists = await conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :u"), params)
            verb = "ALTER" if exists else "CREATE"
            statement = await conn.scalar(
                text(
                    f"SELECT format('{verb} ROLE %I LOGIN PASSWORD %L', "
                    "CAST(:u AS text), CAST(:p AS text))"
                ),
                params,
            )
            grant = await conn.scalar(
                text("SELECT format('GRANT goszakup_api TO %I', CAST(:u AS text))"), params
            )
            await conn.exec_driver_sql(statement)
            await conn.exec_driver_sql(grant)
        action = "updated" if exists else "created"
        typer.echo(f"user {url.username}: {action}, granted goszakup_api")

    asyncio.run(_with_engine(job))


eval_app = typer.Typer(no_args_is_help=True)
app.add_typer(eval_app, name="eval", help="Agent quality evaluation")


@eval_app.command("run", help="Run the golden question set and write a report")
def eval_run(
    provider: Annotated[str | None, typer.Option(help="openai, qwen or gemini")] = None,
    model: Annotated[str | None, typer.Option(help="Model name for the provider")] = None,
    concurrency: int = 4,
    only: Annotated[list[str] | None, typer.Option(help="Case id prefixes to run")] = None,
) -> None:
    from goszakup_ai.agent.graph import open_agent
    from goszakup_ai.core.config import REPO_ROOT
    from goszakup_ai.evals.cases import build_cases
    from goszakup_ai.evals.runner import render_report, run_eval

    settings = get_settings()
    updates: dict[str, str] = {}
    if provider:
        updates["llm_provider"] = provider
    if model:
        updates[f"{provider or settings.llm_provider}_model"] = model
    settings = settings.model_copy(update=updates)

    async def job(engine: AsyncEngine) -> None:
        sessions = make_sessionmaker(engine)
        async with sessions() as session:
            cases = await build_cases(session)
            as_of = await session.scalar(
                text(
                    "SELECT max(finished_at) FROM meta.sync_run "
                    "WHERE status = 'ok' AND command LIKE 'ingest scope%'"
                )
            )
        if only:
            cases = [c for c in cases if c.id.startswith(tuple(only))]
        url = settings.database_url.get_secret_value()
        async with open_agent(settings, sessions, url) as agent:
            report = await run_eval(agent, cases, as_of, concurrency)
        out = REPO_ROOT / "evals" / "reports"
        out.mkdir(parents=True, exist_ok=True)
        name = f"{report.started_at:%Y%m%d_%H%M}_{report.model.replace(':', '_')}"
        (out / f"{name}.md").write_text(render_report(report), encoding="utf-8")
        (out / f"{name}.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
        m = report.metrics
        typer.echo(
            f"{report.model}: facts {m['fact_accuracy']:.1%} "
            f"(LLM text {m['narrative_fact_accuracy']:.1%}), intent {m['intent_accuracy']:.1%}, "
            f"errors {m['errors']} → evals/reports/{name}.md"
        )

    asyncio.run(_with_engine(job))


@app.command("serve", help="Run the HTTP API")
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run("goszakup_ai.api.app:app", host=host, port=port, reload=reload)


async def _bootstrap(full: bool, benchmark: bool) -> None:
    await _run("ingest refs", lambda i: i.load_refs())
    await _load_cpi()
    await _run(
        "ingest scope --full" if full else "ingest scope",
        lambda i: i.load_scope(list(TARGET_BINS), full=full),
    )
    await _with_engine(build_marts)
    if benchmark:
        await _run(
            "ingest benchmark",
            lambda i: i.load_benchmark(coverage=0.95, max_contracts=200, full=full),
        )
        await _with_engine(refresh_marts)

    async def checks(engine: AsyncEngine) -> None:
        _print_checks(await run_checks(engine))

    await _with_engine(checks)


@app.command("bootstrap", help="First full load: refs, CPI, 27 BINs, marts, benchmark, DQ")
def bootstrap(
    benchmark: Annotated[bool, typer.Option(help="Also load the price benchmark (~1 h)")] = True,
) -> None:
    asyncio.run(_bootstrap(full=True, benchmark=benchmark))


@app.command("schedule", help="Long-running worker: periodic sync and weekly benchmark")
def schedule(
    sync_hours: Annotated[float, typer.Option(envvar="SYNC_INTERVAL_HOURS")] = 6,
    benchmark_days: Annotated[float, typer.Option(envvar="BENCHMARK_INTERVAL_DAYS")] = 7,
) -> None:
    import time

    log = logging.getLogger("goszakup.schedule")

    async def has_data() -> bool:
        engine = make_engine(get_settings())
        try:
            async with engine.connect() as conn:
                runs = await conn.scalar(
                    text("SELECT count(*) FROM meta.sync_run WHERE status = 'ok'")
                )
                return bool(runs)
        finally:
            await engine.dispose()

    async def loop() -> None:
        if not await has_data():
            log.info("empty database: running bootstrap")
            await _bootstrap(full=True, benchmark=True)
        next_benchmark = time.monotonic() + benchmark_days * 86400
        while True:
            try:
                await _sync()
                if time.monotonic() >= next_benchmark:
                    await _load_cpi()
                    await _run(
                        "ingest benchmark",
                        lambda i: i.load_benchmark(coverage=0.95, max_contracts=200),
                    )
                    await _with_engine(refresh_marts)
                    next_benchmark = time.monotonic() + benchmark_days * 86400
            except Exception:
                log.exception("scheduled run failed; retrying at the next interval")
            await asyncio.sleep(sync_hours * 3600)

    asyncio.run(loop())


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
