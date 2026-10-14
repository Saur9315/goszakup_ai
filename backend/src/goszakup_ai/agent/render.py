from __future__ import annotations

from datetime import datetime

from goszakup_ai.agent.formatting import fmt_date, fmt_number
from goszakup_ai.agent.schemas import Language, ResolvedParams, ToolResult, Verification

HEADINGS: dict[Language, dict[str, str]] = {
    "ru": {
        "verdict": "Краткий вывод",
        "data": "Использованные данные",
        "analysis": "Сравнение и аналитика",
        "method": "Метод оценки",
        "confidence": "Уверенность и ограничения",
        "examples": "Примеры (Top-K)",
    },
    "kk": {
        "verdict": "Қысқаша қорытынды",
        "data": "Пайдаланылған деректер",
        "analysis": "Салыстыру және талдау",
        "method": "Бағалау әдісі",
        "confidence": "Сенімділік және шектеулер",
        "examples": "Мысалдар (Top-K)",
    },
}

KEY_FACTS_PER_TOOL = 8

LABELS: dict[Language, dict[str, str]] = {
    "ru": {
        "period": "Период (финансовые годы)",
        "customers": "Заказчики",
        "all_customers": "все 27 организаций выборки",
        "goods": "ТРУ (ЕНС ТРУ)",
        "lots": "Лоты",
        "region": "Регион",
        "source": "Источник",
        "as_of": "данные на",
        "note": "Примечание",
        "key_facts": "ключевые показатели",
    },
    "kk": {
        "period": "Кезең (қаржы жылдары)",
        "customers": "Тапсырыс берушілер",
        "all_customers": "іріктеудегі барлық 27 ұйым",
        "goods": "ТЖҚ (ЕНС ТРУ)",
        "lots": "Лоттар",
        "region": "Өңір",
        "source": "Дереккөз",
        "as_of": "деректер",
        "note": "Ескертпе",
        "key_facts": "негізгі көрсеткіштер",
    },
}


def _confidence(results: list[ToolResult]) -> str:
    explicit = [r for r in results if r.confidence_label]
    if explicit:
        return "; ".join(
            f"{r.title}: {r.confidence_label} ({fmt_number(r.confidence, 2)})" for r in explicit
        )
    n = sum(r.sample_size or 0 for r in results)
    label = "high" if n >= 30 else "medium" if n >= 10 else "low"
    return f"{label} — по объёму выборки N = {fmt_number(n)}"


def _table(r: ToolResult) -> list[str]:
    if not r.items:
        return ["_Нет записей._"]
    headers = [h for _, h in r.columns]
    lines = ["| # | " + " | ".join(headers) + " |", "|---|" + "---|" * len(headers)]
    for i, item in enumerate(r.items, 1):
        cells = []
        for key, _ in r.columns:
            value = item.get(key)
            if key == "link":
                cells.append(f"[открыть]({value})" if value else "—")
            else:
                cells.append(str(value if value not in (None, "") else "—").replace("|", "/"))
        lines.append(f"| {i} | " + " | ".join(cells) + " |")
    return lines


def render(
    language: Language,
    p: ResolvedParams,
    results: list[ToolResult],
    verdict: str,
    analysis: list[str],
    verification: Verification,
    data_as_of: datetime | None,
    dq_notes: list[str],
) -> str:
    h, lb = HEADINGS[language], LABELS[language]
    out = [f"## {h['verdict']}", verdict, "", f"## {h['data']}"]
    out.append(f"- {lb['period']}: {', '.join(map(str, p.years))}")
    if p.customer_names:
        orgs = "; ".join(f"{n} (БИН {b})" for b, n in p.customer_names.items())
        out.append(f"- {lb['customers']}: {orgs}")
    elif p.intent != "fair_price":
        out.append(f"- {lb['customers']}: {lb['all_customers']}")
    if p.enstru_codes:
        codes = "; ".join(f"{c} {p.enstru_names.get(c, '')}".strip() for c in p.enstru_codes)
        out.append(f"- {lb['goods']}: {codes}")
    if p.lot_numbers:
        out.append(f"- {lb['lots']}: {', '.join(p.lot_numbers)}")
    if p.region_name:
        out.append(f"- {lb['region']}: {p.region_name}")
    if p.intent == "price_anomaly":
        out.append(f"- Порог отклонения от средневзвешенной: {fmt_number(p.threshold * 100)}%")
    elif p.intent == "volume_anomaly":
        min_ratio = 1 + p.threshold if p.threshold > 0.3 else 1.5
        out.append(f"- Минимальный рост количества к базе: ×{fmt_number(min_ratio, 2)}")
    out.append(
        f"- {lb['source']}: OWS v3 goszakup.gov.kz"
        + (f", {lb['as_of']} {fmt_date(data_as_of)} {data_as_of:%H:%M}" if data_as_of else "")
    )
    out.extend(f"- {lb['note']}: {n}" for n in p.notes)

    out += ["", f"## {h['analysis']}", *[f"- {a}" for a in analysis]]
    for r in results:
        if r.facts:
            out.append(f"\n**{r.title} — {lb['key_facts']}**")
            out.extend(f"- {f.label}: {f.display}" for f in r.facts[:KEY_FACTS_PER_TOOL])

    out += ["", f"## {h['method']}"]
    out.extend(f"- **{r.title}.** {r.method}" for r in results if r.method)

    out += ["", f"## {h['confidence']}", f"- Уверенность: {_confidence(results)}"]
    for r in results:
        if r.sample_size is not None:
            out.append(f"- {r.title}: объектов в анализе N = {fmt_number(r.sample_size)}")
    limitations = list(dict.fromkeys(lim for r in results for lim in r.limitations))
    out.extend(f"- Ограничение: {lim}" for lim in limitations)
    out.extend(f"- Качество данных: {n}" for n in dq_notes)
    out.append(
        f"- Проверка цифр: {verification.numbers_grounded} из {verification.numbers_total} чисел "
        "в тексте вывода подтверждены результатами инструментов"
    )

    out += ["", f"## {h['examples']}"]
    for r in results:
        out += [f"**{r.title}**", "", *_table(r), ""]
    return "\n".join(out).strip() + "\n"
