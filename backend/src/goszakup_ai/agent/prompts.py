from __future__ import annotations

from goszakup_ai.agent.schemas import Fact, Language, ResolvedParams, ToolResult, Turn

PROMPT_VERSION = "2026-10-14.3"
HISTORY_TURNS = 3

UNDERSTAND_SYSTEM = """\
Ты разбираешь вопросы о государственных закупках Республики Казахстан (портал goszakup.gov.kz).
В базе — закупки 27 организаций-заказчиков за 2024–2026 годы и договоры других заказчиков РК
для сравнения цен. Вопрос может быть на русском или казахском языке.

Определи язык, тип вопроса и параметры:
- если вопрос упоминает организацию по названию или сокращению, верни её БИН из списка ниже;
  БИН не из списка возвращай только если он явно написан в вопросе; никогда не придумывай БИН;
- товары, работы, услуги верни по-русски, коротко, в именительном падеже
  («дизельное топливо», «говядина», «ноутбук»); казахские названия переведи на русский;
- номера лотов возвращай как в вопросе (например 54949500-ЗЦП4);
- порог отклонения — в процентах (например 30).

Если вопрос продолжает диалог («а за 2024 год?», «а у ЦКБ?», «покажи подробнее»),
возьми недостающие параметры (тип вопроса, организации, товары, лоты, годы) из предыдущих
вопросов диалога ниже.

Организации выборки (БИН — название):
{orgs}
"""

COMPOSE_SYSTEM = """\
Ты аналитик государственных закупок. Отвечай на {language} языке.

Правила:
- опирайся только на факты из таблицы; не домысливай и не используй общие фразы;
- каждое число, сумму, процент, количество и дату бери только из таблицы фактов и пиши
  либо точно в том виде, как в колонке «значение», либо ссылкой {{f3}} на месте числа;
  не вычисляй новые числа (разности, доли, суммы) и не ставь ссылки-сноски в конце фраз;
- verdict — 1–3 предложения: прямой ответ на вопрос с ключевыми цифрами;
- analysis — 2–5 коротких пунктов: с чем сравнивали, средние и медианы, найденные отклонения,
  размер выборки; без повторения вердикта.
"""

LANGUAGE_NAMES = {"ru": "русском", "kk": "казахском"}


def orgs_block(orgs: list[tuple[str, str]]) -> str:
    return "\n".join(f"{b} — {name}" for b, name in orgs)


def params_block(p: ResolvedParams) -> str:
    lines = [f"Тип вопроса: {p.intent}", f"Годы: {', '.join(map(str, p.years))}"]
    if p.customer_names:
        lines.append("Заказчики: " + "; ".join(f"{n} ({b})" for b, n in p.customer_names.items()))
    if p.enstru_codes:
        lines.append(
            "ЕНС ТРУ: " + "; ".join(f"{c} {p.enstru_names.get(c, '')}" for c in p.enstru_codes)
        )
    if p.lot_numbers:
        lines.append("Лоты: " + ", ".join(p.lot_numbers))
    if p.region_name:
        lines.append(f"Регион: {p.region_name}")
    lines.extend(f"Примечание: {n}" for n in p.notes)
    return "\n".join(lines)


def facts_block(facts: list[Fact]) -> str:
    return "\n".join(f"{{{f.id}}} | {f.label} | {f.display}" for f in facts)


def compose_user(
    question: str,
    p: ResolvedParams,
    results: list[ToolResult],
    facts: list[Fact],
    previous_question: str | None = None,
) -> str:
    limitations = sorted({lim for r in results for lim in r.limitations})
    context = (
        f"Это продолжение диалога, предыдущий вопрос: «{previous_question}». "
        "Ответь на тот же показатель для новых условий.\n"
        if previous_question
        else ""
    )
    return (
        f"{context}Вопрос: {question}\n\n"
        f"Параметры:\n{params_block(p)}\n\n"
        f"Инструменты: {'; '.join(r.title for r in results)}\n\n"
        f"Факты (id | показатель | значение):\n{facts_block(facts)}\n\n"
        f"Ограничения:\n" + ("\n".join(f"- {x}" for x in limitations) or "- нет")
    )


def history_block(history: list[Turn]) -> str:
    if not history:
        return ""
    lines = ["Предыдущие вопросы диалога (от старых к новым):"]
    for t in history[-HISTORY_TURNS:]:
        parts = [f"тип={t.intent}"]
        if t.customer_bins:
            parts.append(f"БИН={','.join(t.customer_bins)}")
        if t.items:
            parts.append(f"товары={','.join(t.items)}")
        if t.lot_numbers:
            parts.append(f"лоты={','.join(t.lot_numbers)}")
        if t.years:
            parts.append(f"годы={','.join(map(str, t.years))}")
        if t.region:
            parts.append(f"регион={t.region}")
        lines.append(f"- «{t.question}» ({'; '.join(parts)}) → {t.answer[:200]}")
    return "\n".join(lines)


CLARIFICATIONS: dict[str, dict[Language, str]] = {
    "out_of_scope": {
        "ru": "Я отвечаю на вопросы о государственных закупках 27 организаций за 2024–2026 годы: "
        "поиск и сравнение закупок, аналитика, аномалии цен и объёмов, справедливость цены лота.",
        "kk": "Мен 2024–2026 жылдардағы 27 ұйымның мемлекеттік сатып алулары туралы сұрақтарға "
        "жауап беремін: іздеу және салыстыру, талдау, баға мен көлем ауытқулары, лот бағасының "
        "әділдігі.",
    },
    "need_lot": {
        "ru": "Для оценки справедливости цены нужен номер лота (например, 54949500-ЗЦП4).",
        "kk": "Бағаның әділдігін бағалау үшін лот нөмірі қажет (мысалы, 54949500-ЗЦП4).",
    },
    "suggest_lots": {
        "ru": "Возможно, подойдёт один из лотов:",
        "kk": "Мүмкін, мына лоттардың бірі сәйкес келеді:",
    },
    "unknown_item": {
        "ru": "Не нашёл в данных товар или услугу «{items}». Уточните название, например как в "
        "объявлении о закупке.",
        "kk": "Деректерден «{items}» тауарын немесе қызметін таппадым. Атауын нақтылаңыз.",
    },
}
