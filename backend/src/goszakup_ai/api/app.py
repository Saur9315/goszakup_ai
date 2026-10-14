from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from goszakup_ai.agent.graph import Agent, open_agent
from goszakup_ai.agent.llm import LlmConfigError
from goszakup_ai.agent.schemas import AgentAnswer, Turn
from goszakup_ai.analytics.anomalies import (
    PriceAnomalyReport,
    VolumeAnomalyReport,
    price_anomalies,
    volume_anomalies,
)
from goszakup_ai.analytics.fair_price import FairPriceResult
from goszakup_ai.analytics.repository import NotFoundError, fair_price_for_lot
from goszakup_ai.core.config import get_settings
from goszakup_ai.db.models import AnalysisRun
from goszakup_ai.db.session import make_engine, make_sessionmaker

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    url = (settings.api_database_url or settings.database_url).get_secret_value()
    engine = make_engine(settings, url)
    app.state.sessions = make_sessionmaker(engine)
    app.state.agent = None
    async with AsyncExitStack() as stack:
        try:
            app.state.agent = await stack.enter_async_context(
                open_agent(settings, app.state.sessions, url)
            )
        except LlmConfigError as e:
            log.warning("agent disabled: %s", e)
        yield
    await engine.dispose()


app = FastAPI(title="GosZakup AI", version="0.1.0", lifespan=lifespan)


@app.exception_handler(NotFoundError)
async def not_found(_: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(LlmConfigError)
async def llm_not_configured(_: Request, exc: LlmConfigError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


async def session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as s:
        yield s


def agent(request: Request) -> Agent:
    if request.app.state.agent is None:
        raise HTTPException(status_code=503, detail="LLM is not configured")
    return request.app.state.agent  # type: ignore[no-any-return]


Session = Annotated[AsyncSession, Depends(session)]


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    thread_id: uuid.UUID | None = None


@app.get("/api/health")
async def health(db: Session) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/api/ask")
async def ask(body: AskRequest, a: Annotated[Agent, Depends(agent)]) -> AgentAnswer:
    return await a.ask(body.question, str(body.thread_id) if body.thread_id else None)


@app.get("/api/threads/{thread_id}")
async def thread_history(thread_id: uuid.UUID, a: Annotated[Agent, Depends(agent)]) -> list[Turn]:
    return await a.history(str(thread_id))


@app.get("/api/runs/{run_id}")
async def get_run(run_id: uuid.UUID, db: Session) -> dict[str, Any]:
    run = await db.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "id": str(run.id),
        "created_at": run.created_at,
        "question": run.question,
        "intent": run.intent,
        "status": run.status,
        "model": run.model,
        "latency_ms": run.latency_ms,
        "params": run.params,
        "tool_results": run.tool_results,
        "answer": run.answer,
        "verification": run.verification,
        "error": run.error,
    }


@app.get("/api/status")
async def status(db: Session) -> dict[str, Any]:
    as_of = await db.scalar(
        text(
            "SELECT max(finished_at) FROM meta.sync_run "
            "WHERE status = 'ok' AND command LIKE 'ingest scope%'"
        )
    )
    checks = await db.execute(
        text(
            "SELECT DISTINCT ON (check_name) check_name, severity, failed_count, total_count, "
            "checked_at FROM meta.dq_check_result ORDER BY check_name, checked_at DESC"
        )
    )
    return {"data_as_of": as_of, "checks": [dict(r._mapping) for r in checks]}


@app.get("/api/orgs")
async def orgs(db: Session) -> list[dict[str, Any]]:
    rows = await db.execute(text("SELECT bin, name_ru FROM meta.scope_bin ORDER BY name_ru"))
    return [dict(r._mapping) for r in rows]


@app.get("/api/fair-price/{lot}")
async def fair_price(lot: str, db: Session) -> list[FairPriceResult]:
    return await fair_price_for_lot(db, lot)


@app.get("/api/anomalies/price")
async def anomalies_price(
    db: Session,
    threshold: float = 0.3,
    direction: Literal["above", "below", "both"] = "above",
    bins: Annotated[list[str] | None, Query()] = None,
    years: Annotated[list[int] | None, Query()] = None,
    enstru: Annotated[list[str] | None, Query()] = None,
    confirmed_only: bool = True,
    limit: int = Query(default=20, le=200),
) -> PriceAnomalyReport:
    return await price_anomalies(
        db,
        threshold=threshold,
        direction=direction,
        customer_bins=bins,
        years=years,
        enstru_codes=enstru,
        only_confirmed=confirmed_only,
        limit=limit,
    )


@app.get("/api/anomalies/volume")
async def anomalies_volume(
    db: Session,
    min_ratio: float = 1.5,
    bins: Annotated[list[str] | None, Query()] = None,
    years: Annotated[list[int] | None, Query()] = None,
    limit: int = Query(default=20, le=200),
) -> VolumeAnomalyReport:
    return await volume_anomalies(
        db, min_ratio=min_ratio, customer_bins=bins, years=years, limit=limit
    )


@app.get("/api/efficiency")
async def efficiency(
    db: Session, years: Annotated[list[int] | None, Query()] = None
) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT e.*, sb.name_ru FROM mart.procurement_efficiency e "
            "JOIN meta.scope_bin sb ON sb.bin = e.customer_bin "
            "WHERE e.year = ANY(:years) ORDER BY e.contract_amount DESC NULLS LAST"
        ),
        {"years": years or [2024, 2025, 2026]},
    )
    return [dict(r._mapping) for r in rows]
