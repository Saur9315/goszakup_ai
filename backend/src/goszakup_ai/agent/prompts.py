from __future__ import annotations

from goszakup_ai.agent.schemas import Fact, ResolvedParams, ToolResult

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
    question: str, p: ResolvedParams, results: list[ToolResult], facts: list[Fact]
) -> str:
    limitations = sorted({lim for r in results for lim in r.limitations})
    return (
        f"Вопрос: {question}\n\n"
        f"Параметры:\n{params_block(p)}\n\n"
        f"Инструменты: {'; '.join(r.title for r in results)}\n\n"
        f"Факты (id | показатель | значение):\n{facts_block(facts)}\n\n"
        f"Ограничения:\n" + ("\n".join(f"- {x}" for x in limitations) or "- нет")
    )
