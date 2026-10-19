import argparse
import asyncio
import uuid
from datetime import datetime

from goszakup_ai.agent.graph import open_agent
from goszakup_ai.core.config import REPO_ROOT, get_settings
from goszakup_ai.db.session import make_engine, make_sessionmaker

EXAMPLES: list[tuple[str, list[str]]] = [
    (
        "Аномалии цен (обязательный вопрос ТЗ)",
        [
            "Найди закупки с отклонением цены > 30% от средневзвешенной "
            "по данному ЕНСТРУ за 2025 год"
        ],
    ),
    (
        "Справедливость цены лота (обязательный вопрос ТЗ)",
        [
            "Оцени адекватность цены лота №85092773-ОК3 относительно аналогичных контрактов "
            "других ведомств в идентичном городе поставки"
        ],
    ),
    (
        "Справедливость цены: разные товары под одним кодом ЕНС ТРУ",
        ["Оцени адекватность цены лота №69612060-ОК1 относительно аналогичных контрактов"],
    ),
    (
        "Завышение объёмов (обязательный вопрос ТЗ)",
        [
            "Выяви нетипичное завышение количества ТРУ по сравнению с предыдущими годами "
            "у Дирекции государственных резиденций"
        ],
    ),
    (
        "Поиск",
        [
            "Сколько договоров на поставку дизельного топлива заключили организации "
            "в 2025 году и на какую сумму?"
        ],
    ),
    (
        "Сравнение",
        [
            "Сравни Больницу МЦ УДП и Национальный госпиталь по сумме и количеству "
            "договоров за 2025 год"
        ],
    ),
    (
        "Аналитика эффективности",
        ["Какая доля закупок из одного источника у Автохозяйства УДП в 2025 году?"],
    ),
    ("Вопрос на казахском языке", ["2025 жылы Ұлттық госпитальдің сатып алу тиімділігі қандай?"]),
    (
        "Диалог: уточнение номера лота",
        ["Оцени справедливость цены говядины у Дирекции административных зданий", "73162345-ОК2"],
    ),
    ("Предупреждение о неполных данных", ["Как менялись закупки ЦКБ по годам?"]),
    ("Вопрос не по теме", ["Какая погода завтра в Астане?"]),
]


def demote(markdown: str) -> str:
    return "\n".join(
        f"#{line}" if line.startswith("## ") else line for line in markdown.splitlines()
    )


async def main(model: str | None) -> None:
    settings = get_settings()
    if model:
        settings = settings.model_copy(update={f"{settings.llm_provider}_model": model})
    engine = make_engine(settings)
    sessions = make_sessionmaker(engine)
    parts: list[str] = []
    model_name = ""
    async with open_agent(settings, sessions, settings.database_url.get_secret_value()) as agent:
        model_name = agent.model_name
        for i, (title, questions) in enumerate(EXAMPLES, 1):
            thread = str(uuid.uuid4())
            parts.append(f"## {i}. {title}\n")
            for q in questions:
                a = await agent.ask(q, thread)
                v = a.verification
                parts.append(f"> **Вопрос:** {q}\n")
                parts.append(
                    f"`run_id {a.run_id}` · {a.latency_ms} мс · тип вопроса `{a.params.intent}` · "
                    f"проверка цифр {v.numbers_grounded}/{v.numbers_total}\n"
                )
                parts.append(demote(a.markdown) + "\n")
            parts.append("---\n")
    await engine.dispose()
    header = (
        "# Примеры ответов агента\n\n"
        f"Ответы сгенерированы скриптом `backend/scripts/make_examples.py` "
        f"{datetime.now():%d.%m.%Y %H:%M} на модели `{model_name}` и вставлены без правки. "
        "Каждый ответ сохранён в журнале `meta.analysis_run` и открывается по `run_id` "
        "через `GET /api/runs/{id}` (журнал не входит в опубликованный дамп базы).\n\n"
        "Разделы ответа соответствуют ТЗ: краткий вывод, использованные данные, сравнение и "
        "аналитика, метод оценки, уверенность и ограничения, примеры Top-K со ссылками.\n\n"
        + "\n".join(f"{i}. {t}" for i, (t, _) in enumerate(EXAMPLES, 1))
        + "\n\n---\n"
    )
    out = REPO_ROOT / "docs" / "examples.md"
    out.write_text(header + "\n".join(parts), encoding="utf-8")
    print(f"written {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate docs/examples.md with real agent answers"
    )
    parser.add_argument("--model", default=None)
    asyncio.run(main(parser.parse_args().model))
