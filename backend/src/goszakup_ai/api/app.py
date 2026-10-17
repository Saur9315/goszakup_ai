from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from goszakup_ai.api.auth import (
    DUMMY_HASH,
    decode_token,
    encode_token,
    new_claims,
    verify_password,
)
from goszakup_ai.core.config import get_settings
from goszakup_ai.db.models import AgentThread, AnalysisRun, AppUser
from goszakup_ai.db.models.meta import SYNC_LOCK_CLASS
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
Sessions = async_sessionmaker[AsyncSession]
AgentDep = Annotated[Agent, Depends(agent)]
bearer = HTTPBearer(auto_error=False)


class User(BaseModel):
    id: int
    username: str


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User | None:
    if credentials is None:
        return None
    secret = get_settings().auth_secret
    claims = decode_token(secret.get_secret_value(), credentials.credentials) if secret else None
    if claims is not None:
        async with request.app.state.sessions() as db:
            active = await db.scalar(select(AppUser.is_active).where(AppUser.id == claims.user_id))
        if active:
            return User(id=claims.user_id, username=claims.username)
    raise HTTPException(status_code=401, detail="invalid or expired token")


CurrentUser = Annotated[User | None, Depends(current_user)]


def require_user(user: CurrentUser) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="login required")
    return user


RequiredUser = Annotated[User, Depends(require_user)]


async def authorize_thread(
    sessions: Sessions, thread_id: uuid.UUID | None, user: User | None
) -> None:
    if thread_id is None:
        return
    async with sessions() as db:
        owner = await db.scalar(
            select(AgentThread.user_id).where(AgentThread.thread_id == thread_id)
        )
    if owner is not None and (user is None or user.id != owner):
        raise HTTPException(status_code=404, detail="thread not found")


async def remember_thread(
    sessions: Sessions, thread_id: str, user: User | None, title: str
) -> None:
    if user is None:
        return
    async with sessions.begin() as db:
        await db.execute(
            pg_insert(AgentThread)
            .values(thread_id=uuid.UUID(thread_id), user_id=user.id, title=title[:120])
            .on_conflict_do_update(index_elements=["thread_id"], set_={"updated_at": func.now()})
        )


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    thread_id: uuid.UUID | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    token: str
    username: str
    expires_at: datetime


class ThreadInfo(BaseModel):
    thread_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ThreadAnswer(BaseModel):
    run_id: uuid.UUID
    created_at: datetime
    question: str
    kind: str | None
    markdown: str


@app.get("/api/health")
async def health(db: Session) -> dict[str, Any]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "auth": get_settings().auth_secret is not None}


@app.post("/api/auth/login")
async def login(body: LoginRequest, db: Session) -> LoginResponse:
    settings = get_settings()
    if settings.auth_secret is None:
        raise HTTPException(status_code=503, detail="authentication is not configured")
    user = await db.scalar(select(AppUser).where(AppUser.username == body.username.strip().lower()))
    stored = user.password_hash if user is not None else DUMMY_HASH
    valid = await asyncio.to_thread(verify_password, body.password, stored)
    if user is None or not valid or not user.is_active:
        raise HTTPException(status_code=401, detail="invalid username or password")
    claims = new_claims(user.id, user.username, int(settings.auth_token_hours * 3600))
    return LoginResponse(
        token=encode_token(settings.auth_secret.get_secret_value(), claims),
        username=user.username,
        expires_at=datetime.fromtimestamp(claims.expires_at, UTC),
    )


@app.get("/api/me")
async def me(user: RequiredUser) -> User:
    return user


@app.post("/api/ask")
async def ask(body: AskRequest, request: Request, a: AgentDep, user: CurrentUser) -> AgentAnswer:
    sessions = request.app.state.sessions
    await authorize_thread(sessions, body.thread_id, user)
    answer = await a.ask(body.question, str(body.thread_id) if body.thread_id else None)
    await remember_thread(sessions, answer.thread_id, user, body.question)
    return answer


@app.post("/api/ask/stream")
async def ask_stream(
    body: AskRequest, request: Request, a: AgentDep, user: CurrentUser
) -> StreamingResponse:
    sessions = request.app.state.sessions
    await authorize_thread(sessions, body.thread_id, user)

    async def events() -> AsyncIterator[str]:
        try:
            async for event in a.stream(
                body.question, str(body.thread_id) if body.thread_id else None
            ):
                if event.answer is not None:
                    await remember_thread(sessions, event.answer.thread_id, user, body.question)
                yield f"event: {event.kind}\ndata: {event.model_dump_json(exclude_none=True)}\n\n"
        except Exception as e:
            log.exception("streamed answer failed")
            detail = json.dumps({"detail": str(e)}, ensure_ascii=False)
            yield f"event: error\ndata: {detail}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/threads")
async def my_threads(db: Session, user: RequiredUser) -> list[ThreadInfo]:
    rows = await db.scalars(
        select(AgentThread)
        .where(AgentThread.user_id == user.id)
        .order_by(AgentThread.updated_at.desc())
        .limit(100)
    )
    return [ThreadInfo.model_validate(r, from_attributes=True) for r in rows]


@app.get("/api/threads/{thread_id}")
async def thread_history(
    thread_id: uuid.UUID, request: Request, a: AgentDep, user: CurrentUser
) -> list[Turn]:
    await authorize_thread(request.app.state.sessions, thread_id, user)
    return await a.history(str(thread_id))


@app.get("/api/threads/{thread_id}/answers")
async def thread_answers(
    thread_id: uuid.UUID, request: Request, db: Session, user: CurrentUser
) -> list[ThreadAnswer]:
    await authorize_thread(request.app.state.sessions, thread_id, user)
    rows = await db.execute(
        select(
            AnalysisRun.id,
            AnalysisRun.created_at,
            AnalysisRun.question,
            AnalysisRun.kind,
            AnalysisRun.answer,
        )
        .where(AnalysisRun.thread_id == thread_id, AnalysisRun.status == "ok")
        .order_by(AnalysisRun.created_at)
    )
    return [
        ThreadAnswer(
            run_id=r.id,
            created_at=r.created_at,
            question=r.question,
            kind=r.kind,
            markdown=(r.answer or {}).get("markdown", ""),
        )
        for r in rows
    ]


@app.get("/api/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID, request: Request, db: Session, user: CurrentUser
) -> dict[str, Any]:
    run = await db.scalar(select(AnalysisRun).where(AnalysisRun.id == run_id))
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    await authorize_thread(request.app.state.sessions, run.thread_id, user)
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
    running = await db.execute(
        text(
            "SELECT r.id, r.command, r.started_at FROM meta.sync_run r "
            "WHERE r.status = 'running' AND EXISTS (SELECT 1 FROM pg_locks l "
            "WHERE l.locktype = 'advisory' AND l.classid::bigint = :c "
            "AND l.objid::bigint = r.id AND l.objsubid = 2 AND l.granted) ORDER BY r.id"
        ),
        {"c": SYNC_LOCK_CLASS},
    )
    return {
        "data_as_of": as_of,
        "sync_running": [dict(r._mapping) for r in running],
        "checks": [dict(r._mapping) for r in checks],
    }


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
    confirmed_only: bool = False,
    limit: int = Query(default=20, le=200),
) -> VolumeAnomalyReport:
    return await volume_anomalies(
        db,
        min_ratio=min_ratio,
        customer_bins=bins,
        years=years,
        only_confirmed=confirmed_only,
        limit=limit,
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
