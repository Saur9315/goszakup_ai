from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Any, TypedDict, cast

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from goszakup_ai.agent.formatting import fmt_pct
from goszakup_ai.agent.llm import make_chat_model
from goszakup_ai.agent.prompts import (
    COMPOSE_SYSTEM,
    LANGUAGE_NAMES,
    UNDERSTAND_SYSTEM,
    compose_user,
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
    Verification,
)
from goszakup_ai.agent.tools import run_tools
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


class AgentState(TypedDict, total=False):
    question: str
    analysis: QuestionAnalysis
    params: ResolvedParams
    results: list[ToolResult]
    facts: list[Fact]
    draft: AnswerDraft
    verification: Verification
    attempts: int
    error: str


class Agent:
    def __init__(self, settings: Settings, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.llm, self.model_name, self.method = make_chat_model(settings)
        self.sessions = sessions
        self.graph = self._build()

    def _build(self) -> Any:
        g = StateGraph(AgentState)
        g.add_node("understand", self._understand)
        g.add_node("resolve", self._resolve)
        g.add_node("tools", self._tools)
        g.add_node("compose", self._compose)
        g.add_node("verify", self._verify)
        g.add_edge(START, "understand")
        g.add_edge("understand", "resolve")
        g.add_edge("resolve", "tools")
        g.add_conditional_edges("tools", lambda s: END if s.get("error") else "compose")
        g.add_edge("compose", "verify")
        g.add_conditional_edges("verify", self._after_verify)
        return g.compile()

    async def _structured(self, schema: type[Any], messages: list[BaseMessage]) -> Any:
        runnable = self.llm.with_structured_output(schema, method=self.method)
        return await runnable.ainvoke(messages)

    async def _understand(self, state: AgentState) -> AgentState:
        async with self.sessions() as session:
            orgs = await scope_orgs(session)
        analysis = await self._structured(
            QuestionAnalysis,
            [
                SystemMessage(UNDERSTAND_SYSTEM.format(orgs=orgs_block(orgs))),
                HumanMessage(state["question"]),
            ],
        )
        return {"analysis": cast(QuestionAnalysis, analysis)}

    async def _resolve(self, state: AgentState) -> AgentState:
        async with self.sessions() as session:
            params = await resolve(session, state["analysis"], state["question"])
        return {"params": params}

    async def _tools(self, state: AgentState) -> AgentState:
        try:
            async with self.sessions() as session:
                results = await run_tools(session, state["params"])
        except NotFoundError as e:
            return {"error": str(e), "results": [], "facts": []}
        facts: list[Fact] = []
        for r in results:
            for f in r.facts:
                f.id = f"f{len(facts) + 1}"
                facts.append(f)
        return {"results": results, "facts": facts, "attempts": 0}

    async def _compose(self, state: AgentState) -> AgentState:
        p = state["params"]
        messages: list[BaseMessage] = [
            SystemMessage(COMPOSE_SYSTEM.format(language=LANGUAGE_NAMES[p.language])),
            HumanMessage(compose_user(state["question"], p, state["results"], state["facts"])),
        ]
        previous = state.get("verification")
        if previous and previous.unverified:
            messages.append(
                HumanMessage(
                    "В прошлом варианте были числа не из таблицы фактов: "
                    + ", ".join(previous.unverified)
                    + ". Перепиши ответ: каждое число — только ссылкой {fN}."
                )
            )
        draft = cast(AnswerDraft, await self._structured(AnswerDraft, messages))
        displays = {f.id: f.display for f in state["facts"]}
        draft = AnswerDraft(
            verdict=drop_footnote_refs(draft.verdict, displays),
            analysis=[drop_footnote_refs(a, displays) for a in draft.analysis],
        )
        return {"draft": draft, "attempts": state.get("attempts", 0) + 1}

    async def _verify(self, state: AgentState) -> AgentState:
        draft = state["draft"]
        allowed = allowed_numbers(state["params"], state["results"], state["facts"])
        result = verify(
            [draft.verdict, *draft.analysis],
            {f.id for f in state["facts"]},
            allowed,
            state["attempts"],
        )
        return {"verification": result}

    def _after_verify(self, state: AgentState) -> str:
        if state["verification"].unverified and state["attempts"] < MAX_COMPOSE_ATTEMPTS:
            return "compose"
        return END

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
            drops = (
                await session.execute(
                    text(
                        "SELECT customer_name, year, contracts, prev_contracts "
                        "FROM mart.customer_coverage WHERE customer_bin = ANY(:bins) "
                        "AND prev_contracts >= 20 AND contracts < 0.2 * prev_contracts"
                    ),
                    {"bins": bins},
                )
            ).all()
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

    async def ask(self, question: str) -> AgentAnswer:
        started = time.monotonic()
        run_id = uuid.uuid4()
        try:
            state = cast(AgentState, await self.graph.ainvoke({"question": question}))
            answer = await self._answer(run_id, question, state, started)
        except Exception as e:
            await self._save_failed(run_id, question, repr(e), started)
            raise
        await self._save(answer)
        return answer

    async def _answer(
        self, run_id: uuid.UUID, question: str, state: AgentState, started: float
    ) -> AgentAnswer:
        p = state["params"]
        results = state.get("results", [])
        if state.get("error"):
            verdict, analysis = state["error"], []
            verification = Verification(
                numbers_total=0, numbers_grounded=0, unverified=[], attempts=0
            )
        else:
            facts = {f.id: f for f in state["facts"]}
            draft = state["draft"]
            verdict = substitute(draft.verdict, facts)
            analysis = [substitute(a, facts) for a in draft.analysis]
            verification = state["verification"]
        data_as_of, dq_notes = await self._data_context(p.intent, p.customer_bins)
        markdown = render(
            p.language, p, results, verdict, analysis, verification, data_as_of, dq_notes
        )
        return AgentAnswer(
            run_id=str(run_id),
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
        )

    async def _save(self, a: AgentAnswer) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                insert(AnalysisRun).values(
                    id=uuid.UUID(a.run_id),
                    question=a.question,
                    language=a.params.language,
                    intent=a.params.intent,
                    params=a.params.model_dump(mode="json"),
                    tool_results=[r.model_dump(mode="json") for r in a.tool_results],
                    answer={"verdict": a.verdict, "analysis": a.analysis, "markdown": a.markdown},
                    verification=a.verification.model_dump(),
                    model=a.model,
                    latency_ms=a.latency_ms,
                    status="ok",
                )
            )

    async def _save_failed(
        self, run_id: uuid.UUID, question: str, error: str, started: float
    ) -> None:
        async with self.sessions.begin() as session:
            await session.execute(
                insert(AnalysisRun).values(
                    id=run_id,
                    question=question,
                    model=self.model_name,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    status="failed",
                    error=error[:2000],
                )
            )
