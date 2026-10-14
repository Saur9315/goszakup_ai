from __future__ import annotations

import logging
import operator
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal, TypedDict, cast

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import insert, make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from goszakup_ai.agent.formatting import fmt_pct
from goszakup_ai.agent.llm import LlmConfigError, make_chat_model
from goszakup_ai.agent.prompts import (
    CLARIFICATIONS,
    COMPOSE_SYSTEM,
    LANGUAGE_NAMES,
    PROMPT_VERSION,
    UNDERSTAND_SYSTEM,
    compose_user,
    history_block,
    orgs_block,
)
from goszakup_ai.agent.render import render
from goszakup_ai.agent.resolve import resolve, scope_orgs
from goszakup_ai.agent.schemas import (
    AgentAnswer,
    AnswerDraft,
    Fact,
    QuestionAnalysis,
    ResolvedParams,
    ToolResult,
    Turn,
    Verification,
)
from goszakup_ai.agent.tools import run_tools, suggest_lots
from goszakup_ai.agent.verify import allowed_numbers, drop_footnote_refs, substitute, verify
from goszakup_ai.analytics.repository import NotFoundError
from goszakup_ai.core.config import Settings
from goszakup_ai.db.models import AnalysisRun

log = logging.getLogger(__name__)

MAX_COMPOSE_ATTEMPTS = 2
PRICE_INTENTS = {"fair_price", "price_anomaly", "compare", "search"}
DQ_NOTES = {
    "unit_imputed": "единица измерения восстановлена косвенно у {share} позиций",
    "kato_from_customer": "место поставки определено по адресу заказчика у {share} позиций",
    "cpi_month_missing": "для {share} позиций ещё нет опубликованного ИПЦ месяца подписания",
}
COVERAGE_SQL = """
SELECT customer_name, year, contracts, prev_contracts
FROM mart.customer_coverage
WHERE customer_bin = ANY(:bins) AND prev_contracts >= 20 AND contracts < 0.2 * prev_contracts
"""


class AgentState(TypedDict, total=False):
    question: str
    history: Annotated[list[Turn], operator.add]
    analysis: QuestionAnalysis | None
    params: ResolvedParams | None
    results: list[ToolResult]
    facts: list[Fact]
    draft: AnswerDraft | None
    verification: Verification | None
    attempts: int
    clarification: str | None
    llm_fallback: bool


Node = Callable[[AgentState], Awaitable[AgentState]]


def timed(name: str, fn: Node) -> Callable[[AgentState, RunnableConfig], Awaitable[AgentState]]:
    async def node(state: AgentState, config: RunnableConfig) -> AgentState:
        started = time.monotonic()
        try:
            return await fn(state)
        finally:
            timings = config.get("configurable", {}).get("timings")
            if timings is not None:
                elapsed = int((time.monotonic() - started) * 1000)
                timings[name] = timings.get(name, 0) + elapsed

    return node


def template_draft(facts: list[Fact]) -> AnswerDraft:
    head, rest = facts[:3], facts[3:8]
    verdict = "; ".join(f"{f.label}: {{{f.id}}}" for f in head) + "." if head else "Нет данных."
    return AnswerDraft(verdict=verdict, analysis=[f"{f.label}: {{{f.id}}}" for f in rest])


class Agent:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        checkpointer: BaseCheckpointSaver[Any] | None = None,
    ) -> None:
        self.llm, self.model_name, self.method = make_chat_model(settings)
        self.fallback = None
        fallback = settings.llm_fallback_provider
        if fallback and fallback != settings.llm_provider:
            try:
                self.fallback = make_chat_model(settings, fallback)
            except LlmConfigError as e:
                log.warning("fallback LLM disabled: %s", e)
        self.sessions = sessions
        self.graph = self._build(checkpointer)

    def _build(self, checkpointer: BaseCheckpointSaver[Any] | None) -> Any:
        g = StateGraph(AgentState)
        nodes: list[tuple[str, Node]] = [
            ("understand", self._understand),
            ("resolve", self._resolve),
            ("check", self._check),
            ("tools", self._tools),
            ("compose", self._compose),
            ("verify", self._verify),
            ("remember", self._remember),
        ]
        for name, fn in nodes:
            g.add_node(name, timed(name, fn))  # type: ignore[call-overload]
        g.add_edge(START, "understand")
        g.add_edge("understand", "resolve")
        g.add_edge("resolve", "check")
        g.add_conditional_edges("check", self._skip_if_clarified("tools"))
        g.add_conditional_edges("tools", self._skip_if_clarified("compose"))
        g.add_edge("compose", "verify")
        g.add_conditional_edges("verify", self._after_verify)
        g.add_edge("remember", END)
        return g.compile(checkpointer=checkpointer)

    @staticmethod
    def _skip_if_clarified(next_node: str) -> Callable[[AgentState], str]:
        return lambda s: "remember" if s.get("clarification") else next_node

    async def _structured(self, schema: type[Any], messages: list[BaseMessage]) -> Any:
        runnable: Any = self.llm.with_structured_output(schema, method=self.method)
        if self.fallback:
            llm, _, method = self.fallback
            runnable = runnable.with_fallbacks([llm.with_structured_output(schema, method=method)])
        return await runnable.ainvoke(messages)

    async def _understand(self, state: AgentState) -> AgentState:
        async with self.sessions() as session:
            orgs = await scope_orgs(session)
        system = UNDERSTAND_SYSTEM.format(orgs=orgs_block(orgs))
        history = history_block(state.get("history") or [])
        analysis = await self._structured(
            QuestionAnalysis,
            [SystemMessage(f"{system}\n\n{history}".strip()), HumanMessage(state["question"])],
        )
        return {
            "analysis": cast(QuestionAnalysis, analysis),
            "params": None,
            "results": [],
            "facts": [],
            "draft": None,
            "verification": None,
            "attempts": 0,
            "clarification": None,
            "llm_fallback": False,
        }

    async def _resolve(self, state: AgentState) -> AgentState:
        analysis = state["analysis"]
        assert analysis is not None
        async with self.sessions() as session:
            params = await resolve(session, analysis, state["question"])
        return {"params": params}

    async def _check(self, state: AgentState) -> AgentState:
        p = state["params"]
        assert p is not None
        lang = p.language
        if p.intent == "out_of_scope":
            return {"clarification": CLARIFICATIONS["out_of_scope"][lang]}
        if p.intent == "fair_price" and not p.lot_numbers:
            async with self.sessions() as session:
                lots = await suggest_lots(session, p)
            message = CLARIFICATIONS["need_lot"][lang]
            if lots:
                options = "\n".join(f"- {lot}" for lot in lots)
                message += f"\n{CLARIFICATIONS['suggest_lots'][lang]}\n{options}"
            return {"clarification": message}
        if p.items and not p.enstru_codes:
            items = ", ".join(p.items)
            return {"clarification": CLARIFICATIONS["unknown_item"][lang].format(items=items)}
        return {}

    async def _tools(self, state: AgentState) -> AgentState:
        p = state["params"]
        assert p is not None
        try:
            async with self.sessions() as session:
                results = await run_tools(session, p)
        except NotFoundError as e:
            return {"clarification": str(e)}
        facts: list[Fact] = []
        for r in results:
            for f in r.facts:
                f.id = f"f{len(facts) + 1}"
                facts.append(f)
        return {"results": results, "facts": facts}

    async def _compose(self, state: AgentState) -> AgentState:
        p = state["params"]
        assert p is not None
        facts = state["facts"]
        messages: list[BaseMessage] = [
            SystemMessage(COMPOSE_SYSTEM.format(language=LANGUAGE_NAMES[p.language])),
            HumanMessage(
                compose_user(
                    state["question"],
                    p,
                    state["results"],
                    facts,
                    history[-1].question if (history := state.get("history")) else None,
                )
            ),
        ]
        previous = state.get("verification")
        if previous and previous.unverified:
            messages.append(
                HumanMessage(
                    "В прошлом варианте были числа не из таблицы фактов: "
                    + ", ".join(previous.unverified)
                    + ". Перепиши ответ, используя только значения из таблицы."
                )
            )
        attempts = state.get("attempts", 0) + 1
        try:
            draft = cast(AnswerDraft, await self._structured(AnswerDraft, messages))
        except Exception:
            log.exception("compose failed, falling back to a template answer")
            return {"draft": template_draft(facts), "attempts": attempts, "llm_fallback": True}
        displays = {f.id: f.display for f in facts}
        draft = AnswerDraft(
            verdict=drop_footnote_refs(draft.verdict, displays),
            analysis=[drop_footnote_refs(a, displays) for a in draft.analysis],
        )
        return {"draft": draft, "attempts": attempts}

    async def _verify(self, state: AgentState) -> AgentState:
        draft, p = state["draft"], state["params"]
        assert draft is not None and p is not None
        allowed = allowed_numbers(p, state["results"], state["facts"])
        result = verify(
            [draft.verdict, *draft.analysis],
            {f.id for f in state["facts"]},
            allowed,
            state.get("attempts", 0),
        )
        return {"verification": result}

    def _after_verify(self, state: AgentState) -> Literal["compose", "remember"]:
        v = state.get("verification")
        retry = v is not None and bool(v.unverified) and not state.get("llm_fallback")
        return (
            "compose" if retry and state.get("attempts", 0) < MAX_COMPOSE_ATTEMPTS else "remember"
        )

    async def _remember(self, state: AgentState) -> AgentState:
        p = state.get("params")
        draft = state.get("draft")
        answer = state.get("clarification") or ""
        if not answer and draft is not None:
            answer = substitute(draft.verdict, {f.id: f for f in state.get("facts", [])})
        turn = Turn(
            question=state["question"],
            intent=p.intent if p else "out_of_scope",
            customer_bins=p.customer_bins if p else [],
            items=p.items if p else [],
            enstru_codes=p.enstru_codes if p else [],
            lot_numbers=p.lot_numbers if p else [],
            years=p.years if p else [],
            region=p.region_name if p else None,
            answer=answer,
        )
        return {"history": [turn]}

    async def history(self, thread_id: str) -> list[Turn]:
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        return list(snapshot.values.get("history", []))

    async def ask(self, question: str, thread_id: str | None = None) -> AgentAnswer:
        started = time.monotonic()
        run_id = uuid.uuid4()
        thread = thread_id or str(uuid.uuid4())
        usage = UsageMetadataCallbackHandler()
        timings: dict[str, int] = {}
        config: RunnableConfig = {
            "configurable": {"thread_id": thread, "timings": timings},
            "callbacks": [usage],
        }
        try:
            state = cast(AgentState, await self.graph.ainvoke({"question": question}, config))
            answer = await self._answer(run_id, thread, question, state, started)
        except Exception as e:
            await self._save_failed(run_id, thread, question, repr(e), started)
            raise
        answer.usage = {model: dict(u) for model, u in usage.usage_metadata.items()}
        answer.timings_ms = timings
        await self._save(answer)
        return answer

    async def _answer(
        self, run_id: uuid.UUID, thread: str, question: str, state: AgentState, started: float
    ) -> AgentAnswer:
        p = state.get("params") or ResolvedParams(language="ru", intent="out_of_scope")
        results = state.get("results") or []
        clarification = state.get("clarification")
        draft = state.get("draft")
        if clarification or draft is None:
            verdict = clarification or ""
            return AgentAnswer(
                run_id=str(run_id),
                thread_id=thread,
                kind="clarification",
                question=question,
                params=p,
                tool_results=[],
                verdict=verdict,
                analysis=[],
                markdown=verdict + "\n",
                verification=Verification(
                    numbers_total=0, numbers_grounded=0, unverified=[], attempts=0
                ),
                data_as_of=None,
                model=self.model_name,
                latency_ms=int((time.monotonic() - started) * 1000),
                prompt_version=PROMPT_VERSION,
            )
        facts = {f.id: f for f in state["facts"]}
        verdict = substitute(draft.verdict, facts)
        analysis = [substitute(a, facts) for a in draft.analysis]
        verification = state.get("verification") or Verification(
            numbers_total=0, numbers_grounded=0, unverified=[], attempts=0
        )
        data_as_of, dq_notes = await self._data_context(p.intent, p.customer_bins)
        if state.get("llm_fallback"):
            dq_notes.insert(0, "LLM недоступна: вывод собран шаблоном из фактов")
        markdown = render(
            p.language, p, results, verdict, analysis, verification, data_as_of, dq_notes
        )
        return AgentAnswer(
            run_id=str(run_id),
            thread_id=thread,
            question=question,
            params=p,
            tool_results=results,
            verdict=verdict,
            analysis=analysis,
            markdown=markdown,
            verification=verification,
            data_as_of=data_as_of,
            model=self.model_name,
            latency_ms=int((time.monotonic() - started) * 1000),
            llm_fallback=bool(state.get("llm_fallback")),
            prompt_version=PROMPT_VERSION,
        )

    async def _data_context(
        self, intent: str, bins: list[str]
    ) -> tuple[datetime | None, list[str]]:
        async with self.sessions() as session:
            as_of = await session.scalar(
                text(
                    "SELECT max(finished_at) FROM meta.sync_run "
                    "WHERE status = 'ok' AND command LIKE 'ingest scope%'"
                )
            )
            rows = await session.execute(
                text(
                    "SELECT DISTINCT ON (check_name) check_name, failed_count, total_count "
                    "FROM meta.dq_check_result ORDER BY check_name, checked_at DESC"
                )
            )
            checks = {r.check_name: r for r in rows}
            drops = (await session.execute(text(COVERAGE_SQL), {"bins": bins})).all()
        notes = [
            f"у «{d.customer_name}» в {d.year} году {d.contracts} договоров против "
            f"{d.prev_contracts} годом ранее — данные по организации неполные "
            "(закупки, вероятно, ведутся вне портала goszakup)"
            for d in drops
        ]
        if intent in PRICE_INTENTS:
            for name, template in DQ_NOTES.items():
                r = checks.get(name)
                if r and r.failed_count and r.total_count:
                    share = fmt_pct(r.failed_count / r.total_count)
                    notes.append(template.format(share=share) + " (по всей базе)")
        fresh = checks.get("sync_older_than_24h")
        if fresh and fresh.failed_count:
            notes.append("последняя синхронизация старше 24 часов")
        return as_of, notes

    async def _save(self, a: AgentAnswer) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                insert(AnalysisRun).values(
                    id=uuid.UUID(a.run_id),
                    thread_id=uuid.UUID(a.thread_id),
                    kind=a.kind,
                    question=a.question,
                    language=a.params.language,
                    intent=a.params.intent,
                    params=a.params.model_dump(mode="json"),
                    tool_results=[r.model_dump(mode="json") for r in a.tool_results],
                    answer={"verdict": a.verdict, "analysis": a.analysis, "markdown": a.markdown},
                    verification=a.verification.model_dump(),
                    model=a.model,
                    latency_ms=a.latency_ms,
                    llm_fallback=a.llm_fallback,
                    usage=a.usage,
                    timings_ms=a.timings_ms,
                    prompt_version=a.prompt_version,
                    status="ok",
                )
            )

    async def _save_failed(
        self, run_id: uuid.UUID, thread: str, question: str, error: str, started: float
    ) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                insert(AnalysisRun).values(
                    id=run_id,
                    thread_id=uuid.UUID(thread),
                    question=question,
                    model=self.model_name,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    prompt_version=PROMPT_VERSION,
                    status="failed",
                    error=error[:2000],
                )
            )


CHECKPOINT_TYPES = [
    ("goszakup_ai.agent.schemas", name)
    for name in (
        "AnswerDraft",
        "Fact",
        "QuestionAnalysis",
        "ResolvedParams",
        "ToolResult",
        "Turn",
        "Verification",
    )
]


def _psycopg_conninfo(database_url: str) -> str:
    url = make_url(database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


@asynccontextmanager
async def open_agent(
    settings: Settings, sessions: async_sessionmaker[AsyncSession], database_url: str
) -> AsyncIterator[Agent]:
    async with AsyncConnectionPool(
        _psycopg_conninfo(database_url),
        max_size=5,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": "-c search_path=agent",
        },
    ) as pool:
        serde = JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)
        saver = AsyncPostgresSaver(pool, serde=serde)  # type: ignore[arg-type]
        await saver.setup()
        yield Agent(settings, sessions, saver)
