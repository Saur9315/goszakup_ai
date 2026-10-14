from __future__ import annotations

import asyncio
import statistics
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from goszakup_ai.agent.graph import Agent
from goszakup_ai.agent.schemas import AgentAnswer
from goszakup_ai.evals.cases import EvalCase
from goszakup_ai.evals.matching import fact_present

TZ_FACT_ACCURACY = 0.85


class FactCheck(BaseModel):
    name: str
    kind: str
    expected: str
    in_answer: bool
    in_narrative: bool


class CaseResult(BaseModel):
    id: str
    language: str
    question: str
    intent_expected: str | None
    intent_actual: str | None = None
    kind_expected: str
    kind_actual: str | None = None
    bins_ok: bool | None = None
    lots_ok: bool | None = None
    years_ok: bool | None = None
    facts: list[FactCheck] = []
    numbers_total: int = 0
    numbers_grounded: int = 0
    latencies_ms: list[int] = []
    input_tokens: int = 0
    output_tokens: int = 0
    run_ids: list[str] = []
    error: str | None = None


class EvalReport(BaseModel):
    model: str
    started_at: datetime
    data_as_of: datetime | None
    cases: list[CaseResult]
    metrics: dict[str, Any]


def _tokens(answer: AgentAnswer) -> tuple[int, int]:
    usage = answer.usage.values()
    return (
        sum(int(u.get("input_tokens", 0)) for u in usage),
        sum(int(u.get("output_tokens", 0)) for u in usage),
    )


def evaluate(case: EvalCase, answers: list[AgentAnswer]) -> CaseResult:
    last = answers[-1]
    p = last.params
    narrative = "\n".join([last.verdict, *last.analysis])
    tokens = [_tokens(a) for a in answers]
    result = CaseResult(
        id=case.id,
        language=case.language,
        question=" → ".join(case.turns),
        intent_expected=case.intent,
        intent_actual=p.intent,
        kind_expected=case.kind,
        kind_actual=last.kind,
        facts=[
            FactCheck(
                name=f.name,
                kind=f.kind,
                expected=str(f.value),
                in_answer=fact_present(f.kind, f.value, last.markdown),
                in_narrative=fact_present(f.kind, f.value, narrative),
            )
            for f in case.facts
        ],
        numbers_total=last.verification.numbers_total,
        numbers_grounded=last.verification.numbers_grounded,
        latencies_ms=[a.latency_ms for a in answers],
        input_tokens=sum(t[0] for t in tokens),
        output_tokens=sum(t[1] for t in tokens),
        run_ids=[a.run_id for a in answers],
    )
    if case.kind == "answer":
        result.bins_ok = set(case.bins) == set(p.customer_bins)
        if case.lots:
            result.lots_ok = set(case.lots) <= set(p.lot_numbers)
        if case.years:
            result.years_ok = set(case.years) == set(p.years)
    return result


async def run_case(agent: Agent, case: EvalCase) -> CaseResult:
    thread = str(uuid.uuid4())
    answers: list[AgentAnswer] = []
    try:
        for question in case.turns:
            answers.append(await agent.ask(question, thread))
    except Exception as e:
        return CaseResult(
            id=case.id,
            language=case.language,
            question=" → ".join(case.turns),
            intent_expected=case.intent,
            kind_expected=case.kind,
            error=repr(e)[:500],
        )
    return evaluate(case, answers)


def _share(values: list[bool | None]) -> float | None:
    known = [v for v in values if v is not None]
    return sum(known) / len(known) if known else None


def metrics(results: list[CaseResult]) -> dict[str, Any]:
    facts = [f for r in results for f in r.facts]
    latencies = sorted(ms for r in results for ms in r.latencies_ms)
    p95 = latencies[int(0.95 * (len(latencies) - 1))] if latencies else None
    numbers = sum(r.numbers_total for r in results)
    return {
        "cases": len(results),
        "questions": sum(len(r.latencies_ms) for r in results),
        "errors": sum(r.error is not None for r in results),
        "facts": len(facts),
        "fact_accuracy": _share([f.in_answer for f in facts]),
        "narrative_fact_accuracy": _share([f.in_narrative for f in facts]),
        "intent_accuracy": _share(
            [r.intent_actual == r.intent_expected for r in results if r.intent_expected]
        ),
        "kind_accuracy": _share([r.kind_actual == r.kind_expected for r in results]),
        "bins_accuracy": _share([r.bins_ok for r in results]),
        "lots_accuracy": _share([r.lots_ok for r in results]),
        "years_accuracy": _share([r.years_ok for r in results]),
        "grounding": sum(r.numbers_grounded for r in results) / numbers if numbers else None,
        "latency_p50_ms": statistics.median(latencies) if latencies else None,
        "latency_p95_ms": p95,
        "input_tokens": sum(r.input_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
    }


async def run_eval(
    agent: Agent, cases: list[EvalCase], data_as_of: datetime | None, concurrency: int
) -> EvalReport:
    started = datetime.now()
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(case: EvalCase) -> CaseResult:
        async with semaphore:
            return await run_case(agent, case)

    results = await asyncio.gather(*(guarded(c) for c in cases))
    return EvalReport(
        model=agent.model_name,
        started_at=started,
        data_as_of=data_as_of,
        cases=list(results),
        metrics=metrics(list(results)),
    )


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _mark(value: bool | None) -> str:
    return "—" if value is None else ("✓" if value else "✗")


def render_report(report: EvalReport) -> str:
    m = report.metrics
    passed = m["fact_accuracy"] is not None and m["fact_accuracy"] >= TZ_FACT_ACCURACY
    lines = [
        "# Оценка качества AI-агента",
        "",
        f"- Модель: `{report.model}`",
        f"- Прогон: {report.started_at:%d.%m.%Y %H:%M}",
        f"- Данные на: {report.data_as_of:%d.%m.%Y %H:%M}" if report.data_as_of else "- Данные: —",
        f"- Сценариев: {m['cases']}, вопросов: {m['questions']}, ошибок выполнения: {m['errors']}",
        "",
        "## Метрики",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        f"| **Точность фактов в ответе (цифры, даты, БИН, лоты)** | **{_pct(m['fact_accuracy'])}** "
        f"({'выполнено' if passed else 'не выполнено'} требование ТЗ ≥ 85%) |",
        f"| Точность фактов в тексте, написанном LLM | {_pct(m['narrative_fact_accuracy'])} |",
        f"| Определение типа вопроса | {_pct(m['intent_accuracy'])} |",
        f"| Ответ или уточнение — как ожидалось | {_pct(m['kind_accuracy'])} |",
        f"| Извлечение БИН | {_pct(m['bins_accuracy'])} |",
        f"| Извлечение номеров лотов | {_pct(m['lots_accuracy'])} |",
        f"| Извлечение периода | {_pct(m['years_accuracy'])} |",
        f"| Числа в тексте LLM, подтверждённые данными | {_pct(m['grounding'])} |",
        f"| Задержка p50 / p95 | {m['latency_p50_ms']} / {m['latency_p95_ms']} мс |",
        f"| Токены: вход / выход | {m['input_tokens']:,} / {m['output_tokens']:,} |".replace(
            ",", " "
        ),
        f"| Проверено фактов | {m['facts']} |",
        "",
        "## Сценарии",
        "",
        "| Сценарий | Язык | Тип: ожид. → факт | БИН | Лот | Годы | Факты | Время, мс |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in report.cases:
        found = sum(f.in_answer for f in r.facts)
        intent = f"{r.intent_expected} → {r.intent_actual or 'ошибка'}"
        lines.append(
            f"| {r.id} | {r.language} | {intent} | {_mark(r.bins_ok)} | {_mark(r.lots_ok)} | "
            f"{_mark(r.years_ok)} | {found}/{len(r.facts)} | "
            f"{' + '.join(map(str, r.latencies_ms)) or '—'} |"
        )
    problems = [
        f"- `{r.id}` — {f.name}: ожидалось {f.expected}"
        for r in report.cases
        for f in r.facts
        if not f.in_answer
    ]
    problems += [f"- `{r.id}` — ошибка выполнения: {r.error}" for r in report.cases if r.error]
    problems += [
        f"- `{r.id}` — тип вопроса {r.intent_actual} вместо {r.intent_expected}"
        for r in report.cases
        if r.intent_expected and r.intent_actual and r.intent_actual != r.intent_expected
    ]
    lines += ["", "## Расхождения", "", *(problems or ["Нет."])]
    lines += [
        "",
        "## Как считается",
        "",
        "- Ожидаемые значения вычисляются прямым SQL по витринам в момент прогона, поэтому набор "
        "остаётся корректным после ежедневной синхронизации.",
        "- Факт найден, если число с учётом единиц (млн, млрд, %) и точности записи "
        "совпадает с ожидаемым; БИН, номера лотов и даты — по точному вхождению.",
        "- «Точность фактов в ответе» — по всему ответу пользователю; «в тексте LLM» — только по "
        "краткому выводу и пунктам аналитики, которые пишет модель.",
        "- Диалоговые сценарии проверяют последний ответ в треде.",
    ]
    return "\n".join(lines) + "\n"
